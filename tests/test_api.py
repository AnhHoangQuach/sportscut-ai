import json
import ast
import inspect
import subprocess
import sys
from pathlib import Path
import shutil
import uuid

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from sportscut.api import app
from sportscut.media import MediaError
from sportscut.models import Segment
from sportscut import export, media, pipeline, sources


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
    assert set(body) == {
        "job_id", "source_name", "source_url", "duration", "highlights"
    }
    assert body["source_name"] == "match.mp4"
    assert body["source_url"] is None
    assert body["duration"] == pytest.approx(90, abs=0.1)
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
        {k: v for k, v in entry.items() if k not in {"file", "event"}} for entry in manifest
    ]
    assert (job_dir / "input").read_bytes() == source.read_bytes()


def test_post_persists_full_job_and_returns_canonical_response(
    monkeypatch, data_dir
):
    entries = [{
        "start": 1.0, "end": 2.5, "score": 3.0, "reason": "peak",
        "event": "other", "file": "clip_01.mp4",
    }]
    monkeypatch.setattr(pipeline, "run", lambda *_a, **_k: entries)
    monkeypatch.setattr(media, "probe_duration", lambda path: 12.5)

    response = client.post(
        "/highlights", files={"file": ("match.mp4", b"video")}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "job_id", "source_name", "source_url", "duration", "highlights"
    }
    assert body["source_name"] == "match.mp4"
    assert body["source_url"] is None
    assert body["duration"] == 12.5
    assert body["highlights"] == [{
        "start": 1.0, "end": 2.5, "score": 3.0, "reason": "peak",
        "clip_url": f"http://testserver/highlights/{body['job_id']}/clips/clip_01.mp4",
    }]
    job_path = data_dir / "jobs" / body["job_id"] / "job.json"
    assert json.loads(job_path.read_text()) == {
        "source_name": "match.mp4", "source_url": None, "duration": 12.5,
        "version": 0, "segments": entries,
    }
    assert job_path.read_text().endswith("\n")


def _persist_test_job(data_dir, *, source=b"0123456789"):
    job_id = str(uuid.uuid4())
    job_dir = data_dir / "jobs" / job_id
    (job_dir / "clips").mkdir(parents=True)
    (job_dir / "input").write_bytes(source)
    segment = {
        "start": 1.0, "end": 2.0, "score": 3.0, "reason": "peak",
        "event": "other", "file": "clip_01.mp4",
    }
    job = {
        "source_name": "match.mp4", "source_url": None, "duration": 10.0,
        "version": 0, "segments": [segment],
    }
    (job_dir / "job.json").write_text(json.dumps(job) + "\n")
    (job_dir / "clips" / "highlights.json").write_text(json.dumps([segment]))
    (job_dir / "clips" / "clip_01.mp4").write_bytes(b"old clip")
    return job_id, job_dir, job


def test_get_highlights_returns_persisted_job(data_dir):
    job_id, _, job = _persist_test_job(data_dir)

    response = client.get(f"/highlights/{job_id}")

    assert response.status_code == 200
    assert response.json() == {
        "job_id": job_id, "source_name": "match.mp4", "source_url": None,
        "duration": 10.0,
        "highlights": [{
            "start": 1.0, "end": 2.0, "score": 3.0, "reason": "peak",
            "clip_url": f"http://testserver/highlights/{job_id}/clips/clip_01.mp4",
        }],
    }


@pytest.mark.parametrize(
    "case", ["invalid", "uppercase", "unknown", "malformed", "huge-number"]
)
def test_get_highlights_rejects_invalid_or_malformed_jobs(data_dir, case):
    job_id, job_dir, _ = _persist_test_job(data_dir)
    if case == "invalid":
        requested = "not-a-uuid"
    elif case == "uppercase":
        requested = job_id.upper()
    elif case == "unknown":
        requested = str(uuid.uuid4())
    elif case == "malformed":
        requested = job_id
        (job_dir / "job.json").write_text('{"segments": [{"start": "bad"}]}')
    else:
        requested = job_id
        job = json.loads((job_dir / "job.json").read_text())
        job["duration"] = 10 ** 400
        (job_dir / "job.json").write_text(json.dumps(job))

    response = client.get(f"/highlights/{requested}")

    assert response.status_code == 404
    assert response.json() == {"detail": "not found"}


def test_source_full_response(data_dir):
    job_id, _, _ = _persist_test_job(data_dir)

    response = client.get(f"/highlights/{job_id}/source")

    assert response.status_code == 200
    assert response.content == b"0123456789"
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == "10"


