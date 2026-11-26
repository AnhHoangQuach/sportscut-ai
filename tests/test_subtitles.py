"""T-022: commentary subtitles for vertical clips (sportscut/subtitles.py and wiring)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import types
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sportscut import media, subtitles

ROOT = Path(__file__).resolve().parents[1]
TWELVE = "aaaa bbbb cccc dddd eeee ffff gggg hhhh iiii jjjj kkkk llll"
TWELVE_SRT = (
    "1\n00:00:00,000 --> 00:00:04,800\naaaa bbbb cccc dddd eeee\nffff gggg hhhh iiii jjjj\n\n"
    "2\n00:00:04,800 --> 00:00:05,700\nkkkk llll\n\n"
)


# ---------------------------------------------------------------- srt_time / write_srt
@pytest.mark.parametrize("t,expected", [
    (0, "00:00:00,000"),
    (4.8, "00:00:04,800"),
    (3725.25, "01:02:05,250"),
    (59.9996, "00:01:00,000"),
])
def test_srt_time_values(t, expected):
    assert subtitles.srt_time(t) == expected


def test_write_srt_exact_and_empty(tmp_path):
    cues = [(0.0, 4.8, "aaaa bbbb cccc dddd eeee\nffff gggg hhhh iiii jjjj"), (4.8, 5.7, "kkkk llll")]
    path = tmp_path / "a" / "b" / "clip_01.srt"
    assert subtitles.write_srt(cues, str(path)) == path
    assert path.read_bytes() == TWELVE_SRT.encode("utf-8")
    empty = tmp_path / "c" / "empty.srt"
    assert subtitles.write_srt([], empty) == empty
    assert empty.read_bytes() == b""


def test_write_srt_utf8_vietnamese(tmp_path):
    path = subtitles.write_srt([(1.0, 2.5, "Vào rồi")], tmp_path / "v.srt")
    assert path.read_bytes() == "1\n00:00:01,000 --> 00:00:02,500\nVào rồi\n\n".encode("utf-8")


# ---------------------------------------------------------------- layout
def test_layout_short_cue_unchanged():
    assert subtitles.layout([(1.0, 2.5, "Vào rồi")]) == [(1.0, 2.5, "Vào rồi")]


def test_layout_splits_into_two_line_chunks(tmp_path):
    cues = subtitles.layout([(0.0, 5.7, TWELVE)])
    assert len(cues) == 2
    (s0, e0, t0), (s1, e1, t1) = cues
    assert s0 == 0.0 and e0 == pytest.approx(4.8, abs=1e-9)
    assert t0 == "aaaa bbbb cccc dddd eeee\nffff gggg hhhh iiii jjjj"
    assert s1 == pytest.approx(4.8, abs=1e-9) and e1 == 5.7
    assert t1 == "kkkk llll"
    path = subtitles.write_srt(cues, tmp_path / "x.srt")
    assert path.read_text(encoding="utf-8") == TWELVE_SRT


def test_layout_vietnamese_lines_within_28():
    text = ("Vào rồi! Một bàn thắng tuyệt đẹp của đội chủ nhà ở phút cuối cùng của trận đấu, "
            "khán giả trên sân vỡ òa trong niềm vui sướng tột cùng")
    cues = subtitles.layout([(3.0, 11.0, text)])
    assert len(cues) >= 2
    for _, _, chunk in cues:
        lines = chunk.split("\n")
        assert len(lines) <= subtitles.MAX_LINES == 2
        assert all(len(line) <= subtitles.WRAP_CHARS == 28 for line in lines)
    assert cues[0][0] == 3.0 and cues[-1][1] == 11.0
    for (_, end, _), (start, _, _) in zip(cues, cues[1:]):
        assert start == end
    assert " ".join(" ".join(c[2].split("\n")) for c in cues) == text


def test_layout_breaks_long_words():
    cues = subtitles.layout([(0.0, 1.0, "x" * 70)])
    lines = [line for c in cues for line in c[2].split("\n")]
    assert all(len(line) <= 28 for line in lines) and "".join(lines) == "x" * 70


# ---------------------------------------------------------------- transcribe
class FakeTranscriber:
    def __init__(self, items=(), error=None):
        self.items = list(items)
        self.error = error
        self.calls = []

    def transcribe(self, audio):
        self.calls.append(audio)
        if self.error is not None:
            raise self.error
        return list(self.items)


def _fake_audio(monkeypatch, audio):
    seen = []
    monkeypatch.setattr(media, "extract_audio", lambda path: seen.append(path) or audio)
    return seen


def test_transcribe_normalises_clamps_sorts(monkeypatch):
    audio = np.zeros(96000, np.float32)
    seen = _fake_audio(monkeypatch, audio)
    fake = FakeTranscriber([
        (2.0, 3.5, "  hai  "), (-0.2, 1.0, "Vào rồi!"), (1.5, 1.5, "x"),
        (4.0, 9.0, "cuối"), (2.5, 3.0, "   "),
    ])
    clip = Path("/tmp/out/clip_01.mp4")
    assert subtitles.transcribe(clip, fake) == [
        (0.0, 1.0, "Vào rồi!"), (2.0, 3.5, "hai"), (4.0, 6.0, "cuối"),
    ]
    assert seen == [clip]
    assert len(fake.calls) == 1 and fake.calls[0] is audio


def test_transcribe_nfc(monkeypatch):
    _fake_audio(monkeypatch, np.zeros(32000, np.float32))
    nfd = unicodedata.normalize("NFD", "Vào rồi  bàn\nthắng")
    assert nfd != unicodedata.normalize("NFC", nfd)
    cues = subtitles.transcribe("clip_01.mp4", FakeTranscriber([(0.0, 1.0, nfd)]))
    assert cues == [(0.0, 1.0, unicodedata.normalize("NFC", "Vào rồi bàn thắng"))]


def test_transcribe_empty_audio_skips(monkeypatch):
    _fake_audio(monkeypatch, np.zeros(0, np.float32))
    fake = FakeTranscriber(error=AssertionError("must not be called"))
    assert subtitles.transcribe("clip_01.mp4", fake) == []
    assert fake.calls == []


def test_transcribe_wraps_errors(monkeypatch):
    _fake_audio(monkeypatch, np.zeros(16000, np.float32))
    with pytest.raises(subtitles.TranscriptionError) as exc:
        subtitles.transcribe(Path("out") / "clip_01.mp4", FakeTranscriber(error=RuntimeError("boom")))
    assert str(exc.value) == "speech-to-text failed for clip_01.mp4: boom"
    assert isinstance(exc.value, RuntimeError)


def test_transcribe_media_error_propagates(monkeypatch):
    def broken(path):
        raise media.MediaError("no audio")

    monkeypatch.setattr(media, "extract_audio", broken)
    with pytest.raises(media.MediaError, match="no audio"):
        subtitles.transcribe("clip_01.mp4", FakeTranscriber())


# ---------------------------------------------------------------- faster-whisper backend
def _fake_faster_whisper(monkeypatch, download_result="/cache/base", download_error=None):
    log = {"init": [], "transcribe": [], "download": []}

    class WhisperModel:
        def __init__(self, *args, **kwargs):
            log["init"].append((args, kwargs))

        def transcribe(self, audio, **kwargs):
            log["transcribe"].append((audio, kwargs))
            segments = iter([SimpleNamespace(start=0.5, end=1.5, text=" Goal!"),
                             SimpleNamespace(start=2.0, end=3.0, text=" Vào rồi")])
            return segments, SimpleNamespace(language="en")

    def download_model(name, *args, **kwargs):
        log["download"].append((name, args, kwargs))
        if download_error is not None:
            raise download_error
        return download_result

    module = types.ModuleType("faster_whisper")
    module.WhisperModel = WhisperModel
    module.download_model = download_model
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    return log


def test_whisper_transcriber_lazy_and_auto_language(monkeypatch):
    log = _fake_faster_whisper(monkeypatch)
    transcriber = subtitles.WhisperTranscriber()
    assert log["init"] == []
    audio = np.zeros(16000, np.float32)
    first = transcriber.transcribe(audio)
    second = transcriber.transcribe(audio)
    assert log["init"] == [(("base",), {"device": "cpu", "compute_type": "int8"})]
    assert len(log["transcribe"]) == 2
    for got, kwargs in log["transcribe"]:
        assert got is audio
        assert kwargs["language"] is None and kwargs["vad_filter"] is True
    assert list(first) == list(second) == [(0.5, 1.5, " Goal!"), (2.0, 3.0, " Vào rồi")]


def test_default_transcriber_with_and_without_extra(monkeypatch):
    _fake_faster_whisper(monkeypatch)
    assert isinstance(subtitles.default_transcriber(), subtitles.WhisperTranscriber)
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    assert subtitles.default_transcriber() is None


def test_download_models_uses_base(monkeypatch):
    log = _fake_faster_whisper(monkeypatch, download_result="/cache/base")
    assert subtitles.download_models() == Path("/cache/base")
    assert [name for name, _, _ in log["download"]] == ["base"]
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    with pytest.raises(ImportError):
        subtitles.download_models()


def test_import_does_not_load_faster_whisper():
    code = 'import sys, sportscut.cli, sportscut.subtitles; print("faster_whisper" in sys.modules)'
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_subtitles_module_has_no_subprocess():
    assert "subprocess" not in (ROOT / "sportscut" / "subtitles.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------- vertical burn-in filters
from sportscut import vertical  # noqa: E402

FONT = "/fonts/DejaVuSans.ttf"
BASE = "crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1"
BS3 = "\\" * 3
CAPTION = "BÀN THẮNG · 34'"
DRAWTEXT_34 = (
    f"drawtext=fontfile=/fonts/DejaVuSans.ttf:text=BÀN THẮNG · 34{BS3}':expansion=none:"
    "fontsize=64:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=16:x=(w-text_w)/2:y=240"
)
BOX = (40, 16, 160, 40)
BOX_GRAPH = (
    "split=2[sc_main][sc_box];[sc_main]crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,"
    "setsar=1[sc_v];[sc_box]crop=w=160:h=40:x=40:y=16,scale=640:160,setsar=1[sc_b];"
    "[sc_v][sc_b]overlay=x=220:y=40"
)
T021 = {  # (score_box, caption) -> the T-021 filter string
    (None, None): BASE,
    (None, CAPTION): BASE + "," + DRAWTEXT_34,
    (BOX, None): BOX_GRAPH,
    (BOX, CAPTION): BOX_GRAPH + "," + DRAWTEXT_34,
}


def _sub(text, y, start="1.000", end="2.500"):
    return (
        f"drawtext=fontfile=/fonts/DejaVuSans.ttf:text={text}:expansion=none:fontsize=56:"
        "fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=12:x=(w-text_w)/2:"
        f"y={y}:enable='between(t,{start},{end})'"
    )


def test_vertical_filter_with_subtitles_exact():
    got = vertical.vertical_filter([(0.0, 320.0)], 640, 360,
                                   subtitles=[(1.0, 2.5, "Vào rồi\nhay quá")], fontfile=FONT)
    assert got == BASE + "," + _sub("Vào rồi", 1520) + "," + _sub("hay quá", 1600)


def test_vertical_filter_one_line_cue_and_cue_order():
    got = vertical.vertical_filter([(0.0, 320.0)], 640, 360, fontfile=FONT,
                                   subtitles=[(0.0, 1.0, "một"), (1.0, 2.5, "hai\nba")])
    assert got == ",".join([
        BASE, _sub("một", 1600, "0.000", "1.000"),
        _sub("hai", 1520, "1.000", "2.500"), _sub("ba", 1600, "1.000", "2.500"),
    ])


@pytest.mark.parametrize("box,caption", list(T021))
def test_vertical_filter_without_subtitles_byte_identical(box, caption):
    for subs in (None, []):
        got = vertical.vertical_filter([(0.0, 320.0)], 640, 360, score_box=box, caption=caption,
                                       fontfile=FONT if caption else None, subtitles=subs)
        assert got == T021[(box, caption)]


def test_vertical_filter_box_caption_and_subtitles():
    got = vertical.vertical_filter([(0.0, 320.0)], 640, 360, score_box=BOX, caption=CAPTION,
                                   fontfile=FONT, subtitles=[(1.0, 2.5, "Vào rồi")])
    assert got == BOX_GRAPH + "," + DRAWTEXT_34 + "," + _sub("Vào rồi", 1600)


def test_subtitles_need_fontfile():
    with pytest.raises(ValueError, match="^subtitles need a fontfile$"):
        vertical.vertical_filter([(0.0, 320.0)], 640, 360, subtitles=[(0.0, 1.0, "x")])


def test_subtitle_line_text_is_escaped():
    line = "it's 1:0"
    got = vertical.subtitle_filters([(0.0, 1.0, line)], FONT)
    assert "text=" + vertical._escape(line) + ":expansion=none" in got
    assert vertical._escape(line) != line
    assert "text=it's" not in got


def _wire(monkeypatch, font=Path(FONT)):
    calls = []
    monkeypatch.setattr(media, "probe_size", lambda p: calls.append(("probe_size",)) or (640, 360))
    monkeypatch.setattr(media, "find_font", lambda: calls.append(("find_font",)) or font)

    def fake_filter(clip, vf, out):
        calls.append(("filter_video", vf))
        return Path(out)

    monkeypatch.setattr(media, "filter_video", fake_filter)
    return calls


def test_render_vertical_subtitles_call_order(monkeypatch, tmp_path):
    calls = _wire(monkeypatch)
    vertical.render_vertical(tmp_path / "c.mp4", [(0.0, 320.0)], tmp_path / "v" / "o.mp4",
                             subtitles=[(0.5, 2.0, "x")])
    assert [c[0] for c in calls] == ["probe_size", "find_font", "filter_video"]
    assert "enable='between(t,0.500,2.000)'" in calls[-1][1]


@pytest.mark.parametrize("kw", [{}, {"subtitles": []}, {"subtitles": None}])
def test_render_vertical_without_subtitles_is_t043(monkeypatch, tmp_path, kw):
    calls = _wire(monkeypatch)
    monkeypatch.setattr(media, "find_font", lambda: pytest.fail("find_font called"))
    vertical.render_vertical(tmp_path / "c.mp4", [(0.0, 320.0)], tmp_path / "v" / "o.mp4", **kw)
    assert calls == [("probe_size",), ("filter_video", BASE)]


# ---------------------------------------------------------------- real burn-in
def _has_drawtext() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    out = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return any(line.split()[1:2] == ["drawtext"] for line in out.splitlines())


def _grey(path, t):
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t}", "-i", str(path), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
        check=True, capture_output=True,
    )
    return np.frombuffer(result.stdout, np.uint8).reshape(1920, 1080).astype(np.int16)


@pytest.mark.skipif(not _has_drawtext(), reason="ffmpeg has no drawtext filter")
def test_burned_subtitles_lower_third_only(require_ffmpeg, tmp_path):
    try:
        media.find_font()
    except media.MediaError as exc:
        pytest.skip(f"no font: {exc}")
    clip = tmp_path / "black.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=25:d=3",
         "-f", "lavfi", "-i", "anoisesrc=d=3:c=white:r=44100:a=0.02:seed=5",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "3", str(clip)],
        check=True, capture_output=True,
    )
    cues = subtitles.layout([(0.5, 2.0, "Vào rồi! Một bàn thắng tuyệt đẹp của đội chủ nhà ở phút cuối")])
    with_subs = vertical.render_vertical(clip, [(0.0, 320.0)], tmp_path / "subs.mp4", subtitles=cues)
    plain = vertical.render_vertical(clip, [(0.0, 320.0)], tmp_path / "plain.mp4")
    for path in (with_subs, plain):
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=codec_name,width,height", "-of", "csv=p=0", str(path)],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        assert probe == "h264,1080,1920"
    a, b = _grey(with_subs, 1.0), _grey(plain, 1.0)
    diff = np.abs(a - b) > 100
    assert diff[1280:].sum() >= 2000
    assert diff[:1280].sum() <= 50
    assert (a[1280:, :40] > 100).sum() == 0 and (a[1280:, 1040:] > 100).sum() == 0
    after = np.abs(_grey(with_subs, 2.5) - _grey(plain, 2.5)) > 100
    assert after.sum() <= 50


# ---------------------------------------------------------------- pipeline wiring
import json  # noqa: E402

import sportscut.pipeline  # noqa: E402
import sportscut.reframe  # noqa: E402
from sportscut.export import MANIFEST_NAME  # noqa: E402
from sportscut.models import Segment  # noqa: E402
from sportscut.pipeline import PipelineError  # noqa: E402

KEYS = ["start", "end", "score", "reason", "event", "event_confidence", "file", "vertical_file"]
GOAL_SEGMENT = Segment(2.0, 8.0, 1.0, "r", "goal", 0.9)
OTHER_SEGMENT = Segment(2.0, 8.0, 1.0, "r", "other", 0.0)
PIPE_CUE = (0.5, 2.0, "Vào rồi! Bàn thắng")


def _record_render(monkeypatch):
    renders = []

    def fake_render(clip, crop_path, dest, **kw):
        renders.append(kw)
        return Path(dest)

    monkeypatch.setattr(sportscut.vertical, "render_vertical", fake_render)
    monkeypatch.setattr(sportscut.reframe, "plan_crop", lambda clip: [(0.0, 80.0)])
    return renders


@pytest.mark.parametrize("segment,expected_keys", [
    (GOAL_SEGMENT, ["caption", "subtitles"]),
    (OTHER_SEGMENT, ["subtitles"]),
])
def test_pipeline_writes_srt_and_passes_subtitles(burst_video, tmp_path, monkeypatch, segment, expected_keys):
    monkeypatch.setattr(sportscut.pipeline, "select_segments", lambda *a, **k: [segment])
    renders = _record_render(monkeypatch)
    out = tmp_path / "out"
    entries = sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6,
                                     vertical=True, transcriber=FakeTranscriber([PIPE_CUE]))
    srt = out / "vertical" / "clip_01.srt"
    assert srt.read_bytes() == "1\n00:00:00,500 --> 00:00:02,000\nVào rồi! Bàn thắng\n\n".encode("utf-8")
    assert len(renders) == 1 and sorted(renders[0]) == expected_keys
    assert renders[0]["subtitles"] == [PIPE_CUE]
    assert [list(e) for e in entries] == [KEYS]
    assert [list(e) for e in json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))] == [KEYS]


def test_pipeline_empty_transcript_writes_empty_srt(burst_video, tmp_path, monkeypatch):
    renders = _record_render(monkeypatch)
    out = tmp_path / "out"
    sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6,
                           vertical=True, transcriber=FakeTranscriber([]))
    assert (out / "vertical" / "clip_01.srt").read_bytes() == b""
    assert len(renders) == 1 and "subtitles" not in renders[0]


def test_pipeline_transcribes_only_clip_audio(burst_video, tmp_path, monkeypatch):
    _record_render(monkeypatch)
    fake = FakeTranscriber([])
    entries = sportscut.pipeline.run(burst_video, tmp_path / "out", top=2, min_len=4, max_len=6,
                                     vertical=True, transcriber=fake)
    assert len(entries) == 2 and len(fake.calls) == len(entries)
    for audio, entry in zip(fake.calls, entries):
        assert abs(audio.size / media.SAMPLE_RATE - (entry["end"] - entry["start"])) <= 0.25
    assert sum(a.size for a in fake.calls) / media.SAMPLE_RATE <= 12.5


def test_pipeline_without_transcriber_never_touches_subtitles(burst_video, tmp_path, monkeypatch):
    renders = _record_render(monkeypatch)
    monkeypatch.setattr(subtitles, "transcribe", lambda *a: pytest.fail("transcribe called"))
    monkeypatch.setattr(subtitles, "write_srt", lambda *a: pytest.fail("write_srt called"))
    out = tmp_path / "out"
    sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True)
    assert renders == [{}]
    assert list(out.rglob("*.srt")) == []


def test_pipeline_transcriber_needs_vertical(burst_video, tmp_path):
    fake = FakeTranscriber([PIPE_CUE])
    out = tmp_path / "out"
    with pytest.raises(PipelineError, match="^transcriber needs vertical=True$"):
        sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, transcriber=fake)
    assert not (out / "clip_01.mp4").exists()
    assert fake.calls == []


def test_pipeline_transcription_error(burst_video, tmp_path, monkeypatch):
    _record_render(monkeypatch)
    with pytest.raises(PipelineError) as exc:
        sportscut.pipeline.run(burst_video, tmp_path / "out", top=1, min_len=4, max_len=6,
                               vertical=True, transcriber=FakeTranscriber(error=RuntimeError("boom")))
    assert str(exc.value) == "speech-to-text failed for clip_01.mp4: boom"


# ---------------------------------------------------------------- CLI
from sportscut import cli  # noqa: E402

NOTICE = (
    "sportscut: notice: subtitles need the [asr] extra: pip install 'sportscut[asr]'; "
    "vertical clips are rendered without subtitles\n"
)
ENTRY = {"file": "clip_01.mp4", "vertical_file": "vertical/clip_01.mp4"}


def _record_run(monkeypatch):
    calls = []

    def fake_run(video, out, **kw):
        calls.append(kw)
        return [dict(ENTRY)]

    monkeypatch.setattr(cli, "run", fake_run)
    return calls


def test_cli_subtitles_forwards_transcriber(monkeypatch, capsys):
    calls = _record_run(monkeypatch)
    sentinel = object()
    monkeypatch.setattr(subtitles, "default_transcriber", lambda: sentinel)
    assert cli.main(["cut", "v.mp4", "--out", "O", "--vertical", "--subtitles"]) == 0
    assert len(calls) == 1 and calls[0]["transcriber"] is sentinel
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [str(Path("O") / "clip_01.mp4"), str(Path("O") / "vertical/clip_01.mp4")]


def test_cli_subtitles_notice_without_extra(monkeypatch, capsys):
    calls = _record_run(monkeypatch)
    monkeypatch.setattr(subtitles, "default_transcriber", lambda: None)
    assert cli.main(["cut", "v.mp4", "--out", "O", "--vertical", "--subtitles"]) == 0
    assert calls[0]["transcriber"] is None
    captured = capsys.readouterr()
    assert captured.err == NOTICE
    assert captured.out.splitlines() == [str(Path("O") / "clip_01.mp4"), str(Path("O") / "vertical/clip_01.mp4")]


def test_cli_subtitles_notice_with_missing_module(monkeypatch, capsys):
    _record_run(monkeypatch)
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    assert cli.main(["cut", "v.mp4", "--out", "O", "--vertical", "--subtitles"]) == 0
    assert capsys.readouterr().err == NOTICE


def test_cli_without_subtitles_never_checks_extra(monkeypatch, capsys):
    calls = _record_run(monkeypatch)
    monkeypatch.setattr(subtitles, "default_transcriber", lambda: pytest.fail("default_transcriber called"))
    assert cli.main(["cut", "v.mp4", "--out", "O", "--vertical"]) == 0
    assert calls[0]["transcriber"] is None
    assert capsys.readouterr().err == ""


def test_cli_subtitles_needs_vertical(monkeypatch, capsys):
    calls = _record_run(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(["cut", "v.mp4", "--out", "O", "--subtitles"])
    assert exc.value.code == 2
    assert "--subtitles needs --vertical" in capsys.readouterr().err
    assert calls == []


def test_cli_transcription_error_exit_1(burst_video, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(subtitles, "default_transcriber",
                        lambda: FakeTranscriber(error=RuntimeError("boom")))
    monkeypatch.setattr(sportscut.reframe, "plan_crop", lambda clip: [(0.0, 80.0)])
    code = cli.main(["cut", str(burst_video), "--out", str(tmp_path / "O"), "--top", "1",
                     "--min-len", "4", "--max-len", "6", "--vertical", "--subtitles"])
    assert code == 1
    assert capsys.readouterr().err == "sportscut: error: speech-to-text failed for clip_01.mp4: boom\n"


def test_cli_download_models_ok(monkeypatch, capsys):
    _fake_faster_whisper(monkeypatch, download_result="/cache/base")
    assert cli.main(["download-models"]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"downloaded faster-whisper base model to {Path('/cache/base')}\n"
    assert captured.err == ""


def test_cli_download_models_missing_extra(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    assert cli.main(["download-models"]) == 1
    captured = capsys.readouterr()
    assert captured.err == "sportscut download-models: error: needs the [asr] extra: pip install 'sportscut[asr]'\n"
    assert captured.out == ""


def test_cli_download_models_failure(monkeypatch, capsys):
    _fake_faster_whisper(monkeypatch, download_error=OSError("offline"))
    assert cli.main(["download-models"]) == 1
    assert capsys.readouterr().err == "sportscut download-models: error: offline\n"
