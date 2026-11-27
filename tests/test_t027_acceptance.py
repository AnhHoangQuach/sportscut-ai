"""T-027 Tester acceptance tests, written from the acceptance criteria (not the developer's tests).

The signal generator (numpy WAV muxed with ffmpeg) and the tone measurement (least-squares
lock-in amplitude at one frequency) are independent of tests/test_voiceover.py.
"""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import wave
from pathlib import Path

import numpy as np
import pytest

from sportscut import cli, media, pipeline
from sportscut import vertical as vertical_mod
from sportscut.commentary import script, voiceover
from sportscut.pipeline import PipelineError

ROOT = Path(__file__).resolve().parents[1]
SR = media.SAMPLE_RATE

needs_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg required")


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")


def _base():
    result = _git("merge-base", "main", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


# ------------------------------------------------------------------ fakes / signal helpers
class ToneFake:
    """Fake Synthesizer: 2000 Hz sine, amplitude 0.3, length = script.speech_seconds(text)."""

    def __init__(self, sample_rate=22050, freq=2000.0, fail=None):
        self.sample_rate = sample_rate
        self.freq = freq
        self.fail = fail
        self.calls = []

    def synthesize(self, text):
        self.calls.append(text)
        if self.fail:
            raise self.fail
        n = round(script.speech_seconds(text) * self.sample_rate)
        t = np.arange(n) / self.sample_rate
        return (0.3 * np.sin(2 * np.pi * self.freq * t)).astype(np.float32)


class OnesFake:
    sample_rate = 1000

    def __init__(self, n=3000):
        self.n = n
        self.calls = 0

    def synthesize(self, text):
        self.calls += 1
        return np.ones(self.n, np.float32)


def _make_clip(path, seconds, freq=300.0, amp=0.25):
    """Own generator: numpy sine -> 16-bit WAV -> mp4 (160x120 video + AAC)."""
    rate = 44100
    t = np.arange(round(seconds * rate)) / rate
    pcm = np.round(amp * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2")
    wav = path.with_suffix(".src.wav")
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                    f"testsrc=size=160x120:rate=10:duration={seconds}", "-i", str(wav),
                    "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                    "-shortest", str(path)], check=True, capture_output=True)
    wav.unlink()
    return path


def tone_level(samples, f, t0, t1):
    """Amplitude of the f-Hz component in [t0, t1] by least-squares fit of sin+cos."""
    seg = samples[int(t0 * SR):int(t1 * SR)].astype(np.float64)
    t = np.arange(len(seg)) / SR
    basis = np.stack([np.sin(2 * np.pi * f * t), np.cos(2 * np.pi * f * t)], axis=1)
    coef, *_ = np.linalg.lstsq(basis, seg, rcond=None)
    return float(np.hypot(*coef)) + 1e-12


def db(a, b):
    return 20 * np.log10(a / b)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _streams(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of",
                          "csv=p=0", str(path)], capture_output=True, text=True, check=True).stdout
    return sorted(out.split())


LINES = [(2.0, "Vào! Bàn thắng!"), (6.0, "Tỉ số 1-0.")]


def _windows():
    return [(s + 0.15, s + script.speech_seconds(t) - 0.15) for s, t in LINES]


@pytest.fixture(scope="module")
def clip10(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg required")
    return _make_clip(tmp_path_factory.mktemp("t027") / "clip_01.mp4", 10)


# ------------------------------------------------------------------ AC1 / AC2
def test_ac1_pyproject_tts_extra_and_no_models_in_git():
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["optional-dependencies"]
    assert extras["tts"] == ["piper-tts>=1.3"]
    assert not any("piper" in dep for dep in extras["dev"])
    base = _base()
    if base:
        old = tomllib.loads(_git("show", f"{base}:pyproject.toml").stdout)["project"]["optional-dependencies"]
        for name in ("api", "youtube", "llm", "asr", "dev"):
            assert extras[name] == old[name], name
    assert _git("ls-files", "*.onnx", "*.onnx.json", "*.mp4", "*.wav").stdout.strip() == ""


def test_ac2_fresh_import_loads_no_piper_and_no_subprocess():
    code = ("import sys, sportscut.cli, sportscut.pipeline, sportscut.commentary.voiceover; "
            "print('piper' in sys.modules, 'onnxruntime' in sys.modules)")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False False"
    pkg = ROOT / "sportscut"
    assert "subprocess" not in (pkg / "commentary/voiceover.py").read_text(encoding="utf-8")
    assert "subprocess" not in (pkg / "pipeline.py").read_text(encoding="utf-8")
    assert "subprocess" not in (pkg / "cli.py").read_text(encoding="utf-8")
    importers = sorted(p.relative_to(pkg).as_posix() for p in pkg.rglob("*.py")
                       if any(l.strip() in ("import subprocess",) or l.strip().startswith("from subprocess")
                              for l in p.read_text(encoding="utf-8").splitlines()))
    assert importers == ["events/incidents.py", "media.py"]


# ------------------------------------------------------------------ AC3
def test_ac3_second_line_delayed_no_overlap():
    fake = OnesFake()
    track, spoken = voiceover.voice_track([(1.0, "a"), (2.0, "b")], fake, 10.0)
    assert spoken == [(1.0, 4.0), (4.0, 7.0)]
    assert track.dtype == np.float32 and len(track) == 10000
    assert np.all(track[1000:7000] == 1.0)
    assert np.all(track[:1000] == 0) and np.all(track[7000:] == 0)


def test_ac3_truncated_at_clip_end():
    track, spoken = voiceover.voice_track([(8.0, "x")], OnesFake(), 10.0)
    assert spoken == [(8.0, 10.0)] and len(track) == 10000
    assert np.all(track[8000:] == 1.0) and np.all(track[:8000] == 0)


@pytest.mark.parametrize("lines", [[(10.0, "x")], [], [(12.5, "late")]])
def test_ac3_skipped_lines_never_synthesize(lines):
    fake = OnesFake()
    track, spoken = voiceover.voice_track(lines, fake, 10.0)
    assert spoken == [] and fake.calls == 0
    assert len(track) == 10000 and not track.any() and track.dtype == np.float32


def test_ac3_values_clipped():
    class Loud(OnesFake):
        def synthesize(self, text):
            return np.array([3.0, -4.0, 0.5] * 100)

    track, spoken = voiceover.voice_track([(0.0, "a")], Loud(), 1.0)
    assert track.dtype == np.float32
    assert track.max() == 1.0 and track.min() == -1.0 and spoken == [(0.0, 0.3)]


def test_ac3_synthesis_error_message():
    class Boom(OnesFake):
        def synthesize(self, text):
            raise RuntimeError("boom")

    with pytest.raises(voiceover.SynthesisError, match=r"^text-to-speech failed: boom$"):
        voiceover.voice_track([(1.0, "a")], Boom(), 10.0)


# ------------------------------------------------------------------ AC4 / AC5
def _approx(got, want):
    assert len(got) == len(want)
    for (a, b), (c, d) in zip(got, want):
        assert abs(a - c) < 1e-9 and abs(b - d) < 1e-9


def test_ac4_duck_intervals():
    _approx(voiceover.duck_intervals([(1.0, 2.0), (2.2, 3.0)], 10.0), [(0.85, 3.15)])
    _approx(voiceover.duck_intervals([(0.1, 0.5)], 10.0), [(0.0, 0.65)])
    _approx(voiceover.duck_intervals([(9.0, 10.0)], 10.0), [(8.85, 10.0)])
    assert voiceover.duck_intervals([], 10.0) == []
    # unsorted input, far apart -> sorted, separate
    _approx(voiceover.duck_intervals([(6.0, 7.0), (1.0, 2.0)], 10.0), [(0.85, 2.15), (5.85, 7.15)])


FMT = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"


def test_ac5_mix_filter_exact():
    assert voiceover.mix_filter([(1.85, 3.00714), (5.85, 7.29286)]) == (
        f"[0:a]{FMT},volume=volume=0.251189:enable='between(t,1.850,3.007)+between(t,5.850,7.293)'[bg];"
        f"[1:a]{FMT}[vo];[bg][vo]amix=inputs=2:duration=first:normalize=0[a]")
    assert voiceover.mix_filter([]) == (
        f"[0:a]{FMT}[bg];[1:a]{FMT}[vo];[bg][vo]amix=inputs=2:duration=first:normalize=0[a]")


# ------------------------------------------------------------------ AC6
def test_ac6_mix_audio_args(tmp_path, monkeypatch):
    clip, voice = tmp_path / "c.mp4", tmp_path / "v.wav"
    clip.write_bytes(b"x")
    voice.write_bytes(b"y")
    dest = tmp_path / "sub" / "o.mp4"
    calls = []

    class Done:
        returncode, stdout, stderr = 0, b"", b""

    monkeypatch.setattr(media.subprocess, "run", lambda a, **k: calls.append((a, k)) or Done())
    assert media.mix_audio(clip, voice, "G", dest) == Path(dest)
    assert calls == [([media.find_tool("ffmpeg"), "-v", "error", "-nostdin", "-y", "-i", str(clip),
                       "-i", str(voice), "-filter_complex", "G", "-map", "0:v:0", "-map", "[a]",
                       "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                       str(dest)], {"capture_output": True, "check": False})]


@pytest.mark.parametrize("missing", ["clip", "voice"])
def test_ac6_missing_input(tmp_path, monkeypatch, missing):
    files = {"clip": tmp_path / "c.mp4", "voice": tmp_path / "v.wav"}
    for name, p in files.items():
        if name != missing:
            p.write_bytes(b"x")
    monkeypatch.setattr(media.subprocess, "run", lambda *a, **k: pytest.fail("ffmpeg ran"))
    with pytest.raises(media.MediaError, match="^media file not found: "):
        media.mix_audio(files["clip"], files["voice"], "G", tmp_path / "o.mp4")


@needs_ffmpeg
def test_ac6_ffmpeg_failure_real(tmp_path):
    clip, voice = tmp_path / "c.mp4", tmp_path / "v.wav"
    clip.write_bytes(b"not a video")
    voice.write_bytes(b"not audio")
    with pytest.raises(media.MediaError, match="^ffmpeg failed for "):
        media.mix_audio(clip, voice, voiceover.mix_filter([]), tmp_path / "o.mp4")


# ------------------------------------------------------------------ AC7 / AC8 (real ffmpeg)
def test_ac7_real_mix_measured(clip10, tmp_path):
    before = _sha(clip10)
    dest = tmp_path / "clip_01.vo.mp4"
    assert voiceover.make_voiceover(LINES, ToneFake(), [(clip10, dest)]) == [dest]
    assert _sha(clip10) == before
    assert abs(media.probe_duration(dest) - media.probe_duration(clip10)) <= 0.1
    assert _streams(dest) == ["audio", "video"]
    vo, orig = media.extract_audio(dest), media.extract_audio(clip10)
    quiet = [(0.5, 1.5), (4.0, 5.0)]
    for t0, t1 in _windows():
        speech = tone_level(vo, 2000, t0, t1)
        for q0, q1 in quiet:
            assert db(speech, tone_level(vo, 2000, q0, q1)) >= 30, (t0, q0)
        assert db(tone_level(orig, 300, t0, t1), tone_level(vo, 300, t0, t1)) >= 8, (t0, t1)
    for t0, t1 in [(0.5, 1.5), (4.0, 5.0), (8.0, 9.5)]:
        assert abs(db(tone_level(vo, 300, t0, t1), tone_level(orig, 300, t0, t1))) <= 1, (t0, t1)


def test_ac7_voice_starts_at_scripted_time(clip10, tmp_path):
    """The tone is absent just before each scripted start (catches a voice placed late or early)."""
    dest = tmp_path / "vo.mp4"
    voiceover.make_voiceover(LINES, ToneFake(), [(clip10, dest)])
    vo = media.extract_audio(dest)
    for start, text in LINES:
        on = tone_level(vo, 2000, start + 0.05, start + 0.35)
        off = tone_level(vo, 2000, start - 0.45, start - 0.15)
        assert db(on, off) >= 30, start


def test_ac8_two_targets_one_synthesis_per_line(clip10, tmp_path):
    copy = tmp_path / "copy.mp4"
    shutil.copy(clip10, copy)
    fake = ToneFake()
    dests = [tmp_path / "a.vo.mp4", tmp_path / "vertical" / "b.vo.mp4"]
    assert voiceover.make_voiceover(LINES, fake, [(clip10, dests[0]), (copy, dests[1])]) == dests
    assert len(fake.calls) == 2
    for src, dest in zip([clip10, copy], dests):
        assert dest.is_file()
        assert abs(media.probe_duration(dest) - media.probe_duration(src)) <= 0.1


@needs_ffmpeg
@pytest.mark.parametrize("seconds,lines", [
    (1.0, [(0.5, "Vào! Bàn thắng! Tuyệt vời quá!")]),   # very short clip, speech truncated
    (3.0, []),                                          # no script lines -> no ducking
])
def test_ac7_edge_short_clip_and_empty_script(tmp_path, seconds, lines):
    clip = _make_clip(tmp_path / "c.mp4", seconds)
    dest = tmp_path / "c.vo.mp4"
    assert voiceover.make_voiceover(lines, ToneFake(), [(clip, dest)]) == [dest]
    assert abs(media.probe_duration(dest) - media.probe_duration(clip)) <= 0.1
    if not lines:
        vo, orig = media.extract_audio(dest), media.extract_audio(clip)
        assert abs(db(tone_level(vo, 300, 0.5, 2.5), tone_level(orig, 300, 0.5, 2.5))) <= 1


@needs_ffmpeg
def test_ac7_silent_clip(tmp_path):
    clip = _make_clip(tmp_path / "s.mp4", 4, amp=0.0)
    dest = tmp_path / "s.vo.mp4"
    voiceover.make_voiceover([(1.0, "Vào!")], ToneFake(), [(clip, dest)])
    vo = media.extract_audio(dest)
    assert db(tone_level(vo, 2000, 1.05, 1.2), tone_level(vo, 2000, 2.5, 3.5)) >= 30


# ------------------------------------------------------------------ AC9 / AC10
def test_ac9_download_voice(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    fetched = []
    monkeypatch.setattr(voiceover, "_fetch", lambda url, dest: (fetched.append(url), Path(dest).write_bytes(b"m")))
    url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium"
    assert voiceover.VOICE_URL == url
    path = voiceover.download_voice()
    assert path == tmp_path / "sportscut" / "piper" / "vi_VN-vais1000-medium.onnx" and path.is_file()
    assert fetched == [url + ".onnx", url + ".onnx.json"]
    fetched.clear()
    assert voiceover.download_voice() == path and fetched == []


def test_ac9_download_failure_cleans_up(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    def offline(url, dest):
        Path(dest).write_bytes(b"partial")
        raise OSError("offline")

    monkeypatch.setattr(voiceover, "_fetch", offline)
    with pytest.raises(OSError, match="offline"):
        voiceover.download_voice()
    left = list((tmp_path / "sportscut" / "piper").iterdir())
    assert not [p for p in left if p.name.endswith((".onnx", ".part"))]


def test_ac10_piper_lazy_load_once(monkeypatch):
    loads, downloads = [], []

    class Chunk:
        def __init__(self, arr):
            self.audio_float_array = arr

    class Voice:
        class config:
            sample_rate = 22050

        def synthesize(self, text):
            yield Chunk(np.array([0.1, 0.2], np.float64))
            yield Chunk(np.array([0.3], np.float64))

    class PiperVoice:
        @staticmethod
        def load(path):
            loads.append(path)
            return Voice()

    fake_mod = type(sys)("piper")
    fake_mod.PiperVoice = PiperVoice
    monkeypatch.setitem(sys.modules, "piper", fake_mod)
    monkeypatch.setattr(voiceover, "download_voice", lambda: downloads.append(1) or Path("/cache/v.onnx"))
    synth = voiceover.PiperSynthesizer()
    assert loads == [] and downloads == []
    a, b = synth.synthesize("x"), synth.synthesize("y")
    assert loads == ["/cache/v.onnx"]
    for arr in (a, b):
        assert arr.dtype == np.float32 and np.allclose(arr, [0.1, 0.2, 0.3])
    assert synth.sample_rate == 22050
    assert isinstance(voiceover.default_synthesizer(), voiceover.PiperSynthesizer)
    monkeypatch.setitem(sys.modules, "piper", None)
    assert voiceover.default_synthesizer() is None


# ------------------------------------------------------------------ AC11 / AC12 (pipeline)
def _script_count(out, entry):
    return len(json.loads((out / entry["script_file"]).read_text(encoding="utf-8"))["lines"])


def test_ac11_pipeline_writes_vo(burst_video, tmp_path):
    out, fake = tmp_path / "out", ToneFake()
    entries = pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, voiceover=True, synthesizer=fake)
    entry = entries[0]
    assert (out / "clip_01.script.json").is_file() and (out / "clip_01.vo.mp4").is_file()
    assert abs(media.probe_duration(out / "clip_01.vo.mp4") - media.probe_duration(out / "clip_01.mp4")) <= 0.1
    assert list(entry)[-2:] == ["script_file", "voiceover_file"] and entry["voiceover_file"] == "clip_01.vo.mp4"
    manifest = json.loads((out / "highlights.json").read_text(encoding="utf-8"))
    assert list(manifest[0])[-2:] == ["script_file", "voiceover_file"]
    assert len(fake.calls) == _script_count(out, entry)


def test_ac11_pipeline_vertical_vo(burst_video, tmp_path, monkeypatch):
    monkeypatch.setattr(vertical_mod, "render_vertical",
                        lambda clip, crop, dest, **kw: (Path(dest).parent.mkdir(parents=True, exist_ok=True),
                                                        shutil.copy(clip, dest)))
    out, fake = tmp_path / "out", ToneFake()
    entry = pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True,
                         voiceover=True, synthesizer=fake)[0]
    assert (out / "vertical" / "clip_01.vo.mp4").is_file()
    keys = ["script_file", "voiceover_file", "vertical_voiceover_file"]
    assert list(entry)[-3:] == keys and entry["vertical_voiceover_file"] == "vertical/clip_01.vo.mp4"
    assert list(json.loads((out / "highlights.json").read_text(encoding="utf-8"))[0])[-3:] == keys
    assert len(fake.calls) == _script_count(out, entry)


def test_ac12_synthesizer_without_voiceover(burst_video, tmp_path):
    fake = ToneFake()
    with pytest.raises(PipelineError, match="^synthesizer needs voiceover=True$"):
        pipeline.run(burst_video, tmp_path / "out", synthesizer=fake)
    assert not (tmp_path / "out" / "clip_01.mp4").exists() and fake.calls == []


def test_ac12_synthesis_failure(burst_video, tmp_path):
    with pytest.raises(PipelineError, match=r"^clip_01\.mp4: text-to-speech failed: boom$"):
        pipeline.run(burst_video, tmp_path / "out", top=1, min_len=4, max_len=6, voiceover=True,
                     synthesizer=ToneFake(fail=RuntimeError("boom")))


def test_ac12_no_synthesizer_is_t026(burst_video, tmp_path):
    out = tmp_path / "out"
    entries = pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, voiceover=True)
    assert not list(out.rglob("*.vo.mp4"))
    assert list(entries[0])[-1] == "script_file"


# ------------------------------------------------------------------ AC13 / AC14 (CLI)
@pytest.fixture
def recorded(monkeypatch):
    calls = []

    def fake_run(video, out, **kwargs):
        calls.append(kwargs)
        return [{"file": "clip_01.mp4"}]

    monkeypatch.setattr(cli, "run", fake_run)
    return calls


def test_ac13_forwards_synthesizer(recorded, monkeypatch, capsys, tmp_path):
    sentinel = object()
    monkeypatch.setattr(voiceover, "default_synthesizer", lambda: sentinel)
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--voiceover"]) == 0
    assert recorded[-1]["synthesizer"] is sentinel and capsys.readouterr().err == ""


def test_ac13_notice_without_extra(recorded, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(voiceover, "default_synthesizer", lambda: None)
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--voiceover"]) == 0
    assert recorded[-1]["synthesizer"] is None
    assert capsys.readouterr().err == ("sportscut: notice: voice-over needs the [tts] extra: "
                                       "pip install 'sportscut[tts]'; only the commentary scripts are written\n")


def test_ac13_no_flag_never_calls_default(recorded, monkeypatch, tmp_path):
    monkeypatch.setattr(voiceover, "default_synthesizer", lambda: pytest.fail("called"))
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path)]) == 0
    assert recorded[-1]["synthesizer"] is None


def test_ac13_stdout_order(monkeypatch, capsys, tmp_path):
    entry = {"file": "clip_01.mp4", "vertical_file": "vertical/clip_01.mp4", "script_file": "clip_01.script.json",
             "voiceover_file": "clip_01.vo.mp4", "vertical_voiceover_file": "vertical/clip_01.vo.mp4"}
    monkeypatch.setattr(cli, "run", lambda v, o, **k: [entry])
    monkeypatch.setattr(voiceover, "default_synthesizer", lambda: object())
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--voiceover", "--vertical"]) == 0
    assert capsys.readouterr().out.splitlines() == [str(tmp_path / v) for v in entry.values()]


def test_ac13_pipeline_error_exit_1(monkeypatch, capsys, tmp_path):
    def boom(video, out, **kw):
        raise PipelineError("clip_01.mp4: text-to-speech failed: boom")

    monkeypatch.setattr(cli, "run", boom)
    monkeypatch.setattr(voiceover, "default_synthesizer", lambda: object())
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--voiceover"]) == 1
    assert "sportscut: error: clip_01.mp4: text-to-speech failed: boom" in capsys.readouterr().err


def test_ac14_download_models_tts(monkeypatch, capsys):
    monkeypatch.setattr(voiceover, "download_voice", lambda: Path("/c/v.onnx"))
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setattr(cli.subtitles, "download_models", lambda *a, **k: pytest.fail("whisper touched"))
    assert cli.main(["download-models", "--tts"]) == 0
    assert capsys.readouterr().out == "downloaded Piper voice vi_VN-vais1000-medium to /c/v.onnx\n"


def test_ac14_download_models_tts_offline(monkeypatch, capsys):
    def offline():
        raise OSError("offline")

    monkeypatch.setattr(voiceover, "download_voice", offline)
    assert cli.main(["download-models", "--tts"]) == 1
    assert capsys.readouterr().err == "sportscut download-models: error: offline\n"


def test_ac14_help_lists_tts():
    out = subprocess.run([sys.executable, "-m", "sportscut", "download-models", "--help"], cwd=ROOT,
                         capture_output=True, text=True)
    assert out.returncode == 0 and "--tts" in out.stdout


# ------------------------------------------------------------------ AC15
def test_ac15_smoke_test_is_skipped_not_failed_without_piper():
    try:
        import piper  # noqa: F401
        pytest.skip("piper installed; the smoke test runs for real")
    except ImportError:
        pass
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "-rs", "tests/test_voiceover_piper_smoke.py"],
                         cwd=ROOT, capture_output=True, text=True)
    assert out.returncode in (0, 5), out.stdout   # 5 = whole module skipped by importorskip
    assert "skipped" in out.stdout and "failed" not in out.stdout and "passed" not in out.stdout


