import json
import math
from pathlib import Path
from collections.abc import Sequence
import time

from sportscut import media, player


TOLERANCE = 0.5


def match_times(pred: Sequence[float], truth: Sequence[float], tol: float = TOLERANCE) -> list[tuple[int, int]]:
    pred_indices = sorted(range(len(pred)), key=lambda index: pred[index])
    truth_indices = sorted(range(len(truth)), key=lambda index: truth[index])
    pairs = []
    i = j = 0
    while i < len(pred_indices) and j < len(truth_indices):
        pi, ti = pred_indices[i], truth_indices[j]
        if abs(pred[pi] - truth[ti]) <= tol + 1e-9:
            pairs.append((pi, ti))
            i += 1
            j += 1
        elif pred[pi] < truth[ti]:
            i += 1
        else:
            j += 1
    return pairs


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def score_clip(touches, queries, detected: list[player.Touch], found: dict[player.PlayerQuery, list[player.Touch]]) -> dict:
    pairs = match_times([item.t for item in detected], [time for time, _ in touches])
    counts = {
        "tp": 0, "fp": 0, "fn": 0,
        "any_tp": len(pairs), "any_fp": len(detected) - len(pairs), "any_fn": len(touches) - len(pairs),
        "team_hits": 0, "id_hits": 0,
    }
    for detected_index, label_index in pairs:
        touch, query = detected[detected_index], touches[label_index][1]
        counts["team_hits"] += touch.team == query.team
        counts["id_hits"] += touch.team == query.team and touch.number == query.number
    for query in queries:
        truth = [time for time, author in touches if author == query]
        predicted = found[query]
        matched = len(match_times([item.t for item in predicted], truth))
        counts["tp"] += matched
        counts["fp"] += len(predicted) - matched
        counts["fn"] += len(truth) - matched
    return counts


def metrics(counts: dict, seconds: float, query_minutes: float) -> dict:
    precision, recall, f1 = prf(counts["tp"], counts["fp"], counts["fn"])
    _, _, any_f1 = prf(counts["any_tp"], counts["any_fp"], counts["any_fn"])
    any_tp = counts["any_tp"]
    rounded = lambda value: round(value, 4)
    return {
        "f1": rounded(f1), "precision": rounded(precision), "recall": rounded(recall),
        "touch_f1_any": rounded(any_f1),
        "team_accuracy": rounded(counts["team_hits"] / any_tp) if any_tp else None,
        "id_accuracy": rounded(counts["id_hits"] / any_tp) if any_tp else None,
        "seconds_per_min": rounded(seconds / query_minutes) if query_minutes else 0.0,
    }


def load_labels(path) -> tuple[list[tuple[float, player.PlayerQuery]], list[player.PlayerQuery]]:
    label_path = Path(path)
    try:
        data = json.loads(label_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{label_path}: top level must be an object")
    if "touches" not in data or not isinstance(data["touches"], list):
        raise ValueError(f"{label_path}: touches must be a list")
    if "players" in data and not isinstance(data["players"], list):
        raise ValueError(f"{label_path}: players must be a list")

    touches: list[tuple[float, player.PlayerQuery]] = []
    queries: set[player.PlayerQuery] = set()
    for field in ("players", "touches"):
        for index, entry in enumerate(data.get(field, [])):
            location = f"{field}[{index}]"
            if not isinstance(entry, dict):
                raise ValueError(f"{label_path}: {location} must be an object")
            if field == "touches":
                value = entry.get("t")
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or value < 0):
                    raise ValueError(f"{label_path}: {location}.t must be a non-negative number")
            try:
                query = player.PlayerQuery(entry.get("team"), entry.get("number"))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{label_path}: {location}: {exc}") from exc
            queries.add(query)
            if field == "touches":
                touches.append((float(value), query))
    return sorted(touches, key=lambda item: item[0]), sorted(queries, key=lambda q: (q.team, q.number))


def evaluate_dir(path, debug: bool = False) -> dict:
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    case_dirs = sorted(item for item in root.iterdir() if item.is_dir() and (item / "labels.json").is_file())
    if not case_dirs:
        raise ValueError(f"no eval-player cases found in {root}")
    prepared = []
    for case_dir in case_dirs:
        clip = case_dir / "clip.mp4"
        if not clip.is_file():
            raise ValueError(f"missing {clip}; run python tests/fixtures/eval_player/build.py for the synthetic set")
        touches, queries = load_labels(case_dir / "labels.json")
        prepared.append((case_dir, clip, touches, queries))

    count_keys = ("tp", "fp", "fn", "any_tp", "any_fp", "any_fn", "team_hits", "id_hits")
    totals = {key: 0 for key in count_keys}
    total_seconds = total_minutes = 0.0
    per_clip = []
    for case_dir, clip, touches, queries in prepared:
        duration = media.probe_duration(clip)
        detected = player.detect_touches(clip)
        found = {}
        seconds = 0.0
        for query in queries:
            started = time.perf_counter()
            found[query] = player.find_touches(clip, query)
            seconds += time.perf_counter() - started
        query_minutes = duration * len(queries) / 60
        counts = score_clip(touches, queries, detected, found)
        for key in count_keys:
            totals[key] += counts[key]
        total_seconds += seconds
        total_minutes += query_minutes
        entry = {
            "clip": case_dir.name, "duration": round(duration, 4),
            "touches": len(touches), "queries": len(queries),
            **metrics(counts, seconds, query_minutes),
        }
        if debug:
            entry["candidates"] = [touch.to_dict() for touch in detected]
        per_clip.append(entry)
    return {**metrics(totals, total_seconds, total_minutes), "per_clip": per_clip}
