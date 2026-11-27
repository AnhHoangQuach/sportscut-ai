"""T-027 voice-over: voice track placement, ducking, ffmpeg mix, Piper loading, pipeline and CLI."""
import hashlib
import json
import shutil
import subprocess
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from sportscut import cli, media, pipeline
from sportscut.commentary import script, voiceover
from sportscut.commentary.voiceover import SynthesisError, duck_intervals, mix_filter, voice_track
from sportscut.media import MediaError
from sportscut.pipeline import PipelineError

ROOT = Path(__file__).resolve().parents[1]


class Ones:
    """Fake synthesizer: sample_rate 1000, every line is 3000 ones (3.0 s)."""

    sample_rate = 1000

    def __init__(self, n=3000, value=1.0):
        self.calls, self.n, self.value = [], n, value

    def synthesize(self, text):
        self.calls.append(text)
        return np.full(self.n, self.value)


class Tone:
    """Fake synthesizer: 2000 Hz sine at 0.3, as long as the script's speech estimate."""

    sample_rate = 22050

    def __init__(self):
        self.calls = []

    def synthesize(self, text):
        self.calls.append(text)
        n = round(script.speech_seconds(text) * self.sample_rate)
        return (0.3 * np.sin(2 * np.pi * 2000 * np.arange(n) / self.sample_rate)).astype(np.float32)


class Boom:
    sample_rate = 22050

    def synthesize(self, text):
        raise RuntimeError("boom")


# ---------- voice_track (AC3) ----------

def test_voice_track_places_and_delays_next_line():
    fake = Ones()
    track, spoken = voice_track([(1.0, "a"), (2.0, "b")], fake, 10.0)
    assert spoken == [(1.0, 4.0), (4.0, 7.0)]
    assert track.dtype == np.float32 and len(track) == 10000
    assert np.all(track[1000:7000] == 1.0)
    assert np.all(track[:1000] == 0) and np.all(track[7000:] == 0)
    assert fake.calls == ["a", "b"]


def test_voice_track_truncates_at_clip_end():
    track, spoken = voice_track([(8.0, "x")], Ones(), 10.0)
    assert spoken == [(8.0, 10.0)]
    assert len(track) == 10000 and np.all(track[8000:] == 1.0) and np.all(track[:8000] == 0)


@pytest.mark.parametrize("lines", [[(10.0, "x")], []])
def test_voice_track_skips_without_synthesizing(lines):
    fake = Ones()
    track, spoken = voice_track(lines, fake, 10.0)
    assert spoken == [] and fake.calls == []
    assert len(track) == 10000 and not track.any()


def test_voice_track_skips_line_pushed_past_end():
    fake = Ones(n=12000)
    _, spoken = voice_track([(1.0, "a"), (2.0, "b")], fake, 10.0)
    assert spoken == [(1.0, 10.0)] and fake.calls == ["a"]


def test_voice_track_clips_values():
    track, _ = voice_track([(0.0, "a")], Ones(value=3.0), 10.0)
    assert track.max() == 1.0 and track.dtype == np.float32
    track, _ = voice_track([(0.0, "a")], Ones(value=-3.0), 10.0)
    assert track.min() == -1.0


def test_voice_track_synthesis_error():
    with pytest.raises(SynthesisError, match=r"^text-to-speech failed: boom$"):
        voice_track([(1.0, "a")], Boom(), 10.0)


def test_voice_track_sample_rate_error():
    class BadRate:
        @property
        def sample_rate(self):
            raise OSError("no voice")

    with pytest.raises(SynthesisError, match=r"^text-to-speech failed: no voice$"):
        voice_track([(1.0, "a")], BadRate(), 10.0)


# ---------- duck_intervals (AC4) ----------

def _close(got, want):
    assert len(got) == len(want)
    for (a, b), (c, d) in zip(got, want):
        assert abs(a - c) < 1e-9 and abs(b - d) < 1e-9


def test_duck_intervals_pad_and_merge():
    _close(duck_intervals([(1.0, 2.0), (2.2, 3.0)], 10.0), [(0.85, 3.15)])


def test_duck_intervals_clamp():
    _close(duck_intervals([(0.1, 0.5)], 10.0), [(0.0, 0.65)])
    _close(duck_intervals([(9.0, 10.0)], 10.0), [(8.85, 10.0)])


def test_duck_intervals_sorted_and_separate():
    _close(duck_intervals([(6.0, 7.0), (1.0, 2.0)], 10.0), [(0.85, 2.15), (5.85, 7.15)])


