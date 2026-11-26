import json
import math
from numbers import Real
from pathlib import Path
import time
from typing import NamedTuple

import numpy as np

from sportscut import media, reframe


class Label(NamedTuple):
    t: float
    ball: tuple[float, float] | None
    players: tuple[tuple[float, float, float, float], ...]


def _finite_number(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, Real)
        and math.isfinite(value)
    )


def load_labels(path) -> list[Label]:
    label_path = Path(path)
    try:
        data = json.loads(label_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label_path}: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"{label_path}: top level must be a list")
    if not data:
        raise ValueError(f"{label_path}: no labels")

    labels = []
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            raise ValueError(f"{label_path}: [{index}] must be an object")
        t = entry.get("t")
        if not _finite_number(t) or t < 0:
            raise ValueError(
                f"{label_path}: [{index}].t must be a non-negative number"
            )

        ball = entry.get("ball") if "ball" in entry else ...
        if ball is not None and not (
            isinstance(ball, list)
            and len(ball) == 2
            and all(_finite_number(value) for value in ball)
        ):
            raise ValueError(
                f"{label_path}: [{index}].ball must be null or [x, y]"
            )

        players = entry.get("players", [])
        valid_players = isinstance(players, list) and all(
            isinstance(box, list)
            and len(box) == 4
            and all(_finite_number(value) for value in box)
            and box[2] > 0
            and box[3] > 0
            for box in players
        )
        if not valid_players:
            raise ValueError(
                f"{label_path}: [{index}].players must be a list of "
                "[x, y, w, h] with w, h > 0"
            )
        labels.append(Label(
            float(t),
            None if ball is None else (float(ball[0]), float(ball[1])),
            tuple(tuple(float(value) for value in box) for box in players),
        ))
    return sorted(labels, key=lambda item: item.t)


def validate_plan(plan, width: int, cw: int, where: str) -> None:
    prefix = f"plan_crop returned an invalid plan for {where}: "
    if plan is None or isinstance(plan, (str, bytes)):
        raise ValueError(prefix + "not (t, x) pairs")
    try:
        if len(plan) == 0:
            raise ValueError(prefix + "empty")
    except TypeError:
        raise ValueError(prefix + "not (t, x) pairs") from None

    parsed = []
    for item in plan:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError(prefix + "not (t, x) pairs")
        t, x = item
        if not _finite_number(t) or not _finite_number(x):
            raise ValueError(prefix + "not (t, x) pairs")
        parsed.append((float(t), float(x)))
    if any(current <= previous for (previous, _), (current, _) in zip(parsed, parsed[1:])):
        raise ValueError(prefix + "t not strictly increasing")
    lower = cw / 2 - 1e-6
    upper = width - cw / 2 + 1e-6
    if any(x < lower or x > upper for _, x in parsed):
        raise ValueError(prefix + "x outside the frame")


def score_clip(
    labels: list[Label], plan, width: int, cw: int, duration: float
) -> dict:
    ts, xs = zip(*plan)
    counts = {
        "ball_hits": 0,
        "ball_total": 0,
        "player_hits": 0,
        "player_total": 0,
    }
    for item in labels:
        center = float(np.interp(item.t, ts, xs))
        left = center - cw / 2 - 1e-9
        right = center + cw / 2 + 1e-9
        if item.ball is not None:
            counts["ball_total"] += 1
            counts["ball_hits"] += left <= item.ball[0] <= right
        for x, _y, box_width, _height in item.players:
            counts["player_total"] += 1
            counts["player_hits"] += left <= x + box_width / 2 <= right

    grid = reframe.sample_times(duration)
    centers = np.interp(grid, ts, xs)
    jerk = np.abs(np.diff(centers, 2)) / width
    counts["jerk_sum"] = float(jerk.sum())
    counts["jerk_n"] = len(jerk)
    return counts


def metrics(counts: dict, seconds: float, minutes: float) -> dict:
    return {
        "ball_in_crop": (
            round(counts["ball_hits"] / counts["ball_total"], 4)
            if counts["ball_total"] else None
        ),
        "players_in_crop": (
            round(counts["player_hits"] / counts["player_total"], 4)
            if counts["player_total"] else None
        ),
        "jitter": (
            round(counts["jerk_sum"] / counts["jerk_n"], 6)
            if counts["jerk_n"] else 0.0
        ),
        "seconds_per_min": round(seconds / minutes, 4) if minutes else 0.0,
    }


def evaluate_dir(path) -> dict:
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    case_dirs = sorted(
        item for item in root.iterdir()
        if item.is_dir() and (item / "labels.json").is_file()
    )
    if not case_dirs:
        raise ValueError(f"no eval-crop cases found in {root}")

    prepared = []
    for case_dir in case_dirs:
        clip = case_dir / "clip.mp4"
        if not clip.is_file():
            raise ValueError(
                f"missing {clip}; run python tests/fixtures/eval_crop/build.py "
                "for the synthetic set"
            )
        labels = load_labels(case_dir / "labels.json")
        prepared.append((case_dir, clip, labels))

    count_keys = (
        "ball_hits", "ball_total", "player_hits", "player_total",
        "jerk_sum", "jerk_n",
    )
    totals = {key: 0 for key in count_keys}
    total_seconds = 0.0
    total_minutes = 0.0
    per_clip = []
    for case_dir, clip, labels in prepared:
        width, height = media.probe_size(clip)
        duration = media.probe_duration(clip)
        cw = reframe.crop_width(width, height)
        started = time.perf_counter()
        plan = reframe.plan_crop(clip)
        seconds = time.perf_counter() - started
        validate_plan(plan, width, cw, case_dir.name)
        counts = score_clip(labels, plan, width, cw, duration)
        for key in count_keys:
            totals[key] += counts[key]
        minutes = duration / 60
        total_seconds += seconds
        total_minutes += minutes
        per_clip.append({
            "clip": case_dir.name,
            "duration": round(duration, 4),
            "labels": len(labels),
            "ball_labels": sum(item.ball is not None for item in labels),
            "player_boxes": sum(len(item.players) for item in labels),
            **metrics(counts, seconds, minutes),
        })
    return {
        **metrics(totals, total_seconds, total_minutes),
        "per_clip": per_clip,
    }
