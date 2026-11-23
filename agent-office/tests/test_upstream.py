"""Transient upstream errors (codex-lb / provider 502, 503, 504, connection refused...) retry fast,
the other CLI covers the work meanwhile, and the dashboard says when work resumes."""
import json
import socket
from datetime import datetime

import pytest

from agent_office.limits import transient_error
from agent_office.models import AgentStatus, Stage
from agent_office.scheduler import plan_steps

BAD_GATEWAY = json.dumps({"type": "turn.failed", "error": {
    "message": "unexpected status 502 Bad Gateway: upstream error"}})


@pytest.mark.parametrize("text", [
    BAD_GATEWAY,
    "Error: unexpected status 503 Service Unavailable",
    "stream error: 504 Gateway Timeout",
    "error sending request for url (http://127.0.0.1:2455/v1/responses): Connection refused (os error 111)",
    "stream disconnected before completion: connection reset by peer",
    "ECONNREFUSED 127.0.0.1:2455",
    "upstream connect error or disconnect/reset before headers",
])
def test_transient_upstream_errors_are_recognised(text):
    assert transient_error(text, "", 1)


def test_success_and_unrelated_failures_are_not_transient():
    assert transient_error(BAD_GATEWAY, "", 0) == ""            # the run worked
    assert transient_error("AssertionError: 502 != 200", "", 1) == ""  # test output, not a gateway
    assert transient_error("boom", "", 2) == ""
    assert transient_error(BAD_GATEWAY + "\n" + "x" * 5000, "", 1) == ""  # only the tail counts


def _to_stage(office, stage):
    while office.store.tasks.get("T-001") is None or office.store.tasks["T-001"].stage != stage:
        office.step()


def test_one_502_rests_codex_for_one_minute_not_the_failure_ladder(env):
    env.script(codex_dev=[{"stdout": BAD_GATEWAY, "fail": True}])
    office = env.office()
    office.add_request("Cut highlights")
    _to_stage(office, Stage.DEV)
    office.step()  # dev hits 502 once
    a = office.store.agents
    assert a["dev"].status == AgentStatus.RESTING and a["tester"].status == AgentStatus.RESTING
    assert a["dev"].rest_cause == "upstream"
    assert (datetime.fromisoformat(a["dev"].rest_until) - env.now).total_seconds() == 60
    assert "502" in a["dev"].rest_detail


