import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
W, H, FPS = 640, 360, 25
DURATION = 12.0
LABEL_HZ = 5
BALL_R = 4
PLAYER_W, PLAYER_H = 14, 30
TEAM_RGB = {
    "red": (200, 30, 30),
    "blue": (30, 60, 200),
    "white": (255, 255, 255),
}

CASES = {
    "slow_dribble": {
        "ball": [(0, 120, 200), (12, 520, 200)],
        "line": False,
        "players": [
            ("red", [(0, 110, 178), (12, 510, 178)]),
            ("blue", [(0, 160, 180), (12, 560, 180)]),
            ("red", [(0, 200, 120)]),
            ("blue", [(0, 450, 280)]),
        ],
    },
    "long_pass": {
        "ball": [
            (0, 100, 180), (4, 100, 180), (5, 560, 180), (12, 580, 190)
        ],
        "line": False,
        "players": [
            ("red", [(0, 90, 155)]),
            ("red", [(0, 575, 160), (12, 590, 165)]),
            ("blue", [(0, 330, 120), (12, 330, 140)]),
            ("blue", [(0, 500, 240)]),
        ],
    },
    "occluded": {
        "ball": [
            (0, 150, 220), (5, 320, 220), (6, 320, 220), (12, 480, 220)
        ],
        "line": False,
        "players": [
            ("blue", [(0, 320, 220)]),
            ("red", [(0, 140, 190), (12, 470, 190)]),
            ("red", [(0, 420, 120)]),
        ],
    },
    "white_distractor": {
        "ball": [(0, 480, 250), (6, 560, 120), (12, 450, 300)],
        "line": True,
        "players": [
            ("white", [(0, 200, 150)]),
            ("red", [(0, 470, 228), (6, 550, 98), (12, 440, 278)]),
            ("blue", [(0, 300, 200)]),
        ],
    },
}


def _position(trajectory, t):
    times = [point[0] for point in trajectory]
    x = np.interp(t, times, [point[1] for point in trajectory])
    y = np.interp(t, times, [point[2] for point in trajectory])
    return float(x), float(y)


def label_times():
    return [round(index / LABEL_HZ, 1) for index in range(int(DURATION * LABEL_HZ))]


def ball_pos(name, t):
    return _position(CASES[name]["ball"], t)


def player_boxes(name, t):
    boxes = []
    for _team, trajectory in CASES[name]["players"]:
        center_x, center_y = _position(trajectory, t)
        boxes.append([
            round(center_x - PLAYER_W / 2),
            round(center_y - PLAYER_H / 2),
            PLAYER_W,
            PLAYER_H,
        ])
    return boxes


def ball_hidden(name, t):
    ball_x, ball_y = (round(value) for value in ball_pos(name, t))
    return any(
        x <= ball_x - BALL_R
        and ball_x + BALL_R <= x + width - 1
        and y <= ball_y - BALL_R
        and ball_y + BALL_R <= y + height - 1
        for x, y, width, height in player_boxes(name, t)
    )


def case_labels(name):
    labels = []
    for t in label_times():
        ball_x, ball_y = ball_pos(name, t)
        labels.append({
            "t": t,
            "ball": None if ball_hidden(name, t) else [round(ball_x), round(ball_y)],
            "players": player_boxes(name, t),
        })
    return labels


def labels_text(name):
    return "[\n" + ",\n".join(json.dumps(entry) for entry in case_labels(name)) + "\n]\n"


def render_frame(name, t):
    frame = np.empty((H, W, 3), dtype=np.uint8)
    frame[:] = (40, 140, 60)
    for x in range(0, W, 64):
        frame[:, x:x + 32] = (36, 128, 54)
    if CASES[name]["line"]:
        frame[:, 319:321] = 255

    ball_x, ball_y = (round(value) for value in ball_pos(name, t))
    yy, xx = np.ogrid[-BALL_R:BALL_R + 1, -BALL_R:BALL_R + 1]
    disk = xx * xx + yy * yy <= BALL_R * BALL_R
    region = frame[
        ball_y - BALL_R:ball_y + BALL_R + 1,
        ball_x - BALL_R:ball_x + BALL_R + 1,
    ]
    region[disk] = 255

    for (team, _trajectory), (x, y, width, height) in zip(
        CASES[name]["players"], player_boxes(name, t)
    ):
        frame[y:y + height, x:x + width] = TEAM_RGB[team]
    return frame


def build_all(out_dir=HERE, force=False):
    output = Path(out_dir)
    clips = []
    for name in CASES:
        directory = output / name
        directory.mkdir(parents=True, exist_ok=True)
        label_path = directory / "labels.json"
        content = labels_text(name)
        changed = not label_path.exists() or label_path.read_text() != content
        if changed:
            label_path.write_text(content)

        clip = directory / "clip.mp4"
        clips.append(clip)
        if clip.exists() and not changed and not force:
            continue

        temporary = directory / "clip.tmp.mp4"
        command = [
            "ffmpeg", "-nostdin", "-v", "error", "-f", "rawvideo",
            "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
            "-i", "pipe:0", "-c:v", "mpeg4", "-q:v", "2", "-pix_fmt",
            "yuv420p", "-an", "-y", str(temporary),
        ]
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stderr=subprocess.PIPE
        )
        assert process.stdin is not None
        try:
            for index in range(round(DURATION * FPS)):
                process.stdin.write(render_frame(name, index / FPS).tobytes())
            process.stdin.close()
            stderr = process.stderr.read() if process.stderr else b""
            code = process.wait()
        except BrokenPipeError:
            stderr = process.stderr.read() if process.stderr else b""
            code = process.wait()
        if code:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(stderr.decode().strip())
        os.replace(temporary, clip)
    return clips


if __name__ == "__main__":
    build_all(force="--force" in sys.argv)
