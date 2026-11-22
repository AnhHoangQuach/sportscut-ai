"""Phase 3: agent-to-agent messages, simulated agents (`office demo`) and the /office page."""
import json

import pytest

from agent_office.models import Stage


def messages(repo):
    lines = (repo / ".agent-office/events.jsonl").read_text().splitlines()
    return [e for e in map(json.loads, lines) if e["event"] == "message"]


def use_simulation(env):
    cfg = env.repo / ".agent-office/config.toml"
    text = cfg.read_text().replace("simulate = false", "simulate = true").replace("sim_delay = 3.0", "sim_delay = 0")
    cfg.write_text(text)


def run_until_idle(env, office, limit=200):
    for _ in range(limit):
        if office.step() is None:
            if not any(a.rest_until for a in office.store.agents.values()):
                return office
            env.advance(minutes=2)  # let a resting agent wake up
    raise AssertionError("simulation did not settle")


def test_messages_show_handoffs_between_agents(auto_env):
    env = auto_env
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    msgs = messages(env.repo)
    pairs = {(m["frm"], m["to"], m["topic"]) for m in msgs}
    assert ("po", "claude", "request") in pairs
    assert ("claude", "codex", "assign") in pairs
    assert ("codex", "claude", "handoff") in pairs
    assert ("claude", "codex", "approve") in pairs
    assert ("claude", "po", "merged") in pairs and ("claude", "po", "done") in pairs
    assert all(m["frm"] != m["to"] for m in msgs)
    assert all(m["text"] for m in msgs)


def test_simulated_office_delivers_sportscut_request(auto_env):
    env = auto_env
    use_simulation(env)
    office = env.office()
    office.add_request("SportsCut MVP")
    run_until_idle(env, office)
    office = env.office()
    tasks = office.store.tasks
    assert len(tasks) == 5 and all(t.stage == Stage.DONE for t in tasks.values())
    assert office.store.requests["R-001"].status == "done"
    assert (env.repo / "sportscut/t_005.py").exists()
    topics = [m["topic"] for m in messages(env.repo)]
    assert "rest" in topics and "awake" in topics  # Codex ran out of quota once and came back
    assert "changes" in topics  # T-003 went through a review round
    assert env.calls() == []  # no real CLI was called


def test_office_page_and_assets(auto_env):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from agent_office.dashboard.server import create_app

    c = TestClient(create_app(auto_env.repo))
    page = c.get("/office")
    assert page.status_code == 200 and "office.js" in page.text and "importmap" in page.text
    assert c.get("/static/office.js").status_code == 200
    assert c.get("/static/vendor/three.module.min.js").status_code == 200
    assert c.get("/static/vendor/OrbitControls.js").status_code == 200
