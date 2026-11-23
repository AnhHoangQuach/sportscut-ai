"""Fully autonomous mode: auto-merge, goal check with follow-ups, questions to the PO."""
import json
import subprocess

from agent_office.models import Stage


def log(repo, ref="main"):
    return subprocess.run(["git", "log", "--format=%s", ref], cwd=repo, capture_output=True, text=True).stdout


def test_auto_merge_runs_whole_request_to_done(auto_env):
    env = auto_env
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    tasks = office.store.tasks
    assert [t.stage for t in tasks.values()] == [Stage.DONE, Stage.DONE]
    assert (env.repo / "feature_1.py").exists() and (env.repo / "feature_2.py").exists()  # main has both
    assert "feat(T-002)" in log(env.repo)
    req = office.store.requests["R-001"]
    assert req.status == "done" and req.goal_rounds == 1 and "Highlights" in req.summary
    assert not (env.tmp / "sportscut-worktrees" / "T-001").exists()  # cleaned up
    events = [json.loads(x)["event"] for x in (env.repo / ".agent-office/events.jsonl").read_text().splitlines()]
    assert events.count("pr_merged") == 2 and "request_done" in events


def test_goal_check_adds_follow_up_tasks(auto_env):
    env = auto_env
    env.script(claude_goal=[{"goal": {"done": False, "summary": "export missing", "tasks": [
        {"key": "1", "title": "Export highlights", "brief": "Write clips.", "depends_on": []}]}}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    assert office.store.tasks["T-003"].title == "Export highlights"
    assert office.store.tasks["T-003"].stage == Stage.DONE
    req = office.store.requests["R-001"]
    assert req.status == "done" and req.goal_rounds == 2 and req.task_ids == ["T-001", "T-002", "T-003"]


def test_unclear_request_asks_po_then_continues(auto_env):
    env = auto_env
    env.script(claude_breakdown=[{"questions": ["Which sport first: football or basketball?"]}],
               claude_techlead=[{"tl": {"business_questions": ["Which sport first: football or basketball?"]}}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    req = office.store.requests["R-001"]
    assert req.status == "blocked" and req.questions == ["Which sport first: football or basketball?"]
    assert not office.store.tasks

    office.submit({"cmd": "answer", "id": "R-001", "text": "Football"})
    env.run_all(office)
    req = office.store.requests["R-001"]
    breakdown_prompts = [c["prompt"] for c in env.calls() if c["kind"] == "breakdown"]
    assert "A: Football" in breakdown_prompts[-1]
    assert req.status == "done"


def test_unclear_task_spec_blocks_task_only(auto_env):
    env = auto_env
    env.script(claude_spec=[{"questions": ["Clip length 10-30s or 5-15s?"]}],
               claude_techlead=[{"tl": {"business_questions": ["Clip length 10-30s or 5-15s?"]}}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.BLOCKED and t1.questions
    office.submit({"cmd": "answer", "id": "T-001", "text": "10-30s"})
    t1 = office.store.tasks["T-001"]  # submit reloads state from disk
    assert t1.stage == Stage.SPEC
    env.run_all(office)
    assert t1.stage == Stage.DONE
    spec_prompts = [c["prompt"] for c in env.calls() if c["kind"] == "spec"]
    assert "A: 10-30s" in spec_prompts[1]


def test_inbox_is_deferred_while_a_runner_owns_the_state(auto_env, monkeypatch):
    env = auto_env
    office = env.office()
    monkeypatch.setattr(office.store, "runner_pid", lambda: 999999)
    out = office.submit({"cmd": "request", "text": "Later"})
    assert out[0].startswith("queued") and not office.store.requests
    monkeypatch.undo()
    runner = env.office()
    runner.is_runner = True
    runner.step()
    assert "R-001" in runner.store.requests
