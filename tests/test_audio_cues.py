import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import numpy as np
import pytest

from sportscut import pipeline
from sportscut import evaluate
from sportscut.events import audio_cues
from sportscut.events import incidents
from sportscut.events import scoreboard
from sportscut.media import SAMPLE_RATE, MediaError, extract_audio, sample_top_band
from sportscut.models import Segment


@pytest.fixture(scope="module")
def built_eval_set(tmp_path_factory, require_ffmpeg):
    build_path = Path(__file__).parent / "fixtures" / "eval" / "build.py"
    spec = importlib.util.spec_from_file_location("t014_eval_build", build_path)
    assert spec is not None and spec.loader is not None
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    root = tmp_path_factory.mktemp("t014_eval")
    build.build_all(root)
    return root, build


def _tone(frequency: float, seconds: float = 1.0, amplitude: float = 0.3) -> np.ndarray:
    t = np.arange(round(seconds * SAMPLE_RATE), dtype=np.float64) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


def _levels() -> np.ndarray:
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


def test_window_levels_constant_zero_and_empty():
    levels = audio_cues.window_levels(np.full(SAMPLE_RATE, 0.1, np.float32))
    assert len(levels) == 10
    assert levels.dtype == np.float64
    assert levels == pytest.approx(np.full(10, -20.0), abs=1e-4)

    assert audio_cues.window_levels(np.zeros(1650, np.float32)) == pytest.approx(
        [-200.0], abs=1e-9
    )
    empty = audio_cues.window_levels(np.empty(0, np.float32))
    assert empty.dtype == np.float64
    assert len(empty) == 0


def test_band_share_tone_offband_silence_and_white_noise():
    whistle = audio_cues.band_share(_tone(3000), 2000, 4000)
    off_band = audio_cues.band_share(_tone(500), 2000, 4000)
    silence = audio_cues.band_share(np.zeros(SAMPLE_RATE, np.float32), 2000, 4000)
    noise = audio_cues.band_share(
        np.random.default_rng(0).normal(0, 0.1, 10 * SAMPLE_RATE).astype(np.float32),
        2000,
        4000,
    )
    play = audio_cues.band_share(_tone(1000, amplitude=0.02), 300, 2000)

    assert len(whistle) == len(off_band) == len(silence) == len(play) == 10
    assert np.all(whistle >= 0.99)
    assert np.all(off_band <= 0.01)
    assert np.array_equal(silence, np.zeros(10))
    assert np.all((0.15 <= noise) & (noise <= 0.35))
    assert np.all(play >= 0.99)


def test_find_whistles_keeps_runs_of_at_least_three_windows():
    signal = _tone(500, seconds=10, amplitude=0.02)
    whistle = _tone(3000, amplitude=0.3)
    for start, duration in ((2.0, 1.0), (5.0, 0.2), (7.0, 0.3)):
        first = round(start * SAMPLE_RATE)
        count = round(duration * SAMPLE_RATE)
        signal[first : first + count] += whistle[:count]

    assert audio_cues.find_whistles(signal) == [(2.0, 3.0), (7.0, 7.3)]
    assert audio_cues.find_whistles(
        np.random.default_rng(1).normal(0, 0.1, 10 * SAMPLE_RATE).astype(np.float32)
    ) == []
    assert audio_cues.find_whistles(np.zeros(10 * SAMPLE_RATE, np.float32)) == []


def test_stoppage_after_counts_quiet_play_band_ignoring_low_booing():
    signal = _tone(1000, seconds=120, amplitude=0.02)
    signal[50 * SAMPLE_RATE : 62 * SAMPLE_RATE] *= 0.25
    signal[53 * SAMPLE_RATE : 60 * SAMPLE_RATE] += _tone(
        100, seconds=7, amplitude=0.08
    )

    assert audio_cues.stoppage_after(signal, 50.0) == pytest.approx(12.0)
    assert audio_cues.stoppage_after(signal, 56.0) == pytest.approx(6.0)
    assert audio_cues.stoppage_after(signal, 40.0) == 0.0
    assert audio_cues.stoppage_after(signal, 200.0) == 0.0

    near_end = _tone(1000, seconds=120, amplitude=0.02)
    near_end[110 * SAMPLE_RATE : 120 * SAMPLE_RATE] *= 0.25
    assert audio_cues.stoppage_after(near_end, 110.0) == pytest.approx(10.0)


