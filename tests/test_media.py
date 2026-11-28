import json, re, shutil, subprocess
from pathlib import Path
import numpy as np
import pytest
from sportscut.media import (
    MediaError,
    SAMPLE_RATE,
    concat_clips,
    cut_clip,
    extract_audio,
    find_tool,
    has_audio,
    probe_duration,
    probe_size,
    require_ffmpeg,
    sample_top_band,
)


def test_sample_top_band_shape_and_values(synthetic_video):
    frames = sample_top_band(synthetic_video)

    assert frames.dtype == np.uint8
    assert frames.shape[0] in (6, 7)
    assert frames.shape[1:] == (30, 160)
    assert frames[1].mean() < 64
    assert frames[4].mean() > 192


def test_sample_top_band_single_ffmpeg_call_with_filter(monkeypatch, tmp_path):
    path = tmp_path / "clip.mp4"
    path.touch()
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout=bytes(2 * 30 * 160), stderr=b"")

    monkeypatch.setattr("sportscut.media.find_tool", lambda name: "ffmpeg")
    monkeypatch.setattr("sportscut.media.subprocess.run", fake_run)

    frames = sample_top_band(path)

    assert frames.shape == (2, 30, 160)
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert "-i" in args and "-an" in args
    assert "fps=1,scale=160:90,format=gray,crop=160:30:0:0" in args
    assert kwargs == {"capture_output": True, "check": False}


def test_sample_top_band_missing_file_without_ffmpeg(monkeypatch, tmp_path):
    path = tmp_path / "missing.mp4"
    monkeypatch.setenv("PATH", "/nonexistent")

    with pytest.raises(MediaError) as exc:
        sample_top_band(path)

    assert str(exc.value) == f"media file not found: {path}"


def test_sample_top_band_non_media_file_raises(require_ffmpeg, tmp_path):
    path = tmp_path / "bad.mp4"
    path.write_text("not a video")

    with pytest.raises(
        MediaError,
        match="^" + re.escape(f"ffmpeg failed for {path}: ") + ".+",
    ):
        sample_top_band(path)

def test_concat_clips_empty_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="^no clips to concatenate$"):
        concat_clips([], tmp_path / "out.mp4")

def test_concat_clips_missing_clip(monkeypatch, tmp_path):
    missing = tmp_path / "missing.mp4"
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(MediaError) as exc:
        concat_clips([missing], tmp_path / "out.mp4")
    assert str(exc.value) == f"media file not found: {missing}"

def test_concat_clips_bad_file(require_ffmpeg, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_text("not a video")
    with pytest.raises(MediaError, match="^" + re.escape(f"ffmpeg failed for {tmp_path / 'out.mp4'}: ") + ".+"):
        concat_clips([bad], tmp_path / "out.mp4")

def test_concat_clips_joins_in_order(synthetic_video, tmp_path):
    first = cut_clip(synthetic_video, 0.5, 1.5, tmp_path / "a.mp4")
    second = cut_clip(synthetic_video, 4.0, 5.0, tmp_path / "it's.mp4")
    dest = tmp_path / "joined.mp4"

    assert concat_clips([first, second], dest) == dest
    assert probe_duration(dest) == pytest.approx(2.0, abs=0.5)
    assert _gray_mean(dest, 0.3) < 64
    assert _gray_mean(dest, 1.5) > 192
    assert list(tmp_path.glob("*.txt")) == []

def _video_only(tmp_path: Path) -> Path:
    path = tmp_path / "video_only.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
        "color=c=black:s=160x120:r=5:d=3", "-c:v", "mpeg4", "-q:v", "5",
        "-pix_fmt", "yuv420p", str(path),
    ], check=True)
    return path

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

def test_has_audio_true_for_synthetic_video(synthetic_video):
    assert has_audio(synthetic_video) is True

def test_has_audio_false_for_video_only(require_ffmpeg, tmp_path):
    assert has_audio(_video_only(tmp_path)) is False

