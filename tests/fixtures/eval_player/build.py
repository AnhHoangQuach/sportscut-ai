import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np


HERE = Path(__file__).resolve().parent
W, H, FPS = 640, 360, 25
SHIRT_W, SHIRT_H = 16, 32
BALL_R = 4
TEAM_RGB = {"red": (200, 30, 30), "blue": (30, 60, 200)}
FONT = {
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
}


def _players(touches, points, extras):
    players = {(team, number): [] for _, team, number in touches}
    for (t, team, number), (x, y) in zip(touches, points):
        players[(team, number)].append((t, x, y))
    players.update(extras)
    return players


SHORT_TOUCHES = [(2.0,"red",7),(4.0,"red",10),(5.0,"red",10),(7.0,"red",9),(8.2,"red",9),(10.0,"blue",4),(11.0,"blue",4),(13.0,"blue",5),(14.0,"blue",5),(16.4,"red",7),(17.4,"red",7),(19.0,"red",10)]
SHORT_POINTS = [(80,120),(150,190),(175,135),(245,110),(270,135),(340,195),(365,120),(430,110),(455,80),(520,195),(540,220),(590,120)]
DRIBBLE_TIMES = [round(2 + 1.2 * i, 1) for i in range(11)]
DRIBBLE_TOUCHES = [(t,"red",10) for t in DRIBBLE_TIMES] + [(15.2,"red",10),(17.0,"red",11)]
DRIBBLE_POINTS = [(100 + 42*i, 145 + (14 if i % 2 else -14)) for i in range(11)] + [(555,180),(590,120)]
NEAR_TOUCHES = [(3.0,"red",10),(6.0,"red",11),(8.0,"red",11),(11.0,"red",10),(14.0,"red",10),(16.0,"red",8)]
NEAR_POINTS = [(100,100),(400,100),(400,160),(100,160),(160,100),(300,200)]
HIDDEN_TOUCHES = [(2.0,"red",5),(4.0,"blue",8),(5.2,"blue",8),(7.0,"blue",3),(9.0,"blue",8),(11.0,"red",5),(14.0,"blue",8),(16.0,"blue",3)]
HIDDEN_POINTS = [(80,120),(150,180),(180,110),(250,100),(330,180),(410,110),(500,180),(570,110)]

CASES = {
    "short_passes": {"duration": 24.0, "touches": SHORT_TOUCHES, "players": _players(SHORT_TOUCHES, SHORT_POINTS, {("blue",10): [(0,580,250)]}), "ball_end": (21.0,610,200), "hidden": []},
    "dribble": {"duration": 20.0, "touches": DRIBBLE_TOUCHES, "players": _players(DRIBBLE_TOUCHES, DRIBBLE_POINTS, {("blue",6): [(0,100,260),(20,500,260)], ("blue",3): [(0,140,290),(20,540,290)]}), "ball_end": (19.0,610,190), "hidden": []},
    "near_miss": {"duration": 20.0, "touches": NEAR_TOUCHES, "players": _players(NEAR_TOUCHES, NEAR_POINTS, {("blue",4): [(0,240,99)], ("blue",2): [(0,240,159)]}), "ball_end": (18.0,380,120), "hidden": []},
    "number_hidden": {"duration": 20.0, "touches": HIDDEN_TOUCHES, "players": _players(HIDDEN_TOUCHES, HIDDEN_POINTS, {}), "ball_end": (18.0,610,180), "hidden": [("blue",8,t-1,t+1) for t,team,number in HIDDEN_TOUCHES if (team,number)==("blue",8)]},
}


def _centre(name, team, number, t):
    frames = CASES[name]["players"][(team, number)]
    times = [item[0] for item in frames]
    return float(np.interp(t, times, [item[1] for item in frames])), float(np.interp(t, times, [item[2] for item in frames]))


def player_box(name, team, number, t):
    cx, cy = _centre(name, team, number, t)
    box = (round(cx - SHIRT_W / 2), round(cy - SHIRT_H / 2), SHIRT_W, SHIRT_H)
    is_touch = any(abs(t-time) < 1e-9 and (team, number) == (touch_team, touch_number)
                   for time, touch_team, touch_number in CASES[name]["touches"])
    if not is_touch:
        ball_x, ball_y = ball_pos(name, t)
        x, y, w, h = box
        if x <= ball_x <= x + w and y <= ball_y <= y + h:
            box = (x, y - 50, w, h)
    return box


