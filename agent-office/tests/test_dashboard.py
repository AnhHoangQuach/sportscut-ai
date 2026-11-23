import json

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agent_office.dashboard.server import create_app  # noqa: E402
from agent_office.models import AgentStatus, Stage  # noqa: E402


@pytest.fixture
def client(auto_env):
    return TestClient(create_app(auto_env.repo)), auto_env


def test_index_and_state(client):
    c, env = client
    assert "Agent Office" in c.get("/").text
    s = c.get("/api/state").json()
    assert s["config"]["merge_mode"] == "auto" and s["runner"]["running"] is False
    assert {a["name"]: a["provider"] for a in s["agents"]} == {
        "pm": "claude", "lead": "claude", "dev": "codex", "tester": "codex"}
    assert [r["name"] for r in s["roles"]] == ["pm", "lead", "dev", "tester"]
    assert s["roles"][3]["title"] == "Tester" and s["legacy_agents"] == {"claude": "pm", "codex": "dev"}
    assert c.post("/api/agents/tester/wake").status_code == 200
    assert c.post("/api/agents/codex/wake").status_code == 200
    assert c.post("/api/agents/gpt/wake").status_code == 404


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


def test_waiting_list_explains_idle_sessions_while_a_task_runs(client):
    """The dashboard used to show only why the *next* step could not start, so while one
    Developer coded it said nothing about the other idle Developer sessions."""
    c, env = client
    env.script(claude_breakdown=[{"result": json.dumps({"tasks": [
        {"key": "1", "title": "Task 1", "brief": "x", "depends_on": []},
        {"key": "2", "title": "Task 2", "brief": "x", "depends_on": ["1"]}]})}])
    office = env.office()
    office.add_request("Cut highlights")
    office.step()
    office.store.tasks["T-001"].stage = Stage.DEV
    office.store.agents["dev"].active = ["T-001"]
    office.store.save()
    w = c.get("/api/state").json()["waiting_on"]
    assert any("T-002 waits for T-001 to be merged" in x for x in w)
    assert not any(x.startswith("T-001") for x in w)  # being coded: not waiting


def test_state_says_who_covers_a_role_resting_on_a_server_error(client):
    c, env = client
    office = env.office()
    for role in ("dev", "tester"):
        a = office.store.agents[role]
        a.status, a.rest_until, a.rest_cause = AgentStatus.RESTING, "2099-01-01T00:00:00+00:00", "upstream"
    office.store.save()
    agents = {a["name"]: a for a in c.get("/api/state").json()["agents"]}
    assert agents["dev"]["covered_by"] == "pm" and agents["tester"]["covered_by"] == "lead"
    assert agents["pm"]["covered_by"] == ""
    js = c.get("/static/app.js").text
    assert "upstream" in js and "covered_by" in js
