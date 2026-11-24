"""Audio features for whistle, stoppage, and save classification."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path
from typing import NamedTuple

import numpy as np

from sportscut.events import scoreboard
from sportscut.media import SAMPLE_RATE, extract_audio
from sportscut.models import Segment

WINDOW = SAMPLE_RATE // 10
CHUNK = 600
BASELINE_WINDOWS = 600
WHISTLE_LOW, WHISTLE_HIGH = 2000.0, 4000.0
WHISTLE_SHARE = 0.5
WHISTLE_MIN_WINDOWS = 3
PLAY_LOW, PLAY_HIGH = 300.0, 2000.0
QUIET_DB = 6.0
ABOVE_DB = 6.0
RISE_DB = 3.0
NEAR_PEAK_DB = 2.0
RISE_LOOKBACK = 50
SAVE_MAX_SEC = 4.0
SAVE_MAX_RISE = 0.5
WHISTLE_AFTER = 5.0
BOARD_BEFORE, BOARD_AFTER = 10.0, 30.0
CONF_SAVE = 0.6


class RoarShape(NamedTuple):
    peak: float
    start: float
    end: float
    duration: float
    rise: float
    decay: float


def window_levels(samples: np.ndarray) -> np.ndarray:
    """Return RMS decibels for each complete 0.1 second window."""
    count = len(samples) // WINDOW
    if count == 0:
        return np.empty(0, dtype=np.float64)
    frames = samples[: count * WINDOW].reshape(count, WINDOW)
    rms = np.sqrt(
        np.einsum("ij,ij->i", frames, frames, dtype=np.float64) / WINDOW
    )
    return 20 * np.log10(rms + 1e-10)


def band_share(samples: np.ndarray, low: float, high: float) -> np.ndarray:
    """Return the fraction of Hann-windowed power inside a frequency band."""
    count = len(samples) // WINDOW
    if count == 0:
        return np.empty(0, dtype=np.float64)
    frames = samples[: count * WINDOW].reshape(count, WINDOW)
    hann = np.hanning(WINDOW)
    frequencies = np.fft.rfftfreq(WINDOW, 1 / SAMPLE_RATE)
    selected = (low <= frequencies) & (frequencies <= high)
    shares = np.empty(count, dtype=np.float64)
    for first in range(0, count, CHUNK):
        stop = min(first + CHUNK, count)
        spectrum = np.fft.rfft(frames[first:stop] * hann, axis=1)
        power = np.abs(spectrum) ** 2
        total = power.sum(axis=1)
        shares[first:stop] = np.divide(
            power[:, selected].sum(axis=1),
            total,
            out=np.zeros(stop - first, dtype=np.float64),
            where=total != 0,
        )
    return shares


def _band_power(
    samples: np.ndarray, low: float, high: float, first: int, stop: int
) -> np.ndarray:
    """Return Hann-windowed band power for the requested window range."""
    if first >= stop:
        return np.empty(0, dtype=np.float64)
    frames = samples[first * WINDOW : stop * WINDOW].reshape(stop - first, WINDOW)
    hann = np.hanning(WINDOW)
    frequencies = np.fft.rfftfreq(WINDOW, 1 / SAMPLE_RATE)
    selected = (low <= frequencies) & (frequencies <= high)
    result = np.empty(stop - first, dtype=np.float64)
    for offset in range(0, stop - first, CHUNK):
        chunk_stop = min(offset + CHUNK, stop - first)
        spectrum = np.fft.rfft(frames[offset:chunk_stop] * hann, axis=1)
        result[offset:chunk_stop] = (np.abs(spectrum[:, selected]) ** 2).sum(
            axis=1
        )
    return result


def find_whistles(samples: np.ndarray) -> list[tuple[float, float]]:
    """Return maximal whistle-like intervals lasting at least 0.3 seconds."""
    qualifying = band_share(samples, WHISTLE_LOW, WHISTLE_HIGH) >= WHISTLE_SHARE
    intervals = []
    first = 0
    while first < len(qualifying):
        if not qualifying[first]:
            first += 1
            continue
        stop = first + 1
        while stop < len(qualifying) and qualifying[stop]:
            stop += 1
        if stop - first >= WHISTLE_MIN_WINDOWS:
            intervals.append((first / 10, stop / 10))
        first = stop
    return intervals


def stoppage_after(samples: np.ndarray, at: float) -> float:
    """Measure continuous low play-band activity starting at ``at``."""
    count = len(samples) // WINDOW
    start = round(at * 10)
    if start < 0 or start >= count:
        return 0.0
    first = max(0, start - BASELINE_WINDOWS)
    stop = min(count, start + BASELINE_WINDOWS + 1)
    power = _band_power(samples, PLAY_LOW, PLAY_HIGH, first, stop)
    levels = 10 * np.log10(power + 1e-20)
    baseline = float(np.median(levels))
    index = start - first
    quiet = 0
    while index + quiet < len(levels):
        if levels[index + quiet] > baseline - QUIET_DB:
            break
        quiet += 1
    return quiet / 10


def roar_shape(levels: np.ndarray, start: float, end: float) -> RoarShape:
    """Measure the peak, above-baseline run, rise, and decay of a roar."""
    first = max(0, math.floor(start * 10 + 1e-6))
    stop = min(len(levels), math.ceil(end * 10 - 1e-6))
    if first >= stop:
        value = float(start)
        return RoarShape(value, value, value, 0.0, 0.0, 0.0)

    peak = first + int(np.argmax(levels[first:stop]))
    baseline = float(
        np.median(
            levels[
                max(0, peak - BASELINE_WINDOWS) : peak + BASELINE_WINDOWS + 1
            ]
        )
    )
    peak_time = peak / 10
    if levels[peak] < baseline + ABOVE_DB:
        return RoarShape(peak_time, peak_time, peak_time, 0.0, 0.0, 0.0)

    left = peak
    while left > 0 and levels[left - 1] >= baseline + ABOVE_DB:
        left -= 1
    right = peak + 1
    while right < len(levels) and levels[right] >= baseline + ABOVE_DB:
        right += 1

    rise_first = next(
        index
        for index in range(max(0, peak - RISE_LOOKBACK), peak + 1)
        if levels[index] >= baseline + RISE_DB
    )
    near_peak = levels[peak] - NEAR_PEAK_DB
    rise_end = next(
        index
        for index in range(rise_first, peak + 1)
        if levels[index] >= near_peak
    )
    decay_start = max(
        index for index in range(peak, right) if levels[index] >= near_peak
    )
    return RoarShape(
        peak_time,
        left / 10,
        right / 10,
        (right - left) / 10,
        (rise_end - rise_first) / 10,
        (right - 1 - decay_start) / 10,
    )


def match_saves(
    segments: list[Segment],
    levels: np.ndarray,
    whistles: list[tuple[float, float]],
    changes: list[float] | None,
) -> list[Segment]:
    """Tag eligible short, sharp roars while preserving segment geometry."""
    if changes is None:
        return list(segments)
    result = list(segments)
    for index, segment in enumerate(segments):
        if segment.event != "other":
            continue
        shape = roar_shape(levels, segment.start, segment.end)
        if not (0 < shape.duration < SAVE_MAX_SEC):
            continue
        if shape.rise > SAVE_MAX_RISE:
            continue
        if any(
            whistle_start < shape.end + WHISTLE_AFTER
            and whistle_end > shape.start
            for whistle_start, whistle_end in whistles
        ):
            continue
        if any(
            shape.peak - BOARD_BEFORE <= change <= shape.peak + BOARD_AFTER
            for change in changes
        ):
            continue
        result[index] = replace(
            segment,
            event="save",
            event_confidence=CONF_SAVE,
            reason=f"{segment.reason}; sharp roar {shape.duration:.1f}s",
        )
    return result


def tag_saves(video: str | Path, segments: list[Segment]) -> list[Segment]:
    """Load audio features and tag saves when a scoreboard is visible."""
    changes = scoreboard.board_changes(video)
    if changes is None:
        return list(segments)
    samples = extract_audio(video)
    return match_saves(
        list(segments), window_levels(samples), find_whistles(samples), changes
    )
