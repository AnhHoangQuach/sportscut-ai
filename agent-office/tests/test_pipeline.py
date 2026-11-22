import json
from datetime import datetime

import pytest

from agent_office.agents import extract_json
from agent_office.models import InvalidTransition, Stage, Task


def test_transitions_are_enforced():
    t = Task(id="T-001", title="x", brief="", request_id="R-001")
    t.move(Stage.SPEC)
    with pytest.raises(InvalidTransition):
        t.move(Stage.PR)


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
    codex = office.store.agents["codex"]
    assert t1.stage == Stage.DEV and t1.checkpoint and "usage limit" in t1.checkpoint["reason"]
    assert codex.status.value == "resting" and codex.reset_known
    assert datetime.fromisoformat(codex.rest_until) == datetime.fromisoformat("2026-11-22T14:01:00+00:00")
    assert office.store.agents["claude"].status.value == "idle"  # agents rest independently

    wt = env.tmp / "sportscut-worktrees" / "T-001"
    assert (wt / ".office" / "CHECKPOINT.md").exists()
    log = __import__("subprocess").run(["git", "log", "--format=%s"], cwd=wt, capture_output=True,
                                       text=True).stdout
    assert "wip(office): checkpoint T-001 dev" in log  # partial work saved

    env.advance(hours=1)
    assert office.step() is None  # still resting
    env.advance(hours=1, minutes=2)
    env.run_all(office)
    assert t1.stage == Stage.PR and t1.checkpoint is None
    dev_prompts = [c["prompt"] for c in env.calls() if c["kind"] == "dev"]
    assert "RESUMING" in dev_prompts[-1]


def test_unknown_reset_uses_backoff_and_probe(env):
    env.script(codex_dev=[{"fail": True}, {"fail": True}],
               codex_probe=[{"limit": "usage limit reached"}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    codex = office.store.agents["codex"]
    assert codex.status.value == "resting" and not codex.reset_known
    assert codex.rest_until == "2026-11-22T12:15:00+00:00"  # 15 min rung

    env.advance(minutes=16)
    office.step()  # probe -> still limited -> 30 min rung
    assert codex.rest_until == "2026-11-22T12:46:00+00:00"

    env.advance(minutes=31)
    env.run_all(office)  # probe ok -> work resumes
    assert office.store.tasks["T-001"].stage == Stage.PR
    assert codex.backoff_level == 0


def test_review_loop_blocks_after_three_rounds_then_po_answer(env):
    changes = [{"verdict": "changes"}] * 3
    env.script(claude_review=changes)
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.BLOCKED and t1.review_round == 3
    dev_prompts = [c["prompt"] for c in env.calls() if c["kind"] == "dev"]
    assert len(dev_prompts) == 3 and "revision" in dev_prompts[1]
    task_md = (env.tmp / "sportscut-worktrees" / "T-001" / ".office" / "TASK.md").read_text()
    assert "fix it" in task_md

    office.answer("T-001", "Keep it simple, ignore x.py")
    env.run_all(office)
    assert t1.stage == Stage.PR and t1.review_round == 1


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


def test_protected_paths_block_the_task(env):
    cfg = env.repo / ".agent-office" / "config.toml"
    cfg.write_text(cfg.read_text().replace("protected_paths = []", 'protected_paths = ["feature_1.py"]'))
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.BLOCKED and "protected" in t1.blocked_reason
