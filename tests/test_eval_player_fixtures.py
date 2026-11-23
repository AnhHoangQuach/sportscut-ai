import importlib.util
import json
import math
from pathlib import Path
import subprocess

import numpy as np
import pytest

from sportscut.eval_player import evaluate_dir
from sportscut.cli import main
from sportscut.player import PlayerQuery, Touch


BUILD_PATH = Path(__file__).parent / "fixtures/eval_player/build.py"


def load_build():
    spec = importlib.util.spec_from_file_location("eval_player_build", BUILD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_build()


@pytest.fixture(scope="module")
def eval_player_set(require_ffmpeg, tmp_path_factory):
    directory = tmp_path_factory.mktemp("eval_player")
    build.build_all(directory)
    return directory


def box_distance(point, box) -> float:
    x, y = point
    bx, by, w, h = box
    return math.hypot(max(bx - x, 0, x - (bx + w)), max(by - y, 0, y - (by + h)))


def test_committed_labels_match_generator() -> None:
    for name in build.CASES:
        path = BUILD_PATH.parent / name / "labels.json"
        assert json.loads(path.read_text()) == build.case_labels(name)


def test_set_coverage_and_timing_rules() -> None:
    touches = queries = 0
    teams = set()
    for name, case in build.CASES.items():
        times = [item[0] for item in case["touches"]]
        labels = build.case_labels(name)
        touches += len(times)
        queries += len(labels["players"])
        teams.update(item[1] for item in case["touches"])
        assert 20 <= case["duration"] <= 40
        assert all(abs(t * 5 - round(t * 5)) < 1e-9 for t in times)
        assert times[0] >= 1 and times[-1] <= case["duration"] - 2
        assert all(b - a >= 1 for a, b in zip(times, times[1:]))
    assert touches >= 35 and queries >= 17 and teams == {"red", "blue"}
    assert {p[0] for p in build.CASES["short_passes"]["players"] if p[1] == 10} == {"red", "blue"}


def test_ball_touch_proximity_and_velocity_change() -> None:
    for name, case in build.CASES.items():
        for t, team, number in case["touches"]:
            assert box_distance(build.ball_pos(name, t), build.player_box(name, team, number, t)) <= 8
            before = np.array(build.ball_pos(name, t)) - np.array(build.ball_pos(name, t - 0.2))
            after = np.array(build.ball_pos(name, t + 0.2)) - np.array(build.ball_pos(name, t))
            if np.linalg.norm(before) < 1e-6 or np.linalg.norm(after) < 1e-6:
                assert max(np.linalg.norm(before), np.linalg.norm(after)) >= 1e-6
                continue
            cosine = np.dot(before, after) / np.linalg.norm(before) / np.linalg.norm(after)
            angle = math.degrees(math.acos(np.clip(cosine, -1, 1)))
            ratio = max(np.linalg.norm(before), np.linalg.norm(after)) / min(np.linalg.norm(before), np.linalg.norm(after))
            assert angle >= 25 or ratio >= 1.5


def test_ball_never_inside_a_box() -> None:
    for name, case in build.CASES.items():
        for t in np.arange(0, case["duration"], 0.04):
            point = build.ball_pos(name, t)
            assert all(box_distance(point, build.player_box(name, *who, t)) > 0 for who in case["players"])


def test_near_miss_case() -> None:
    case = build.CASES["near_miss"]
    zero_touch = [("blue", 4), ("blue", 2)]
    found = []
    for t in np.arange(0, case["duration"], 0.04):
        if min(abs(t - item[0]) for item in case["touches"]) < 1:
            continue
        for who in zero_touch:
            distance = box_distance(build.ball_pos("near_miss", t), build.player_box("near_miss", *who, t))
            if 6 <= distance <= 14:
                before = np.array(build.ball_pos("near_miss", t)) - np.array(build.ball_pos("near_miss", t - 0.04))
                after = np.array(build.ball_pos("near_miss", t + 0.04)) - np.array(build.ball_pos("near_miss", t))
                cosine = np.dot(before, after) / np.linalg.norm(before) / np.linalg.norm(after)
                angle = math.degrees(math.acos(np.clip(cosine, -1, 1)))
                ratio = max(np.linalg.norm(before), np.linalg.norm(after)) / min(np.linalg.norm(before), np.linalg.norm(after))
                assert angle < 5 and ratio <= 1.1
                found.append((t, who))
    assert len({who for _, who in found}) >= 2


def test_number_hidden_case() -> None:
    times = [t for t, team, number in build.CASES["number_hidden"]["touches"] if (team, number) == ("blue", 8)]
    for t in times:
        frame = build.render_frame("number_hidden", t)
        x, y, w, h = build.player_box("number_hidden", "blue", 8, t)
        crop = frame[y:y+h, x:x+w]
        assert np.count_nonzero(np.all(crop >= 200, axis=2)) <= 80  # ball only
    frame = build.render_frame("number_hidden", 7.5)
    x, y, w, h = build.player_box("number_hidden", "blue", 8, 7.5)
    assert np.count_nonzero(np.all(frame[y:y+h, x:x+w] >= 200, axis=2)) >= 10


def test_clip_format_ffprobe(eval_player_set: Path) -> None:
    for name, case in build.CASES.items():
        output = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,width,height,r_frame_rate:format=duration",
            "-of", "json", str(eval_player_set / name / "clip.mp4")
        ], capture_output=True, text=True, check=True)
        data = json.loads(output.stdout)
        stream = data["streams"][0]
        assert (stream["codec_name"], stream["width"], stream["height"], stream["r_frame_rate"]) == ("mpeg4", 640, 360, "25/1")
        assert float(data["format"]["duration"]) == pytest.approx(case["duration"], abs=0.1)