@pytest.mark.parametrize(("range_header", "content", "content_range"), [
    ("bytes=2-5", b"2345", "bytes 2-5/10"),
    ("bytes=2-", b"23456789", "bytes 2-9/10"),
    ("bytes=-4", b"6789", "bytes 6-9/10"),
    ("bytes=7-99", b"789", "bytes 7-9/10"),
])
def test_source_valid_ranges(data_dir, range_header, content, content_range):
    job_id, _, _ = _persist_test_job(data_dir)

    response = client.get(
        f"/highlights/{job_id}/source", headers={"Range": range_header}
    )

    assert response.status_code == 206
    assert response.content == content
    assert response.headers["content-range"] == content_range
    assert response.headers["content-length"] == str(len(content))
    assert response.headers["accept-ranges"] == "bytes"


@pytest.mark.parametrize("range_header", [
    "items=0-1", "bytes=0-1,3-4", "bytes=-0", "bytes=10-", "bytes=5-2",
    "bytes=--1", "bytes=-", "bytes=1.5-2",
])
def test_source_rejects_invalid_ranges(data_dir, range_header):
    job_id, _, _ = _persist_test_job(data_dir)

    response = client.get(
        f"/highlights/{job_id}/source", headers={"Range": range_header}
    )

    assert response.status_code == 416
    assert response.headers["content-range"] == "bytes */10"


def test_source_rejects_missing_input_and_invalid_job(data_dir):
    job_id, job_dir, _ = _persist_test_job(data_dir)
    (job_dir / "input").unlink()

    assert client.get(f"/highlights/{job_id}/source").status_code == 404
    assert client.get("/highlights/not-a-uuid/source").status_code == 404
    assert client.get(f"/highlights/{job_id.upper()}/source").status_code == 404
    assert client.get(f"/highlights/{uuid.uuid4()}/source").status_code == 404
    assert client.get("/highlights/..%2F..%2Fetc/source").status_code == 404


@pytest.mark.parametrize("payload", [
    {},
    {"segments": [], "extra": True},
    {"segments": [{"start": 1, "end": 2, "extra": True}]},
    {"segments": [{"start": "1", "end": 2}]},
    {"segments": [{"start": True, "end": 2}]},
    {"segments": [{"start": -1, "end": 2}]},
    {"segments": [{"start": 2, "end": 2}]},
    {"segments": [{"start": 3, "end": 2}]},
    {"segments": [{"start": 1, "end": 11}]},
    {"segments": [{"start": 0, "end": 1}] * 51},
])
def test_put_segments_rejects_invalid_without_export_or_changes(
    monkeypatch, data_dir, payload
):
    job_id, job_dir, _ = _persist_test_job(data_dir)
    watched = [
        job_dir / "job.json", job_dir / "clips" / "highlights.json",
        job_dir / "clips" / "clip_01.mp4",
    ]
    before = [path.read_bytes() for path in watched]
    calls = []
    monkeypatch.setattr(export, "export_clips", lambda *_a, **_k: calls.append(1))

    response = client.put(f"/highlights/{job_id}/segments", json=payload)

    assert response.status_code == 422
    assert calls == []
    assert [path.read_bytes() for path in watched] == before


def test_put_segments_rejects_non_finite_without_export(monkeypatch, data_dir):
    job_id, _, _ = _persist_test_job(data_dir)
    calls = []
    monkeypatch.setattr(export, "export_clips", lambda *_a, **_k: calls.append(1))

    response = client.put(
        f"/highlights/{job_id}/segments",
        content='{"segments":[{"start":NaN,"end":2}]}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert calls == []


@pytest.mark.parametrize("requested", ["not-a-uuid", str(uuid.uuid4())])
def test_put_segments_rejects_invalid_or_unknown_job(monkeypatch, requested):
    calls = []
    monkeypatch.setattr(export, "export_clips", lambda *_a, **_k: calls.append(1))

    response = client.put(
        f"/highlights/{requested}/segments", json={"segments": []}
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "not found"}
    assert calls == []


def _persist_video_job(data_dir, synthetic_video):
    job_id = str(uuid.uuid4())
    job_dir = data_dir / "jobs" / job_id
    job_dir.mkdir(parents=True)
    shutil.copy(synthetic_video, job_dir / "input")
    export.export_clips(
        job_dir / "input", [Segment(0.5, 1.5, 2.0, "detected")],
        job_dir / "clips",
    )
    segments = json.loads((job_dir / "clips" / "highlights.json").read_text())
    job = {
        "source_name": "synthetic.mp4", "source_url": None,
        "duration": media.probe_duration(job_dir / "input"), "version": 0,
        "segments": segments,
    }
    (job_dir / "job.json").write_text(json.dumps(job, indent=2) + "\n")
    return job_id, job_dir


def test_put_segments_recuts_synthetic_video(data_dir, synthetic_video):
    job_id, job_dir = _persist_video_job(data_dir, synthetic_video)
    old_url = f"/highlights/{job_id}/clips/clip_01.mp4"

    response = client.put(f"/highlights/{job_id}/segments", json={"segments": [
        {"start": 3.2, "end": 5.0, "reason": "custom"},
        {"start": 0.5, "end": 1.5, "reason": ""},
    ]})

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "job_id", "source_name", "source_url", "duration", "highlights"
    }
    assert [(item["start"], item["end"]) for item in body["highlights"]] == [
        (0.5, 1.5), (3.2, 5.0)
    ]
    assert [item["score"] for item in body["highlights"]] == [None, None]
    assert [item["reason"] for item in body["highlights"]] == ["manual", "custom"]
    job = json.loads((job_dir / "job.json").read_text())
    manifest = json.loads((job_dir / "clips" / "highlights.json").read_text())
    assert job["version"] == 1 and job["segments"] == manifest
    assert [item["file"] for item in manifest] == [
        "clip_01_v1.mp4", "clip_02_v1.mp4"
    ]
    assert [media.probe_duration(job_dir / "clips" / item["file"]) for item in manifest] == pytest.approx(
        [1.0, 1.8], abs=0.5
    )
    assert client.get(old_url).status_code == 404
    assert all(client.get(item["clip_url"]).status_code == 200 for item in body["highlights"])


