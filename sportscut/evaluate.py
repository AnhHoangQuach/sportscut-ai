import csv
import json
import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from sportscut import detect
from sportscut.eval_player import prf
from sportscut.events import audio_cues, scoreboard
from sportscut.models import EVENT_TYPES, Segment

LABEL_TYPES = ("goal", "save", "red_card", "controversy", "chance", "yellow_card", "foul", "other")
MIN_IOU = 0.3
VIDEO_SUFFIXES = (".mp4", ".mkv", ".mov")
_TIME = re.compile(r"^(\d+):([0-5]\d)(\.\d+)?$")


class Label(NamedTuple):
    start: float
    end: float
    type: str


def to_event(label_type: str) -> str:
    return label_type if label_type in EVENT_TYPES[:-1] else "other"


def temporal_iou(a_start, a_end, b_start, b_end) -> float:
    overlap = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    return overlap / (max(a_end, b_end) - min(a_start, b_start)) if overlap else 0.0


def match_segments(segments: Sequence[Segment], labels: Sequence[Label]) -> list[tuple[int, int]]:
    candidates = []
    for i, segment in enumerate(segments):
        for j, label in enumerate(labels):
            iou = temporal_iou(segment.start, segment.end, label.start, label.end)
            contained = segment.start <= label.start and label.end <= segment.end
            if iou >= MIN_IOU - 1e-9 or contained:
                candidates.append((-iou, j, i))
    used_segments, used_labels, pairs = set(), set(), []
    for _, j, i in sorted(candidates):
        if i not in used_segments and j not in used_labels:
            used_segments.add(i)
            used_labels.add(j)
            pairs.append((i, j))
    return sorted(pairs, key=lambda pair: pair[1])


def _label(start, end, kind, where: str) -> Label:
    for name, value in (("start", start), ("end", end)):
        try:
            finite = math.isfinite(value)
        except (OverflowError, TypeError):
            finite = False
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not finite:
            raise ValueError(f"{where}: {name} must be a finite number")
    if start < 0:
        raise ValueError(f"{where}: start must be non-negative")
    if end <= start:
        raise ValueError(f"{where}: end must be greater than start")
    if not isinstance(kind, str):
        raise ValueError(f"{where}: type must be a string")
    kind = kind.strip().lower()
    if kind not in LABEL_TYPES:
        raise ValueError(f"{where}: unknown type {kind}")
    return Label(float(start), float(end), kind)


def _parse_time(value: str, where: str) -> float:
    match = _TIME.fullmatch(value)
    if not match:
        raise ValueError(f"{where}: invalid time {value}")
    return int(match[1]) * 60 + float(match[2] + (match[3] or ""))


def load_labels(path: str | Path) -> list[Label]:
    label_path = Path(path)
    if label_path.suffix.lower() == ".json":
        try:
            data = json.loads(label_path.read_text())
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"{label_path}: {exc}") from exc
        if not isinstance(data, list):
            raise ValueError(f"{label_path}: top level must be a list")
        result = []
        for i, item in enumerate(data):
            where = f"{label_path}: [{i}]"
            if not isinstance(item, dict):
                raise ValueError(f"{where}: must be an object")
            result.append(_label(item.get("start"), item.get("end"), item.get("type"), where))
        return result
    if label_path.suffix.lower() != ".csv":
        raise ValueError(f"{label_path}: unsupported label format")
    try:
        rows = list(csv.reader(label_path.read_text().splitlines()))
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"{label_path}: {exc}") from exc
    result, seen_data = [], False
    for number, row in enumerate(rows, 1):
        cells = [cell.strip() for cell in row]
        if not cells or not any(cells) or cells[0].startswith("#"):
            continue
        if not seen_data and cells[0].lower() == "start":
            seen_data = True
            continue
        seen_data = True
        where = f"{label_path}: line {number}"
        if len(cells) != 3:
            raise ValueError(f"{where}: expected 3 columns")
        start, end = _parse_time(cells[0], where), _parse_time(cells[1], where)
        result.append(_label(start, end, cells[2], where))
    return result


