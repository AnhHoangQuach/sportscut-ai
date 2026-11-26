import importlib.util
import json
from pathlib import Path
import subprocess

import numpy as np
import pytest

from sportscut import eval_crop, reframe
from sportscut.media import probe_duration, probe_size


BUILD_PATH = Path(__file__).parent / "fixtures/eval_crop/build.py"


def load_build():
    spec = importlib.util.spec_from_file_location("eval_crop_build", BUILD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_build()


@pytest.fixture(scope="module")
def eval_crop_set(require_ffmpeg, tmp_path_factory):
    directory = tmp_path_factory.mktemp("eval_crop")
    build.build_all(directory)
    return directory


def test_builder_is_standalone_and_committed_labels_match():
    assert "sportscut" not in BUILD_PATH.read_text()
    assert list(build.CASES) == [
        "slow_dribble", "long_pass", "occluded", "white_distractor"
    ]
    assert {
        item.name for item in BUILD_PATH.parent.iterdir()
        if item.is_dir() and (item / "labels.json").is_file()
    } == set(build.CASES)
    for name in build.CASES:
        path = BUILD_PATH.parent / name / "labels.json"
        assert path.read_text() == build.labels_text(name)


def test_label_geometry_timing_occlusion_and_speed_rules():
    nulls = {}
    for name in build.CASES:
        labels = build.case_labels(name)
        assert len(labels) == 60
        assert [entry["t"] for entry in labels] == build.label_times()
        assert all(abs(entry["t"] * 5 - round(entry["t"] * 5)) < 1e-9 for entry in labels)
        for entry in labels:
            ball = entry["ball"]
            if ball is not None:
                x, y = ball
                assert build.BALL_R <= x < build.W - build.BALL_R
                assert build.BALL_R <= y < build.H - build.BALL_R
                assert type(x) is type(y) is int
            for x, y, width, height in entry["players"]:
                assert 0 <= x and x + width <= build.W
                assert 0 <= y and y + height <= build.H
                assert all(type(value) is int for value in (x, y, width, height))
        nulls[name] = [entry["t"] for entry in labels if entry["ball"] is None]

    assert all(not times for name, times in nulls.items() if name != "occluded")
    hidden = nulls["occluded"]
    assert 4 <= len(hidden) <= 8
    assert min(hidden) >= 4.6 and max(hidden) <= 6.4
    assert hidden == build.label_times()[
        build.label_times().index(hidden[0]):build.label_times().index(hidden[-1]) + 1
    ]

    def speeds(name):
        balls = [entry["ball"] for entry in build.case_labels(name)]
        return [
            np.linalg.norm(np.subtract(second, first)) * build.LABEL_HZ
            for first, second in zip(balls, balls[1:])
        ]

    assert max(speeds("long_pass")) >= 300
    assert max(speeds("slow_dribble")) <= 60
    assert all(
        entry["ball"][0] > 421
        for entry in build.case_labels("white_distractor")
    )


def test_rendering_covers_hidden_ball_and_has_white_distractors():
    hidden_t = next(
        entry["t"] for entry in build.case_labels("occluded")
        if entry["ball"] is None
    )
    hidden = build.render_frame("occluded", hidden_t)
    visible = build.render_frame("occluded", 0)
    assert np.count_nonzero(np.all(hidden == 255, axis=2)) == 0
    assert np.count_nonzero(np.all(visible == 255, axis=2)) >= 20

    frame = build.render_frame("white_distractor", 0)
    bx, by = (round(value) for value in build.ball_pos("white_distractor", 0))
    white = np.all(frame == 255, axis=2)
    white[by-build.BALL_R:by+build.BALL_R+1, bx-build.BALL_R:bx+build.BALL_R+1] = False
    assert np.count_nonzero(white) >= 200


def test_built_clips_have_expected_media_properties(eval_crop_set):
    clips = build.build_all(eval_crop_set)
    assert {path.parent.name for path in clips} == set(build.CASES)
    for clip in clips:
        assert probe_size(clip) == (640, 360)
        assert probe_duration(clip) == pytest.approx(12.0, abs=0.05)
        output = subprocess.run([
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=codec_name,r_frame_rate", "-of", "json",
            str(clip),
        ], check=True, capture_output=True, text=True)
        stream = json.loads(output.stdout)["streams"][0]
        assert (stream["codec_name"], stream["r_frame_rate"]) == ("mpeg4", "25/1")


def test_build_is_idempotent_and_force_reencodes(eval_crop_set):
    clips = sorted(eval_crop_set.glob("*/clip.mp4"))
    before = {path: path.stat().st_mtime_ns for path in clips}
    build.build_all(eval_crop_set)
    assert {path: path.stat().st_mtime_ns for path in clips} == before
    build.build_all(eval_crop_set, force=True)
    assert all(path.stat().st_mtime_ns != before[path] for path in clips)


def test_center_crop_baseline_and_oracle(eval_crop_set, monkeypatch):
    monkeypatch.setattr(reframe, 'plan_crop', reframe.center_plan)
    baseline = eval_crop.evaluate_dir(eval_crop_set)
    assert list(baseline) == [
        "ball_in_crop", "players_in_crop", "jitter", "seconds_per_min", "per_clip"
    ]
    hits = total = 0
    for name in build.CASES:
        for entry in build.case_labels(name):
            if entry["ball"] is not None:
                total += 1
                hits += 219 <= entry["ball"][0] <= 421
    assert baseline["ball_in_crop"] == round(hits / total, 4)
    assert baseline["ball_in_crop"] < 0.95
    assert baseline["jitter"] == 0.0
    assert len(baseline["per_clip"]) == 4

    def oracle(video):
        labels = json.loads((Path(video).parent / "labels.json").read_text())
        return [
            (entry["t"], float(np.clip(entry["ball"][0], 101, 539)))
            for entry in labels if entry["ball"] is not None
        ]

    monkeypatch.setattr(reframe, "plan_crop", oracle)
    assert eval_crop.evaluate_dir(eval_crop_set)["ball_in_crop"] == 1.0


def test_eval_crop_documentation():
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text()
    assert "## Video dọc 9:16: đo khung cắt (eval-crop)" in readme
    assert "python tests/fixtures/eval_crop/build.py" in readme
    assert "python -m sportscut eval-crop tests/fixtures/eval_crop --json" in readme
    assert "data/eval_crop/<name>/{clip.mp4,labels.json}" in readme
    assert all(name in readme for name in (
        "ball_in_crop", "players_in_crop", "jitter", "seconds_per_min"
    ))
    assert '"ball_in_crop": 0.2821' in readme
    assert '"jitter": 0.0' in readme
    assert "Mục tiêu: ball_in_crop ≥ 0.95 với jitter thấp" in readme

    design = (
        root / "docs/superpowers/specs/"
        "2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md"
    ).read_text()
    assert (
        "T-017: same exception for the reframing eval set — "
        "tests/fixtures/eval_crop/build.py may write git-ignored clip.mp4 files "
        "inside tests/fixtures/eval_crop/; pytest builds only in temp dirs and "
        "no media is committed."
    ) in design