def test_put_segments_second_version_and_empty_replacement(data_dir, synthetic_video):
    job_id, job_dir = _persist_video_job(data_dir, synthetic_video)
    first = client.put(
        f"/highlights/{job_id}/segments",
        json={"segments": [{"start": 0.5, "end": 1.5}]},
    )
    first_url = first.json()["highlights"][0]["clip_url"]

    second = client.put(
        f"/highlights/{job_id}/segments",
        json={"segments": [{"start": 2.0, "end": 3.0}]},
    )
    assert second.status_code == 200
    assert second.json()["highlights"][0]["clip_url"].endswith("clip_01_v2.mp4")
    assert json.loads((job_dir / "job.json").read_text())["version"] == 2
    assert client.get(first_url).status_code == 404

    empty = client.put(f"/highlights/{job_id}/segments", json={"segments": []})
    assert empty.status_code == 200 and empty.json()["highlights"] == []
    assert json.loads((job_dir / "job.json").read_text())["version"] == 3
    assert json.loads((job_dir / "clips" / "highlights.json").read_text()) == []
    assert client.get(second.json()["highlights"][0]["clip_url"]).status_code == 404


@pytest.mark.parametrize("unexpected", [False, True])
def test_put_segments_failure_preserves_active_job(
    monkeypatch, data_dir, unexpected
):
    job_id, job_dir, _ = _persist_test_job(data_dir)
    job_path = job_dir / "job.json"
    manifest_path = job_dir / "clips" / "highlights.json"
    old_job = job_path.read_bytes()
    old_manifest = manifest_path.read_bytes()
    old_response = client.get(f"/highlights/{job_id}").json()
    old_clip = client.get(old_response["highlights"][0]["clip_url"]).content

    def fail_export(_video, _segments, clips_dir, **_kwargs):
        (Path(clips_dir) / "clip_01_v1.mp4").write_bytes(b"partial")
        error = RuntimeError("unexpected") if unexpected else MediaError("cut failed")
        raise error

    monkeypatch.setattr(export, "export_clips", fail_export)
    if unexpected:
        with pytest.raises(RuntimeError, match="unexpected"):
            client.put(
                f"/highlights/{job_id}/segments",
                json={"segments": [{"start": 2, "end": 3}]},
            )
    else:
        response = client.put(
            f"/highlights/{job_id}/segments",
            json={"segments": [{"start": 2, "end": 3}]},
        )
        assert response.status_code == 500
        assert response.json() == {"detail": "processing failed"}

    assert job_path.read_bytes() == old_job
    assert manifest_path.read_bytes() == old_manifest
    assert list((job_dir / "clips").glob("*_v1.mp4")) == []
    assert client.get(f"/highlights/{job_id}").json() == old_response
    assert client.get(old_response["highlights"][0]["clip_url"]).content == old_clip


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


def test_unexpected_processing_error_removes_job(monkeypatch, data_dir):
    before = _jobs(data_dir)
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("unexpected failure")
    ))
    with pytest.raises(RuntimeError, match="unexpected failure"):
        client.post("/highlights", files={"file": ("x", b"x")})
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
    monkeypatch.setattr(media, "probe_duration", lambda _path: 10.0)
    response = client.post("/highlights", files={"file": ("x", b"1234567890")})
    assert response.status_code == 200
    assert response.json()["highlights"] == []