def test_roar_shape_save_like_swell_like_long_below_and_empty():
    levels = _levels()

    assert audio_cues.roar_shape(levels, 46.0, 58.0) == pytest.approx(
        audio_cues.RoarShape(50.0, 50.0, 52.4, 2.4, 0.1, 0.0)
    )
    assert audio_cues.roar_shape(levels, 78.0, 90.0) == pytest.approx(
        audio_cues.RoarShape(82.5, 81.5, 84.0, 2.5, 2.5, 0.5)
    )
    long = audio_cues.roar_shape(levels, 56.0, 68.0)
    assert long.duration == pytest.approx(4.0)
    assert long.rise == 0.0
    assert audio_cues.roar_shape(levels, 96.0, 108.0) == audio_cues.RoarShape(
        100.0, 100.0, 100.0, 0.0, 0.0, 0.0
    )
    assert audio_cues.roar_shape(levels, 130.0, 140.0) == audio_cues.RoarShape(
        130.0, 130.0, 130.0, 0.0, 0.0, 0.0
    )


def test_roar_shape_rise_uses_first_window_in_five_second_lookback():
    levels = _levels()
    levels[455] = -36

    assert audio_cues.roar_shape(levels, 46.0, 58.0).rise == pytest.approx(4.5)


def test_match_saves_tags_only_short_sharp_other_roars():
    short = Segment(46.0, 58.0, 5.0, "audio peak z=5.0")
    slow = Segment(78.0, 90.0, 4.0, "w")
    long = Segment(56.0, 68.0, 3.0, "l")
    below = Segment(96.0, 108.0, 2.0, "b")
    goal = Segment(46.0, 58.0, 5.0, "g", "goal", 0.9)
    original = [short, slow, long, below, goal]

    result = audio_cues.match_saves(original, _levels(), [], [])

    assert result == [
        Segment(
            46.0,
            58.0,
            5.0,
            "audio peak z=5.0; sharp roar 2.4s",
            "save",
            0.6,
        ),
        slow,
        long,
        below,
        goal,
    ]
    assert result[1:] == original[1:]
    assert original == [short, slow, long, below, goal]
    no_board = audio_cues.match_saves([short], _levels(), [], None)
    assert no_board == [short]
    assert no_board is not original

    slow_rise_levels = _levels()
    slow_rise_levels[455] = -36
    assert audio_cues.match_saves([short], slow_rise_levels, [], []) == [short]


@pytest.mark.parametrize(
    ("whistles", "changes", "event"),
    [
        ([(55.0, 56.0)], [], "other"),
        ([(50.5, 51.5)], [], "other"),
        ([(57.5, 58.5)], [], "save"),
        ([(48.0, 49.9)], [], "save"),
        ([], [80.0], "other"),
        ([], [40.0], "other"),
        ([], [80.5], "save"),
        ([], [39.5], "save"),
    ],
)
def test_match_saves_whistle_and_board_exclusions(whistles, changes, event):
    segment = Segment(46.0, 58.0, 5.0, "audio peak z=5.0")

    result = audio_cues.match_saves([segment], _levels(), whistles, changes)

    assert result[0].event == event


def test_board_changes_composes_scoreboard_helpers(monkeypatch):
    frames = np.zeros((2, 3, 4), dtype=np.uint8)
    box = (0, 0, 4, 3)
    calls = []

    monkeypatch.setattr(
        scoreboard,
        "sample_top_band",
        lambda video: calls.append(("sample", video)) or frames,
    )
    monkeypatch.setattr(
        scoreboard,
        "find_box",
        lambda value: calls.append(("box", value)) or box,
    )
    monkeypatch.setattr(
        scoreboard,
        "score_changes",
        lambda value, found: calls.append(("changes", value, found)) or [12.0],
    )

    assert scoreboard.board_changes("match.mp4") == [12.0]
    assert calls == [
        ("sample", "match.mp4"),
        ("box", frames),
        ("changes", frames, box),
    ]

    monkeypatch.setattr(scoreboard, "find_box", lambda _frames: None)
    monkeypatch.setattr(
        scoreboard,
        "score_changes",
        lambda *_args: pytest.fail("score changes ran without a board"),
    )
    assert scoreboard.board_changes("match.mp4") is None


def test_tag_saves_without_board_skips_audio(monkeypatch):
    segments = [Segment(1.0, 2.0, 3.0, "candidate")]
    monkeypatch.setattr(scoreboard, "board_changes", lambda _video: None)
    monkeypatch.setattr(
        audio_cues,
        "extract_audio",
        lambda _video: pytest.fail("audio decoded without a scoreboard"),
    )

    result = audio_cues.tag_saves("match.mp4", segments)

    assert result == segments
    assert result is not segments


def test_tag_saves_without_board_keeps_real_burst(burst_video):
    segments = pipeline.find_highlights(burst_video, top=None)

    assert scoreboard.board_changes(burst_video) is None
    assert audio_cues.tag_saves(burst_video, segments) == segments