def score_case(segments: Sequence[Segment], labels: Sequence[Label]) -> dict:
    pairs = match_segments(segments, labels)
    matched_segments = {i for i, _ in pairs}
    type_hits = sum(segments[i].event == to_event(labels[j].type) for i, j in pairs)
    events = {}
    for event in EVENT_TYPES:
        tp = sum(segments[i].event == event == to_event(labels[j].type) for i, j in pairs)
        events[event] = {"tp": tp, "fp": sum(s.event == event for s in segments) - tp,
                         "fn": sum(to_event(label.type) == event for label in labels) - tp}
    top = sorted(range(len(segments)), key=lambda i: (-segments[i].score, segments[i].start))[:5]
    return {"tp": len(pairs), "fp": len(segments) - len(pairs), "fn": len(labels) - len(pairs),
            "type_hits": type_hits, "p5_hits": sum(i in matched_segments for i in top),
            "p5_total": len(top), "events": events}


def summarize(counts: dict) -> dict:
    precision, recall, f1 = prf(counts["tp"], counts["fp"], counts["fn"])
    rounded = lambda value: round(value, 4)
    per_event = {}
    for event in EVENT_TYPES:
        item = counts["events"][event]
        p = item["tp"] / (item["tp"] + item["fp"]) if item["tp"] + item["fp"] else None
        r = item["tp"] / (item["tp"] + item["fn"]) if item["tp"] + item["fn"] else None
        event_f1 = None if p is None or r is None else (2 * p * r / (p + r) if p + r else 0.0)
        per_event[event] = {"precision": rounded(p) if p is not None else None,
                            "recall": rounded(r) if r is not None else None,
                            "f1": rounded(event_f1) if event_f1 is not None else None}
    return {"f1": rounded(f1), "precision": rounded(precision), "recall": rounded(recall),
            "event_accuracy": rounded(counts["type_hits"] / counts["tp"]) if counts["tp"] else None,
            "per_event": per_event,
            "precision_at_5": rounded(counts["p5_hits"] / counts["p5_total"]) if counts["p5_total"] else 0.0}


def evaluate_dir(path: str | Path) -> dict:
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    prepared = []
    for case in sorted(item for item in root.iterdir() if item.is_dir()):
        label_files = [case / name for name in ("labels.json", "labels.csv") if (case / name).is_file()]
        if len(label_files) > 1:
            raise ValueError(f"{case}: has both labels.json and labels.csv")
        if not label_files:
            continue
        videos = [item for item in case.iterdir()
                  if item.is_file() and not item.name.startswith(".")
                  and item.suffix.lower() in VIDEO_SUFFIXES]
        if len(videos) != 1:
            raise ValueError(f"{case}: expected exactly one video (.mp4, .mkv, .mov), found {len(videos)}")
        prepared.append((case, videos[0], load_labels(label_files[0])))
    if not prepared:
        raise ValueError(f"no eval cases found in {root}")
    totals = {"tp": 0, "fp": 0, "fn": 0, "type_hits": 0, "p5_hits": 0, "p5_total": 0,
              "events": {event: {"tp": 0, "fp": 0, "fn": 0} for event in EVENT_TYPES}}
    per_match = []
    for case, video, labels in prepared:
        segments = audio_cues.tag_saves(
            video, scoreboard.tag_goals(video, detect.find_highlights(video))
        )
        counts = score_case(segments, labels)
        for key in ("tp", "fp", "fn", "type_hits", "p5_hits", "p5_total"):
            totals[key] += counts[key]
        for event in EVENT_TYPES:
            for key in ("tp", "fp", "fn"):
                totals["events"][event][key] += counts["events"][event][key]
        metrics = summarize(counts)
        per_match.append({"match": case.name, "labels": len(labels), "predictions": len(segments),
                          **{key: metrics[key] for key in ("f1", "precision", "recall", "event_accuracy", "precision_at_5")}})
    return {**summarize(totals), "per_match": per_match}
