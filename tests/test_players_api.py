import json
import uuid
import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from sportscut import media, pipeline, player
from sportscut.api import app
from sportscut.player import PlayerQuery, Touch

client = TestClient(app)

@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("SPORTSCUT_MAX_UPLOAD_BYTES", raising=False)
    return tmp_path

def _job(root, with_player=True):
    job_id = str(uuid.uuid4()); job_dir = root / "jobs" / job_id
    job_dir.mkdir(parents=True); (job_dir / "input").write_bytes(b"source")
    job = {"source_name": "match.mp4", "source_url": None, "duration": 6, "version": 0, "segments": []}
    (job_dir / "job.json").write_text(json.dumps(job))
    if with_player:
        (job_dir / "player").mkdir(); (job_dir / "player" / "player.json").write_text(json.dumps({"reel": "player_red_10.mp4"}))
        (job_dir / "player" / "player_red_10.mp4").write_bytes(b"reel")
    return job_id, job_dir

def _post(data, content=None):
    return client.post("/players", data=data, files=None if content is None else {"file": ("match.mp4", content, "video/mp4")})

def test_upload_builds_reel_job_and_download(root, synthetic_video, monkeypatch):
    calls = []; touches = [Touch(1.0, "red", 10, .9, None), Touch(4.5, "red", 10, .8, None)]
    monkeypatch.setattr(player, "find_touches", lambda video, query: calls.append((video, query)) or touches)
    source = synthetic_video.read_bytes(); response = _post({"team": "RED", "number": 10}, source); body = response.json()
    job_dir = root / "jobs" / body["job_id"]; manifest = json.loads((job_dir / "player" / "player.json").read_text())
    job = json.loads((job_dir / "job.json").read_text()); reel_path = job_dir / "player" / "player_red_10.mp4"
    assert response.status_code == 200 and set(body) == {"job_id", "touches", "reel_url"}
    assert str(uuid.UUID(body["job_id"])) == body["job_id"] and calls == [(job_dir / "input", PlayerQuery("red", 10))]
    assert (job_dir / "input").read_bytes() == source
    assert {p.name for p in (job_dir / "player").iterdir()} == {"player_red_10.mp4", "player.json"}
    assert body["touches"] == manifest["touches"] and body["reel_url"].endswith(f"/players/{body['job_id']}/reel/player_red_10.mp4")
    assert set(job) == {"source_name", "source_url", "duration", "version", "segments"}
    assert (job["source_name"], job["source_url"], job["version"], job["segments"]) == ("match.mp4", None, 0, [])
    assert job["duration"] == pytest.approx(6, abs=.2) and client.get(f"/highlights/{body['job_id']}").json()["highlights"] == []
    assert client.get(f"/highlights/{body['job_id']}/source").headers["content-type"].startswith("video/mp4")
    downloaded = client.get(body["reel_url"])
    assert downloaded.status_code == 200 and downloaded.headers["content-type"].startswith("video/mp4")
    assert downloaded.content == reel_path.read_bytes() and media.probe_duration(reel_path) > 0

@pytest.mark.parametrize("case", ["fresh", "no-player", "manifest", "input", "wrong", "traversal"])
def test_reel_route_rejects(root, case):
    job_id, job_dir = _job(root, case != "no-player")
    names = {"manifest": "player.json", "input": "input", "wrong": "player_blue_7.mp4", "traversal": "..%2Finput"}
    if case == "fresh": job_id = str(uuid.uuid4())
    response = client.get(f"/players/{job_id}/reel/{names.get(case, 'player_red_10.mp4')}")
    assert response.status_code == 404 and (case == "traversal" or response.json() == {"detail": "not found"})
    leaked = {(job_dir / "input").read_bytes()} | ({(job_dir / "player" / "player.json").read_bytes()} if case != "no-player" else set())
    assert response.content not in leaked

