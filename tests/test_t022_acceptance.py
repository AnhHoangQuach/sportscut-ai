"""T-022 Tester acceptance tests (commentary subtitles on vertical clips).

Written from the acceptance criteria in .office/TASK.md, independently of the
Developer's tests. Media is generated with ffmpeg in temporary directories only.
Assertions that compare against live `main` or that require a file to END with a
T-022 section are gated to branches starting with `office/T-022` (Tech Lead
decision, item 4), so they do not trap later tasks.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import types
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import sportscut.pipeline
import sportscut.reframe
import sportscut.subtitles
import sportscut.vertical
from sportscut import cli, media, subtitles, vertical
from sportscut.media import MediaError
from sportscut.models import Segment
from sportscut.pipeline import PipelineError

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git") or "/usr/bin/git"
T004_SPEC = "docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md"
T021_SPEC = "docs/superpowers/specs/2026-11-23-t-021-overlay-the-live-broadcast-scoreboard-and-design.md"
T043_SPEC = "docs/superpowers/specs/2026-11-24-t-043-render-vertical-9-16-clips-from-design.md"
VERT_HEADING = "## Video dọc 9:16 cho TikTok/Reels (cut --vertical)"
CROP_HEADING = "## Video dọc 9:16: đo khung cắt (eval-crop)"
FONT = "/fonts/DejaVuSans.ttf"
OLD_FILTER = "crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1"
BS3 = "\\" * 3
DRAWTEXT_34 = (
    f"drawtext=fontfile=/fonts/DejaVuSans.ttf:text=BÀN THẮNG · 34{BS3}':expansion=none:"
    "fontsize=64:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=16:x=(w-text_w)/2:y=240"
)
BOX_GRAPH = (
    "split=2[sc_main][sc_box];[sc_main]crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,"
    "setsar=1[sc_v];[sc_box]crop=w=160:h=40:x=40:y=16,scale=640:160,setsar=1[sc_b];"
    "[sc_v][sc_b]overlay=x=220:y=40"
)
BOX = (40, 16, 160, 40)
NOTICE = (
    "sportscut: notice: subtitles need the [asr] extra: pip install 'sportscut[asr]'; "
    "vertical clips are rendered without subtitles\n"
)
TWELVE = "aaaa bbbb cccc dddd eeee ffff gggg hhhh iiii jjjj kkkk llll"
TWELVE_SRT = (
    "1\n00:00:00,000 --> 00:00:04,800\naaaa bbbb cccc dddd eeee\nffff gggg hhhh iiii jjjj\n\n"
    "2\n00:00:04,800 --> 00:00:05,700\nkkkk llll\n\n"
)
VI_LONG = (
    "Vào rồi! Một bàn thắng tuyệt đẹp của đội chủ nhà ở phút cuối cùng của trận đấu, "
    "thủ môn đội khách hoàn toàn bất lực trước cú sút căng như kẻ chỉ"
)
KEYS = ["start", "end", "score", "reason", "event", "event_confidence", "file"]
GOAL_SEGMENT = Segment(2.0, 8.0, 1.0, "r", "goal", 0.9)
OTHER_SEGMENT = Segment(2.0, 8.0, 1.0, "r", "other", 0.0)
GOAL_CAPTION = "BÀN THẮNG · 1'"


def _run(*args, **kw):
    return subprocess.run(list(args), capture_output=True, text=True, **kw)


def _branch() -> str:
    result = _run(GIT, "rev-parse", "--abbrev-ref", "HEAD", cwd=ROOT)
    return result.stdout.strip() if result.returncode == 0 else ""


def _on_t022_branch() -> bool:
    return _branch().startswith("office/T-022")


own_branch = pytest.mark.skipif(not _on_t022_branch(), reason="only checked on office/T-022 branches")


def _merge_base() -> str:
    result = _run(GIT, "merge-base", "main", "HEAD", cwd=ROOT)
    if result.returncode != 0:
        pytest.skip("no main branch to compare with")
    return result.stdout.strip()


def _show(ref_path: str) -> str:
    result = _run(GIT, "show", ref_path, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    return result.stdout


class FakeTranscriber:
    def __init__(self, items=(), exc=None):
        self.items = list(items)
        self.exc = exc
        self.calls = []

    def transcribe(self, audio):
        self.calls.append(audio)
        if self.exc is not None:
            raise self.exc
        return list(self.items)


def _fake_faster_whisper(download_result="/cache/base", download_exc=None):
    mod = types.ModuleType("faster_whisper")
    mod.inits = []
    mod.calls = []
    mod.downloads = []

    class WhisperModel:
        def __init__(self, *args, **kwargs):
            mod.inits.append((args, kwargs))

        def transcribe(self, audio, **kwargs):
            mod.calls.append((audio, kwargs))
            segs = [SimpleNamespace(start=0.25, end=1.5, text=" Vào rồi"),
                    SimpleNamespace(start=2.0, end=3.0, text=" goal")]
            return iter(segs), SimpleNamespace(language="vi")

    def download_model(name, *args, **kwargs):
        mod.downloads.append((name, args, kwargs))
        if download_exc is not None:
            raise download_exc
        return download_result

    mod.WhisperModel = WhisperModel
    mod.download_model = download_model
    return mod


# ---------------------------------------------------------------- AC1
def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_ac1_asr_extra_declared():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert extras["asr"] == ["faster-whisper>=1.0"]
    assert not any("whisper" in dep for dep in extras["dev"])
    assert not any("whisper" in dep for dep in _pyproject()["project"]["dependencies"])


def test_ac1_other_extras_unchanged():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert extras["api"] == ["fastapi>=0.110", "uvicorn>=0.29", "python-multipart>=0.0.9"]
    assert extras["youtube"] == ["yt-dlp>=2024.8.6"]
    assert extras["dev"] == ["pytest>=8", "httpx>=0.27", "fastapi>=0.110", "uvicorn>=0.29",
                             "python-multipart>=0.0.9"]


@own_branch
def test_ac1_other_extras_equal_merge_base():
    base = tomllib.loads(_show(f"{_merge_base()}:pyproject.toml"))["project"]["optional-dependencies"]
    extras = _pyproject()["project"]["optional-dependencies"]
    for key in ("api", "youtube", "dev"):
        assert extras[key] == base[key], key


def test_ac1_no_model_or_media_files_tracked():
    files = _run(GIT, "ls-files", cwd=ROOT).stdout.splitlines()
    bad = [f for f in files if f.endswith((".bin", ".pt", ".onnx", ".safetensors", ".mp4"))]
    assert bad == []


# ---------------------------------------------------------------- AC2
def test_ac2_fresh_import_does_not_load_faster_whisper():
    code = ("import sys, sportscut.cli, sportscut.subtitles; "
            "print('faster_whisper' in sys.modules, 'ctranslate2' in sys.modules)")
    result = _run(sys.executable, "-c", code, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False False"


def test_ac2_no_subprocess_in_subtitles_and_only_two_importers():
    assert "subprocess" not in (ROOT / "sportscut" / "subtitles.py").read_text(encoding="utf-8")
    importers = sorted(
        p.relative_to(ROOT / "sportscut").as_posix()
        for p in (ROOT / "sportscut").rglob("*.py")
        if re.search(r"^\s*(import subprocess|from subprocess import)", p.read_text(encoding="utf-8"), re.M)
    )
    assert importers == ["events/incidents.py", "media.py"]
    for name in ("vertical.py", "pipeline.py", "cli.py"):
        assert "subprocess" not in (ROOT / "sportscut" / name).read_text(encoding="utf-8"), name


# ---------------------------------------------------------------- AC3
@pytest.mark.parametrize("t, expected", [
    (0, "00:00:00,000"), (4.8, "00:00:04,800"), (3725.25, "01:02:05,250"),
    (59.9996, "00:01:00,000"), (0.0004, "00:00:00,000"), (5.7, "00:00:05,700"),
])
def test_ac3_srt_time(t, expected):
    assert subtitles.srt_time(t) == expected


def test_ac3_write_srt_creates_dirs_utf8_lf(tmp_path):
    path = tmp_path / "a" / "b" / "clip_01.srt"
    cues = [(0.5, 2.0, "Vào rồi!\nhay quá"), (2.0, 3.25, "đội khách")]
    result = subtitles.write_srt(cues, str(path))
    assert isinstance(result, Path) and result == path
    raw = path.read_bytes()
    assert b"\r" not in raw
    assert raw.decode("utf-8") == (
        "1\n00:00:00,500 --> 00:00:02,000\nVào rồi!\nhay quá\n\n"
        "2\n00:00:02,000 --> 00:00:03,250\nđội khách\n\n"
    )


def test_ac3_write_srt_empty_is_zero_bytes(tmp_path):
    path = tmp_path / "x" / "empty.srt"
    assert subtitles.write_srt([], path) == Path(path)
    assert path.exists() and path.stat().st_size == 0


def test_ac3_write_srt_overwrites(tmp_path):
    path = tmp_path / "c.srt"
    path.write_text("old junk\n" * 10, encoding="utf-8")
    subtitles.write_srt([], path)
    assert path.stat().st_size == 0


# ---------------------------------------------------------------- AC4
def test_ac4_short_cue_unchanged():
    assert subtitles.layout([(1.0, 2.5, "Vào rồi")]) == [(1.0, 2.5, "Vào rồi")]


def test_ac4_two_line_cue_keeps_times():
    text = "aaaa bbbb cccc dddd eeee ffff gggg"
    out = subtitles.layout([(1.0, 3.0, text)])
    assert len(out) == 1 and out[0][:2] == (1.0, 3.0)
    assert out[0][2] == "aaaa bbbb cccc dddd eeee\nffff gggg"


def test_ac4_twelve_words_split_and_srt(tmp_path):
    out = subtitles.layout([(0.0, 5.7, TWELVE)])
    assert len(out) == 2
    (s1, e1, t1), (s2, e2, t2) = out
    assert s1 == 0.0 and e1 == pytest.approx(4.8, abs=1e-9)
    assert t1 == "aaaa bbbb cccc dddd eeee\nffff gggg hhhh iiii jjjj"
    assert s2 == pytest.approx(4.8, abs=1e-9) and e2 == 5.7 and t2 == "kkkk llll"
    path = subtitles.write_srt(out, tmp_path / "x.srt")
    assert path.read_text(encoding="utf-8") == TWELVE_SRT


def test_ac4_limits_and_contiguity_vietnamese():
    cues = [(3.0, 11.0, VI_LONG), (12.0, 13.0, "x" * 70)]
    out = subtitles.layout(cues)
    assert len(out) > 2
    for _, _, text in out:
        lines = text.split("\n")
        assert 1 <= len(lines) <= 2
        assert all(0 < len(line) <= 28 for line in lines)
    vi = [c for c in out if c[0] < 12.0]
    assert vi[0][0] == 3.0 and vi[-1][1] == 11.0
    for a, b in zip(vi, vi[1:]):
        assert a[1] == pytest.approx(b[0]) and a[0] < a[1]
    # no text lost (only whitespace changes)
    assert " ".join(" ".join(c[2].split("\n")) for c in vi).split() == VI_LONG.split()
    longword = [c for c in out if c[0] >= 12.0]
    assert "".join(c[2].replace("\n", "") for c in longword) == "x" * 70


def test_ac4_empty_input():
    assert subtitles.layout([]) == []


# ---------------------------------------------------------------- AC5
AC5_ITEMS = [(2.0, 3.5, "  hai  "), (-0.2, 1.0, "Vào rồi!"), (1.5, 1.5, "x"),
             (4.0, 9.0, "cuối"), (2.5, 3.0, "   ")]


def _patch_audio(monkeypatch, audio):
    seen = []

    def fake_extract(path):
        seen.append(path)
        return audio

    monkeypatch.setattr(media, "extract_audio", fake_extract)
    return seen


def test_ac5_normalise_clamp_sort(monkeypatch):
    audio = np.zeros(96000, np.float32)
    seen = _patch_audio(monkeypatch, audio)
    fake = FakeTranscriber(AC5_ITEMS)
    clip = Path("/x/out/clip_01.mp4")
    result = subtitles.transcribe(clip, fake)
    assert result == [(0.0, 1.0, "Vào rồi!"), (2.0, 3.5, "hai"), (4.0, 6.0, "cuối")]
    assert len(fake.calls) == 1 and fake.calls[0] is audio
    assert seen == [clip]
    assert all(isinstance(c[0], float) and isinstance(c[1], float) for c in result)


def test_ac5_nfd_becomes_nfc(monkeypatch):
    _patch_audio(monkeypatch, np.zeros(32000, np.float32))
    nfd = unicodedata.normalize("NFD", "Vào rồi! Bàn thắng")
    assert nfd != "Vào rồi! Bàn thắng"
    result = subtitles.transcribe("clip_01.mp4", FakeTranscriber([(0.0, 1.0, nfd)]))
    assert result == [(0.0, 1.0, "Vào rồi! Bàn thắng")]
    assert unicodedata.is_normalized("NFC", result[0][2])


def test_ac5_empty_audio_skips_transcriber(monkeypatch):
    _patch_audio(monkeypatch, np.zeros(0, np.float32))
    fake = FakeTranscriber([(0.0, 1.0, "x")])
    assert subtitles.transcribe("clip_01.mp4", fake) == []
    assert fake.calls == []


def test_ac5_errors_wrapped(monkeypatch):
    _patch_audio(monkeypatch, np.zeros(16000, np.float32))
    with pytest.raises(subtitles.TranscriptionError) as exc:
        subtitles.transcribe(Path("/tmp/out/clip_01.mp4"), FakeTranscriber(exc=RuntimeError("boom")))
    assert str(exc.value) == "speech-to-text failed for clip_01.mp4: boom"
    assert isinstance(exc.value, RuntimeError)


def test_ac5_generator_errors_wrapped(monkeypatch):
    """A lazy transcriber that fails while iterating is also a TranscriptionError."""
    _patch_audio(monkeypatch, np.zeros(16000, np.float32))

    class Lazy:
        def transcribe(self, audio):
            yield (0.0, 0.5, "a")
            raise ValueError("late")

    with pytest.raises(subtitles.TranscriptionError, match="^speech-to-text failed for c.mp4: late$"):
        subtitles.transcribe("c.mp4", Lazy())


def test_ac5_media_error_propagates(monkeypatch):
    def boom(path):
        raise MediaError("no audio")

    monkeypatch.setattr(media, "extract_audio", boom)
    with pytest.raises(MediaError):
        subtitles.transcribe("c.mp4", FakeTranscriber())


def test_ac5_real_silent_clip(require_ffmpeg, tmp_path):
    """Real extract_audio on a silent 2 s clip: the transcriber gets ~2 s of 16 kHz float32."""
    clip = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x120:r=10:d=2",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "2", "-c:v", "mpeg4", "-c:a", "aac",
         str(clip)], check=True, capture_output=True)
    fake = FakeTranscriber([])
    assert subtitles.transcribe(clip, fake) == []
    assert len(fake.calls) == 1
    audio = fake.calls[0]
    assert audio.dtype == np.float32 and audio.ndim == 1
    assert abs(audio.size / media.SAMPLE_RATE - 2.0) < 0.15


# ---------------------------------------------------------------- AC6
def test_ac6_whisper_lazy_once_auto_language(monkeypatch):
    fw = _fake_faster_whisper()
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    tr = subtitles.WhisperTranscriber()
    assert fw.inits == []
    a1 = np.zeros(16000, np.float32)
    a2 = np.ones(8000, np.float32)
    r1 = tr.transcribe(a1)
    r2 = tr.transcribe(a2)
    assert fw.inits == [(("base",), {"device": "cpu", "compute_type": "int8"})]
    assert len(fw.calls) == 2
    assert fw.calls[0][0] is a1 and fw.calls[1][0] is a2
    for _, kwargs in fw.calls:
        assert "language" in kwargs and kwargs["language"] is None
        assert kwargs["vad_filter"] is True
    assert [tuple(x) for x in r1] == [(0.25, 1.5, " Vào rồi"), (2.0, 3.0, " goal")]
    assert [tuple(x) for x in r2] == [tuple(x) for x in r1]


def test_ac6_whisper_through_transcribe(monkeypatch):
    fw = _fake_faster_whisper()
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    _patch_audio(monkeypatch, np.zeros(48000, np.float32))
    assert subtitles.transcribe("clip_01.mp4", subtitles.WhisperTranscriber()) == [
        (0.25, 1.5, "Vào rồi"), (2.0, 3.0, "goal")]


def test_ac6_default_transcriber(monkeypatch):
    monkeypatch.setitem(sys.modules, "faster_whisper", _fake_faster_whisper())
    assert isinstance(subtitles.default_transcriber(), subtitles.WhisperTranscriber)
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    assert subtitles.default_transcriber() is None


def test_ac6_download_models(monkeypatch):
    fw = _fake_faster_whisper(download_result="/cache/base")
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    result = subtitles.download_models()
    assert result == Path("/cache/base") and isinstance(result, Path)
    assert [d[0] for d in fw.downloads] == ["base"]
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(ImportError):
        subtitles.download_models()


# ---------------------------------------------------------------- AC7
AC7_EXPECTED = (
    "crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1,"
    "drawtext=fontfile=/fonts/DejaVuSans.ttf:text=Vào rồi:expansion=none:fontsize=56:fontcolor=white:"
    "box=1:boxcolor=black@0.6:boxborderw=12:x=(w-text_w)/2:y=1520:enable='between(t,1.000,2.500)',"
    "drawtext=fontfile=/fonts/DejaVuSans.ttf:text=hay quá:expansion=none:fontsize=56:fontcolor=white:"
    "box=1:boxcolor=black@0.6:boxborderw=12:x=(w-text_w)/2:y=1600:enable='between(t,1.000,2.500)'"
)


def _sub(text, y, start, end):
    return (f"drawtext=fontfile=/fonts/DejaVuSans.ttf:text={text}:expansion=none:fontsize=56:"
            f"fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=12:x=(w-text_w)/2:y={y}:"
            f"enable='between(t,{start},{end})'")


def test_ac7_exact_two_line_string():
    vf = vertical.vertical_filter([(0.0, 320.0)], 640, 360,
                                  subtitles=[(1.0, 2.5, "Vào rồi\nhay quá")], fontfile=FONT)
    assert vf == AC7_EXPECTED


def test_ac7_one_line_cue_and_order():
    vf = vertical.vertical_filter([(0.0, 320.0)], 640, 360, fontfile=FONT,
                                  subtitles=[(0.25, 1.0, "một"), (1.0, 2.0, "hai\nba")])
    assert vf == ",".join([OLD_FILTER, _sub("một", 1600, "0.250", "1.000"),
                           _sub("hai", 1520, "1.000", "2.000"), _sub("ba", 1600, "1.000", "2.000")])
    assert "\n" not in vf


def test_ac7_line_text_escaped():
    vf = vertical.vertical_filter([(0.0, 320.0)], 640, 360, fontfile=FONT,
                                  subtitles=[(0.0, 1.0, "it's 1:0")])
    assert "text=" + vertical._escape("it's 1:0") + ":expansion=none" in vf
    assert vertical._escape("it's 1:0") != "it's 1:0"


def test_ac7_with_box_and_caption():
    cue = [(1.0, 2.5, "Vào rồi\nhay quá")]
    vf = vertical.vertical_filter([(0.0, 320.0)], 640, 360, score_box=BOX,
                                  caption="BÀN THẮNG · 34'", fontfile=FONT, subtitles=cue)
    subs = AC7_EXPECTED[len(OLD_FILTER) + 1:]
    assert vf == BOX_GRAPH + "," + DRAWTEXT_34 + "," + subs
    assert vf.index("fontsize=64") < vf.index("fontsize=56")


@pytest.mark.parametrize("subs", [None, []])
@pytest.mark.parametrize("box, caption, expected", [
    (None, None, OLD_FILTER),
    (BOX, None, BOX_GRAPH),
    (None, "BÀN THẮNG · 34'", OLD_FILTER + "," + DRAWTEXT_34),
    (BOX, "BÀN THẮNG · 34'", BOX_GRAPH + "," + DRAWTEXT_34),
])
def test_ac7_no_subtitles_is_t021_identical(subs, box, caption, expected):
    font = FONT if caption else None
    assert vertical.vertical_filter([(0.0, 320.0)], 640, 360, box, caption, font, subs) == expected
    assert vertical.vertical_filter([(0.0, 320.0)], 640, 360, score_box=box, caption=caption,
                                    fontfile=font, subtitles=subs) == expected


def test_ac7_subtitles_need_fontfile():
    with pytest.raises(ValueError, match="^subtitles need a fontfile$"):
        vertical.vertical_filter([(0.0, 320.0)], 640, 360, subtitles=[(0.0, 1.0, "x")])


# ---------------------------------------------------------------- AC8
def _patch_media(monkeypatch):
    calls = []
    monkeypatch.setattr(media, "probe_size", lambda clip: calls.append(("probe_size",)) or (640, 360))
    monkeypatch.setattr(media, "find_font", lambda: calls.append(("find_font",)) or Path(FONT))

    def fake_filter(clip, vf, out):
        calls.append(("filter_video", vf))
        return Path(out)

    monkeypatch.setattr(media, "filter_video", fake_filter)
    return calls


def test_ac8_render_with_subtitles_call_order(monkeypatch, tmp_path):
    calls = _patch_media(monkeypatch)
    out = tmp_path / "v" / "c.mp4"
    assert vertical.render_vertical("clip.mp4", [(0.0, 320.0)], out, subtitles=[(0.5, 2.0, "x")]) == out
    assert [c[0] for c in calls] == ["probe_size", "find_font", "filter_video"]
    assert "enable='between(t,0.500,2.000)'" in calls[-1][1]
    assert f"fontfile={FONT}:" in calls[-1][1]


@pytest.mark.parametrize("kw", [{}, {"subtitles": []}, {"subtitles": None}])
def test_ac8_render_without_subtitles_is_t043(monkeypatch, tmp_path, kw):
    calls = _patch_media(monkeypatch)
    vertical.render_vertical("clip.mp4", [(0.0, 320.0)], tmp_path / "c.mp4", **kw)
    assert [c[0] for c in calls] == ["probe_size", "filter_video"]
    assert calls[-1][1] == OLD_FILTER


# ---------------------------------------------------------------- AC9
def _has_drawtext() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    out = _run("ffmpeg", "-hide_banner", "-filters").stdout
    return re.search(r"\sdrawtext\s", out) is not None


def _gray(path: Path, t: float) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-ss", str(t), "-i", str(path), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"], check=True, capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(1920, 1080).astype(np.int16)


@pytest.fixture(scope="module")
def burned(require_ffmpeg, tmp_path_factory):
    try:
        media.find_font()
    except MediaError as exc:
        pytest.skip(f"no Vietnamese font: {exc}")
    if not _has_drawtext():
        pytest.skip("ffmpeg has no drawtext filter")
    d = tmp_path_factory.mktemp("t022burn")
    clip = d / "black.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=25:d=3",
         "-f", "lavfi", "-i", "anoisesrc=d=3:c=white:r=44100:a=0.02:seed=5", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "3", str(clip)], check=True, capture_output=True)
    cues = subtitles.layout([(0.5, 2.0, "Vào rồi! Một bàn thắng tuyệt đẹp của đội chủ nhà ở phút cuối")])
    subbed, plain, plain2 = d / "subbed.mp4", d / "plain.mp4", d / "plain2.mp4"
    vertical.render_vertical(clip, [(0.0, 320.0)], subbed, subtitles=cues)
    vertical.render_vertical(clip, [(0.0, 320.0)], plain)
    vertical.render_vertical(clip, [(0.0, 320.0)], plain2)
    return subbed, plain, plain2


def test_ac9_both_outputs_1080x1920_h264(burned):
    for path in burned[:2]:
        out = _run("ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                   "stream=codec_name,width,height", "-of", "csv=p=0", str(path)).stdout.strip()
        assert out == "h264,1080,1920"


def test_ac9_subtitles_in_lower_third_inside_width(burned):
    subbed, plain, _ = burned
    a, b = _gray(subbed, 1.0), _gray(plain, 1.0)
    diff = np.abs(a - b) > 100
    assert diff[1280:].sum() >= 2000
    assert diff[:1280].sum() <= 50
    lower = a[1280:]
    assert (lower[:, :40] > 100).sum() == 0
    assert (lower[:, 1040:] > 100).sum() == 0


def test_ac9_subtitles_gone_after_cue(burned):
    subbed, plain, _ = burned
    diff = np.abs(_gray(subbed, 2.5) - _gray(plain, 2.5)) > 100
    assert diff.sum() <= 50


def test_ac9_check_can_fail(burned):
    """The pixel-count check is meaningful: two no-subtitle renders differ in < 2000 pixels."""
    _, plain, plain2 = burned
    diff = np.abs(_gray(plain, 1.0) - _gray(plain2, 1.0)) > 100
    assert diff[1280:].sum() < 2000


# ---------------------------------------------------------------- AC10
def _record_render(monkeypatch):
    renders = []

    def fake_render(clip, crop_path, dest, **kw):
        renders.append(((clip, crop_path, dest), kw))
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"v")
        return Path(dest)

    monkeypatch.setattr(sportscut.vertical, "render_vertical", fake_render)
    monkeypatch.setattr(sportscut.reframe, "plan_crop", lambda clip: [(0.0, 80.0)])
    return renders


AC10_TEXT = "Vào rồi! Bàn thắng"
AC10_SRT = "1\n00:00:00,500 --> 00:00:02,000\nVào rồi! Bàn thắng\n\n"


@pytest.mark.parametrize("segment, base_kw", [
    (GOAL_SEGMENT, {"caption": GOAL_CAPTION}),
    (OTHER_SEGMENT, {}),
])
def test_ac10_pipeline_writes_srt_and_forwards(burst_video, tmp_path, monkeypatch, segment, base_kw):
    monkeypatch.setattr(sportscut.pipeline, "select_segments", lambda *a, **k: [segment])
    renders = _record_render(monkeypatch)
    out = tmp_path / "out"
    fake = FakeTranscriber([(0.5, 2.0, AC10_TEXT)])
    entries = sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6,
                                     vertical=True, transcriber=fake)
    srt = out / "vertical" / "clip_01.srt"
    assert srt.read_bytes() == AC10_SRT.encode("utf-8")
    assert len(renders) == 1
    (clip, _, dest), kw = renders[0]
    assert kw == {**base_kw, "subtitles": [(0.5, 2.0, AC10_TEXT)]}
    assert Path(clip) == out / "clip_01.mp4" and Path(dest) == out / "vertical" / "clip_01.mp4"
    assert len(fake.calls) == 1
    assert [list(e) for e in entries] == [KEYS + ["vertical_file"]]
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8")) \
        if (out / "manifest.json").exists() else entries
    assert [list(e) for e in manifest] == [KEYS + ["vertical_file"]]


def test_ac10_manifest_same_as_without_transcriber(burst_video, tmp_path, monkeypatch):
    _record_render(monkeypatch)
    a = sportscut.pipeline.run(burst_video, tmp_path / "a", top=2, min_len=4, max_len=6, vertical=True)
    b = sportscut.pipeline.run(burst_video, tmp_path / "b", top=2, min_len=4, max_len=6, vertical=True,
                               transcriber=FakeTranscriber([(0.5, 2.0, "x")]))
    assert [list(e) for e in a] == [list(e) for e in b]
    assert a == b
    files_a = sorted(p.name for p in (tmp_path / "a").iterdir())
    files_b = sorted(p.name for p in (tmp_path / "b").iterdir())
    assert files_a == files_b
    if (tmp_path / "a" / "manifest.json").exists():
        assert (tmp_path / "a" / "manifest.json").read_text() == (tmp_path / "b" / "manifest.json").read_text()


def test_ac10_long_cue_is_laid_out(burst_video, tmp_path, monkeypatch):
    renders = _record_render(monkeypatch)
    out = tmp_path / "out"
    fake = FakeTranscriber([(0.0, 5.7, TWELVE)])
    sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True, transcriber=fake)
    subs = renders[0][1]["subtitles"]
    assert len(subs) == 2 and all(len(s[2].split("\n")) <= 2 for s in subs)
    assert (out / "vertical" / "clip_01.srt").read_text(encoding="utf-8") == TWELVE_SRT


def test_ac10_empty_transcript(burst_video, tmp_path, monkeypatch):
    renders = _record_render(monkeypatch)
    out = tmp_path / "out"
    sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True,
                           transcriber=FakeTranscriber([]))
    srt = out / "vertical" / "clip_01.srt"
    assert srt.exists() and srt.stat().st_size == 0
    assert "subtitles" not in renders[0][1]


# ---------------------------------------------------------------- AC11
def test_ac11_only_clip_audio_transcribed(burst_video, tmp_path, monkeypatch):
    _record_render(monkeypatch)
    out = tmp_path / "out"
    fake = FakeTranscriber([])
    entries = sportscut.pipeline.run(burst_video, out, top=2, min_len=4, max_len=6,
                                     vertical=True, transcriber=fake)
    assert len(entries) == 2
    assert len(fake.calls) == len(entries)
    for audio, entry in zip(fake.calls, entries):
        assert abs(audio.size / 16000 - (entry["end"] - entry["start"])) <= 0.25
    assert sum(a.size for a in fake.calls) / 16000 <= 12.5
    for entry in entries:
        assert (out / entry["vertical_file"]).with_suffix(".srt").exists()


def test_ac11_no_transcriber_never_touches_subtitles(burst_video, tmp_path, monkeypatch):
    _record_render(monkeypatch)
    monkeypatch.setattr(sportscut.subtitles, "transcribe", lambda *a, **k: pytest.fail("transcribe called"))
    monkeypatch.setattr(sportscut.subtitles, "write_srt", lambda *a, **k: pytest.fail("write_srt called"))
    monkeypatch.setattr(sportscut.subtitles, "layout", lambda *a, **k: pytest.fail("layout called"))
    out = tmp_path / "out"
    sportscut.pipeline.run(burst_video, out, top=2, min_len=4, max_len=6, vertical=True)
    assert list(out.rglob("*.srt")) == []


# ---------------------------------------------------------------- AC12
def test_ac12_transcriber_needs_vertical(burst_video, tmp_path):
    out = tmp_path / "out"
    fake = FakeTranscriber([(0.0, 1.0, "x")])
    with pytest.raises(PipelineError) as exc:
        sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, transcriber=fake)
    assert str(exc.value) == "transcriber needs vertical=True"
    assert not (out / "clip_01.mp4").exists()
    assert not out.exists() or list(out.rglob("*")) == []
    assert fake.calls == []


def test_ac12_transcription_error_is_pipeline_error(burst_video, tmp_path, monkeypatch):
    renders = _record_render(monkeypatch)
    with pytest.raises(PipelineError) as exc:
        sportscut.pipeline.run(burst_video, tmp_path / "out", top=1, min_len=4, max_len=6,
                               vertical=True, transcriber=FakeTranscriber(exc=RuntimeError("boom")))
    assert str(exc.value) == "speech-to-text failed for clip_01.mp4: boom"
    assert renders == []


def test_ac12_cli_transcription_error_exit_1(burst_video, tmp_path, monkeypatch, capsys):
    _record_render(monkeypatch)
    monkeypatch.setattr(subtitles, "default_transcriber",
                        lambda: FakeTranscriber(exc=RuntimeError("boom")))
    code = cli.main(["cut", str(burst_video), "--out", str(tmp_path / "o"), "--top", "1",
                     "--min-len", "4", "--max-len", "6", "--vertical", "--subtitles"])
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err == "sportscut: error: speech-to-text failed for clip_01.mp4: boom\n"


# ---------------------------------------------------------------- AC13
def _fake_cli_run(monkeypatch):
    seen = []

    def fake_run(video, out_dir, **kwargs):
        seen.append(kwargs)
        return [{"file": "clip_01.mp4", "vertical_file": "vertical/clip_01.mp4"}]

    monkeypatch.setattr(cli, "run", fake_run)
    return seen


def test_ac13_forwards_transcriber(monkeypatch, tmp_path, capsys):
    seen = _fake_cli_run(monkeypatch)
    sentinel = object()
    monkeypatch.setattr(subtitles, "default_transcriber", lambda: sentinel)
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--vertical", "--subtitles"]) == 0
    captured = capsys.readouterr()
    assert len(seen) == 1 and seen[0]["transcriber"] is sentinel and seen[0]["vertical"] is True
    assert captured.err == ""
    assert captured.out.splitlines() == [str(tmp_path / "clip_01.mp4"), str(tmp_path / "vertical" / "clip_01.mp4")]


def test_ac13_notice_without_extra(monkeypatch, tmp_path, capsys):
    seen = _fake_cli_run(monkeypatch)
    monkeypatch.setattr(subtitles, "default_transcriber", lambda: None)
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--vertical", "--subtitles"]) == 0
    captured = capsys.readouterr()
    assert captured.err == NOTICE
    assert seen[0]["transcriber"] is None
    assert captured.out.splitlines() == [str(tmp_path / "clip_01.mp4"), str(tmp_path / "vertical" / "clip_01.mp4")]


def test_ac13_notice_with_module_really_missing(monkeypatch, tmp_path, capsys):
    seen = _fake_cli_run(monkeypatch)
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--vertical", "--subtitles"]) == 0
    assert capsys.readouterr().err == NOTICE
    assert seen[0]["transcriber"] is None


def test_ac13_without_subtitles_never_checks_extra(monkeypatch, tmp_path, capsys):
    seen = _fake_cli_run(monkeypatch)
    monkeypatch.setattr(subtitles, "default_transcriber", lambda: pytest.fail("default_transcriber called"))
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--vertical"]) == 0
    assert "transcriber" in seen[0] and seen[0]["transcriber"] is None
    captured = capsys.readouterr()
    assert captured.err == "" and len(captured.out.splitlines()) == 2


def test_ac13_subtitles_needs_vertical(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "run", lambda *a, **k: pytest.fail("run called"))
    monkeypatch.setattr(subtitles, "default_transcriber", lambda: pytest.fail("default_transcriber called"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--subtitles"])
    assert exc.value.code == 2
    assert "--subtitles needs --vertical" in capsys.readouterr().err


def test_ac13_help_mentions_subtitles(capsys):
    with pytest.raises(SystemExit):
        cli.main(["cut", "--help"])
    out = capsys.readouterr().out
    assert "--subtitles" in out


def test_ac13_real_cli_subtitles_without_extra(burst_video, tmp_path):
    """Real `python -m sportscut cut --vertical --subtitles` in a fresh interpreter (no extra installed)."""
    probe = _run(sys.executable, "-c", "import faster_whisper", cwd=ROOT)
    if probe.returncode == 0:
        pytest.skip("faster_whisper is installed here")
    if not _has_drawtext():
        pytest.skip("ffmpeg has no drawtext filter (needed by the T-021 caption path)")
    out = tmp_path / "o"
    result = _run(sys.executable, "-m", "sportscut", "cut", str(burst_video), "--out", str(out),
                  "--top", "1", "--min-len", "4", "--max-len", "6", "--vertical", "--subtitles", cwd=ROOT)
    assert result.returncode == 0, result.stderr
    assert result.stderr == NOTICE
    assert len(result.stdout.splitlines()) == 2
    assert list(out.rglob("*.srt")) == []


# ---------------------------------------------------------------- AC14
def test_ac14_download_ok(monkeypatch, capsys):
    fw = _fake_faster_whisper(download_result="/cache/base")
    monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    assert cli.main(["download-models"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "downloaded faster-whisper base model to /cache/base\n"
    assert captured.err == ""
    assert [d[0] for d in fw.downloads] == ["base"]


def test_ac14_download_missing_extra(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    assert cli.main(["download-models"]) == 1
    captured = capsys.readouterr()
    assert captured.err == "sportscut download-models: error: needs the [asr] extra: pip install 'sportscut[asr]'\n"
    assert captured.out == ""


def test_ac14_download_failure(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "faster_whisper", _fake_faster_whisper(download_exc=OSError("offline")))
    assert cli.main(["download-models"]) == 1
    assert capsys.readouterr().err == "sportscut download-models: error: offline\n"


def test_ac14_real_cli_without_extra():
    probe = _run(sys.executable, "-c", "import faster_whisper", cwd=ROOT)
    if probe.returncode == 0:
        pytest.skip("faster_whisper is installed here")
    result = _run(sys.executable, "-m", "sportscut", "download-models", cwd=ROOT)
    assert result.returncode == 1
    assert result.stderr == "sportscut download-models: error: needs the [asr] extra: pip install 'sportscut[asr]'\n"


def test_ac14_download_models_listed_in_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "download-models" in capsys.readouterr().out


# ---------------------------------------------------------------- AC15
SMOKE = ROOT / "tests" / "test_subtitles_asr_smoke.py"


def test_ac15_smoke_file_uses_importorskip_and_real_transcriber():
    text = SMOKE.read_text(encoding="utf-8")
    assert "importorskip" in text and "faster_whisper" in text
    assert "WhisperTranscriber" in text
    for tool in ("say", "espeak-ng", "espeak"):
        assert tool in text
    assert "test_real_model_english" in text and "test_real_model_vietnamese" in text


def test_ac15_smoke_is_skipped_not_failed_without_extra():
    probe = _run(sys.executable, "-c", "import faster_whisper", cwd=ROOT)
    if probe.returncode == 0:
        pytest.skip("faster_whisper is installed: the smoke test actually runs")
    result = _run(sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", str(SMOKE), cwd=ROOT)
    assert result.returncode in (0, 5), result.stdout + result.stderr
    assert "failed" not in result.stdout and "error" not in result.stdout.lower()
    assert "skipped" in result.stdout


# ---------------------------------------------------------------- AC16
def _vert_section(readme: str) -> str:
    return readme.split(VERT_HEADING, 1)[1].split("\n## ", 1)[0]


def test_ac16_readme_section_mentions():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = _vert_section(readme)
    for needle in ("--subtitles", "pip install 'sportscut[asr]'", "sportscut download-models",
                   "vertical/clip_NN.srt"):
        assert needle in section, needle
    assert readme.index(VERT_HEADING) < readme.index(CROP_HEADING)


@own_branch
def test_ac16_readme_insert_only_and_eval_crop_tail_identical():
    base = _show(f"{_merge_base()}:README.md")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.split(CROP_HEADING, 1)[1] == base.split(CROP_HEADING, 1)[1]
    assert readme.endswith(CROP_HEADING + base.split(CROP_HEADING, 1)[1])
    base_section = _vert_section(base)
    section = _vert_section(readme)
    # section starts with main's full text; T-022 text comes at the end
    assert section.startswith(base_section.rstrip("\n"))
    assert "--subtitles" not in base_section
    assert readme.split(VERT_HEADING, 1)[0] == base.split(VERT_HEADING, 1)[0]


@pytest.mark.parametrize("spec, needle", [
    (T004_SPEC, "transcriber=None"), (T021_SPEC, "subtitles=None"), (T043_SPEC, "--subtitles"),
])
def test_ac16_spec_has_t022_section(spec, needle):
    text = (ROOT / spec).read_text(encoding="utf-8")
    assert "## Updated by T-022" in text
    assert needle in text.split("## Updated by T-022", 1)[1]


@own_branch
@pytest.mark.parametrize("spec", [T004_SPEC, T021_SPEC, T043_SPEC])
def test_ac16_spec_ends_with_t022_section_appended(spec):
    text = (ROOT / spec).read_text(encoding="utf-8")
    headings = re.findall(r"^## .*$", text, re.M)
    assert headings[-1] == "## Updated by T-022"
    base = _show(f"{_merge_base()}:{spec}")
    assert text.startswith(base.rstrip("\n"))


# ---------------------------------------------------------------- AC17
INSERT_ONLY = ["sportscut/cli.py", "sportscut/pipeline.py", "pyproject.toml", "README.md",
               T004_SPEC, T021_SPEC, T043_SPEC]


@own_branch
def test_ac17_insert_only_files_have_no_deleted_lines():
    base = _merge_base()
    out = _run(GIT, "diff", "--numstat", base, "--", *INSERT_ONLY, cwd=ROOT).stdout
    rows = {line.split("\t")[2]: (line.split("\t")[0], line.split("\t")[1]) for line in out.splitlines()}
    for path in INSERT_ONLY:
        if path in rows:
            assert rows[path][1] == "0", (path, rows[path])
    for path in ("sportscut/cli.py", "sportscut/pipeline.py", "pyproject.toml", "README.md"):
        assert path in rows, path


@own_branch
def test_ac17_protected_paths_unchanged():
    base = _merge_base()
    out = _run(GIT, "diff", "--name-only", base, "--", "sportscut/media.py", "sportscut/events/",
               "sportscut/reframe.py", "sportscut/export.py", "tests/conftest.py", "tests/fixtures/",
               cwd=ROOT).stdout
    assert out.strip() == ""


@own_branch
def test_ac17_preexisting_tests_unedited_except_t021_gate():
    base = _merge_base()
    out = _run(GIT, "diff", "--name-status", base, "--", "tests/", cwd=ROOT).stdout
    changed = {line.split("\t")[-1]: line.split("\t")[0] for line in out.splitlines()}
    modified = {p for p, s in changed.items() if s != "A"}
    assert modified <= {"tests/test_t021_acceptance.py"}, modified
    if "tests/test_t021_acceptance.py" in modified:
        diff = _run(GIT, "diff", "-U0", base, "--", "tests/test_t021_acceptance.py", cwd=ROOT).stdout
        removed = [line[1:].strip() for line in diff.splitlines()
                   if line.startswith("-") and not line.startswith("---")]
        assert removed == ['assert headings[-1] == "## Updated by T-021"'] * 2


def _archive_main(tmp_path: Path) -> Path:
    dest = tmp_path / "main_src"
    dest.mkdir()
    tar = tmp_path / "main.tar"
    result = _run(GIT, "archive", "--format=tar", "-o", str(tar), "main", "sportscut", cwd=ROOT)
    if result.returncode != 0:
        pytest.skip("cannot archive main")
    with tarfile.open(tar) as tf:
        tf.extractall(dest, filter="data")
    return dest


def _eval_json(cwd: Path, *args) -> dict:
    code = ("import sys, runpy, sportscut; print(sportscut.__file__, file=sys.stderr); "
            "sys.argv=['sportscut', *sys.argv[1:]]; runpy.run_module('sportscut', run_name='__main__')")
    result = _run(sys.executable, "-c", code, *args, cwd=cwd)
    assert result.returncode == 0, result.stderr
    return {"origin": result.stderr.splitlines()[0], **json.loads(result.stdout)}


def _need_fixture(directory: Path, name: str) -> None:
    if not list(directory.rglob(name)):
        pytest.skip(f"{directory} media not built (git-ignored)")


@own_branch
def test_ac17_eval_f1_equals_main(tmp_path):
    fixtures = ROOT / "tests" / "fixtures" / "eval"
    _need_fixture(fixtures, "*.mp4")
    main_src = _archive_main(tmp_path)
    ours = _eval_json(ROOT, "eval", str(fixtures), "--json")
    base = _eval_json(main_src, "eval", str(fixtures), "--json")
    assert base["origin"].startswith(str(main_src))
    assert ours["origin"].startswith(str(ROOT))
    assert ours["f1"] == base["f1"]
    assert ours["precision"] == base["precision"] and ours["recall"] == base["recall"]


def _drop_speed(report):
    if isinstance(report, dict):
        return {k: _drop_speed(v) for k, v in report.items() if k not in ("seconds_per_min", "origin")}
    if isinstance(report, list):
        return [_drop_speed(v) for v in report]
    return report


@own_branch
def test_ac17_eval_crop_equals_main_except_speed(tmp_path):
    fixtures = ROOT / "tests" / "fixtures" / "eval_crop"
    _need_fixture(fixtures, "*.mp4")
    main_src = _archive_main(tmp_path)
    ours = _eval_json(ROOT, "eval-crop", str(fixtures), "--json")
    base = _eval_json(main_src, "eval-crop", str(fixtures), "--json")
    assert base["origin"].startswith(str(main_src))
    assert _drop_speed(ours) == _drop_speed(base)
