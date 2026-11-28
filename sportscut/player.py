import math
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

import numpy as np

from sportscut import jersey, media, reframe


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
TEAM_RGB = {
    "black": (0, 0, 0), "blue": (0, 0, 255), "green": (0, 128, 0), "orange": (255, 165, 0),
    "pink": (255, 105, 180), "purple": (128, 0, 128), "red": (255, 0, 0),
    "sky": (135, 206, 235), "white": (255, 255, 255), "yellow": (255, 255, 0),
}
TEAM_MIN_SAT = 0.25       # min HSV saturation of a shirt pixel (tunable 0.15..0.40)
TEAM_K = 4                # k-means clusters before dropping/merging (tunable 3..5)
TEAM_MIN_SHARE = 0.1      # min share of pixels for a cluster to be a team (tunable 0.05..0.20)
TEAM_MERGE = 0.15         # merge clusters closer than this, feature units (tunable 0.05..0.30)
TEAM_EVERY = 5            # every 5th 5 Hz sample = 1 Hz (fixed)
TEAM_TIE = 0.05           # relative distance gap counted as 'equally far' (fixed)
TEAM_MIN_PIXELS = 50      # fixed
TEAM_MAX_PIXELS = 20000   # fixed
TEAM_ITERS = 20           # fixed

NUMBER_SPAN = 2.0     # seconds read before and after each touch (fixed)
NUMBER_WIDTH = 1280   # max decode width of the number crops, never upscaled (fixed)
TRACK_GATE = 1.0      # max distance from the predicted centre per 5 Hz sample, times the previous box height (tunable 0.5..2.0)
TRACK_MERGE = 1.3     # a blob wider or taller than this times the seed box is two merged players (tunable 1.2..1.6)
MIN_CONFIDENCE = 0.5  # default min vote confidence (tunable 0.3..0.8)


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
    min_confidence: float = MIN_CONFIDENCE

    def __post_init__(self) -> None:
        object.__setattr__(self, "team", normalize_team(self.team))
        if type(self.number) is not int or not 1 <= self.number <= 99:
            raise ValueError("player number must be an integer from 1 to 99")
        value = self.min_confidence
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0 <= value <= 1):
            raise ValueError("min confidence must be between 0 and 1")
        object.__setattr__(self, "min_confidence", float(value))


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


def colour_features(rgb: np.ndarray) -> np.ndarray:
    """Map uint8 RGB (N, 3) to the HSV cone [s*cos(2*pi*h), s*sin(2*pi*h), v]."""
    rgb = np.asarray(rgb, np.float64).reshape(-1, 3) / 255
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    high = rgb.max(axis=1)
    d = high - rgb.min(axis=1)
    safe_d = np.where(d == 0, 1.0, d)
    sat = np.where(high == 0, 0.0, d / np.where(high == 0, 1.0, high))
    hue = np.where(
        high == r,
        np.mod((g - b) / safe_d, 6),
        np.where(high == g, (b - r) / safe_d + 2, (r - g) / safe_d + 4),
    ) / 6
    angle = 2 * np.pi * np.where(d == 0, 0.0, hue)
    return np.stack([sat * np.cos(angle), sat * np.sin(angle), high], axis=1)


