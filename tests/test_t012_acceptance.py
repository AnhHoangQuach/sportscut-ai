"""Independent acceptance coverage for T-012, derived from .office/TASK.md."""

import json
from pathlib import Path
import re
from uuid import UUID

import numpy as np
import pytest
from fastapi.testclient import TestClient

from sportscut import api, cli, media, pipeline
from sportscut.detect import find_highlights
from sportscut.evaluate import evaluate_dir
from sportscut.models import Segment
from sportscut.ranking import EVENT_PRIORITY, parse_events, select_segments


def _worked_segments() -> list[Segment]:
    return [
        Segment(0, 5, 10.0, "F", "other"),
        Segment(10, 20, 4.0, "A", "other"),
        Segment(30, 40, 2.0, "B", "goal", 0.8),
        Segment(50, 60, 3.0, "C", "save", 0.7),
        Segment(70, 80, 5.0, "D", "red_card", 0.6),
        Segment(85, 89, 6.0, "E", "controversy", 0.5),
    ]


def _manifest_dir(root: Path, job_id: str, entries: list[dict]) -> Path:
    clips = root / "jobs" / job_id / "clips"
    clips.mkdir(parents=True)
    (clips / "highlights.json").write_text(json.dumps(entries))
    return clips


def test_t012_ac1_event_confidence_serialization_and_validation() -> None:
    expected = {
        "start": 1.0,
        "end": 3.5,
        "score": 0.8,
        "reason": "crowd noise",
        "event": "other",
        "event_confidence": 0.0,
    }
    assert Segment(1.0, 3.5, 0.8, "crowd noise").to_dict() == expected
    assert list(expected) == list(Segment(1.0, 3.5, 0.8, "crowd noise").to_dict())
    assert Segment(1, 2, 1, "x", "goal", 0.75).to_dict()["event_confidence"] == 0.75
    native = Segment(1, 2, 1, "x", event_confidence=np.float64(0.5)).to_dict()
    assert native["event_confidence"] == 0.5
    assert type(native["event_confidence"]) is float
    for value in (-0.1, 1.5, float("nan")):
        with pytest.raises(ValueError, match="^event_confidence must be between 0 and 1$"):
            Segment(1, 2, 1, "x", event_confidence=value)


def test_t012_ac2_event_parser_normalizes_deduplicates_and_rejects_bad_items() -> None:
    assert EVENT_PRIORITY == {
        "goal": 5, "red_card": 4, "controversy": 3, "save": 2, "other": 1
    }
    assert parse_events("Goal, save,goal") == ("goal", "save")
    message = "unknown event {!r}; choose from goal, save, red_card, controversy, other"
    for text, bad in (("penalty", "penalty"), ("", ""), ("goal,", ""), ("goal,,save", "")):
        with pytest.raises(ValueError, match=f"^{re.escape(message.format(bad))}$"):
            parse_events(text)


def test_t012_ac3_ranking_priority_filters_and_returns_time_order() -> None:
    segments = _worked_segments()
    cases = [
        (3, None, [30, 70, 85]),
        (4, None, [0, 30, 70, 85]),
        (10, ("goal",), [30]),
        (5, ("save", "goal"), [30, 50]),
        (1, ("other",), [0]),
        (1, ("controversy", "red_card"), [70]),
    ]
    for top, events, starts in cases:
        assert [item.start for item in select_segments(segments, top, events)] == starts
    ties = [Segment(30, 35, 4, "late"), Segment(10, 15, 4, "early")]
    assert select_segments(ties, 1)[0].start == 10


def test_t012_ac4_empty_selection_and_public_validation_errors() -> None:
    others = [Segment(0, 5, 2, "x"), Segment(10, 15, 3, "y")]
    assert select_segments(others, 10, ("goal",)) == []
    assert select_segments(others, 10, ()) == []
    with pytest.raises(ValueError, match="^top must be >= 1$"):
        select_segments(others, 0)
    with pytest.raises(ValueError, match="^unknown event 'penalty'; choose from"):
        select_segments(others, 1, ("penalty",))


def test_t012_ac5_uncapped_detection_preserves_capped_results(burst_video: Path) -> None:
    uncapped = find_highlights(str(burst_video), top=None)
    assert len(uncapped) >= 3
    expected = sorted(
        sorted(uncapped, key=lambda item: (-item.score, item.start))[:2],
        key=lambda item: item.start,
    )
    assert find_highlights(str(burst_video), top=2) == expected
    with pytest.raises(ValueError, match="^top must be >= 1$"):
        find_highlights(str(burst_video), top=0)