def test_duck_intervals_touching_merge():
    _close(duck_intervals([(1.0, 2.0), (2.3, 3.0)], 10.0), [(0.85, 3.15)])


def test_duck_intervals_empty():
    assert duck_intervals([], 10.0) == []


# ---------- mix_filter (AC5) ----------

FMT = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"


def test_mix_filter_exact():
    assert mix_filter([(1.85, 3.00714), (5.85, 7.29286)]) == (
        f"[0:a]{FMT},volume=volume=0.251189:"
        "enable='between(t,1.850,3.007)+between(t,5.850,7.293)'[bg];"
        f"[1:a]{FMT}[vo];[bg][vo]amix=inputs=2:duration=first:normalize=0[a]"
    )


def test_mix_filter_without_ducking():
    assert mix_filter([]) == (
        f"[0:a]{FMT}[bg];[1:a]{FMT}[vo];[bg][vo]amix=inputs=2:duration=first:normalize=0[a]"
    )


# ---------- media.mix_audio (AC6) ----------

def _files(tmp_path):
    clip, voice = tmp_path / "c.mp4", tmp_path / "v.wav"
    clip.write_bytes(b"c")
    voice.write_bytes(b"v")
    return clip, voice


def test_mix_audio_exact_args(tmp_path, monkeypatch):
    clip, voice = _files(tmp_path)
    dest = tmp_path / "sub" / "c.vo.mp4"
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, b"", b"")

    monkeypatch.setattr("sportscut.media.find_tool", lambda name: name)
    monkeypatch.setattr("sportscut.media.subprocess.run", fake_run)
    assert media.mix_audio(str(clip), str(voice), "GRAPH", str(dest)) == dest
    assert calls == [([
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(clip), "-i", str(voice),
        "-filter_complex", "GRAPH", "-map", "0:v:0", "-map", "[a]", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dest),
    ], {"capture_output": True, "check": False})]
    assert dest.parent.is_dir()


@pytest.mark.parametrize("missing", ["clip", "voice"])
def test_mix_audio_missing_input(tmp_path, monkeypatch, missing):
    clip, voice = _files(tmp_path)
    (clip if missing == "clip" else voice).unlink()
    monkeypatch.setattr("sportscut.media.subprocess.run", lambda *a, **k: pytest.fail("ffmpeg ran"))
    with pytest.raises(MediaError, match="^media file not found: "):
        media.mix_audio(clip, voice, "G", tmp_path / "o.mp4")


def test_mix_audio_ffmpeg_failure(tmp_path, monkeypatch):
    clip, voice = _files(tmp_path)
    monkeypatch.setattr("sportscut.media.find_tool", lambda name: name)
    monkeypatch.setattr(
        "sportscut.media.subprocess.run",
        lambda args, **k: subprocess.CompletedProcess(args, 1, b"", b"x\nbad graph\n"),
    )
    with pytest.raises(MediaError, match=r"^ffmpeg failed for .*c\.mp4: bad graph$"):
        media.mix_audio(clip, voice, "G", tmp_path / "o.mp4")


# ---------- make_voiceover with real ffmpeg (AC7, AC8) ----------

LINES = [(2.0, "Vào! Bàn thắng!"), (6.0, "Tỉ số 1-0.")]
SR = media.SAMPLE_RATE


@pytest.fixture(scope="module")
def tone_clip(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required on PATH")
    path = tmp_path_factory.mktemp("vo") / "clip_01.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=160x120:r=10:d=10",
        "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=44100:duration=10",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(path),
    ], check=True, capture_output=True)
    return path


def band_rms(samples, sr, f, t0, t1):
    seg = np.asarray(samples[int(t0 * sr):int(t1 * sr)], np.float64)
    spec = np.fft.rfft(seg)
    freqs = np.fft.rfftfreq(len(seg), 1 / sr)
    spec[np.abs(freqs - f) > 50] = 0
    return float(np.sqrt(np.mean(np.fft.irfft(spec, len(seg)) ** 2)))


def db(a, b):
    return 20 * np.log10(a / b)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _spoken_windows():
    return [(s + 0.15, s + script.speech_seconds(t) - 0.15) for s, t in LINES]


