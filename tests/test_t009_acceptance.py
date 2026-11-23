"""Independent acceptance coverage for T-009's preview editing workflow."""

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from sportscut import media
from sportscut.api import app


ROOT = Path(__file__).parents[1]
WEB = ROOT / "sportscut" / "web"
TIMEFMT = WEB / "timefmt.js"


class _Markup(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.nodes: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self.nodes.append((tag, dict(attrs)))

    def find(
        self, *, tag: str | None = None, element_id: str | None = None,
        class_name: str | None = None,
    ) -> dict[str, str | None]:
        for node_tag, attrs in self.nodes:
            classes = (attrs.get("class") or "").split()
            if (
                (tag is None or node_tag == tag)
                and (element_id is None or attrs.get("id") == element_id)
                and (class_name is None or class_name in classes)
            ):
                return attrs
        raise AssertionError(
            f"missing tag={tag!r}, id={element_id!r}, class={class_name!r}"
        )


def _write_job(data_dir: Path, job_id: str) -> None:
    job_dir = data_dir / "jobs" / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "source_name": "acceptance.mp4",
                "source_url": None,
                "duration": 6.0,
                "version": 0,
                "segments": [
                    {
                        "start": 0.5,
                        "end": 1.5,
                        "score": 2.0,
                        "reason": "detected",
                        "file": "clip_01.mp4",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.fixture
def preview_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    with TestClient(app) as client:
        yield client, tmp_path


def _node_json(script: str) -> object:
    node = shutil.which("node")
    assert node is not None, "node is required to verify the browser helper"
    program = f"const T = require({json.dumps(str(TIMEFMT))});\n{script}"
    result = subprocess.run(
        [node, "-e", program],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_preview_route_acceptance(preview_client) -> None:
    client, data_dir = preview_client
    job_id = str(uuid4())
    _write_job(data_dir, job_id)

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.content == (WEB / "preview.html").read_bytes()
    for marker in (
        "<!doctype html>",
        'id="player"',
        'id="segments"',
        'id="save"',
        'id="add-segment"',
    ):
        assert marker in response.text
    assert "/jobs/{job_id}" not in app.openapi()["paths"]


def test_preview_route_rejects_unknown_and_malformed_jobs(preview_client) -> None:
    client, data_dir = preview_client
    existing = str(uuid4())
    _write_job(data_dir, existing)
    missing_json = str(uuid4())
    (data_dir / "jobs" / missing_json).mkdir()
    invalid_json = str(uuid4())
    (data_dir / "jobs" / invalid_json).mkdir()
    (data_dir / "jobs" / invalid_json / "job.json").write_text(
        "{}", encoding="utf-8"
    )

    for candidate in (
        str(uuid4()),
        existing.upper(),
        "not-a-uuid",
        missing_json,
        invalid_json,
    ):
        response = client.get(f"/jobs/{candidate}")
        assert response.status_code == 404, candidate
        assert response.json() == {"detail": "not found"}, candidate


def test_preview_document_and_static_assets_acceptance(preview_client) -> None:
    client, _ = preview_client
    source = (WEB / "preview.html").read_text(encoding="utf-8")
    markup = _Markup()
    markup.feed(source)

    assert markup.find(tag="html")["lang"] == "vi"
    assert (
        source.index('/static/style.css')
        < source.index('/static/timefmt.js')
        < source.index('/static/preview.js')
    )
    for script_name in ("timefmt.js", "preview.js"):
        script = markup.find(tag="script", class_name=None)
        assert script is not None
        response = client.get(f"/static/{script_name}")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"].lower()

    assert "controls" in markup.find(tag="video", element_id="player")
    markup.find(tag="output", element_id="current-time")
    markup.find(tag="ol", element_id="segments")
    markup.find(tag="template", element_id="segment-row")
    for class_name in (
        "play",
        "start",
        "end",
        "start-minus",
        "start-plus",
        "end-minus",
        "end-plus",
        "set-start",
        "set-end",
        "delete",
        "clip",
        "clip-player",
    ):
        markup.find(class_name=class_name)
    assert markup.find(tag="a")["href"] == "/"
    markup.find(tag="button", element_id="add-segment")
    markup.find(tag="button", element_id="save")
    status = markup.find(element_id="status")
    error = markup.find(element_id="error")
    assert status["role"] == "status" and "hidden" in status
    assert error["role"] == "alert" and "hidden" in error
    assert re.search(
        r'<script\s+src="/static/timefmt[.]js"\s+defer(?:="")?\s*>', source
    )
    assert re.search(
        r'<script\s+src="/static/preview[.]js"\s+defer(?:="")?\s*>', source
    )
    for name in ("preview.html", "preview.js", "timefmt.js"):
        asset = (WEB / name).read_text(encoding="utf-8")
        assert "http://" not in asset and "https://" not in asset


def test_time_helpers_acceptance_contract() -> None:
    result = _node_json(
        """
        function errorName(call) {
          try { call(); return null } catch (error) { return error.name }
        }
        console.log(JSON.stringify({
          constants: [T.MAX_SEGMENTS, T.NEW_SEGMENT_SECONDS],
          formatted: [0, 5, 0.04, 65.25, 59.96, 600, 5400, 10800]
            .map((value) => T.formatTime(value)),
          errors: [-1, NaN, Infinity]
            .map((value) => errorName(() => T.formatTime(value))),
          parsed: ["01:05.3", "1:05", "00:00.0", "90:00.0", "75.5",
            " 00:02.5 "].map((value) => T.parseTime(value)),
          rejected: ["1:60", "", "abc", "-1", "1:2:3", "1e3", "00:05,5"]
            .map((value) => T.parseTime(value)).concat([T.parseTime(123)]),
          clamped: [T.clampTime(-0.3, 6), T.clampTime(6.4, 6),
            T.clampTime(2.5, 6)],
          created: [[3, 90], [85, 90], [90, 90], [2, 6], [6, 6]]
            .map(([time, duration]) => T.newSegmentAt(time, duration)),
        }))
        """
    )

    assert result == {
        "constants": [50, 10],
        "formatted": [
            "00:00.0",
            "00:05.0",
            "00:00.0",
            "01:05.3",
            "01:00.0",
            "10:00.0",
            "90:00.0",
            "180:00.0",
        ],
        "errors": ["RangeError", "RangeError", "RangeError"],
        "parsed": [65.3, 65, 0, 5400, 75.5, 2.5],
        "rejected": [None] * 8,
        "clamped": [0, 6, 2.5],
        "created": [
            {"start": 3, "end": 13, "reason": "manual"},
            {"start": 85, "end": 90, "reason": "manual"},
            {"start": 80, "end": 90, "reason": "manual"},
            {"start": 2, "end": 6, "reason": "manual"},
            {"start": 0, "end": 6, "reason": "manual"},
        ],
    }


def test_segment_validation_acceptance_contract() -> None:
    result = _node_json(
        """
        const valid = {start: 0, end: 1}
        console.log(JSON.stringify({
          empty: T.validateSegments([], 6),
          overlap: T.validateSegments([{start: 0, end: 4},
            {start: 2, end: 5}], 6),
          adjacent: T.validateSegments([{start: 0, end: 3},
            {start: 3, end: 6}], 6),
          bounds: [
            {start: 3, end: 3}, {start: -0.1, end: 1},
            {start: 4, end: 3}, {start: 5, end: 6.1}
          ].map((row) => T.validateSegments([row], 6)),
          invalid: [
            T.validateSegments([valid, {start: NaN, end: 2}], 6),
            T.validateSegments([valid, {start: 1, end: "2"}], 6)
          ],
          fifty: T.validateSegments(Array.from({length: 50}, () => valid), 6),
          fiftyOne: T.validateSegments(
            Array.from({length: 51}, () => valid), 6),
        }))
        """
    )
    bounds_message = "Đoạn 1: cần 0 ≤ đầu < cuối ≤ 00:06.0."
    invalid_message = "Đoạn 2: thời gian không hợp lệ."

    assert result["empty"] == []
    assert result["overlap"] == []
    assert result["adjacent"] == []
    assert result["bounds"] == [[bounds_message]] * 4
    assert result["invalid"] == [[invalid_message], [invalid_message]]
    assert result["fifty"] == []
    assert "Tối đa 50 đoạn." in result["fiftyOne"]


def test_time_helper_module_is_pure_acceptance() -> None:
    source = TIMEFMT.read_text(encoding="utf-8")
    for forbidden in ("document", "window", "fetch", "localStorage", "XMLHttpRequest"):
        assert forbidden not in source

    node = shutil.which("node")
    assert node is not None, "node is required to verify the browser helper"
    program = (
        f"const T = require({json.dumps(str(TIMEFMT))});"
        "if (T !== globalThis.SportsCutTime) process.exit(9);"
    )
    result = subprocess.run(
        [node, "-e", program],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_preview_javascript_acceptance_contract() -> None:
    source = (WEB / "preview.js").read_text(encoding="utf-8")
    tick = chr(96)
    dollar = chr(36)
    load_fetch = (
        "fetch(" + tick + "/highlights/" + dollar
        + "{encodeURIComponent(jobId)}" + tick + ")"
    )
    source_url = (
        tick + "/highlights/" + dollar
        + "{encodeURIComponent(jobId)}/source" + tick
    )
    put_fetch = (
        "fetch(" + tick + "/highlights/" + dollar
        + "{encodeURIComponent(jobId)}/segments" + tick + ", {"
    )
    error_text = (
        tick + "Lỗi " + dollar + "{response.status}: "
        + dollar + "{message}" + tick
    )
    expected = (
        r"/^\/jobs\/([^/]+)\/?$/",
        load_fetch,
        source_url,
        put_fetch,
        'method: "PUT"',
        '"Content-Type": "application/json"',
        "({ start, end, reason })",
        "T.validateSegments(segments, duration)",
        "T.newSegmentAt(player.currentTime, duration)",
        "T.clampTime(",
        "T.parseTime(",
        "T.formatTime(",
        "player.play()",
        "player.pause()",
        "data?.detail",
        error_text,
        "save.disabled = true",
        "save.disabled = false",
        "finally",
        "Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ.",
        "Đã lưu",
    )
    for fragment in expected:
        assert fragment in source, fragment

    validate_at = source.index("T.validateSegments(segments, duration)")
    put_at = source.index(put_fetch)
    assert validate_at < put_at
    assert "return" in source[validate_at:put_at]
    assert "http://" not in source and "https://" not in source


def test_preview_styles_acceptance() -> None:
    source = (WEB / "style.css").read_text(encoding="utf-8")
    for fragment in (
        "main.preview",
        "min(100%, 64rem)",
        "#player",
        "width: 100%",
        ".segment",
        "flex-wrap: wrap",
        ".segment input",
        "width: 6.5rem",
        ".clip-player",
        "width: 12rem",
        '[aria-invalid="true"]',
        "2px solid #b42318",
    ):
        assert fragment in source


def test_preview_api_sequence_acceptance(
    preview_client, synthetic_video: Path, tmp_path: Path
) -> None:
    client, _ = preview_client
    with synthetic_video.open("rb") as upload:
        created_response = client.post(
            "/highlights",
            files={"file": ("synthetic.mp4", upload, "video/mp4")},
            data={"top": "1", "min_len": "0.5", "max_len": "1.0"},
        )
    assert created_response.status_code == 200, created_response.text
    created = created_response.json()
    assert len(created["highlights"]) == 1
    job_id = created["job_id"]
    original_clip = created["highlights"][0]["clip_url"]

    page = client.get(f"/jobs/{job_id}")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    loaded = client.get(f"/highlights/{job_id}")
    assert loaded.status_code == 200
    assert loaded.json()["highlights"] == created["highlights"]
    source = client.get(
        f"/highlights/{job_id}/source", headers={"Range": "bytes=0-99"}
    )
    assert source.status_code == 206
    assert len(source.content) == 100

    edited_response = client.put(
        f"/highlights/{job_id}/segments",
        json={
            "segments": [
                {
                    "start": 1.0,
                    "end": 3.5,
                    "reason": created["highlights"][0]["reason"],
                },
                {"start": 4.0, "end": 5.5, "reason": "manual"},
            ]
        },
    )
    assert edited_response.status_code == 200, edited_response.text
    edited = edited_response.json()
    assert [(item["start"], item["end"]) for item in edited["highlights"]] == [
        (1.0, 3.5),
        (4.0, 5.5),
    ]
    expected = (("clip_01_v1.mp4", 2.5), ("clip_02_v1.mp4", 1.5))
    for index, (suffix, duration) in enumerate(expected):
        clip_url = edited["highlights"][index]["clip_url"]
        assert clip_url.endswith(suffix)
        download = client.get(clip_url)
        assert download.status_code == 200
        clip_path = tmp_path / suffix
        clip_path.write_bytes(download.content)
        assert media.probe_duration(clip_path) == pytest.approx(duration, abs=0.5)

    assert client.get(original_clip).status_code == 404
    assert client.get(f"/jobs/{job_id}").status_code == 200
    cleared = client.put(
        f"/highlights/{job_id}/segments", json={"segments": []}
    )
    assert cleared.status_code == 200
    assert cleared.json()["highlights"] == []
    assert client.get(f"/highlights/{job_id}").json()["highlights"] == []
    assert client.get(f"/jobs/{job_id}").status_code == 200


def test_readme_preview_instructions_acceptance() -> None:
    source = (ROOT / "README.md").read_text(encoding="utf-8")
    heading = "## Trang web: tải lên, xem trước và chỉnh mốc cắt"
    assert heading in source
    section = source.split(heading, 1)[1].split("\n## ", 1)[0]
    for text in (
        "pip install -e '.[api,youtube]'",
        "sportscut serve",
        "http://127.0.0.1:8000/",
        "/jobs/JOB_ID",
        "mm:ss.s",
        "Lưu",
    ):
        assert text in section
    assert "![" not in section
