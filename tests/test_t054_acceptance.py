import json, shutil, uuid; from pathlib import Path
import pytest
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from sportscut import player
from sportscut.api import app

client = TestClient(app); ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
API = README.split("## API HTTP\n", 1)[1].split("\n## ", 1)[0]
PARA = API.split("POST /players", 1)[1].split("Hiện việc xử lý", 1)[0] if "POST /players" in API else ""

@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path)); monkeypatch.delenv("SPORTSCUT_MAX_UPLOAD_BYTES", raising=False); return tmp_path

def _job(root, video):
    job_id = str(uuid.uuid4()); d = root / "jobs" / job_id; d.mkdir(parents=True); shutil.copy(video, d / "input")
    (d / "job.json").write_text(json.dumps({"source_name": "m.mp4", "source_url": None, "duration": 6, "version": 0, "segments": []}))
    return job_id

def _raise(*a): raise ValueError("equally close")
@pytest.mark.parametrize("case", ["both", "neither", "team", "num0", "numabc", "tie"])
def test_bad_requests_give_422(root, synthetic_video, monkeypatch, case):
    monkeypatch.setattr(player, "find_touches", _raise if case == "tie" else lambda *a: [])
    data = {"job_id": _job(root, synthetic_video), "team": "zzz" if case == "team" else "red", "number": {"num0": 0, "numabc": "abc"}.get(case, 10)}
    files = {"file": ("m.mp4", synthetic_video.read_bytes(), "video/mp4")} if case == "both" else None
    if case == "neither": del data["job_id"]
    assert client.post("/players", data=data, files=files).status_code == 422 and "422" in PARA

def test_unknown_job_404_and_no_touches_200(root, synthetic_video, monkeypatch):
    monkeypatch.setattr(player, "find_touches", lambda *a: [])
    assert client.post("/players", data={"job_id": str(uuid.uuid4()), "team": "red", "number": 10}).status_code == 404 and "404" in PARA
    r = client.post("/players", data={"job_id": _job(root, synthetic_video), "team": "red", "number": 10}); body = r.json()
    assert r.status_code == 200 and set(body) == {"job_id", "touches", "reel_url"} and body["touches"] == [] and body["reel_url"] is None
    assert all(k in PARA for k in ("reel_url", "job_id", "touches", "null", "đồng bộ")) and "nền" not in PARA and "async" not in PARA.lower()

def test_readme_stale_notes_gone_and_headings_kept():
    assert not any(s in README for s in ("vẫn chưa trả về gì cho tới khi T-032/T-033 xong", "vẫn là stub", "chưa lọc theo số áo"))
    web = README.split("## Trang web: tải lên, xem trước và chỉnh mốc cắt\n", 1)[1].split("\n## ", 1)[0]
    assert "\n15. " in web and all(s in web for s in ("Theo dõi cầu thủ", "Không tìm thấy pha chạm bóng nào.", "Tạo video cầu thủ"))
