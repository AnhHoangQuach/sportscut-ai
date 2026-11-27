"""T-027 smoke test with the real Piper voice (skipped without the [tts] extra or the voice).

The voice is downloaded into the user cache on first use; the test is skipped
when that download fails (offline). Not run in CI: the dev extra does not include piper.
"""
import shutil
import subprocess
import time

import numpy as np
import pytest

pytest.importorskip("piper")

from sportscut import media  # noqa: E402
from sportscut.commentary import script, voiceover  # noqa: E402
from sportscut.commentary.facts import ClipFacts  # noqa: E402


@pytest.fixture(scope="module")
def synth():
    try:
        voiceover.download_voice()
    except OSError as exc:
        pytest.skip(f"Piper voice not available: {exc}")
    return voiceover.PiperSynthesizer()


def test_real_synthesis_shape_and_speed(synth):
    audio = synth.synthesize("Vào! Bàn thắng!")
    sr = synth.sample_rate
    assert sr > 0 and audio.ndim == 1 and audio.dtype == np.float32
    assert 0.3 <= len(audio) / sr <= 5.0 and np.abs(audio).max() > 0.01
    lines = script.write_script(ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0"), 30.0)
    assert len(lines) == 3
    start = time.perf_counter()
    for _, text in lines:
        synth.synthesize(text)
    assert time.perf_counter() - start < 5.0


def test_real_make_voiceover(synth, tmp_path):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required on PATH")
    clip = tmp_path / "clip_01.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=160x120:r=10:d=6",
        "-f", "lavfi", "-i", "sine=frequency=300:sample_rate=44100:duration=6",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(clip),
    ], check=True, capture_output=True)
    dest = tmp_path / "clip_01.vo.mp4"
    voiceover.make_voiceover([(1.0, "Vào! Bàn thắng!")], synth, [(clip, dest)])
    assert abs(media.probe_duration(dest) - media.probe_duration(clip)) <= 0.1