# ------------------------------------------------------------------ AC16 (docs)
def test_ac16_readme_section():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    head = "### Lồng tiếng bình luận (--voiceover)"
    i, j = readme.index(head), readme.index("## Theo dõi cầu thủ: đo độ chính xác (eval-player)")
    assert readme.index("### Kịch bản bình luận") < i < j
    section = readme[i:j]
    for needle in ("pip install 'sportscut[tts]'", "sportscut download-models --tts",
                   "sportscut cut match.mp4 --out out --voiceover --vertical", "clip_NN.vo.mp4",
                   "vertical/clip_NN.vo.mp4", "12 dB", "Piper", "~/.cache/sportscut/piper", "GPL-3.0"):
        assert needle in section, needle
    assert "```json" not in section
    assert "sẽ có ở task sau" not in readme


def test_ac16_eval_crop_section_last_and_unchanged():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    head = "## Video dọc 9:16: đo khung cắt (eval-crop)"
    tail = readme[readme.index(head):]
    assert "\n## " not in tail[len(head):]
    base = _base()
    if base:
        old = _git("show", f"{base}:README.md").stdout
        assert tail == old[old.index(head):]


@pytest.mark.parametrize("spec,needle", [
    ("2026-11-23-t-026-generate-a-timed-vietnamese-commentary-script-design.md", "clip_NN.vo.mp4"),
    ("2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md", "synthesizer=None"),
    ("2026-11-23-t-022-add-commentary-subtitles-to-vertical-clips-design.md", "download-models --tts"),
])
def test_ac16_spec_appendices(spec, needle):
    text = (ROOT / "docs/superpowers/specs" / spec).read_text(encoding="utf-8")
    appendix = text.split("## Updated by T-027", 1)
    assert len(appendix) == 2 and needle in appendix[1]
    assert "\n## " not in appendix[1]   # appended at the end
    base = _base()
    if base:
        old = _git("show", f"{base}:docs/superpowers/specs/{spec}").stdout
        assert text.startswith(old.rstrip("\n"))