def test_make_voiceover_mix(tone_clip, tmp_path):
    before = _sha(tone_clip)
    dest = tmp_path / "clip_01.vo.mp4"
    assert voiceover.make_voiceover(LINES, Tone(), [(tone_clip, dest)]) == [dest]
    assert abs(media.probe_duration(dest) - media.probe_duration(tone_clip)) <= 0.1
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(dest)],
        capture_output=True, text=True, check=True,
    ).stdout.split()
    assert sorted(probe) == ["audio", "video"]
    orig, vo = media.extract_audio(tone_clip), media.extract_audio(dest)
    quiet = [(0.5, 1.5), (4.0, 5.0)]
    for t0, t1 in _spoken_windows():
        for q0, q1 in quiet:
            assert db(band_rms(vo, SR, 2000, t0, t1), band_rms(vo, SR, 2000, q0, q1)) >= 30
        assert db(band_rms(orig, SR, 300, t0, t1), band_rms(vo, SR, 300, t0, t1)) >= 8
    for t0, t1 in quiet + [(8.0, 9.5)]:
        assert abs(db(band_rms(vo, SR, 300, t0, t1), band_rms(orig, SR, 300, t0, t1))) <= 1
    assert _sha(tone_clip) == before


def test_make_voiceover_two_targets_synthesizes_once(tone_clip, tmp_path):
    copy = tmp_path / "copy.mp4"
    shutil.copy(tone_clip, copy)
    fake = Tone()
    dests = [tmp_path / "a.vo.mp4", tmp_path / "vertical" / "b.vo.mp4"]
    assert voiceover.make_voiceover(LINES, fake, [(tone_clip, dests[0]), (copy, dests[1])]) == dests
    assert fake.calls == [t for _, t in LINES]
    for src, dest in zip((tone_clip, copy), dests):
        assert abs(media.probe_duration(dest) - media.probe_duration(src)) <= 0.1


def test_write_wav_is_mono_16bit(tmp_path):
    import wave
    path = tmp_path / "v.wav"
    voiceover._write_wav(np.array([0.0, 0.5, -1.0], np.float32), 22050, path)
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 22050)
        assert np.frombuffer(w.readframes(3), "<i2").tolist() == [0, 16384, -32767]


# ---------- download_voice (AC9) ----------

URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
    "vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium"
)


def test_download_voice_fetches_in_order_then_reuses_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    calls = []

    def fake_fetch(url, dest):
        calls.append(url)
        assert dest.name.endswith(".part")
        dest.write_bytes(b"data")

    monkeypatch.setattr(voiceover, "_fetch", fake_fetch)
    assert voiceover.VOICE_URL == URL
    want = tmp_path / "sportscut" / "piper" / "vi_VN-vais1000-medium.onnx"
    assert voiceover.download_voice() == want
    assert calls == [URL + ".onnx", URL + ".onnx.json"]
    assert want.read_bytes() == b"data" and want.with_suffix(".onnx.json").is_file()
    calls.clear()
    assert voiceover.download_voice() == want and calls == []


def test_download_voice_default_cache_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert voiceover.voice_dir() == tmp_path / ".cache" / "sportscut" / "piper"