def test_upstream_retries_go_1_2_5_then_stay_at_5_minutes(env):
    env.script(codex_dev=[{"stdout": BAD_GATEWAY, "fail": True}],
               codex_probe=[{"stdout": BAD_GATEWAY, "fail": True}] * 3)
    office = env.office()
    office.add_request("Cut highlights")
    _to_stage(office, Stage.DEV)
    a = office.store.agents
    a["pm"].status = a["lead"].status = AgentStatus.RESTING  # no failover: watch codex alone
    a["pm"].rest_until = a["lead"].rest_until = "2099-01-01T00:00:00+00:00"
    office.step()
    gaps = []
    for _ in range(4):
        until = datetime.fromisoformat(a["dev"].rest_until)
        gaps.append(int((until - env.now).total_seconds() // 60))
        env.now = until
        office.step()  # wake: probe (fails 3 times, then the default probe answers)
    assert gaps == [1, 2, 5, 5]
    assert a["dev"].status != AgentStatus.RESTING


def test_only_the_first_upstream_rest_is_announced(env):
    env.script(codex_dev=[{"stdout": BAD_GATEWAY, "fail": True}],
               codex_probe=[{"stdout": BAD_GATEWAY, "fail": True}] * 2)
    office = env.office()
    office.add_request("Cut highlights")
    _to_stage(office, Stage.DEV)
    a = office.store.agents
    a["pm"].status = a["lead"].status = AgentStatus.RESTING
    a["pm"].rest_until = a["lead"].rest_until = "2099-01-01T00:00:00+00:00"
    office.step()
    for _ in range(2):
        env.now = datetime.fromisoformat(a["dev"].rest_until)
        office.step()
    events = [json.loads(x) for x in (env.repo / ".agent-office" / "events.jsonl").read_text().splitlines()]
    rest_msgs = [e for e in events if e["event"] == "message" and e.get("topic") == "rest" and "codex" in e["text"]]
    assert len(rest_msgs) == 1 and "502" in rest_msgs[0]["text"]


@pytest.mark.parametrize("cause", ["upstream", "failure"])
def test_claude_covers_dev_and_test_while_codex_rests_for_errors(env, cause):
    office = env.office()
    req = office.add_request("Cut highlights")
    req.status = "planned"
    office._add_tasks(req, [{"key": "1", "title": "Cut", "brief": "x"}])
    task = office.store.tasks[req.task_ids[0]]
    for role in ("dev", "tester"):
        a = office.store.agents[role]
        a.status, a.rest_until, a.rest_cause = AgentStatus.RESTING, "2026-11-22T14:00:00+00:00", cause
    task.stage = Stage.DEV
    assert plan_steps(office.store, env.now, True).steps[0].agent == "pm"
    task.stage = Stage.TEST
    assert plan_steps(office.store, env.now, True).steps[0].agent == "lead"


def test_502_on_dev_hands_the_task_to_claude_and_it_gets_done(env):
    env.script(codex_dev=[{"stdout": BAD_GATEWAY, "fail": True}])
    office = env.office()
    office.add_request("Cut highlights")
    _to_stage(office, Stage.DEV)
    office.step()  # 502: codex rests 1 min
    office.step()  # the PM (claude) covers the dev step right away
    assert office.store.tasks["T-001"].stage == Stage.TEST
    dev_calls = [c for c in env.calls() if c["kind"] == "dev"]
    assert [c["agent"] for c in dev_calls] == ["codex", "claude"]
    events = [json.loads(x) for x in (env.repo / ".agent-office" / "events.jsonl").read_text().splitlines()]
    fo = [e for e in events if e["event"] == "agent_failover"]
    assert fo and fo[0]["agent"] == "pm" and fo[0]["reason"] == "upstream"


def _closed_port() -> str:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}/backend-api/codex"


def test_wake_checks_the_codex_lb_server_before_spending_a_probe(env):
    home = env.tmp / "codex-home"
    home.mkdir(exist_ok=True)
    (home / "config.toml").write_text(
        'model_provider = "codex-lb"\n[model_providers.codex-lb]\n'
        f'base_url = "{_closed_port()}"\n')
    office = env.office()
    for role in ("dev", "tester"):
        a = office.store.agents[role]
        a.status, a.rest_until, a.rest_cause = AgentStatus.RESTING, env.now.isoformat(), "upstream"
        a.backoff_level = 1
    office.step()  # wake: the server is down, so no probe, rest again
    a = office.store.agents["dev"]
    assert a.status == AgentStatus.RESTING and a.rest_cause == "upstream"
    assert "not reachable" in a.rest_detail
    assert [c for c in env.calls() if c["kind"] == "probe"] == []


def test_awake_after_upstream_says_work_resumes(env):
    office = env.office()
    for role in ("dev", "tester"):
        a = office.store.agents[role]
        a.status, a.rest_until, a.rest_cause = AgentStatus.RESTING, env.now.isoformat(), "upstream"
    office.step()
    events = [json.loads(x) for x in (env.repo / ".agent-office" / "events.jsonl").read_text().splitlines()]
    awake = [e for e in events if e["event"] == "agent_awake"]
    assert awake and awake[-1]["cause"] == "upstream"
    msgs = [e for e in events if e["event"] == "message" and e.get("topic") == "awake"]
    assert "làm tiếp" in msgs[-1]["text"] and "quota" not in msgs[-1]["text"]
