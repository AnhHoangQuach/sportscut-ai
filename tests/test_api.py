import json
import ast
import inspect
import subprocess
import sys
from pathlib import Path
import uuid

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from sportscut.api import app
from sportscut.media import MediaError
from sportscut import pipeline


client = TestClient(app)


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("api-data")


@pytest.fixture(autouse=True)
def api_env(monkeypatch, data_dir):
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(data_dir))
    monkeypatch.delenv("SPORTSCUT_MAX_UPLOAD_BYTES", raising=False)


@pytest.fixture(scope="module")
def job(data_dir, burst_video):
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("SPORTSCUT_DATA_DIR", str(data_dir))
        with burst_video.open("rb") as upload:
            response = client.post("/highlights", files={"file": ("match.mp4", upload)})
    assert response.status_code == 200, response.text
    return response.json(), data_dir, burst_video


def test_post_returns_highlights_covering_bursts(job):
    body, data_dir, source = job
    assert set(body) == {"job_id", "highlights"}
    job_id = body["job_id"]
    assert str(uuid.UUID(job_id)) == job_id
    highlights = body["highlights"]
    assert len(highlights) == 3
    assert all(set(item) == {"start", "end", "score", "reason", "clip_url"} for item in highlights)
    assert all(any(item["start"] <= start and item["end"] >= end for item in highlights)
               for start, end in [(20, 21), (50, 51), (75, 76)])
    job_dir = data_dir / "jobs" / job_id
    manifest = json.loads((job_dir / "clips" / "highlights.json").read_text())
    assert [{k: v for k, v in item.items() if k != "clip_url"} for item in highlights] == [
        {k: v for k, v in entry.items() if k != "file"} for entry in manifest
    ]
    assert (job_dir / "input").read_bytes() == source.read_bytes()


def test_clip_urls_serve_mp4_bytes(job):
    body, data_dir, _ = job
    clips_dir = data_dir / "jobs" / body["job_id"] / "clips"
    for number, item in enumerate(body["highlights"], 1):
        response = client.get(item["clip_url"])
        name = f"clip_{number:02d}.mp4"
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("video/mp4")
        assert response.content and response.content == (clips_dir / name).read_bytes()
        assert item["clip_url"].endswith(f"/highlights/{body['job_id']}/clips/{name}")


def test_post_passes_form_options(burst_video):
    with burst_video.open("rb") as upload:
        response = client.post(
            "/highlights", files={"file": ("match.mp4", upload)},
            data={"top": "1", "min_len": "4", "max_len": "6"},
        )
    assert response.status_code == 200
    highlights = response.json()["highlights"]
    assert len(highlights) == 1
    assert highlights[0]["end"] - highlights[0]["start"] == pytest.approx(6, abs=0.01)


def _jobs(data_dir):
    root = data_dir / "jobs"
    return set(root.iterdir()) if root.exists() else set()


def test_post_non_video_returns_400_without_path(data_dir, require_ffmpeg):
    before = _jobs(data_dir)
    response = client.post("/highlights", files={"file": ("bad.txt", b"not video")})
    assert response.status_code == 400
    assert response.json()["detail"].startswith("ffprobe failed for upload: ")
    assert str(data_dir) not in response.text
    assert _jobs(data_dir) == before


def test_post_no_audio_returns_400(data_dir, require_ffmpeg, tmp_path):
    video = tmp_path / "silent.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x120:r=5:d=3",
        "-c:v", "mpeg4", "-q:v", "5", "-pix_fmt", "yuv420p", str(video),
    ], check=True, capture_output=True)
    before = _jobs(data_dir)
    response = client.post("/highlights", files={"file": ("silent.mp4", video.read_bytes())})
    assert response.status_code == 400
    assert response.json() == {"detail": "no audio stream in upload"}
    assert _jobs(data_dir) == before


