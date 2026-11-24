import numpy as np

from sportscut.media import SAMPLE_RATE, extract_audio, probe_duration
from sportscut.models import Segment

PRE_SEC = 8.0
POST_SEC = 4.0
BASELINE_SEC = 120
MIN_Z = 3.0
MIN_SCALE_DB = 1.0


def loudness_residual(samples: np.ndarray) -> np.ndarray:
    """Return per-second RMS dB above the centred rolling baseline."""
    n = len(samples) // SAMPLE_RATE
    if n == 0:
        return np.empty(0, dtype=np.float64)
    frames = samples[: n * SAMPLE_RATE].reshape(n, SAMPLE_RATE)
    rms = np.sqrt(
        np.einsum("ij,ij->i", frames, frames, dtype=np.float64) / SAMPLE_RATE
    )
    db = 20 * np.log10(rms + 1e-10)
    half_window = BASELINE_SEC // 2
    baseline = np.array(
        [
            np.median(db[max(0, i - half_window) : i + half_window + 1])
            for i in range(n)
        ]
    )
    return db - baseline


def place_window(
    anchor: float, length: float, duration: float, before: float
) -> tuple[float, float]:
    """Place a fixed-length window around an anchor inside media bounds."""
    start = float(anchor - before)
    end = float(start + length)
    if start < 0:
        end -= start
        start = 0.0
    if end > duration:
        start -= end - duration
        end = float(duration)
    return max(start, 0.0), end


def find_highlights(
    video: str, top: int | None = 10, min_len: float = 10, max_len: float = 30
) -> list[Segment]:
    if top is not None and top < 1:
        raise ValueError("top must be >= 1")
    if min_len <= 0:
        raise ValueError("min_len must be > 0")
    if min_len > max_len:
        raise ValueError("min_len must be <= max_len")

    duration = probe_duration(video)
    samples = extract_audio(video)
    residual = loudness_residual(samples)
    if len(residual) == 0:
        return []

    mad = np.median(np.abs(residual - np.median(residual)))
    scale = max(1.4826 * mad, MIN_SCALE_DB)
    z_scores = residual / scale
    candidates = [
        (i + 0.5, z_score)
        for i, z_score in enumerate(z_scores)
        if z_score >= MIN_Z
        and z_score >= (z_scores[i - 1] if i else -np.inf)
        and z_score > (z_scores[i + 1] if i + 1 < len(z_scores) else -np.inf)
    ]

    length = min(max(PRE_SEC + POST_SEC, min_len), max_len)
    windows = []
    for peak_time, z_score in candidates:
        start, end = place_window(
            peak_time,
            length,
            duration,
            length * PRE_SEC / (PRE_SEC + POST_SEC),
        )
        windows.append((start, end, z_score))

    kept = []
    for window in sorted(windows, key=lambda item: (-item[2], item[0])):
        start, end, _score = window
        if all(not (start < other[1] and other[0] < end) for other in kept):
            kept.append(window)
            if top is not None and len(kept) == top:
                break

    return sorted(
        (
            Segment(
                start=float(start),
                end=float(end),
                score=float(z_score),
                reason=f"audio peak z={z_score:.1f}",
            )
            for start, end, z_score in kept
        ),
        key=lambda segment: segment.start,
    )
