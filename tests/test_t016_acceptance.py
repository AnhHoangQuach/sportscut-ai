"""Independent acceptance coverage for T-016.

These tests exercise public HTTP routes and the browser-facing pure JavaScript
module from the acceptance criteria, independently of the developer tests.
"""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from sportscut import media, pipeline
from sportscut.api import app
from sportscut.models import Segment


ROOT = Path(__file__).resolve().parents[1]
FILTERS_JS = ROOT / "sportscut" / "web" / "filters.js"
PREVIEW_JS = ROOT / "sportscut" / "web" / "preview.js"

EVENTS = ["goal", "save", "red_card", "controversy", "other"]
LABELS = {
    "goal": "Bàn thắng",
    "save": "Cứu thua",
    "red_card": "Thẻ đỏ",
    "controversy": "Tranh cãi",
    "other": "Khác",
}


class _HTMLSnapshot(HTMLParser):
    """Small stdlib parser used to inspect the served user interface."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[dict[str, Any]] = []
        self._open: list[int] = []
        self._templates: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "template":
            self._templates.append(values.get("id"))
        element = {
            "tag": tag,
            "attrs": values,
            "text": "",
            "template": self._templates[-1] if self._templates else None,
        }
        self.elements.append(element)
        if tag not in self.VOID:
            self._open.append(len(self.elements) - 1)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        for index in self._open:
            self.elements[index]["text"] += data

    def handle_endtag(self, tag: str) -> None:
        for offset in range(len(self._open) - 1, -1, -1):
            if self.elements[self._open[offset]]["tag"] == tag:
                del self._open[offset:]
                break
        if tag == "template" and self._templates:
            self._templates.pop()

    def find(self, *, tag: str | None = None, element_id: str | None = None) -> list[dict[str, Any]]:
        return [
            element
            for element in self.elements
            if (tag is None or element["tag"] == tag)
            and (element_id is None or element["attrs"].get("id") == element_id)
        ]


def _parse_html(text: str) -> _HTMLSnapshot:
    snapshot = _HTMLSnapshot()
    snapshot.feed(text)
    return snapshot


def _node_json(script: str) -> Any:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required on PATH")
    completed = subprocess.run(
        [node, "-e", script],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    lines = completed.stdout.splitlines()
    assert len(lines) == 1, "requiring filters.js must not print extra output"
    return json.loads(lines[0])


def _detected_segments(*_args: Any, **_kwargs: Any) -> list[Segment]:
    return [
        Segment(0.5, 1.5, 2.0, "crowd", event="other"),
        Segment(2.0, 3.0, 1.0, "crowd", event="goal"),
        Segment(3.5, 4.5, 3.0, "crowd", event="save"),
        Segment(4.6, 5.6, 1.5, "crowd", event="goal"),
    ]


def _post_video(
    client: TestClient,
    video: Path,
    **fields: str,
) -> dict[str, Any]:
    response = client.post(
        "/highlights",
        files={"file": ("match.mp4", video.read_bytes(), "video/mp4")},
        data={"min_len": "0.5", "max_len": "1.0", **fields},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _job_dir(data_dir: Path, job_id: str) -> Path:
    matches = [path for path in data_dir.rglob(job_id) if path.is_dir()]
    assert len(matches) == 1
    return matches[0]


def _write_handmade_job(data_dir: Path) -> str:
    job_id = str(uuid4())
    job_dir = data_dir / "jobs" / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "source_name": "match.mp4",
                "source_url": None,
                "duration": 6.0,
                "version": 0,
                "segments": [],
            }
        ),
        encoding="utf-8",
    )
    return job_id


def test_t016_filter_module_public_contract_and_purity() -> None:
    source = FILTERS_JS.read_text(encoding="utf-8")
    for forbidden in (
        "document",
        "window",
        "fetch",
        "localStorage",
        "XMLHttpRequest",
        "http://",
        "https://",
    ):
        assert forbidden not in source

    result = _node_json(
        """
        const F = require('./sportscut/web/filters.js');
        console.log(JSON.stringify({
          sameObject: F === globalThis.SportsCutFilter,
          keys: Object.keys(F).sort(),
          types: F.EVENT_TYPES,
          labels: F.EVENT_LABELS,
          priorities: F.EVENT_PRIORITY,
          presets: F.PRESETS,
          frozen: Object.values(F.PRESETS).every(
            (preset) => Object.isFrozen(preset) && Object.isFrozen(preset.events)
          ),
          normalized: [
            F.normalizeEvent('goal'), F.normalizeEvent('save'),
            F.normalizeEvent('red_card'), F.normalizeEvent('controversy'),
            F.normalizeEvent(undefined), F.normalizeEvent(null),
            F.normalizeEvent(''), F.normalizeEvent('penalty')
          ],
          eventLabels: ['goal', 'save', 'red_card', 'controversy', undefined]
            .map((event) => F.eventLabel(event))
        }));
        """
    )
    assert result == {
        "sameObject": True,
        "keys": [
            "EVENT_LABELS",
            "EVENT_PRIORITY",
            "EVENT_TYPES",
            "PRESETS",
            "eventLabel",
            "normalizeEvent",
            "sameSelection",
            "selectIndices",
            "toggleEvent",
        ],
        "types": EVENTS,
        "labels": LABELS,
        "priorities": {"goal": 5, "red_card": 4, "controversy": 3, "save": 2, "other": 1},
        "presets": {
            "all": {"events": [], "top": None},
            "goals": {"events": ["goal"], "top": None},
            "top5": {"events": [], "top": 5},
        },
        "frozen": True,
        "normalized": ["goal", "save", "red_card", "controversy", "other", "other", "other", "other"],
        "eventLabels": ["Bàn thắng", "Cứu thua", "Thẻ đỏ", "Tranh cãi", "Khác"],
    }


def test_t016_filter_selection_ranking_edges_and_immutability() -> None:
    result = _node_json(
        """
        const F = require('./sportscut/web/filters.js');
        const worked = [
          {start:0,end:10,score:2,event:'other'},
          {start:15,end:25,score:1,event:'save'},
          {start:30,end:40,score:2,event:'goal'},
          {start:50,end:60,score:1.5,event:'save'},
          {start:70,end:80,score:2,event:'red_card'},
          {start:85,end:95,score:3,event:'other'},
          {start:100,end:110,score:null,event:'controversy'}
        ];
        const before = JSON.stringify(worked);
        const inputSelection = {events:['save'], top:5};
        const inputBefore = JSON.stringify(inputSelection);
        const invalid = [0, -1, 2.5, '5', NaN].map((top) => {
          try { F.selectIndices(worked, {events:[], top}); return null; }
          catch (error) { return [error.name, error.message]; }
        });
        const unknown = [
          {start:0,end:0.001,score:1},
          {start:1,end:1.001,score:1,event:'penalty'}
        ];
        const nanStarts = [
          {start:Number.NaN,end:2,score:1,event:'other'},
          {start:1,end:2,score:1,event:'other'}
        ];
        console.log(JSON.stringify({
          selections: [
            F.selectIndices(worked, F.PRESETS.top5),
            F.selectIndices(worked, F.PRESETS.goals),
            F.selectIndices(worked, F.PRESETS.all),
            F.selectIndices(worked, null),
            F.selectIndices(worked, undefined),
            F.selectIndices(worked, {events:[],top:2}),
            F.selectIndices(worked, {events:[],top:3}),
            F.selectIndices(worked, {events:['save'],top:1}),
            F.selectIndices(worked, {events:['other'],top:1}),
            F.selectIndices(worked, {events:['controversy'],top:null}),
            F.selectIndices(worked, {events:['goal','save'],top:null}),
            F.selectIndices(worked, {events:['goal'],top:5})
          ],
          tie: F.selectIndices([
            {start:30,end:31,score:1,event:'other'},
            {start:10,end:11,score:1,event:'other'}
          ], {events:[],top:1}),
          unknown: F.selectIndices(unknown, {events:['other'],top:null}),
          nanStart: F.selectIndices(nanStarts, {events:[],top:1}),
          empty: F.selectIndices([], {events:[],top:1}),
          invalid,
          unchanged: before === JSON.stringify(worked),
          toggledOn: F.toggleEvent(inputSelection, 'goal'),
          toggledOff: F.toggleEvent(inputSelection, 'save'),
          frozenToggle: F.toggleEvent(F.PRESETS.all, 'goal'),
          selectionUnchanged: inputBefore === JSON.stringify(inputSelection),
          same: F.sameSelection(
            {events:['save','goal'],top:null}, {events:['goal','save'],top:null}
          ),
          differentTop: F.sameSelection(
            {events:['goal'],top:null}, {events:['goal'],top:5}
          ),
          differentEvents: F.sameSelection(
            {events:['goal'],top:null}, {events:['save'],top:null}
          ),
          topAfterFilter: F.selectIndices([
            {start:0,end:1,score:100,event:'save'},
            {start:1,end:2,score:1,event:'goal'},
            {start:2,end:3,score:2,event:'goal'}
          ], {events:['goal'],top:1})
        }));
        """
    )
    assert result["selections"] == [
        [1, 2, 3, 4, 5],
        [2],
        [0, 1, 2, 3, 4, 5, 6],
        [0, 1, 2, 3, 4, 5, 6],
        [0, 1, 2, 3, 4, 5, 6],
        [2, 4],
        [2, 3, 4],
        [3],
        [5],
        [6],
        [1, 2, 3],
        [2],
    ]
    assert result["tie"] == [1]
    assert result["unknown"] == [0, 1]
    assert result["nanStart"] == [1]
    assert result["empty"] == []
    assert result["invalid"] == [["RangeError", "top must be a positive integer"]] * 5
    assert result["unchanged"] is True
    assert result["toggledOn"] == {"events": ["goal", "save"], "top": 5}
    assert result["toggledOff"] == {"events": [], "top": 5}
    assert result["frozenToggle"] == {"events": ["goal"], "top": None}
    assert result["selectionUnchanged"] is True
    assert result["same"] is True
    assert result["differentTop"] is False
    assert result["differentEvents"] is False
    assert result["topAfterFilter"] == [2]


def test_t016_preview_and_upload_pages_expose_accessible_filter_controls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    job_id = _write_handmade_job(tmp_path)
    client = TestClient(app)

    preview_response = client.get(f"/jobs/{job_id}")
    assert preview_response.status_code == 200
    assert preview_response.headers["content-type"].startswith("text/html")
    preview = _parse_html(preview_response.text)

    filters = preview.find(element_id="filters")
    assert len(filters) == 1
    assert filters[0]["attrs"]["role"] == "group"
    assert filters[0]["attrs"]["aria-label"] == "Lọc theo sự kiện"
    all_button = preview.find(tag="button", element_id="filter-all")
    assert len(all_button) == 1
    assert all_button[0]["attrs"]["aria-pressed"] == "true"
    assert all_button[0]["text"].strip() == "Tất cả"

    chips = [
        item
        for item in preview.find(tag="button")
        if "chip" in item["attrs"].get("class", "").split()
    ]
    assert [(item["attrs"].get("data-event"), item["text"].strip()) for item in chips] == [
        (event, LABELS[event]) for event in EVENTS
    ]
    assert all(item["attrs"].get("aria-pressed") == "false" for item in chips)
    assert preview.find(tag="button", element_id="preset-goals")[0]["text"].strip() == "Chỉ bàn thắng"
    assert preview.find(tag="button", element_id="preset-top5")[0]["text"].strip() == "Top 5 pha hay"
    assert len(preview.find(tag="output", element_id="filter-count")) == 1
    badges = [
        item
        for item in preview.find()
        if "event-badge" in item["attrs"].get("class", "").split()
    ]
    assert len(badges) == 1
    assert badges[0]["template"] == "segment-row"

    resources = [
        item["attrs"].get("href") if item["tag"] == "link" else item["attrs"].get("src")
        for item in preview.elements
        if (item["tag"] == "link" and item["attrs"].get("rel") == "stylesheet")
        or item["tag"] == "script"
    ]
    assert resources == [
        "/static/style.css",
        "/static/timefmt.js",
        "/static/filters.js",
        "/static/metafmt.js",
        "/static/preview.js",
    ]
    scripts = preview.find(tag="script")
    assert all("defer" in item["attrs"] for item in scripts)
    assert preview.find(tag="a")[0]["attrs"].get("href") == "/"
    static_response = client.get("/static/filters.js")
    assert static_response.status_code == 200
    assert "javascript" in static_response.headers["content-type"]

    upload_response = client.get("/")
    assert upload_response.status_code == 200
    upload = _parse_html(upload_response.text)
    checkboxes = [
        item
        for item in upload.find(tag="input")
        if item["attrs"].get("name") == "events"
    ]
    assert [item["attrs"].get("id") for item in checkboxes] == [f"event-{event}" for event in EVENTS]
    assert [item["attrs"].get("value") for item in checkboxes] == EVENTS
    assert all(item["attrs"].get("type") == "checkbox" for item in checkboxes)
    assert all("checked" not in item["attrs"] for item in checkboxes)
    labels = {
        item["attrs"].get("for"): item["text"].strip()
        for item in upload.find(tag="label")
    }
    assert {f"event-{event}": labels[f"event-{event}"] for event in EVENTS} == {
        f"event-{event}": LABELS[event] for event in EVENTS
    }
    upload_resources = [
        item["attrs"].get("href") if item["tag"] == "link" else item["attrs"].get("src")
        for item in upload.elements
        if (item["tag"] == "link" and item["attrs"].get("rel") == "stylesheet")
        or item["tag"] == "script"
    ]
    assert upload_resources == ["/static/style.css", "/static/app.js"]


def test_t016_preview_javascript_keeps_hidden_segments_and_upload_sends_events() -> None:
    source = PREVIEW_JS.read_text(encoding="utf-8")
    for marker in (
        "const F = globalThis.SportsCutFilter",
        "F.selectIndices(segments, selection)",
        "if (!shown.has(index)) return",
        "F.eventLabel(",
        "F.normalizeEvent(event)",
        "F.toggleEvent(selection",
        "F.PRESETS.goals",
        "F.PRESETS.top5",
        "F.sameSelection(",
        "aria-pressed",
        "Đang hiện",
        "Không có đoạn nào khớp bộ lọc.",
        "({ start, end, reason, event })",
        "segments.splice(index, 1)",
    ):
        assert marker in source

    add_start = source.index('addSegment.addEventListener("click"')
    save_start = source.index('save.addEventListener("click"')
    assert "selection = F.PRESETS.all" in source[add_start:save_start]
    put_fetch = source.index("fetch(", save_start)
    save_before_fetch = source[save_start:put_fetch]
    assert "T.validateSegments(segments, duration)" in save_before_fetch
    assert "selectIndices" not in save_before_fetch

    app_source = (ROOT / "sportscut" / "web" / "app.js").read_text(encoding="utf-8")
    query = "document.querySelectorAll('input[name=\"events\"]:checked')"
    append = 'if (events) formData.append("events", events)'
    assert query in app_source
    assert '.join(",")' in app_source
    assert append in app_source
    assert app_source.index(append) < app_source.index('fetch("/highlights"')


def test_t016_http_filters_ranks_exports_and_put_keeps_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic_video: Path,
) -> None:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline, "find_highlights", _detected_segments)
    client = TestClient(app)

    goals = _post_video(client, synthetic_video, events="goal")
    assert [item["event"] for item in goals["highlights"]] == ["goal", "goal"]
    assert [item["start"] for item in goals["highlights"]] == [2.0, 4.6]
    for number, item in enumerate(goals["highlights"]):
        clip_response = client.get(item["clip_url"])
        assert clip_response.status_code == 200
        assert clip_response.headers["content-type"].startswith("video/mp4")
        clip_path = tmp_path / f"downloaded-{number}.mp4"
        clip_path.write_bytes(clip_response.content)
        assert media.probe_duration(clip_path) == pytest.approx(1.0, abs=0.5)
    goals_job = json.loads((_job_dir(tmp_path, goals["job_id"]) / "job.json").read_text(encoding="utf-8"))
    assert [item["event"] for item in goals_job["segments"]] == ["goal", "goal"]
    assert client.get(f'/highlights/{goals["job_id"]}').json()["highlights"] == goals["highlights"]

    top = _post_video(client, synthetic_video, top="2")
    assert [(item["start"], item["event"]) for item in top["highlights"]] == [
        (3.5, "save"),
        (4.6, "goal"),
    ]

    editable = _post_video(client, synthetic_video, top="10")
    put_response = client.put(
        f'/highlights/{editable["job_id"]}/segments',
        json={
            "segments": [
                {"start": 2.0, "end": 3.0, "reason": "x", "event": "goal"},
                {"start": 0.5, "end": 1.5},
                {"start": 3.5, "end": 4.5, "event": None},
            ]
        },
    )
    assert put_response.status_code == 200, put_response.text
    edited = put_response.json()["highlights"]
    assert [item["start"] for item in edited] == [0.5, 2.0, 3.5]
    assert [item["event"] for item in edited] == ["other", "goal", "other"]
    assert all(item["score"] is None for item in edited)
    assert all(item["event_confidence"] == 0.0 for item in edited)
    persisted = json.loads((_job_dir(tmp_path, editable["job_id"]) / "job.json").read_text(encoding="utf-8"))
    assert [item["event"] for item in persisted["segments"]] == ["other", "goal", "other"]
    only_goal = client.get(f'/highlights/{editable["job_id"]}?event=goal')
    assert only_goal.status_code == 200
    assert [(item["start"], item["event"]) for item in only_goal.json()["highlights"]] == [(2.0, "goal")]


def test_t016_put_rejects_invalid_events_without_touching_exported_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic_video: Path,
) -> None:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline, "find_highlights", _detected_segments)
    client = TestClient(app)
    created = _post_video(client, synthetic_video, top="10")
    job_dir = _job_dir(tmp_path, created["job_id"])
    before = {
        path.relative_to(job_dir).as_posix(): path.read_bytes()
        for path in job_dir.rglob("*")
        if path.is_file()
    }

    def unexpected_export(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("invalid input reached export.export_clips")

    monkeypatch.setattr("sportscut.api.export.export_clips", unexpected_export)
    invalid_items = [
        {"start": 0.5, "end": 1.5, "event": "penalty"},
        {"start": 0.5, "end": 1.5, "event": "Goal"},
        {"start": 0.5, "end": 1.5, "event": 1},
        {"start": 0.5, "end": 1.5, "extra": "forbidden"},
    ]
    for item in invalid_items:
        response = client.put(
            f'/highlights/{created["job_id"]}/segments',
            json={"segments": [item]},
        )
        assert response.status_code == 422, response.text
        after = {
            path.relative_to(job_dir).as_posix(): path.read_bytes()
            for path in job_dir.rglob("*")
            if path.is_file()
        }
        assert after == before


def test_t016_documentation_explains_view_only_filters_and_contract_updates() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    heading = "## Trang web: tải lên, xem trước và chỉnh mốc cắt"
    start = readme.index(heading)
    next_heading = readme.find("\n## ", start + len(heading))
    section = readme[start:] if next_heading == -1 else readme[start:next_heading]
    for marker in ("Chỉ bàn thắng", "Top 5 pha hay", "Tất cả", "Bàn thắng", "Lưu"):
        assert marker in section
    assert "ẩn" in section.lower()
    assert "vẫn" in section.lower()
    assert "![" not in section

    for relative in (
        "docs/superpowers/specs/2026-11-23-t-007-add-job-read-source-streaming-and-design.md",
        "docs/superpowers/specs/2026-11-23-t-009-build-the-preview-page-with-manual-design.md",
    ):
        spec = (ROOT / relative).read_text(encoding="utf-8")
        update = spec[spec.index("## Updated by T-016") :]
        assert "event" in update