def test_default_data_dir_is_cwd_sportscut_data(monkeypatch, tmp_path):
    calls = []
    monkeypatch.delenv("SPORTSCUT_DATA_DIR")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: calls.append((a, k)) or [])
    monkeypatch.setattr(media, "probe_duration", lambda _path: 4.0)
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


@pytest.mark.parametrize("mode", ["both", "neither"])
def test_exactly_one_of_file_or_url(monkeypatch, data_dir, mode):
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: calls.append("pipeline"))
    monkeypatch.setattr(sources, "download_youtube", lambda *a: calls.append("download"))
    before = _jobs(data_dir)
    files = {"file": ("x", b"x")} if mode == "both" else None
    data = {"url": "https://youtu.be/abc123"} if mode == "both" else None
    response = client.post("/highlights", files=files, data=data)
    assert response.status_code == 422
    assert response.json() == {"detail": "send exactly one of file or url"}
    assert calls == [] and _jobs(data_dir) == before


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_url_with_file_is_upload(monkeypatch, blank):
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: [])
    monkeypatch.setattr(media, "probe_duration", lambda _path: 1.0)
    response = client.post(
        "/highlights", files={"file": ("x", b"x")}, data={"url": blank}
    )
    assert response.status_code == 200


@pytest.mark.parametrize("url", ["https://evil.com/x", "http://169.254.169.254/"])
def test_invalid_url_returns_400_without_download(monkeypatch, data_dir, url):
    calls = []
    monkeypatch.setattr(sources, "download_youtube", lambda *a: calls.append("download"))
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: calls.append("pipeline"))
    before = _jobs(data_dir)
    response = client.post("/highlights", data={"url": url})
    assert response.status_code == 400
    assert response.json() == {"detail": sources.URL_ERROR}
    assert calls == [] and _jobs(data_dir) == before


def test_download_failure_returns_400_and_cleans(monkeypatch, data_dir):
    monkeypatch.setattr(sources, "download_youtube", lambda *a: (_ for _ in ()).throw(
        sources.SourceError("could not download video: Video unavailable")
    ))
    before = _jobs(data_dir)
    response = client.post("/highlights", data={"url": "https://youtu.be/abc123"})
    assert response.status_code == 400
    assert response.json() == {"detail": "could not download video: Video unavailable"}
    assert _jobs(data_dir) == before


def test_download_unexpected_error_removes_job(monkeypatch, data_dir):
    monkeypatch.setattr(sources, "download_youtube", lambda *a: (_ for _ in ()).throw(
        RuntimeError("unexpected download failure")
    ))
    before = _jobs(data_dir)
    with pytest.raises(RuntimeError, match="unexpected download failure"):
        client.post("/highlights", data={"url": "https://youtu.be/abc123"})
    assert _jobs(data_dir) == before


def test_upload_writes_job_json_with_null_source(monkeypatch, data_dir):
    monkeypatch.setattr(pipeline, "run", lambda *a, **k: [])
    monkeypatch.setattr(media, "probe_duration", lambda _path: 1.0)
    response = client.post("/highlights", files={"file": ("x", b"x")})
    job_id = response.json()["job_id"]
    assert json.loads((data_dir / "jobs" / job_id / "job.json").read_text()) == {
        "source_name": "x", "source_url": None, "duration": 1.0,
        "version": 0, "segments": [],
    }
    assert client.get(f"/highlights/{job_id}/clips/job.json").status_code == 404


def test_url_job_matches_upload_result(monkeypatch, data_dir, burst_video):
    calls = []

    def fake_download(url, dest):
        calls.append((url, dest))
        dest.mkdir(parents=True)
        return Path(shutil.copy(burst_video, dest / "source.mp4"))

    monkeypatch.setattr(sources, "download_youtube", fake_download)
    url = "https://youtu.be/abc123"
    url_response = client.post("/highlights", data={"url": url})
    with burst_video.open("rb") as upload:
        upload_response = client.post("/highlights", files={"file": ("match.mp4", upload)})
    assert url_response.status_code == upload_response.status_code == 200
    body = url_response.json()
    comparable = lambda items: [{k: v for k, v in item.items() if k != "clip_url"} for item in items]
    assert comparable(body["highlights"]) == comparable(upload_response.json()["highlights"])
    job_dir = data_dir / "jobs" / body["job_id"]
    assert calls == [(url, job_dir / "download")]
    assert (job_dir / "input").read_bytes() == burst_video.read_bytes()
    assert not (job_dir / "download").exists()
    persisted = json.loads((job_dir / "job.json").read_text())
    assert persisted == {
        "source_name": None, "source_url": url, "duration": body["duration"],
        "version": 0,
        "segments": json.loads((job_dir / "clips" / "highlights.json").read_text()),
    }
    assert all(client.get(item["clip_url"]).status_code == 200 for item in body["highlights"])
