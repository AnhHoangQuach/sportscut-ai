import json
from pathlib import Path
import subprocess

import numpy as np
import pytest

from sportscut.media import SAMPLE_RATE, extract_audio, probe_duration


def _gray_mean(video: Path, time: float) -> float:
    args = [
        "ffmpeg", "-v", "error", "-nostdin", "-ss", str(time),
        "-i", str(video), "-frames:v", "1", "-vf",
        "scale=8:6,format=gray", "-f", "rawvideo", "pipe:1",
    ]
    output = subprocess.run(args, check=True, capture_output=True).stdout
    assert len(output) == 48
    return float(np.frombuffer(output, np.uint8).mean())


def _rms(audio: np.ndarray, start: float, end: float) -> float:
    window = audio[int(start * SAMPLE_RATE):int(end * SAMPLE_RATE)]
    return float(np.sqrt(np.mean(np.square(window))))


def test_synthetic_video_is_temporary_and_six_seconds(synthetic_video):
    repository = Path(__file__).resolve().parents[1]
    assert synthetic_video.exists()
    assert not synthetic_video.is_relative_to(repository)
    assert probe_duration(synthetic_video) == pytest.approx(6.0, abs=0.15)


def test_synthetic_video_streams(synthetic_video):
    args = [
        "ffprobe", "-v", "error", "-show_entries",
        "stream=codec_type,width,height,channels,sample_rate", "-of", "json",
        "-i", str(synthetic_video),
    ]
    data = json.loads(subprocess.run(args, check=True, capture_output=True, text=True).stdout)
    video = [stream for stream in data["streams"] if stream["codec_type"] == "video"]
    audio = [stream for stream in data["streams"] if stream["codec_type"] == "audio"]
    assert len(video) == len(audio) == 1
    assert (video[0]["width"], video[0]["height"]) == (160, 120)
    assert audio[0]["channels"] == 2
    assert audio[0]["sample_rate"] == "44100"


def test_synthetic_video_has_one_scene_change_at_3s(synthetic_video):
    assert all(_gray_mean(synthetic_video, t) < 64 for t in (0.5, 1.5, 2.5))
    assert all(_gray_mean(synthetic_video, t) > 192 for t in (3.5, 4.5, 5.5))


def test_synthetic_video_has_audio_burst(synthetic_video):
    audio = extract_audio(synthetic_video)
    burst = _rms(audio, 2.2, 2.8)
    assert burst >= 5 * _rms(audio, 0.2, 1.8)
    assert burst >= 5 * _rms(audio, 3.5, 5.5)
