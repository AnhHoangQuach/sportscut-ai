import json, re, shutil, subprocess
from pathlib import Path
import numpy as np
import pytest
from sportscut.media import (
    MediaError,
    SAMPLE_RATE,
    cut_clip,
    extract_audio,
    find_tool,
    probe_duration,
)

def _gray_mean(video: Path, time: float) -> float:
    args = ["ffmpeg", "-v", "error", "-nostdin", "-ss", str(time), "-i",
            str(video), "-frames:v", "1", "-vf", "scale=8:6,format=gray",
            "-f", "rawvideo", "pipe:1"]
    output = subprocess.run(args, check=True, capture_output=True).stdout
    assert len(output) == 48
    return float(np.frombuffer(output, np.uint8).mean())

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

def test_cut_clip_missing_file_raises(tmp_path):
    path = tmp_path / "missing.mp4"
    with pytest.raises(MediaError) as exc:
        cut_clip(path, 0, 1, tmp_path / "out.mp4")
    assert str(exc.value) == f"media file not found: {path}"

def test_cut_clip_without_tool(monkeypatch, tmp_path):
    path = tmp_path / "clip.mp4"; path.write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(MediaError) as exc:
        cut_clip(path, 0, 1, tmp_path / "out.mp4")
    assert str(exc.value) == "ffmpeg not found on PATH; install ffmpeg"

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

def test_cut_clip_rejects_non_media(require_ffmpeg, tmp_path):
    path = tmp_path / "bad.mp4"; path.write_text("not a video")
    with pytest.raises(MediaError, match="^" + re.escape(f"ffmpeg failed for {path}: ") + ".+"):
        cut_clip(path, 0, 1, tmp_path / "out.mp4")

def test_cut_clip_is_accurate_h264(synthetic_video, tmp_path):
    dest = tmp_path / "c.mp4"
    assert cut_clip(synthetic_video, 3.2, 5.2, dest) == dest
    assert probe_duration(dest) == pytest.approx(2.0, abs=0.5)
    args = ["ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type,codec_name", "-of", "json", "-i", str(dest)]
    streams = json.loads(subprocess.run(
        args, check=True, capture_output=True, text=True
    ).stdout)["streams"]
    assert [s["codec_name"] for s in streams if s["codec_type"] == "video"] == ["h264"]
    assert [s["codec_name"] for s in streams if s["codec_type"] == "audio"] == ["aac"]
    assert _gray_mean(dest, 0.05) > 192
