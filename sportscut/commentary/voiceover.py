"""Vietnamese voice-over for clips: offline text-to-speech mixed over the clip with ducking.

The TTS engine (Piper) is an optional extra and is only imported when a voice is
actually loaded. All ffmpeg work goes through `sportscut.media`.
"""

import os
import shutil
import tempfile
import urllib.request
import wave
from pathlib import Path
from typing import Protocol

import numpy as np

from sportscut import media

VOICE = "vi_VN-vais1000-medium"
VOICE_URL = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
             "vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium")   # + ".onnx" / ".onnx.json"
TTS_HINT = "pip install 'sportscut[tts]'"
DUCK_DB = 12.0           # original audio is lowered by this much while speech plays
DUCK_PAD = 0.15          # s of ducking before and after each spoken interval
MIX_RATE = 48000


class SynthesisError(RuntimeError):
    """The text-to-speech engine failed on a script line."""


class Synthesizer(Protocol):
    sample_rate: int

    def synthesize(self, text: str) -> np.ndarray:
        """Mono float samples in [-1, 1] at self.sample_rate."""


def voice_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "sportscut" / "piper"


def _fetch(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as out:
        shutil.copyfileobj(response, out)


def download_voice() -> Path:
    """Download the Piper voice (.onnx + .onnx.json) into voice_dir() once and return the .onnx path."""
    folder = voice_dir()
    folder.mkdir(parents=True, exist_ok=True)
    for suffix in (".onnx", ".onnx.json"):
        final = folder / f"{VOICE}{suffix}"
        if final.exists():
            continue
        part = folder / f"{VOICE}{suffix}.part"
        try:
            _fetch(VOICE_URL + suffix, part)
            part.replace(final)
        except BaseException:
            part.unlink(missing_ok=True)
            raise
    return folder / f"{VOICE}.onnx"


class PiperSynthesizer:
    """Piper on CPU; the voice is downloaded and loaded on first use, once."""

    def __init__(self):
        self._voice = None

    def _load(self) -> None:
        if self._voice is None:
            path = download_voice()
            from piper import PiperVoice
            self._voice = PiperVoice.load(str(path))

    @property
    def sample_rate(self) -> int:
        self._load()
        return int(self._voice.config.sample_rate)

    def synthesize(self, text: str) -> np.ndarray:
        self._load()
        chunks = [np.asarray(c.audio_float_array, np.float32) for c in self._voice.synthesize(text)]
        return np.concatenate(chunks) if chunks else np.zeros(0, np.float32)


def default_synthesizer() -> PiperSynthesizer | None:
    """Return a PiperSynthesizer, or None when the [tts] extra is not installed."""
    try:
        import piper  # noqa: F401
    except ImportError:
        return None
    return PiperSynthesizer()


def voice_track(lines, synthesizer, duration) -> tuple[np.ndarray, list[tuple[float, float]]]:
    """Place each (start, text) line at its time; a line that would overlap is delayed."""
    try:
        sr = int(synthesizer.sample_rate)
    except Exception as exc:
        raise SynthesisError(f"text-to-speech failed: {exc}") from exc
    track = np.zeros(round(duration * sr), np.float32)
    spoken, prev_end = [], 0
    for start, text in lines:
        pos = max(round(start * sr), prev_end)
        if pos >= len(track):
            continue
        try:
            audio = np.asarray(synthesizer.synthesize(text), np.float32).ravel()
        except Exception as exc:
            raise SynthesisError(f"text-to-speech failed: {exc}") from exc
        end = min(pos + len(audio), len(track))
        track[pos:end] = audio[: end - pos]
        prev_end = end
        if end > pos:
            spoken.append((pos / sr, end / sr))
    return np.clip(track, -1, 1), spoken


def duck_intervals(spoken, duration) -> list[tuple[float, float]]:
    """Pad each spoken interval by DUCK_PAD, clamp to [0, duration], sort and merge."""
    padded = sorted(
        (max(0.0, start - DUCK_PAD), min(duration, end + DUCK_PAD)) for start, end in spoken
    )
    merged: list[tuple[float, float]] = []
    for start, end in padded:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def mix_filter(duck) -> str:
    """ffmpeg filter graph: [0:a] lowered by DUCK_DB on `duck`, plus [1:a] (voice), as [a]."""
    fmt = f"aformat=sample_fmts=fltp:sample_rates={MIX_RATE}:channel_layouts=stereo"
    bg = f"[0:a]{fmt}"
    if duck:
        enable = "+".join(f"between(t,{s:.3f},{e:.3f})" for s, e in duck)
        bg += f",volume=volume={10 ** (-DUCK_DB / 20):.6f}:enable='{enable}'"
    return f"{bg}[bg];[1:a]{fmt}[vo];[bg][vo]amix=inputs=2:duration=first:normalize=0[a]"


def _write_wav(samples, sr, path) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sr)
        out.writeframes(np.round(np.asarray(samples) * 32767).astype("<i2").tobytes())


def make_voiceover(lines, synthesizer, targets) -> list[Path]:
    """Synthesize `lines` once and mix them over every (clip, dest) target; clips are only read."""
    duration = media.probe_duration(targets[0][0])
    track, spoken = voice_track(lines, synthesizer, duration)
    graph = mix_filter(duck_intervals(spoken, duration))
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "voice.wav"
        _write_wav(track, int(synthesizer.sample_rate), wav)
        return [media.mix_audio(clip, wav, graph, dest) for clip, dest in targets]
