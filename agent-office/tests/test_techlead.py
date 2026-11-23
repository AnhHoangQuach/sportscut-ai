"""The PO only sends requests. Technical and coordination blockers go to Claude as Tech Lead,
who decides (retry, restart, split, wait, drop) and logs the decision; only business questions
reach the PO. Tasks that change the same files are ordered so they do not block each other."""
import json
import subprocess

from agent_office.config import load_config
from agent_office.models import Stage, Task
from agent_office.pipeline import prompt
from agent_office.scheduler import file_conflict, plan_steps

from test_practices import set_cfg


def events(repo):
    return [json.loads(x) for x in (repo / ".agent-office/events.jsonl").read_text().splitlines()]


def po_messages(repo):
    return [e for e in events(repo) if e["event"] == "message" and e["to"] == "po"]


def never_blocked(task):
    return not any(h.get("to") == "blocked" for h in task.history)


def test_technical_spec_question_is_answered_by_the_tech_lead_not_the_po(env):
    env.script(claude_spec=[{"questions": ["argparse or click for the CLI?"]}], claude_techlead=[{"tl": {
        "action": "retry", "decision": "CLI uses argparse (stdlib, no new dependency)",
        "guidance": "argparse or click: use argparse."}}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.PR and never_blocked(t1) and t1.questions == []
    tl = next(c["prompt"] for c in env.calls() if c["kind"] == "techlead")
    assert "argparse or click for the CLI?" in tl and "business_questions" in tl
    spec2 = [c["prompt"] for c in env.calls() if c["kind"] == "spec"][1]
    assert "Tech Lead decisions" in spec2 and "use argparse" in spec2
    decisions = subprocess.run(["git", "show", f"{t1.branch}:docs/superpowers/DECISIONS.md"], cwd=env.repo,
                               capture_output=True, text=True).stdout
    assert "Tech Lead (questions): CLI uses argparse" in decisions
    assert not any(e["topic"] == "question" for e in po_messages(env.repo))


def test_technical_breakdown_question_is_answered_and_planning_goes_on(auto_env):
    env = auto_env
    env.script(claude_breakdown=[{"questions": ["One module or a package?"]}], claude_techlead=[{"tl": {
        "action": "retry", "decision": "Start with a package sportscut/", "guidance": "A package."}}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    req = office.store.requests["R-001"]
    assert req.status == "done" and req.questions == [] and len(req.task_ids) == 2
    assert "Q: One module or a package?\nA: A package." in req.tl_notes[0]
    assert "Tech Lead decisions" in [c["prompt"] for c in env.calls() if c["kind"] == "breakdown"][1]
    assert "Tech Lead (questions): Start with a package sportscut/" in req.decisions


def test_failing_tests_after_all_attempts_get_a_new_approach_from_the_tech_lead(env):
    env.script(codex_test=[{"message": "2 failed\nRESULT: FAIL"}] * 3)
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.PR and never_blocked(t1) and t1.tl_rounds == 1 and t1.test_attempts == 0
    tl = next(c["prompt"] for c in env.calls() if c["kind"] == "techlead")
    assert "tests_failing" in tl and "2 failed" in tl
    assert "TECH LEAD DECISION" in [c["prompt"] for c in env.calls() if c["kind"] == "dev"][-1]


def test_split_replaces_the_task_and_rewires_dependents(env):
    env.script(claude_review=[{"verdict": "changes"}] * 3, claude_techlead=[{"tl": {
        "action": "split", "decision": "T-001 mixes CLI and config; split it",
        "tasks": [{"key": "1", "title": "CLI skeleton", "brief": "b", "depends_on": []},
                  {"key": "2", "title": "Config file", "brief": "b", "depends_on": ["1"]}]}}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    tasks = office.store.tasks
    assert tasks["T-001"].stage == Stage.DONE and "split into T-003, T-004" in tasks["T-001"].dropped
    assert tasks["T-004"].depends_on == ["T-003"]
    assert tasks["T-002"].depends_on == ["T-003", "T-004"]
    assert tasks["T-003"].stage == Stage.PR  # manual merge mode: waits for the PO to merge
    assert office.store.requests["R-001"].task_ids == ["T-001", "T-002", "T-003", "T-004"]


def test_restart_after_another_task_starts_fresh_from_the_base(env):
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.PR
    old_branch = t1.branch
    office._escalate(t1, "merge_conflict", "merge conflict with main still there after 2 attempts")
    env.script(claude_techlead=[{"tl": {"action": "restart", "after": ["T-002"],
                                        "decision": "Redo T-001 on top of T-002, they both change cli.py"}}])
    office.step()
    assert t1.stage == Stage.TODO and t1.depends_on == ["T-002"] and t1.attempt == 1
    assert t1.worktree == "" and t1.pr_url == "" and t1.conflicts == 0
    branches = subprocess.run(["git", "branch", "--list"], cwd=env.repo, capture_output=True, text=True).stdout
    assert old_branch in branches  # kept for reference (only a secret branch is deleted)
    t1.depends_on = []  # pretend T-002 merged
    env.run_all(office)
    assert t1.stage == Stage.PR and t1.branch == "office/T-001-r2"


def test_wait_pauses_the_task_without_asking_anyone(env):
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    office._escalate(t1, "merge_failed", "could not merge: gh: connection refused")
    env.script(claude_techlead=[{"tl": {"action": "wait", "minutes": 30, "decision": "GitHub is down; retry"}}])
    office.step()
    assert t1.retry_at and t1.stage == Stage.PR and not t1.tl_issue
    plan = plan_steps(office.store, env.now, True)
    assert all(s.target != "T-001" for s in plan.steps) and plan.wait_until is not None
    assert any("T-001 waits until" in w for w in plan.waiting_on)
    env.advance(minutes=31)
    assert any(s.target == "T-001" for s in plan_steps(office.store, env.now, True).steps)


def test_unreadable_tech_lead_answer_is_retried_then_the_task_is_dropped_and_reported(env):
    set_cfg(env, ("tech_lead_rounds = 3", "tech_lead_rounds = 2"))
    env.script(claude_spec=[{"questions": ["x?"]}], claude_techlead=[{"result": "no json"}, {"result": "still no"}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.DONE and t1.dropped and never_blocked(t1)
    assert len([c for c in env.calls() if c["kind"] == "techlead"]) == 2
    assert [e for e in events(env.repo) if e["event"] == "techlead_unparseable"]
    assert any(e["topic"] == "report" for e in po_messages(env.repo))
    assert office.store.tasks["T-002"].stage == Stage.PR  # the rest of the request keeps going


def test_request_level_tech_lead_out_of_rounds_pauses_instead_of_asking(auto_env):
    env = auto_env
    set_cfg(env, ("tech_lead_rounds = 3", "tech_lead_rounds = 1"))
    env.script(claude_breakdown=[{"result": "not json"}, {"result": "not json"}],
               claude_techlead=[{"tl": {"action": "retry", "decision": "re-plan"}}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    req = office.store.requests["R-001"]
    assert req.status == "new" and req.retry_at and req.questions == []
    assert any(e["event"] == "techlead_paused" for e in events(env.repo))
    env.advance(minutes=61)
    env.run_all(office)
    assert req.status == "done"


def test_goal_rounds_cap_closes_the_request_with_a_report(auto_env):
    env = auto_env
    set_cfg(env, ("max_goal_rounds = 3", "max_goal_rounds = 1"))
    more = {"goal": {"done": False, "summary": "export missing", "tasks": [
        {"key": "1", "title": "Export", "brief": "b", "depends_on": []}]}}
    env.script(claude_goal=[more, more])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    req = office.store.requests["R-001"]
    assert req.status == "done" and "export missing" in req.note
    msgs = po_messages(env.repo)
    assert any(e["topic"] == "report" for e in msgs) and not any(e["topic"] == "question" for e in msgs)


def _task(tid, stage, files, worktree=""):
    return Task(id=tid, title=tid, brief="", request_id="R-001", stage=stage, files=files, worktree=worktree)


def test_tasks_that_change_the_same_files_run_one_after_the_other(env):
    office = env.office()
    st = office.store
    st.tasks = {t.id: t for t in (
        _task("T-001", Stage.DEV, ["sportscut/cli.py", "docs/superpowers/DECISIONS.md"]),
        _task("T-002", Stage.DEV, ["./sportscut/cli.py"]),
        _task("T-003", Stage.DEV, ["sportscut/audio.py", "docs/superpowers/DECISIONS.md"]),
        _task("T-004", Stage.DEV, ["sportscut/"]))}
    plan = plan_steps(st, env.now, False, slots={"claude": 1, "codex": 4})
    assert [s.target for s in plan.steps] == ["T-001", "T-003"]
    assert any("T-002 waits for T-001: both change sportscut/cli.py" in w for w in plan.waiting_on)
    # a task already coding keeps its files even when a lower id arrives later
    st.tasks["T-001"].stage = Stage.SPEC
    st.tasks["T-002"].worktree = "/wt/T-002"
    assert file_conflict(st, st.tasks["T-004"])[0] == "T-002"
    assert file_conflict(st, st.tasks["T-002"]) == ("", [])


def test_spec_files_are_recorded_for_ordering(env):
    env.script(claude_spec=[{"spec": {"spec": "s", "acceptance_criteria": ["a"], "test_plan": ["t"],
                                      "files": ["sportscut/cli.py"]}}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    assert office.store.tasks["T-001"].files == ["sportscut/cli.py"]


def test_prompts_keep_technical_questions_away_from_the_po():
    tl = prompt("tech_lead")
    for word in ("business_questions", "Technical", "retry", "restart", "split", "wait", "drop",
                 "guardrails cannot be waived", "DECISIONS.md"):
        assert word in tl, word
    for name in ("pm_breakdown", "pm_spec", "pm_goal"):
        assert "business" in prompt(name) and "never" in prompt(name), name
    assert '"files"' in prompt("pm_spec")
    assert "same file" in prompt("pm_breakdown")
    assert "Tech Lead" in prompt("dev", task_id="T-001", mode="")


def test_default_config_gives_the_tech_lead_three_rounds(env):
    assert load_config(env.repo / ".agent-office").tech_lead_rounds == 3
