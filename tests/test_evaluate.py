import json
from pathlib import Path

import pytest

from sportscut.models import Segment


def seg(start, end, score=1, event="other"):
    return Segment(start, end, score, "test", event)


def test_mapping_iou_and_one_to_one() -> None:
    from sportscut.evaluate import Label, match_segments, temporal_iou, to_event

    assert [to_event(x) for x in ("goal", "save", "red_card", "controversy")] == [
        "goal", "save", "red_card", "controversy"
    ]
    assert [to_event(x) for x in ("chance", "yellow_card", "foul", "other")] == ["other"] * 4
    assert temporal_iou(0, 6, 3, 10) == 0.3
    assert temporal_iou(0, 1, 2, 3) == 0.0
    assert match_segments([seg(0, 6)], [Label(3, 10, "goal")]) == [(0, 0)]
    assert match_segments([seg(0, 6)], [Label(3, 10.1, "goal")]) == []
    assert match_segments([seg(10, 20), seg(11, 21)], [Label(12, 18, "goal")]) == [(0, 0)]
    assert match_segments([seg(0, 30)], [Label(5, 7, "goal"), Label(20, 22, "save")]) == [(0, 0)]


def test_load_labels_json_and_csv(tmp_path: Path) -> None:
    from sportscut.evaluate import Label, load_labels

    path = tmp_path / "labels.json"
    path.write_text(json.dumps([{"start": 1, "end": 2.5, "type": " Goal ", "importance": 2}]))
    assert load_labels(path) == [Label(1.0, 2.5, "goal")]
    path.write_text("[]")
    assert load_labels(path) == []
    csv_path = tmp_path / "labels.csv"
    csv_path.write_text("start,end,type\n\n# note\n00:20,00:21,goal\n93:05,93:12.5,Save\n")
    assert load_labels(csv_path) == [Label(20, 21, "goal"), Label(5585, 5592.5, "save")]


@pytest.mark.parametrize("value", ["{}", "[1]", '[{"end": 2, "type": "goal"}]', '[{"start": true, "end": 2, "type": "goal"}]', '[{"start": -1, "end": 2, "type": "goal"}]', '[{"start": 2, "end": 2, "type": "goal"}]', '[{"start": 1, "end": 2, "type": "penalty"}]', "{"])
def test_load_json_invalid(tmp_path: Path, value: str) -> None:
    from sportscut.evaluate import load_labels

    path = tmp_path / "labels.json"
    path.write_text(value)
    with pytest.raises(ValueError, match=str(path)):
        load_labels(path)


def test_load_json_decode_error_names_path(tmp_path: Path) -> None:
    from sportscut.evaluate import load_labels

    path = tmp_path / "labels.json"
    path.write_bytes(b"\xff")
    with pytest.raises(ValueError) as error:
        load_labels(path)
    assert str(path) in str(error.value)


@pytest.mark.parametrize("line", ["12:60,13:00,goal", "1:2:3,13:00,goal", "00:01,00:02", "00:02,00:01,goal", "00:01,00:02,penalty"])
def test_load_csv_invalid(tmp_path: Path, line: str) -> None:
    from sportscut.evaluate import load_labels

    path = tmp_path / "labels.csv"
    path.write_text("# comment\n" + line + "\n")
    with pytest.raises(ValueError) as error:
        load_labels(path)
    assert str(path) in str(error.value) and "line 2" in str(error.value)


def test_score_case_worked_example() -> None:
    from sportscut.evaluate import Label, score_case, summarize

    segments = [seg(0, 10, 5, "goal"), seg(20, 30, 4, "save"), seg(40, 50, 3), seg(60, 70, 2, "goal")]
    labels = [Label(2, 6, "goal"), Label(22, 26, "goal"), Label(42, 46, "foul"), Label(80, 85, "red_card")]
    result = summarize(score_case(segments, labels))
    assert list(result) == ["f1", "precision", "recall", "event_accuracy", "per_event", "precision_at_5"]
    assert result == {"f1": .75, "precision": .75, "recall": .75, "event_accuracy": .6667,
        "per_event": {"goal": {"precision": .5, "recall": .5, "f1": .5}, "save": {"precision": 0.0, "recall": None, "f1": None}, "red_card": {"precision": None, "recall": 0.0, "f1": None}, "controversy": {"precision": None, "recall": None, "f1": None}, "other": {"precision": 1.0, "recall": 1.0, "f1": 1.0}}, "precision_at_5": .75}


def test_evaluate_dir_validates_then_aggregates(tmp_path: Path, monkeypatch) -> None:
    from sportscut import detect
    from sportscut.evaluate import evaluate_dir

    called = []
    monkeypatch.setattr(detect, "find_highlights", lambda video: called.append(Path(video).parent.name) or [seg(0, 10)])
    with pytest.raises(ValueError, match="no eval cases found"):
        evaluate_dir(tmp_path)
    for name in ("b", "a"):
        case = tmp_path / name
        case.mkdir()
        (case / "labels.json").write_text('[{"start":2,"end":3,"type":"foul"}]')
        (case / "video.mp4").touch()
    report = evaluate_dir(tmp_path)
    assert called == ["a", "b"]
    assert report["f1"] == 1.0
    assert [item["match"] for item in report["per_match"]] == ["a", "b"]
    assert list(report["per_match"][0]) == ["match", "labels", "predictions", "f1", "precision", "recall", "event_accuracy", "precision_at_5"]


def test_cli_eval_json_and_error(tmp_path: Path, monkeypatch, capsys) -> None:
    from sportscut import evaluate
    from sportscut.cli import main

    report = {"f1": 1.0}
    monkeypatch.setattr(evaluate, "evaluate_dir", lambda path: report)
    assert main(["eval", str(tmp_path), "--json"]) == 0
    assert capsys.readouterr().out == '{"f1": 1.0}\n'
    monkeypatch.setattr(evaluate, "evaluate_dir", lambda path: (_ for _ in ()).throw(ValueError("bad")))
    assert main(["eval", str(tmp_path)]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "sportscut eval: error: bad\n"
