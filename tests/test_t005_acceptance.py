"""Independent user-facing acceptance coverage for task T-005."""

import ast
import inspect
import json
from pathlib import Path
import subprocess
import sys
import uuid

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sportscut import pipeline
import sportscut.api as api
from sportscut.cli import main
from sportscut.media import MediaError


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SPORTSCUT_MAX_UPLOAD_BYTES", raising=False)
    return TestClient(api.app), tmp_path


def _job_dirs(root: Path) -> set[Path]:
    jobs = root / "jobs"
    return set(jobs.iterdir()) if jobs.exists() else set()


def test_acceptance_ac1_package_and_import_contracts():
    import tomllib

    config = tomllib.loads(Path("pyproject.toml").read_text())
    project = config["project"]
    assert project["dependencies"] == ["numpy>=1.26"]
    expected_api = ["fastapi>=0.110", "uvicorn>=0.29", "python-multipart>=0.0.9"]
    assert project["optional-dependencies"]["api"] == expected_api
    assert project["optional-dependencies"]["dev"] == [
        "pytest>=8", "httpx>=0.27", *expected_api
    ]
    assert isinstance(api.app, FastAPI)
    tree = ast.parse(Path(api.__file__).read_text())
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert "subprocess" not in imported
    assert not inspect.iscoroutinefunction(api.create_highlights)
    probe = subprocess.run(
        [sys.executable, "-c", "import sys,sportscut.cli; assert 'fastapi' not in sys.modules and 'uvicorn' not in sys.modules"],
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr


def test_acceptance_ac2_ac3_real_video_round_trip(api_client, burst_video):
    client, root = api_client
    source = burst_video.read_bytes()
    response = client.post("/highlights", files={"file": ("match.mp4", source, "video/mp4")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"job_id", "highlights"}
    assert str(uuid.UUID(body["job_id"])) == body["job_id"]
    assert len(body["highlights"]) == 3
    assert all(
        any(h["start"] <= start and h["end"] >= end for h in body["highlights"])
        for start, end in ((20, 21), (50, 51), (75, 76))
    )
    job = root / "jobs" / body["job_id"]
    assert (job / "input").read_bytes() == source
    manifest = json.loads((job / "clips" / "highlights.json").read_text())
    assert [{k: v for k, v in h.items() if k != "clip_url"} for h in body["highlights"]] == [
        {k: v for k, v in entry.items() if k != "file"} for entry in manifest
    ]
    for number, highlight in enumerate(body["highlights"], 1):
        assert set(highlight) == {"start", "end", "score", "reason", "clip_url"}
        name = f"clip_{number:02d}.mp4"
        assert highlight["clip_url"].endswith(f"/{body['job_id']}/clips/{name}")
        clip = client.get(highlight["clip_url"])
        assert clip.status_code == 200
        assert clip.headers["content-type"].startswith("video/mp4")
        assert clip.content == (job / "clips" / name).read_bytes()
        assert clip.content


def test_acceptance_ac4_form_options(api_client, burst_video):
    client, _ = api_client
    response = client.post(
        "/highlights",
        files={"file": ("match.mp4", burst_video.read_bytes())},
        data={"top": "1", "min_len": "4", "max_len": "6"},
    )
    assert response.status_code == 200
    assert len(response.json()["highlights"]) == 1
    item = response.json()["highlights"][0]
    assert item["end"] - item["start"] == pytest.approx(6, abs=0.01)


def test_acceptance_ac5_bad_and_silent_media_cleanup(api_client, require_ffmpeg, tmp_path):
    client, root = api_client
    before = _job_dirs(root)
    bad = client.post("/highlights", files={"file": ("bad.txt", b"not video")})
    assert bad.status_code == 400
    assert bad.json()["detail"].startswith("ffprobe failed for upload: ")
    assert str(root) not in bad.text
    silent_path = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x120:r=5:d=1", "-c:v", "mpeg4", str(silent_path)],
        check=True,
    )
    silent = client.post("/highlights", files={"file": ("silent.mp4", silent_path.read_bytes())})
    assert silent.status_code == 400
    assert silent.json() == {"detail": "no audio stream in upload"}
    assert _job_dirs(root) == before


def test_acceptance_ac6_media_error_is_sanitized_and_cleaned(api_client, monkeypatch):
    client, root = api_client
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: (_ for _ in ()).throw(MediaError("secret")))
    response = client.post("/highlights", files={"file": ("x", b"x")})
    assert response.status_code == 500
    assert response.json() == {"detail": "processing failed"}
    assert _job_dirs(root) == set()


