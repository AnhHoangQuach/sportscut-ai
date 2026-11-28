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
REVERT_MAX = 180.0
REVERT_FRAC = 0.01
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
MAX_BOARD_W = 80  # half of media.BAND_W (160): real boards sit in a corner
MAX_CHANGES = 4  # a board may change at most max(4, seconds/600) times
SECONDS_PER_CHANGE = 600  # assumption: <= ~1 real score change per 10 minutes
BUSY_FRAC = 0.25  # flipping in > 25% of samples is a clock/pan, not a score
GOAL_BEFORE = 12.0  # goal clip: build-up and shot before the roar onset
GOAL_AFTER = 10.0  # ... and the celebration after it

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


def _flips(frames: np.ndarray, box: Box) -> np.ndarray:
    """Per-sample share of box pixels that changed by >= FLIP_DIFF; flips[0] == 0."""
    x, y, width, height = box
    board = frames[:, y : y + height, x : x + width].astype(np.int16)
    flips = np.zeros(len(board), dtype=np.float64)
    if len(board) > 1:
        flips[1:] = np.mean(np.abs(board[1:] - board[:-1]) >= FLIP_DIFF, axis=(1, 2))
    return flips


def plausible_board(frames: np.ndarray, box: Box, changes: list[float]) -> bool:
    """False when the box is too wide, changes too often, or never settles."""
    if box[2] > MAX_BOARD_W:
        return False
    if len(changes) > max(MAX_CHANGES, len(frames) / SECONDS_PER_CHANGE):
        return False
    flips = _flips(frames, box)
    busy = float(np.mean(flips[1:] >= CHANGE_FRAC)) if len(flips) > 1 else 0.0
    return busy <= BUSY_FRAC


def score_changes(frames: np.ndarray, box: Box) -> list[float]:
    """Return stable scoreboard state changes, timed at each transition start."""
    x, y, width, height = box
    board = frames[:, y : y + height, x : x + width].astype(np.int16)
    flips = _flips(frames, box)

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


def _board(video: str | Path) -> tuple[np.ndarray, Box, list[float]] | None:
    """Sample the band once; return (frames, box, changes) for a plausible board."""
    frames = sample_top_band(video)
    box = find_box(frames)
    if box is None:
        return None
    changes = score_changes(frames, box)
    if not plausible_board(frames, box, changes):
        return None
    return frames, box, changes


def board_changes(video: str | Path) -> list[float] | None:
    """Return scoreboard change times, or None when no plausible board is visible."""
    board = _board(video)
    return None if board is None else board[2]


def find_reverts(
    frames: np.ndarray, box: Box, changes: list[float]
) -> list[tuple[float, float]]:
    """Return adjacent scoreboard changes that restore the earlier state."""
    if len(changes) < 2:
        return []
    x, y, width, height = box
    board = frames[:, y : y + height, x : x + width].astype(np.int16)
    reverts = []
    ordered = sorted(changes)
    for first, second in zip(ordered, ordered[1:]):
        if second - first > REVERT_MAX:
            continue
        before = board[int(first) - 1]
        after = board[min(int(second) + STABLE_SAMPLES, len(board) - 1)]
        changed = np.mean(np.abs(after - before) >= FLIP_DIFF)
        if changed < REVERT_FRAC:
            reverts.append((first, second))
    return reverts


def board_reverts(video: str | Path) -> list[tuple[float, float]]:
    """Return scoreboard change pairs that restore the earlier state."""
    board = _board(video)
    return [] if board is None else find_reverts(*board)


def _roar_bounds(
    residual: np.ndarray, start: float, end: float
) -> tuple[float, int, int]:
    """Return (peak time, left, right) of the sustained run around the segment's loudest second; left == right when there is no run."""
    first = max(0, math.floor(start))
    stop = min(len(residual), math.ceil(end))
    if first >= stop:
        return float(start), 0, 0
    peak = first + int(np.argmax(residual[first:stop]))
    if residual[peak] < ROAR_DB:
        return peak + 0.5, peak, peak
    left = peak
    while left > 0 and residual[left - 1] >= ROAR_DB:
        left -= 1
    right = peak + 1
    while right < len(residual) and residual[right] >= ROAR_DB:
        right += 1
    return peak + 0.5, left, right


def roar(residual: np.ndarray, start: float, end: float) -> tuple[float, int]:
    """Find the peak second and sustained-above-baseline run around it."""
    peak, left, right = _roar_bounds(residual, start, end)
    return peak, right - left


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
    tagged = match_goals(
        list(segments), residual, changes, duration, min_len, max_len
    )
    return shape_goals(tagged, residual, duration, min_len, max_len)


def _by_time(segment: Segment) -> tuple[float, float]:
    return segment.start, segment.end


def _merge(group: list[Segment]) -> Segment:
    base = max(
        sorted(group, key=_by_time),
        key=lambda s: -math.inf if s.score is None else s.score,
    )
    return replace(
        base,
        start=min(s.start for s in group),
        end=max(s.end for s in group),
        event_confidence=max(s.event_confidence for s in group),
    )


def shape_goals(
    segments: list[Segment],
    residual: np.ndarray,
    duration: float,
    min_len: float = 10,
    max_len: float = 30,
) -> list[Segment]:
    """Give roar goals a build-up-to-celebration window, merge overlapping goals, drop non-goals they cover."""
    length = min(max(GOAL_BEFORE + GOAL_AFTER, min_len), max_len)
    before = length * GOAL_BEFORE / (GOAL_BEFORE + GOAL_AFTER)
    goals, others = [], []
    for segment in segments:
        if segment.event != "goal":
            others.append(segment)
            continue
        if segment.event_confidence != CONF_BOARD_ONLY:
            _peak, left, right = _roar_bounds(residual, segment.start, segment.end)
            if right - left >= ROAR_SEC:
                start, end = place_window(float(left), length, duration, before)
                segment = replace(segment, start=start, end=end)
        goals.append(segment)

    groups: list[list[Segment]] = []
    for goal in sorted(goals, key=_by_time):
        if groups and goal.start < max(s.end for s in groups[-1]):
            groups[-1].append(goal)
        else:
            groups.append([goal])
    merged = [group[0] if len(group) == 1 else _merge(group) for group in groups]

    kept = [
        s
        for s in others
        if not any(s.start < g.end and g.start < s.end for g in merged)
    ]
    return sorted(merged + kept, key=_by_time)
