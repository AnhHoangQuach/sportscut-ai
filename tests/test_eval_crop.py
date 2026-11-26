import json
import math

import pytest

from sportscut import eval_crop


def write_labels(path, value):
    path.write_text(json.dumps(value))
    return path


def label(t=0.0, ball=(320.0, 100.0), players=()):
    return eval_crop.Label(t, ball, tuple(players))


def test_load_labels_sorts_and_accepts_sparse_optional_fields(tmp_path):
    path = write_labels(tmp_path / "labels.json", [
        {"t": 2, "ball": None},
        {"t": 0.5, "ball": [10, 20], "players": [[1, 2, 3, 4]]},
    ])
    assert eval_crop.load_labels(path) == [
        eval_crop.Label(0.5, (10.0, 20.0), ((1.0, 2.0, 3.0, 4.0),)),
        eval_crop.Label(2.0, None, ()),
    ]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({}, "top level must be a list"),
        ([], "no labels"),
        ([1], "[0] must be an object"),
        ([{"ball": None}], "[0].t must be a non-negative number"),
        ([{"t": True, "ball": None}], "[0].t must be a non-negative number"),
        ([{"t": "0", "ball": None}], "[0].t must be a non-negative number"),
        ([{"t": math.nan, "ball": None}], "[0].t must be a non-negative number"),
        ([{"t": -1, "ball": None}], "[0].t must be a non-negative number"),
        ([{"t": 0}], "[0].ball must be null or [x, y]"),
        ([{"t": 0, "ball": [1, 2, 3]}], "[0].ball must be null or [x, y]"),
        ([{"t": 0, "ball": [True, 2]}], "[0].ball must be null or [x, y]"),
        ([{"t": 0, "ball": [1, math.inf]}], "[0].ball must be null or [x, y]"),
        ([{"t": 0, "ball": None, "players": {}}], "[0].players must be a list"),
        ([{"t": 0, "ball": None, "players": [[1, 2, 0, 4]]}], "[0].players must be a list"),
        ([{"t": 0, "ball": None, "players": [[1, 2, 3, True]]}], "[0].players must be a list"),
    ],
)
def test_load_labels_rejects_malformed_entries(tmp_path, value, message):
    path = write_labels(tmp_path / "labels.json", value)
    with pytest.raises(ValueError) as exc:
        eval_crop.load_labels(path)
    assert str(exc.value).startswith(f"{path}: ")
    assert message in str(exc.value)


