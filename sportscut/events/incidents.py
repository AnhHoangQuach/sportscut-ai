"""Red-card and controversial-incident classification helpers."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np

from sportscut.events import audio_cues, scoreboard
from sportscut.media import MediaError, _failure_detail, extract_audio, find_tool
from sportscut.models import Segment

RED_MIN_STOP = 8.0
CONTRO_MIN_STOP = 30.0
BOO_LOW, BOO_HIGH = 20.0, 220.0
BOO_SHARE = 0.5
BOO_MIN_SEC = 10.0
CLOSEUP_LOOK = 15.0
CLOSEUP_FPS = 2
FRAME_W, FRAME_H = 160, 90
RED_SHARE = 0.5
RED_MIN_FRAMES = 2
CONF_RED, CONF_CONTRO, CONF_REVERT = 0.5, 0.4, 0.5


def red_share(frames: np.ndarray) -> np.ndarray:
    """Return each frame's saturated-red share inside its centre crop."""
    if len(frames) == 0:
        return np.empty(0, dtype=np.float64)
    height, width = frames.shape[1:3]
    centre = frames[:, height // 4 : 3 * height // 4, width // 4 : 3 * width // 4]
    red = (centre[..., 0] >= 150) & (centre[..., 1] <= 60) & (centre[..., 2] <= 60)
    return red.mean(axis=(1, 2), dtype=np.float64)


def booing_seconds(samples: np.ndarray, start: float, end: float) -> float:
    """Count 0.1-second windows dominated by low-frequency booing."""
    first = max(0, round(start * 10))
    stop = min(len(samples) // audio_cues.WINDOW, round(end * 10))
    if first >= stop:
        return 0.0
    shares = audio_cues.band_share(
        samples[first * audio_cues.WINDOW : stop * audio_cues.WINDOW],
        BOO_LOW,
        BOO_HIGH,
    )
    return float((shares >= BOO_SHARE).sum() / 10)


def classify(stoppage: float, booing: float, red_frames: int) -> str:
    """Classify incident cues with red-card precedence."""
    if stoppage >= RED_MIN_STOP and red_frames >= RED_MIN_FRAMES:
        return "red_card"
    if stoppage >= CONTRO_MIN_STOP and booing >= BOO_MIN_SEC:
        return "controversy"
    return "other"


def sample_frames(
    video: str | Path, start: float, duration: float
) -> np.ndarray:
    """Decode small RGB frames from one candidate-local time window."""
    path = Path(video)
    if not path.is_file():
        raise MediaError(f"media file not found: {video}")
    ffmpeg = find_tool("ffmpeg")
    args = [
        ffmpeg,
        "-v",
        "error",
        "-nostdin",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(path),
        "-t",
        f"{duration:.3f}",
        "-an",
        "-vf",
        f"fps={CLOSEUP_FPS},scale={FRAME_W}:{FRAME_H}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "pipe:1",
    ]
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode:
        detail = _failure_detail(result.stderr, result.returncode)
        raise MediaError(f"ffmpeg failed for {video}: {detail}")
    frame_size = FRAME_W * FRAME_H * 3
    count = len(result.stdout) // frame_size
    return np.frombuffer(result.stdout, dtype=np.uint8)[: count * frame_size].reshape(
        count, FRAME_H, FRAME_W, 3
    )


def tag_incidents(
    video: str | Path, segments: list[Segment]
) -> list[Segment]:
    """Tag red cards, booing controversies, and reverted-score goals."""
    result = list(segments)
    goal_indexes = [
        index for index, segment in enumerate(segments) if segment.event == "goal"
    ]
    if goal_indexes:
        relabelled: set[int] = set()
        for first, second in scoreboard.board_reverts(video):
            markers = (
                f"scoreboard change at {first:.0f}s",
                f"scoreboard change at {second:.0f}s",
            )
            for index in goal_indexes:
                if index in relabelled:
                    continue
                segment = segments[index]
                if not any(marker in segment.reason for marker in markers):
                    continue
                result[index] = replace(
                    segment,
                    event="controversy",
                    event_confidence=CONF_REVERT,
                    reason=(
                        f"{segment.reason}; scoreboard change at {first:.0f}s "
                        f"reverted at {second:.0f}s"
                    ),
                )
                relabelled.add(index)

    if not any(segment.event == "other" for segment in result):
        return result

    samples = extract_audio(video)
    whistles = audio_cues.find_whistles(samples)
    for index, segment in enumerate(result):
        if segment.event != "other":
            continue
        whistle = next(
            (
                (start, end)
                for start, end in whistles
                if segment.start <= start < segment.end
            ),
            None,
        )
        if whistle is None:
            continue
        whistle_start, whistle_end = whistle
        stoppage = audio_cues.stoppage_after(samples, whistle_end)
        if stoppage < RED_MIN_STOP:
            continue
        red_frames = int(
            (
                red_share(sample_frames(video, whistle_end, CLOSEUP_LOOK))
                >= RED_SHARE
            ).sum()
        )
        booing = booing_seconds(samples, whistle_end, whistle_end + stoppage)
        event = classify(stoppage, booing, red_frames)
        if event == "red_card":
            result[index] = replace(
                segment,
                event=event,
                event_confidence=CONF_RED,
                reason=(
                    f"{segment.reason}; whistle at {whistle_start:.0f}s, "
                    f"stoppage {stoppage:.0f}s, red close-up"
                ),
            )
        elif event == "controversy":
            result[index] = replace(
                segment,
                event=event,
                event_confidence=CONF_CONTRO,
                reason=(
                    f"{segment.reason}; whistle at {whistle_start:.0f}s, "
                    f"stoppage {stoppage:.0f}s, booing {booing:.0f}s"
                ),
            )
    return result
