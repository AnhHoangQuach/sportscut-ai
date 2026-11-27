import math
import os
from collections.abc import Sequence
from numbers import Real

import numpy as np

from sportscut import media


ASPECT = 9 / 16
SAMPLE_HZ = 5
ANALYSIS_WIDTH = 320      # analysis frame width in px (never upscaled)
GREEN_HUE = (60.0, 180.0) # HSV hue range of grass, degrees
GREEN_MIN_SAT = 0.20      # HSV saturation in [0, 1]
GREEN_MIN_VAL = 0.15      # HSV value in [0, 1]
FIELD_MIN = 0.25          # share of green pixels for 'field detected'
FIELD_ROW_MIN = 0.30      # share of green pixels for a row to count as field
MIN_MASS = 20             # eroded player pixels needed for a measurement
DEAD_ZONE = 0.06          # fraction of frame width
EASE = 0.2                # share of the error beyond the dead zone closed per sample
MAX_PAN = 0.1             # fraction of frame width per second
BALL_LEVEL = 160          # min RGB channel for a bright (ball) pixel
BALL_FILL = 0.4           # minimum bright share of the inner box
BALL_BOXES = (3, 5)       # odd inner box sizes in analysis px (fixed)
BALL_RING = 2             # empty ring width around the inner box (fixed)
BALL_NMS = 3.0            # suppression radius in analysis px (fixed)
BALL_GATE = 0.25          # tracking gate, fraction of the analysis width
BALL_LOST = 5             # consecutive missed samples before the ball is lost
BLEND_STEP = 0.1          # ball-confidence weight change per sample
BALL_EDGE = 0.15          # crop-width share kept between the ball and the crop edge
BALL_DEAD_ZONE = 0.01     # ball-mode dead zone, fraction of frame width
BALL_EASE = 0.3           # ball-mode easing
BALL_MAX_PAN = 0.3        # ball-mode max pan, fraction of frame width per second


def crop_width(width: int, height: int, aspect: float = ASPECT) -> int:
    """Return the even-width, full-height crop for the requested aspect."""
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or width <= 0
        or isinstance(height, bool)
        or not isinstance(height, int)
        or height <= 0
    ):
        raise ValueError("width and height must be positive integers")
    if (
        isinstance(aspect, bool)
        or not isinstance(aspect, Real)
        or not math.isfinite(aspect)
        or aspect <= 0
    ):
        raise ValueError("aspect must be a positive finite number")
    return min(width, max(2, 2 * math.floor(height * aspect / 2)))


def sample_times(duration: float) -> list[float]:
    """Return the 5 Hz sample grid over ``[0, duration)``."""
    if (
        isinstance(duration, bool)
        or not isinstance(duration, Real)
        or not math.isfinite(duration)
        or duration <= 0
    ):
        raise ValueError("duration must be a positive finite number")
    count = max(1, math.floor(duration * SAMPLE_HZ + 1e-9))
    return [round(index / SAMPLE_HZ, 4) for index in range(count)]


def green_mask(frame: np.ndarray) -> np.ndarray:
    """Return a bool (h, w) mask of grass-green pixels in an RGB uint8 frame."""
    rgb = frame.astype(np.float64)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    high = rgb.max(axis=-1)
    d = high - rgb.min(axis=-1)
    safe_d = np.where(d == 0, 1.0, d)
    value = high / 255
    sat = np.where(high == 0, 0.0, d / np.where(high == 0, 1.0, high))
    hue = np.where(
        high == r,
        60 * np.mod((g - b) / safe_d, 6),
        np.where(high == g, 60 * ((b - r) / safe_d + 2), 60 * ((r - g) / safe_d + 4)),
    )
    hue = np.where(d == 0, 0.0, hue)
    return (
        (hue >= GREEN_HUE[0])
        & (hue <= GREEN_HUE[1])
        & (sat >= GREEN_MIN_SAT)
        & (value >= GREEN_MIN_VAL)
    )


def field_mask(frame: np.ndarray) -> np.ndarray | None:
    """Return the bool (h, w) inside-field mask, or None with no field."""
    green = green_mask(frame)
    if green.mean() < FIELD_MIN:
        return None
    w = green.shape[1]
    rows = green.mean(axis=1) >= FIELD_ROW_MIN
    first = green.argmax(axis=1)
    last = w - 1 - green[:, ::-1].argmax(axis=1)
    cols = np.arange(w)
    return rows[:, None] & (cols >= first[:, None]) & (cols <= last[:, None])


def player_mask(frame: np.ndarray) -> np.ndarray | None:
    """Return the eroded non-green mass inside the field, or None with no field."""
    inside = field_mask(frame)
    if inside is None:
        return None
    h, w = inside.shape
    candidates = inside & ~green_mask(frame)
    eroded = np.zeros((h, w), bool)
    if h >= 3 and w >= 3:
        core = np.ones((h - 2, w - 2), bool)
        for dy in range(3):
            for dx in range(3):
                core &= candidates[dy : h - 2 + dy, dx : w - 2 + dx]
        eroded[1:-1, 1:-1] = core
    return eroded


