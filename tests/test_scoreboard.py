import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time

import numpy as np
import pytest

from sportscut import detect
from sportscut.evaluate import Label, evaluate_dir, match_segments
from sportscut.events.scoreboard import (
    find_box,
    match_goals,
    roar,
    score_changes,
    tag_goals,
)
from sportscut.media import SAMPLE_RATE, sample_top_band
from sportscut.models import Segment


@pytest.fixture(scope="module")
def built_eval_set(tmp_path_factory, require_ffmpeg):
    build_path = Path(__file__).parent / "fixtures" / "eval" / "build.py"
    spec = importlib.util.spec_from_file_location("t013_eval_build", build_path)
    assert spec is not None and spec.loader is not None
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    root = tmp_path_factory.mktemp("t013_eval")
    build.build_all(root)
    return root


def test_place_window_examples():
    assert detect.place_window(50, 12, 100, 8) == (42.0, 54.0)
    assert detect.place_window(5, 12, 100, 8) == (0.0, 12.0)
    assert detect.place_window(95, 12, 100, 8) == (88.0, 100.0)
    assert detect.place_window(5, 12, 6, 8) == (0.0, 6.0)


def test_loudness_residual_lengths():
    assert len(detect.loudness_residual(np.zeros(0, np.float32))) == 0
    samples = np.zeros(int(3.5 * SAMPLE_RATE), np.float32)
    assert len(detect.loudness_residual(samples)) == 3


def _scoreboard_frames(change=20):
    frames = np.random.default_rng(0).integers(60, 140, (40, 30, 160)).astype(
        np.uint8
    )
    frames[:, 5:19, 10:40] = 0
    frames[:change, 8:16, 14:20] = 255
    frames[change:, 8:16, 26:32] = 255
    return frames


def test_find_box_locates_static_box():
    box = find_box(_scoreboard_frames())

    assert box is not None
    x, y, w, h = box
    assert 9 <= x <= 13
    assert 4 <= y <= 7
    assert 33 <= x + w <= 41
    assert 16 <= y + h <= 20


def test_find_box_none_for_noise_black_and_single_frame():
    noise = np.random.default_rng(1).integers(0, 256, (20, 30, 160)).astype(
        np.uint8
    )
    black = np.zeros((20, 30, 160), np.uint8)

    assert find_box(noise) is None
    assert find_box(black) is None
    assert find_box(black[:1]) is None


def test_score_changes_single_change():
    frames = _scoreboard_frames()
    box = find_box(frames)

    assert box is not None
    assert score_changes(frames, box) == [20.0]


def test_score_changes_ignores_flash():
    frames = _scoreboard_frames(change=40)
    frames[10, 8:16, 14:20] = 0
    frames[10, 8:16, 26:32] = 255
    box = find_box(frames)

    assert box is not None
    assert score_changes(frames, box) == []


def test_score_changes_needs_stable_tail():
    frames = _scoreboard_frames(change=38)
    box = find_box(frames)

    assert box is not None
    assert score_changes(frames, box) == []


def test_score_changes_two_sample_transition():
    frames = _scoreboard_frames()
    frames[20, 8:16, 26:32] = 0
    box = find_box(frames)

    assert box is not None
    assert score_changes(frames, box) == [20.0]


def _roar_residual():
    residual = np.zeros(200)
    residual[20:30] = 20
    residual[55:58] = 20
    residual[100:130] = 12
    return residual


def _segments():
    return [
        Segment(14, 26, 5, "audio peak z=5.0"),
        Segment(50, 62, 5, "b"),
        Segment(105, 117, 4, "c"),
    ]


def test_roar_runs():
    residual = _roar_residual()

    assert roar(residual, 14, 26) == (20.5, 10)
    assert roar(residual, 50, 62) == (55.5, 3)
    assert roar(residual, 105, 117) == (105.5, 30)
    assert roar(residual, 250, 260) == (250.0, 0)
    assert roar(np.full(20, 5.9), 2, 10)[1] == 0


def test_match_goals_with_board():
    a, b, c = _segments()
    result = match_goals([a, b, c], _roar_residual(), [21.0], 200)

    assert result[0] == Segment(
        14,
        26,
        5,
        "audio peak z=5.0; scoreboard change at 21s",
        "goal",
        0.9,
    )
    assert result[1:] == [b, c]

    result = match_goals([a, b, c], _roar_residual(), [21.0, 150.0], 200)
    assert [segment.event for segment in result] == ["goal", "other", "goal"]


def test_match_goals_nearest_peak_wins():
    residual = _roar_residual()
    residual[60:70] = 20
    a = _segments()[0]
    d = Segment(54, 66, 5, "d")

    result = match_goals([a, d], residual, [62.0], 200)

    assert result[0] == a
    assert result[1].event == "goal"
    assert result[1].event_confidence == 0.9


