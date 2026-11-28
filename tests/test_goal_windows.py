"""T-058 unit tests: scoreboard.shape_goals gives each roar goal a build-up-to-celebration window."""
import copy

import numpy as np
import pytest

from sportscut.events import scoreboard
from sportscut.models import Segment


def residual(*runs, n=200):
    r = np.zeros(n)
    for a, b in runs:
        r[a:b] = 10.0
    return r


def span(segment):
    return segment.start, segment.end


def test_reshapes_roar_goal_to_onset_window():  # unit 1 (AC1)
    for conf in (0.4, 0.9):
        goal = Segment(36, 48, 5.0, "r", "goal", conf)
        assert scoreboard.shape_goals([goal], residual((40, 48)), 200) == [
            Segment(28.0, 50.0, 5.0, "r", "goal", conf)
        ]


def test_clamp_keeps_ratio():  # unit 2 (AC2)
    goal, r = Segment(36, 48, 5.0, "r", "goal", 0.4), residual((40, 48))
    assert span(scoreboard.shape_goals([goal], r, 200, max_len=11)[0]) == (34.0, 45.0)
    out = scoreboard.shape_goals([goal], r, 200, min_len=30, max_len=30)[0]
    assert span(out) == (pytest.approx(40 - 30 * 12 / 22), pytest.approx(40 + 30 * 10 / 22))
    assert out.end - out.start == pytest.approx(30)


def test_window_stays_inside_media():  # unit 3 (AC3)
    goal = Segment(1, 13, 5, "r", "goal", 0.4)
    assert span(scoreboard.shape_goals([goal], residual((5, 13)), 200)[0]) == (0.0, 22.0)
    goal = Segment(48, 58, 5, "r", "goal", 0.4)
    assert span(scoreboard.shape_goals([goal], residual((52, 58), n=60), 60)[0]) == (38.0, 60.0)


def test_not_reshaped():  # unit 4 (AC4)
    board = Segment(30, 60, 3.0, "b", "goal", 0.6)
    assert scoreboard.shape_goals([board], residual((40, 48)), 200) == [board]
    goal = Segment(36, 48, 5.0, "r", "goal", 0.4)
    for r in (np.zeros(200), residual((40, 45))):
        assert scoreboard.shape_goals([goal], r, 200) == [goal]
    other = Segment(36, 48, 5.0, "o")
    assert scoreboard.shape_goals([other], residual((40, 48)), 200) == [other]


def test_roar_values_unchanged():  # unit 5
    assert scoreboard.roar(residual((40, 48)), 36, 48) == (40.5, 8)
    assert scoreboard.roar(np.zeros(50), 10, 20) == (10.5, 0)
    assert scoreboard.roar(np.zeros(50), 60, 70) == (60.0, 0)


def test_overlapping_goals_merge():  # unit 6 (AC5)
    r = residual((40, 48), (55, 62))
    a = Segment(36, 48, 5, "a", "goal", 0.4)
    b = Segment(51, 63, 7, "b", "goal", 0.9)
    assert scoreboard.shape_goals([a, b], r, 200) == [Segment(28.0, 65.0, 7, "b", "goal", 0.9)]
    board = Segment(45, 75, 3.0, "board", "goal", 0.6)
    assert scoreboard.shape_goals([a, board], residual((40, 48)), 200) == [
        Segment(28.0, 75.0, 5, "a", "goal", 0.6)
    ]
    touching = Segment(50, 80, 3.0, "board", "goal", 0.6)
    assert scoreboard.shape_goals([a, touching], residual((40, 48)), 200) == [
        Segment(28.0, 50.0, 5, "a", "goal", 0.4),
        touching,
    ]


def test_non_goals_overlapping_a_goal_are_dropped():  # unit 7 (AC6)
    goal = Segment(36, 48, 5.0, "r", "goal", 0.4)
    touch, far = Segment(50, 62, 4, "x"), Segment(70, 82, 4, "y")
    segments = [goal, Segment(45, 57, 9, "o"), Segment(20, 30, 3, "s", "save", 0.6), touch, far]
    assert scoreboard.shape_goals(segments, residual((40, 48)), 200) == [
        Segment(28.0, 50.0, 5.0, "r", "goal", 0.4),
        touch,
        far,
    ]


def test_input_not_mutated_and_output_sorted():  # unit 8 (AC6)
    segments = [Segment(70, 82, 4, "y"), Segment(36, 48, 5.0, "r", "goal", 0.4), Segment(5, 15, 1, "z")]
    before = copy.deepcopy(segments)
    out = scoreboard.shape_goals(segments, residual((40, 48)), 200)
    assert segments == before and out is not segments
    assert out == sorted(out, key=span)
    assert [s.reason for s in out] == ["z", "r", "y"]


def test_none_score_loses_to_scored_goal():  # unit 9 (AC5 tie rule)
    r = residual((40, 48), (55, 62))
    goals = [Segment(36, 48, None, "n", "goal", 0.9), Segment(51, 63, 1.0, "s", "goal", 0.4)]
    assert scoreboard.shape_goals(goals, r, 200) == [Segment(28.0, 65.0, 1.0, "s", "goal", 0.9)]


def test_tag_goals_ends_with_shape_goals(monkeypatch):  # unit 10 (AC7)
    resid, tagged, calls = np.zeros(30), [Segment(1, 12, 1.0, "m", "goal", 0.4)], []
    monkeypatch.setattr(scoreboard, "probe_duration", lambda video: 77.0)
    monkeypatch.setattr(scoreboard, "extract_audio", lambda video: "audio")
    monkeypatch.setattr(scoreboard, "loudness_residual", lambda audio: resid)
    monkeypatch.setattr(scoreboard, "board_changes", lambda video: None)
    monkeypatch.setattr(scoreboard, "match_goals", lambda *args: tagged)
    monkeypatch.setattr(scoreboard, "shape_goals", lambda *args: calls.append(args) or ["shaped"])
    assert scoreboard.tag_goals("v.mp4", [], 12, 28) == ["shaped"]
    assert len(calls) == 1
    assert calls[0][0] is tagged and calls[0][1] is resid and calls[0][2:] == (77.0, 12, 28)
