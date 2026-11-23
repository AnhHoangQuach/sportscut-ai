import re, shutil, subprocess
import numpy as np
import pytest
from sportscut.media import MediaError, SAMPLE_RATE, extract_audio, find_tool, probe_duration

@pytest.mark.parametrize("name", ["ffmpeg", "ffprobe"])
def test_find_tool_missing_raises_exact_message(name, monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(MediaError) as exc: find_tool(name)
    assert str(exc.value) == f"{name} not found on PATH; install ffmpeg"

def test_find_tool_returns_path_from_path(require_ffmpeg):
    assert find_tool("ffmpeg") == shutil.which("ffmpeg")
    assert SAMPLE_RATE == 16_000 and issubclass(MediaError, RuntimeError)

@pytest.mark.parametrize("function,tool", [(probe_duration, "ffprobe"), (extract_audio, "ffmpeg")])
def test_media_operation_without_tool(function, tool, monkeypatch, tmp_path):
    path = tmp_path / "clip.mp4"; path.write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(MediaError) as exc: function(path)
    assert str(exc.value) == f"{tool} not found on PATH; install ffmpeg"

@pytest.mark.parametrize("function", [probe_duration, extract_audio])
def test_missing_file_raises(function, tmp_path):
    path = tmp_path / "missing.mp4"
    with pytest.raises(MediaError) as exc: function(path)
    assert str(exc.value) == f"media file not found: {path}"

def test_probe_duration_without_duration_value(monkeypatch, tmp_path):
    path = tmp_path / "clip.mp4"; path.write_bytes(b"")
    monkeypatch.setattr("sportscut.media.find_tool", lambda name: "ffprobe")
    result = subprocess.CompletedProcess([], 0, stdout="N/A\n", stderr="")
    monkeypatch.setattr("sportscut.media.subprocess.run", lambda *a, **k: result)
    with pytest.raises(MediaError) as exc: probe_duration(path)
    assert str(exc.value) == f"ffprobe returned no duration for {path}"

@pytest.mark.parametrize("function,tool", [(probe_duration, "ffprobe"), (extract_audio, "ffmpeg")])
def test_rejects_non_media(function, tool, require_ffmpeg, tmp_path):
    path = tmp_path / "bad.mp4"; path.write_text("not a video")
    with pytest.raises(MediaError, match="^" + re.escape(f"{tool} failed for {path}: ") + ".+"):
        function(path)

def test_probe_duration_of_synthetic_video(synthetic_video):
    duration = probe_duration(synthetic_video)
    assert type(duration) is float and duration == pytest.approx(6.0, abs=0.15)

def test_extract_audio_is_mono_16k_float32(synthetic_video):
    audio = extract_audio(synthetic_video)
    assert audio.dtype == np.float32 and audio.ndim == 1 and audio.flags.writeable
    assert abs(audio.size - 6 * SAMPLE_RATE) <= 1600 and np.abs(audio).max() <= 1.0
