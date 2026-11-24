import json
import subprocess
from datetime import datetime

import pytest

from agent_office.agents import extract_json
from agent_office.models import Agent, AgentStatus, InvalidTransition, Stage, Task
from agent_office.scheduler import next_step


def test_transitions_are_enforced():
    t = Task(id="T-001", title="x", brief="", request_id="R-001")
    t.move(Stage.SPEC)
    with pytest.raises(InvalidTransition):
        t.move(Stage.PR)


def test_old_resting_state_is_migrated_to_quota_failover():
    agent = Agent.from_dict({"name": "claude", "status": "resting",
                             "last_error": "usage_limit_reached", "rest_until": "2026-11-22T14:00:00+00:00"})
    assert agent.rest_cause == "quota"


def test_extract_json_handles_prose_and_fences():
    assert extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Result: {"a": {"b": "}"}} trailing') == {"a": {"b": "}"}}


def test_happy_path_request_to_merge(env):
    office = env.office()
    office.add_request("Cut highlights from a football match")
    env.run_all(office)

    t1, t2 = office.store.tasks["T-001"], office.store.tasks["T-002"]
    assert t2.depends_on == ["T-001"]
    assert t1.stage == Stage.PR and t1.pr_url == "local:office/T-001"
    assert t2.stage == Stage.TODO  # waits for T-001 to be merged
    assert t1.acceptance_criteria == ["AC1 works"] and t1.review_round == 1

    # each task got its own worktree on its own branch, with orchestrator commits
    wt = env.tmp / "sportscut-worktrees" / "T-001"
    assert (wt / "feature_1.py").exists()
    log = __import__("subprocess").run(["git", "log", "--format=%s"], cwd=wt, capture_output=True,
                                       text=True).stdout
    assert "feat(T-001): Scaffold CLI" in log
    assert not (env.repo / "feature_1.py").exists()  # main untouched until PO merges

    # no API keys reached the CLIs
    assert env.calls() and not any(c["has_api_key"] for c in env.calls())

    # PO merges -> done, and T-002 starts
    env.merge("office/T-001")
    office = env.run_all()
    assert office.store.tasks["T-001"].stage == Stage.DONE
    assert office.store.tasks["T-002"].stage == Stage.PR

    events = [json.loads(line)["event"] for line in
              (env.repo / ".agent-office" / "events.jsonl").read_text().splitlines()]
    for e in ("request_added", "task_created", "stage_changed", "worktree_ready", "review_done", "pr_ready"):
        assert e in events