def test_build_is_idempotent(eval_player_set: Path) -> None:
    clips = list(eval_player_set.glob("*/clip.mp4"))
    before = {path: path.stat().st_mtime_ns for path in clips}
    labels = {path: path.read_bytes() for path in eval_player_set.glob("*/labels.json")}
    build.build_all(eval_player_set)
    assert {path: path.stat().st_mtime_ns for path in clips} == before
    assert {path: path.read_bytes() for path in labels} == labels


def test_decoded_frames_show_ball_and_team_colour(eval_player_set: Path) -> None:
    for name, case in build.CASES.items():
        for t, team, number in case["touches"]:
            raw = subprocess.run([
                "ffmpeg", "-v", "error", "-ss", str(t), "-i", str(eval_player_set/name/"clip.mp4"),
                "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"
            ], capture_output=True, check=True).stdout
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(build.H, build.W, 3)
            bx, by = (round(value) for value in build.ball_pos(name, t))
            assert np.all(frame[by, bx] >= 200)
            x, y, w, h = build.player_box(name, team, number, t)
            assert np.all(np.abs(frame[y+h-4, x+w//2].astype(int) - build.TEAM_RGB[team]) <= 40)


@pytest.mark.parametrize(("offset", "expected"), [(0.0, 1.0), (0.5, 1.0), (0.6, 0.0)])
def test_eval_oracle_and_shift(eval_player_set: Path, monkeypatch: pytest.MonkeyPatch, offset: float, expected: float) -> None:
    def touches(video):
        data = json.loads((Path(video).parent / "labels.json").read_text())
        return [Touch(item["t"] + offset, item["team"], item["number"], 1, None) for item in data["touches"]]
    def found(video, query):
        return [item for item in touches(video) if (item.team, item.number) == (query.team, query.number)]
    monkeypatch.setattr("sportscut.player.detect_touches", touches)
    monkeypatch.setattr("sportscut.player.find_touches", found)
    report = evaluate_dir(eval_player_set)
    assert report["f1"] == report["touch_f1_any"] == expected
    if offset <= 0.5:
        assert report["team_accuracy"] == report["id_accuracy"] == 1.0


def test_eval_player_cli_baseline_json(eval_player_set: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval-player", str(eval_player_set), "--json"]) == 0
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1 and captured.err == ""
    report = json.loads(captured.out)
    assert set(report) == {"f1", "precision", "recall", "touch_f1_any", "team_accuracy", "id_accuracy", "seconds_per_min", "per_clip"}
    assert [item["clip"] for item in report["per_clip"]] == sorted(build.CASES)
    assert report["f1"] == report["touch_f1_any"] == 0.0
    assert report["team_accuracy"] is report["id_accuracy"] is None


def test_eval_player_indent_output(eval_player_set: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval-player", str(eval_player_set)]) == 0
    output = capsys.readouterr().out
    assert len(output.splitlines()) > 1
    assert json.loads(output)["f1"] == 0.0