def _box_sums(ii: np.ndarray, size: int, pad: int) -> np.ndarray:
    """Sum of size x size boxes centred on every pixel at least pad from the edge."""
    h, w = ii.shape[0] - 1, ii.shape[1] - 1
    half = size // 2
    r0, r1 = pad - half, h - pad - half
    c0, c1 = pad - half, w - pad - half
    return (
        ii[r0 + size : r1 + size, c0 + size : c1 + size]
        - ii[r0:r1, c0 + size : c1 + size]
        - ii[r0 + size : r1 + size, c0:c1]
        + ii[r0:r1, c0:c1]
    )


def ball_candidates(frame: np.ndarray) -> list[tuple[float, float, float]]:
    """Return isolated, compact bright blobs inside the field as (x, y, score)."""
    field = field_mask(frame)
    if field is None:
        return []
    bright = (frame.min(axis=-1) >= BALL_LEVEL) & field
    h, w = bright.shape
    rows, cols = np.indices((h, w), dtype=np.float64)
    integrals = []
    for values in (bright.astype(np.float64), rows * bright, cols * bright):
        ii = np.zeros((h + 1, w + 1))
        ii[1:, 1:] = values.cumsum(axis=0).cumsum(axis=1)
        integrals.append(ii)
    hits = []
    for s in BALL_BOXES:
        pad = s // 2 + BALL_RING
        if h < 2 * pad + 1 or w < 2 * pad + 1:
            continue
        inner = _box_sums(integrals[0], s, pad)
        outer = _box_sums(integrals[0], s + 2 * BALL_RING, pad)
        ok = (outer == inner) & (inner > 0) & (inner >= BALL_FILL * s * s)
        rs, cs = np.nonzero(ok)
        row_sum = _box_sums(integrals[1], s, pad)[rs, cs]
        col_sum = _box_sums(integrals[2], s, pad)[rs, cs]
        n = inner[rs, cs]
        for x, y, count in zip(col_sum / n + 0.5, row_sum / n + 0.5, n):
            hits.append((float(x), float(y), float(count) / (s * s)))
    hits.sort(key=lambda hit: (-hit[2], hit[1], hit[0]))
    kept: list[tuple[float, float, float]] = []
    for hit in hits:
        if all(math.hypot(hit[0] - k[0], hit[1] - k[1]) > BALL_NMS for k in kept):
            kept.append(hit)
    return kept


def track_ball(
    samples: Sequence[Sequence[tuple[float, float, float]]],
    gate: float,
    lost_after: int = BALL_LOST,
) -> list[tuple[float, float] | None]:
    """Follow one ball through per-sample candidates with a constant-velocity gate."""
    out: list[tuple[float, float] | None] = []
    pos: tuple[float, float] | None = None
    vel = (0.0, 0.0)
    misses = 0
    for cands in samples:
        if pos is None:
            if cands:
                best = max(cands, key=lambda c: c[2])  # first max wins ties
                pos, vel, misses = (best[0], best[1]), (0.0, 0.0), 0
            out.append(pos)
            continue
        n = misses + 1
        pred = (pos[0] + vel[0] * n, pos[1] + vel[1] * n)
        dists = [math.hypot(c[0] - pred[0], c[1] - pred[1]) for c in cands]
        inside = [i for i, d in enumerate(dists) if d <= gate]
        if inside:
            c = cands[min(inside, key=lambda i: dists[i])]
            vel = ((c[0] - pos[0]) / n, (c[1] - pos[1]) / n)
            pos, misses = (c[0], c[1]), 0
            out.append(pos)
            continue
        misses += 1
        if misses >= lost_after:
            pos, vel, misses = None, (0.0, 0.0), 0
        out.append(pos)
    return out


def target_x(frame: np.ndarray, crop_cols: int) -> float | None:
    """Return the mass centroid of the crop-wide window holding the most player mass."""
    mask = player_mask(frame)
    if mask is None or mask.sum() < MIN_MASS:
        return None
    col = mask.sum(axis=0).astype(np.float64)
    k = min(crop_cols, col.size)
    sums = np.concatenate(([0.0], np.cumsum(col)))
    start = int(np.argmax(sums[k:] - sums[:-k]))
    window = col[start : start + k]
    centres = np.arange(start, start + k) + 0.5
    return float((centres * window).sum() / window.sum())


def _at(param: float | Sequence[float], i: int) -> float:
    """Return a scalar gain, or the i-th value of a per-sample gain."""
    return param if isinstance(param, Real) else param[i]


