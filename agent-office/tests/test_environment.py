"""Agents fix their own environment: network for Codex, allowed commands for Claude,
a setup command run by the orchestrator, and automatic retries on missing dependencies."""
import json
import subprocess
import sys
from pathlib import Path

from agent_office.agents import ClaudeAgent, CodexAgent
from agent_office.config import AgentConfig, load_config
from agent_office.models import Stage
from agent_office.pipeline import prompt

from test_practices import set_cfg

MISSING = "BLOCKED: tests fail with ModuleNotFoundError: No module named 'numpy'"
# Counts its runs and creates a project venv, like `python -m venv .venv && pip install -e .`
SETUP = (f"{sys.executable} -c \"import pathlib;p=pathlib.Path('.venv/bin');p.mkdir(parents=True,exist_ok=True);"
         "c=pathlib.Path('.venv/setup_runs');c.write_text(str(int(c.read_text())+1 if c.exists() else 1))\"")


def test_codex_gets_network_in_its_sandbox_unless_turned_off(tmp_path):
    on = CodexAgent(AgentConfig(cmd="codex")).build_cmd(tmp_path, {})
    assert "sandbox_workspace_write.network_access=true" in on and on[on.index("--sandbox") + 1] == "workspace-write"
    off = CodexAgent(AgentConfig(cmd="codex", network=False)).build_cmd(tmp_path, {})
    assert not any("network_access" in a for a in off)


def test_claude_may_run_only_the_allowed_commands(tmp_path):
    cmd = ClaudeAgent(AgentConfig(cmd="claude", allowed_commands=["python -m pytest", "ffprobe"])).build_cmd(
        tmp_path, {})
    tools = cmd[cmd.index("--allowedTools") + 1:]
    assert "Bash(python -m pytest:*)" in tools and "Bash(ffprobe:*)" in tools and "Read" in tools
    assert not any(t in ("Bash", "Bash(*)", "Write", "Edit") for t in tools)
    assert "--dangerously-skip-permissions" not in cmd


def test_default_config_turns_self_repair_on(env):
    cfg = load_config(env.repo / ".agent-office")
    assert cfg.codex.network is True and cfg.dep_retries == 2 and cfg.setup_cmd == ""
    assert "python -m pytest" in cfg.claude.allowed_commands


def test_prompts_say_install_and_retry_before_blocked():
    for text in (prompt("dev", task_id="T-001", mode=""), prompt("test", task_id="T-001", extra="")):
        assert "is not a blocker" in text and "install" in text and "2 attempts" in text


def test_setup_runs_in_new_worktree_and_venv_is_used_but_not_committed(env):
    set_cfg(env, ('setup_cmd = ""', "setup_cmd = " + json.dumps(SETUP)))
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    wt = Path(t1.worktree)
    assert t1.stage == Stage.PR and (wt / ".venv/setup_runs").read_text() == "1"
    dev = next(c for c in env.calls() if c["kind"] == "dev")
    assert dev["path0"] == str(wt / ".venv" / "bin")
    files = subprocess.run(["git", "ls-files"], cwd=wt, capture_output=True, text=True).stdout
    assert ".venv" not in files


def test_missing_dependency_is_fixed_and_retried_without_the_po(env):
    set_cfg(env, ('setup_cmd = ""', "setup_cmd = " + json.dumps(SETUP)))
    env.script(codex_dev=[{"message": MISSING}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.PR and t1.env_fixes == 1
    assert (Path(t1.worktree) / ".venv/setup_runs").read_text() == "2"   # new worktree + the fix
    dev = [c["prompt"] for c in env.calls() if c["kind"] == "dev"]
    assert "ENVIRONMENT" in dev[1] and "No module named 'numpy'" in dev[1]


def test_tech_lead_not_the_po_takes_over_after_the_retries_are_used(env):
    env.script(codex_dev=[{"message": MISSING}] * 3)
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.PR and t1.tl_rounds == 1 and not t1.blocked_reason
    tl = [c["prompt"] for c in env.calls() if c["kind"] == "techlead"]
    assert len(tl) == 1 and "missing_dependency" in tl[0] and "numpy" in tl[0]
    dev = [c["prompt"] for c in env.calls() if c["kind"] == "dev"]
    assert len(dev) == 4 and "TECH LEAD DECISION" in dev[3]


def test_a_business_blocker_reaches_the_po_through_the_tech_lead(env):
    env.script(codex_dev=[{"message": "BLOCKED: the spec does not say which leagues to support"}],
               claude_techlead=[{"tl": {"business_questions": ["Which leagues: Premier League only, or all?"]}}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.BLOCKED and t1.env_fixes == 0
    assert t1.questions == ["Which leagues: Premier League only, or all?"] and "business" in t1.blocked_reason
