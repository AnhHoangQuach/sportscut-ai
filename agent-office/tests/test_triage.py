"""State saved before the Tech Lead existed: tasks and requests blocked "waiting for the PO" for a
technical reason are handed to the Tech Lead when the office starts again (or on `office triage`).
Only questions the Tech Lead already screened as business stay with the PO."""
import json

from agent_office.cli import main as office_main
from agent_office.models import Stage


def events(repo):
    return [json.loads(x) for x in (repo / ".agent-office/events.jsonl").read_text().splitlines()]


def legacy_block(office, task_id, stage, reason, questions=None):
    """What a pre-Tech-Lead office left in state.json."""
    t = office.store.tasks[task_id]
    t.stage, t.blocked_from, t.blocked_reason, t.questions = Stage.BLOCKED, stage, reason, questions or []
    office.store.save()
    return t


def planned(env):
    office = env.office()
    office.add_request("Cut highlights")
    office.step()  # breakdown -> T-001, T-002
    return office


def test_old_technical_blocks_go_to_the_tech_lead_when_the_office_starts(env):
    office = planned(env)
    legacy_block(office, "T-001", "test", "tests still failing after 3 attempts")
    legacy_block(office, "T-002", "spec", "PM needs answers: argparse or click?", ["argparse or click?"])
    office = env.office()   # restart on the new code
    env.run_all(office)
    t1, t2 = office.store.tasks["T-001"], office.store.tasks["T-002"]
    assert t1.stage == Stage.PR and t1.tl_rounds == 1 and t1.blocked_reason == ""
    kinds = [e["issue"] for e in events(env.repo) if e["event"] == "techlead_needed"]
    assert "tests_failing" in kinds and "questions" in kinds
    tl = [c["prompt"] for c in env.calls() if c["kind"] == "techlead"]
    assert any("argparse or click?" in p for p in tl)
    assert t2.stage == Stage.PR and t2.tl_rounds == 1 and t2.questions == []
    assert any(e["event"] == "triaged" for e in events(env.repo))


def test_business_questions_screened_by_the_tech_lead_stay_with_the_po(env):
    office = planned(env)
    legacy_block(office, "T-001", "spec", "business question for the PO: Which league?", ["Which league?"])
    office = env.office()
    office.step()
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.BLOCKED and t1.questions == ["Which league?"]
    assert not [c for c in env.calls() if c["kind"] == "techlead"]


def test_an_old_business_question_is_confirmed_by_the_tech_lead(env):
    env.script(claude_techlead=[{"tl": {"business_questions": ["Which league?"]}}])
    office = planned(env)
    legacy_block(office, "T-001", "spec", "PM needs answers: Which league?", ["Which league?"])
    office = env.office()
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.BLOCKED and t1.blocked_reason.startswith("business question")
    # screened once: a later start does not ask the Tech Lead again
    office = env.office()
    env.run_all(office)
    assert len([c for c in env.calls() if c["kind"] == "techlead"]) == 1


def test_old_blocked_request_is_triaged(auto_env):
    env = auto_env
    office = env.office()
    req = office.add_request("Cut highlights")
    req.status, req.blocked_stage, req.note = "blocked", "new", "PM needs answers before planning"
    req.questions = ["One module or a package?"]
    office.store.save()
    office = env.office()
    env.run_all(office)
    req = office.store.requests["R-001"]
    assert req.status == "done" and req.tl_notes and "One module or a package?" in req.tl_notes[0]


def test_old_goal_round_cap_block_closes_with_a_report(auto_env):
    env = auto_env
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    req = office.store.requests["R-001"]
    req.status, req.blocked_stage, req.note = "blocked", "planned", "still not done after 3 follow-up rounds: x"
    req.goal_rounds = 4
    office.store.save()
    env.script(claude_goal=[{"goal": {"done": False, "summary": "export missing",
                                       "tasks": [{"key": "1", "title": "Export", "brief": "b"}]}}])
    office = env.office()
    env.run_all(office)
    req = office.store.requests["R-001"]
    assert req.status == "done" and "export missing" in req.note


def test_office_triage_command(env, capsys):
    office = planned(env)
    legacy_block(office, "T-001", "dev", "BLOCKED: cannot decide the clip format")
    assert office_main(["--repo", str(env.repo), "triage"]) == 0
    out = capsys.readouterr().out
    assert "T-001" in out and "Tech Lead" in out
    t1 = env.office().store.tasks["T-001"]
    assert t1.stage == Stage.DEV and t1.tl_kind == "dev_blocked" and t1.tl_issue