def test_load_labels_wraps_json_and_os_errors(tmp_path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[")
    for path in (invalid, tmp_path / "missing.json"):
        with pytest.raises(ValueError) as exc:
            eval_crop.load_labels(path)
        assert str(exc.value).startswith(f"{path}: ")


def test_score_clip_uses_inclusive_crop_edges_and_player_centres():
    labels = [
        label(0, (219, 0)),
        label(0.2, (421, 0)),
        label(0.4, (218.9, 0), ((410, 0, 20, 30),)),
    ]
    counts = eval_crop.score_clip(labels, [(0, 320)], 640, 202, 0.6)
    assert counts["ball_hits"] == 2
    assert counts["ball_total"] == 3
    assert counts["player_hits"] == counts["player_total"] == 1


def test_score_clip_interpolates_crop_center():
    counts = eval_crop.score_clip(
        [label(1, (320, 0))], [(0, 101), (2, 539)], 640, 202, 2.2
    )
    assert counts["ball_hits"] == counts["ball_total"] == 1


def test_score_clip_constant_plan_has_zero_jitter():
    counts = eval_crop.score_clip([], [(0, 320)], 640, 202, 0.8)
    assert counts["jerk_sum"] == 0.0
    assert eval_crop.metrics(counts, 0, 0)["jitter"] == 0.0


def test_score_clip_zigzag_jitter():
    counts = eval_crop.score_clip(
        [], [(0, 320), (0.2, 340), (0.4, 320), (0.6, 340)],
        640, 202, 0.8,
    )
    assert counts["jerk_n"] == 2
    assert eval_crop.metrics(counts, 0, 0)["jitter"] == round(40 / 640, 6)


def test_metrics_zero_denominators_and_key_order():
    counts = {
        "ball_hits": 0, "ball_total": 0,
        "player_hits": 0, "player_total": 0,
        "jerk_sum": 0.0, "jerk_n": 0,
    }
    report = eval_crop.metrics(counts, seconds=2, minutes=0.5)
    assert list(report) == [
        "ball_in_crop", "players_in_crop", "jitter", "seconds_per_min"
    ]
    assert report == {
        "ball_in_crop": None,
        "players_in_crop": None,
        "jitter": 0.0,
        "seconds_per_min": 4.0,
    }


@pytest.mark.parametrize(
    ("plan", "reason"),
    [
        ([], "empty"),
        ([1], "not (t, x) pairs"),
        ([(0, 320, 1)], "not (t, x) pairs"),
        ([(math.nan, 320)], "not (t, x) pairs"),
        ([(0, math.inf)], "not (t, x) pairs"),
        ([(0, 320), (0, 320)], "t not strictly increasing"),
        ([(0, 100)], "x outside the frame"),
        ([(0, 540)], "x outside the frame"),
    ],
)
def test_validate_plan_rejects_contract_violations(plan, reason):
    with pytest.raises(ValueError) as exc:
        eval_crop.validate_plan(plan, 640, 202, "case")
    assert str(exc.value) == f"plan_crop returned an invalid plan for case: {reason}"


def test_evaluate_dir_rejects_missing_or_empty_root(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match=f"not a directory: {missing}"):
        eval_crop.evaluate_dir(missing)
    with pytest.raises(ValueError, match="no eval-crop cases found"):
        eval_crop.evaluate_dir(tmp_path)


def test_evaluate_dir_validates_every_case_before_planning(tmp_path, monkeypatch):
    first = tmp_path / "a"
    first.mkdir()
    (first / "clip.mp4").touch()
    write_labels(first / "labels.json", [{"t": 0, "ball": [320, 0]}])
    second = tmp_path / "b"
    second.mkdir()
    write_labels(second / "labels.json", [{"t": 0, "ball": [320, 0]}])
    calls = []
    monkeypatch.setattr("sportscut.eval_crop.reframe.plan_crop", calls.append)
    with pytest.raises(ValueError, match="run python tests/fixtures/eval_crop/build.py"):
        eval_crop.evaluate_dir(tmp_path)
    assert calls == []


def test_evaluate_dir_rejects_bad_plan(tmp_path, monkeypatch):
    case = tmp_path / "case"
    case.mkdir()
    (case / "clip.mp4").touch()
    write_labels(case / "labels.json", [{"t": 0, "ball": [320, 0]}])
    monkeypatch.setattr("sportscut.eval_crop.media.probe_size", lambda path: (640, 360))
    monkeypatch.setattr("sportscut.eval_crop.media.probe_duration", lambda path: 1.0)
    monkeypatch.setattr("sportscut.eval_crop.reframe.plan_crop", lambda path: [])
    with pytest.raises(ValueError, match="invalid plan for case: empty"):
        eval_crop.evaluate_dir(tmp_path)


def test_evaluate_dir_micro_averages_and_sorts_per_clip(tmp_path, monkeypatch):
    values = {"b": [320, 320, 320], "a": [320, 10]}
    for name, xs in values.items():
        case = tmp_path / name
        case.mkdir()
        (case / "clip.mp4").touch()
        write_labels(case / "labels.json", [
            {"t": index * 0.2, "ball": [x, 0]}
            for index, x in enumerate(xs)
        ])
    monkeypatch.setattr("sportscut.eval_crop.media.probe_size", lambda path: (640, 360))
    monkeypatch.setattr("sportscut.eval_crop.media.probe_duration", lambda path: 1.0)
    monkeypatch.setattr(
        "sportscut.eval_crop.reframe.plan_crop", lambda path: [(0, 320)]
    )
    report = eval_crop.evaluate_dir(tmp_path)
    assert list(report) == [
        "ball_in_crop", "players_in_crop", "jitter", "seconds_per_min", "per_clip"
    ]
    assert report["ball_in_crop"] == 0.8
    assert [item["clip"] for item in report["per_clip"]] == ["a", "b"]
    assert list(report["per_clip"][0]) == [
        "clip", "duration", "labels", "ball_labels", "player_boxes",
        "ball_in_crop", "players_in_crop", "jitter", "seconds_per_min",
    ]