def feet(name, team, number, t):
    cx, cy = _centre(name, team, number, t)
    return cx, cy + SHIRT_H / 2 + BALL_R + 4


def ball_pos(name, t):
    case = CASES[name]
    touches = case["touches"]
    points = [feet(name, team, number, time) for time, team, number in touches]
    if t <= touches[0][0]:
        return points[0]
    for index in range(len(touches) - 1):
        start, end = touches[index][0], touches[index + 1][0]
        if t <= end:
            ratio = (t - start) / (end - start)
            return tuple(a + ratio * (b - a) for a, b in zip(points[index], points[index + 1]))
    end_t, end_x, end_y = case["ball_end"]
    ratio = min(1.0, (t - touches[-1][0]) / (end_t - touches[-1][0]))
    return tuple(a + ratio * (b - a) for a, b in zip(points[-1], (end_x, end_y)))


def case_labels(name):
    case = CASES[name]
    return {
        "players": [{"team": team, "number": number} for team, number in sorted(case["players"])],
        "touches": [{"t": round(t, 2), "team": team, "number": number} for t, team, number in case["touches"]],
    }


def _draw_number(frame, number, x, y):
    text = str(number)
    width = len(text) * 6 + (len(text) - 1) * 2
    left = x + round((SHIRT_W - width) / 2)
    for digit_index, digit in enumerate(text):
        for row, bits in enumerate(FONT[digit]):
            for column, bit in enumerate(bits):
                if bit == "1":
                    px = left + digit_index * 8 + column * 2
                    frame[y+6+row*2:y+8+row*2, px:px+2] = 255


def render_frame(name, t):
    frame = np.empty((H, W, 3), dtype=np.uint8)
    frame[:] = (40, 140, 60)
    for x in range(0, W, 64):
        frame[:, x:x+32] = (36, 128, 54)
    case = CASES[name]
    for team, number in case["players"]:
        x, y, w, h = player_box(name, team, number, t)
        frame[y:y+h, x:x+w] = TEAM_RGB[team]
        hidden = any((team, number) == item[:2] and item[2] <= t <= item[3] for item in case["hidden"])
        if not hidden:
            _draw_number(frame, number, x, y)
    bx, by = (round(value) for value in ball_pos(name, t))
    yy, xx = np.ogrid[-BALL_R:BALL_R+1, -BALL_R:BALL_R+1]
    disk = xx*xx + yy*yy <= BALL_R*BALL_R
    region = frame[by-BALL_R:by+BALL_R+1, bx-BALL_R:bx+BALL_R+1]
    region[disk] = 255
    return frame


def build_all(out_dir=HERE, force=False):
    out_dir = Path(out_dir)
    clips = []
    for name, case in CASES.items():
        directory = out_dir / name
        directory.mkdir(parents=True, exist_ok=True)
        label_path = directory / "labels.json"
        content = json.dumps(case_labels(name), indent=1) + "\n"
        changed = not label_path.exists() or label_path.read_text() != content
        if changed:
            label_path.write_text(content)
        clip = directory / "clip.mp4"
        clips.append(clip)
        if clip.exists() and not changed and not force:
            continue
        temporary = directory / "clip.tmp.mp4"
        command = ["ffmpeg","-nostdin","-v","error","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(FPS),"-i","pipe:0","-c:v","mpeg4","-q:v","2","-pix_fmt","yuv420p","-an","-y",str(temporary)]
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        assert process.stdin is not None
        try:
            for index in range(round(case["duration"] * FPS)):
                process.stdin.write(render_frame(name, index / FPS).tobytes())
            process.stdin.close()
            stderr = process.stderr.read() if process.stderr else b""
            code = process.wait()
        except BrokenPipeError:
            stderr = process.stderr.read() if process.stderr else b""
            code = process.wait()
        if code:
            raise RuntimeError(stderr.decode().strip())
        os.replace(temporary, clip)
    return clips


if __name__ == "__main__":
    build_all(force="--force" in sys.argv)
