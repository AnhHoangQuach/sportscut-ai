"""Commentary subtitles for vertical clips: speech-to-text, layout and SRT files.

The speech-to-text model (faster-whisper) is an optional extra and is only
imported when a transcription or a model download actually happens.
"""

import textwrap
import unicodedata
from pathlib import Path
from typing import Iterable, Protocol

import numpy as np

from sportscut import media

MODEL_NAME = "base"
WRAP_CHARS = 28         # max characters per subtitle line (fits 1080 px at fontsize 56)
MAX_LINES = 2            # lines shown at once
ASR_HINT = "pip install 'sportscut[asr]'"
Cue = tuple[float, float, str]   # (start s, end s, text), times relative to the clip


class TranscriptionError(RuntimeError):
    """The speech-to-text engine failed on a clip."""


class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray) -> Iterable[tuple[float, float, str]]:
        """audio: float32 mono at media.SAMPLE_RATE (16 kHz). Returns (start, end, text) in seconds."""


class WhisperTranscriber:
    """faster-whisper `base` on CPU; the model is loaded on the first transcription."""

    def __init__(self):
        self._model = None

    def transcribe(self, audio):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
        segments, _info = self._model.transcribe(
            audio, language=None, vad_filter=True, condition_on_previous_text=False
        )
        return [(s.start, s.end, s.text) for s in segments]


def default_transcriber() -> WhisperTranscriber | None:
    """Return a WhisperTranscriber, or None when the [asr] extra is not installed."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return None
    return WhisperTranscriber()


def download_models() -> Path:
    """Download the speech-to-text model into the Hugging Face cache and return its path."""
    from faster_whisper import download_model   # ImportError propagates to the CLI
    return Path(download_model(MODEL_NAME))


def transcribe(clip, transcriber: Transcriber) -> list[Cue]:
    """Return the clip's commentary as sorted, clamped, NFC-normalised cues."""
    audio = media.extract_audio(clip)
    if audio.size == 0:
        return []
    try:
        items = list(transcriber.transcribe(audio))
    except Exception as exc:
        raise TranscriptionError(f"speech-to-text failed for {Path(clip).name}: {exc}") from exc
    duration = audio.size / media.SAMPLE_RATE
    cues: list[Cue] = []
    for start, end, text in items:
        text = unicodedata.normalize("NFC", " ".join(str(text).split()))
        start = max(0.0, float(start))
        end = min(float(end), duration)
        if text and end > start:
            cues.append((start, end, text))
    return sorted(cues, key=lambda cue: (cue[0], cue[1]))


def layout(cues) -> list[Cue]:
    """Wrap each cue to WRAP_CHARS and split it into chunks of at most MAX_LINES lines.

    A cue's time is shared between its chunks in proportion to their characters.
    """
    out: list[Cue] = []
    for start, end, text in cues:
        lines = textwrap.wrap(text, WRAP_CHARS, break_long_words=True, break_on_hyphens=False)
        chunks = [lines[i:i + MAX_LINES] for i in range(0, len(lines), MAX_LINES)]
        if len(chunks) <= 1:
            out.append((start, end, "\n".join(lines)))
            continue
        total = sum(len(line) for line in lines)
        cum = 0
        chunk_start = start
        for k, chunk in enumerate(chunks):
            cum += sum(len(line) for line in chunk)
            chunk_end = end if k == len(chunks) - 1 else start + (end - start) * cum / total
            out.append((chunk_start, chunk_end, "\n".join(chunk)))
            chunk_start = chunk_end
    return out


def srt_time(t: float) -> str:
    """Return t seconds as an SRT timestamp HH:MM:SS,mmm."""
    ms = round(t * 1000)
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}"


def write_srt(cues, path) -> Path:
    """Write cues as a UTF-8 SRT file with LF newlines; zero cues give an empty file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for i, (start, end, text) in enumerate(cues, 1):
            f.write(f"{i}\n{srt_time(start)} --> {srt_time(end)}\n{text}\n\n")
    return path
