import json
from pathlib import Path
import re
import shutil
import subprocess
import uuid

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from sportscut import api, media, pipeline
from sportscut.models import Segment


WEB_DIR = Path(__file__).parents[1] / "sportscut" / "web"


def _event_segments(*_args, **_kwargs) -> list[Segment]:
    return [
        Segment(0.5, 1.5, 2.0, "other", event="other"),
        Segment(2.0, 3.0, 1.0, "goal one", event="goal"),
        Segment(3.5, 4.5, 3.0, "save", event="save"),
        Segment(4.6, 5.6, 1.5, "goal two", event="goal"),
    ]


def _create_event_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic_video: Path,
) -> tuple[TestClient, dict]:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline, "find_highlights", _event_segments)
    client = TestClient(api.app)
    with synthetic_video.open("rb") as upload:
        response = client.post(
            "/highlights",
            files={"file": ("match.mp4", upload, "video/mp4")},
            data={"min_len": "0.5", "max_len": "1.0"},
        )
    assert response.status_code == 200, response.text
    return client, response.json()


def _write_hand_job(data_dir: Path, job_id: str) -> None:
    job_dir = data_dir / "jobs" / job_id
    job_dir.mkdir(parents=True)
    job = {
        "source_name": "match.mp4",
        "source_url": None,
        "duration": 6.0,
        "version": 0,
        "segments": [{
            "start": 0.5,
            "end": 1.5,
            "score": 2.0,
            "reason": "detected",
            "event": "goal",
            "event_confidence": 0.8,
            "file": "clip_01.mp4",
        }],
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")


def test_post_events_goal_returns_only_goal_clips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic_video: Path,
) -> None:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline, "find_highlights", _event_segments)
    client = TestClient(api.app)

    with synthetic_video.open("rb") as upload:
        response = client.post(
            "/highlights",
            files={"file": ("match.mp4", upload, "video/mp4")},
            data={
                "events": "goal",
                "min_len": "0.5",
                "max_len": "1.0",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    highlights = body["highlights"]
    assert [item["event"] for item in highlights] == ["goal", "goal"]
    assert [item["start"] for item in highlights] == [2.0, 4.6]
    for index, item in enumerate(highlights):
        clip = client.get(item["clip_url"])
        assert clip.status_code == 200
        assert clip.headers["content-type"].startswith("video/mp4")
        clip_path = tmp_path / f"download-{index}.mp4"
        clip_path.write_bytes(clip.content)
        assert media.probe_duration(clip_path) == pytest.approx(1.0, abs=0.5)

    job_path = tmp_path / "jobs" / body["job_id"] / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert [item["event"] for item in job["segments"]] == ["goal", "goal"]
    loaded = client.get(f"/highlights/{body['job_id']}")
    assert loaded.status_code == 200
    assert loaded.json()["highlights"] == highlights


def test_post_top_ranks_by_event_priority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic_video: Path,
) -> None:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(pipeline, "find_highlights", _event_segments)
    client = TestClient(api.app)

    with synthetic_video.open("rb") as upload:
        response = client.post(
            "/highlights",
            files={"file": ("match.mp4", upload, "video/mp4")},
            data={"top": "2", "min_len": "0.5", "max_len": "1.0"},
        )

    assert response.status_code == 200, response.text
    highlights = response.json()["highlights"]
    assert [item["start"] for item in highlights] == [3.5, 4.6]
    assert [item["event"] for item in highlights] == ["save", "goal"]


def _node_eval(tmp_path: Path, expression: str) -> object:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required on PATH")
    runner = tmp_path / "filters-runner.js"
    runner.write_text(
        "const F = require(process.argv[2])\n"
        f"console.log(JSON.stringify({expression}))\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [node, str(runner), str(WEB_DIR / "filters.js")],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_filters_module_is_pure_and_exports_constants(tmp_path: Path) -> None:
    source = (WEB_DIR / "filters.js").read_text(encoding="utf-8")
    for forbidden in (
        "document", "window", "fetch", "localStorage", "XMLHttpRequest",
        "http://", "https://",
    ):
        assert forbidden not in source

    actual = _node_eval(tmp_path, """({
      sameObject: F === globalThis.SportsCutFilter,
      eventTypes: F.EVENT_TYPES,
      eventLabels: F.EVENT_LABELS,
      eventPriority: F.EVENT_PRIORITY,
      presets: F.PRESETS,
      frozen: Object.values(F.PRESETS).map(
        (preset) => Object.isFrozen(preset) && Object.isFrozen(preset.events),
      ),
    })""")
    assert actual == {
        "sameObject": True,
        "eventTypes": ["goal", "save", "red_card", "controversy", "other"],
        "eventLabels": {
            "goal": "Bàn thắng",
            "save": "Cứu thua",
            "red_card": "Thẻ đỏ",
            "controversy": "Tranh cãi",
            "other": "Khác",
        },
        "eventPriority": {
            "goal": 5,
            "red_card": 4,
            "controversy": 3,
            "save": 2,
            "other": 1,
        },
        "presets": {
            "all": {"events": [], "top": None},
            "goals": {"events": ["goal"], "top": None},
            "top5": {"events": [], "top": 5},
        },
        "frozen": [True, True, True],
    }

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required on PATH")
    loaded = subprocess.run(
        [node, "-e", "require(process.argv[1])", str(WEB_DIR / "filters.js")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert loaded.returncode == 0, loaded.stderr
    assert loaded.stdout == ""


def test_filters_normalize_and_label(tmp_path: Path) -> None:
    actual = _node_eval(tmp_path, """(() => {
      const values = ["goal", "save", "red_card", "controversy", undefined, null, "", "penalty"]
      return values.map((event) => [F.normalizeEvent(event), F.eventLabel(event)])
    })()""")
    assert actual == [
        ["goal", "Bàn thắng"],
        ["save", "Cứu thua"],
        ["red_card", "Thẻ đỏ"],
        ["controversy", "Tranh cãi"],
        ["other", "Khác"],
        ["other", "Khác"],
        ["other", "Khác"],
        ["other", "Khác"],
    ]


def test_filters_select_indices_worked_list(tmp_path: Path) -> None:
    actual = _node_eval(tmp_path, """(() => {
      const segments = [
        {start: 0, end: 10, score: 2, event: "other"},
        {start: 15, end: 25, score: 1, event: "save"},
        {start: 30, end: 40, score: 2, event: "goal"},
        {start: 50, end: 60, score: 1.5, event: "save"},
        {start: 70, end: 80, score: 2, event: "red_card"},
        {start: 85, end: 95, score: 3, event: "other"},
        {start: 100, end: 110, score: null, event: "controversy"},
      ]
      const before = JSON.stringify(segments)
      const selections = [
        F.PRESETS.top5,
        F.PRESETS.goals,
        F.PRESETS.all,
        null,
        undefined,
        {events: [], top: 2},
        {events: [], top: 3},
        {events: ["save"], top: 1},
        {events: ["other"], top: 1},
        {events: ["controversy"], top: null},
        {events: ["goal", "save"], top: null},
        {events: ["goal"], top: 5},
      ]
      const selected = selections.map((selection) => F.selectIndices(segments, selection))
      return {selected, unchanged: before === JSON.stringify(segments)}
    })()""")
    assert actual == {
        "selected": [
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
        ],
        "unchanged": True,
    }


def test_filters_select_indices_ties_and_errors(tmp_path: Path) -> None:
    actual = _node_eval(tmp_path, """(() => {
      const errors = [0, -1, 2.5, "5", NaN].map((top) => {
        try { F.selectIndices([], {events: [], top}); return null }
        catch (error) { return [error.name, error.message] }
      })
      return {
        tie: F.selectIndices([
          {start: 30, end: 31, score: 1, event: "other"},
          {start: 10, end: 11, score: 1, event: "other"},
        ], {events: [], top: 1}),
        legacy: F.selectIndices([
          {start: 0, end: 1, score: 1},
          {start: 2, end: 3, score: 1, event: "penalty"},
        ], {events: ["other"], top: null}),
        nonFiniteTime: F.selectIndices([
          {start: NaN, end: 1, score: 1, event: "other"},
          {start: 2, end: 3, score: 1, event: "other"},
        ], {events: [], top: 1}),
        empty: F.selectIndices([], F.PRESETS.all),
        errors,
      }
    })()""")
    assert actual == {
        "tie": [1],
        "legacy": [0, 1],
        "nonFiniteTime": [1],
        "empty": [],
        "errors": [
            ["RangeError", "top must be a positive integer"],
            ["RangeError", "top must be a positive integer"],
            ["RangeError", "top must be a positive integer"],
            ["RangeError", "top must be a positive integer"],
            ["RangeError", "top must be a positive integer"],
        ],
    }


def test_filters_toggle_and_same_selection(tmp_path: Path) -> None:
    actual = _node_eval(tmp_path, """(() => {
      const original = {events: ["save"], top: 5}
      const added = F.toggleEvent(original, "goal")
      const removed = F.toggleEvent(original, "save")
      const fromFrozen = F.toggleEvent(F.PRESETS.all, "goal")
      return {
        original,
        added,
        removed,
        fromFrozen,
        newObjects: added !== original && removed !== original && fromFrozen !== F.PRESETS.all,
        sameSet: F.sameSelection(
          {events: ["save", "goal"], top: null},
          {events: ["goal", "save"], top: null},
        ),
        differentTop: F.sameSelection(
          {events: ["goal"], top: null}, {events: ["goal"], top: 5},
        ),
        differentEvents: F.sameSelection(
          {events: ["goal"], top: null}, {events: ["save"], top: null},
        ),
      }
    })()""")
    assert actual == {
        "original": {"events": ["save"], "top": 5},
        "added": {"events": ["goal", "save"], "top": 5},
        "removed": {"events": [], "top": 5},
        "fromFrozen": {"events": ["goal"], "top": None},
        "newObjects": True,
        "sameSet": True,
        "differentTop": False,
        "differentEvents": False,
    }


def test_preview_page_serves_filter_controls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    job_id = str(uuid.uuid4())
    _write_hand_job(tmp_path, job_id)
    client = TestClient(api.app)

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    html = response.text
    assert 'id="filters" role="group" aria-label="Lọc theo sự kiện"' in html
    assert 'id="filter-all" aria-pressed="true">Tất cả</button>' in html
    chips = (
        ("goal", "Bàn thắng"),
        ("save", "Cứu thua"),
        ("red_card", "Thẻ đỏ"),
        ("controversy", "Tranh cãi"),
        ("other", "Khác"),
    )
    assert html.count('class="chip"') == 5
    for event, label in chips:
        assert (
            f'class="chip" data-event="{event}" aria-pressed="false">'
            f"{label}</button>"
        ) in html
    assert 'id="preset-goals" aria-pressed="false">Chỉ bàn thắng</button>' in html
    assert 'id="preset-top5" aria-pressed="false">Top 5 pha hay</button>' in html
    assert 'id="filter-count"' in html
    template = html.split('<template id="segment-row">', 1)[1].split("</template>", 1)[0]
    assert 'class="event-badge"' in template
    assert html.index('<a href="/">') == html.index("<a ")
    assert (
        html.index('href="/static/style.css"')
        < html.index('src="/static/timefmt.js" defer')
        < html.index('src="/static/filters.js" defer')
        < html.index('src="/static/preview.js" defer')
    )

    static = client.get("/static/filters.js")
    assert static.status_code == 200
    assert "javascript" in static.headers["content-type"]


def test_preview_js_filter_contract() -> None:
    source = (WEB_DIR / "preview.js").read_text(encoding="utf-8")
    for marker in (
        "const F = globalThis.SportsCutFilter",
        "let selection = F.PRESETS.all",
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

    add_at = source.index('addSegment.addEventListener("click"')
    save_at = source.index('save.addEventListener("click"')
    assert "selection = F.PRESETS.all" in source[add_at:save_at]
    put_at = source.index(
        "fetch(`/highlights/${encodeURIComponent(jobId)}/segments`", save_at,
    )
    before_put = source[save_at:put_at]
    assert "T.validateSegments(segments, duration)" in before_put
    assert "selectIndices" not in before_put

    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    for marker in (
        "#filters {",
        "display: flex",
        "flex-wrap: wrap",
        "gap: 0.5rem",
        "#filters button {",
        "width: auto",
        '#filters button[aria-pressed="true"] {',
        "background: #1d4ed8",
        "color: #fff",
        ".event-badge {",
        "padding: 0.1rem 0.5rem",
        "border-radius: 999px",
        "background: #e5e7eb",
    ):
        assert marker in css


def test_upload_form_has_event_checkboxes() -> None:
    response = TestClient(api.app).get("/")

    assert response.status_code == 200
    html = response.text
    assert '<fieldset id="events">' in html
    assert "<legend>Chỉ lấy sự kiện (không bắt buộc)</legend>" in html
    options = (
        ("goal", "Bàn thắng"),
        ("save", "Cứu thua"),
        ("red_card", "Thẻ đỏ"),
        ("controversy", "Tranh cãi"),
        ("other", "Khác"),
    )
    assert html.count('name="events" type="checkbox"') == 5
    positions = []
    for event, label in options:
        element_id = f"event-{event}"
        input_match = re.search(
            rf'<input id="{element_id}" name="events" type="checkbox" value="{event}"[^>]*>',
            html,
        )
        assert input_match is not None
        assert "checked" not in input_match.group(0)
        assert f'<label for="{element_id}">{label}</label>' in html
        positions.append(input_match.start())
    assert positions == sorted(positions)
    references = re.findall(r'(?:href|src)="([^"]+)"', html)
    assert references == ["/static/style.css", "/static/app.js"]


def test_app_js_sends_checked_events() -> None:
    source = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    query = "document.querySelectorAll('input[name=\"events\"]:checked')"
    assert query in source
    assert '.join(",")' in source
    append = 'if (events) formData.append("events", events)'
    assert append in source
    assert source.index(append) < source.index('fetch("/highlights"')


def test_readme_documents_event_filters_and_specs_updated() -> None:
    project = WEB_DIR.parents[1]
    readme = (project / "README.md").read_text(encoding="utf-8")
    heading = "## Trang web: tải lên, xem trước và chỉnh mốc cắt"
    section = readme.split(heading, 1)[1].split("\n## ", 1)[0]
    for marker in (
        "Bàn thắng",
        "huy hiệu",
        "Tất cả",
        "Chỉ bàn thắng",
        "Top 5 pha hay",
        "Lưu",
        "bộ lọc chỉ ẩn",
        "vẫn lưu tất cả",
        "liên kết clip",
    ):
        assert marker in section
    assert "![" not in section

    for filename in (
        "2026-11-23-t-007-add-job-read-source-streaming-and-design.md",
        "2026-11-23-t-009-build-the-preview-page-with-manual-design.md",
    ):
        source = (
            project / "docs" / "superpowers" / "specs" / filename
        ).read_text(encoding="utf-8")
        update = source.split("## Updated by T-016", 1)[1]
        assert "event" in update


def test_put_keeps_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic_video: Path,
) -> None:
    client, created = _create_event_job(tmp_path, monkeypatch, synthetic_video)
    job_id = created["job_id"]

    response = client.put(
        f"/highlights/{job_id}/segments",
        json={"segments": [
            {"start": 2.0, "end": 3.0, "reason": "x", "event": "goal"},
            {"start": 0.5, "end": 1.5},
            {"start": 3.5, "end": 4.5, "event": None},
        ]},
    )

    assert response.status_code == 200, response.text
    highlights = response.json()["highlights"]
    assert [item["start"] for item in highlights] == [0.5, 2.0, 3.5]
    assert [item["event"] for item in highlights] == ["other", "goal", "other"]
    assert [item["score"] for item in highlights] == [None, None, None]
    assert [item["event_confidence"] for item in highlights] == [0.0, 0.0, 0.0]

    job_path = tmp_path / "jobs" / job_id / "job.json"
    job = json.loads(job_path.read_text(encoding="utf-8"))
    assert [item["event"] for item in job["segments"]] == ["other", "goal", "other"]
    goals = client.get(f"/highlights/{job_id}?event=goal")
    assert goals.status_code == 200
    assert [(item["start"], item["event"]) for item in goals.json()["highlights"]] == [
        (2.0, "goal"),
    ]


@pytest.mark.parametrize("event", ["penalty", "Goal", 1])
def test_put_rejects_bad_event_without_export(
    event: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic_video: Path,
) -> None:
    client, created = _create_event_job(tmp_path, monkeypatch, synthetic_video)
    job_path = tmp_path / "jobs" / created["job_id"] / "job.json"
    before = job_path.read_bytes()
    monkeypatch.setattr(
        api.export,
        "export_clips",
        lambda *_args, **_kwargs: pytest.fail("export_clips was called"),
    )

    response = client.put(
        f"/highlights/{created['job_id']}/segments",
        json={"segments": [{"start": 1.0, "end": 2.0, "event": event}]},
    )

    assert response.status_code == 422
    assert job_path.read_bytes() == before


def test_put_still_rejects_unknown_segment_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    synthetic_video: Path,
) -> None:
    client, created = _create_event_job(tmp_path, monkeypatch, synthetic_video)
    job_path = tmp_path / "jobs" / created["job_id"] / "job.json"
    before = job_path.read_bytes()
    monkeypatch.setattr(
        api.export,
        "export_clips",
        lambda *_args, **_kwargs: pytest.fail("export_clips was called"),
    )

    response = client.put(
        f"/highlights/{created['job_id']}/segments",
        json={"segments": [{"start": 1.0, "end": 2.0, "extra": True}]},
    )

    assert response.status_code == 422
    assert job_path.read_bytes() == before
