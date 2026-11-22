"""Config file: <target repo>/.agent-office/config.toml"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG = """\
# Agent Office config. No API keys: both CLIs must be logged in with your subscription
# (`claude` -> /login with Pro/Max, `codex` -> `codex login` with ChatGPT).

[office]
base_branch = "main"
# Where task worktrees go. Relative paths are resolved from the target repo.
worktrees_dir = "../{repo}-worktrees"
# Command the orchestrator runs itself to verify a task (empty = trust the tester agent).
test_cmd = ""
# Open a GitHub PR with `gh pr create` when a task is approved.
open_pr = true
remote = "origin"
# "auto": merge as soon as Claude approves and tests pass, then continue with the next task.
# "manual": stop at the PR and wait for the PO to merge.
merge_mode = "auto"
# After all tasks of a request are merged, Claude checks the result against the request and
# may plan follow-up tasks. This caps those extra rounds per request.
max_goal_rounds = 3
# true = use built-in simulated agents (no CLI calls, no quota). `office demo` sets this.
simulate = false
sim_delay = 3.0
# Paths agents must never change (e.g. the orchestrator itself when it lives in the same repo).
protected_paths = []

[claude]
cmd = "claude"
model = ""            # e.g. "opus" or "sonnet"; empty = CLI default
timeout_sec = 1800
extra_args = []

[codex]
cmd = "codex"
model = ""
sandbox = "workspace-write"
timeout_sec = 3600
extra_args = []

[limits]
# Rest ladder used when the CLI does not say when the limit resets.
backoff_minutes = [15, 30, 60]

[parallel]
# How many sessions of each agent may run at the same time. Each task has its own worktree,
# so independent tasks are coded in parallel. More sessions = faster, but quota runs out sooner.
claude = 1
codex = 2

[guardrails]
# Agent calls per agent per day (local time); 0 = no cap. When reached the agent rests until midnight.
max_calls_per_day = { claude = 0, codex = 0 }
# Most tasks Claude may create for one request (breakdown + each follow-up round).
max_tasks_per_request = 12
# A task whose diff changes more lines than this goes to the PO instead of review (0 = no cap).
max_diff_lines = 4000
# Stop a task whose diff adds something that looks like a key, token or private key.
block_secrets = true
"""


@dataclass
class AgentConfig:
    cmd: str
    model: str = ""
    timeout_sec: int = 1800
    extra_args: list[str] = field(default_factory=list)
    sandbox: str = "workspace-write"


@dataclass
class Config:
    base_branch: str = "main"
    worktrees_dir: str = "../{repo}-worktrees"
    test_cmd: str = ""
    open_pr: bool = True
    remote: str = "origin"
    protected_paths: list[str] = field(default_factory=list)
    merge_mode: str = "auto"
    max_goal_rounds: int = 3
    simulate: bool = False
    sim_delay: float = 3.0
    claude: AgentConfig = field(default_factory=lambda: AgentConfig(cmd="claude"))
    codex: AgentConfig = field(default_factory=lambda: AgentConfig(cmd="codex", timeout_sec=3600))
    backoff_minutes: list[int] = field(default_factory=lambda: [15, 30, 60])
    parallel: dict[str, int] = field(default_factory=lambda: {"claude": 1, "codex": 2})
    max_calls_per_day: dict[str, int] = field(default_factory=lambda: {"claude": 0, "codex": 0})
    max_tasks_per_request: int = 12
    max_diff_lines: int = 4000
    block_secrets: bool = True

    def worktrees_path(self, repo: Path) -> Path:
        p = Path(self.worktrees_dir.format(repo=repo.name))
        return (p if p.is_absolute() else (repo / p)).resolve()


def _agent(d: dict, default_cmd: str, default_timeout: int) -> AgentConfig:
    return AgentConfig(
        cmd=d.get("cmd", default_cmd),
        model=d.get("model", ""),
        timeout_sec=int(d.get("timeout_sec", default_timeout)),
        extra_args=list(d.get("extra_args", [])),
        sandbox=d.get("sandbox", "workspace-write"),
    )


def load_config(office_dir: Path) -> Config:
    path = office_dir / "config.toml"
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    o = raw.get("office", {})
    par = raw.get("parallel", {})
    g = raw.get("guardrails", {})
    caps = g.get("max_calls_per_day", {}) if isinstance(g.get("max_calls_per_day"), dict) else {}
    return Config(
        base_branch=o.get("base_branch", "main"),
        worktrees_dir=o.get("worktrees_dir", "../{repo}-worktrees"),
        test_cmd=o.get("test_cmd", ""),
        open_pr=bool(o.get("open_pr", True)),
        remote=o.get("remote", "origin"),
        protected_paths=[str(x) for x in o.get("protected_paths", [])],
        merge_mode=str(o.get("merge_mode", "auto")).lower(),
        max_goal_rounds=int(o.get("max_goal_rounds", 3)),
        simulate=bool(o.get("simulate", False)),
        sim_delay=float(o.get("sim_delay", 3.0)),
        claude=_agent(raw.get("claude", {}), "claude", 1800),
        codex=_agent(raw.get("codex", {}), "codex", 3600),
        backoff_minutes=list(raw.get("limits", {}).get("backoff_minutes", [15, 30, 60])) or [15, 30, 60],
        parallel={n: max(1, int(par.get(n, d))) for n, d in (("claude", 1), ("codex", 2))},
        max_calls_per_day={n: max(0, int(caps.get(n, 0))) for n in ("claude", "codex")},
        max_tasks_per_request=int(g.get("max_tasks_per_request", 12)),
        max_diff_lines=int(g.get("max_diff_lines", 4000)),
        block_secrets=bool(g.get("block_secrets", True)),
    )


def write_default_config(office_dir: Path) -> Path:
    path = office_dir / "config.toml"
    if not path.exists():
        path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return path