def test_download_voice_failure_leaves_no_files(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    def fake_fetch(url, dest):
        dest.write_bytes(b"half")
        raise OSError("offline")

    monkeypatch.setattr(voiceover, "_fetch", fake_fetch)
    with pytest.raises(OSError, match="offline"):
        voiceover.download_voice()
    left = [p.name for p in (tmp_path / "sportscut" / "piper").iterdir()]
    assert not [n for n in left if n.endswith((".onnx", ".part"))]


# ---------- PiperSynthesizer / default_synthesizer (AC10) ----------

@pytest.fixture
def fake_piper(monkeypatch):
    loads = []

    class Voice:
        config = types.SimpleNamespace(sample_rate=22050)

        def synthesize(self, text):
            yield types.SimpleNamespace(audio_float_array=np.array([0.1, 0.2]))
            yield types.SimpleNamespace(audio_float_array=np.array([0.3]))

    class PiperVoice:
        @staticmethod
        def load(path):
            loads.append(path)
            return Voice()

    module = types.ModuleType("piper")
    module.PiperVoice = PiperVoice
    monkeypatch.setitem(sys.modules, "piper", module)
    downloads = []
    monkeypatch.setattr(voiceover, "download_voice", lambda: downloads.append(1) or Path("/cache/v.onnx"))
    return loads, downloads


def test_piper_synthesizer_loads_lazily_once(fake_piper):
    loads, downloads = fake_piper
    synth = voiceover.PiperSynthesizer()
    assert loads == [] and downloads == []
    for _ in range(2):
        audio = synth.synthesize("Vào!")
        assert audio.dtype == np.float32
        assert np.allclose(audio, [0.1, 0.2, 0.3])
    assert loads == ["/cache/v.onnx"] and downloads == [1]
    assert synth.sample_rate == 22050


def test_piper_synthesizer_no_chunks(fake_piper, monkeypatch):
    synth = voiceover.PiperSynthesizer()
    synth._load()
    monkeypatch.setattr(synth._voice, "synthesize", lambda text: iter(()), raising=False)
    audio = synth.synthesize("")
    assert audio.dtype == np.float32 and audio.shape == (0,)


def test_default_synthesizer(fake_piper, monkeypatch):
    assert isinstance(voiceover.default_synthesizer(), voiceover.PiperSynthesizer)
    monkeypatch.setitem(sys.modules, "piper", None)
    assert voiceover.default_synthesizer() is None


# ---------- pipeline (AC11, AC12) ----------

def _script_lines(out, entry):
    record = json.loads((out / entry["script_file"]).read_text(encoding="utf-8"))
    return [line["text"] for line in record["lines"]]


def test_run_writes_voiceover_and_manifest_keys(burst_video, tmp_path):
    from sportscut.export import MANIFEST_NAME
    out, fake = tmp_path / "out", Tone()
    entries = pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, voiceover=True, synthesizer=fake)
    entry = entries[0]
    assert list(entry)[-2:] == ["script_file", "voiceover_file"]
    assert entry["voiceover_file"] == "clip_01.vo.mp4" and (out / "clip_01.script.json").is_file()
    assert abs(media.probe_duration(out / "clip_01.vo.mp4") - media.probe_duration(out / "clip_01.mp4")) <= 0.1
    assert fake.calls == _script_lines(out, entry)
    manifest = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert list(manifest[0])[-2:] == ["script_file", "voiceover_file"]


def test_run_vertical_voiceover(burst_video, tmp_path, monkeypatch):
    from sportscut import vertical
    from sportscut.export import MANIFEST_NAME

    def fake_render(clip, crop_path, dest, **kwargs):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(clip, dest)
        return Path(dest)

    monkeypatch.setattr(vertical, "render_vertical", fake_render)
    out, fake = tmp_path / "out", Tone()
    entries = pipeline.run(
        burst_video, out, top=1, min_len=4, max_len=6, vertical=True, voiceover=True, synthesizer=fake
    )
    keys = ["script_file", "voiceover_file", "vertical_voiceover_file"]
    assert list(entries[0])[-3:] == keys
    assert entries[0]["vertical_voiceover_file"] == "vertical/clip_01.vo.mp4"
    assert (out / "vertical" / "clip_01.vo.mp4").is_file() and (out / "clip_01.vo.mp4").is_file()
    assert fake.calls == _script_lines(out, entries[0])
    manifest = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert list(manifest[0])[-3:] == keys


def test_run_synthesizer_needs_voiceover(burst_video, tmp_path):
    fake = Tone()
    with pytest.raises(PipelineError, match=r"^synthesizer needs voiceover=True$"):
        pipeline.run(burst_video, tmp_path / "out", synthesizer=fake)
    assert not (tmp_path / "out" / "clip_01.mp4").exists() and fake.calls == []


def test_run_synthesis_error(burst_video, tmp_path):
    with pytest.raises(PipelineError, match=r"^clip_01\.mp4: text-to-speech failed: boom$"):
        pipeline.run(burst_video, tmp_path / "out", top=1, min_len=4, max_len=6, voiceover=True, synthesizer=Boom())


def test_run_without_synthesizer_is_t026(burst_video, tmp_path):
    out = tmp_path / "out"
    entries = pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, voiceover=True)
    assert list(entries[0])[-1] == "script_file" and not list(out.rglob("*.vo.mp4"))


# ---------- CLI (AC13, AC14) ----------

@pytest.fixture
def fake_run(monkeypatch):
    calls = []

    def run(video, out, **kwargs):
        calls.append(kwargs)
        return [{"file": "clip_01.mp4"}]

    monkeypatch.setattr(cli, "run", run)
    return calls


def test_cli_cut_forwards_synthesizer(fake_run, monkeypatch, capsys):
    synth = object()
    monkeypatch.setattr(voiceover, "default_synthesizer", lambda: synth)
    assert cli.main(["cut", "v.mp4", "--out", "O", "--voiceover"]) == 0
    assert fake_run[0]["synthesizer"] is synth and fake_run[0]["voiceover"] is True
    assert capsys.readouterr().err == ""


