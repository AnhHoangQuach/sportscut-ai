import json
import math
from pathlib import Path

import numpy as np
import pytest

from sportscut import detect
from sportscut.cli import main
from sportscut.events import audio_cues, scoreboard
from sportscut.evaluate import (
    LABEL_TYPES,
    Label,
    evaluate_dir,
    load_labels,
    match_segments,
    score_case,
    summarize,
    temporal_iou,
    to_event,
)
from sportscut.models import EVENT_TYPES, Segment


def _segment(start, end, score=1.0, event="other"):
    return Segment(start, end, score, "acceptance", event)


def test_t010_ac1_segment_public_contract() -> None:
    assert EVENT_TYPES == ("goal", "save", "red_card", "controversy", "other")
    default = Segment(1, 3.5, 0.8, "crowd noise")
    assert default.to_dict() == {
        "start": 1.0, "end": 3.5, "score": 0.8,
        "reason": "crowd noise", "event": "other", "event_confidence": 0.0,
    }
    assert list(default.to_dict()) == ["start", "end", "score", "reason", "event", "event_confidence"]
    assert _segment(0, 1, event="goal").to_dict()["event"] == "goal"
    numpy_event = _segment(0, 1, event=np.str_("save")).to_dict()["event"]
    assert numpy_event == "save" and type(numpy_event) is str
    for invalid in ("penalty", "Goal", ""):
        with pytest.raises(ValueError, match="event must be one of"):
            _segment(0, 1, event=invalid)


def test_t010_ac2_detect_and_pipeline_public_shapes(
    burst_video, tmp_path: Path, capsys
) -> None:
    assert main(["detect", str(burst_video), "--json"]) == 0
    cli_output = capsys.readouterr()
    assert cli_output.err == "" and cli_output.out.count("\n") == 1
    cli_segments = json.loads(cli_output.out)
    assert cli_segments and all(
        set(item) == {"start", "end", "score", "reason", "event", "event_confidence"}
        and item["event"] == "other"
        for item in cli_segments
    )

    segments = detect.find_highlights(burst_video)
    assert segments and all(set(item.to_dict()) == {"start", "end", "score", "reason", "event", "event_confidence"} for item in segments)
    assert all(item.event == "other" for item in segments)

    from sportscut.pipeline import run

    manifest = run(burst_video, tmp_path / "clips")
    assert manifest and all(set(item) == {"start", "end", "score", "reason", "event", "event_confidence", "file"} for item in manifest)
    assert all(item["event"] == "other" for item in manifest)


def test_t010_ac3_mapping_vocabulary() -> None:
    assert LABEL_TYPES == ("goal", "save", "red_card", "controversy", "chance", "yellow_card", "foul", "other")
    assert [to_event(kind) for kind in LABEL_TYPES] == [
        "goal", "save", "red_card", "controversy", "other", "other", "other", "other"
    ]


@pytest.mark.parametrize("bad", [
    {}, [1], [{"end": 2, "type": "goal"}],
    [{"start": 1, "type": "goal"}],
    [{"start": 1, "end": 2}],
    [{"start": True, "end": 2, "type": "goal"}],
    [{"start": 1, "end": False, "type": "goal"}],
    [{"start": math.inf, "end": 2, "type": "goal"}],
    [{"start": 1, "end": math.nan, "type": "goal"}],
    [{"start": 1, "end": math.inf, "type": "goal"}],
    [{"start": -1, "end": 2, "type": "goal"}],
    [{"start": 2, "end": 2, "type": "goal"}],
    [{"start": 2, "end": 1, "type": "goal"}],
    [{"start": 1, "end": 2, "type": "penalty"}],
])
def test_t010_ac4_json_rejects_invalid_labels_with_path(tmp_path: Path, bad) -> None:
    path = tmp_path / "labels.json"
    path.write_text(json.dumps(bad))
    with pytest.raises(ValueError) as caught:
        load_labels(path)
    assert str(path) in str(caught.value)