def test_has_audio_missing_file_raises(tmp_path):
    path = tmp_path / "missing.mp4"
    with pytest.raises(MediaError) as exc:
        has_audio(path)
    assert str(exc.value) == f"media file not found: {path}"

def test_has_audio_rejects_non_media(require_ffmpeg, tmp_path):
    path = tmp_path / "bad.mp4"
    path.write_text("not a video")
    with pytest.raises(MediaError, match="^" + re.escape(f"ffprobe failed for {path}: ") + ".+"):
        has_audio(path)

def test_require_ffmpeg_missing_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(MediaError) as exc:
        require_ffmpeg()
    assert str(exc.value) == "ffmpeg not found on PATH; install ffmpeg"

def test_require_ffmpeg_ok(require_ffmpeg):
    assert globals()["require_ffmpeg"]() is None

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
    assert audio.dtype == np.float32 and audio.ndim == 1 and not audio.flags.writeable
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


def test_probe_size_of_synthetic_video(synthetic_video):
    assert probe_size(synthetic_video) == (160, 120)


def test_probe_size_missing_file_raises(tmp_path):
    path = tmp_path / "missing.mp4"
    with pytest.raises(MediaError) as exc:
        probe_size(path)
    assert str(exc.value) == f"media file not found: {path}"


def test_probe_size_audio_only_raises(require_ffmpeg, tmp_path):
    path = tmp_path / "audio.wav"
    subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
        "anoisesrc=d=0.1", str(path),
    ], check=True, capture_output=True)
    with pytest.raises(MediaError) as exc:
        probe_size(path)
    assert str(exc.value) == f"no video stream in {path}"


from sportscut.media import sample_frames  # noqa: E402  (T-045, append-only)


def test_sample_frames_shape_and_content(synthetic_video):
    frames = sample_frames(synthetic_video, 5, 80, 60)
    assert isinstance(frames, np.ndarray) and frames.dtype == np.uint8
    assert frames.ndim == 4 and frames.shape[1:] == (60, 80, 3)
    assert 29 <= frames.shape[0] <= 31
    assert all(frames[i].mean() < 30 for i in range(14))
    assert all(frames[i].mean() > 225 for i in range(16, frames.shape[0]))


def test_sample_frames_missing_file(monkeypatch, tmp_path):
    path = tmp_path / "missing.mp4"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("ffmpeg ran"))
    with pytest.raises(MediaError) as exc:
        sample_frames(path, 5, 80, 60)
    assert str(exc.value) == f"media file not found: {path}"


def test_sample_frames_audio_only_raises(require_ffmpeg, tmp_path):
    path = tmp_path / "audio.m4a"
    subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
        "anullsrc=d=1", "-c:a", "aac", str(path),
    ], check=True, capture_output=True)
    with pytest.raises(MediaError, match="^" + re.escape(f"ffmpeg failed for {path}: ")):
        sample_frames(path, 5, 80, 60)


from sportscut.media import filter_video  # noqa: E402  (T-043, appended)


def test_filter_video_missing_file_raises(tmp_path):
    path = tmp_path / "missing.mp4"
    with pytest.raises(MediaError) as exc:
        filter_video(path, "scale=32:24", tmp_path / "o.mp4")
    assert str(exc.value) == f"media file not found: {path}"


def test_filter_video_scales_and_copies_audio(synthetic_video, tmp_path):
    dest = tmp_path / "o.mp4"
    assert filter_video(synthetic_video, "scale=32:24", dest) == dest
    assert probe_size(dest) == (32, 24)
    args = ["ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type,codec_name", "-of", "json", "-i", str(dest)]
    streams = json.loads(subprocess.run(
        args, check=True, capture_output=True, text=True
    ).stdout)["streams"]
    assert [s["codec_name"] for s in streams if s["codec_type"] == "video"] == ["h264"]
    assert [s["codec_name"] for s in streams if s["codec_type"] == "audio"] == ["aac"]


