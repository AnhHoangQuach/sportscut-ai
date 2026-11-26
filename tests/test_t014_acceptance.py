"""Independent acceptance tests for T-014 save tagging."""

import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
import pytest

from sportscut import detect, evaluate, pipeline
from sportscut.events import audio_cues, incidents, scoreboard
from sportscut.media import MediaError, extract_audio, sample_top_band
from sportscut.models import Segment


ROOT = Path(__file__).parents[1]
BUILD_PATH = ROOT / "tests/fixtures/eval/build.py"


def _load_builder():
    spec = importlib.util.spec_from_file_location("t014_acceptance_build", BUILD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def t014_eval_set(tmp_path_factory, require_ffmpeg):
    root = tmp_path_factory.mktemp("t014_acceptance_eval")
    builder = _load_builder()
    videos = builder.build_all(root)
    return root, builder, videos


def _levels():
    levels = np.full(1200, -40.0)
    levels[440] = -36
    levels[499] = -36
    levels[500:524] = -20
    levels[524] = -35
    levels[600:640] = -20
    levels[800:815] = -36
    levels[815:825] = -31
    levels[825:835] = -28
    levels[835:840] = -33
    levels[1000:1010] = -35
    return levels


def _tone(frequency, seconds=1.0, amplitude=0.3):
    time = np.arange(round(16_000 * seconds)) / 16_000
    return amplitude * np.sin(2 * np.pi * frequency * time)


def _git_base():
    return subprocess.run(
        ["/usr/bin/git", "merge-base", "main", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _readme_json(text, marker):
    after = text.split(marker, 1)[1]
    match = re.search(r"```json\n([^\n]+)\n```", after)
    assert match is not None
    return json.loads(match.group(1)), after


def test_ac1_window_and_band_features_cover_empty_silent_short_and_realistic_audio():
    constant = audio_cues.window_levels(np.full(16_000, 0.1, np.float32))
    assert constant.dtype == np.float64
    assert constant == pytest.approx(np.full(10, -20.0), abs=1e-4)
    assert audio_cues.window_levels(np.zeros(1650, np.float32)) == pytest.approx(
        [-200.0], abs=1e-9
    )
    for samples in (np.array([], dtype=np.float32), np.zeros(1599, np.float32)):
        levels = audio_cues.window_levels(samples)
        assert levels.dtype == np.float64
        assert levels.size == 0

    in_band = audio_cues.band_share(_tone(3000), 2000, 4000)
    off_band = audio_cues.band_share(_tone(500), 2000, 4000)
    silence = audio_cues.band_share(np.zeros(16_000), 2000, 4000)
    noise = audio_cues.band_share(
        np.random.default_rng(0).normal(0, 0.1, 160_000), 2000, 4000
    )
    assert len(in_band) == len(off_band) == len(silence) == 10
    assert np.all(in_band >= 0.99)
    assert np.all(off_band <= 0.01)
    assert np.array_equal(silence, np.zeros(10))
    assert np.all((noise >= 0.15) & (noise <= 0.35))
    assert np.all(audio_cues.band_share(_tone(1000, amplitude=0.02), 300, 2000) >= 0.99)
    assert audio_cues.band_share(np.zeros(1599), 2000, 4000).size == 0


def test_ac2_whistles_require_three_consecutive_narrow_band_windows():
    samples = _tone(500, seconds=10, amplitude=0.02)
    whistle = _tone(3000, seconds=1)
    for start, duration in ((2.0, 1.0), (5.0, 0.2), (7.0, 0.3)):
        first = round(start * 16_000)
        length = round(duration * 16_000)
        samples[first : first + length] += whistle[:length]
    assert audio_cues.find_whistles(samples) == [(2.0, 3.0), (7.0, 7.3)]
    assert audio_cues.find_whistles(
        np.random.default_rng(1).normal(0, 0.1, 160_000)
    ) == []
    assert audio_cues.find_whistles(np.zeros(160_000)) == []
    assert audio_cues.find_whistles(np.zeros(1599)) == []


def test_ac3_stoppage_uses_play_band_and_counts_to_signal_end():
    samples = _tone(1000, seconds=120, amplitude=0.02)
    samples[50 * 16_000 : 62 * 16_000] *= 0.25
    samples[53 * 16_000 : 60 * 16_000] += _tone(100, 7, 0.08)
    assert audio_cues.stoppage_after(samples, 50.0) == pytest.approx(12.0)
    assert audio_cues.stoppage_after(samples, 56.0) == pytest.approx(6.0)
    assert audio_cues.stoppage_after(samples, 40.0) == 0.0
    assert audio_cues.stoppage_after(samples, 200.0) == 0.0

    tail = _tone(1000, seconds=120, amplitude=0.02)
    tail[110 * 16_000 :] *= 0.25
    assert audio_cues.stoppage_after(tail, 110.0) == pytest.approx(10.0)


def test_ac4_roar_shape_reports_save_swell_long_quiet_and_outside_cases():
    levels = _levels()
    assert audio_cues.roar_shape(levels, 46, 58) == pytest.approx(
        audio_cues.RoarShape(50.0, 50.0, 52.4, 2.4, 0.1, 0.0)
    )
    assert audio_cues.roar_shape(levels, 78, 90) == pytest.approx(
        audio_cues.RoarShape(82.5, 81.5, 84.0, 2.5, 2.5, 0.5)
    )
    long = audio_cues.roar_shape(levels, 56, 68)
    assert (long.duration, long.rise) == pytest.approx((4.0, 0.0))
    assert audio_cues.roar_shape(levels, 96, 108) == audio_cues.RoarShape(
        100.0, 100.0, 100.0, 0.0, 0.0, 0.0
    )
    assert audio_cues.roar_shape(levels, 130, 140) == audio_cues.RoarShape(
        130.0, 130.0, 130.0, 0.0, 0.0, 0.0
    )
    slow = levels.copy()
    slow[455] = -36
    assert audio_cues.roar_shape(slow, 46, 58).rise == pytest.approx(4.5)


def test_ac5_save_gate_is_strict_non_mutating_and_preserves_other_events():
    levels = _levels()
    save = Segment(46, 58, 5, "audio peak z=5.0")
    swell = Segment(78, 90, 4, "w")
    four_seconds = Segment(56, 68, 3, "l")
    quiet = Segment(96, 108, 2, "b")
    goal = Segment(46, 58, 5, "g", "goal", 0.9)
    original = [save, swell, four_seconds, quiet, goal]
    snapshot = list(original)

    result = audio_cues.match_saves(original, levels, [], [])

    assert original == snapshot
    assert [(item.start, item.end, item.score) for item in result] == [
        (item.start, item.end, item.score) for item in original
    ]
    assert result[0] == Segment(
        46, 58, 5, "audio peak z=5.0; sharp roar 2.4s", "save", 0.6
    )
    assert [item.event for item in result[1:]] == ["other", "other", "other", "goal"]
    assert all(result[index] is original[index] for index in range(1, 5))
    assert audio_cues.match_saves([save], levels, [], None) == [save]
    slow = levels.copy()
    slow[455] = -36
    assert audio_cues.match_saves([save], slow, [], [])[0].event == "other"


def test_ac6_whistle_and_scoreboard_exclusion_boundaries_are_exact():
    segment = Segment(46, 58, 5, "s")
    cases = [
        ([(55.0, 56.0)], [], "other"),
        ([(50.5, 51.5)], [], "other"),
        ([(57.5, 58.5)], [], "save"),
        ([(48.0, 49.9)], [], "save"),
        ([], [80.0], "other"),
        ([], [40.0], "other"),
        ([], [80.5], "save"),
        ([], [39.5], "save"),
    ]
    for whistles, changes, expected in cases:
        result = audio_cues.match_saves([segment], _levels(), whistles, changes)
        assert result[0].event == expected, (whistles, changes)


def test_ac7_board_and_audio_boundaries_short_circuit_and_decode_once(monkeypatch):
    frames = np.zeros((4, 3, 2), dtype=np.uint8)
    calls = []
    monkeypatch.setattr(scoreboard, "sample_top_band", lambda video: frames)
    monkeypatch.setattr(scoreboard, "find_box", lambda value: calls.append(value) or (0, 0, 1, 1))
    monkeypatch.setattr(scoreboard, "score_changes", lambda value, box: [2.0])
    assert scoreboard.board_changes("match.mp4") == [2.0]
    assert calls == [frames]

    segment = Segment(0, 1, 1, "quiet")
    monkeypatch.setattr(scoreboard, "board_changes", lambda video: None)
    monkeypatch.setattr(
        audio_cues, "extract_audio", lambda video: pytest.fail("audio decoded without board")
    )
    assert audio_cues.tag_saves("no-board.mp4", [segment]) == [segment]

    decoded = []
    samples = np.zeros(16_000, np.float32)
    monkeypatch.setattr(scoreboard, "board_changes", lambda video: [])
    monkeypatch.setattr(audio_cues, "extract_audio", lambda video: decoded.append(video) or samples)
    expected = audio_cues.match_saves(
        [segment], audio_cues.window_levels(samples), audio_cues.find_whistles(samples), []
    )
    assert audio_cues.tag_saves("board.mp4", [segment]) == expected
    assert decoded == ["board.mp4"]
    tree = ast.parse((ROOT / "sportscut/events/audio_cues.py").read_text())
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and (getattr(node, "module", "") == "subprocess" or any(alias.name == "subprocess" for alias in node.names))
        for node in ast.walk(tree)
    )


def test_ac7_real_no_board_video_keeps_candidates_unchanged(burst_video):
    candidates = detect.find_highlights(burst_video, top=None)
    assert scoreboard.board_changes(burst_video) is None
    assert audio_cues.tag_saves(burst_video, candidates) == candidates


def test_ac8_pipeline_orders_classifiers_and_wraps_save_media_errors(tmp_path, monkeypatch):
    found = [Segment(1, 5, 1, "found")]
    goals = [Segment(1, 5, 1, "goal", "goal", 0.9)]
    saves = [Segment(6, 10, 2, "save", "save", 0.6)]
    calls = []
    monkeypatch.setattr(pipeline, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(pipeline, "has_audio", lambda video: True)
    monkeypatch.setattr(
        pipeline,
        "find_highlights",
        lambda video, **kwargs: calls.append(("find", video, kwargs)) or found,
    )
    monkeypatch.setattr(
        pipeline,
        "tag_goals",
        lambda video, segments, **kwargs: calls.append(("goals", video, segments, kwargs)) or goals,
    )
    monkeypatch.setattr(
        pipeline,
        "tag_saves",
        lambda video, segments: calls.append(("saves", video, segments)) or saves,
    )
    monkeypatch.setattr(pipeline, "tag_incidents", lambda _video, segments: segments)
    monkeypatch.setattr(
        pipeline,
        "select_segments",
        lambda segments, **kwargs: calls.append(("select", segments, kwargs)) or segments,
    )

    def export(_video, _segments, out):
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / pipeline.MANIFEST_NAME).write_text("[]")

    monkeypatch.setattr(pipeline, "export_clips", export)
    assert pipeline.run("match.mp4", tmp_path / "out", top=2, min_len=4, max_len=6) == []
    assert [call[0] for call in calls] == ["find", "goals", "saves", "select"]
    assert calls[2] == ("saves", "match.mp4", goals)
    assert calls[3][1] is saves

    monkeypatch.setattr(
        pipeline,
        "tag_saves",
        lambda video, segments: (_ for _ in ()).throw(MediaError("save audio failed")),
    )
    with pytest.raises(pipeline.PipelineError, match="^save audio failed$"):
        pipeline.run("match.mp4", tmp_path / "error")


def test_ac9_evaluate_scores_tag_saves_output_after_tag_goals(tmp_path, monkeypatch):
    case = tmp_path / "case"
    case.mkdir()
    video = case / "video.mp4"
    video.write_bytes(b"")
    (case / "labels.json").write_text('[{"start": 1, "end": 2, "type": "save"}]')
    detected = [Segment(0, 3, 2, "detected")]
    goals = [Segment(0, 3, 2, "after goals")]
    saved = [Segment(0, 3, 2, "after saves", "save", 0.6)]
    calls = []
    monkeypatch.setattr(detect, "find_highlights", lambda value: detected)
    monkeypatch.setattr(scoreboard, "tag_goals", lambda value, segments: goals)
    monkeypatch.setattr(incidents, "tag_incidents", lambda _video, segments: segments)

    def tag_saves(value, segments):
        calls.append((value, segments))
        return saved

    monkeypatch.setattr(audio_cues, "tag_saves", tag_saves)
    report = evaluate.evaluate_dir(tmp_path)
    assert calls == [(video, goals)]
    assert calls[0][1] is goals
    assert report["per_event"]["save"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert report["event_accuracy"] == 1.0


def test_ac10_fixture_boards_whistles_and_stoppages_match_labels(t014_eval_set):
    _root, builder, videos = t014_eval_set
    expected_counts = {"cards": 3, "controversy": 2, "goals_saves": 0, "mixed": 1}
    for video in videos:
        name = video.parent.name
        frames = sample_top_band(video)
        box = scoreboard.find_box(frames)
        assert box is not None
        assert scoreboard.board_changes(video) == scoreboard.score_changes(frames, box)

        samples = extract_audio(video)
        whistles = audio_cues.find_whistles(samples)
        expected = [
            (kind, float(t0))
            for kind, t0, *_ in builder.MATCHES[name]["events"]
            if kind in ("red_card", "controversy")
        ]
        assert len(whistles) == expected_counts[name] == len(expected)
        for (start, end), (kind, t0) in zip(whistles, expected):
            assert abs(start - t0) <= 0.2
            assert 0.8 <= end - start <= 1.3
            stopped = audio_cues.stoppage_after(samples, end)
            low, high = (9.0, 13.0) if kind == "red_card" else (25.0, 37.0)
            assert low <= stopped <= high


def test_ac11_fixture_saves_preserve_geometry_goals_and_non_save_labels(t014_eval_set):
    _root, _builder, videos = t014_eval_set
    for video in videos:
        goals = scoreboard.tag_goals(video, detect.find_highlights(video))
        tagged = audio_cues.tag_saves(video, goals)
        assert [(s.start, s.end, s.score) for s in tagged] == [
            (s.start, s.end, s.score) for s in goals
        ]
        for before, after in zip(goals, tagged):
            if before.event == "goal":
                assert after == before

        labels = evaluate.load_labels(video.parent / "labels.json")
        by_label = {j: tagged[i] for i, j in evaluate.match_segments(tagged, labels)}
        for index, label in enumerate(labels):
            assert index in by_label
            if label.type == "save":
                assert by_label[index].event == "save"
                assert by_label[index].event_confidence == 0.6
            elif label.type in ("goal", "red_card", "controversy"):
                assert by_label[index].event != "save"


def test_ac12_eval_api_and_cli_meet_save_goal_and_unchanged_overall_gates(t014_eval_set):
    root, _builder, _videos = t014_eval_set
    report = evaluate.evaluate_dir(root)
    assert report["per_event"]["save"]["precision"] >= 0.8
    assert report["per_event"]["save"]["recall"] >= 0.8
    assert report["per_event"]["goal"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert (report["f1"], report["precision"], report["recall"], report["precision_at_5"]) == (
        0.8421,
        0.7273,
        1.0,
        0.8889,
    )
    result = subprocess.run(
        [sys.executable, "-m", "sportscut", "eval", str(root), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == report


def test_ac13_budget_check_is_opt_in_and_has_the_required_contract():
    source = (ROOT / "tests/test_audio_cues.py").read_text()
    assert "def test_ninety_minute_budget" in source
    assert "set SPORTSCUT_PERF=1 to run the 90-minute budget check" in source
    assert 'os.environ.get("SPORTSCUT_PERF") != "1"' in source
    assert "duration=5400" in source
    assert "size=640x360:rate=25" in source
    assert "budget:" in source and "for 5400s" in source
    assert "elapsed < 600" in source


def test_ac14_readme_records_metrics_tuning_limits_and_unchanged_old_blocks():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    report, after = _readme_json(readme, "Kết quả sau T-014")
    assert report["per_event"]["save"]["recall"] >= 0.8
    assert report["per_event"]["goal"]["recall"] >= 0.95
    assert report["f1"] >= 0.8421
    assert "data/eval/" in after and "tổng hợp" in after

    base_readme = subprocess.run(
        ["/usr/bin/git", "show", f"{_git_base()}:README.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for marker in ("Baseline đo trong T-011", "Kết quả sau T-013"):
        assert _readme_json(readme, marker)[0] == _readme_json(base_readme, marker)[0]
    t013 = (
        ROOT / "docs/superpowers/specs/2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md"
    ).read_text(encoding="utf-8")
    assert "(updated by T-014" in t013


def test_ac15_task_diff_uses_merge_base_and_touches_no_forbidden_path():
    changed = set(
        subprocess.run(
            ["/usr/bin/git", "diff", "--name-only", _git_base()],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
    )
    forbidden = {
        "tests/conftest.py",
        "sportscut/models.py",
        "sportscut/ranking.py",
        "sportscut/export.py",
        "tests/fixtures/eval/build.py",
    }
    assert changed.isdisjoint(forbidden)
    assert not any(
        path.startswith("tests/fixtures/eval/") and path.endswith("/labels.json")
        for path in changed
    )
    assert not any(path == "agent-office" or path.startswith("agent-office/") for path in changed)
    assert not any(path == ".agent-office" or path.startswith(".agent-office/") for path in changed)