def test_t010_ac4_ac5_label_formats(tmp_path: Path) -> None:
    json_path = tmp_path / "labels.json"
    json_path.write_text('[{"start":1,"end":2,"type":" Goal ","importance":9}]')
    assert load_labels(json_path) == [Label(1, 2, "goal")]
    json_path.write_text("[]")
    assert load_labels(json_path) == []

    csv_path = tmp_path / "labels.csv"
    csv_path.write_text("start,end,type\n\n# ignored\n00:20,00:21,goal\n93:05,93:12.5,Save\n")
    assert load_labels(csv_path) == [Label(20, 21, "goal"), Label(5585, 5592.5, "save")]


@pytest.mark.parametrize("row", [
    "12:60,13:00,goal", "1:2:3,13:00,goal", "00:01,00:02",
    "00:02,00:01,goal", "00:01,00:02,penalty",
])
def test_t010_ac5_csv_errors_name_physical_line(tmp_path: Path, row: str) -> None:
    path = tmp_path / "labels.csv"
    path.write_text("# ignored\n\n" + row + "\n")
    with pytest.raises(ValueError) as caught:
        load_labels(path)
    assert str(path) in str(caught.value) and "line 3" in str(caught.value)


def test_t010_ac6_matching_boundaries_and_one_to_one() -> None:
    assert temporal_iou(0, 6, 3, 10) == 0.3
    assert match_segments([_segment(0, 6)], [Label(3, 10, "goal")]) == [(0, 0)]
    assert match_segments([_segment(0, 6)], [Label(3, 10.1, "goal")]) == []
    assert match_segments([_segment(10, 20)], [Label(12, 14, "goal")]) == [(0, 0)]
    assert match_segments([_segment(10, 20)], [Label(17, 25, "goal")]) == []
    assert match_segments([_segment(10, 20), _segment(11, 21)], [Label(12, 18, "goal")]) == [(0, 0)]
    assert match_segments([_segment(0, 30)], [Label(5, 7, "goal"), Label(20, 22, "save")]) == [(0, 0)]


def test_t010_ac7_worked_metrics_and_exact_shapes() -> None:
    segments = [_segment(0, 10, 5, "goal"), _segment(20, 30, 4, "save"),
                _segment(40, 50, 3), _segment(60, 70, 2, "goal")]
    labels = [Label(2, 6, "goal"), Label(22, 26, "goal"),
              Label(42, 46, "foul"), Label(80, 85, "red_card")]
    report = summarize(score_case(segments, labels))
    assert list(report) == ["f1", "precision", "recall", "event_accuracy", "per_event", "precision_at_5"]
    assert report == {"f1": .75, "precision": .75, "recall": .75, "event_accuracy": .6667,
        "per_event": {"goal": {"precision": .5, "recall": .5, "f1": .5},
          "save": {"precision": 0.0, "recall": None, "f1": None},
          "red_card": {"precision": None, "recall": 0.0, "f1": None},
          "controversy": {"precision": None, "recall": None, "f1": None},
          "other": {"precision": 1.0, "recall": 1.0, "f1": 1.0}}, "precision_at_5": .75}


@pytest.mark.parametrize("total,matched,expected", [(7, 3, .6), (2, 1, .5), (0, 0, 0.0)])
def test_t010_ac8_precision_at_5(total: int, matched: int, expected: float) -> None:
    segments = [_segment(i * 10, i * 10 + 5, total - i) for i in range(total)]
    labels = [Label(i * 10 + 1, i * 10 + 2, "other") for i in range(matched)]
    report = summarize(score_case(segments, labels))
    assert report["precision_at_5"] == expected
    if not matched:
        assert report["event_accuracy"] is None


