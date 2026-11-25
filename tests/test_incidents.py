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

from sportscut import detect, evaluate
from sportscut.events import audio_cues, incidents, scoreboard
from sportscut.media import SAMPLE_RATE, MediaError
from sportscut.models import Segment


def _board_state(kind: str) -> np.ndarray:
    frame = np.zeros((30, 160), dtype=np.uint8)
    if kind == "b":
        frame[4:14, 5:11] = 255
    elif kind == "c":
        frame[4:14, 21:27] = 255
    return frame


def _state_run(*runs: tuple[str, int]) -> np.ndarray:
    return np.concatenate(
        [np.repeat(_board_state(kind)[None], count, axis=0) for kind, count in runs]
    )


def test_find_reverts_pairs_and_gap_limit():
    box = (2, 2, 30, 14)
    reverted = _state_run(("a", 10), ("b", 10), ("a", 20))
    changed_again = _state_run(("a", 10), ("b", 10), ("c", 20))
    too_late = _state_run(("a", 10), ("b", 181), ("a", 9))
    inclusive = _state_run(("a", 10), ("b", 180), ("a", 10))

    assert scoreboard.score_changes(reverted, box) == [10.0, 20.0]
    assert scoreboard.find_reverts(reverted, box, [10.0, 20.0]) == [
        (10.0, 20.0)
    ]
    assert scoreboard.find_reverts(changed_again, box, [10.0, 20.0]) == []
    assert scoreboard.find_reverts(too_late, box, [10.0, 191.0]) == []
    assert scoreboard.find_reverts(inclusive, box, [10.0, 190.0]) == [
        (10.0, 190.0)
    ]
    assert scoreboard.find_reverts(reverted, box, []) == []
    assert scoreboard.find_reverts(reverted, box, [10.0]) == []


def test_find_reverts_needs_near_identical_board():
    # 0 -> 1 -> 2 on the built 'mixed' match: the '2' glyph differs from '0' in
    # only 2.58% of board pixels (< CHANGE_FRAC), so it is not a revert.
    box = (2, 2, 30, 14)
    near = np.zeros((30, 160), dtype=np.uint8)
    near[4:6, 5:9] = 255  # 8 of 420 board pixels = 1.9%
    frames = np.concatenate(
        [
            np.repeat(_board_state("a")[None], 10, axis=0),
            np.repeat(_board_state("b")[None], 10, axis=0),
            np.repeat(near[None], 20, axis=0),
        ]
    )
    nearly_same = frames.copy()
    nearly_same[20:] = 0
    nearly_same[20:, 4, 5:9] = 255  # 4 of 420 = 0.95%, still the same state

    assert scoreboard.REVERT_FRAC == 0.01
    assert scoreboard.find_reverts(frames, box, [10.0, 20.0]) == []
    assert scoreboard.find_reverts(nearly_same, box, [10.0, 20.0]) == [(10.0, 20.0)]


def test_board_reverts_composes_helpers_and_skips_without_box(monkeypatch):
    frames = np.zeros((4, 30, 160), dtype=np.uint8)
    box = (2, 2, 30, 14)
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
        lambda value, found: calls.append(("changes", value, found))
        or [10.0, 20.0],
    )
    monkeypatch.setattr(
        scoreboard,
        "find_reverts",
        lambda value, found, changes: calls.append(
            ("reverts", value, found, changes)
        )
        or [(10.0, 20.0)],
    )

    assert scoreboard.board_reverts("m.mp4") == [(10.0, 20.0)]
    assert calls[0] == ("sample", "m.mp4")
    assert calls[1][0] == "box" and calls[1][1] is frames
    assert calls[2][0] == "changes" and calls[2][1] is frames
    assert calls[2][2] == box
    assert calls[3][0] == "reverts" and calls[3][1] is frames
    assert calls[3][2:] == (box, [10.0, 20.0])

    calls.clear()
    monkeypatch.setattr(
        scoreboard,
        "find_box",
        lambda value: calls.append(("box", value)) or None,
    )
    monkeypatch.setattr(
        scoreboard,
        "score_changes",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected changes")),
    )
    monkeypatch.setattr(
        scoreboard,
        "find_reverts",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected reverts")),
    )

    assert scoreboard.board_reverts("m.mp4") == []
    assert calls[0] == ("sample", "m.mp4")
    assert calls[1][0] == "box" and calls[1][1] is frames


