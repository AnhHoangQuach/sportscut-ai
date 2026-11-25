"""PO picks, per role, which CLI (and optionally which model) it runs on, from the dashboard,
without editing config.toml by hand or restarting `office run`."""
import json
import tomllib
from datetime import timedelta

import pytest

from agent_office.agents.base import AgentResult
from agent_office.agents.claude import ClaudeAgent
from agent_office.config import load_config, set_role
from agent_office.limits import LimitHit
from agent_office.models import AgentStatus, Stage
from agent_office.pipeline import Office


def events(repo, kind=None):
    rows = [json.loads(x) for x in (repo / ".agent-office/events.jsonl").read_text().splitlines()]
    return [e for e in rows if kind is None or e["event"] == kind]


def model_arg(call):
    a = call["args"]
    return a[a.index("--model") + 1] if "--model" in a else ""


def test_set_role_edits_only_the_roles_section_of_config(env):
    office_dir = env.repo / ".agent-office"
    before = (office_dir / "config.toml").read_text()
    set_role(office_dir, "pm", "codex", "gpt-5-codex")
    text = (office_dir / "config.toml").read_text()
    cfg = load_config(office_dir)
    assert cfg.roles == {"pm": "codex", "lead": "claude", "dev": "codex", "tester": "codex"}
    assert cfg.role_models["pm"] == "gpt-5-codex" and cfg.role_models["lead"] == ""
    assert "# Product Manager: breakdown, specs, goal check" in text  # comments kept
    assert text.count("\n") >= before.count("\n")
    tomllib.loads(text)
    set_role(office_dir, "pm", "claude", "")
    assert load_config(office_dir).roles["pm"] == "claude"
    assert load_config(office_dir).role_models["pm"] == ""
    # every other line is untouched
    assert [ln for ln in (office_dir / "config.toml").read_text().splitlines() if "pm" not in ln] == \
        [ln for ln in before.splitlines() if "pm" not in ln]


@pytest.mark.parametrize("role,provider,model", [
    ("boss", "claude", ""), ("pm", "gpt", ""), ("pm", "claude", 'opus"\n[x]'), ("pm", "claude", "a b")])
def test_set_role_rejects_bad_values_and_keeps_the_file(env, role, provider, model):
    path = env.repo / ".agent-office/config.toml"
    before = path.read_text()
    with pytest.raises(ValueError):
        set_role(path.parent, role, provider, model)
    assert path.read_text() == before


def test_set_role_adds_a_roles_section_to_an_old_config(env):
    path = env.repo / ".agent-office/config.toml"
    path.write_text('[office]\nbase_branch = "main"\n')
    set_role(path.parent, "dev", "claude", "sonnet")
    cfg = load_config(path.parent)
    assert cfg.roles["dev"] == "claude" and cfg.role_models["dev"] == "sonnet"
    assert cfg.base_branch == "main"


def test_submit_without_runner_applies_now_and_the_role_runs_on_its_new_cli(env):
    office = env.office()
    res = office.submit({"cmd": "set_role", "role": "pm", "provider": "codex", "model": "gpt-5-codex"})
    assert res == ["pm now runs on codex (gpt-5-codex)"]
    assert office.store.agents["pm"].provider == "codex"
    e = events(env.repo, "role_changed")[-1]
    assert (e["role"], e["provider"], e["model"], e["from_provider"]) == ("pm", "codex", "gpt-5-codex", "claude")
    office.add_request("Cut highlights")
    env.run_all(office)
    breakdown = next(c for c in env.calls() if c["kind"] == "breakdown")
    assert breakdown["agent"] == "codex" and model_arg(breakdown) == "gpt-5-codex"


def test_running_office_applies_a_queued_change_without_restart(env):
    office = env.office()
    office.add_request("Cut highlights")
    office.step()  # breakdown on claude
    assert env.calls()[-1]["agent"] == "claude"
    # the dashboard (another process) queues the change while this runner is alive
    office.store.append_inbox({"cmd": "set_role", "role": "pm", "provider": "codex", "model": ""})
    env.run_all(office)
    specs = [c for c in env.calls() if c["kind"] == "spec"]
    assert specs and all(c["agent"] == "codex" for c in specs)
    assert office.cfg.roles["pm"] == "codex"
    assert load_config(env.repo / ".agent-office").roles["pm"] == "codex"  # persisted


