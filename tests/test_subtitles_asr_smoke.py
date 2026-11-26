"""T-022 smoke test with the real faster-whisper model (skipped without the [asr] extra).

Speech is synthesized with `say` (macOS) or `espeak-ng`/`espeak`; the test is
skipped when no such tool or voice is available. Not run in CI: the dev extra
does not include faster-whisper.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("faster_whisper")

from sportscut import media, subtitles  # noqa: E402

VI_LETTERS = set("àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ")


def _say_has_vi() -> bool:
    out = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    return any("vi_VN" in line and line.split()[0] == "Linh" for line in out.splitlines())


def _speak(text: str, lang: str, dest_dir: Path) -> Path:
    """Write text as speech to an audio file, or skip when no TTS tool or voice exists."""
    if shutil.which("say"):
        if lang == "vi" and not _say_has_vi():
            pytest.skip("say has no Vietnamese voice (Linh)")
        out = dest_dir / "speech.aiff"
        voice = ["-v", "Linh"] if lang == "vi" else []
        subprocess.run(["say", *voice, "-o", str(out), text], check=True, capture_output=True)
        return out
    for tool in ("espeak-ng", "espeak"):
        if shutil.which(tool):
            out = dest_dir / "speech.wav"
            voice = ["-v", "vi"] if lang == "vi" else []
            result = subprocess.run([tool, *voice, "-w", str(out), text], capture_output=True)
            if result.returncode or not out.is_file():
                pytest.skip(f"{tool} cannot speak {lang}")
            return out
    pytest.skip("no text-to-speech tool (say, espeak-ng, espeak) on PATH")


def _clip(text: str, lang: str, tmp_path: Path) -> Path:
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required on PATH")
    speech = _speak(text, lang, tmp_path)
    clip = tmp_path / "clip_01.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x120:r=10",
         "-i", str(speech), "-shortest", "-c:v", "mpeg4", "-pix_fmt", "yuv420p", "-c:a", "aac",
         str(clip)],
        check=True, capture_output=True,
    )
    return clip


def test_real_model_english(tmp_path):
    clip = _clip("What a goal! The home team scores in the final minute.", "en", tmp_path)
    cues = subtitles.transcribe(clip, subtitles.WhisperTranscriber())
    duration = media.probe_duration(clip)
    assert len(cues) >= 1
    for start, end, _ in cues:
        assert 0 <= start < end <= duration + 0.05
    assert "goal" in " ".join(text for _, _, text in cues).lower()


def test_real_model_vietnamese(tmp_path):
    clip = _clip("Vào rồi! Một bàn thắng tuyệt đẹp", "vi", tmp_path)
    cues = subtitles.transcribe(clip, subtitles.WhisperTranscriber())
    assert len(cues) >= 1
    joined = " ".join(text for _, _, text in cues).lower()
    assert VI_LETTERS & set(joined)
