import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agent_office.dashboard.server import create_app  # noqa: E402


@pytest.fixture
def client(auto_env):
    return TestClient(create_app(auto_env.repo)), auto_env


def test_index_and_state(client):
    c, env = client
    assert "Agent Office" in c.get("/").text
    s = c.get("/api/state").json()
    assert s["config"]["merge_mode"] == "auto" and s["runner"]["running"] is False
    assert {a["name"] for a in s["agents"]} == {"claude", "codex"}


def test_post_request_goes_through_inbox(client):
    c, env = client
    r = c.post("/api/requests", json={"text": "Cut football highlights"}).json()
    assert r["results"] == ["R-001 added"]
    assert c.get("/api/state").json()["requests"][0]["text"] == "Cut football highlights"
    assert c.post("/api/requests", json={"text": "  "}).status_code == 400


def test_answer_and_logs_and_notes(client):
    c, env = client
    env.script(claude_spec=[{"questions": ["Which sport?"]}],
               claude_techlead=[{"tl": {"business_questions": ["Which sport?"]}}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    s = c.get("/api/state").json()
    t1 = next(t for t in s["tasks"] if t["id"] == "T-001")
    assert t1["stage"] == "blocked" and t1["questions"] == ["Which sport?"]
    assert any("T-001 waits for the PO" in w for w in s["waiting_on"])
    logs = c.get("/api/tasks/T-001/logs").json()
    assert logs and "spec" in logs[0]
    assert "Which sport?" in c.get(f"/api/tasks/T-001/logs/{logs[0]}").text
    assert c.get("/api/tasks/T-001/logs/..%2Fstate.json").status_code in (400, 404)
    r = c.post("/api/tasks/T-001/answer", json={"text": "Football"}).json()
    assert r["results"] == ["T-001 back to spec"]


def test_websocket_streams_snapshot_then_events(client):
    c, env = client
    with c.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "snapshot" and first["state"]["tasks"] == []
        c.post("/api/requests", json={"text": "Cut highlights"})
        seen = []
        for _ in range(4):
            msg = ws.receive_json()
            seen.append(msg["type"])
            if msg["type"] == "event":
                assert msg["event"]["event"] == "request_added"
                break
        assert "event" in seen
