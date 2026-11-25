"""Separate roles: Claude = PM + Tech Lead, Codex = Developer + Tester. Each role is its own agent
(state, prompt, log, session slot, desk); roles on the same CLI share one subscription quota."""
import json

import pytest

from agent_office.cli import main as office_main
from agent_office.config import load_config
from agent_office.models import AgentStatus, Stage
from agent_office.scheduler import plan_steps
from agent_office.store import Store


def events(repo):
    return [json.loads(x) for x in (repo / ".agent-office/events.jsonl").read_text().splitlines()]


def set_cfg(env, *pairs):
    cfg = env.repo / ".agent-office/config.toml"
    text = cfg.read_text()
    for old, new in pairs:
        assert old in text, old
        text = text.replace(old, new)
    cfg.write_text(text)


def test_four_roles_on_two_subscriptions_by_default(env):
    store = Store(env.repo).load()
    assert {n: a.provider for n, a in store.agents.items()} == {
        "pm": "claude", "lead": "claude", "dev": "codex", "tester": "codex"}
    cfg = load_config(store.dir)
    assert cfg.roles == {"pm": "claude", "lead": "claude", "dev": "codex", "tester": "codex"}
    assert cfg.parallel == {"pm": 1, "lead": 1, "dev": 2, "tester": 1}


def test_old_parallel_keys_apply_to_every_role_of_that_cli(env):
    set_cfg(env, ("pm = 1\nlead = 1\ndev = 2\ntester = 1\n", ""))  # only `claude = 2`, `codex = 3` left
    assert load_config(env.repo / ".agent-office").parallel == {"pm": 2, "lead": 2, "dev": 3, "tester": 3}


def test_roles_section_moves_a_role_to_the_other_cli(env):
    set_cfg(env, ('tester = "codex"', 'tester = "claude"'))
    store = Store(env.repo).load()
    assert store.agents["tester"].provider == "claude"
    assert [a.name for a in store.roles_of("claude")] == ["pm", "lead", "tester"]


def test_old_state_with_one_agent_per_cli_is_migrated(env):
    state = env.repo / ".agent-office/state.json"
    data = json.loads(state.read_text())
    data["agents"] = [
        {"name": "claude", "status": "idle", "calls_total": 7, "calls_today": 2, "calls_day": "2026-11-22"},
        {"name": "codex", "status": "resting", "rest_until": "2026-11-22T14:00:00+00:00", "rest_cause": "quota",
         "rest_detail": "usage limit reached", "reset_known": True, "calls_total": 5, "rests_total": 1},
    ]
    state.write_text(json.dumps(data))
    store = Store(env.repo).load()
    assert sorted(store.agents) == ["dev", "lead", "pm", "tester"]
    for name in ("dev", "tester"):  # both roles of the resting CLI keep resting until the same time
        a = store.agents[name]
        assert a.status == AgentStatus.RESTING and a.rest_until == "2026-11-22T14:00:00+00:00"
        assert a.rest_cause == "quota" and a.reset_known
    assert store.agents["lead"].status == AgentStatus.IDLE
    # usage counters are kept once per CLI, not doubled
    assert store.agents["pm"].calls_total == 7 and store.agents["lead"].calls_total == 0
    assert store.agents["dev"].calls_total + store.agents["tester"].calls_total == 5
    store.save()
    assert {a["name"] for a in json.loads(state.read_text())["agents"]} == {"pm", "lead", "dev", "tester"}


def test_each_step_belongs_to_its_role(env):
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    assert office.store.tasks["T-001"].stage == Stage.PR
    work = [(e["agent"], e["label"]) for e in events(env.repo) if e["event"] == "agent_working"]
    labels = {}
    for agent, label in work:
        labels.setdefault(label.rstrip("0123456789"), set()).add(agent)
    assert labels == {"breakdown": {"pm"}, "spec": {"pm"}, "dev": {"dev"}, "test": {"tester"},
                      "review": {"lead"}}
    by_kind = {c["kind"]: c["agent"] for c in env.calls()}
    assert by_kind["dev"] == "codex" and by_kind["test"] == "codex"
    assert by_kind["spec"] == "claude" and by_kind["review"] == "claude"
    logs = sorted(p.name for p in (env.repo / ".agent-office/logs/T-001").iterdir())
    assert any(n.endswith("-dev-dev.log") for n in logs) and any(n.endswith("-test-tester.log") for n in logs)
    assert any(n.endswith("-review1-lead.log") for n in logs) and any(n.endswith("-spec-pm.log") for n in logs)
    a = office.store.agents
    assert all(a[r].calls_total >= 1 for r in ("pm", "lead", "dev", "tester"))


