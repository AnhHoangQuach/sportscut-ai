import json
import uuid
from pathlib import Path
import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from sportscut import media, pipeline
from sportscut.api import app
from sportscut.player import PlayerQuery, Touch
client = TestClient(app)
@pytest.fixture(autouse=True)
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SPORTSCUT_MAX_UPLOAD_BYTES", raising=False)
    return tmp_path
def _post(data, blob=None):
    files = None if blob is None else {"file": ("match.mp4", blob, "video/mp4")}
    return client.post("/players", data=data, files=files)
def _jobs(root):
    path = root / "jobs"
    return list(path.iterdir()) if path.exists() else []
def _seed(root, job_id, blob=b"video", player=True):
    job = root / "jobs" / job_id
    job.mkdir(parents=True)
    (job / "input").write_bytes(blob)
    payload = {"source_name": "match.mp4", "source_url": None, "duration": 6.0,
               "version": 0, "segments": []}
    (job / "job.json").write_text(json.dumps(payload), encoding="utf-8")
    if player:
        (job / "player").mkdir()
        (job / "player" / "player.json").write_text(
            json.dumps({"reel": "player_red_10.mp4"}), encoding="utf-8")
        (job / "player" / "player_red_10.mp4").write_bytes(b"reel")
    return job
def test_upload_is_a_complete_downloadable_job(data_root, synthetic_video, monkeypatch):
    blob, calls = synthetic_video.read_bytes(), []
    touches = [Touch(1.0, "red", 10, 0.9, None), Touch(4.5, "red", 10, 0.8, None)]
    monkeypatch.setattr("sportscut.player.find_touches", lambda video, query: calls.append((Path(video), query)) or touches)
    response = _post({"team": "RED", "number": "10"}, blob)
    assert response.status_code == 200
    body, parsed = response.json(), uuid.UUID(response.json()["job_id"])
    assert set(body) == {"job_id", "touches", "reel_url"}
    assert parsed.version == 4 and str(parsed) == body["job_id"]
    job = data_root / "jobs" / body["job_id"]
    assert calls == [(job / "input", PlayerQuery("red", 10))]
    assert (job / "input").read_bytes() == blob
    assert {p.name for p in (job / "player").iterdir()} == {"player_red_10.mp4", "player.json"}
    manifest = json.loads((job / "player" / "player.json").read_text())
    assert body["touches"] == manifest["touches"]
    assert body["reel_url"].endswith(f"/players/{body['job_id']}/reel/player_red_10.mp4")
    saved = json.loads((job / "job.json").read_text())
    assert set(saved) == {"source_name", "source_url", "duration", "version", "segments"}
    assert saved | {"duration": 6.0} == {"source_name": "match.mp4", "source_url": None,
                                           "duration": 6.0, "version": 0, "segments": []}
    assert abs(saved["duration"] - 6.0) <= 0.2
    saved_job = client.get(f"/highlights/{body['job_id']}")
    source = client.get(f"/highlights/{body['job_id']}/source")
    assert saved_job.status_code == 200 and saved_job.json()["highlights"] == []
    assert source.status_code == 200 and source.headers["content-type"] == "video/mp4"
    download = client.get(body["reel_url"])
    reel_path = job / "player" / "player_red_10.mp4"
    assert download.status_code == 200 and download.headers["content-type"] == "video/mp4"
    assert download.content == reel_path.read_bytes() and media.probe_duration(reel_path) > 0
def test_existing_job_is_reused_without_other_changes(data_root, synthetic_video, monkeypatch):
    monkeypatch.setattr(pipeline, "run", lambda *args, **kwargs: [])
    made = client.post("/highlights", files={"file": ("match.mp4", synthetic_video.read_bytes(), "video/mp4")})
    assert made.status_code == 200
    job_id, calls = made.json()["job_id"], []
    job = data_root / "jobs" / job_id
    clips = job / "clips"
    clips.mkdir(exist_ok=True)
    (clips / "sentinel").write_bytes(b"keep")
    before_json, before_clips, count = (job / "job.json").read_bytes(), {p.name: p.read_bytes() for p in clips.iterdir()}, len(_jobs(data_root))
    monkeypatch.setattr("sportscut.player.find_touches", lambda video, query: calls.append(Path(video)) or [Touch(1, "blue", 7, .9, None)])
    response = _post({"job_id": job_id, "team": "blue", "number": "7"})
    assert response.status_code == 200 and response.json()["job_id"] == job_id
    assert calls == [job / "input"] and (job / "player").is_dir()
    assert (job / "job.json").read_bytes() == before_json and len(_jobs(data_root)) == count
    assert {p.name: p.read_bytes() for p in clips.iterdir()} == before_clips
