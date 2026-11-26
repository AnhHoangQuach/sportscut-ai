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


def player_mask(frame: np.ndarray) -> np.ndarray | None:
    """Return the eroded non-green mass inside the field, or None with no field."""
    green = green_mask(frame)
    if green.mean() < FIELD_MIN:
        return None
    h, w = green.shape
    rows = green.mean(axis=1) >= FIELD_ROW_MIN
    first = green.argmax(axis=1)
    last = w - 1 - green[:, ::-1].argmax(axis=1)
    cols = np.arange(w)
    inside = rows[:, None] & (cols >= first[:, None]) & (cols <= last[:, None])
    candidates = inside & ~green
    eroded = np.zeros((h, w), bool)
    if h >= 3 and w >= 3:
        core = np.ones((h - 2, w - 2), bool)
        for dy in range(3):
            for dx in range(3):
                core &= candidates[dy : h - 2 + dy, dx : w - 2 + dx]
        eroded[1:-1, 1:-1] = core
    return eroded


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


def smooth_path(
    targets: Sequence[float | None],
    width: int,
    cw: int,
    dead_zone: float = DEAD_ZONE,
    ease: float = EASE,
    max_pan: float = MAX_PAN,
) -> list[float]:
    """Turn per-sample targets into a camera path: dead zone, easing, max pan."""
    if not targets:
        return []
    lo, hi = cw / 2, width - cw / 2
    dz = dead_zone * width
    max_step = max_pan * width / SAMPLE_HZ
    x = width / 2 if targets[0] is None else min(max(targets[0], lo), hi)
    path = [x]
    for target in targets[1:]:
        if target is not None:
            err = target - x
            step = 0.0 if abs(err) <= dz else ease * (err - math.copysign(dz, err))
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
    """Plan a 5 Hz crop path that follows the players with a smoothed camera."""
    width, height = media.probe_size(video)
    cw = crop_width(width, height, aspect)
    times = sample_times(media.probe_duration(video))
    aw = min(ANALYSIS_WIDTH, width)
    ah = max(2, 2 * round(height * aw / width / 2))
    k = max(1, round(cw * aw / width))
    frames = media.sample_frames(video, SAMPLE_HZ, aw, ah)
    targets: list[float | None] = []
    for i in range(len(times)):
        tx = target_x(frames[i], k) if i < len(frames) else None
        targets.append(None if tx is None else tx * width / aw)
    return list(zip(times, smooth_path(targets, width, cw)))
