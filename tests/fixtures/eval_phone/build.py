"""Synthetic phone/pitch-side eval set (T-055, R-010).

No scoreboard; a static fence/roofline in the top band that shifts 3 px at camera pans.
A goal is a 7-8 s cheer (+12 dB, 300-3000 Hz) followed by a kickoff whistle 40 s later.
Reuses the broadcast builder's constants and noise helpers (that file is frozen).
"""
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import wave

import numpy as np


HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("eval_phone_base_build", HERE.parent / "eval" / "build.py")
_BASE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_BASE)
W, H, FPS, AUDIO_RATE = _BASE.W, _BASE.H, _BASE.FPS, _BASE.AUDIO_RATE
_band_noise, _ramp = _BASE._band_noise, _BASE._ramp

DURATION = 600.0
KICKOFF_AFTER = 40.0
GOAL_LABEL = (-10.0, 6.0)
CHANCE_LABEL = (-4.0, 4.0)
EVENT_DB = 12.0
AMBIENT_RMS = 0.02
EVENT_RMS = AMBIENT_RMS * math.sqrt(10 ** (EVENT_DB / 10) - 1)
RAMP_SEC = 0.3
WHISTLE_HZ, WHISTLE_AMP, WHISTLE_SEC = 3000, 0.1, 1.0
PAN_SHIFT, POST_PERIOD = 3, 8
CASES = {
    "pitch_a": {"seed": 1501, "goals": [(120.0, 7.0), (395.0, 8.0)],
                "chances": [(50.0, 2.0), (270.0, 2.5), (520.0, 3.0)],
                "gust": (300.0, 8.0), "pans": [75, 160, 245, 330, 420, 500, 580]},
    "pitch_b": {"seed": 1502, "goals": [(200.0, 7.5), (450.0, 8.0)],
                "chances": [(90.0, 3.0), (330.0, 2.0), (540.0, 2.5)],
                "gust": (150.0, 10.0), "pans": [65, 140, 235, 300, 390, 475, 560]},
}


def case_labels(name):
    case = CASES[name]
    labels = [{"start": float(t0 + GOAL_LABEL[0]), "end": float(t0 + GOAL_LABEL[1]), "type": "goal"}
              for t0, _ in case["goals"]]
    labels += [{"start": float(t0 + CHANCE_LABEL[0]), "end": float(t0 + CHANCE_LABEL[1]), "type": "chance"}
               for t0, _ in case["chances"]]
    return sorted(labels, key=lambda item: item["start"])


def pan_offset(name, t):
    return (PAN_SHIFT * sum(t >= p for p in CASES[name]["pans"])) % POST_PERIOD


def render_frame(name, t):
    frame = np.empty((H, W, 3), dtype=np.uint8)
    frame[0:8] = (170, 190, 210)
    frame[8:10] = (30, 30, 30)
    frame[10:22] = (60, 60, 60)
    posts = (np.arange(W) - pan_offset(name, t)) % POST_PERIOD < 2
    frame[10:22, posts] = (230, 230, 230)
    frame[22:] = (40, 140, 60)
    bx = round(80 + 60 * math.sin(0.37 * t))
    by = round(60 + 20 * math.sin(0.23 * t + 1))
    yy, xx = np.ogrid[-2:3, -2:3]
    region = frame[by - 2:by + 3, bx - 2:bx + 3]
    region[xx * xx + yy * yy <= 4] = 255
    return frame


def _plateau(envelope, t0, duration, level):
    start, end = round(t0 * AUDIO_RATE), round((t0 + duration) * AUDIO_RATE)
    ramp = round(RAMP_SEC * AUDIO_RATE)
    _ramp(envelope, start, start + ramp, 0.0, level)
    envelope[start + ramp:end - ramp] = level
    _ramp(envelope, end - ramp, end, level, 0.0)


def audio_track(name):
    case = CASES[name]
    size = round(DURATION * AUDIO_RATE)
    rng = np.random.default_rng(case["seed"])
    ambient = _band_noise(rng, size, 100, 4000)
    cheer = _band_noise(rng, size, 300, 3000)
    gust = _band_noise(rng, size, 30, 300)
    cheer_env = np.zeros(size, dtype=np.float32)
    gust_env = np.zeros(size, dtype=np.float32)
    for t0, duration in [*case["goals"], *case["chances"]]:
        _plateau(cheer_env, t0, duration, EVENT_RMS)
    _plateau(gust_env, *case["gust"], EVENT_RMS)
    mix = AMBIENT_RMS * ambient + cheer_env * cheer + gust_env * gust
    length = round(WHISTLE_SEC * AUDIO_RATE)
    local = np.arange(length, dtype=np.float64) / AUDIO_RATE
    fade = np.minimum(1.0, np.minimum(local / 0.02, (WHISTLE_SEC - local) / 0.02))
    tone = (WHISTLE_AMP * fade * np.sin(2 * np.pi * WHISTLE_HZ * local)).astype(np.float32)
    for t0, _ in case["goals"]:
        start = round((t0 + KICKOFF_AFTER) * AUDIO_RATE)
        mix[start:start + length] += tone
    return np.clip(mix, -1, 1).astype(np.float32)


def _encode(name, output):
    temporary = output.parent / ".video.tmp.mp4"
    temporary.unlink(missing_ok=True)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "audio.wav"
            with wave.open(str(audio_path), "wb") as audio_file:
                audio_file.setnchannels(1)
                audio_file.setsampwidth(2)
                audio_file.setframerate(AUDIO_RATE)
                audio_file.writeframes(np.round(audio_track(name) * 32767).astype("<i2").tobytes())
            command = [
                "ffmpeg", "-nostdin", "-v", "error", "-f", "rawvideo",
                "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                "-i", "pipe:0", "-i", str(audio_path), "-c:v", "mpeg4",
                "-q:v", "2", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-b:a", "64k", "-ar", str(AUDIO_RATE), "-ac", "1",
                "-t", str(DURATION), "-y", str(temporary),
            ]
            with tempfile.TemporaryFile() as errors:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
                try:
                    for index in range(round(DURATION * FPS)):
                        process.stdin.write(render_frame(name, index / FPS).tobytes())
                    process.stdin.close()
                except BrokenPipeError:
                    try:
                        process.stdin.close()
                    except BrokenPipeError:
                        pass
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
                code = process.wait()
                errors.seek(0)
                stderr = errors.read().decode(errors="replace").strip()
            if code:
                raise RuntimeError(stderr)
        os.replace(temporary, output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def build_all(out_dir=HERE, force=False):
    out_dir = Path(out_dir)
    videos = []
    for name in CASES:
        directory = out_dir / name
        directory.mkdir(parents=True, exist_ok=True)
        labels = json.dumps(case_labels(name), indent=1) + "\n"
        label_path = directory / "labels.json"
        changed = not label_path.exists() or label_path.read_text() != labels
        if changed:
            label_path.write_text(labels)
        video = directory / "video.mp4"
        videos.append(video)
        if not video.exists() or changed or force:
            _encode(name, video)
    return videos


if __name__ == "__main__":
    build_all(force="--force" in sys.argv)
