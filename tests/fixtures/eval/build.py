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
W, H, FPS = 160, 90, 10
AUDIO_RATE = 16_000
SCOREBOARD = (2, 2, 30, 14)
DISTRACTORS = ("swell", "chant")
MATCHES = {
    "cards": {"duration": 180.0, "events": [
        ("red_card", 20), ("save", 50), ("controversy", 75),
        ("swell", 130), ("red_card", 155),
    ]},
    "controversy": {"duration": 180.0, "events": [
        ("controversy", 20), ("goal", 75, "away"), ("chant", 105),
        ("controversy", 130),
    ]},
    "goals_saves": {"duration": 180.0, "events": [
        ("goal", 20, "home"), ("save", 55), ("swell", 75),
        ("goal", 100, "away"), ("save", 140), ("chant", 160),
    ]},
    "mixed": {"duration": 180.0, "events": [
        ("save", 15), ("red_card", 40), ("goal", 70, "home"),
        ("swell", 105), ("goal", 125, "home"), ("save", 160),
    ]},
}
SEEDS = {name: 1101 + index for index, name in enumerate(MATCHES)}

_LABEL_OFFSETS = {
    "goal": (-2.0, 10.0),
    "save": (-4.0, 4.0),
    "red_card": (-2.0, 8.0),
    "controversy": (-4.0, 6.0),
}
_FOOTPRINT_OFFSETS = {
    "goal": (-3.0, 18.0),
    "save": (-4.0, 4.0),
    "red_card": (-2.0, 12.0),
    "controversy": (-6.0, 36.0),
    "swell": (0.0, 5.0),
    "chant": (0.0, 6.0),
}
FONT = {
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"),
    "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "111"),
}


def match_labels(name):
    labels = []
    for event in MATCHES[name]["events"]:
        kind, t0 = event[:2]
        if kind in DISTRACTORS:
            continue
        start, end = _LABEL_OFFSETS[kind]
        labels.append({"start": float(t0 + start), "end": float(t0 + end), "type": kind})
    return sorted(labels, key=lambda item: item["start"])


def footprints(name):
    spans = []
    for event in MATCHES[name]["events"]:
        kind, t0 = event[:2]
        start, end = _FOOTPRINT_OFFSETS[kind]
        spans.append((kind, float(t0 + start), float(t0 + end)))
    return sorted(spans, key=lambda item: item[1])


def score_at(name, t):
    score = [0, 0]
    for kind, t0, *details in MATCHES[name]["events"]:
        if kind == "goal" and t >= t0 + 1.0:
            score[details[0] == "away"] += 1
    return tuple(score)


def play_clock(name, t):
    frozen = 0.0
    for kind, t0, *_ in MATCHES[name]["events"]:
        duration = 12 if kind == "red_card" else 36 if kind == "controversy" else 0
        frozen += min(max(t - t0, 0.0), duration)
    return t - frozen


def _replay_source(name, t):
    for kind, t0, *_ in MATCHES[name]["events"]:
        if kind == "goal" and t0 + 13 <= t < t0 + 18:
            return t0 - 3 + (t - (t0 + 13))
        if kind == "controversy" and t0 + 20 <= t < t0 + 26:
            return t0 - 6 + (t - (t0 + 20))
    return t


def _draw_digit(frame, digit, x, y):
    for row, bits in enumerate(FONT[str(digit)]):
        for column, bit in enumerate(bits):
            if bit == "1":
                frame[y + row * 2:y + row * 2 + 2,
                      x + column * 2:x + column * 2 + 2] = 255


def render_frame(name, t):
    display_t = _replay_source(name, t)
    # Close-ups follow replay source time; extending MATCHES could replay one.
    closeup = any(kind == "red_card" and t0 + 4 <= display_t < t0 + 8
                  for kind, t0, *_ in MATCHES[name]["events"])
    frame = np.empty((H, W, 3), dtype=np.uint8)
    if closeup:
        frame[:] = (200, 20, 20)
        x, y, w, h = (W - 24) // 2, (H - 32) // 2, 24, 32
        frame[y:y + h, x:x + w] = (230, 190, 160)
    else:
        frame[:] = (40, 140, 60)
        for x in range(16, W, 32):
            frame[:, x:x + 16] = (36, 128, 54)
        clock = play_clock(name, display_t)
        bx = round(80 + 60 * math.sin(0.37 * clock) + 10 * math.sin(1.3 * clock))
        by = round(52 + 24 * math.sin(0.23 * clock + 1) + 8 * math.sin(0.9 * clock))
        yy, xx = np.ogrid[-2:3, -2:3]
        region = frame[by - 2:by + 3, bx - 2:bx + 3]
        region[xx * xx + yy * yy <= 4] = 255

    x, y, w, h = SCOREBOARD
    frame[y:y + h, x:x + w] = 0
    home, away = score_at(name, t)
    _draw_digit(frame, home, 5, 4)
    frame[8:10, 14:18] = 255
    _draw_digit(frame, away, 21, 4)
    return frame


def _band_noise(rng, size, low, high):
    spectrum = np.fft.rfft(rng.standard_normal(size))
    frequencies = np.fft.rfftfreq(size, 1 / AUDIO_RATE)
    spectrum[(frequencies < low) | (frequencies > high)] = 0
    noise = np.fft.irfft(spectrum, size).astype(np.float32)
    noise /= np.sqrt(np.mean(noise.astype(np.float64) ** 2))
    return noise