def blend_weights(ball: Sequence[object], step: float = BLEND_STEP) -> list[float]:
    """Ramp the ball-confidence weight up while tracked and down once lost."""
    weights: list[float] = []
    for i, b in enumerate(ball):
        if i == 0:
            weights.append(1.0 if b is not None else 0.0)
        elif b is not None:
            weights.append(min(1.0, weights[-1] + step))
        else:
            weights.append(max(0.0, weights[-1] - step))
    return weights


def framed_x(frame: np.ndarray, crop_cols: int, ball_x: float, margin: float) -> float:
    """Frame the most player mass while the camera centre stays within margin of the ball."""
    lo, hi = ball_x - margin, ball_x + margin
    mask = player_mask(frame)
    if mask is None:
        return float(ball_x)
    col = mask.sum(axis=0).astype(np.float64)
    k = min(crop_cols, col.size)
    sums = np.concatenate(([0.0], np.cumsum(col)))
    mass = sums[k:] - sums[:-k]
    centres = np.arange(mass.size) + k / 2
    allowed = (centres >= lo) & (centres <= hi)
    if not allowed.any():
        return float(ball_x)
    start = int(np.argmax(np.where(allowed, mass, -1.0)))
    if mass[start] < MIN_MASS:
        return float(ball_x)
    window = col[start : start + k]
    x = float((np.arange(start, start + k) + 0.5) @ window / window.sum())
    return min(max(x, lo), hi)


def smooth_path(
    targets: Sequence[float | None],
    width: int,
    cw: int,
    dead_zone: float | Sequence[float] = DEAD_ZONE,
    ease: float | Sequence[float] = EASE,
    max_pan: float | Sequence[float] = MAX_PAN,
) -> list[float]:
    """Turn per-sample targets into a camera path: dead zone, easing, max pan.

    Each gain is a scalar or a per-sample sequence (step into sample i uses i).
    """
    for param in (dead_zone, ease, max_pan):
        if not isinstance(param, Real) and len(param) != len(targets):
            raise ValueError("per-sample gains must match the number of targets")
    if not targets:
        return []
    lo, hi = cw / 2, width - cw / 2
    x = width / 2 if targets[0] is None else min(max(targets[0], lo), hi)
    path = [x]
    for i, target in enumerate(targets[1:], start=1):
        if target is not None:
            dz = _at(dead_zone, i) * width
            max_step = _at(max_pan, i) * width / SAMPLE_HZ
            ease_i = _at(ease, i)
            err = target - x
            step = 0.0 if abs(err) <= dz else ease_i * (err - math.copysign(dz, err))
            step = min(max(step, -max_step), max_step)
            x = min(max(x + step, lo), hi)
        path.append(x)
    return path


def center_plan(
    video: str | os.PathLike[str], aspect: float = ASPECT
) -> list[tuple[float, float]]:
    """Plan a static center crop at 5 Hz (the T-017 baseline)."""
    width, height = media.probe_size(video)
    crop_width(width, height, aspect)
    duration = media.probe_duration(video)
    return [(sample_time, width / 2) for sample_time in sample_times(duration)]


def plan_crop(
    video: str | os.PathLike[str], aspect: float = ASPECT
) -> list[tuple[float, float]]:
    """Plan a 5 Hz crop path that follows the ball, falling back to the players."""
    width, height = media.probe_size(video)
    cw = crop_width(width, height, aspect)
    times = sample_times(media.probe_duration(video))
    aw = min(ANALYSIS_WIDTH, width)
    ah = max(2, 2 * round(height * aw / width / 2))
    k = max(1, round(cw * aw / width))
    scale = width / aw
    frames = media.sample_frames(video, SAMPLE_HZ, aw, ah)
    n = len(times)
    have = [i < len(frames) for i in range(n)]
    cands = [ball_candidates(frames[i]) if have[i] else [] for i in range(n)]
    ball = track_ball(cands, BALL_GATE * aw, BALL_LOST)
    w = blend_weights(ball, BLEND_STEP)
    margin = (0.5 - BALL_EDGE) * k
    targets: list[float | None] = []
    last_b = None
    for i in range(n):
        p = target_x(frames[i], k) if have[i] else None
        if ball[i] is not None:
            last_b = ball[i][0]
        if last_b is None or w[i] == 0:
            t = p
        else:
            f = framed_x(frames[i], k, last_b, margin) if have[i] else last_b
            t = f if p is None or w[i] == 1 else w[i] * f + (1 - w[i]) * p
        targets.append(None if t is None else t * scale)
    dz = [DEAD_ZONE + wi * (BALL_DEAD_ZONE - DEAD_ZONE) for wi in w]
    ease = [EASE + wi * (BALL_EASE - EASE) for wi in w]
    pan = [MAX_PAN + wi * (BALL_MAX_PAN - MAX_PAN) for wi in w]
    return list(zip(times, smooth_path(targets, width, cw, dz, ease, pan)))