def test_usage_limit_checkpoint_and_resume(env):
    env.script(codex_dev=[{"limit": "You've hit your usage limit. Try again in 2 hours.", "write": "half.py"}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)

    t1 = office.store.tasks["T-001"]
    codex = office.store.agents["dev"]
    assert codex.status.value == "resting" and codex.reset_known
    assert datetime.fromisoformat(codex.rest_until) == datetime.fromisoformat("2026-11-22T14:01:00+00:00")
    assert office.store.agents["tester"].rest_until == codex.rest_until  # same CLI, same quota
    assert office.store.agents["pm"].status.value == "idle"  # the other CLI's roles keep working
    assert office.store.agents["lead"].status.value == "idle"

    # The interrupted session is Codex's: Claude does not take over the half-done task, it waits.
    assert t1.stage == Stage.DEV and t1.checkpoint["provider"] == "codex"
    wt = env.tmp / "sportscut-worktrees" / "T-001"
    assert (wt / ".office" / "CHECKPOINT.md").exists()
    log = __import__("subprocess").run(["git", "log", "--format=%s"], cwd=wt, capture_output=True,
                                       text=True).stdout
    assert "wip(office): checkpoint T-001 dev" in log  # partial work saved
    assert [c["agent"] for c in env.calls() if c["kind"] == "dev"] == ["codex"]
    why = next(r for r in next_step(office.store, env.now).waiting_on if r.startswith("T-001"))
    assert "codex" in why and "interrupted" in why

    env.advance(hours=3)  # Codex is back and resumes its own work
    env.run_all(office)
    assert t1.stage == Stage.PR and t1.checkpoint is None
    assert not (wt / ".office" / "CHECKPOINT.md").exists()
    assert (wt / "half.py").exists()
    dev_calls = [c for c in env.calls() if c["kind"] == "dev"]
    assert [c["agent"] for c in dev_calls] == ["codex", "codex"]
    assert "RESUMING" in dev_calls[-1]["prompt"]


def test_codex_runs_claude_step_read_only_while_claude_is_quota_resting(env):
    office = env.office()
    office.add_request("Cut highlights")
    for role in ("pm", "lead"):
        claude = office.store.agents[role]
        claude.status = AgentStatus.RESTING
        claude.rest_until = "2026-11-22T14:00:00+00:00"
        claude.rest_cause = "quota"

    office.step()

    assert office.store.requests["R-001"].status == "planned"
    call = next(c for c in env.calls() if c["agent"] == "codex" and c["kind"] == "breakdown")
    assert call["args"][call["args"].index("--sandbox") + 1] == "read-only"
    event_rows = [json.loads(line) for line in (env.repo / ".agent-office/events.jsonl").read_text().splitlines()]
    assert any(e["event"] == "agent_failover" and e["preferred"] == "pm" and e["agent"] == "dev"
               and e["preferred_provider"] == "claude" and e["provider"] == "codex" for e in event_rows)


def test_unknown_reset_uses_backoff_and_probe(env):
    env.script(codex_dev=[{"fail": True}, {"fail": True}],
               codex_probe=[{"limit": "usage limit reached"}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    codex = office.store.agents["dev"]
    assert codex.status.value == "resting" and not codex.reset_known
    assert codex.rest_until == "2026-11-22T12:15:00+00:00"  # 15 min rung

    env.advance(minutes=16)
    office.step()  # probe -> still limited -> 30 min rung
    assert codex.rest_until == "2026-11-22T12:46:00+00:00"

    env.advance(minutes=31)
    env.run_all(office)  # probe ok -> work resumes
    assert office.store.tasks["T-001"].stage == Stage.PR
    assert codex.backoff_level == 0


def test_review_loop_goes_to_the_tech_lead_after_three_rounds_not_the_po(env):
    changes = [{"verdict": "changes"}] * 3
    env.script(claude_review=changes, claude_techlead=[{"tl": {
        "action": "retry", "decision": "x.py comment is out of scope; keep the simple version",
        "guidance": "Keep it simple, ignore the x.py comment."}}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.PR and t1.review_round == 1 and t1.tl_rounds == 1
    assert not any(h.get("to") == "blocked" for h in t1.history)
    dev_prompts = [c["prompt"] for c in env.calls() if c["kind"] == "dev"]
    assert len(dev_prompts) == 4 and "revision" in dev_prompts[1] and "ignore the x.py comment" in dev_prompts[3]
    tl = next(c["prompt"] for c in env.calls() if c["kind"] == "techlead")
    assert "review_rejected" in tl and "fix it" in tl
    task_md = (env.tmp / "sportscut-worktrees" / "T-001" / ".office" / "TASK.md").read_text()
    assert "x.py comment is out of scope" in task_md


def test_failing_tests_go_back_to_dev(env):
    env.script(codex_test=[{"message": "1 failed\nRESULT: FAIL"}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.PR and t1.test_attempts == 1
    notes = [h.get("note", "") for h in t1.history]
    assert any("tests failed" in n for n in notes)


def test_test_cmd_is_run_by_orchestrator(env):
    cfg = env.repo / ".agent-office" / "config.toml"
    cfg.write_text(cfg.read_text().replace('test_cmd = ""', 'test_cmd = "test -f feature_2.py"'))
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    # first dev pass only creates feature_1.py -> orchestrator test fails -> second pass passes
    assert t1.stage == Stage.PR and t1.test_attempts == 1


def test_cli_status_and_show(env, capsys):
    from agent_office.cli import main
    env.office().add_request("Cut highlights")
    assert main(["--repo", str(env.repo), "run", "--max-steps", "2"]) == 0
    assert main(["--repo", str(env.repo), "show", "T-001"]) == 0
    out = capsys.readouterr().out
    assert "T-001" in out and "Scaffold CLI" in out


def test_protected_paths_are_never_merged_and_the_po_is_only_informed(env):
    cfg = env.repo / ".agent-office" / "config.toml"
    cfg.write_text(cfg.read_text().replace("protected_paths = []", 'protected_paths = ["feature_1.py"]'))
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    # every retry still touches the file, so the Tech Lead runs out of rounds and drops the task
    assert t1.stage == Stage.DONE and "protected" in t1.dropped and t1.tl_rounds == 3
    assert not any(h.get("to") == "blocked" for h in t1.history)
    assert "feature_1.py" not in subprocess.run(["git", "ls-files"], cwd=env.repo, capture_output=True,
                                                 text=True).stdout
    report = [e for e in events(env.repo) if e["event"] == "message" and e["to"] == "po"]
    assert any(e["topic"] == "report" for e in report) and not any(e["topic"] == "question" for e in report)


def events(repo):
    return [json.loads(x) for x in (repo / ".agent-office/events.jsonl").read_text().splitlines()]
