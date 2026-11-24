import json
from pathlib import Path
import shutil
import subprocess
import uuid

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from sportscut import media
from sportscut.api import app


client = TestClient(app)
WEB_DIR = Path(__file__).parents[1] / "sportscut" / "web"


@pytest.fixture
def api_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    return tmp_path


def _write_job(data_dir, job_id):
    job_dir = data_dir / "jobs" / job_id
    job_dir.mkdir(parents=True)
    job = {
        "source_name": "m.mp4", "source_url": None, "duration": 6.0,
        "version": 0, "segments": [{
            "start": 0.5, "end": 1.5, "score": 2.0,
            "reason": "detected", "file": "clip_01.mp4",
        }],
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    return job_dir


def test_preview_page_served_for_existing_job(api_env):
    job_id = str(uuid.uuid4())
    _write_job(api_env, job_id)

    response = client.get(f"/jobs/{job_id}")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    for marker in (
        "<!doctype html>", 'id="player"', 'id="segments"',
        'id="save"', 'id="add-segment"',
    ):
        assert marker in response.text


def test_preview_page_404_for_unknown_or_invalid_ids(api_env):
    existing = str(uuid.uuid4())
    _write_job(api_env, existing)
    missing_manifest = str(uuid.uuid4())
    (api_env / "jobs" / missing_manifest).mkdir(parents=True)
    invalid_manifest = str(uuid.uuid4())
    invalid_dir = api_env / "jobs" / invalid_manifest
    invalid_dir.mkdir(parents=True)
    (invalid_dir / "job.json").write_text("{}", encoding="utf-8")

    for requested in (
        str(uuid.uuid4()), existing.upper(), "not-a-uuid",
        missing_manifest, invalid_manifest,
    ):
        response = client.get(f"/jobs/{requested}")
        assert response.status_code == 404
        assert response.json() == {"detail": "not found"}
    assert "/jobs/{job_id}" not in app.openapi()["paths"]


def test_preview_html_contract():
    html = (WEB_DIR / "preview.html").read_text(encoding="utf-8")
    assert '<html lang="vi">' in html
    style_at = html.index('href="/static/style.css"')
    time_at = html.index('src="/static/timefmt.js" defer')
    preview_at = html.index('src="/static/preview.js" defer')
    assert style_at < time_at < preview_at
    for marker in (
        '<a href="/">', '<video id="player" controls', 'id="current-time"',
        '<ol id="segments">', '<template id="segment-row">',
        'id="add-segment"', 'id="save"',
        'id="status" role="status" hidden',
        'id="error" role="alert" aria-live="assertive" hidden',
    ):
        assert marker in html
    for class_name in (
        "play", "start", "end", "start-minus", "start-plus", "end-minus",
        "end-plus", "set-start", "set-end", "delete", "clip", "clip-player",
    ):
        assert f'class="{class_name}"' in html
    for name in ("preview.html", "preview.js", "timefmt.js"):
        source = (WEB_DIR / name).read_text(encoding="utf-8")
        assert "http://" not in source and "https://" not in source
    for name in ("preview.js", "timefmt.js"):
        response = client.get(f"/static/{name}")
        assert response.status_code == 200
        assert response.headers["content-type"].split(";", 1)[0] in {
            "text/javascript", "application/javascript",
        }


def _node_eval(tmp_path, expression):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required on PATH")
    runner = tmp_path / "runner.js"
    runner.write_text(
        "const T = require(process.argv[2])\n"
        f"console.log(JSON.stringify({expression}))\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [node, str(runner), str(WEB_DIR / "timefmt.js")],
        check=True, capture_output=True, text=True,
    )
    return json.loads(result.stdout)


def test_timefmt_format_time(tmp_path):
    actual = _node_eval(tmp_path, """(() => {
      const values = [0, 5, 0.04, 65.25, 59.96, 600, 5400, 10800]
      const errors = [-1, NaN, Infinity].map((value) => {
        try { T.formatTime(value); return null } catch (error) { return error.name }
      })
      return {formatted: values.map(T.formatTime), errors}
    })()""")
    assert actual == {
        "formatted": [
            "00:00.0", "00:05.0", "00:00.0", "01:05.3",
            "01:00.0", "10:00.0", "90:00.0", "180:00.0",
        ],
        "errors": ["RangeError"] * 3,
    }


def test_timefmt_parse_time(tmp_path):
    actual = _node_eval(tmp_path, """(() => {
      const valid = ["01:05.3", "1:05", "00:00.0", "90:00.0", "75.5", " 00:02.5 "]
      const invalid = ["1:60", "", "abc", "-1", "1:2:3", "1e3", "00:05,5", 2]
      return {valid: valid.map(T.parseTime), invalid: invalid.map(T.parseTime)}
    })()""")
    assert actual["valid"] == pytest.approx([65.3, 65, 0, 5400, 75.5, 2.5])
    assert actual["invalid"] == [None] * 8


def test_timefmt_clamp_and_new_segment(tmp_path):
    actual = _node_eval(tmp_path, """({
      constants: [T.MAX_SEGMENTS, T.NEW_SEGMENT_SECONDS],
      clamped: [[-0.3, 6], [6.4, 6], [2.5, 6]].map((x) => T.clampTime(...x)),
      added: [[3, 90], [85, 90], [90, 90], [2, 6], [6, 6]].map((x) => T.newSegmentAt(...x)),
    })""")
    assert actual == {
        "constants": [50, 10], "clamped": [0, 6, 2.5],
        "added": [
            {"start": 3, "end": 13, "reason": "manual"},
            {"start": 85, "end": 90, "reason": "manual"},
            {"start": 80, "end": 90, "reason": "manual"},
            {"start": 2, "end": 6, "reason": "manual"},
            {"start": 0, "end": 6, "reason": "manual"},
        ],
    }


def test_timefmt_validate_segments(tmp_path):
    actual = _node_eval(tmp_path, """(() => {
      const valid = Array.from({length: 50}, () => ({start: 0, end: 1}))
      return {
        empty: T.validateSegments([], 6),
        overlap: T.validateSegments([{start: 0, end: 3}, {start: 2, end: 4}, {start: 4, end: 6}], 6),
        equal: T.validateSegments([{start: 3, end: 3}], 6),
        negative: T.validateSegments([{start: -1, end: 2}], 6),
        reversed: T.validateSegments([{start: 3, end: 2}], 6),
        beyond: T.validateSegments([{start: 3, end: 7}], 6),
        invalid: T.validateSegments([{start: 0, end: 1}, {start: NaN, end: 2}], 6),
        fifty: T.validateSegments(valid, 6),
        fiftyOne: T.validateSegments([...valid, {start: 0, end: 1}], 6),
      }
    })()""")
    bounds = ["Đoạn 1: cần 0 ≤ đầu < cuối ≤ 00:06.0."]
    assert actual["empty"] == actual["overlap"] == actual["fifty"] == []
    assert actual["equal"] == actual["negative"] == actual["reversed"] == actual["beyond"] == bounds
    assert actual["invalid"] == ["Đoạn 2: thời gian không hợp lệ."]
    assert "Tối đa 50 đoạn." in actual["fiftyOne"]


def test_timefmt_is_pure(tmp_path):
    source = (WEB_DIR / "timefmt.js").read_text(encoding="utf-8")
    for forbidden in ("document", "window", "fetch", "localStorage", "XMLHttpRequest"):
        assert forbidden not in source
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required on PATH")
    result = subprocess.run(
        [node, "-e", "const T=require(process.argv[1]); if(T!==globalThis.SportsCutTime) throw Error()", str(WEB_DIR / "timefmt.js")],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""


def test_preview_js_contract():
    source = (WEB_DIR / "preview.js").read_text(encoding="utf-8")
    for marker in (
        "const T = globalThis.SportsCutTime",
        "location.pathname.match(/^\\/jobs\\/([^/]+)\\/?$/)",
        "decodeURIComponent", "encodeURIComponent(jobId)",
        "fetch(`/highlights/${encodeURIComponent(jobId)}`)",
        "`/highlights/${encodeURIComponent(jobId)}/source`",
        "fetch(`/highlights/${encodeURIComponent(jobId)}/segments`, {",
        'method: "PUT"', '"Content-Type": "application/json"',
        "({ start, end, reason, event })", "T.newSegmentAt(player.currentTime, duration)",
        "T.clampTime(", "T.parseTime(", "T.formatTime(",
        "player.currentTime = seg.start", "player.play()", "player.pause()",
        "playUntil", "clip_url", "segments.splice", "NaN",
        "data?.detail", "`Lỗi ${response.status}: ${message}`",
        "Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ.",
        "Không tìm thấy job.", "save.disabled = true", "save.disabled = false",
        "finally", "Đang cắt lại clip…", "Đã lưu",
    ):
        assert marker in source
    save_at = source.index('save.addEventListener("click"')
    validate_at = source.index("T.validateSegments(segments, duration)", save_at)
    put_at = source.index("fetch(`/highlights/${encodeURIComponent(jobId)}/segments`", save_at)
    assert validate_at < put_at
    load_at = source.index("async function loadJob()")
    initial_disable_at = source.index(
        "save.disabled = true\naddSegment.disabled = true"
    )
    accepted_at = source.index("acceptResponse(data)", load_at)
    enable_at = source.index(
        "save.disabled = false\n    addSegment.disabled = false", accepted_at
    )
    assert initial_disable_at < load_at < accepted_at < enable_at
    assert "http://" not in source and "https://" not in source


def test_preview_flow_end_to_end(api_env, synthetic_video, tmp_path):
    with synthetic_video.open("rb") as upload:
        created = client.post(
            "/highlights",
            files={"file": ("match.mp4", upload, "video/mp4")},
            data={"top": "1", "min_len": "0.5", "max_len": "1.0"},
        )
    assert created.status_code == 200, created.text
    original = created.json()
    job_id = original["job_id"]
    old_clip_url = original["highlights"][0]["clip_url"]

    page = client.get(f"/jobs/{job_id}")
    loaded = client.get(f"/highlights/{job_id}")
    source = client.get(
        f"/highlights/{job_id}/source", headers={"Range": "bytes=0-99"},
    )
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert loaded.status_code == 200
    assert loaded.json()["highlights"] == original["highlights"]
    assert source.status_code == 206

    edited = client.put(f"/highlights/{job_id}/segments", json={"segments": [
        {"start": 1.0, "end": 3.5, "reason": original["highlights"][0]["reason"]},
        {"start": 4.0, "end": 5.5, "reason": "manual"},
    ]})
    assert edited.status_code == 200, edited.text
    highlights = edited.json()["highlights"]
    assert [(item["start"], item["end"]) for item in highlights] == [
        (1.0, 3.5), (4.0, 5.5),
    ]
    assert highlights[0]["clip_url"].endswith("clip_01_v1.mp4")
    assert highlights[1]["clip_url"].endswith("clip_02_v1.mp4")
    for index, (item, expected) in enumerate(zip(highlights, (2.5, 1.5))):
        clip = client.get(item["clip_url"])
        assert clip.status_code == 200
        path = tmp_path / f"clip-{index}.mp4"
        path.write_bytes(clip.content)
        assert media.probe_duration(path) == pytest.approx(expected, abs=0.5)
    assert client.get(old_clip_url).status_code == 404
    assert client.get(f"/jobs/{job_id}").status_code == 200


def test_preview_styles_and_readme_contract():
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    for marker in (
        "main.preview {", "width: min(100%, 64rem)", "#player {",
        ".segment {", "display: flex", "flex-wrap: wrap",
        ".segment input {", "width: 6.5rem", ".clip-player {",
        "width: 12rem", '[aria-invalid="true"] {',
        "outline: 2px solid #b42318",
    ):
        assert marker in css

    readme = (WEB_DIR.parents[1] / "README.md").read_text(encoding="utf-8")
    heading = "## Trang web: tải lên, xem trước và chỉnh mốc cắt"
    section = readme.split(heading, 1)[1].split("\n## ", 1)[0]
    for marker in (
        "pip install -e '.[api,youtube]'", "sportscut serve",
        "http://127.0.0.1:8000/", "/jobs/JOB_ID", "▶ Đoạn N", "mm:ss.s",
        "75.5", "Đầu/Cuối = hiện tại", "±0.5 s", "Xóa",
        "Thêm đoạn tại thời điểm hiện tại", "10 giây", "Lưu", "404",
    ):
        assert marker in section
    assert "![" not in section