def test_zero_touches_has_no_video(data_root, synthetic_video, monkeypatch):
    monkeypatch.setattr("sportscut.player.find_touches", lambda *args: [])
    response = _post({"team": "red", "number": "10"}, synthetic_video.read_bytes())
    job = data_root / "jobs" / response.json()["job_id"] / "player"
    assert response.status_code == 200 and response.json()["touches"] == [] and response.json()["reel_url"] is None
    assert json.loads((job / "player.json").read_text())["reel"] is None
    assert not list(job.glob("*.mp4"))
@pytest.mark.parametrize(("data", "send_file"), [
    ({"team": "plaid", "number": "10"}, True), ({"team": "red", "number": "0"}, True),
    ({"team": "red", "number": "100"}, True), ({"team": "red", "number": "abc"}, True),
    ({"number": "10"}, True), ({"team": "red"}, True),
    ({"job_id": str(uuid.uuid4()), "team": "red", "number": "10"}, True),
    ({"team": "red", "number": "10"}, False), ({"job_id": "   ", "team": "red", "number": "10"}, False),
])
def test_invalid_requests_are_rejected_before_processing(data_root, monkeypatch, data, send_file):
    monkeypatch.setattr("sportscut.player.find_touches", lambda *args: pytest.fail("find_touches called"))
    assert _post(data, b"x" if send_file else None).status_code == 422
    assert _jobs(data_root) == []
@pytest.mark.parametrize("case", ["fresh", "uppercase", "traversal"])
def test_invalid_job_ids_are_not_found(data_root, monkeypatch, case):
    lower = str(uuid.uuid4())
    job_id = str(uuid.uuid4()) if case == "fresh" else "../etc"
    if case == "uppercase":
        _seed(data_root, lower, player=False)
        job_id = lower.upper()
    monkeypatch.setattr("sportscut.player.find_touches", lambda *args: pytest.fail("find_touches called"))
    response = _post({"job_id": job_id, "team": "red", "number": "10"})
    assert response.status_code == 404 and response.json() == {"detail": "not found"}
@pytest.mark.parametrize(("case", "name"), [("fresh", "x.mp4"), ("no_player", "x.mp4"),
    ("manifest", "player.json"), ("input", "input"), ("other", "player_blue_7.mp4"),
    ("traversal", "..%2Finput")])
def test_reel_download_requires_the_manifest_name(data_root, case, name):
    job_id = str(uuid.uuid4())
    job = None if case == "fresh" else _seed(data_root, job_id, player=case != "no_player")
    response = client.get(f"/players/{job_id}/reel/{name}")
    assert response.status_code == 404
    if case != "traversal":
        assert response.json() == {"detail": "not found"}
    if job:
        assert response.content != (job / "input").read_bytes()
        if (job / "player" / "player.json").exists():
            assert response.content != (job / "player" / "player.json").read_bytes()
def test_bad_and_oversize_uploads_are_cleaned(data_root, synthetic_video, monkeypatch):
    monkeypatch.setattr("sportscut.player.find_touches", lambda *args: pytest.fail("find_touches called"))
    response = _post({"team": "red", "number": "10"}, b"not a video")
    assert response.status_code == 400 and str(data_root) not in response.json()["detail"] and _jobs(data_root) == []
    monkeypatch.setenv("SPORTSCUT_MAX_UPLOAD_BYTES", "10")
    response = _post({"team": "red", "number": "10"}, b"more than ten bytes")
    assert response.status_code == 413 and _jobs(data_root) == []
@pytest.mark.parametrize(("error", "status", "detail"), [(media.MediaError("boom"), 500, "processing failed"),
                                                            (ValueError("bad"), 422, "bad")])
def test_processing_errors_are_mapped_and_new_jobs_removed(data_root, synthetic_video, monkeypatch, error, status, detail):
    def fail(*args):
        raise error
    monkeypatch.setattr("sportscut.player.find_touches", fail)
    response = _post({"team": "red", "number": "10"}, synthetic_video.read_bytes())
    assert response.status_code == status and response.json() == {"detail": detail} and _jobs(data_root) == []
def test_existing_job_survives_processing_error(data_root, synthetic_video, monkeypatch):
    job_id = str(uuid.uuid4())
    job = _seed(data_root, job_id, synthetic_video.read_bytes(), player=False)
    before = ((job / "input").read_bytes(), (job / "job.json").read_bytes())
    def fail(*args):
        raise media.MediaError("boom")
    monkeypatch.setattr("sportscut.player.find_touches", fail)
    response = _post({"job_id": job_id, "team": "red", "number": "10"})
    assert response.status_code == 500 and response.json() == {"detail": "processing failed"}
    assert job.is_dir() and ((job / "input").read_bytes(), (job / "job.json").read_bytes()) == before
