import math
import os
from numbers import Real

from sportscut import media


ASPECT = 9 / 16
SAMPLE_HZ = 5


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


def plan_crop(
    video: str | os.PathLike[str], aspect: float = ASPECT
) -> list[tuple[float, float]]:
    """Plan a static center crop at 5 Hz."""
    width, height = media.probe_size(video)
    crop_width(width, height, aspect)
    duration = media.probe_duration(video)
    return [(sample_time, width / 2) for sample_time in sample_times(duration)]