@pytest.mark.parametrize("data,files", [
    ({}, None), ({"top": "0"}, {"file": ("x", b"x")}),
    ({"top": "abc"}, {"file": ("x", b"x")}),
    ({"min_len": "0"}, {"file": ("x", b"x")}),
    ({"max_len": "-1"}, {"file": ("x", b"x")}),
    ({"min_len": "nan"}, {"file": ("x", b"x")}),
    ({"max_len": "inf"}, {"file": ("x", b"x")}),
    ({"min_len": "20", "max_len": "10"}, {"file": ("x", b"x")}),
])
def test_acceptance_ac7_invalid_input_has_no_side_effect(api_client, monkeypatch, data, files):
    client, root = api_client
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: calls.append((a, k)))
    response = client.post("/highlights", data=data, files=files)
    assert response.status_code == 422
    assert calls == []
    assert _job_dirs(root) == set()
    if data.get("min_len") == "20":
        assert response.json() == {"detail": "min_len must be <= max_len"}


def test_acceptance_ac8_limit_boundary(api_client, monkeypatch):
    client, root = api_client
    calls = []
    monkeypatch.setenv("SPORTSCUT_MAX_UPLOAD_BYTES", "10")
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: calls.append((a, k)) or [])
    over = client.post("/highlights", files={"file": ("x", b"12345678901")})
    assert over.status_code == 413
    assert over.json() == {"detail": "upload exceeds 10 bytes"}
    assert calls == [] and _job_dirs(root) == set()
    exact = client.post("/highlights", files={"file": ("x", b"1234567890")})
    assert exact.status_code == 200
    assert exact.json()["highlights"] == []


def test_acceptance_ac9_default_directory_tracks_cwd(monkeypatch, tmp_path):
    monkeypatch.delenv("SPORTSCUT_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: calls.append((a, k)) or [])
    response = TestClient(api.app).post("/highlights", files={"file": ("x", b"data")})
    assert response.status_code == 200
    job = tmp_path / "sportscut-data" / "jobs" / response.json()["job_id"]
    assert (job / "input").read_bytes() == b"data"
    assert calls == [((job / "input", job / "clips"), {"top": 10, "min_len": 10, "max_len": 30})]


def test_acceptance_ac10_manifest_authorizes_downloads(api_client):
    client, root = api_client
    job_id = str(uuid.uuid4())
    clips = root / "jobs" / job_id / "clips"
    clips.mkdir(parents=True)
    (clips / "clip_01.mp4").write_bytes(b"allowed")
    (clips / "highlights.json").write_text(json.dumps([{"file": "clip_01.mp4"}]))
    (root / "jobs" / job_id / "input").write_bytes(b"secret")
    paths = [
        f"/highlights/not-a-uuid/clips/clip_01.mp4",
        f"/highlights/{job_id.upper()}/clips/clip_01.mp4",
        f"/highlights/{uuid.uuid4()}/clips/clip_01.mp4",
        f"/highlights/{job_id}/clips/clip_99.mp4",
        f"/highlights/{job_id}/clips/highlights.json",
        f"/highlights/{job_id}/clips/input",
        f"/highlights/{job_id}/clips/..%2Finput",
        f"/highlights/{job_id}/clips/%2e%2e%2finput",
        f"/highlights/{job_id}/clips/..%2Fclips%2Fhighlights.json",
    ]
    for path in paths:
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.content not in {b"secret", (clips / "highlights.json").read_bytes()}


def test_acceptance_ac11_serve_cli(monkeypatch, capsys):
    import uvicorn

    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: calls.append((a, k)))
    assert main(["serve"]) == 0
    assert calls == [((api.app,), {"host": "127.0.0.1", "port": 8000})]
    calls.clear()
    assert main(["serve", "--host", "0.0.0.0", "--port", "9001"]) == 0
    assert calls == [((api.app,), {"host": "0.0.0.0", "port": 9001})]
    assert main([]) == 0
    assert "serve" in capsys.readouterr().out
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    assert main(["serve"]) == 1
    assert capsys.readouterr().err == "sportscut: error: the API needs the [api] extra: pip install 'sportscut[api]'\n"


def test_acceptance_ac13_documentation_and_ignore_contract():
    readme = Path("README.md").read_text()
    assert "## API HTTP" in readme
    for text in ("pip install -e '.[api]'", "sportscut serve", "curl -F file=@", "/highlights", "curl -o", "SPORTSCUT_DATA_DIR", "SPORTSCUT_MAX_UPLOAD_BYTES"):
        assert text in readme
    assert "sportscut-data/" in Path(".gitignore").read_text().splitlines()
    implementation_commit = subprocess.run(
        ["git", "log", "-1", "--format=%H", "--", "sportscut/api.py"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    numstat = subprocess.run(
        ["git", "show", "--numstat", "--format=", implementation_commit],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    allowed = {
        ".gitignore", "README.md", "pyproject.toml", "sportscut/api.py",
        "sportscut/cli.py", "tests/test_api.py", "tests/test_cli.py",
    }
    changed_paths = {line.split("\t", 2)[2] for line in numstat}
    assert changed_paths <= allowed, (
        f"AC13 allows only the listed implementation files, got "
        f"{sorted(changed_paths - allowed)}"
    )
    changed_lines = sum(int(added) + int(deleted) for added, deleted, _ in
                        (line.split("\t", 2) for line in numstat))
    assert changed_lines < 400, f"AC13 requires <400 changed lines, got {changed_lines}"