def test_handoffs_go_developer_to_tester_to_tech_lead(auto_env):
    env = auto_env
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    pairs = {(m["frm"], m["to"], m["topic"]) for m in events(env.repo) if m["event"] == "message"}
    assert ("po", "pm", "request") in pairs and ("pm", "po", "plan") in pairs
    assert ("pm", "dev", "assign") in pairs
    assert ("dev", "tester", "handoff") in pairs
    assert ("tester", "lead", "handoff") in pairs
    assert ("lead", "dev", "approve") in pairs and ("lead", "po", "merged") in pairs
    assert ("pm", "po", "done") in pairs


def test_tester_failure_goes_back_to_the_developer_with_the_report(env):
    env.script(codex_test=[{"write": "test_acceptance_t1.py", "text": "def test_ac1():\n    assert False\n",
                            "message": "test_ac1 fails: feature_1.VALUE is 1, AC1 wants 2\nRESULT: FAIL"}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.PR and t1.test_attempts == 1
    assert "test_acceptance_t1.py" in t1.tester_files
    said = [m for m in events(env.repo) if m["event"] == "message" and m["topic"] == "test_fail"]
    assert said and said[0]["frm"] == "tester" and said[0]["to"] == "dev"
    dev_prompts = [c["prompt"] for c in env.calls() if c["kind"] == "dev"]
    assert len(dev_prompts) >= 2 and "Tester" in dev_prompts[1]
    task_md = (env.tmp / "sportscut-worktrees" / "T-001" / ".office" / "TASK.md").read_text()
    assert "test_acceptance_t1.py" in task_md  # the developer is told which tests are the Tester's


def test_tester_is_told_when_the_developer_changed_its_tests(env):
    env.script(codex_test=[{"write": "test_acceptance_t1.py", "text": "def test_ac1():\n    assert False\n",
                            "message": "RESULT: FAIL"}],
               codex_dev=[{}, {"write": "test_acceptance_t1.py", "text": "def test_ac1():\n    pass\n"}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    assert any(e["event"] == "tests_changed_by_dev" and e["files"] == ["test_acceptance_t1.py"]
               for e in events(env.repo))
    test_prompts = [c["prompt"] for c in env.calls() if c["kind"] == "test"]
    assert "test_acceptance_t1.py" in test_prompts[1] and "changed" in test_prompts[1]


def test_quota_limit_rests_every_role_of_that_cli_together(env):
    env.script(codex_dev=[{"limit": "You've hit your usage limit. Try again in 2 hours."}])
    office = env.office()
    office.add_request("Cut highlights")
    office.step()  # breakdown
    office.step()  # todo -> spec
    office.step()  # spec
    office.step()  # dev hits the Codex limit
    a = office.store.agents
    assert a["dev"].status == AgentStatus.RESTING and a["tester"].status == AgentStatus.RESTING
    assert a["dev"].rest_until == a["tester"].rest_until
    assert a["pm"].status == AgentStatus.IDLE and a["lead"].status == AgentStatus.IDLE
    rest = [e for e in events(env.repo) if e["event"] == "agent_resting"]
    assert rest[-1]["provider"] == "codex" and rest[-1]["roles"] == ["dev", "tester"]
    assert a["dev"].rests_total + a["tester"].rests_total == 1


def test_one_probe_wakes_all_roles_of_a_cli(env):
    env.script(codex_dev=[{"fail": True}, {"fail": True}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    a = office.store.agents
    assert a["dev"].status == AgentStatus.RESTING and a["tester"].status == AgentStatus.RESTING
    env.advance(minutes=16)
    plan = plan_steps(office.store, env.now)
    wakes = [s for s in plan.steps if s.kind == "wake"]
    assert [s.target for s in wakes] == ["codex"]
    env.run_all(office)
    assert a["dev"].status != AgentStatus.RESTING and a["tester"].status != AgentStatus.RESTING
    assert len([c for c in env.calls() if c["kind"] == "probe"]) == 1


def test_two_failures_from_different_roles_of_one_cli_rest_it(env):
    env.script(codex_test=[{"fail": True}])
    office = env.office()
    office.add_request("Cut highlights")
    a = office.store.agents
    while office.store.tasks.get("T-001") is None or office.store.tasks["T-001"].stage != Stage.TEST:
        office.step()
    a["dev"].failures = 1  # e.g. a parallel dev session failed just before
    office.step()  # the tester's run fails too: the Codex CLI is failing, not one role
    assert a["tester"].rest_cause == "failure" and a["dev"].status == AgentStatus.RESTING


def test_daily_budget_counts_all_roles_of_a_cli(auto_env):
    env = auto_env
    set_cfg(env, ("max_calls_per_day = { claude = 0, codex = 0 }", "max_calls_per_day = { claude = 2, codex = 0 }"))
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    a = office.store.agents
    assert a["pm"].calls_today == 2 and a["lead"].calls_today == 0  # breakdown + spec used the budget
    assert a["lead"].status == AgentStatus.RESTING and a["pm"].status == AgentStatus.RESTING
    assert a["lead"].rest_cause == "budget"


@pytest.mark.parametrize("name", ["tester", "codex"])
def test_wake_accepts_a_role_or_a_cli_name(env, name):
    office = env.office()
    for role in ("dev", "tester"):
        a = office.store.agents[role]
        a.status, a.rest_until, a.rest_cause = AgentStatus.RESTING, "2026-11-22T14:00:00+00:00", "quota"
    office.store.save()
    assert office_main(["--repo", str(env.repo), "wake", name]) == 0
    store = Store(env.repo).load()
    assert all(store.agents[r].status == AgentStatus.IDLE for r in ("dev", "tester"))


def test_wake_rejects_unknown_names(env, capsys):
    with pytest.raises(SystemExit):
        office_main(["--repo", str(env.repo), "wake", "gpt"])


def test_failover_keeps_the_role_but_uses_the_other_cli(env):
    office = env.office()
    req = office.add_request("Cut highlights")
    req.status = "planned"
    office._add_tasks(req, [{"key": "1", "title": "Cut", "brief": "x"}])
    task = office.store.tasks[req.task_ids[0]]
    task.stage = Stage.TEST
    for role in ("dev", "tester"):
        a = office.store.agents[role]
        a.status, a.rest_until, a.rest_cause = AgentStatus.RESTING, "2026-11-22T14:00:00+00:00", "quota"
    step = plan_steps(office.store, env.now, True).steps[0]
    assert (step.target, step.agent) == (task.id, "lead")  # the Tech Lead covers testing on Claude
    task.stage = Stage.DEV
    assert plan_steps(office.store, env.now, True).steps[0].agent == "pm"


def test_stats_show_roles_and_subscriptions(auto_env, capsys):
    env = auto_env
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    assert office_main(["--repo", str(env.repo), "stats", "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert set(st["agents"]) == {"pm", "lead", "dev", "tester"}
    assert st["agents"]["tester"]["provider"] == "codex" and st["agents"]["tester"]["max_sessions"] == 1
    assert set(st["providers"]) == {"claude", "codex"}
    assert st["providers"]["codex"]["roles"] == ["dev", "tester"]
    assert st["providers"]["codex"]["calls_total"] == st["agents"]["dev"]["calls_total"] + \
        st["agents"]["tester"]["calls_total"]
    assert office_main(["--repo", str(env.repo), "stats"]) == 0
    out = capsys.readouterr().out
    assert "tester" in out and "codex" in out and "lead" in out


def test_every_role_prompt_is_recognised_as_its_own_step():
    """The fake CLI and the demo agents tell steps apart by role markers; a prompt that mentions
    another role must not be mistaken for it (the dev prompt talks about the Tester)."""
    import sys
    from pathlib import Path

    from agent_office.agents.sim import SimAgent
    from agent_office.pipeline import prompt
    sys.path.insert(0, str(Path(__file__).parent))
    from fake_agent import kind_of
    sim = SimAgent("codex", 0, Path("/nonexistent"))
    for name, kind in (("dev", "dev"), ("test", "test"), ("review", "review"), ("pm_spec", "spec"),
                       ("pm_breakdown", "breakdown"), ("pm_goal", "goal"), ("tech_lead", "techlead")):
        text = prompt(name)
        assert kind_of("codex", text) == kind and sim._kind(text) == kind, name
