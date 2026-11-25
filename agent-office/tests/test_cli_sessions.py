"""[parallel] claude = N / codex = M: how many sessions of each subscription CLI run at the same
time, all its roles together (failover sessions count for the CLI that actually runs them)."""
import json
from concurrent.futures import ThreadPoolExecutor

from agent_office.config import load_config
from agent_office.models import AgentStatus, Stage
from agent_office.scheduler import plan_steps
from test_parallel import events, run_parallel, set_cfg

ALL = {"pm": 3, "lead": 3, "dev": 3, "tester": 3}


def four_tasks(env, office, stage=Stage.DEV):
    office.add_request("Cut highlights")
    env.script(claude_breakdown=[{"result": json.dumps({"tasks": [
        {"key": str(i), "title": f"Task {i}", "brief": "x", "depends_on": []} for i in range(1, 5)]})}])
    office.step()
    for t in office.store.tasks.values():
        t.stage = stage


def test_default_config_has_a_session_count_per_cli(env):
    cfg = load_config(env.repo / ".agent-office")
    assert cfg.cli_parallel == {"claude": 2, "codex": 3}
    assert cfg.parallel == {"pm": 1, "lead": 1, "dev": 2, "tester": 1}


def test_cli_count_is_read_and_missing_means_no_cap(env):
    set_cfg(env, ("claude = 2\ncodex = 3", "codex = 1"))
    cfg = load_config(env.repo / ".agent-office")
    assert cfg.cli_parallel == {"claude": 0, "codex": 1}
    assert cfg.parallel == {"pm": 1, "lead": 1, "dev": 2, "tester": 1}  # role counts unchanged


def test_old_config_with_only_cli_keys_also_caps_the_cli_total(env):
    set_cfg(env, ("pm = 1\nlead = 1\ndev = 2\ntester = 1\n", ""))  # only `claude = 2`, `codex = 3` left
    cfg = load_config(env.repo / ".agent-office")
    assert cfg.parallel == {"pm": 2, "lead": 2, "dev": 3, "tester": 3}
    assert cfg.cli_parallel == {"claude": 2, "codex": 3}


def test_plan_steps_never_starts_more_codex_sessions_than_the_cli_count(auto_env):
    env = auto_env
    office = env.office()
    four_tasks(env, office)
    office.store.tasks["T-004"].stage = Stage.TEST
    plan = plan_steps(office.store, env.now, True, slots=ALL, cli_slots={"codex": 2})
    assert [(s.target, s.agent) for s in plan.steps] == [("T-004", "tester"), ("T-001", "dev")]
    assert any("T-002" in r and "codex" in r for r in plan.waiting_on)
    plan = plan_steps(office.store, env.now, True, slots=ALL, cli_slots={"codex": 0})
    assert plan.steps == []


def test_failover_session_counts_for_the_cli_that_runs_it(auto_env):
    env = auto_env
    office = env.office()
    four_tasks(env, office)
    for role in ("dev", "tester"):
        a = office.store.agents[role]
        a.status, a.rest_until, a.rest_cause = AgentStatus.RESTING, "2026-11-22T14:00:00+00:00", "quota"
    plan = plan_steps(office.store, env.now, True, slots=ALL, cli_slots={"claude": 1, "codex": 3})
    assert [(s.target, s.agent) for s in plan.steps if s.kind == "task"] == [("T-001", "pm")]


def test_dispatch_caps_running_sessions_per_cli(auto_env):
    env = auto_env
    set_cfg(env, ("dev = 2", "dev = 3"), ("codex = 3", "codex = 2"))
    office = env.office()
    four_tasks(env, office)
    office.inflight["T-001"] = "dev"
    office.inflight["T-002"] = "tester"  # codex already runs 2 sessions
    office.dispatch(ThreadPoolExecutor(max_workers=1))
    assert set(office.inflight) == {"T-001", "T-002"}
    idle = [e for e in events(env.repo) if e["event"] == "slots_idle" and e["role"] == "dev"]
    assert idle and any("codex" in w and "2/2" in w for w in idle[-1]["waiting_on"])
    assert any("dev: 2/3 sessions idle" in line and "codex 2/2" in line for line in env.lines)


def test_parallel_run_respects_cli_count(auto_env):
    env = auto_env
    set_cfg(env, ("simulate = false", "simulate = true"), ("sim_delay = 3.0", "sim_delay = 0.3"),
            ("dev = 2", "dev = 3"), ("tester = 1", "tester = 2"), ("codex = 3", "codex = 1"))
    office = env.office()
    peak_cli = {"codex": 0}
    orig = office.dispatch

    def dispatch(pool):
        started = orig(pool)
        with office.lock:
            n = sum(1 for a in office.inflight.values() if a and office.store.agents[a].provider == "codex")
            peak_cli["codex"] = max(peak_cli["codex"], n)
        return started

    office.dispatch = dispatch
    office.add_request("SportsCut MVP")
    run_parallel(env, office)
    assert all(t.stage == Stage.DONE for t in office.store.tasks.values())
    assert peak_cli["codex"] == 1


def test_stats_show_sessions_per_cli(auto_env):
    from agent_office import stats

    office = auto_env.office()
    office.store.agents["dev"].active = ["T-001"]
    office.store.agents["tester"].active = ["T-002"]
    st = stats.collect(office.store, load_config(office.store.dir))
    assert st["providers"]["codex"]["sessions"] == 2 and st["providers"]["codex"]["max_sessions"] == 3
    assert st["providers"]["claude"]["max_sessions"] == 2