def test_t012_ac6_pipeline_ranks_then_exports_filtered_clips(
    burst_video: Path, tmp_path: Path, monkeypatch
) -> None:
    calls = []

    def detector(video, **kwargs):
        calls.append((video, kwargs))
        return _worked_segments()

    monkeypatch.setattr(pipeline, "find_highlights", detector)
    entries = pipeline.run(burst_video, tmp_path / "ranked", top=3)
    assert [entry["start"] for entry in entries] == [30, 70, 85]
    assert [entry["event"] for entry in entries] == ["goal", "red_card", "controversy"]
    assert [entry["file"] for entry in entries] == ["clip_01.mp4", "clip_02.mp4", "clip_03.mp4"]
    assert all((tmp_path / "ranked" / entry["file"]).is_file() for entry in entries)
    assert all(set(entry) == {
        "start", "end", "score", "reason", "event", "event_confidence", "file"
    } for entry in entries)
    assert json.loads((tmp_path / "ranked" / "highlights.json").read_text()) == entries
    assert calls[0][1]["top"] is None

    filtered = pipeline.run(burst_video, tmp_path / "goal", events=["goal"])
    assert [(entry["start"], entry["event"], entry["file"]) for entry in filtered] == [
        (30.0, "goal", "clip_01.mp4")
    ]


def test_t012_ac7_pipeline_empty_filter_and_early_top_validation(
    burst_video: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        pipeline,
        "find_highlights",
        lambda *args, **kwargs: [Segment(10, 20, 4, "only other")],
    )
    out = tmp_path / "empty"
    assert pipeline.run(burst_video, out, events=("goal",)) == []
    assert json.loads((out / "highlights.json").read_text()) == []
    assert list(out.glob("*.mp4")) == []
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(pipeline.PipelineError, match="^top must be >= 1$"):
        pipeline.run(burst_video, tmp_path / "invalid", top=0)


def test_t012_ac8_default_pipeline_output_matches_capped_detector(
    burst_video: Path, tmp_path: Path
) -> None:
    expected = find_highlights(str(burst_video), top=2)
    entries = pipeline.run(burst_video, tmp_path / "default", top=2)
    assert [(e["start"], e["end"], e["score"]) for e in entries] == [
        (s.start, s.end, s.score) for s in expected
    ]
    assert all(e["event"] == "other" and e["event_confidence"] == 0.0 for e in entries)


