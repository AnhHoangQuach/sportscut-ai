"""A rest says why: which agent, quota or a failing CLI, the error line and the log to read.
Two failed CLI runs in a row are not reported as "out of quota"."""
import json

from agent_office.cli import sleep_message
from agent_office.scheduler import next_step


def events(repo):
    return [json.loads(x) for x in (repo / ".agent-office/events.jsonl").read_text().splitlines()]


def test_repeated_cli_failures_rest_with_the_real_error_not_quota(env):
    env.script(codex_dev=[{"fail": True}, {"fail": True}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    codex = office.store.agents["codex"]
    assert codex.status.value == "resting" and codex.rest_cause == "failure"
    assert codex.rest_detail == "boom" and codex.rest_log.endswith("-codex.log")
    said = [e["text"] for e in events(env.repo) if e["event"] == "message" and e.get("topic") == "rest"]
    assert said and "Mình hết quota" not in said[-1] and "không phải hết quota" in said[-1] and "boom" in said[-1] and "CLI" in said[-1]
    assert not any("usage limit" in line for line in env.lines)
    plan = next_step(office.store, env.now)
    why = next(r for r in plan.waiting_on if r.startswith("codex resting"))
    assert "CLI failed" in why and "boom" in why and codex.rest_log in why
    msg = sleep_message(plan)
    assert "codex resting until" in msg and "boom" in msg and "agents rest;" not in msg


def test_quota_rest_names_the_matched_cli_message(env):
    env.script(codex_dev=[{"limit": "You've hit your usage limit. Try again in 2 hours."}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    plan = next_step(office.store, env.now)
    why = next(r for r in plan.waiting_on if r.startswith("codex resting"))
    assert "quota" in why and "hit your usage limit" in why
    said = [e["text"] for e in events(env.repo) if e["event"] == "message" and e.get("topic") == "rest"]
    assert "hết quota" in said[-1]


def test_task_retry_wait_is_not_called_an_agent_rest(env):
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    office._github_failed(t1, "gh pr create failed: error connecting to api.github.com")
    plan = next_step(office.store, env.now)
    msg = sleep_message(plan)
    assert "T-001 waits until" in msg and "GitHub network retry 1/4" in msg
    assert "agents rest" not in msg