def test_tag_saves_with_board_decodes_once(monkeypatch):
    segments = [Segment(1.0, 2.0, 3.0, "candidate")]
    samples = np.arange(10, dtype=np.float32)
    levels = np.array([-20.0])
    whistles = [(1.0, 2.0)]
    tagged = [Segment(1.0, 2.0, 3.0, "tagged")]
    decoded = []

    monkeypatch.setattr(scoreboard, "board_changes", lambda _video: [])
    monkeypatch.setattr(
        audio_cues,
        "extract_audio",
        lambda video: decoded.append(video) or samples,
    )
    monkeypatch.setattr(
        audio_cues,
        "window_levels",
        lambda value: levels if value is samples else pytest.fail("wrong samples"),
    )
    monkeypatch.setattr(
        audio_cues,
        "find_whistles",
        lambda value: whistles if value is samples else pytest.fail("wrong samples"),
    )

    def fake_match(received, found_levels, found_whistles, changes):
        assert received == segments and received is not segments
        assert found_levels is levels
        assert found_whistles is whistles
        assert changes == []
        return tagged

    monkeypatch.setattr(audio_cues, "match_saves", fake_match)

    assert audio_cues.tag_saves("match.mp4", segments) is tagged
    assert decoded == ["match.mp4"]


def test_audio_cues_does_not_import_subprocess():
    source = Path(audio_cues.__file__).read_text(encoding="utf-8")
    imported = {
        alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )

    assert "subprocess" not in imported


def test_pipeline_calls_tag_saves_after_tag_goals_and_wraps_media_error(
    tmp_path, monkeypatch
):
    video = tmp_path / "match.mp4"
    output = tmp_path / "clips"
    detected = [Segment(1.0, 2.0, 5.0, "detected")]
    goals = [Segment(1.0, 2.0, 5.0, "goal", "goal", 0.9)]
    saves = [Segment(3.0, 4.0, 4.0, "save", "save", 0.6)]
    selected = [saves[0]]
    calls = []

    monkeypatch.setattr(pipeline, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(pipeline, "has_audio", lambda value: value == video)

    def fake_find(value, **kwargs):
        calls.append(("find", value, kwargs))
        return detected

    def fake_goals(value, segments, **kwargs):
        calls.append(("goals", value, segments, kwargs))
        return goals

    def fake_saves(value, segments):
        calls.append(("saves", value, segments))
        return saves

    def fake_select(segments, **kwargs):
        calls.append(("select", segments, kwargs))
        return selected

    def fake_export(_video, segments, out_dir):
        assert segments is selected
        Path(out_dir).mkdir()
        (Path(out_dir) / pipeline.MANIFEST_NAME).write_text(
            json.dumps([segment.to_dict() for segment in segments])
        )

    monkeypatch.setattr(pipeline, "find_highlights", fake_find)
    monkeypatch.setattr(pipeline, "tag_goals", fake_goals)
    monkeypatch.setattr(pipeline, "tag_incidents", lambda _video, segments: segments)
    monkeypatch.setattr(pipeline, "tag_saves", fake_saves)
    monkeypatch.setattr(pipeline, "select_segments", fake_select)
    monkeypatch.setattr(pipeline, "export_clips", fake_export)

    pipeline.run(video, output, top=2, min_len=4, max_len=6)

    assert calls == [
        ("find", video, {"top": None, "min_len": 4, "max_len": 6}),
        ("goals", video, detected, {"min_len": 4, "max_len": 6}),
        ("saves", video, goals),
        ("select", saves, {"top": 2, "events": None}),
    ]

    monkeypatch.setattr(
        pipeline,
        "tag_saves",
        lambda *_args: (_ for _ in ()).throw(MediaError("save decode failed")),
    )
    with pytest.raises(pipeline.PipelineError, match="^save decode failed$"):
        pipeline.run(video, output, top=2, min_len=4, max_len=6)


def test_evaluate_dir_runs_tag_saves_on_tag_goals_output(tmp_path, monkeypatch):
    case = tmp_path / "case"
    case.mkdir()
    video = case / "video.mp4"
    video.touch()
    (case / "labels.json").write_text(
        json.dumps([{"start": 1.0, "end": 2.0, "type": "save"}])
    )
    detected = [Segment(0.0, 3.0, 5.0, "detected")]
    goals = [Segment(0.0, 3.0, 5.0, "after goals")]
    saves = [Segment(0.0, 3.0, 5.0, "after saves", "save", 0.6)]
    calls = []

    monkeypatch.setattr(evaluate.detect, "find_highlights", lambda value, **kw: detected)

    def fake_goals(value, segments):
        calls.append(("goals", value, segments))
        return goals

    def fake_saves(value, segments):
        calls.append(("saves", value, segments))
        return saves

    monkeypatch.setattr(evaluate.scoreboard, "tag_goals", fake_goals)
    monkeypatch.setattr(incidents, "tag_incidents", lambda _video, segments: segments)
    monkeypatch.setattr(audio_cues, "tag_saves", fake_saves)

    report = evaluate.evaluate_dir(tmp_path)

    assert calls == [("goals", video, detected), ("saves", video, goals)]
    assert report["per_event"]["save"] == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }


def test_board_changes_matches_inline_detection(built_eval_set):
    root, _build = built_eval_set
    for case in sorted(path for path in root.iterdir() if path.is_dir()):
        video = case / "video.mp4"
        frames = sample_top_band(video)
        box = scoreboard.find_box(frames)
        expected = None if box is None else scoreboard.score_changes(frames, box)

        assert scoreboard.board_changes(video) == expected


def test_fixture_whistles_and_stoppages(built_eval_set):
    root, build = built_eval_set
    expected_counts = {"cards": 3, "controversy": 2, "goals_saves": 0, "mixed": 1}

    for name, match in build.MATCHES.items():
        samples = extract_audio(root / name / "video.mp4")
        whistles = audio_cues.find_whistles(samples)
        expected = [
            (kind, float(at))
            for kind, at, *_details in match["events"]
            if kind in ("red_card", "controversy")
        ]
        assert len(whistles) == expected_counts[name] == len(expected)
        for (start, end), (kind, at) in zip(whistles, expected):
            assert abs(start - at) <= 0.2
            assert 0.8 <= end - start <= 1.3
            stoppage = audio_cues.stoppage_after(samples, end)
            if kind == "red_card":
                assert 9.0 <= stoppage <= 13.0
            else:
                assert 25.0 <= stoppage <= 37.0


def test_tag_saves_labels_every_fixture_save_and_nothing_else_scored(
    built_eval_set,
):
    root, _build = built_eval_set
    for case in sorted(path for path in root.iterdir() if path.is_dir()):
        video = case / "video.mp4"
        goals = scoreboard.tag_goals(video, pipeline.find_highlights(video, top=None))
        segments = audio_cues.tag_saves(video, goals)
        labels = evaluate.load_labels(case / "labels.json")

        assert len(segments) == len(goals)
        assert [
            (segment.start, segment.end, segment.score) for segment in segments
        ] == [(segment.start, segment.end, segment.score) for segment in goals]
        for before, after in zip(goals, segments):
            if before.event == "goal":
                assert after == before

        paired = {
            label_index: segments[segment_index]
            for segment_index, label_index in evaluate.match_segments(segments, labels)
        }
        for label_index, label in enumerate(labels):
            if label.type == "save":
                assert paired[label_index].event == "save"
                assert paired[label_index].event_confidence == 0.6
            elif label.type in ("goal", "red_card", "controversy"):
                assert paired[label_index].event != "save"


def test_eval_save_gate_and_unchanged_goal_and_overall_metrics(built_eval_set):
    root, _build = built_eval_set
    report = evaluate.evaluate_dir(root)

    assert report["per_event"]["save"]["recall"] >= 0.8
    assert report["per_event"]["save"]["precision"] >= 0.8
    assert report["per_event"]["goal"] == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }
    assert report["f1"] == 0.8421
    assert report["precision"] == 0.7273
    assert report["recall"] == 1.0
    assert report["precision_at_5"] == 0.8889

    result = subprocess.run(
        [sys.executable, "-m", "sportscut", "eval", str(root), "--json"],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == report


@pytest.mark.skipif(
    os.environ.get("SPORTSCUT_PERF") != "1",
    reason="set SPORTSCUT_PERF=1 to run the 90-minute budget check",
)
def test_ninety_minute_budget(tmp_path, require_ffmpeg, monkeypatch):
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
    real_board_changes = scoreboard.board_changes

    def force_audio_path(value):
        changes = real_board_changes(value)
        return [] if changes is None else changes

    monkeypatch.setattr(scoreboard, "board_changes", force_audio_path)

    started = time.perf_counter()
    candidates = pipeline.find_highlights(video, top=None)
    goals = scoreboard.tag_goals(video, candidates)
    audio_cues.tag_saves(video, goals)
    elapsed = time.perf_counter() - started

    print(f"budget: {elapsed:.2f}s for 5400s")
    assert elapsed < 600


def test_readme_records_t014_invariants_and_t013_spec_note():
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    marker = "Kết quả sau T-014"
    assert marker in readme
    after = readme.split(marker, 1)[1]
    block = re.search(r"```json\n([^\n]+)\n```", after)
    assert block is not None
    report = json.loads(block.group(1))
    assert report["per_event"]["save"]["recall"] >= 0.8
    assert report["per_event"]["goal"]["recall"] >= 0.95
    assert report["f1"] >= 0.8421
    assert "data/eval/" in after
    assert "tổng hợp" in after
    assert "Baseline đo trong T-011" in readme
    assert "Kết quả sau T-013" in readme

    t013_spec = (
        root
        / "docs/superpowers/specs/2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md"
    ).read_text(encoding="utf-8")
    assert "(updated by T-014" in t013_spec