def test_filter_video_invalid_filter_raises(synthetic_video, tmp_path):
    with pytest.raises(MediaError, match=r"^ffmpeg failed for .+: .+"):
        filter_video(synthetic_video, "nosuchfilter", tmp_path / "o.mp4")


def test_only_media_module_imports_subprocess():
    root = Path(__file__).resolve().parents[1] / "sportscut"
    importers = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if re.search(r"^\s*(import subprocess|from subprocess import)", path.read_text(encoding="utf-8"), re.M)
    )
    # events/incidents.py predates T-043 (T-015 decision, DECISIONS.md) and is
    # out of this task's scope; T-043 must add no new importer.
    assert importers == ["events/incidents.py", "media.py"]
    assert "vertical.py" not in importers


# T-021: find_font through fontconfig (appended)
import sportscut.media as media_mod  # noqa: E402
from sportscut.media import find_font  # noqa: E402


class _Done:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def _fake_fontconfig(monkeypatch, fc_list, fc_match, missing=()):
    calls = []

    def which(name):
        return None if name in missing else f"/bin/{name}"

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return fc_list if args[0] == "/bin/fc-list" else fc_match

    monkeypatch.setattr(media_mod.shutil, "which", which)
    monkeypatch.setattr(media_mod.subprocess, "run", run)
    return calls


@pytest.mark.parametrize("tool", ["fc-list", "fc-match"])
def test_find_font_tool_missing_raises(monkeypatch, tmp_path, tool):
    font = tmp_path / "a.ttf"
    font.write_bytes(b"x")
    _fake_fontconfig(monkeypatch, _Done(f"{font}\n"), _Done(f"{font}\n"), missing=(tool,))
    with pytest.raises(MediaError) as exc:
        find_font()
    assert str(exc.value) == f"{tool} not found on PATH; install fontconfig to draw captions"


def test_find_font_no_existing_font_raises(monkeypatch, tmp_path):
    listed = f"{tmp_path / 'gone.ttf'}\n\n"
    _fake_fontconfig(monkeypatch, _Done(listed), _Done(""))
    with pytest.raises(MediaError) as exc:
        find_font()
    assert str(exc.value) == (
        "no font with Vietnamese support found; install one (for example "
        "DejaVu Sans or Noto Sans) and check with: fc-list :lang=vi"
    )


def test_find_font_fc_list_failure_raises(monkeypatch):
    _fake_fontconfig(monkeypatch, _Done("", 1, "boom\n"), _Done(""))
    with pytest.raises(MediaError) as exc:
        find_font()
    assert str(exc.value) == "fc-list failed: boom"


def test_find_font_follows_fc_match_order(monkeypatch, tmp_path):
    a, b = tmp_path / "A.ttf", tmp_path / "B.ttf"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    calls = _fake_fontconfig(
        monkeypatch,
        _Done(f"{a}\n {b} \n"),
        _Done(f"{tmp_path / 'other.ttf'}\n{b}\n{a}\n"),
    )
    assert find_font() == b
    assert [args for args, _ in calls] == [
        ["/bin/fc-list", "--format", "%{file}\n", ":lang=vi"],
        ["/bin/fc-match", "-s", "--format", "%{file}\n", "sans-serif:lang=vi"],
    ]
    assert all(
        kwargs == {"capture_output": True, "check": False, "text": True}
        for _, kwargs in calls
    )


@pytest.mark.parametrize("fc_match", [_Done("", 1, "bad"), _Done("/nowhere.ttf\n")])
def test_find_font_falls_back_to_sorted_first(monkeypatch, tmp_path, fc_match):
    a, b = tmp_path / "A.ttf", tmp_path / "B.ttf"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    _fake_fontconfig(monkeypatch, _Done(f"{b}\n{a}\n"), fc_match)
    assert find_font() == a


def test_find_font_real_fontconfig():
    if shutil.which("fc-list") is None or shutil.which("fc-match") is None:
        pytest.skip("fontconfig is not on PATH")
    try:
        font = find_font()
    except MediaError as exc:
        pytest.skip(str(exc))
    assert font.is_file()