def test_existing_job_is_reused(root, synthetic_video, monkeypatch):
    monkeypatch.setattr(pipeline, "run", lambda *args, **kwargs: [])
    created = client.post("/highlights", files={"file": ("match.mp4", synthetic_video.read_bytes())}).json(); job_dir = root / "jobs" / created["job_id"]
    (job_dir / "clips").mkdir(exist_ok=True); (job_dir / "clips" / "sentinel").write_bytes(b"keep")
    before = (job_dir / "job.json").read_bytes(), {p: p.read_bytes() for p in (job_dir / "clips").iterdir()}; calls = []
    monkeypatch.setattr(player, "find_touches", lambda video, query: calls.append((video, query)) or [])
    response = _post({"job_id": created["job_id"], "team": "blue", "number": 7})
    assert response.status_code == 200 and response.json()["job_id"] == created["job_id"] and calls == [(job_dir / "input", PlayerQuery("blue", 7))]
    assert before == ((job_dir / "job.json").read_bytes(), {p: p.read_bytes() for p in (job_dir / "clips").iterdir()})
    assert len(list((root / "jobs").iterdir())) == 1 and (job_dir / "player").is_dir()

def test_zero_touches(root, synthetic_video, monkeypatch):
    monkeypatch.setattr(player, "find_touches", lambda *args: []); response = _post({"team": "red", "number": 10}, synthetic_video.read_bytes())
    player_dir = root / "jobs" / response.json()["job_id"] / "player"
    assert response.status_code == 200 and response.json()["touches"] == [] and response.json()["reel_url"] is None
    assert json.loads((player_dir / "player.json").read_text())["reel"] is None and not list(player_dir.glob("*.mp4"))

@pytest.mark.parametrize("data,content", [
    ({"team": "plaid", "number": 10}, b"x"), ({"team": "red", "number": 0}, b"x"), ({"team": "red", "number": 100}, b"x"),
    ({"team": "red", "number": "abc"}, b"x"), ({"number": 10}, b"x"), ({"team": "red"}, b"x"),
    ({"team": "red", "number": 10, "job_id": str(uuid.uuid4())}, b"x"), ({"team": "red", "number": 10}, None),
    ({"team": "red", "number": 10, "job_id": "   "}, None),
])
def test_rejects_bad_request(root, monkeypatch, data, content):
    monkeypatch.setattr(player, "find_touches", lambda *args: pytest.fail("find_touches called")); response = _post(data, content)
    assert response.status_code == 422 and (not (root / "jobs").exists() or not list((root / "jobs").iterdir()))

@pytest.mark.parametrize("case", ["fresh", "uppercase", "traversal"])
def test_unknown_job_is_404(root, monkeypatch, case):
    job_id, _ = _job(root); values = {"fresh": str(uuid.uuid4()), "uppercase": job_id.upper(), "traversal": "../etc"}
    monkeypatch.setattr(player, "find_touches", lambda *args: pytest.fail("find_touches called")); response = _post({"job_id": values[case], "team": "red", "number": 10})
    assert response.status_code == 404 and response.json() == {"detail": "not found"}

@pytest.mark.parametrize("case,status", [("invalid", 400), ("media", 500), ("value", 422), ("large", 413)])
def test_new_upload_errors_are_mapped_and_cleaned(root, synthetic_video, monkeypatch, case, status):
    failures = {"media": media.MediaError("boom"), "value": ValueError("bad")}
    monkeypatch.setattr(player, "find_touches", lambda *args: (_ for _ in ()).throw(failures[case]) if case in failures else pytest.fail("find_touches called"))
    if case == "large": monkeypatch.setenv("SPORTSCUT_MAX_UPLOAD_BYTES", "10")
    content = b"not a video" if case == "invalid" else (b"x" * 11 if case == "large" else synthetic_video.read_bytes())
    response = _post({"team": "red", "number": 10}, content)
    assert response.status_code == status and not list((root / "jobs").iterdir())
    assert status != 500 or response.json() == {"detail": "processing failed"}
    assert status != 400 or str(root) not in response.json()["detail"]

def test_existing_job_media_error_preserves_job(root, synthetic_video, monkeypatch):
    job_id, job_dir = _job(root, False); (job_dir / "input").write_bytes(synthetic_video.read_bytes())
    before = (job_dir / "input").read_bytes(), (job_dir / "job.json").read_bytes()
    monkeypatch.setattr(player, "find_touches", lambda *args: (_ for _ in ()).throw(media.MediaError("boom")))
    response = _post({"job_id": job_id, "team": "red", "number": 10})
    assert response.status_code == 500 and response.json() == {"detail": "processing failed"}
    assert before == ((job_dir / "input").read_bytes(), (job_dir / "job.json").read_bytes())
