import shutil
import subprocess
import re

import numpy as np

import pytest

from sportscut.media import (
    MediaError,
    SAMPLE_RATE,
    extract_audio,
    find_tool,
    probe_duration,
)


@pytest.mark.parametrize("name", ["ffmpeg", "ffprobe"])
def test_find_tool_missing_raises_exact_message(name, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(MediaError) as exc:
        find_tool(name)

    assert str(exc.value) == f"{name} not found on PATH; install ffmpeg"


def test_find_tool_returns_path_from_path(require_ffmpeg):
    assert find_tool("ffmpeg") == shutil.which("ffmpeg")


def test_sample_rate_contract():
    assert SAMPLE_RATE == 16_000
    assert issubclass(MediaError, RuntimeError)


def test_probe_duration_without_ffprobe(monkeypatch, tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path))

    with pytest.raises(MediaError) as exc:
        probe_duration(path)

    assert str(exc.value) == "ffprobe not found on PATH; install ffmpeg"


def test_missing_file_raises_for_probe_duration(tmp_path):
    path = tmp_path / "missing.mp4"
    with pytest.raises(MediaError) as exc:
        probe_duration(path)
    assert str(exc.value) == f"media file not found: {path}"


def test_probe_duration_without_duration_value(monkeypatch, tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"")
    monkeypatch.setattr("sportscut.media.find_tool", lambda name: "ffprobe")
    result = subprocess.CompletedProcess([], 0, stdout="N/A\n", stderr="")
    monkeypatch.setattr("sportscut.media.subprocess.run", lambda *a, **k: result)

    with pytest.raises(MediaError) as exc:
        probe_duration(path)

    assert str(exc.value) == f"ffprobe returned no duration for {path}"


def test_probe_duration_rejects_non_media(require_ffmpeg, tmp_path):
    path = tmp_path / "bad.mp4"
    path.write_text("not a video")
    prefix = re.escape(f"ffprobe failed for {path}: ")
    with pytest.raises(MediaError, match=f"^{prefix}.+"):
        probe_duration(path)


def test_probe_duration_of_synthetic_video(synthetic_video):
    duration = probe_duration(synthetic_video)
    assert type(duration) is float
    assert duration == pytest.approx(6.0, abs=0.15)


def test_extract_audio_without_ffmpeg(monkeypatch, tmp_path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(MediaError) as exc:
        extract_audio(path)
    assert str(exc.value) == "ffmpeg not found on PATH; install ffmpeg"


def test_missing_file_raises_for_extract_audio(tmp_path):
    path = tmp_path / "missing.mp4"
    with pytest.raises(MediaError) as exc:
        extract_audio(path)
    assert str(exc.value) == f"media file not found: {path}"


def test_extract_audio_rejects_non_media(require_ffmpeg, tmp_path):
    path = tmp_path / "bad.mp4"
    path.write_text("not a video")
    prefix = re.escape(f"ffmpeg failed for {path}: ")
    with pytest.raises(MediaError, match=f"^{prefix}.+"):
        extract_audio(path)


def test_extract_audio_is_mono_16k_float32(synthetic_video):
    audio = extract_audio(synthetic_video)
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert abs(audio.size - 6 * SAMPLE_RATE) <= 1600
    assert np.abs(audio).max() <= 1.0
    assert audio.flags.writeable