def test_t012_ac9_cli_forwards_events_top_and_real_empty_result(
    burst_video: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return []

    with monkeypatch.context() as patch:
        patch.setattr(cli, "run", fake_run)
        assert cli.main(["cut", "v.mp4", "--out", str(tmp_path / "a"), "--events", "Goal, save"]) == 0
        assert cli.main(["cut", "v.mp4", "--out", str(tmp_path / "b")]) == 0
        assert cli.main(["cut", "v.mp4", "--out", str(tmp_path / "c"), "--top", "5"]) == 0
    assert [call[1]["events"] for call in calls] == [("goal", "save"), None, None]
    assert calls[2][1]["top"] == 5
    capsys.readouterr()
    out = tmp_path / "real"
    assert cli.main(["cut", str(burst_video), "--out", str(out), "--events", "goal"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads((out / "highlights.json").read_text()) == []


@pytest.mark.parametrize("bad", ["penalty", "", "goal,,save"])
def test_t012_ac10_cli_rejects_unknown_events_before_work(
    bad: str, tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli, "run", lambda *a, **k: pytest.fail("pipeline.run was called"))
    out = tmp_path / "clips"
    with pytest.raises(SystemExit) as exited:
        cli.main(["cut", "video.mp4", "--out", str(out), "--events", bad])
    assert exited.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "argument --events: unknown event" in captured.err
    assert not out.exists()


def test_t012_ac11_post_forwards_events_and_returns_ordered_compatible_items(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    calls = []
    entries = [
        {"start": 1, "end": 3, "score": 5, "reason": "new", "event": "goal",
         "event_confidence": 0.9, "file": "clip_01.mp4"},
        {"start": 5, "end": 7, "score": 2, "reason": "legacy", "file": "clip_02.mp4"},
    ]

    def fake_run(*args, **kwargs):
        calls.append(kwargs)
        return entries

    monkeypatch.setattr(pipeline, "run", fake_run)
    monkeypatch.setattr(media, "probe_duration", lambda path: 10.0)
    client = TestClient(api.app)
    forms = [({"events": "goal,save", "top": "2"}, ("goal", "save")), ({}, None), ({"events": "  "}, None)]
    for form, expected_events in forms:
        response = client.post("/highlights", data=form, files={"file": ("x.mp4", b"data")})
        assert response.status_code == 200
        highlights = response.json()["highlights"]
        assert list(highlights[0]) == [
            "start", "end", "score", "reason", "event", "event_confidence", "clip_url"
        ]
        assert highlights[1]["event"] == "other" and highlights[1]["event_confidence"] == 0.0
        assert calls[-1]["events"] == expected_events
    assert calls[0]["top"] == 2


def test_t012_ac12_post_rejects_unknown_before_job_and_real_goal_filter_is_empty(
    burst_video: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    client = TestClient(api.app)
    with monkeypatch.context() as patch:
        patch.setattr(pipeline, "run", lambda *a, **k: pytest.fail("pipeline.run was called"))
        response = client.post(
            "/highlights", data={"events": "penalty"}, files={"file": ("x.mp4", b"data")}
        )
    assert response.status_code == 422
    assert response.json()["detail"] == (
        "unknown event 'penalty'; choose from goal, save, red_card, controversy, other"
    )
    assert not (tmp_path / "jobs").exists()

    response = client.post(
        "/highlights",
        data={"events": "goal"},
        files={"file": ("burst.mp4", burst_video.read_bytes(), "video/mp4")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["highlights"] == []
    manifest = tmp_path / "jobs" / body["job_id"] / "clips" / "highlights.json"
    assert json.loads(manifest.read_text()) == []


def test_t012_ac13_job_read_filters_manifest_and_defaults_legacy_fields(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    job_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    entries = [
        {"start": 1, "end": 2, "score": 5, "reason": "g", "event": "goal",
         "event_confidence": 0.8, "file": "clip_01.mp4"},
        {"start": 3, "end": 4, "score": 2, "reason": "old", "file": "clip_02.mp4"},
        {"start": 5, "end": 6, "score": 3, "reason": "s", "event": "save",
         "event_confidence": 0.6, "file": "clip_03.mp4"},
    ]
    _manifest_dir(tmp_path, job_id, entries)
    client = TestClient(api.app)
    expected_counts = [("", 3), ("?event=goal", 1), ("?event=goal,save", 2),
                       ("?event=red_card", 0), ("?event=", 3)]
    for query, count in expected_counts:
        response = client.get(f"/highlights/{job_id}{query}")
        assert response.status_code == 200
        assert set(response.json()) == {"job_id", "highlights"}
        assert len(response.json()["highlights"]) == count
    all_items = client.get(f"/highlights/{job_id}").json()["highlights"]
    assert [item["start"] for item in all_items] == [1, 3, 5]
    assert (all_items[1]["event"], all_items[1]["event_confidence"]) == ("other", 0.0)
    for item, entry in zip(all_items, entries):
        expected = str(client.base_url).rstrip("/") + str(
            api.app.url_path_for("get_clip", job_id=job_id, name=entry["file"])
        )
        assert item["clip_url"] == expected


def test_t012_ac14_job_read_validation_and_canonical_ids(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    job_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    _manifest_dir(tmp_path, job_id, [])
    client = TestClient(api.app)
    missing = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    bad_event = client.get(f"/highlights/{missing}?event=penalty")
    assert bad_event.status_code == 422
    assert bad_event.json()["detail"].startswith("unknown event 'penalty'")
    for value in (missing, "not-a-uuid", job_id.upper()):
        response = client.get(f"/highlights/{value}")
        assert response.status_code == 404
        assert response.json()["detail"] == "not found"
    assert str(UUID(job_id)) == job_id


def test_t012_ac15_eval_metrics_are_unchanged(burst_video: Path, tmp_path: Path) -> None:
    case = tmp_path / "burst"
    case.mkdir()
    (case / "video.mp4").symlink_to(burst_video)
    (case / "labels.json").write_text(json.dumps([
        {"start": 20, "end": 21, "type": "goal"},
        {"start": 50, "end": 51, "type": "controversy"},
        {"start": 5, "end": 7, "type": "chance"},
    ]))
    report = evaluate_dir(tmp_path)
    assert (report["f1"], report["precision"], report["recall"]) == (0.6667, 0.6667, 0.6667)


def test_t012_ac16_persistent_specs_and_readme_describe_the_public_behavior() -> None:
    root = Path(__file__).parents[1]
    specs = root / "docs" / "superpowers" / "specs"

    def ac_line(filename: str, ac: str) -> str:
        return next(line for line in (specs / filename).read_text().splitlines() if line.startswith(f"- {ac}:"))

    checks = [
        ("2026-11-23-t-035-scaffold-sportscut-packaging-version-cli-and-design.md", "AC5", "event_confidence"),
        ("2026-11-23-t-002-detect-highlight-segments-from-audio-excitement-design.md", "AC1", "top=None"),
        ("2026-11-23-t-002-detect-highlight-segments-from-audio-excitement-design.md", "AC9", "event_confidence"),
        ("2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md", "AC1", "events=None"),
        ("2026-11-23-t-005-expose-post-highlights-over-http-with-design.md", "AC2", "event_confidence"),
        ("2026-11-23-t-010-add-event-types-to-segments-and-design.md", "AC1", "event_confidence"),
        ("2026-11-23-t-010-add-event-types-to-segments-and-design.md", "AC2", "event_confidence"),
    ]
    for filename, ac, phrase in checks:
        line = ac_line(filename, ac)
        assert phrase in line and "(updated by T-012)" in line
    for filename, ac in (
        (checks[0][0], "AC5"), (checks[2][0], "AC9"), (checks[3][0], "AC1")
    ):
        assert "(updated by T-010)" in ac_line(filename, ac)
    readme = (root / "README.md").read_text()
    assert "sportscut cut match.mp4 --out clips --events goal --top 5" in readme
    assert "-F events=goal,save" in readme
    assert "/highlights/JOB_ID?event=goal" in readme


def test_t012_ac13_event_filter_on_persisted_api_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    entries = [
        {"start": 1, "end": 3, "score": 5, "reason": "g", "event": "goal",
         "event_confidence": 0.9, "file": "clip_01.mp4"},
        {"start": 5, "end": 7, "score": 2, "reason": "o", "event": "other",
         "event_confidence": 0.0, "file": "clip_02.mp4"},
        {"start": 8, "end": 9, "score": 3, "reason": "s", "event": "save",
         "event_confidence": 0.4, "file": "clip_03.mp4"},
    ]
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: entries)
    monkeypatch.setattr(media, "probe_duration", lambda path: 10.0)
    client = TestClient(api.app)
    job_id = client.post("/highlights", files={"file": ("x.mp4", b"data")}).json()["job_id"]
    for query, starts in (("", [1, 5, 8]), ("?event=goal", [1]), ("?event=save,goal", [1, 8]),
                          ("?event=red_card", []), ("?event=", [1, 5, 8])):
        response = client.get(f"/highlights/{job_id}{query}")
        assert response.status_code == 200
        highlights = response.json()["highlights"]
        assert [item["start"] for item in highlights] == starts
        assert all(list(item) == [
            "start", "end", "score", "reason", "event", "event_confidence", "clip_url"
        ] for item in highlights)
    goal = client.get(f"/highlights/{job_id}?event=goal").json()["highlights"][0]
    assert (goal["event"], goal["event_confidence"]) == ("goal", 0.9)
    assert client.get(f"/highlights/{job_id}?event=penalty").status_code == 422


def test_t012_ac16_spec_updates_keep_unrelated_criteria() -> None:
    specs = Path(__file__).parents[1] / "docs" / "superpowers" / "specs"

    def ac_line(prefix: str, ac: str) -> str:
        (path,) = specs.glob(f"{prefix}*-design.md")
        return next(line for line in path.read_text().splitlines() if line.startswith(f"- {ac}:"))

    t005 = ac_line("2026-11-23-t-005-", "AC2")
    for phrase in ("returns 200", "str(uuid.UUID(job_id))", "has 3 items", "(20,21), (50,51), (75,76)",
                   "with `file` removed, in the same order", "bytes equal burst_video's bytes",
                   "{start, end, score, reason, event, event_confidence, clip_url}"):
        assert phrase in t005, phrase
    t010_ac1 = ac_line("2026-11-23-t-010-", "AC1")
    for phrase in ("`event='goal'` round-trips", "np.str_('save')", "('penalty', 'Goal', '')",
                   "'event':'other','event_confidence':0.0}"):
        assert phrase in t010_ac1, phrase
    t010_ac2 = ac_line("2026-11-23-t-010-", "AC2")
    assert "The full `python -m pytest -q` passes" in t010_ac2
    assert "{start,end,score,reason,event,event_confidence,clip_url}" in t010_ac2
    assert "unchanged ({start,end,score,reason,clip_url})" not in t010_ac2
    t004 = ac_line("2026-11-23-t-004-", "AC1")
    assert "not a subclass of MediaError or ValueError" in t004
    assert "json.loads(<out_dir>/highlights.json)" in t004
    (t007,) = specs.glob("2026-11-23-t-007-*-design.md")
    headings = [line for line in t007.read_text().splitlines() if line.startswith("## ")]
    assert headings[-1] == "## Updated by T-012"
    (t012,) = specs.glob("2026-11-23-t-012-*-design.md")
    for path in (t007, t012):
        text = path.read_text()
        assert "Pre-T-007 manifest-only jobs remain readable" not in text
        assert "legacy manifest-only jobs" not in text