def _ramp(envelope, start, end, first, last):
    envelope[start:end] = np.linspace(first, last, end - start, endpoint=False)


def audio_track(name):
    duration = MATCHES[name]["duration"]
    size = round(duration * AUDIO_RATE)
    rng = np.random.default_rng(SEEDS[name])
    crowd = _band_noise(rng, size, 200, 2000)
    boo = _band_noise(rng, size, 60, 200)
    crowd_env = np.full(size, 0.02, dtype=np.float32)
    boo_env = np.zeros(size, dtype=np.float32)
    whistles = []

    for kind, t0, *_ in MATCHES[name]["events"]:
        start = round(t0 * AUDIO_RATE)
        if kind == "goal":
            rise = start + round(0.5 * AUDIO_RATE)
            fall = start + 9 * AUDIO_RATE
            end = start + 10 * AUDIO_RATE
            _ramp(crowd_env, start, rise, 0.02, 0.2)
            crowd_env[rise:fall] = 0.2
            _ramp(crowd_env, fall, end, 0.2, 0.02)
        elif kind == "save":
            rise = start + round(0.1 * AUDIO_RATE)
            fall = start + 2 * AUDIO_RATE
            end = start + round(2.5 * AUDIO_RATE)
            _ramp(crowd_env, start, rise, 0.02, 0.2)
            crowd_env[rise:fall] = 0.2
            _ramp(crowd_env, fall, end, 0.2, 0.02)
        elif kind in ("red_card", "controversy"):
            whistles.append(start)
            stop = t0 + (12 if kind == "red_card" else 36)
            crowd_env[(t0 + 1) * AUDIO_RATE:stop * AUDIO_RATE] = 0.005
            if kind == "controversy":
                boo_start = (t0 + 3) * AUDIO_RATE
                boo_rise = boo_start + round(0.5 * AUDIO_RATE)
                boo_fall = (t0 + 33) * AUDIO_RATE - round(0.5 * AUDIO_RATE)
                boo_end = (t0 + 33) * AUDIO_RATE
                _ramp(boo_env, boo_start, boo_rise, 0.0, 0.08)
                boo_env[boo_rise:boo_fall] = 0.08
                _ramp(boo_env, boo_fall, boo_end, 0.08, 0.0)
        elif kind == "swell":
            peak = start + round(2.5 * AUDIO_RATE)
            end = start + 5 * AUDIO_RATE
            _ramp(crowd_env, start, peak, 0.02, 0.08)
            _ramp(crowd_env, peak, end, 0.08, 0.02)
        elif kind == "chant":
            length = 6 * AUDIO_RATE
            local = np.arange(length, dtype=np.float64) / AUDIO_RATE
            gain = np.minimum(np.minimum(local / 2, (6 - local) / 2), 1.0)
            target = 0.08 * (0.6 + 0.4 * np.sin(2 * np.pi * 2 * local))
            crowd_env[start:start + length] = 0.02 + gain * (target - 0.02)

    mix = crowd_env * crowd + boo_env * boo
    length = AUDIO_RATE
    local = np.arange(length, dtype=np.float64) / AUDIO_RATE
    fade = np.minimum(1.0, np.minimum(local / 0.02, (1.0 - local) / 0.02))
    tone = (0.3 * fade * np.sin(2 * np.pi * 3000 * local)).astype(np.float32)
    for start in whistles:
        mix[start:start + length] += tone
    return np.clip(mix, -1, 1).astype(np.float32)


def _encode_match(name, output):
    temporary = output.parent / ".video.tmp.mp4"
    temporary.unlink(missing_ok=True)
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_path = Path(temp_dir) / "audio.wav"
            samples = audio_track(name)
            with wave.open(str(audio_path), "wb") as audio_file:
                audio_file.setnchannels(1)
                audio_file.setsampwidth(2)
                audio_file.setframerate(AUDIO_RATE)
                pcm = np.round(samples * 32767).astype("<i2")
                audio_file.writeframes(pcm.tobytes())
            duration = MATCHES[name]["duration"]
            command = [
                "ffmpeg", "-nostdin", "-v", "error", "-f", "rawvideo",
                "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                "-i", "pipe:0", "-i", str(audio_path), "-c:v", "mpeg4",
                "-q:v", "2", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-b:a", "64k", "-ar", str(AUDIO_RATE), "-ac", "1",
                "-t", str(duration), "-y", str(temporary),
            ]
            with tempfile.TemporaryFile() as errors:
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=errors)
                assert process.stdin is not None
                try:
                    for index in range(round(duration * FPS)):
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
    for name in MATCHES:
        directory = out_dir / name
        directory.mkdir(parents=True, exist_ok=True)
        labels = json.dumps(match_labels(name), indent=1) + "\n"
        label_path = directory / "labels.json"
        changed = not label_path.exists() or label_path.read_text() != labels
        if changed:
            label_path.write_text(labels)
        video = directory / "video.mp4"
        videos.append(video)
        if not video.exists() or changed or force:
            _encode_match(name, video)
    return videos


if __name__ == "__main__":
    build_all(force="--force" in sys.argv)