def test_role_model_overrides_the_cli_model_only_for_that_role(env):
    set_role(env.repo / ".agent-office", "lead", "claude", "opus")
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    calls = env.calls()
    assert {model_arg(c) for c in calls if c["kind"] == "review"} == {"opus"}
    assert {model_arg(c) for c in calls if c["kind"] in ("breakdown", "spec")} == {""}


def test_moved_role_takes_the_rest_state_of_its_new_cli(env):
    office = env.office()
    until = (env.now + timedelta(hours=1)).isoformat(timespec="seconds")
    for name in ("dev", "tester"):
        a = office.store.agents[name]
        a.status, a.rest_until, a.rest_cause = AgentStatus.RESTING, until, "quota"
    office.store.save()
    office.submit({"cmd": "set_role", "role": "pm", "provider": "codex", "model": ""})
    pm = office.store.agents["pm"]
    assert pm.status == AgentStatus.RESTING and pm.rest_until == until and pm.rest_cause == "quota"
    office.submit({"cmd": "set_role", "role": "dev", "provider": "claude", "model": ""})
    dev = office.store.agents["dev"]
    assert dev.status == AgentStatus.IDLE and dev.rest_until == "" and dev.rest_cause == ""
    assert office.store.agents["tester"].status == AgentStatus.RESTING  # codex itself still rests


class SwitchingCodex:
    """Codex that hits its usage limit after the PO moved the Developer to Claude mid-call."""
    name = "codex"

    def __init__(self):
        self.office = None
        self.switched = False

    def env_problem(self):
        return ""

    def server_problem(self):
        return ""

    def run(self, text, cwd, log_path=None, **extra):
        if not self.switched and "**Developer**" in text:
            self.switched = True
            self.office.set_role("dev", "claude", "")
            return AgentResult("codex", 1, "", "usage limit", limit=LimitHit("codex", "usage limit", None),
                               log_path=str(log_path))
        return AgentResult("codex", 0, "", "", text="All good.\nRESULT: PASS")


def test_switch_during_a_call_rests_the_cli_that_answered_not_the_new_one(env):
    office = env.office()
    codex = SwitchingCodex()
    office = Office(env.repo, agents={"claude": ClaudeAgent(office.cfg.claude), "codex": codex},
                    clock=lambda: env.now, echo=env.lines.append)
    codex.office = office
    office.add_request("Cut highlights")
    for _ in range(10):
        office.step()
        if codex.switched:
            break
    assert codex.switched
    rests = events(env.repo, "agent_resting")
    assert [(e["provider"], e["roles"]) for e in rests] == [("codex", ["tester"])]
    assert office.store.agents["dev"].provider == "claude"
    assert office.store.agents["dev"].status != AgentStatus.RESTING
    assert office.store.agents["pm"].status != AgentStatus.RESTING
    t = office.store.tasks["T-001"]
    assert t.stage == Stage.DEV and t.checkpoint  # half-done work kept, resumed on Claude next
    office.step()
    assert next(c for c in reversed(env.calls()) if c["kind"] == "dev")["agent"] == "claude"


def test_dashboard_sets_role_and_state_shows_cli_and_model(auto_env):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from agent_office.dashboard.server import create_app
    c = TestClient(create_app(auto_env.repo))
    r = c.post("/api/roles/tester", json={"provider": "claude", "model": "sonnet"})
    assert r.status_code == 200 and r.json()["results"] == ["tester now runs on claude (sonnet)"]
    s = c.get("/api/state").json()
    tester = next(x for x in s["roles"] if x["name"] == "tester")
    assert (tester["provider"], tester["model"]) == ("claude", "sonnet")
    assert s["config"]["models"] == {"claude": "", "codex": ""}
    assert c.post("/api/roles/tester", json={"provider": "gpt", "model": ""}).status_code == 400
    assert c.post("/api/roles/tester", json={"provider": "claude", "model": "x y"}).status_code == 400
    assert c.post("/api/roles/boss", json={"provider": "claude", "model": ""}).status_code == 404