def test_cli_cut_without_extra_prints_notice(fake_run, monkeypatch, capsys):
    monkeypatch.setattr(voiceover, "default_synthesizer", lambda: None)
    assert cli.main(["cut", "v.mp4", "--out", "O", "--voiceover"]) == 0
    assert fake_run[0]["synthesizer"] is None
    assert capsys.readouterr().err == (
        "sportscut: notice: voice-over needs the [tts] extra: pip install 'sportscut[tts]'; "
        "only the commentary scripts are written\n"
    )


def test_cli_cut_without_flag_never_loads_tts(fake_run, monkeypatch):
    monkeypatch.setattr(voiceover, "default_synthesizer", lambda: pytest.fail("called"))
    assert cli.main(["cut", "v.mp4", "--out", "O"]) == 0
    assert fake_run[0]["synthesizer"] is None


def test_cli_cut_prints_voiceover_paths(monkeypatch, capsys):
    entry = {
        "file": "clip_01.mp4", "vertical_file": "vertical/clip_01.mp4",
        "script_file": "clip_01.script.json", "voiceover_file": "clip_01.vo.mp4",
        "vertical_voiceover_file": "vertical/clip_01.vo.mp4",
    }
    monkeypatch.setattr(cli, "run", lambda video, out, **kw: [entry])
    monkeypatch.setattr(voiceover, "default_synthesizer", lambda: object())
    assert cli.main(["cut", "v.mp4", "--out", "O", "--vertical", "--voiceover"]) == 0
    assert capsys.readouterr().out.splitlines() == [str(Path("O") / v) for v in entry.values()]


def test_cli_cut_pipeline_error(monkeypatch, capsys):
    def boom(video, out, **kw):
        raise PipelineError("clip_01.mp4: text-to-speech failed: boom")

    monkeypatch.setattr(cli, "run", boom)
    monkeypatch.setattr(voiceover, "default_synthesizer", lambda: object())
    assert cli.main(["cut", "v.mp4", "--out", "O", "--voiceover"]) == 1
    assert capsys.readouterr().err == "sportscut: error: clip_01.mp4: text-to-speech failed: boom\n"


def test_cli_download_models_tts(monkeypatch, capsys):
    from sportscut import subtitles
    monkeypatch.setattr(voiceover, "download_voice", lambda: Path("/c/v.onnx"))
    monkeypatch.setattr(subtitles, "download_models", lambda: pytest.fail("whisper"))
    assert cli.main(["download-models", "--tts"]) == 0
    assert capsys.readouterr().out == "downloaded Piper voice vi_VN-vais1000-medium to /c/v.onnx\n"


def test_cli_download_models_tts_failure(monkeypatch, capsys):
    def offline():
        raise OSError("offline")

    monkeypatch.setattr(voiceover, "download_voice", offline)
    assert cli.main(["download-models", "--tts"]) == 1
    assert capsys.readouterr().err == "sportscut download-models: error: offline\n"


def test_cli_help_lists_tts_and_voiceover(capsys):
    for argv in (["download-models", "--help"], ["cut", "--help"]):
        with pytest.raises(SystemExit):
            cli.main(argv)
    out = " ".join(capsys.readouterr().out.split())
    assert "--tts" in out and "clip_NN.vo.mp4" in out


# ---------- packaging and import rules (AC1, AC2) ----------

def test_pyproject_tts_extra():
    import tomllib
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["optional-dependencies"]
    assert extras["tts"] == ["piper-tts>=1.3"]
    assert not any("piper" in dep for dep in extras["dev"])


def test_no_voice_model_or_media_in_git():
    if shutil.which("git") is None:
        pytest.skip("git not available")
    files = subprocess.run(
        ["git", "ls-files", "*.onnx", "*.onnx.json", "*.mp4", "*.wav"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout
    assert files == ""


def test_imports_do_not_load_piper():
    code = (
        "import sys, sportscut.cli, sportscut.pipeline, sportscut.commentary.voiceover; "
        "print('piper' in sys.modules, 'onnxruntime' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout == "False False\n"


def test_voiceover_does_not_use_subprocess():
    assert "subprocess" not in (ROOT / "sportscut" / "commentary" / "voiceover.py").read_text(encoding="utf-8")
