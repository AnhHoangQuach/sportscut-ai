"""Independent acceptance tests for T-015 red-card and controversy tagging.

Written by the Tester from the T-015 acceptance criteria (AC1-AC16), not from
the developer's tests.
"""

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

from sportscut import detect, evaluate, media, pipeline
from sportscut.events import audio_cues, incidents, scoreboard
from sportscut.media import MediaError
from sportscut.models import Segment


ROOT = Path(__file__).parents[1]
BUILD_PATH = ROOT / "tests/fixtures/eval/build.py"
RATE = 16_000
RED = (200, 20, 20)
GREEN = (40, 140, 60)
BOX = (2, 2, 30, 14)


def _git(*args):
    return subprocess.run(
        ["/usr/bin/git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


def _base():
    return _git("merge-base", "main", "HEAD").strip()


def _load_builder():
    spec = importlib.util.spec_from_file_location("t015_acceptance_build", BUILD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def t015_eval_set(tmp_path_factory, require_ffmpeg):
    root = tmp_path_factory.mktemp("t015_acceptance_eval")
    builder = _load_builder()
    videos = builder.build_all(root)
    return root, builder, videos


def _frames(*states):
    """states: (array, count) pairs -> stacked (n, 30, 160) uint8 frames."""
    return np.concatenate([np.repeat(state[None], count, axis=0) for state, count in states])


def _board_states():
    a = np.zeros((30, 160), np.uint8)
    b = a.copy()
    b[4:14, 5:11] = 255
    c = a.copy()
    c[4:14, 21:27] = 255
    return a, b, c


def _filled(colour, n=1):
    frames = np.zeros((n, 90, 160, 3), np.uint8)
    frames[...] = colour
    return frames


def _time(start, end):
    return np.arange(round(start * RATE), round(end * RATE)) / RATE


def _add(sig, start, end, amplitude, freq):
    a, b = round(start * RATE), round(end * RATE)
    sig[a:b] += amplitude * np.sin(2 * np.pi * freq * _time(start, end))


def _boo_signal():
    sig = 0.02 * np.sin(2 * np.pi * 1000 * _time(0, 120))
    _add(sig, 63, 93, 0.08, 100)
    return sig


def _ac7_signal():
    sig = 0.02 * np.sin(2 * np.pi * 1000 * _time(0, 120))
    for start, end in ((21, 33), (61, 97)):
        sig[round(start * RATE):round(end * RATE)] *= 0.25
    _add(sig, 63, 93, 0.08, 100)
    for start in (20, 60, 105):
        _add(sig, start, start + 1, 0.3, 3000)
    return sig


class _Stubs:
    def __init__(self, monkeypatch, sig, red_starts=(21.0,), red_count=4, reverts=()):
        self.audio_calls = 0
        self.revert_calls = 0
        self.frame_calls = []
        self.sig = sig
        self.red_starts = red_starts
        self.red_count = red_count
        self.reverts = list(reverts)
        monkeypatch.setattr(incidents, "extract_audio", self.extract_audio)
        monkeypatch.setattr(incidents, "sample_frames", self.sample_frames)
        monkeypatch.setattr(scoreboard, "board_reverts", self.board_reverts)

    def extract_audio(self, video, *args, **kwargs):
        self.audio_calls += 1
        return self.sig

    def board_reverts(self, video):
        self.revert_calls += 1
        return list(self.reverts)

    def sample_frames(self, video, start, duration):
        self.frame_calls.append((video, start, duration))
        if start in self.red_starts:
            red = _filled(RED, self.red_count)
            return np.concatenate([red, _filled(GREEN, 4 - self.red_count)])
        return _filled(GREEN, 4)


# AC1 -----------------------------------------------------------------------

def test_ac1_find_reverts_cases_gap_limit_and_short_inputs():
    a, b, c = _board_states()
    case_a = _frames((a, 10), (b, 10), (a, 20))
    assert scoreboard.score_changes(case_a, BOX) == [10.0, 20.0]
    assert scoreboard.find_reverts(case_a, BOX, [10.0, 20.0]) == [(10.0, 20.0)]
    case_b = _frames((a, 10), (b, 10), (c, 20))
    assert scoreboard.find_reverts(case_b, BOX, [10.0, 20.0]) == []
    case_c = _frames((a, 10), (b, 181), (a, 9))
    assert scoreboard.find_reverts(case_c, BOX, [10.0, 191.0]) == []
    case_d = _frames((a, 10), (b, 180), (a, 10))
    assert scoreboard.find_reverts(case_d, BOX, [10.0, 190.0]) == [(10.0, 190.0)]
    assert scoreboard.find_reverts(case_a, BOX, []) == []
    assert scoreboard.find_reverts(case_a, BOX, [10.0]) == []


def test_ac1_find_reverts_sorts_changes_and_returns_time_order():
    a, b, _c = _board_states()
    frames = _frames((a, 10), (b, 10), (a, 20))
    assert scoreboard.find_reverts(frames, BOX, [20.0, 10.0]) == [(10.0, 20.0)]
    assert scoreboard.REVERT_MAX == 180.0


# AC2 -----------------------------------------------------------------------

def test_ac2_board_reverts_composes_helpers_in_order(monkeypatch):
    calls = []
    frames = object()
    box = (1, 2, 3, 4)
    changes = [5.0, 9.0]
    reverts = [(5.0, 9.0)]
    monkeypatch.setattr(scoreboard, "sample_top_band", lambda v: calls.append(("sample", v)) or frames)
    monkeypatch.setattr(scoreboard, "find_box", lambda f: calls.append(("box", f)) or box)
    monkeypatch.setattr(scoreboard, "score_changes", lambda f, b: calls.append(("changes", f, b)) or changes)
    monkeypatch.setattr(
        scoreboard, "find_reverts", lambda f, b, c: calls.append(("reverts", f, b, c)) or reverts
    )
    assert scoreboard.board_reverts("m.mp4") is reverts
    assert [call[0] for call in calls] == ["sample", "box", "changes", "reverts"]
    assert calls[0][1] == "m.mp4"
    assert calls[1][1] is frames
    assert calls[2][1] is frames and calls[2][2] is box
    assert calls[3][1] is frames and calls[3][2] is box and calls[3][3] is changes


def test_ac2_board_reverts_without_box_skips_changes_and_reverts(monkeypatch):
    calls = []
    monkeypatch.setattr(scoreboard, "sample_top_band", lambda v: np.zeros((3, 30, 160), np.uint8))
    monkeypatch.setattr(scoreboard, "find_box", lambda f: None)
    monkeypatch.setattr(scoreboard, "score_changes", lambda *a: calls.append("changes"))
    monkeypatch.setattr(scoreboard, "find_reverts", lambda *a: calls.append("reverts"))
    assert scoreboard.board_reverts("m.mp4") == []
    assert calls == []


# AC3 -----------------------------------------------------------------------

def test_ac3_red_share_centre_crop_and_pixel_thresholds():
    frames = _filled(RED, 3)
    frames[1] = GREEN
    frames[2, 22:67, 40:120] = GREEN
    shares = incidents.red_share(frames)
    assert shares.dtype == np.float64
    assert shares.tolist() == [1.0, 0.0, 0.0]

    half = _filled(GREEN)
    half[0, 22:44, 40:120] = RED
    assert incidents.red_share(half)[0] == pytest.approx(22 / 45)
    assert incidents.red_share(_filled((150, 60, 60))).tolist() == [1.0]
    for colour in ((149, 60, 60), (150, 61, 60), (150, 60, 61)):
        assert incidents.red_share(_filled(colour)).tolist() == [0.0]
    empty = incidents.red_share(np.zeros((0, 90, 160, 3), np.uint8))
    assert empty.dtype == np.float64 and empty.shape == (0,)


def test_ac3_red_share_ignores_red_outside_the_centre():
    frame = _filled(RED)
    frame[0, 22:67, 40:120] = (0, 0, 0)
    assert incidents.red_share(frame).tolist() == [0.0]


# AC4 -----------------------------------------------------------------------

def test_ac4_booing_seconds_counts_low_band_windows():
    sig = _boo_signal()
    assert incidents.booing_seconds(sig, 61.0, 97.0) == pytest.approx(30.0)
    assert incidents.booing_seconds(sig, 61.0, 70.0) == pytest.approx(7.0)
    assert incidents.booing_seconds(sig, 0.0, 60.0) == 0.0
    assert incidents.booing_seconds(sig, 200.0, 210.0) == 0.0
    assert incidents.booing_seconds(sig, 70.0, 65.0) == 0.0


def test_ac4_booing_seconds_edge_inputs():
    assert incidents.booing_seconds(np.zeros(0, np.float32), 0.0, 10.0) == 0.0
    assert incidents.booing_seconds(np.zeros(100, np.float32), 0.0, 10.0) == 0.0


# AC5 -----------------------------------------------------------------------

@pytest.mark.parametrize(
    ("stoppage", "booing", "red_frames", "expected"),
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
def test_ac5_classify_table(stoppage, booing, red_frames, expected):
    assert incidents.classify(stoppage, booing, red_frames) == expected


# AC6 -----------------------------------------------------------------------

def test_ac6_sample_frames_exact_command_and_partial_frame_drop(tmp_path, monkeypatch, require_ffmpeg):
    video = tmp_path / "m.mp4"
    video.write_bytes(b"x")
    calls = []
    frame = 90 * 160 * 3

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout=bytes(frame * 2 + frame // 2), stderr=b"")

    monkeypatch.setattr(incidents.subprocess, "run", run)
    frames = incidents.sample_frames(video, 24.0, 4.0)
    assert calls == [(
        [media.find_tool("ffmpeg"), "-v", "error", "-nostdin", "-ss", "24.000", "-i", str(video),
         "-t", "4.000", "-an", "-vf", "fps=2,scale=160:90", "-f", "rawvideo", "-pix_fmt",
         "rgb24", "pipe:1"],
        {"capture_output": True, "check": False},
    )]
    assert frames.dtype == np.uint8
    assert frames.shape == (2, 90, 160, 3)


def test_ac6_sample_frames_real_black_and_white(synthetic_video):
    black = incidents.sample_frames(synthetic_video, 0.5, 2.0)
    white = incidents.sample_frames(synthetic_video, 3.5, 2.0)
    assert 3 <= len(black) <= 5 and 3 <= len(white) <= 5
    assert all(frame.mean() <= 30 for frame in black)
    assert all(frame.mean() >= 225 for frame in white)


def test_ac6_sample_frames_missing_file_even_without_path(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    with pytest.raises(MediaError, match="^media file not found:"):
        incidents.sample_frames(tmp_path / "missing.mp4", 0.0, 1.0)


def test_ac6_sample_frames_non_media_file(tmp_path, require_ffmpeg):
    text = tmp_path / "notes.txt"
    text.write_text("not a video\n")
    with pytest.raises(MediaError, match="^ffmpeg failed for"):
        incidents.sample_frames(text, 0.0, 1.0)


def test_ac6_red_closeup_on_built_cards_match(t015_eval_set):
    root, _builder, _videos = t015_eval_set
    video = root / "cards" / "video.mp4"
    closeup = incidents.red_share(incidents.sample_frames(video, 24.0, 4.0))
    assert 7 <= len(closeup) <= 9
    assert all(value >= 0.5 for value in closeup)
    opening = incidents.red_share(incidents.sample_frames(video, 0.0, 4.0))
    assert len(opening) > 0
    assert all(value <= 0.05 for value in opening)


# AC7 -----------------------------------------------------------------------

def _ac7_segments():
    return [
        Segment(15, 27, 5, "a"),
        Segment(55, 67, 4, "b"),
        Segment(80, 92, 3, "c"),
        Segment(100, 112, 2, "d"),
        Segment(56, 68, 6, "g", "goal", 0.9),
        Segment(14, 26, 1, "s", "save", 0.6),
    ]


def test_ac7_signal_preconditions():
    sig = _ac7_signal()
    assert audio_cues.find_whistles(sig) == [(20.0, 21.0), (60.0, 61.0), (105.0, 106.0)]
    assert audio_cues.stoppage_after(sig, 21.0) == pytest.approx(12.0)
    assert audio_cues.stoppage_after(sig, 61.0) == pytest.approx(36.0)


def test_ac7_tag_incidents_audio_rules_and_frame_locality(monkeypatch):
    stubs = _Stubs(monkeypatch, _ac7_signal())
    segments = _ac7_segments()
    snapshot = list(segments)
    reprs = [repr(s) for s in segments]
    a, b, c, d, g, s = segments
    result = incidents.tag_incidents("m.mp4", segments)

    assert result == [
        Segment(15, 27, 5, "a; whistle at 20s, stoppage 12s, red close-up", "red_card", 0.5),
        Segment(55, 67, 4, "b; whistle at 60s, stoppage 36s, booing 30s", "controversy", 0.4),
        c, d, g, s,
    ]
    assert result is not segments
    assert segments == snapshot and [repr(x) for x in segments] == reprs
    assert stubs.frame_calls == [("m.mp4", 21.0, 15.0), ("m.mp4", 61.0, 15.0)]
    assert stubs.audio_calls == 1
    assert stubs.revert_calls == 1


# AC8 -----------------------------------------------------------------------

def test_ac8_red_card_beats_controversy(monkeypatch):
    _Stubs(monkeypatch, _ac7_signal(), red_starts=(21.0, 61.0))
    result = incidents.tag_incidents("m.mp4", _ac7_segments())
    assert result[1] == Segment(
        55, 67, 4, "b; whistle at 60s, stoppage 36s, red close-up", "red_card", 0.5
    )


def test_ac8_one_red_frame_is_not_enough(monkeypatch):
    _Stubs(monkeypatch, _ac7_signal(), red_count=1)
    segments = _ac7_segments()
    result = incidents.tag_incidents("m.mp4", segments)
    assert result[0] == segments[0]


def test_ac8_reverted_goal_becomes_controversy(monkeypatch):
    stubs = _Stubs(monkeypatch, _ac7_signal(), reverts=[(45.0, 150.0)])
    g1 = Segment(40, 52, 5, "audio peak z=5.0; scoreboard change at 45s", "goal", 0.9)
    g2 = Segment(90, 120, 3, "scoreboard change at 150s", "goal", 0.6)
    g3 = Segment(10, 22, 7, "audio peak z=7.0; scoreboard change at 13s", "goal", 0.9)
    g4 = Segment(60, 72, 4, "audio peak z=4.0; sustained roar 8s", "goal", 0.4)
    suffix = "; scoreboard change at 45s reverted at 150s"
    result = incidents.tag_incidents("m.mp4", [g1, g2, g3, g4])
    assert result == [
        Segment(40, 52, 5, g1.reason + suffix, "controversy", 0.5),
        Segment(90, 120, 3, g2.reason + suffix, "controversy", 0.5),
        g3,
        g4,
    ]
    assert stubs.audio_calls == 0
    assert stubs.frame_calls == []
    assert stubs.revert_calls == 1


def test_ac8_goal_matching_both_reverts_is_relabelled_once(monkeypatch):
    _Stubs(monkeypatch, _ac7_signal(), reverts=[(45.0, 150.0), (150.0, 170.0)])
    goal = Segment(90, 120, 3, "scoreboard change at 150s", "goal", 0.6)
    result = incidents.tag_incidents("m.mp4", [goal])
    assert result == [
        Segment(90, 120, 3, "scoreboard change at 150s; scoreboard change at 45s reverted at 150s",
                "controversy", 0.5)
    ]


# AC9 -----------------------------------------------------------------------

def test_ac9_nothing_to_check_decodes_nothing(monkeypatch):
    stubs = _Stubs(monkeypatch, _ac7_signal())
    assert incidents.tag_incidents("m.mp4", []) == []
    tagged = [Segment(1, 5, 1, "s", "save", 0.6), Segment(6, 9, 1, "r", "red_card", 0.5)]
    assert incidents.tag_incidents("m.mp4", tagged) == tagged
    assert (stubs.audio_calls, stubs.revert_calls, stubs.frame_calls) == (0, 0, [])


def test_ac9_real_noise_videos_unchanged(burst_video, synthetic_video):
    segs = [Segment(10, 22, 3, "x"), Segment(40, 52, 2, "y", "goal", 0.9)]
    assert incidents.tag_incidents(burst_video, segs) == segs
    short = [Segment(0, 4, 1, "z")]
    assert incidents.tag_incidents(synthetic_video, short) == short


# AC10 ----------------------------------------------------------------------

def _pipeline_spies(monkeypatch, calls):
    found = [Segment(1, 5, 1, "found")]
    goals = [Segment(1, 5, 1, "goal", "goal", 0.9)]
    tagged = [Segment(1, 5, 1, "goal", "goal", 0.9)]
    saves = [Segment(6, 10, 2, "save", "save", 0.6)]
    monkeypatch.setattr(pipeline, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(pipeline, "has_audio", lambda video: True)
    monkeypatch.setattr(pipeline, "find_highlights", lambda v, **k: calls.append(("find", v)) or found)
    monkeypatch.setattr(pipeline, "tag_goals", lambda v, s, **k: calls.append(("goals", v, s)) or goals)
    monkeypatch.setattr(pipeline, "tag_incidents", lambda v, s: calls.append(("incidents", v, s)) or tagged)
    monkeypatch.setattr(pipeline, "tag_saves", lambda v, s: calls.append(("saves", v, s)) or saves)
    monkeypatch.setattr(pipeline, "select_segments", lambda s, **k: calls.append(("select", s)) or s)

    def export(_video, _segments, out):
        Path(out).mkdir(parents=True, exist_ok=True)
        (Path(out) / pipeline.MANIFEST_NAME).write_text("[]")

    monkeypatch.setattr(pipeline, "export_clips", export)
    return found, goals, tagged, saves


def test_ac10_pipeline_runs_incidents_between_goals_and_saves(tmp_path, monkeypatch):
    calls = []
    found, goals, tagged, saves = _pipeline_spies(monkeypatch, calls)
    pipeline.run("match.mp4", tmp_path / "out", top=2, min_len=4, max_len=6)
    assert [call[0] for call in calls] == ["find", "goals", "incidents", "saves", "select"]
    assert calls[1][2] is found
    assert calls[2][1] == "match.mp4" and calls[2][2] is goals
    assert calls[3][2] is tagged
    assert calls[4][1] is saves


def test_ac10_pipeline_wraps_incident_media_error(tmp_path, monkeypatch):
    _pipeline_spies(monkeypatch, [])

    def boom(_video, _segments):
        raise MediaError("incident frames failed")

    monkeypatch.setattr(pipeline, "tag_incidents", boom)
    with pytest.raises(pipeline.PipelineError, match="^incident frames failed$"):
        pipeline.run("match.mp4", tmp_path / "out")


# AC11 ----------------------------------------------------------------------

def test_ac11_evaluate_dir_chains_goals_incidents_saves(tmp_path, monkeypatch):
    videos = []
    for name in ("b_case", "a_case"):
        case = tmp_path / name
        case.mkdir()
        (case / "video.mp4").write_bytes(b"")
        (case / "labels.json").write_text('[{"start": 1, "end": 4, "type": "red_card"}]')
        videos.append(case / "video.mp4")
    calls = []
    outputs = {}

    def find(video):
        calls.append(("find", video))
        return [Segment(0, 5, 1, "found")]

    def goals(video, segments):
        calls.append(("goals", video))
        outputs[("goals", video)] = [Segment(0, 5, 1, "goals")]
        return outputs[("goals", video)]

    def tag_incidents(video, segments):
        assert segments is outputs[("goals", video)]
        calls.append(("incidents", video))
        outputs[("incidents", video)] = [Segment(0, 5, 1, "inc", "red_card", 0.5)]
        return outputs[("incidents", video)]

    def saves(video, segments):
        assert segments is outputs[("incidents", video)]
        calls.append(("saves", video))
        return segments

    monkeypatch.setattr(detect, "find_highlights", find)
    monkeypatch.setattr(scoreboard, "tag_goals", goals)
    monkeypatch.setattr(incidents, "tag_incidents", tag_incidents)
    monkeypatch.setattr(audio_cues, "tag_saves", saves)
    report = evaluate.evaluate_dir(tmp_path)
    assert [c[0] for c in calls] == ["find", "goals", "incidents", "saves"] * 2
    assert sorted({c[1] for c in calls if c[0] == "incidents"}) == sorted(videos)
    assert report["per_event"]["red_card"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}


STUB_FILES = {
    "tests/test_evaluate.py": ["test_evaluate_dir_validates_then_aggregates",
                               "test_evaluate_dir_ignores_hidden_video_metadata"],
    "tests/test_eval_fixtures.py": ["test_eval_all_other_baseline_shape"],
    "tests/test_eval_fixtures_acceptance.py": ["test_acceptance_eval_oracles"],
    "tests/test_t010_acceptance.py": ["test_t010_ac9_sums_cases_in_sorted_order"],
    "tests/test_audio_cues.py": ["test_pipeline_calls_tag_saves_after_tag_goals_and_wraps_media_error",
                                "test_evaluate_dir_runs_tag_saves_on_tag_goals_output"],
    "tests/test_t014_acceptance.py": ["test_ac8_pipeline_orders_classifiers_and_wraps_save_media_errors",
                                      "test_ac9_evaluate_scores_tag_saves_output_after_tag_goals"],
}
STUB_RE = re.compile(
    r'^\s*monkeypatch\.setattr\((incidents|pipeline), "tag_incidents", '
    r"lambda _video, segments: segments\)$"
)
IMPORT_RE = re.compile(r"^\s*from sportscut\.events import [a-z_, ]+$")


# Updated by T-028: T-015 is merged (squash commit dc06807, parent 0c613ee), so
# merge-base(main, HEAD) no longer shows its stub lines on any later branch.
# Pin the diff to T-015's own change; the current-file checks below still run.
T015_PARENT = "0c613ee27e00a932c64a2da6c43c10f4a7ee14c2"
T015_COMMIT = "dc0680766116b53ae10049c6078750054c05ec6d"


@pytest.mark.parametrize("path", sorted(STUB_FILES))
def test_ac11_existing_tests_only_gain_a_pass_through_stub(path):
    diff = _git("diff", "-U0", T015_PARENT, T015_COMMIT, "--", path).splitlines()
    removed = [l[1:] for l in diff if l.startswith("-") and not l.startswith("---")]
    added = [l[1:] for l in diff if l.startswith("+") and not l.startswith("+++")]
    assert all(IMPORT_RE.match(line) for line in removed), removed
    stubs = [line for line in added if STUB_RE.match(line)]
    others = [line for line in added if not STUB_RE.match(line)]
    assert all(IMPORT_RE.match(line) and "incidents" in line for line in others), others
    assert len(others) - len(removed) <= 1
    tree = ast.parse((ROOT / path).read_text())
    source = (ROOT / path).read_text()
    holders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            body = ast.get_source_segment(source, node)
            holders += [node.name] * sum(1 for line in body.splitlines() if STUB_RE.match(line))
    assert sorted(holders) == sorted(STUB_FILES[path])
    assert len(stubs) == len(STUB_FILES[path])


# AC12 / AC13 ---------------------------------------------------------------

def test_ac12_fixture_incidents_tagged_with_local_frame_sampling(t015_eval_set, monkeypatch):
    _root, builder, videos = t015_eval_set
    real = incidents.sample_frames
    calls = []

    def spy(video, start, duration):
        calls.append((Path(video).parent.name, start, duration))
        return real(video, start, duration)

    monkeypatch.setattr(incidents, "sample_frames", spy)
    expected_calls = {"cards": 3, "controversy": 2, "goals_saves": 0, "mixed": 1}
    for video in videos:
        name = video.parent.name
        assert scoreboard.board_reverts(video) == []
        goals = scoreboard.tag_goals(video, detect.find_highlights(video))
        before = len(calls)
        segs = incidents.tag_incidents(video, goals)
        mine = calls[before:]
        assert len(mine) == expected_calls[name], (name, mine)
        incident_starts = [t0 + 1 for kind, t0, *_ in builder.MATCHES[name]["events"]
                           if kind in ("red_card", "controversy")]
        for _name, start, duration in mine:
            assert duration == 15.0
            assert any(abs(start - t) <= 0.3 for t in incident_starts), (name, start)
        assert len(segs) == len(goals)
        assert [(s.start, s.end, s.score) for s in segs] == [(g.start, g.end, g.score) for g in goals]
        for seg, goal in zip(segs, goals):
            if goal.event == "goal":
                assert seg == goal
        labels = evaluate.load_labels(video.parent / "labels.json")
        paired = dict((j, i) for i, j in evaluate.match_segments(segs, labels))
        for j, label in enumerate(labels):
            seg = segs[paired[j]] if j in paired else None
            if label.type == "red_card":
                assert seg is not None and (seg.event, seg.event_confidence) == ("red_card", 0.5), (name, label)
            elif label.type == "controversy":
                assert seg is not None and (seg.event, seg.event_confidence) == ("controversy", 0.4), (name, label)
            elif label.type in ("goal", "save") and seg is not None:
                assert seg.event not in ("red_card", "controversy"), (name, label, seg)


def test_ac13_eval_gate_and_unchanged_overall_metrics(t015_eval_set):
    root, _builder, _videos = t015_eval_set
    report = evaluate.evaluate_dir(root)
    perfect = {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert report["per_event"]["red_card"] == perfect
    assert report["per_event"]["controversy"] == perfect
    assert report["per_event"]["goal"] == perfect
    assert report["per_event"]["save"]["precision"] >= 0.8
    assert report["per_event"]["save"]["recall"] >= 0.8
    assert report["event_accuracy"] == 1.0
    assert (report["f1"], report["precision"], report["recall"], report["precision_at_5"]) == (
        0.8421, 0.7273, 1.0, 0.8889,
    )
    result = subprocess.run(
        [sys.executable, "-m", "sportscut", "eval", str(root), "--json"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == report


# AC14 ----------------------------------------------------------------------

def test_ac14_budget_test_is_opt_in_with_exact_skip_reason():
    env = {k: v for k, v in os.environ.items() if k != "SPORTSCUT_PERF"}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider",
         "tests/test_incidents.py::test_ninety_minute_budget"],
        cwd=ROOT, capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stdout
    assert "1 skipped" in result.stdout
    assert "set SPORTSCUT_PERF=1 to run the 90-minute budget check" in result.stdout


def test_ac14_budget_test_contract():
    source = (ROOT / "tests/test_incidents.py").read_text()
    tree = ast.parse(source)
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "test_ninety_minute_budget")
    body = ast.get_source_segment(source, node)
    for needle in ("testsrc2=size=640x360:rate=25:duration=5400", "anoisesrc", "amplitude=0.02",
                   "16000", "mpeg4", "aac", "board_changes", "find_highlights", "tag_goals",
                   "tag_incidents", "tag_saves", "budget:", "for 5400s", "< 600"):
        assert needle in body, needle


# AC15 ----------------------------------------------------------------------

T015_MARKER = "Kết quả sau T-015"


def test_ac15_readme_records_t015_invariants():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert T015_MARKER in readme
    after = readme.split(T015_MARKER, 1)[1]
    match = re.search(r"```json\n([^\n]*)\n```", after)
    assert match is not None
    report = json.loads(match.group(1))
    per = report["per_event"]
    assert per["red_card"]["recall"] >= 0.6667
    assert per["controversy"]["recall"] >= 0.6667
    assert per["goal"]["recall"] == 1.0
    assert per["save"]["recall"] >= 0.8
    assert report["f1"] >= 0.8421
    for word in ("data/eval/", "tổng hợp", "[vision]"):
        assert word in after, word
    marker_line = next(line for line in readme.splitlines() if T015_MARKER in line)
    assert marker_line.startswith(
        "Kết quả sau T-015 (thẻ đỏ = còi + dừng trận ≥ 8 giây + cận cảnh đỏ giữa khung hình; "
        "tranh cãi = còi + dừng trận ≥ 30 giây + tiếng la ó ≥ 10 giây, hoặc tỷ số bị hoàn lại):"
    )


def test_ac15_older_readme_blocks_unchanged_and_specs_updated():
    diff = _git("diff", "-U0", _base(), "--", "README.md").splitlines()
    removed = [l for l in diff if l.startswith("-") and not l.startswith("---")]
    assert removed == []
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    old = _git("show", f"{_base()}:README.md")
    for marker in ("Baseline đo trong T-011", "Kết quả sau T-013", "Kết quả sau T-014"):
        assert marker in old and marker in readme
    assert readme.index("Kết quả sau T-014") < readme.index(T015_MARKER)
    specs = ROOT / "docs/superpowers/specs"
    for name in ("2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md",
                 "2026-11-23-t-014-tag-saves-using-whistle-detection-and-design.md"):
        assert "(updated by T-015" in (specs / name).read_text(encoding="utf-8"), name


# AC16 ----------------------------------------------------------------------

FORBIDDEN = {
    "tests/conftest.py", "pyproject.toml", "sportscut/models.py", "sportscut/ranking.py",
    "sportscut/export.py", "sportscut/events/audio_cues.py",
    "tests/fixtures/eval/build.py",
}


def test_ac16_diff_scope_against_merge_base():
    changed = set(_git("diff", "--name-only", _base()).splitlines())
    changed |= set(_git("ls-files", "--others", "--exclude-standard").splitlines())
    assert changed.isdisjoint(FORBIDDEN), changed & FORBIDDEN
    assert not any(p.startswith("tests/fixtures/eval/") and p.endswith("/labels.json") for p in changed)
    assert not any(p.split("/")[0] in ("agent-office", ".agent-office") for p in changed)


def test_ac16_incidents_imports_only_stdlib_numpy_and_sportscut():
    tree = ast.parse((ROOT / "sportscut/events/incidents.py").read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            roots.add(node.module.split(".")[0])
    allowed_third_party = {"numpy", "sportscut"}
    for name in roots - allowed_third_party:
        assert name in sys.stdlib_module_names, name