def test_t010_ac9_all_directory_errors_happen_before_detection(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(detect, "find_highlights", lambda _: pytest.fail("detection ran before validation"))
    with pytest.raises(ValueError, match="not a directory"):
        evaluate_dir(tmp_path / "missing")
    with pytest.raises(ValueError, match="no eval cases found"):
        evaluate_dir(tmp_path)

    case = tmp_path / "case"
    case.mkdir()
    (case / "labels.json").write_text("[]")
    (case / "labels.csv").write_text("")
    with pytest.raises(ValueError, match="has both"):
        evaluate_dir(tmp_path)
    (case / "labels.csv").unlink()
    with pytest.raises(ValueError, match="expected exactly one video"):
        evaluate_dir(tmp_path)
    (case / "a.mp4").touch()
    (case / "b.MOV").touch()
    with pytest.raises(ValueError, match="expected exactly one video"):
        evaluate_dir(tmp_path)


def test_t010_ac10_real_cli_burst_json_and_pretty(burst_video: Path, tmp_path: Path, capsys) -> None:
    case = tmp_path / "burst"
    case.mkdir()
    (case / "video.mp4").symlink_to(burst_video)
    (case / "labels.json").write_text(json.dumps([
        {"start": 20, "end": 21, "type": "goal"},
        {"start": 50, "end": 51, "type": "controversy"},
        {"start": 5, "end": 7, "type": "chance"},
    ]))
    assert main(["eval", str(tmp_path), "--json"]) == 0
    json_output = capsys.readouterr().out
    assert json_output.count("\n") == 1
    report = json.loads(json_output)
    assert list(report) == ["f1", "precision", "recall", "event_accuracy", "per_event", "precision_at_5", "per_match"]
    assert (report["f1"], report["precision"], report["recall"]) == (.6667, .6667, .6667)
    assert report["event_accuracy"] == 0.0 and report["precision_at_5"] == .6667
    assert report["per_event"]["goal"]["recall"] == 0.0
    assert report["per_event"]["other"]["precision"] == 0.0
    assert report["per_match"][0]["match"] == "burst"
    assert (report["per_match"][0]["labels"], report["per_match"][0]["predictions"]) == (3, 3)

    assert main(["eval", str(tmp_path)]) == 0
    pretty = capsys.readouterr().out
    assert pretty.startswith("{\n  \"") and json.loads(pretty) == report


def test_t010_ac11_cli_error_and_help(tmp_path: Path, capsys) -> None:
    assert main(["eval", str(tmp_path / "missing")]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("sportscut eval: error: not a directory:")
    with pytest.raises(SystemExit) as exited:
        main(["eval", "--help"])
    assert exited.value.code == 0
    help_output = capsys.readouterr().out
    assert "DIRECTORY" in help_output and "--json" in help_output


def test_t010_ac2_api_response_keys(tmp_path: Path, monkeypatch) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    import sportscut.api as api
    from sportscut import media, pipeline

    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    entry = {**_segment(1, 12, 0.9, "goal").to_dict(), "file": "clip_01.mp4"}
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: [entry])
    monkeypatch.setattr(media, "probe_duration", lambda _path: 20.0)
    response = TestClient(api.app).post("/highlights", files={"file": ("x.mp4", b"data")})
    assert response.status_code == 200
    (highlight,) = response.json()["highlights"]
    assert set(highlight) == {"start", "end", "score", "reason", "event", "event_confidence", "clip_url"}


def test_t010_ac4_broken_json_and_non_string_type_name_path(tmp_path: Path) -> None:
    path = tmp_path / "labels.json"
    for text in ("[{", '[{"start":1,"end":2,"type":3}]', '[{"start":"1","end":2,"type":"goal"}]'):
        path.write_text(text)
        with pytest.raises(ValueError) as caught:
            load_labels(path)
        assert str(path) in str(caught.value)


@pytest.mark.parametrize("raw", [b"\xff\xfe\x00[", b'[{"start":1,"end":2,"type":"g\xe9al"}]'])
def test_t010_ac4_non_utf8_json_names_path(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "labels.json"
    path.write_bytes(raw)
    with pytest.raises(ValueError) as caught:
        load_labels(path)
    assert str(path) in str(caught.value)


def test_t010_ac4_ac11_non_utf8_json_cli_exit_2(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(detect, "find_highlights", lambda _: pytest.fail("detection ran"))
    case = tmp_path / "m1"
    case.mkdir()
    (case / "v.mp4").touch()
    (case / "labels.json").write_bytes(b"\x80\x81 not utf-8")
    assert main(["eval", str(tmp_path), "--json"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("sportscut eval: error: ")
    assert str(case / "labels.json") in output.err


def test_t010_ac5_padded_cells_and_header_only_first(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    path.write_text(" 01:00 , 01:10.25 ,  Red_Card \n")
    assert load_labels(path) == [Label(60, 70.25, "red_card")]
    path.write_text("00:01,00:02,goal\nstart,end,type\n")
    with pytest.raises(ValueError, match="line 2"):
        load_labels(path)


def test_t010_ac6_best_iou_wins_and_unmatched_stays_fp_fn() -> None:
    # The label prefers the closer clip; the other clip is fp.
    segments = [_segment(0, 30), _segment(10, 16)]
    assert match_segments(segments, [Label(11, 15, "goal")]) == [(1, 0)]
    counts = score_case([_segment(0, 30)], [Label(5, 7, "goal"), Label(20, 22, "goal")])
    assert (counts["tp"], counts["fp"], counts["fn"]) == (1, 0, 1)
    counts = score_case([_segment(10, 20), _segment(11, 21)], [Label(12, 18, "goal")])
    assert (counts["tp"], counts["fp"], counts["fn"]) == (1, 1, 0)


def _case(root: Path, name: str, labels: list[dict]) -> None:
    case = root / name
    case.mkdir()
    (case / "match.mkv").touch()
    (case / "labels.json").write_text(json.dumps(labels))


def test_t010_ac9_sums_cases_in_sorted_order(tmp_path: Path, monkeypatch) -> None:
    _case(tmp_path, "b", [{"start": 2, "end": 4, "type": "goal"}, {"start": 50, "end": 52, "type": "save"}])
    _case(tmp_path, "a", [{"start": 2, "end": 4, "type": "foul"}])
    (tmp_path / "notes").mkdir()  # no labels: not a case, ignored
    (tmp_path / "c").mkdir()
    (tmp_path / "c" / "labels.csv").write_text("00:01,00:05,goal\n")
    (tmp_path / "c" / "clip.MP4").touch()
    by_case = {
        "a": [_segment(0, 10, 3), _segment(30, 40, 2)],
        "b": [_segment(0, 10, 5, "goal")],
        "c": [],
    }
    calls = []

    def fake(video):
        calls.append(Path(video).parent.name)
        return by_case[Path(video).parent.name]

    monkeypatch.setattr(detect, "find_highlights", fake)
    monkeypatch.setattr(scoreboard, "tag_goals", lambda video, segments, **kw: list(segments))
    monkeypatch.setattr(audio_cues, "tag_saves", lambda video, segments, **kw: list(segments))
    report = evaluate_dir(tmp_path)
    assert calls == ["a", "b", "c"]
    # totals: tp=2 (a:1, b:1), fp=1, fn=2 -> p=0.6667, r=0.5
    assert (report["precision"], report["recall"], report["f1"]) == (.6667, .5, .5714)
    assert report["event_accuracy"] == 1.0
    assert report["precision_at_5"] == .6667
    assert report["per_event"]["goal"] == {"precision": 1.0, "recall": .5, "f1": .6667}
    assert [m["match"] for m in report["per_match"]] == ["a", "b", "c"]
    for entry in report["per_match"]:
        assert list(entry) == ["match", "labels", "predictions", "f1", "precision",
                               "recall", "event_accuracy", "precision_at_5"]
    assert report["per_match"][2] == {"match": "c", "labels": 1, "predictions": 0, "f1": 0.0,
        "precision": 0.0, "recall": 0.0, "event_accuracy": None, "precision_at_5": 0.0}


def test_t010_ac11_case_without_video_exits_2_before_detection(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(detect, "find_highlights", lambda _: pytest.fail("detection ran"))
    case = tmp_path / "m1"
    case.mkdir()
    (case / "labels.csv").write_text("00:01,00:02,goal\n")
    assert main(["eval", str(tmp_path), "--json"]) == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("sportscut eval: error: ") and "expected exactly one video" in output.err
    (case / "labels.csv").write_text("00:01,00:02,penalty\n")
    (case / "v.mp4").touch()
    assert main(["eval", str(tmp_path)]) == 2
    assert "penalty" in capsys.readouterr().err


def test_t010_ac12_protected_files_untouched_and_specs_updated() -> None:
    root = Path(__file__).resolve().parents[1]
    specs = root / "docs" / "superpowers" / "specs"
    for prefix in ("t-035", "t-002", "t-004"):
        (spec,) = specs.glob(f"2026-11-23-{prefix}-*-design.md")
        text = spec.read_text()
        assert "event" in text and "(updated by T-010)" in text, spec.name