def test_media_error_returns_500(monkeypatch, data_dir):
    before = _jobs(data_dir)
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: (_ for _ in ()).throw(
        MediaError("ffmpeg not found on PATH; install ffmpeg")
    ))
    response = client.post("/highlights", files={"file": ("x", b"x")})
    assert response.status_code == 500
    assert response.json() == {"detail": "processing failed"}
    assert _jobs(data_dir) == before


@pytest.mark.parametrize("data,with_file", [
    ({}, False), ({"top": "0"}, True), ({"top": "abc"}, True),
    ({"min_len": "0"}, True), ({"max_len": "-1"}, True),
    ({"min_len": "nan"}, True), ({"max_len": "inf"}, True),
    ({"min_len": "20", "max_len": "10"}, True),
])
def test_bad_parameters_return_422(monkeypatch, data_dir, data, with_file):
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: calls.append((a, k)))
    before = _jobs(data_dir)
    files = {"file": ("x", b"x")} if with_file else None
    response = client.post("/highlights", files=files, data=data)
    assert response.status_code == 422
    assert calls == [] and _jobs(data_dir) == before
    if data.get("min_len") == "20":
        assert response.json() == {"detail": "min_len must be <= max_len"}


def test_upload_over_limit_returns_413(monkeypatch, data_dir):
    calls = []
    monkeypatch.setenv("SPORTSCUT_MAX_UPLOAD_BYTES", "10")
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: calls.append((a, k)))
    before = _jobs(data_dir)
    response = client.post("/highlights", files={"file": ("x", b"12345678901")})
    assert response.status_code == 413
    assert response.json() == {"detail": "upload exceeds 10 bytes"}
    assert calls == [] and _jobs(data_dir) == before


def test_upload_at_limit_is_accepted(monkeypatch):
    monkeypatch.setenv("SPORTSCUT_MAX_UPLOAD_BYTES", "10")
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: [])
    response = client.post("/highlights", files={"file": ("x", b"1234567890")})
    assert response.status_code == 200
    assert response.json()["highlights"] == []


def test_default_data_dir_is_cwd_sportscut_data(monkeypatch, tmp_path):
    calls = []
    monkeypatch.delenv("SPORTSCUT_DATA_DIR")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: calls.append((a, k)) or [])
    response = client.post("/highlights", files={"file": ("x", b"data")})
    assert response.status_code == 200
    job_id = response.json()["job_id"]
    expected = tmp_path / "sportscut-data" / "jobs" / job_id
    assert (expected / "input").read_bytes() == b"data"
    assert calls == [((expected / "input", expected / "clips"),
                      {"top": 10, "min_len": 10, "max_len": 30})]


@pytest.mark.parametrize("case", [
    "bad-id", "upper-id", "fresh-id", "clip_99.mp4", "highlights.json", "input",
    "..%2Finput", "%2e%2e%2finput", "..%2Fclips%2Fhighlights.json",
])
def test_get_clip_rejects(job, case):
    body, data_dir, _ = job
    job_id = body["job_id"]
    if case == "bad-id":
        job_id, name = "not-a-uuid", "clip_01.mp4"
    elif case == "upper-id":
        job_id, name = job_id.upper(), "clip_01.mp4"
    elif case == "fresh-id":
        job_id, name = str(uuid.uuid4()), "clip_01.mp4"
    else:
        name = case
    response = client.get(f"/highlights/{job_id}/clips/{name}")
    real_dir = data_dir / "jobs" / body["job_id"]
    assert response.status_code == 404
    assert response.content not in {
        (real_dir / "input").read_bytes(),
        (real_dir / "clips" / "highlights.json").read_bytes(),
    }


def test_api_module_contracts():
    import sportscut.api as api
    tree = ast.parse(Path(api.__file__).read_text())
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) and
                   ((getattr(node, "module", None) == "subprocess") or
                    any(alias.name == "subprocess" for alias in getattr(node, "names", [])))
                   for node in ast.walk(tree))
    assert not inspect.iscoroutinefunction(api.create_highlights)


def test_cli_import_does_not_load_api_dependencies():
    code = "import sys, sportscut.cli; assert 'fastapi' not in sys.modules and 'uvicorn' not in sys.modules"
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0