# ------------------------------------------------------------------ AC17 (no regression)
def _main_tree(tmp_path):
    base = _base()
    if base is None:
        pytest.skip("no main branch to compare against")
    archive = subprocess.run(["git", "archive", base, "sportscut"], cwd=ROOT, capture_output=True)
    assert archive.returncode == 0
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(tmp_path, filter="data")
    return tmp_path


def _sportscut(cwd, pythonpath, *args):
    env = {**os.environ, "PYTHONPATH": str(pythonpath)}
    env.pop("ANTHROPIC_API_KEY", None)
    out = subprocess.run([sys.executable, "-m", "sportscut", *args], cwd=cwd, capture_output=True,
                         text=True, encoding="utf-8", env=env)
    assert out.returncode == 0, out.stderr
    return out.stdout


@needs_ffmpeg
def test_ac17_eval_f1_equals_main(tmp_path):
    main = _main_tree(tmp_path)
    fixture = str(ROOT / "tests/fixtures/eval")
    ours = json.loads(_sportscut(ROOT, ROOT, "eval", fixture, "--json"))
    theirs = json.loads(_sportscut(main, main, "eval", fixture, "--json"))
    assert ours["f1"] == theirs["f1"]


@pytest.mark.parametrize("extra", [[], ["--script"]])
def test_ac17_eval_meta_equals_main(tmp_path, extra):
    if not extra:
        _own_branch_base()  # template wording may change after T-027 (T-050); --script stays checked
    main = _main_tree(tmp_path)
    fixture = str(ROOT / "tests/fixtures/eval_meta")
    assert (_sportscut(ROOT, ROOT, "eval-meta", fixture, "--json", *extra)
            == _sportscut(main, main, "eval-meta", fixture, "--json", *extra))


