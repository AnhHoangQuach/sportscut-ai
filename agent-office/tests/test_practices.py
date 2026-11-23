"""Phase 5: engineering practices in the prompts and the eval (quality) gate."""
import json
import sys

from agent_office.models import Stage
from agent_office.pipeline import prompt

EVAL = (f"{sys.executable} -c \"import json,pathlib;p=pathlib.Path('score.txt');"
        "print('noise');print(json.dumps({'f1': float(p.read_text()) if p.exists() else 0.5}))\"")


def set_cfg(env, *pairs):
    cfg = env.repo / ".agent-office/config.toml"
    text = cfg.read_text()
    for old, new in pairs:
        assert old in text, old
        text = text.replace(old, new)
    cfg.write_text(text)


def test_prompts_carry_the_practices():
    dev = prompt("dev", task_id="T-001", mode="")
    assert "test-driven-development" in dev and "SEE it fail" in dev and "DEV_NOTES.md" in dev
    assert "systematic-debugging" in dev and "verification-before-completion" in dev
    assert "brainstorming" in prompt("pm_breakdown", request="x", request_id="R-001")
    assert "writing-plans" in prompt("pm_spec", request="x", task_id="T-001", title="t", brief="b", po_answer="")
    review = prompt("review", task_id="T-001", round=1, max_rounds=3, spec="", acceptance_criteria="",
                    test_summary="", dev_notes="red: test_x failed", diff="")
    assert "red: test_x failed" in review and "eval score" in review
    assert "A test that cannot fail" in prompt("test", task_id="T-001", extra="")


def test_eval_gate_blocks_a_quality_drop_then_lets_the_fix_through(auto_env):
    env = auto_env
    set_cfg(env, ('eval_cmd = ""', "eval_cmd = " + json.dumps(EVAL)))
    env.script(codex_dev=[{"write": "score.txt", "text": "0.8"},       # T-001 sets the bar
                          {"write": "score.txt", "text": "0.6"},       # T-002 makes it worse
                          {"write": "score.txt", "text": "0.9"}])      # T-002 fixed
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1, t2 = office.store.tasks["T-001"], office.store.tasks["T-002"]
    assert t1.stage == Stage.DONE and t2.stage == Stage.DONE
    assert t2.test_attempts == 1 and t1.eval_score == 0.8 and t2.eval_score == 0.9
    assert office.store.meta["eval_baseline"] == 0.9
    assert [h["score"] for h in office.store.meta["eval_history"]] == [0.8, 0.9]
    dev_prompts = [c["prompt"] for c in env.calls() if c["kind"] == "dev"]
    assert "got worse: 0.6000 vs 0.8000" in (env.repo / ".agent-office").joinpath("state.json").read_text() \
        or any("found failures last time" in p for p in dev_prompts)
    review_prompts = [c["prompt"] for c in env.calls() if c["kind"] == "review"]
    assert any("Eval f1: 0.9000" in p for p in review_prompts)


def test_init_writes_team_rules(env):
    assert (env.repo / "AGENTS.md").exists() and "Test first" in (env.repo / "AGENTS.md").read_text()
    assert (env.repo / "CLAUDE.md").read_text().startswith("@AGENTS.md")
