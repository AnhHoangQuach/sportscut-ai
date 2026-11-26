"""Render vertical 9:16 clips by following a crop path."""

import math
from numbers import Real
from pathlib import Path

from sportscut import media, reframe

OUT_WIDTH = 1080
OUT_HEIGHT = 1920
MAX_EXPRESSION = 100_000


def _is_number(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, Real)
        and math.isfinite(value)
    )


def _validate(crop_path) -> list[tuple[float, float]]:
    try:
        items = list(crop_path)
    except TypeError:
        raise ValueError("invalid crop path: not a sequence") from None
    if not items:
        raise ValueError("invalid crop path: empty")
    keyframes: list[tuple[float, float]] = []
    for index, item in enumerate(items):
        try:
            pair = tuple(item)
        except TypeError:
            raise ValueError(f"invalid crop path: item {index} is not a pair") from None
        if len(pair) != 2 or not all(_is_number(value) for value in pair):
            raise ValueError(
                f"invalid crop path: item {index} is not a pair of finite numbers"
            )
        t, x = float(pair[0]), float(pair[1])
        if index == 0 and t < 0:
            raise ValueError("invalid crop path: first t is negative")
        if keyframes and t <= keyframes[-1][0]:
            raise ValueError(f"invalid crop path: t is not strictly increasing at item {index}")
        keyframes.append((t, x))
    return keyframes


def crop_x_expression(crop_path, width: int, crop_w: int) -> str:
    """Return a flat ffmpeg expression in t for the crop's left edge."""
    keyframes = _validate(crop_path)
    half = crop_w / 2
    lefts = [
        (t, min(max(x, half), width - half) - half) for t, x in keyframes
    ]
    parts = [f"{lefts[0][1]:.4f}"]
    for (t0, l0), (t1, l1) in zip(lefts, lefts[1:]):
        slope = (l1 - l0) / (t1 - t0)
        if abs(slope) < 1e-9:
            continue
        sign = "+" if slope > 0 else "-"
        parts.append(f"{sign}{abs(slope):.6f}*(clip(t,{t0:.4f},{t1:.4f})-{t0:.4f})")
    expr = "".join(parts)
    if len(expr) > MAX_EXPRESSION:
        raise ValueError(f"crop path too long: {len(keyframes)} keyframes")
    return expr


def vertical_filter(crop_path, width: int, height: int) -> str:
    """Return the ffmpeg -vf filter that crops along the path and scales to 9:16."""
    crop_w = reframe.crop_width(width, height)
    expr = crop_x_expression(crop_path, width, crop_w)
    return (
        f"crop=w={crop_w}:h={height}:x='{expr}':y=0,"
        f"scale={OUT_WIDTH}:{OUT_HEIGHT},setsar=1"
    )


def render_vertical(clip, crop_path, out) -> Path:
    """Render a 1080x1920 H.264 copy of clip that follows crop_path."""
    _validate(crop_path)
    width, height = media.probe_size(clip)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    return media.filter_video(clip, vertical_filter(crop_path, width, height), out)
