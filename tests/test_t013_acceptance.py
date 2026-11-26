"""Independent acceptance coverage for T-013 goal tagging."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sportscut import detect, media, pipeline
from sportscut.evaluate import evaluate_dir
from sportscut.events import scoreboard
from sportscut.models import Segment


ROOT = Path(__file__).resolve().parents[1]


def _scoreboard_frames() -> np.ndarray:
    frames = np.random.default_rng(0).integers(
        60, 140, (40, 30, 160), dtype=np.uint8
    )
    frames[:, 5:19, 10:40] = 0
    frames[:20, 8:16, 14:20] = 255
    frames[20:, 8:16, 26:32] = 255
    return frames


def _residual() -> np.ndarray:
    residual = np.zeros(200, dtype=np.float64)
    residual[20:30] = 20
    residual[55:58] = 20
    residual[100:130] = 12
    return residual


def _segments() -> tuple[Segment, Segment, Segment]:
    return (
        Segment(14, 26, 5, "audio peak z=5.0"),
        Segment(50, 62, 5, "b"),
        Segment(105, 117, 4, "c"),
    )


def _overlap(a: Segment, label: dict[str, object]) -> float:
    start = float(label["start"])
    end = float(label["end"])
    intersection = max(0.0, min(a.end, end) - max(a.start, start))
    union = max(a.end, end) - min(a.start, start)
    return intersection / union if union else 0.0


@pytest.fixture(scope="session")
def t013_eval_set(tmp_path_factory, require_ffmpeg) -> Path:
    build_path = ROOT / "tests" / "fixtures" / "eval" / "build.py"
    spec = importlib.util.spec_from_file_location("t013_acceptance_build", build_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path_factory.mktemp("t013_acceptance_eval")
    module.build_all(target)
    return target


def test_ac1_sample_top_band_real_shape_values_and_failures(
    synthetic_video, tmp_path, require_ffmpeg
):
    frames = media.sample_top_band(synthetic_video)
    assert frames.dtype == np.uint8
    assert frames.shape[1:] == (30, 160)
    assert len(frames) in (6, 7)
    assert float(frames[1].mean()) < 64
    assert float(frames[4].mean()) > 192

    bad = tmp_path / "not-media.mp4"
    bad.write_text("not media", encoding="utf-8")
    with pytest.raises(media.MediaError, match=r"^ffmpeg failed for"):
        media.sample_top_band(bad)


def test_ac1_sample_top_band_one_exact_ffmpeg_call_and_partial_drop(
    tmp_path, monkeypatch
):
    video = tmp_path / "input.mp4"
    video.touch()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout=b"\0" * (2 * 4800 + 79), stderr=b"")

    monkeypatch.setattr(media, "find_tool", lambda name: "/tools/ffmpeg")
    monkeypatch.setattr(media.subprocess, "run", fake_run)

    frames = media.sample_top_band(video)

    assert frames.shape == (2, 30, 160)
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == [
        "/tools/ffmpeg",
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(video),
        "-an",
        "-vf",
        "fps=1,scale=160:90,format=gray,crop=160:30:0:0",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    assert kwargs == {"capture_output": True, "check": False}

    missing = tmp_path / "missing.mp4"
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(
        media.MediaError, match=f"^media file not found: {missing}$"
    ):
        media.sample_top_band(missing)


def test_ac2_window_examples_and_empty_short_residuals():
    assert detect.place_window(50, 12, 100, 8) == (42.0, 54.0)
    assert detect.place_window(5, 12, 100, 8) == (0.0, 12.0)
    assert detect.place_window(95, 12, 100, 8) == (87.0, 99.0)
    assert detect.place_window(97, 12, 100, 8) == (88.0, 100.0)
    assert detect.place_window(5, 12, 6, 8) == (0.0, 6.0)
    assert detect.loudness_residual(np.zeros(0, np.float32)).shape == (0,)
    short = np.zeros(int(3.5 * media.SAMPLE_RATE), np.float32)
    assert detect.loudness_residual(short).shape == (3,)


def test_ac3_find_box_locates_board_and_rejects_non_boards():
    frames = _scoreboard_frames()
    box = scoreboard.find_box(frames)
    assert box is not None
    x, y, width, height = box
    assert 9 <= x <= 13
    assert 4 <= y <= 7
    assert 33 <= x + width <= 41
    assert 16 <= y + height <= 20

    noise = np.random.default_rng(1).integers(
        0, 256, (40, 30, 160), dtype=np.uint8
    )
    assert scoreboard.find_box(noise) is None
    assert scoreboard.find_box(np.zeros((40, 30, 160), np.uint8)) is None
    assert scoreboard.find_box(frames[:1]) is None


def test_ac4_changes_require_a_persistent_state_and_stable_tail():
    frames = _scoreboard_frames()
    box = scoreboard.find_box(frames)
    assert box is not None
    assert scoreboard.score_changes(frames, box) == [20.0]

    flash = frames[:20].copy()
    flash[10, 8:16, 14:20] = 0
    flash[10, 8:16, 26:32] = 255
    assert scoreboard.score_changes(flash, box) == []

    late = np.repeat(frames[:1], 40, axis=0)
    late[38:, 8:16, 14:20] = 0
    late[38:, 8:16, 26:32] = 255
    assert scoreboard.score_changes(late, box) == []

    transition = np.repeat(frames[:1], 40, axis=0)
    transition[20:, 8:12, 14:20] = 0
    transition[20:, 8:12, 26:32] = 255
    transition[21:, 12:16, 14:20] = 0
    transition[21:, 12:16, 26:32] = 255
    assert scoreboard.score_changes(transition, box) == [20.0]


def test_ac5_roar_peak_and_full_run_examples():
    residual = _residual()
    assert scoreboard.roar(residual, 14, 26) == (20.5, 10)
    assert scoreboard.roar(residual, 50, 62) == (55.5, 3)
    assert scoreboard.roar(residual, 105, 117) == (105.5, 30)
    assert scoreboard.roar(residual, 250, 260) == (250.0, 0)
    assert scoreboard.roar(np.full(20, 5.99), 2, 10) == (2.5, 0)


def test_ac6_match_goals_is_one_to_one_non_mutating_and_sorted():
    residual = _residual()
    a, b, c = _segments()
    original = [c, a, b]
    snapshot = deepcopy(original)

    output = scoreboard.match_goals(original, residual, [21.0, 150.0], 200)

    assert original == snapshot
    assert [(segment.start, segment.end) for segment in output] == [
        (14, 26),
        (50, 62),
        (105, 117),
    ]
    by_reason = {segment.reason.split(";")[0]: segment for segment in output}
    assert by_reason["audio peak z=5.0"] == Segment(
        14,
        26,
        5,
        "audio peak z=5.0; scoreboard change at 21s",
        "goal",
        0.9,
    )
    assert by_reason["b"].event == "other"
    assert by_reason["b"].event_confidence == 0.0
    assert by_reason["c"].event == "goal"
    assert by_reason["c"].event_confidence == 0.9

    competing = residual.copy()
    competing[60:70] = 20
    d = Segment(58, 70, 5, "d")
    nearest = scoreboard.match_goals([a, d], competing, [62.0], 200)
    assert [segment.event for segment in nearest] == ["other", "goal"]

    save = Segment(14, 26, 5, "r", "save")
    assert scoreboard.match_goals([save], residual, [21.0], 200)[0] == save


def test_ac6_only_the_first_argmax_roar_can_qualify():
    residual = np.zeros(40)
    residual[10] = 20
    residual[14:21] = 20
    segment = Segment(8, 22, 5, "audio peak z=5.0")

    assert scoreboard.roar(residual, segment.start, segment.end) == (10.5, 1)
    assert scoreboard.match_goals([segment], residual, [15.0], 40) == [segment]


@pytest.mark.parametrize(
    ("change", "min_len", "max_len", "expected"),
    [
        (200.0, 10, 30, (140.0, 170.0)),
        (200.0, 10, 20, (145.0, 165.0)),
        (40.0, 10, 30, (0.0, 30.0)),
        (130.0, 10, 30, (70.0, 100.0)),
    ],
)
def test_ac7_board_only_candidate_placement(change, min_len, max_len, expected):
    existing = Segment(100, 112, 4, "x")
    output = scoreboard.match_goals(
        [existing], np.zeros(300), [change], 300, min_len, max_len
    )
    goals = [segment for segment in output if segment.event == "goal"]
    assert len(goals) == 1
    assert (goals[0].start, goals[0].end) == expected
    assert goals[0].score == 3.0
    assert goals[0].event_confidence == 0.6


def test_ac7_board_only_overlap_is_rejected_but_touching_is_allowed():
    existing = Segment(100, 112, 4, "x")
    assert len(scoreboard.match_goals([existing], np.zeros(300), [130.0], 300)) == 2
    assert scoreboard.match_goals([existing], np.zeros(300), [135.0], 300) == [
        existing
    ]


def test_ac8_no_board_falls_back_to_roar_without_adding_segments():
    residual = _residual()
    a, b, c = _segments()
    output = scoreboard.match_goals([a, b, c], residual, None, 200)
    assert len(output) == 3
    assert output[0] == Segment(
        14,
        26,
        5,
        "audio peak z=5.0; sustained roar 10s",
        "goal",
        0.4,
    )
    assert output[1] == b
    assert output[2].event == "goal"
    assert output[2].event_confidence == 0.4
    assert output[2].reason == "c; sustained roar 30s"


def test_ac9_fixture_boards_change_once_per_goal(t013_eval_set):
    expected = {
        "cards": [],
        "controversy": [76.0],
        "goals_saves": [21.0, 101.0],
        "mixed": [71.0, 126.0],
    }
    for match, goal_times in expected.items():
        frames = media.sample_top_band(t013_eval_set / match / "video.mp4")
        box = scoreboard.find_box(frames)
        assert box is not None, match
        changes = scoreboard.score_changes(frames, box)
        assert len(changes) == len(goal_times), match
        assert changes == pytest.approx(goal_times, abs=1.0), match


def test_ac9_tag_goals_labels_only_fixture_goals(t013_eval_set):
    for case in sorted(t013_eval_set.iterdir()):
        video = case / "video.mp4"
        labels = json.loads((case / "labels.json").read_text(encoding="utf-8"))
        goal_labels = [label for label in labels if label["type"] == "goal"]
        tagged = scoreboard.tag_goals(video, detect.find_highlights(video))
        goals = [segment for segment in tagged if segment.event == "goal"]
        assert len(goals) == len(goal_labels), case.name
        assert all(segment.event_confidence == 0.9 for segment in goals), case.name
        for label in goal_labels:
            assert any(
                _overlap(segment, label) >= 0.3
                or segment.start <= float(label["start"]) <= segment.end
                for segment in goals
            ), (case.name, label, goals)


def test_ac10_no_board_and_short_bursts_leave_candidates_unchanged(burst_video):
    candidates = detect.find_highlights(burst_video, top=None)
    assert scoreboard.tag_goals(burst_video, candidates) == candidates


def test_ac11_pipeline_calls_classifier_between_detect_and_select(
    burst_video, tmp_path, monkeypatch
):
    calls: list[tuple[str, object]] = []
    candidate = Segment(10, 16, 5, "candidate")

    def fake_detect(video, **kwargs):
        calls.append(("detect", kwargs))
        return [candidate]

    def fake_tag(video, segments, **kwargs):
        calls.append(("tag", (list(segments), kwargs)))
        return list(segments)

    def fake_select(segments, **kwargs):
        calls.append(("select", (list(segments), kwargs)))
        return []

    monkeypatch.setattr(pipeline, "find_highlights", fake_detect)
    monkeypatch.setattr(pipeline, "tag_goals", fake_tag)
    monkeypatch.setattr(pipeline, "select_segments", fake_select)

    assert pipeline.run(burst_video, tmp_path / "out", top=2, min_len=4, max_len=6) == []
    assert [name for name, _ in calls] == ["detect", "tag", "select"]
    assert calls[0][1] == {"top": None, "min_len": 4, "max_len": 6}
    assert calls[1][1] == ([candidate], {"min_len": 4, "max_len": 6})


def test_ac11_pipeline_wraps_classifier_media_error(burst_video, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "find_highlights", lambda *args, **kwargs: [])

    def fail(*args, **kwargs):
        raise media.MediaError("classifier media failed")

    monkeypatch.setattr(pipeline, "tag_goals", fail)
    with pytest.raises(pipeline.PipelineError, match="^classifier media failed$"):
        pipeline.run(burst_video, tmp_path / "out")


def test_ac11_pipeline_goal_filter_exports_two_goals(t013_eval_set, tmp_path):
    out = tmp_path / "goal-export"
    result = pipeline.run(
        t013_eval_set / "goals_saves" / "video.mp4", out, events=["goal"]
    )
    assert len(result) == 2
    assert [entry["event"] for entry in result] == ["goal", "goal"]
    assert [entry["event_confidence"] for entry in result] == [0.9, 0.9]
    assert json.loads((out / "highlights.json").read_text(encoding="utf-8")) == result


def test_ac12_eval_and_cli_meet_goal_and_overall_gates(t013_eval_set):
    report = evaluate_dir(t013_eval_set)
    assert report["per_event"]["goal"]["recall"] >= 0.95
    assert report["per_event"]["goal"]["precision"] >= 0.8
    assert report["f1"] >= 0.8421
    assert report["recall"] >= 1.0

    completed = subprocess.run(
        [sys.executable, "-m", "sportscut", "eval", str(t013_eval_set), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    cli_report = json.loads(completed.stdout)
    assert cli_report == report


def test_ac13_readme_and_related_specs_record_t013_invariants():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    marker = "Kết quả sau T-013"
    assert marker in readme
    after = readme.split(marker, 1)[1]
    block = after.split("```json", 1)[1].split("```", 1)[0].strip()
    assert len(block.splitlines()) == 1
    report = json.loads(block)
    assert report["per_event"]["goal"]["recall"] >= 0.95
    assert report["f1"] >= 0.8421

    for relative in [
        "docs/superpowers/specs/2026-11-23-t-010-add-event-types-to-segments-and-design.md",
        "docs/superpowers/specs/2026-11-23-t-012-let-users-filter-by-event-and-design.md",
        "docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md",
        "docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md",
    ]:
        assert "(updated by T-013)" in (ROOT / relative).read_text(encoding="utf-8")


def test_ac14_budget_test_is_opt_in_with_exact_skip_reason():
    source = (ROOT / "tests" / "test_scoreboard.py").read_text(encoding="utf-8")
    assert "def test_ninety_minute_budget" in source
    assert "set SPORTSCUT_PERF=1 to run the 90-minute budget check" in source
    assert "budget:" in source and "for 5400s" in source
    assert "< 600" in source


def test_ac15_no_forbidden_paths_or_new_dependency_in_task_diff():
    base = subprocess.run(
        ["/usr/bin/git", "merge-base", "main", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    changed = set(
        subprocess.run(
            ["/usr/bin/git", "diff", "--name-only", base],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    )
    forbidden = {
        "tests/conftest.py",
        "sportscut/export.py",
        "sportscut/models.py",
        "sportscut/ranking.py",
        "tests/fixtures/eval/build.py",
    }
    assert changed.isdisjoint(forbidden)
    assert not any(path == "agent-office" or path.startswith("agent-office/") for path in changed)