def kmeans(points: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic k-means: farthest-point initialisation, then Lloyd iterations."""
    points = np.asarray(points, np.float64)
    first = int(np.argmin(np.linalg.norm(points - points.mean(axis=0), axis=1)))
    centroids = [points[first]]
    nearest = np.linalg.norm(points - points[first], axis=1)
    for _ in range(1, k):
        index = int(np.argmax(nearest))
        centroids.append(points[index])
        nearest = np.minimum(nearest, np.linalg.norm(points - points[index], axis=1))
    centroids = np.array(centroids)
    labels = np.full(len(points), -1)
    for _ in range(TEAM_ITERS):
        dist = np.linalg.norm(points[:, None, :] - centroids[None, :, :], axis=2)
        new = dist.argmin(axis=1)
        if np.array_equal(new, labels):
            break
        labels = new
        for j in range(k):
            if np.any(labels == j):
                centroids[j] = points[labels == j].mean(axis=0)
    return centroids, labels


@dataclass(frozen=True)
class TeamColours:
    centroids: tuple[tuple[float, float, float], tuple[float, float, float]]  # larger team first
    names: tuple[str, str]                                                    # distinct TEAM_NAMES


def shirt_pixels(frame: np.ndarray, box: tuple[int, int, int, int] | None = None) -> np.ndarray:
    """Colour features of saturated player-mask pixels, optionally inside box (x, y, w, h)."""
    mask = reframe.player_mask(frame)
    if mask is None:
        return np.zeros((0, 3))
    if box is not None:
        x, y, w, h = box
        inside = np.zeros_like(mask)
        inside[max(0, y) : y + h, max(0, x) : x + w] = True
        mask = mask & inside
    feats = colour_features(frame[mask])
    return feats[np.hypot(feats[:, 0], feats[:, 1]) >= TEAM_MIN_SAT]


_TEAM_FEATS = colour_features(np.array(list(TEAM_RGB.values()), np.uint8))


def name_teams(centroids: np.ndarray) -> tuple[str, str]:
    """The ordered pair of distinct TEAM_NAMES closest to the two centroids."""
    d = np.linalg.norm(np.asarray(centroids)[:2, None, :] - _TEAM_FEATS[None, :, :], axis=2)
    best, pair = math.inf, ("", "")
    for a, name_a in enumerate(TEAM_NAMES):
        for b, name_b in enumerate(TEAM_NAMES):
            if a != b and d[0, a] + d[1, b] < best:
                best, pair = d[0, a] + d[1, b], (name_a, name_b)
    return pair


def team_colours(frames: np.ndarray) -> TeamColours | None:
    """Two team shirt colours from saturated player pixels sampled at 1 Hz, or None."""
    pooled = [shirt_pixels(frame) for frame in frames[::TEAM_EVERY]]
    points = np.concatenate(pooled) if pooled else np.zeros((0, 3))
    if len(points) < TEAM_MIN_PIXELS:
        return None
    points = points[:: math.ceil(len(points) / TEAM_MAX_PIXELS)]
    centroids, labels = kmeans(points, TEAM_K)
    sizes = np.bincount(labels, minlength=TEAM_K)
    order = sorted(range(TEAM_K), key=lambda j: (-sizes[j], j))
    kept: list[list] = []  # [centroid, size]
    for j in order:
        if sizes[j] < TEAM_MIN_SHARE * len(points):
            continue
        near = [c for c in kept if np.linalg.norm(c[0] - centroids[j]) < TEAM_MERGE]
        if near:
            c = near[0]
            c[0] = (c[0] * c[1] + centroids[j] * sizes[j]) / (c[1] + sizes[j])
            c[1] += sizes[j]
        else:
            kept.append([centroids[j].copy(), int(sizes[j])])
    if len(kept) < 2:
        return None
    pair = np.array([c[0] for c in sorted(kept, key=lambda c: -c[1])[:2]])
    return TeamColours(tuple(tuple(float(v) for v in c) for c in pair), name_teams(pair))


def team_of(frame: np.ndarray, box: tuple[int, int, int, int], colours: TeamColours | None) -> str | None:
    """Majority team of the saturated shirt pixels in box (tie: the larger team)."""
    pixels = shirt_pixels(frame, box) if colours is not None else np.zeros((0, 3))
    if not len(pixels):
        return None
    centroids = np.array(colours.centroids)
    nearest = np.linalg.norm(pixels[:, None, :] - centroids[None, :, :], axis=2).argmin(axis=1)
    votes = np.bincount(nearest, minlength=2)
    return colours.names[1] if votes[1] > votes[0] else colours.names[0]


def pick_team(team: str, colours: TeamColours) -> str:
    """Map a team name or #rrggbb to the closest of the two detected team colours."""
    if team in colours.names:
        return team
    rgb = TEAM_RGB.get(team) or tuple(int(team[i : i + 2], 16) for i in (1, 3, 5))
    feat = colour_features(np.array([rgb], np.uint8))[0]
    d0, d1 = (float(np.linalg.norm(feat - np.array(c))) for c in colours.centroids)
    n0, n1 = colours.names
    if abs(d0 - d1) <= TEAM_TIE * max(d0, d1):
        raise ValueError(
            f"team colour '{team}' is equally close to both team shirts ({n0}, {n1}); "
            f"use --team {n0}, --team {n1} or a closer #rrggbb"
        )
    return n0 if d0 < d1 else n1


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


def _analyse(video: str | os.PathLike[str]) -> tuple[list[Touch], TeamColours | None]:
    """One pass: touch candidates labelled with a team, plus the match's two team colours."""
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
    colours = team_colours(frames)
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
                t=round(i / reframe.SAMPLE_HZ, 4),
                team=team_of(frames[i], blobs[best], colours), number=None,
                confidence=round(strength, 4),
                bbox=(round(x * k), round(y * k), round(w * k), round(h * k)),
            ))
    return suppress_touches(raw), colours


