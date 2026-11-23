import json
from pathlib import Path

import pytest

from sportscut.eval_player import evaluate_dir, load_labels, match_times, metrics, prf, score_clip
from sportscut.player import PlayerQuery, Touch


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value))
    return path


def test_load_labels_valid(tmp_path: Path) -> None:
    path = write_json(tmp_path / "labels.json", {
        "players": [{"team": "blue", "number": 4}],
        "touches": [
            {"t": 2, "team": "red", "number": 10},
            {"t": 1, "team": "blue", "number": 5},
        ],
    })
    touches, queries = load_labels(path)
    assert touches == [(1.0, PlayerQuery("blue", 5)), (2.0, PlayerQuery("red", 10))]
    assert queries == [PlayerQuery("blue", 4), PlayerQuery("blue", 5), PlayerQuery("red", 10)]
    assert load_labels(write_json(tmp_path / "minimal.json", {"touches": []})) == ([], [])


@pytest.mark.parametrize("value,indexed", [
    ([], False), ({}, False), ({"touches": [], "players": {}}, False),
    ({"touches": [{}]}, True),
    ({"touches": [{"t": "1", "team": "red", "number": 1}]}, True),
    ({"touches": [{"t": True, "team": "red", "number": 1}]}, True),
    ({"touches": [{"t": float("nan"), "team": "red", "number": 1}]}, True),
    ({"touches": [{"t": -1, "team": "red", "number": 1}]}, True),
    ({"touches": [{"t": 1, "team": "maroon", "number": 1}]}, True),
    ({"touches": [{"t": 1, "team": "red", "number": 0}]}, True),
])
def test_load_labels_rejects(tmp_path: Path, value: object, indexed: bool) -> None:
    path = write_json(tmp_path / "bad.json", value)
    with pytest.raises(ValueError) as exc_info:
        load_labels(path)
    assert str(path) in str(exc_info.value)
    if indexed:
        assert "touches[0]" in str(exc_info.value)


@pytest.mark.parametrize(("pred", "truth", "expected"), [
    ([1.0, 2.0, 5.0], [1.4, 2.6, 5.5], [(0, 0), (2, 2)]),
    ([3.0, 3.2], [3.1], [(0, 0)]),
    ([3.0], [2.6, 3.4], [(0, 0)]),
    ([1.0, 1.6], [1.5, 2.0], [(0, 0), (1, 1)]),
    ([5.0, 1.0], [1.2], [(1, 0)]),
    ([], [1], []),
])
def test_match_times_cases(pred, truth, expected) -> None:
    assert match_times(pred, truth) == expected


def test_prf() -> None:
    assert prf(0, 0, 0) == (0.0, 0.0, 0.0)
    assert prf(2, 1, 1) == pytest.approx((2 / 3, 2 / 3, 2 / 3))
    assert prf(3, 0, 0) == (1.0, 1.0, 1.0)


def test_score_clip_counts() -> None:
    a, b, c = PlayerQuery("red", 10), PlayerQuery("blue", 4), PlayerQuery("blue", 2)
    labels = [(1.0, a), (3.0, b)]
    detected = [Touch(1.1, "red", 10, 1, None), Touch(3.1, "red", 4, 1, None), Touch(8, None, None, 1, None)]
    found = {
        a: [Touch(1.1, "red", 10, 1, None), Touch(3.1, "red", 10, 1, None)],
        b: [], c: [Touch(9, "blue", 2, 1, None)],
    }
    assert score_clip(labels, [a, b, c], detected, found) == {
        "tp": 1, "fp": 2, "fn": 1,
        "any_tp": 2, "any_fp": 1, "any_fn": 0,
        "team_hits": 1, "id_hits": 1,
    }


def test_score_clip_maximum_matching_with_equal_counts() -> None:
    query = PlayerQuery("red", 10)
    labels = [(time, query) for time in (1.0, 2.0, 3.0, 4.0)]
    predicted = [Touch(time, "red", 10, 1, None) for time in (2.0, 3.0, 4.0, 9.0)]

    counts = score_clip(labels, [query], predicted, {query: predicted})

    assert (counts["tp"], counts["fp"], counts["fn"]) == (3, 1, 1)
    assert (counts["any_tp"], counts["any_fp"], counts["any_fn"]) == (3, 1, 1)


def test_metrics_none_and_rounding() -> None:
    counts = {"tp": 1, "fp": 2, "fn": 2, "any_tp": 0, "any_fp": 0, "any_fn": 1, "team_hits": 0, "id_hits": 0}
    assert metrics(counts, 2, 3) == {
        "f1": 0.3333, "precision": 0.3333, "recall": 0.3333,
        "touch_f1_any": 0.0, "team_accuracy": None, "id_accuracy": None,
        "seconds_per_min": 0.6667,
    }
    assert metrics(counts, 2, 0)["seconds_per_min"] == 0.0


def test_evaluate_dir_errors(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        evaluate_dir(tmp_path / "missing")
    with pytest.raises(ValueError):
        evaluate_dir(tmp_path)
    case = tmp_path / "case"
    case.mkdir()
    write_json(case / "labels.json", {"touches": []})
    with pytest.raises(ValueError, match="build.py"):
        evaluate_dir(tmp_path)
