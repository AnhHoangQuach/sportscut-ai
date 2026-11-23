"""Independent user-facing acceptance checks for T-029."""

import json
from pathlib import Path

import pytest

from sportscut.cli import main
from sportscut.eval_player import evaluate_dir, load_labels, match_times, score_clip
from sportscut.player import PlayerQuery, Touch


def _touch(t: float, team: str = "red", number: int = 10) -> Touch:
    return Touch(t, team, number, 1.0, None)


def test_acceptance_public_models_reject_edge_values_and_serialize() -> None:
    assert PlayerQuery(" RED ", 10) == PlayerQuery("red", 10)
    assert PlayerQuery("#FF0000", 7).team == "#ff0000"
    with pytest.raises(ValueError, match="#rrggbb"):
        PlayerQuery("maroon", 10)
    for invalid in (0, 100, "10", 10.0, True):
        with pytest.raises(ValueError):
            PlayerQuery("red", invalid)  # type: ignore[arg-type]

    value = Touch(1.5, "Blue", 4, 0.8, (1, 2, 16, 32)).to_dict()
    assert value == {
        "t": 1.5, "team": "blue", "number": 4,
        "confidence": 0.8, "bbox": [1, 2, 16, 32],
    }
    assert json.loads(json.dumps(value)) == value
    for confidence in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="confidence"):
            Touch(1.5, None, None, confidence, None)


def test_acceptance_empty_labels_and_inclusive_maximum_matching(tmp_path: Path) -> None:
    labels = tmp_path / "labels.json"
    labels.write_text('{"touches": []}')
    assert load_labels(labels) == ([], [])
    assert match_times([1.0, 1.6], [1.5, 2.0]) == [(0, 0), (1, 1)]
    assert match_times([5.0, 1.0], [1.2]) == [(1, 0)]
    assert match_times([1.0], [1.5]) == [(0, 0)]


def test_acceptance_equal_count_miss_is_not_ordinally_aligned() -> None:
    query = PlayerQuery("red", 10)
    labels = [(t, query) for t in (1.0, 2.0, 3.0, 4.0)]
    predicted = [_touch(t) for t in (2.0, 3.0, 4.0, 9.0)]
    counts = score_clip(labels, [query], predicted, {query: predicted})
    assert (counts["tp"], counts["fp"], counts["fn"]) == (3, 1, 1)
    assert (counts["any_tp"], counts["any_fp"], counts["any_fn"]) == (3, 1, 1)


def test_acceptance_all_cases_are_preflighted_before_video_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("a-valid", "b-missing"):
        case = tmp_path / name
        case.mkdir()
        (case / "labels.json").write_text('{"touches": []}')
    (tmp_path / "a-valid" / "clip.mp4").write_bytes(b"")

    called = False

    def probe(_path: Path) -> float:
        nonlocal called
        called = True
        return 1.0

    monkeypatch.setattr("sportscut.eval_player.media.probe_duration", probe)
    with pytest.raises(ValueError, match="build.py"):
        evaluate_dir(tmp_path)
    assert called is False


def test_acceptance_cli_reports_missing_and_empty_sets(capsys, tmp_path: Path) -> None:
    for directory in (tmp_path / "missing", tmp_path):
        assert main(["eval-player", str(directory), "--json"]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("sportscut eval-player: error:")
