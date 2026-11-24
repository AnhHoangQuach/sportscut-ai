"""Goal classification from scoreboard changes and sustained crowd roar."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import numpy as np

from sportscut.detect import loudness_residual, place_window
from sportscut.media import extract_audio, probe_duration, sample_top_band
from sportscut.models import Segment

EDGE_MIN = 40
MOTION_MAX = 2
DILATE = 2
MIN_BOARD_PIXELS = 12
FLIP_DIFF = 40
CHANGE_FRAC = 0.03
STABLE_SAMPLES = 3
ROAR_DB = 6.0
ROAR_SEC = 6
MATCH_BEFORE = 10.0
MATCH_AFTER = 60.0
LEAD_CENTER = 45.0
LEAD_LEN = 30.0
BOARD_ONLY_SCORE = 3.0
CONF_BOARD = 0.9
CONF_BOARD_ONLY = 0.6
CONF_ROAR_ONLY = 0.4

Box = tuple[int, int, int, int]


def _dilate(mask: np.ndarray) -> np.ndarray:
    padded = np.pad(mask, DILATE)
    result = np.zeros_like(mask)
    height, width = mask.shape
    for dy in range(2 * DILATE + 1):
        for dx in range(2 * DILATE + 1):
            result |= padded[dy : dy + height, dx : dx + width]
    return result


def find_box(frames: np.ndarray) -> Box | None:
    """Find the static high-edge component most likely to be a scoreboard."""
    if len(frames) < 2:
        return None
    values = frames.astype(np.int16)
    motion = np.median(np.abs(values[1:] - values[:-1]), axis=0)
    static = motion <= MOTION_MAX
    ref = np.median(values, axis=0)
    edge = np.zeros(ref.shape, dtype=ref.dtype)
    edge[:, :-1] = np.abs(ref[:, 1:] - ref[:, :-1])
    edge[:-1] = np.maximum(edge[:-1], np.abs(ref[1:] - ref[:-1]))
    mask = static & (edge >= EDGE_MIN)
    dilated = _dilate(mask)

    height, width = mask.shape
    seen = np.zeros_like(mask)
    best_pixels: list[tuple[int, int]] = []
    for first_y, first_x in np.argwhere(dilated):
        if seen[first_y, first_x]:
            continue
        stack = [(int(first_y), int(first_x))]
        seen[first_y, first_x] = True
        original: list[tuple[int, int]] = []
        while stack:
            y, x = stack.pop()
            if mask[y, x]:
                original.append((y, x))
            for ny in range(max(0, y - 1), min(height, y + 2)):
                for nx in range(max(0, x - 1), min(width, x + 2)):
                    if dilated[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        if len(original) > len(best_pixels):
            best_pixels = original

    if len(best_pixels) < MIN_BOARD_PIXELS:
        return None
    ys, xs = zip(*best_pixels)
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    return left, top, right - left + 1, bottom - top + 1


def score_changes(frames: np.ndarray, box: Box) -> list[float]:
    """Return stable scoreboard state changes, timed at each transition start."""
    x, y, width, height = box
    board = frames[:, y : y + height, x : x + width].astype(np.int16)
    flips = np.zeros(len(board), dtype=np.float64)
    if len(board) > 1:
        flips[1:] = np.mean(np.abs(board[1:] - board[:-1]) >= FLIP_DIFF, axis=(1, 2))

    changes = []
    sample = 1
    while sample < len(board):
        if flips[sample] < CHANGE_FRAC:
            sample += 1
            continue
        start = sample
        end = start
        while end + 1 < len(board) and flips[end + 1] >= CHANGE_FRAC:
            end += 1
        stable_end = end + STABLE_SAMPLES
        stable = (
            stable_end < len(board)
            and np.all(flips[end + 1 : stable_end + 1] < CHANGE_FRAC)
        )
        if stable:
            lasting = np.mean(
                np.abs(board[stable_end] - board[start - 1]) >= FLIP_DIFF
            )
            if lasting >= CHANGE_FRAC:
                changes.append(float(start))
        sample = end + 1
    return changes


def board_changes(video: str | Path) -> list[float] | None:
    """Return scoreboard change times, or None when no board is visible."""
    frames = sample_top_band(video)
    box = find_box(frames)
    return None if box is None else score_changes(frames, box)


def roar(residual: np.ndarray, start: float, end: float) -> tuple[float, int]:
    """Find the peak second and sustained-above-baseline run around it."""
    first = max(0, math.floor(start))
    stop = min(len(residual), math.ceil(end))
    if first >= stop:
        return float(start), 0
    peak = first + int(np.argmax(residual[first:stop]))
    if residual[peak] < ROAR_DB:
        return peak + 0.5, 0
    left = peak
    while left > 0 and residual[left - 1] >= ROAR_DB:
        left -= 1
    right = peak + 1
    while right < len(residual) and residual[right] >= ROAR_DB:
        right += 1
    return peak + 0.5, right - left


def match_goals(
    segments: list[Segment],
    residual: np.ndarray,
    changes: list[float] | None,
    duration: float,
    min_len: float = 10,
    max_len: float = 30,
) -> list[Segment]:
    """Match sustained-roar candidates to scoreboard changes."""
    result = list(segments)
    qualified: dict[int, tuple[float, int]] = {}
    for index, segment in enumerate(segments):
        if segment.event != "other":
            continue
        peak, run = roar(residual, segment.start, segment.end)
        if run >= ROAR_SEC:
            qualified[index] = (peak, run)

    if changes is None:
        for index, (_peak, run) in qualified.items():
            segment = segments[index]
            result[index] = replace(
                segment,
                event="goal",
                event_confidence=CONF_ROAR_ONLY,
                reason=f"{segment.reason}; sustained roar {run}s",
            )
        return sorted(result, key=lambda segment: (segment.start, segment.end))

    pairs = []
    for index, (peak, _run) in qualified.items():
        for change in changes:
            if peak - MATCH_BEFORE <= change <= peak + MATCH_AFTER:
                pairs.append((abs(change - peak), change, index))
    used_segments: set[int] = set()
    used_changes: set[float] = set()
    matches: dict[int, float] = {}
    for _distance, change, index in sorted(pairs):
        if index in used_segments or change in used_changes:
            continue
        used_segments.add(index)
        used_changes.add(change)
        matches[index] = change

    for index, change in matches.items():
        segment = segments[index]
        result[index] = replace(
            segment,
            event="goal",
            event_confidence=CONF_BOARD,
            reason=f"{segment.reason}; scoreboard change at {change:.0f}s",
        )

    length = min(max(LEAD_LEN, min_len), max_len)
    for change in sorted(changes):
        if change in used_changes:
            continue
        start, end = place_window(
            change - LEAD_CENTER, length, duration, length / 2
        )
        overlaps = any(
            start < segment.end and segment.start < end for segment in result
        )
        if end > start and not overlaps:
            result.append(
                Segment(
                    start,
                    end,
                    BOARD_ONLY_SCORE,
                    f"scoreboard change at {change:.0f}s",
                    "goal",
                    CONF_BOARD_ONLY,
                )
            )
    return sorted(result, key=lambda segment: (segment.start, segment.end))


def tag_goals(
    video: str | Path,
    segments: list[Segment],
    min_len: float = 10,
    max_len: float = 30,
) -> list[Segment]:
    """Load media signals and classify goal segments."""
    duration = probe_duration(video)
    residual = loudness_residual(extract_audio(video))
    changes = board_changes(video)
    return match_goals(
        list(segments), residual, changes, duration, min_len, max_len
    )