def _read_numbers(
    video: str | os.PathLike[str], touches: Sequence[Touch], reader: jersey.NumberReader
) -> list[tuple[int | None, float]]:
    """One (number, confidence) vote per touch, read from the toucher tracked within NUMBER_SPAN."""
    votes: list[tuple[int | None, float]] = [(None, 0.0)] * len(touches)
    todo = [i for i, touch in enumerate(touches) if touch.bbox is not None]
    if not todo:
        return votes
    width, height = media.probe_size(video)
    nw = min(width, NUMBER_WIDTH)
    nh = max(2, 2 * round(height * nw / width / 2))
    s = max(1, nw // min(reframe.ANALYSIS_WIDTH, nw))
    f, hz = nw / width / s, reframe.SAMPLE_HZ
    groups: list[list] = []  # [lo, hi, touch indices]
    for lo, hi, i in sorted(
        (max(0, math.floor((touches[i].t - NUMBER_SPAN) * hz + 1e-6) / hz),
         math.ceil((touches[i].t + NUMBER_SPAN) * hz - 1e-6) / hz, i) for i in todo
    ):
        if groups and lo <= groups[-1][1] + 1e-9:
            groups[-1][1] = max(groups[-1][1], hi)
            groups[-1][2].append(i)
        else:
            groups.append([lo, hi, [i]])
    centre = lambda b: (b[0] + b[2] / 2, b[1] + b[3] / 2)
    dist = lambda a, b: math.hypot(a[0] - b[0], a[1] - b[1])
    for lo, hi, members in groups:
        frames = media.sample_window(video, round(lo, 4), round(hi - lo + 1 / hz, 4), hz, nw, nh)
        cache: dict[int, list[tuple[int, int, int, int]]] = {}
        blobs = lambda k: cache[k] if k in cache else cache.setdefault(k, player_blobs(frames[k][::s, ::s]))
        for i in members:
            t = touches[i].t
            span = [k for k in range(len(frames)) if abs(lo + k / hz - t) <= NUMBER_SPAN + 1e-6]
            if not span:
                continue
            k0 = min(span, key=lambda k: abs(lo + k / hz - t))
            bx, by, sw, sh = (value * f for value in touches[i].bbox)
            target = (bx + sw / 2, by + sh / 2)
            seed = min(blobs(k0), key=lambda b: dist(centre(b), target), default=None)
            if seed is None or dist(centre(seed), target) > TRACK_GATE * sh:
                continue
            merged = lambda b: b[2] > TRACK_MERGE * sw or b[3] > TRACK_MERGE * sh
            kept = {} if merged(seed) else {k0: seed}
            for step in (1, -1):
                v, c, hp, k = (0.0, 0.0), centre(seed), seed[3], k0 + step
                while span[0] <= k <= span[-1]:
                    p = (c[0] + v[0], c[1] + v[1])
                    near = [b for b in blobs(k) if dist(centre(b), p) <= TRACK_GATE * hp]
                    if not near:
                        break
                    best = min(near, key=lambda b: dist(centre(b), p))
                    if merged(best):
                        c = p
                    else:
                        v, c, hp = (centre(best)[0] - c[0], centre(best)[1] - c[1]), centre(best), best[3]
                        kept[k] = best
                    k += step
            crops = [frames[k][y * s:(y + h) * s, x * s:(x + w) * s] for k, (x, y, w, h) in sorted(kept.items())]
            if reader.max_reads is not None and len(crops) > reader.max_reads:
                picks = np.linspace(0, len(crops) - 1, reader.max_reads)
                crops = [crops[j] for j in sorted({int(round(float(v))) for v in picks})]
            votes[i] = jersey.vote([reader.read(crop) for crop in crops])
    return votes


def detect_touches(video: str | os.PathLike[str]) -> list[Touch]:
    """Touch candidates by any player (wide shots only), numbered when the vote is confident."""
    reader = jersey.get_reader()
    touches, _ = _analyse(video)
    labelled = [touch for touch in touches if touch.team is not None]
    votes = iter(_read_numbers(video, labelled, reader))
    out = []
    for touch in touches:
        number, conf = next(votes) if touch.team is not None else (None, 0.0)
        out.append(replace(touch, number=number) if number is not None and conf >= MIN_CONFIDENCE else touch)
    return out


def find_touches(video: str | os.PathLike[str], query: PlayerQuery) -> list[Touch]:
    """Touches by the queried team whose voted jersey number matches with enough confidence."""
    reader = jersey.get_reader()
    touches, colours = _analyse(video)
    if colours is None:
        return []
    team = pick_team(query.team, colours)
    same = [touch for touch in touches if touch.team == team]
    votes = _read_numbers(video, same, reader)
    return [
        replace(touch, number=n)
        for touch, (n, c) in zip(same, votes)
        if n == query.number and c >= query.min_confidence
    ]