def _own_branch_base():
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not branch.startswith("office/T-027"):
        pytest.skip("scope checks only run on office/T-027 branches")
    base = _base()
    if base is None:
        pytest.skip("no main branch to compare against")
    return base


def test_ac17_frozen_paths_unchanged():
    base = _own_branch_base()
    c = "sportscut/commentary/"
    paths = [c + "script.py", c + "facts.py", c + "meta.py", c + "llm.py", c + "eval_meta.py",
             "sportscut/export.py", "sportscut/models.py", "sportscut/api.py", "sportscut/vertical.py",
             "sportscut/subtitles.py", "sportscut/reframe.py", "sportscut/web/", "tests/conftest.py",
             "tests/fixtures/", "agent-office/"]
    assert _git("diff", "--name-only", base, "--", *paths).stdout.strip() == ""


def test_ac17_media_append_only_and_old_tests_untouched():
    base = _own_branch_base()
    added, deleted, _ = _git("diff", "--numstat", base, "--", "sportscut/media.py").stdout.split("\t")
    assert deleted == "0"
    old_tests = set(_git("ls-tree", "--name-only", base, "tests/").stdout.split())
    changed = _git("diff", "--name-status", base, "--", "tests/").stdout.splitlines()
    assert [l for l in changed if l.split("\t")[-1] in old_tests] == []
