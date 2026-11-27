import math
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from sportscut import media, reframe


KICK_SPAN = 1         # samples before/after used for velocity (tunable 1..3)
TURN_DEG = 20.0       # min direction change, degrees (tunable 10..60)
SPEED_JUMP = 0.75     # min |s_out - s_in| / max(s_in, s_out) (tunable 0.2..0.8)
MIN_SPEED = 0.015     # min speed, fraction of analysis width per second (tunable 0.005..0.05)
REACH = 0.75          # max ball-to-blob gap, times blob bbox height (tunable 0.25..1.0)
BLOB_MIN_AREA = 20    # min eroded pixels of a player blob (tunable 10..40)
TOUCH_NMS = 0.4       # suppression radius in seconds (fixed)

TEAM_NAMES = (
    "black", "blue", "green", "orange", "pink", "purple", "red", "sky", "white", "yellow"
)


def normalize_team(team: str) -> str:
    value = team.strip().lower() if isinstance(team, str) else ""
    if value in TEAM_NAMES or re.fullmatch(r"#[0-9a-f]{6}", value):
        return value
    choices = ", ".join(TEAM_NAMES)
    raise ValueError(f"unknown team colour {team!r}: use one of {choices} or #rrggbb")


@dataclass(frozen=True)
class PlayerQuery:
    team: str
    number: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "team", normalize_team(self.team))
        if type(self.number) is not int or not 1 <= self.number <= 99:
            raise ValueError("player number must be an integer from 1 to 99")


@dataclass(frozen=True)
class Touch:
    t: float
    team: str | None
    number: int | None
    confidence: float
    bbox: tuple[int, int, int, int] | None

    def __post_init__(self) -> None:
        if self.t < 0:
            raise ValueError("touch time must be >= 0")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("touch confidence must be between 0 and 1")
        if self.team is not None:
            object.__setattr__(self, "team", normalize_team(self.team))

    def to_dict(self) -> dict:
        return {
            "t": float(self.t),
            "team": self.team,
            "number": None if self.number is None else int(self.number),
            "confidence": float(self.confidence),
            "bbox": None if self.bbox is None else [int(value) for value in self.bbox],
        }


def player_blobs(frame: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Return (x, y, w, h) boxes of 8-connected player mass in analysis px, sorted by (y, x)."""
    mask = reframe.player_mask(frame)
    if mask is None:
        return []
    h, w = mask.shape
    todo = {(int(r), int(c)) for r, c in np.argwhere(mask)}
    boxes = []
    while todo:
        stack = [todo.pop()]
        r0 = r1 = stack[0][0]
        c0 = c1 = stack[0][1]
        area = 0
        while stack:
            r, c = stack.pop()
            area += 1
            r0, r1, c0, c1 = min(r0, r), max(r1, r), min(c0, c), max(c1, c)
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    nb = (r + dr, c + dc)
                    if nb in todo:
                        todo.remove(nb)
                        stack.append(nb)
        if area >= BLOB_MIN_AREA:
            x0, y0 = max(0, c0 - 1), max(0, r0 - 1)
            x1, y1 = min(w - 1, c1 + 1), min(h - 1, r1 + 1)
            boxes.append((x0, y0, x1 - x0 + 1, y1 - y0 + 1))
    return sorted(boxes, key=lambda box: (box[1], box[0]))


def find_kicks(
    hits: Sequence[tuple[float, float] | None], width: int
) -> list[tuple[int, float]]:
    """Return (sample, strength) where the ball changes direction or speed and moves on."""
    span = KICK_SPAN
    dt = span / reframe.SAMPLE_HZ
    vmin = MIN_SPEED * width
    kicks = []
    for i in range(span, len(hits) - span):
        before, here, after = hits[i - span], hits[i], hits[i + span]
        if before is None or here is None or after is None:
            continue
        vin = ((here[0] - before[0]) / dt, (here[1] - before[1]) / dt)
        vout = ((after[0] - here[0]) / dt, (after[1] - here[1]) / dt)
        s_in, s_out = math.hypot(*vin), math.hypot(*vout)
        if s_out < vmin:
            continue
        jump = abs(s_out - s_in) / max(s_in, s_out)
        turn = 0.0
        if s_in >= vmin:
            cos = (vin[0] * vout[0] + vin[1] * vout[1]) / (s_in * s_out)
            turn = math.degrees(math.acos(min(1.0, max(-1.0, cos))))
        if turn >= TURN_DEG or jump >= SPEED_JUMP:
            kicks.append((i, min(1.0, max(turn / 180, jump))))
    return kicks


def suppress_touches(touches: Sequence[Touch]) -> list[Touch]:
    """Greedy non-maximum suppression by confidence within TOUCH_NMS seconds."""
    kept: list[Touch] = []
    for touch in sorted(touches, key=lambda item: (-item.confidence, item.t)):
        if all(abs(touch.t - other.t) > TOUCH_NMS + 1e-9 for other in kept):
            kept.append(touch)
    return sorted(kept, key=lambda item: item.t)


def _box_gap(point: tuple[float, float], box: tuple[int, int, int, int]) -> float:
    x, y = point
    bx, by, bw, bh = box
    return math.hypot(max(bx - x, 0.0, x - (bx + bw)), max(by - y, 0.0, y - (by + bh)))


def detect_touches(video: str | os.PathLike[str]) -> list[Touch]:
    """Touch candidates by any player: ball kicks next to a player blob (wide shots only)."""
    width, height = media.probe_size(video)
    aw = min(reframe.ANALYSIS_WIDTH, width)
    ah = max(2, 2 * round(height * aw / width / 2))
    frames = media.sample_frames(video, reframe.SAMPLE_HZ, aw, ah)
    cands = [reframe.ball_candidates(frame) for frame in frames]
    track = reframe.track_ball(cands, reframe.BALL_GATE * aw, reframe.BALL_LOST)
    hits = [
        pos if pos is not None and any((c[0], c[1]) == pos for c in cands[i]) else None
        for i, pos in enumerate(track)
    ]
    k = width / aw
    raw = []
    for i, strength in find_kicks(hits, aw):
        blobs = player_blobs(frames[i])
        if not blobs:
            continue
        gaps = [_box_gap(hits[i], blob) for blob in blobs]
        best = min(range(len(blobs)), key=lambda j: gaps[j])
        x, y, w, h = blobs[best]
        if gaps[best] <= REACH * h:
            raw.append(Touch(
                t=round(i / reframe.SAMPLE_HZ, 4), team=None, number=None,
                confidence=round(strength, 4),
                bbox=(round(x * k), round(y * k), round(w * k), round(h * k)),
            ))
    return suppress_touches(raw)


def find_touches(video: str | os.PathLike[str], query: PlayerQuery) -> list[Touch]:
    return [
        touch
        for touch in detect_touches(video)
        if touch.team == query.team and touch.number == query.number
    ]