def test_match_goals_keeps_non_other_events():
    segment = Segment(14, 26, 5, "r", "save")

    assert match_goals([segment], _roar_residual(), [21.0], 200) == [segment]


def test_match_goals_board_only_placement_and_overlap():
    original = Segment(100, 112, 4, "x")
    residual = np.zeros(300)

    assert match_goals([original], residual, [200], 300) == [
        original,
        Segment(140, 170, 3, "scoreboard change at 200s", "goal", 0.6),
    ]
    assert match_goals(
        [original], residual, [200], 300, min_len=10, max_len=20
    )[-1] == Segment(145, 165, 3, "scoreboard change at 200s", "goal", 0.6)
    assert match_goals([original], residual, [40], 300)[0] == Segment(
        0, 30, 3, "scoreboard change at 40s", "goal", 0.6
    )
    assert match_goals([original], residual, [130], 300)[0].end == 100
    assert match_goals([original], residual, [135], 300) == [original]

    result = match_goals([original], residual, [40, 130, 200], 300)
    assert all(
        left.end <= right.start
        for left, right in zip(result, result[1:])
    )


def test_match_goals_fallback_roar_only():
    a, b, c = _segments()

    result = match_goals([a, b, c], _roar_residual(), None, 200)

    assert result[0] == Segment(
        14,
        26,
        5,
        "audio peak z=5.0; sustained roar 10s",
        "goal",
        0.4,
    )
    assert result[1] == b
    assert result[2].event == "goal"
    assert result[2].event_confidence == 0.4
    assert len(result) == 3


def test_match_goals_does_not_mutate_and_sorts():
    segments = list(reversed(_segments()))
    original = list(segments)

    result = match_goals(segments, _roar_residual(), [21.0], 200)

    assert segments == original
    assert result == sorted(result, key=lambda segment: (segment.start, segment.end))


def test_fixture_scoreboard_changes_at_goals(built_eval_set):
    expected = {
        "cards": [],
        "controversy": [76.0],
        "goals_saves": [21.0, 101.0],
        "mixed": [71.0, 126.0],
    }

    for name, goal_times in expected.items():
        frames = sample_top_band(built_eval_set / name / "video.mp4")
        box = find_box(frames)
        assert box is not None, name
        changes = score_changes(frames, box)
        assert changes == pytest.approx(goal_times, abs=1.0), name


def test_tag_goals_labels_each_fixture_goal(built_eval_set):
    for case in sorted(path for path in built_eval_set.iterdir() if path.is_dir()):
        video = case / "video.mp4"
        labels = json.loads((case / "labels.json").read_text())
        goal_labels = [
            Label(label["start"], label["end"], "goal")
            for label in labels
            if label["type"] == "goal"
        ]

        tagged = tag_goals(video, detect.find_highlights(video))
        goals = [segment for segment in tagged if segment.event == "goal"]

        assert len(goals) == len(goal_labels), case.name
        assert len(match_segments(goals, goal_labels)) == len(goal_labels), case.name
        assert all(segment.event_confidence == 0.9 for segment in goals)


def test_tag_goals_leaves_burst_video_unchanged(burst_video):
    candidates = detect.find_highlights(burst_video, top=None)

    assert tag_goals(burst_video, candidates) == candidates


def test_eval_goal_recall_and_f1_gate(built_eval_set):
    report = evaluate_dir(built_eval_set)

    assert report["per_event"]["goal"]["recall"] >= 0.95
    assert report["per_event"]["goal"]["precision"] >= 0.8
    assert report["f1"] >= 0.8421
    assert report["recall"] >= 1.0


def test_readme_t013_result_invariants():
    readme = (Path(__file__).parents[1] / "README.md").read_text()
    marker = "Kết quả sau T-013"
    assert marker in readme
    block = re.search(r"```json\n([^\n]+)\n```", readme.split(marker, 1)[1])
    assert block is not None
    report = json.loads(block.group(1))
    assert report["per_event"]["goal"]["recall"] >= 0.95
    assert report["f1"] >= 0.8421


@pytest.mark.skipif(
    os.environ.get("SPORTSCUT_PERF") != "1",
    reason="set SPORTSCUT_PERF=1 to run the 90-minute budget check",
)
def test_ninety_minute_budget(tmp_path, require_ffmpeg):
    video = tmp_path / "ninety_minutes.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=25:duration=5400",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=amplitude=0.02:sample_rate=16000:duration=5400",
            "-c:v",
            "mpeg4",
            "-q:v",
            "5",
            "-c:a",
            "aac",
            "-shortest",
            str(video),
        ],
        check=True,
    )

    started = time.perf_counter()
    candidates = detect.find_highlights(video, top=None)
    tag_goals(video, candidates)
    elapsed = time.perf_counter() - started

    print(f"budget: {elapsed:.2f}s for 5400s")
    assert elapsed < 600
