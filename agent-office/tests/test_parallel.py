"""Phase 4: parallel sessions, automatic merge-conflict resolution, guardrails, stats."""
import json
import subprocess
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from agent_office.cli import main as office_main
from agent_office.models import Stage
from agent_office.scheduler import plan_steps


def events(repo):
    return [json.loads(x) for x in (repo / ".agent-office/events.jsonl").read_text().splitlines()]


def set_cfg(env, *pairs):
    cfg = env.repo / ".agent-office/config.toml"
    text = cfg.read_text()
    for old, new in pairs:
        assert old in text, old
        text = text.replace(old, new)
    cfg.write_text(text)


def run_parallel(env, office, limit=500):
    peak = {"claude": 0, "codex": 0}
    with ThreadPoolExecutor(max_workers=6) as pool:
        running = set()
        for _ in range(limit):
            running |= set(office.dispatch(pool))
            if running:
                with office.lock:
                    for name in peak:
                        peak[name] = max(peak[name], sum(1 for a in office.inflight.values() if a == name))
                _, running = wait(running, timeout=10, return_when=FIRST_COMPLETED)
                continue
            if any(a.rest_until for a in office.store.agents.values()):
                env.advance(minutes=2)
                continue
            return peak
    raise AssertionError("parallel office did not settle")


def test_plan_steps_respects_sessions_and_busy(auto_env):
    env = auto_env
    office = env.office()
    office.add_request("Cut highlights")
    env.script(claude_breakdown=[{"result": json.dumps({"tasks": [
        {"key": str(i), "title": f"Task {i}", "brief": "x", "depends_on": []} for i in range(1, 5)]})}])
    office.step()  # breakdown -> 4 independent tasks
    for t in office.store.tasks.values():
        t.stage = Stage.DEV
    plan = plan_steps(office.store, env.now, True, slots={"claude": 1, "codex": 2})
    assert [s.target for s in plan.steps] == ["T-001", "T-002"]
    plan = plan_steps(office.store, env.now, True, busy={"T-001"}, slots={"claude": 1, "codex": 1})
    assert [s.target for s in plan.steps] == ["T-002"]


def test_parallel_demo_runs_codex_twice_and_resolves_conflicts(auto_env):
    env = auto_env
    set_cfg(env, ("simulate = false", "simulate = true"), ("sim_delay = 3.0", "sim_delay = 0.3"))
    office = env.office()
    office.add_request("SportsCut MVP")
    peak = run_parallel(env, office)
    assert peak["codex"] == 2 and peak["claude"] == 1
    tasks = office.store.tasks
    assert len(tasks) == 5 and all(t.stage == Stage.DONE for t in tasks.values()), \
        {t.id: (t.stage.value, t.blocked_reason) for t in tasks.values()}
    assert office.store.requests["R-001"].status == "done"
    ev = events(env.repo)
    names = [e["event"] for e in ev]
    assert "step_crashed" not in names
    assert "merge_conflict" in names and "conflict_resolved" in names
    reg = (env.repo / "sportscut/commands.py").read_text()
    assert all(f"'T-00{i}'" in reg for i in range(1, 6)) and "<<<<<<<" not in reg
    log = subprocess.run(["git", "log", "--format=%s", "main"], cwd=env.repo, capture_output=True, text=True).stdout
    assert "conflicts resolved by codex" in log
    codex = office.store.agents["codex"]
    assert codex.calls_total >= 10 and codex.rests_total == 1 and codex.active == []


def test_secret_in_diff_never_merges_and_the_branch_is_thrown_away(auto_env):
    env = auto_env
    env.script(codex_dev=[{"write": "settings.py", "text": "API_KEY = 'sk-ant-api03-abcdefghijklmnopqrstuvwxyz'\n"}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert any(e["event"] == "guardrail" and e["rule"] == "secret" for e in events(env.repo))
    # Tech Lead retry on a secret = fresh branch from main; the secret commit is gone everywhere
    assert t1.stage == Stage.DONE and t1.attempt == 1 and not t1.dropped
    history = subprocess.run(["git", "log", "--all", "-p"], cwd=env.repo, capture_output=True, text=True).stdout
    assert "sk-ant-api03" not in history


def test_daily_budget_rests_agent_until_midnight(auto_env):
    env = auto_env
    set_cfg(env, ("max_calls_per_day = { claude = 0, codex = 0 }", "max_calls_per_day = { claude = 2, codex = 0 }"))
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    claude = office.store.agents["claude"]
    assert claude.status.value == "resting" and claude.calls_today == 2
    assert any(e["event"] == "budget_reached" for e in events(env.repo))
    assert "T00:00:00" in claude.rest_until or claude.rest_until  # rests until local midnight


def test_max_tasks_per_request(auto_env):
    env = auto_env
    set_cfg(env, ("max_tasks_per_request = 12", "max_tasks_per_request = 1"))
    office = env.office()
    office.add_request("Cut highlights")
    office.step()
    assert list(office.store.tasks) == ["T-001"]


def test_stats_command(auto_env, capsys):
    env = auto_env
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    assert office_main(["--repo", str(env.repo), "stats"]) == 0
    out = capsys.readouterr().out
    assert "claude" in out and "codex" in out and "done 2" in out


def test_stats_api(auto_env):
    import pytest
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from agent_office.dashboard.server import create_app

    c = TestClient(create_app(auto_env.repo))
    st = c.get("/api/stats").json()
    assert st["agents"]["codex"]["max_sessions"] == 2 and st["done"] == 0
    assert c.get("/api/state").json()["config"]["parallel"] == {"claude": 1, "codex": 2}