def test_red_share_centre_crop_and_pixel_thresholds():
    frames = np.empty((3, 90, 160, 3), dtype=np.uint8)
    frames[0] = (200, 20, 20)
    frames[1] = (40, 140, 60)
    frames[2] = (200, 20, 20)
    frames[2, 22:67, 40:120] = (40, 140, 60)

    assert incidents.red_share(frames) == pytest.approx([1.0, 0.0, 0.0])

    partial = np.full((1, 90, 160, 3), (40, 140, 60), dtype=np.uint8)
    partial[0, 22:44, 40:120] = (200, 20, 20)
    assert incidents.red_share(partial) == pytest.approx([22 / 45])

    for colour, expected in (
        ((150, 60, 60), 1.0),
        ((149, 60, 60), 0.0),
        ((150, 61, 60), 0.0),
        ((150, 60, 61), 0.0),
    ):
        frame = np.full((1, 90, 160, 3), colour, dtype=np.uint8)
        assert incidents.red_share(frame) == pytest.approx([expected])

    empty = incidents.red_share(np.empty((0, 90, 160, 3), dtype=np.uint8))
    assert empty.dtype == np.float64
    assert len(empty) == 0


def test_booing_seconds_counts_low_band_windows():
    time_axis = np.arange(120 * SAMPLE_RATE, dtype=np.float64) / SAMPLE_RATE
    signal = 0.02 * np.sin(2 * np.pi * 1000 * time_axis)
    first, stop = 63 * SAMPLE_RATE, 93 * SAMPLE_RATE
    signal[first:stop] += 0.08 * np.sin(
        2 * np.pi * 100 * time_axis[first:stop]
    )

    assert incidents.booing_seconds(signal, 61.0, 97.0) == pytest.approx(30.0)
    assert incidents.booing_seconds(signal, 61.0, 70.0) == pytest.approx(7.0)
    assert incidents.booing_seconds(signal, 0.0, 60.0) == 0.0
    assert incidents.booing_seconds(signal, 200.0, 210.0) == 0.0
    assert incidents.booing_seconds(signal, 70.0, 65.0) == 0.0


@pytest.mark.parametrize(
    ("stoppage", "booing", "red_frames", "event"),
    [
        (8.0, 0.0, 2, "red_card"),
        (7.9, 0.0, 9, "other"),
        (36.0, 30.0, 1, "controversy"),
        (36.0, 30.0, 2, "red_card"),
        (30.0, 10.0, 0, "controversy"),
        (29.9, 30.0, 0, "other"),
        (36.0, 9.9, 0, "other"),
    ],
)
def test_classify_thresholds_and_precedence(
    stoppage, booing, red_frames, event
):
    assert incidents.classify(stoppage, booing, red_frames) == event


def test_sample_frames_command_and_shape(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"placeholder")
    frame_size = incidents.FRAME_W * incidents.FRAME_H * 3
    calls = []

    class Result:
        returncode = 0
        stdout = b"\0" * (frame_size * 2 + frame_size // 2)
        stderr = b""

    monkeypatch.setattr(incidents, "find_tool", lambda name: f"/tools/{name}")
    monkeypatch.setattr(
        incidents.subprocess,
        "run",
        lambda args, **kwargs: calls.append((args, kwargs)) or Result(),
    )

    frames = incidents.sample_frames(video, 24.0, 4.0)

    assert calls == [
        (
            [
                "/tools/ffmpeg",
                "-v",
                "error",
                "-nostdin",
                "-ss",
                "24.000",
                "-i",
                str(video),
                "-t",
                "4.000",
                "-an",
                "-vf",
                "fps=2,scale=160:90",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "pipe:1",
            ],
            {"capture_output": True, "check": False},
        )
    ]
    assert frames.dtype == np.uint8
    assert frames.shape == (2, 90, 160, 3)


def test_sample_frames_real_black_white(synthetic_video):
    black = incidents.sample_frames(synthetic_video, 0.5, 2.0)
    white = incidents.sample_frames(synthetic_video, 3.5, 2.0)

    assert 3 <= len(black) <= 5
    assert black.mean() <= 30
    assert 3 <= len(white) <= 5
    assert white.mean() >= 225


def test_sample_frames_missing_and_non_media(tmp_path, require_ffmpeg, monkeypatch):
    missing = tmp_path / "missing.mp4"
    with monkeypatch.context() as no_tools:
        no_tools.setenv("PATH", "/nonexistent")
        with pytest.raises(MediaError, match=r"^media file not found:"):
            incidents.sample_frames(missing, 0.0, 1.0)

    text = tmp_path / "not-media.txt"
    text.write_text("not media", encoding="utf-8")
    with pytest.raises(MediaError, match=r"^ffmpeg failed for"):
        incidents.sample_frames(text, 0.0, 1.0)


def _incident_signal() -> np.ndarray:
    time_axis = np.arange(120 * SAMPLE_RATE, dtype=np.float64) / SAMPLE_RATE
    signal = 0.02 * np.sin(2 * np.pi * 1000 * time_axis)
    signal[21 * SAMPLE_RATE : 33 * SAMPLE_RATE] *= 0.25
    signal[61 * SAMPLE_RATE : 97 * SAMPLE_RATE] *= 0.25
    signal[63 * SAMPLE_RATE : 93 * SAMPLE_RATE] += 0.08 * np.sin(
        2 * np.pi * 100 * time_axis[63 * SAMPLE_RATE : 93 * SAMPLE_RATE]
    )
    for start in (20, 60, 105):
        span = slice(start * SAMPLE_RATE, (start + 1) * SAMPLE_RATE)
        signal[span] += 0.3 * np.sin(2 * np.pi * 3000 * time_axis[span])
    return signal.astype(np.float32)


def _solid_frames(colour, count=4) -> np.ndarray:
    return np.full((count, 90, 160, 3), colour, dtype=np.uint8)


def test_tag_incidents_audio_rules_and_frame_locality(monkeypatch):
    signal = _incident_signal()
    assert audio_cues.find_whistles(signal) == [
        (20.0, 21.0),
        (60.0, 61.0),
        (105.0, 106.0),
    ]
    assert audio_cues.stoppage_after(signal, 21.0) == pytest.approx(12.0)
    assert audio_cues.stoppage_after(signal, 61.0) == pytest.approx(36.0)
    audio_calls = []
    frame_calls = []
    revert_calls = []
    monkeypatch.setattr(
        incidents,
        "extract_audio",
        lambda video: audio_calls.append(video) or signal,
    )

    def fake_frames(video, start, duration):
        frame_calls.append((video, start, duration))
        colour = (200, 20, 20) if start == 21.0 else (40, 140, 60)
        return _solid_frames(colour)

    monkeypatch.setattr(incidents, "sample_frames", fake_frames)
    monkeypatch.setattr(
        scoreboard,
        "board_reverts",
        lambda video: revert_calls.append(video) or [],
    )
    a = Segment(15, 27, 5, "a")
    b = Segment(55, 67, 4, "b")
    c = Segment(80, 92, 3, "c")
    d = Segment(100, 112, 2, "d")
    goal = Segment(56, 68, 6, "g", "goal", 0.9)
    save = Segment(14, 26, 1, "s", "save", 0.6)
    original = [a, b, c, d, goal, save]
    snapshot = list(original)

    result = incidents.tag_incidents("m.mp4", original)

    assert result == [
        Segment(
            15,
            27,
            5,
            "a; whistle at 20s, stoppage 12s, red close-up",
            "red_card",
            0.5,
        ),
        Segment(
            55,
            67,
            4,
            "b; whistle at 60s, stoppage 36s, booing 30s",
            "controversy",
            0.4,
        ),
        c,
        d,
        goal,
        save,
    ]
    assert original == snapshot
    assert frame_calls == [
        ("m.mp4", 21.0, 15.0),
        ("m.mp4", 61.0, 15.0),
    ]
    assert audio_calls == ["m.mp4"]
    assert revert_calls == ["m.mp4"]


def test_tag_incidents_red_beats_controversy_and_needs_two_frames(monkeypatch):
    signal = _incident_signal()
    monkeypatch.setattr(incidents, "extract_audio", lambda _video: signal)
    monkeypatch.setattr(scoreboard, "board_reverts", lambda _video: [])
    a = Segment(15, 27, 5, "a")
    b = Segment(55, 67, 4, "b")
    monkeypatch.setattr(
        incidents,
        "sample_frames",
        lambda _video, _start, _duration: _solid_frames((200, 20, 20)),
    )

    result = incidents.tag_incidents("m.mp4", [a, b])

    assert result[1] == Segment(
        55,
        67,
        4,
        "b; whistle at 60s, stoppage 36s, red close-up",
        "red_card",
        0.5,
    )

    one_red = np.concatenate(
        [_solid_frames((200, 20, 20), 1), _solid_frames((40, 140, 60), 3)]
    )
    monkeypatch.setattr(
        incidents,
        "sample_frames",
        lambda _video, start, _duration: one_red
        if start == 21.0
        else _solid_frames((40, 140, 60)),
    )
    assert incidents.tag_incidents("m.mp4", [a])[0] is a


def test_tag_incidents_reverted_goal_becomes_controversy(monkeypatch):
    calls = []
    monkeypatch.setattr(
        scoreboard,
        "board_reverts",
        lambda video: calls.append(video) or [(45.0, 150.0)],
    )
    monkeypatch.setattr(
        incidents,
        "extract_audio",
        lambda _video: (_ for _ in ()).throw(AssertionError("unexpected audio")),
    )
    goals = [
        Segment(
            40,
            52,
            5,
            "audio peak z=5.0; scoreboard change at 45s",
            "goal",
            0.9,
        ),
        Segment(90, 120, 3, "scoreboard change at 150s", "goal", 0.6),
        Segment(
            10,
            22,
            7,
            "audio peak z=7.0; scoreboard change at 13s",
            "goal",
            0.9,
        ),
        Segment(
            60,
            72,
            4,
            "audio peak z=4.0; sustained roar 8s",
            "goal",
            0.4,
        ),
    ]

    result = incidents.tag_incidents("m.mp4", goals)

    suffix = "; scoreboard change at 45s reverted at 150s"
    assert result[0] == Segment(
        40,
        52,
        5,
        goals[0].reason + suffix,
        "controversy",
        0.5,
    )
    assert result[1] == Segment(
        90,
        120,
        3,
        goals[1].reason + suffix,
        "controversy",
        0.5,
    )
    assert result[2:] == goals[2:]
    assert calls == ["m.mp4"]


def test_tag_incidents_skips_decoding_when_nothing_to_check(monkeypatch):
    monkeypatch.setattr(
        incidents,
        "extract_audio",
        lambda _video: (_ for _ in ()).throw(AssertionError("unexpected audio")),
    )
    monkeypatch.setattr(
        incidents,
        "sample_frames",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected frames")),
    )
    monkeypatch.setattr(
        scoreboard,
        "board_reverts",
        lambda _video: (_ for _ in ()).throw(AssertionError("unexpected board")),
    )
    done = [
        Segment(1, 5, 1, "s", "save", 0.6),
        Segment(6, 9, 1, "r", "red_card", 0.5),
    ]

    assert incidents.tag_incidents("m.mp4", []) == []
    assert incidents.tag_incidents("m.mp4", done) == done


def test_tag_incidents_real_noise_videos_unchanged(
    burst_video, synthetic_video
):
    burst = [
        Segment(10, 22, 3, "x"),
        Segment(40, 52, 2, "y", "goal", 0.9),
    ]
    simple = [Segment(0, 4, 1, "z")]

    assert incidents.tag_incidents(burst_video, burst) == burst
    assert incidents.tag_incidents(synthetic_video, simple) == simple


def test_pipeline_calls_tag_incidents_between_goals_and_saves(
    tmp_path, monkeypatch
):
    from sportscut import pipeline

    video = tmp_path / "match.mp4"
    output = tmp_path / "clips"
    found = [Segment(1, 5, 1, "found")]
    goals = [Segment(1, 5, 1, "goal", "goal", 0.9)]
    tagged = [Segment(6, 10, 2, "red", "red_card", 0.5)]
    saved = [Segment(11, 15, 3, "save", "save", 0.6)]
    calls = []
    monkeypatch.setattr(pipeline, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(pipeline, "has_audio", lambda value: value == video)
    monkeypatch.setattr(
        pipeline,
        "find_highlights",
        lambda value, **kwargs: calls.append(("find", value, kwargs)) or found,
    )
    monkeypatch.setattr(
        pipeline,
        "tag_goals",
        lambda value, segments, **kwargs: calls.append(
            ("goals", value, segments, kwargs)
        )
        or goals,
    )
    monkeypatch.setattr(
        pipeline,
        "tag_incidents",
        lambda value, segments: calls.append(("incidents", value, segments))
        or tagged,
    )
    monkeypatch.setattr(
        pipeline,
        "tag_saves",
        lambda value, segments: calls.append(("saves", value, segments)) or saved,
    )
    monkeypatch.setattr(
        pipeline,
        "select_segments",
        lambda segments, **kwargs: calls.append(("select", segments, kwargs))
        or segments,
    )

    def fake_export(_video, segments, out_dir):
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / pipeline.MANIFEST_NAME).write_text(
            json.dumps([item.to_dict() for item in segments]),
            encoding="utf-8",
        )

    monkeypatch.setattr(pipeline, "export_clips", fake_export)

    pipeline.run(video, output, top=2, min_len=4, max_len=6)

    assert [call[0] for call in calls] == [
        "find",
        "goals",
        "incidents",
        "saves",
        "select",
    ]
    assert calls[2][1:] == (video, goals)
    assert calls[2][2] is goals
    assert calls[3][1:] == (video, tagged)
    assert calls[3][2] is tagged
    assert calls[4][1] is saved

    monkeypatch.setattr(
        pipeline,
        "tag_incidents",
        lambda *_args: (_ for _ in ()).throw(MediaError("incident decode failed")),
    )
    with pytest.raises(pipeline.PipelineError, match="^incident decode failed$"):
        pipeline.run(video, tmp_path / "error", top=2, min_len=4, max_len=6)


def test_evaluate_dir_chains_goals_incidents_saves(tmp_path, monkeypatch):
    from sportscut import evaluate

    case = tmp_path / "case"
    case.mkdir()
    video = case / "video.mp4"
    video.touch()
    (case / "labels.json").write_text(
        '[{"start":1,"end":2,"type":"red_card"}]', encoding="utf-8"
    )
    found = [Segment(0, 3, 1, "found")]
    goals = [Segment(0, 3, 1, "goals")]
    tagged = [Segment(0, 3, 1, "incidents")]
    saved = [Segment(0, 3, 1, "final", "red_card", 0.5)]
    calls = []
    monkeypatch.setattr(evaluate.detect, "find_highlights", lambda value: found)
    monkeypatch.setattr(
        evaluate.scoreboard,
        "tag_goals",
        lambda value, segments: calls.append(("goals", value, segments)) or goals,
    )
    monkeypatch.setattr(
        evaluate.incidents,
        "tag_incidents",
        lambda value, segments: calls.append(("incidents", value, segments))
        or tagged,
    )
    monkeypatch.setattr(
        evaluate.audio_cues,
        "tag_saves",
        lambda value, segments: calls.append(("saves", value, segments)) or saved,
    )

    report = evaluate.evaluate_dir(tmp_path)

    assert calls == [
        ("goals", video, found),
        ("incidents", video, goals),
        ("saves", video, tagged),
    ]
    assert calls[1][2] is goals
    assert calls[2][2] is tagged
    assert report["per_event"]["red_card"] == {
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }


@pytest.fixture(scope="module")
def t015_eval_set(tmp_path_factory, require_ffmpeg):
    build_path = Path(__file__).parent / "fixtures" / "eval" / "build.py"
    spec = importlib.util.spec_from_file_location("t015_eval_build", build_path)
    assert spec is not None and spec.loader is not None
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    root = tmp_path_factory.mktemp("t015_eval")
    build.build_all(root)
    return root, build


def test_sample_frames_red_closeup_on_built_cards(t015_eval_set):
    root, _build = t015_eval_set
    video = root / "cards" / "video.mp4"

    closeup = incidents.red_share(incidents.sample_frames(video, 24.0, 4.0))
    play = incidents.red_share(incidents.sample_frames(video, 0.0, 4.0))

    assert 7 <= len(closeup) <= 9
    assert (closeup >= 0.5).all()
    assert len(play) > 0
    assert (play <= 0.05).all()


def test_fixture_incidents_tagged_with_local_frame_sampling(
    t015_eval_set, monkeypatch
):
    root, build = t015_eval_set
    expected_calls = {"cards": 3, "controversy": 2, "goals_saves": 0, "mixed": 1}
    real_sample = incidents.sample_frames
    calls = []

    def spy(video, start, duration):
        calls.append((start, duration))
        return real_sample(video, start, duration)

    monkeypatch.setattr(incidents, "sample_frames", spy)
    for name, match in build.MATCHES.items():
        video = root / name / "video.mp4"
        assert scoreboard.board_reverts(video) == []
        goals = scoreboard.tag_goals(video, detect.find_highlights(video))
        calls.clear()
        segments = incidents.tag_incidents(video, goals)

        assert len(segments) == len(goals)
        assert [(s.start, s.end, s.score) for s in segments] == [
            (s.start, s.end, s.score) for s in goals
        ]
        for before, after in zip(goals, segments):
            if before.event == "goal":
                assert after == before

        assert len(calls) == expected_calls[name]
        incident_t0 = [
            t0
            for kind, t0, *_ in match["events"]
            if kind in ("red_card", "controversy")
        ]
        for start, duration in calls:
            assert duration == 15.0
            assert any(abs(start - (t0 + 1)) <= 0.3 for t0 in incident_t0)

        labels = evaluate.load_labels(root / name / "labels.json")
        paired = {
            label_index: segments[segment_index]
            for segment_index, label_index in evaluate.match_segments(
                segments, labels
            )
        }
        for index, label in enumerate(labels):
            if label.type == "red_card":
                assert paired[index].event == "red_card"
                assert paired[index].event_confidence == 0.5
            elif label.type == "controversy":
                assert paired[index].event == "controversy"
                assert paired[index].event_confidence == 0.4
            elif label.type in ("goal", "save") and index in paired:
                assert paired[index].event not in ("red_card", "controversy")


def test_eval_incident_gate_and_unchanged_metrics(t015_eval_set):
    root, _build = t015_eval_set
    report = evaluate.evaluate_dir(root)
    perfect = {"precision": 1.0, "recall": 1.0, "f1": 1.0}

    assert report["per_event"]["red_card"] == perfect
    assert report["per_event"]["controversy"] == perfect
    assert report["per_event"]["goal"] == perfect
    assert report["per_event"]["save"]["precision"] >= 0.8
    assert report["per_event"]["save"]["recall"] >= 0.8
    assert report["event_accuracy"] == 1.0
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
            "ffmpeg", "-v", "error", "-nostdin", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=25:duration=5400",
            "-f", "lavfi", "-i", "anoisesrc=amplitude=0.02:sample_rate=16000:duration=5400",
            "-c:v", "mpeg4", "-q:v", "5", "-c:a", "aac", "-shortest", str(video),
        ],
        check=True,
    )
    real_board_changes = scoreboard.board_changes

    def force_audio_path(value):
        changes = real_board_changes(value)
        return [] if changes is None else changes

    monkeypatch.setattr(scoreboard, "board_changes", force_audio_path)

    started = time.perf_counter()
    candidates = detect.find_highlights(video, top=None)
    goals = scoreboard.tag_goals(video, candidates)
    tagged = incidents.tag_incidents(video, goals)
    audio_cues.tag_saves(video, tagged)
    elapsed = time.perf_counter() - started

    print(f"budget: {elapsed:.2f}s for 5400s")
    assert elapsed < 600


def test_readme_records_t015_invariants():
    root = Path(__file__).parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    marker = "Kết quả sau T-015"
    assert marker in readme
    after = readme.split(marker, 1)[1]
    block = re.search(r"```json\n([^\n]+)\n```", after)
    assert block is not None
    report = json.loads(block.group(1))
    per_event = report["per_event"]
    assert per_event["red_card"]["recall"] >= 0.6667
    assert per_event["controversy"]["recall"] >= 0.6667
    assert per_event["goal"]["recall"] == 1.0
    assert per_event["save"]["recall"] >= 0.8
    assert report["f1"] >= 0.8421
    for word in ("data/eval/", "tổng hợp", "[vision]"):
        assert word in after
    for older in ("Baseline đo trong T-011", "Kết quả sau T-013", "Kết quả sau T-014"):
        assert older in readme
        assert readme.index(older) < readme.index(marker)

    specs = root / "docs/superpowers/specs"
    for name in (
        "2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md",
        "2026-11-23-t-014-tag-saves-using-whistle-detection-and-design.md",
    ):
        assert "(updated by T-015" in (specs / name).read_text(encoding="utf-8")
