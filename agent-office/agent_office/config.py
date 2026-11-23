"""Config file: <target repo>/.agent-office/config.toml"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .models import DEFAULT_PROVIDER, PROVIDERS, ROLES

DEFAULT_PARALLEL = {"pm": 1, "lead": 1, "dev": 2, "tester": 1}

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
# "auto": merge as soon as the Tech Lead approves and tests pass, then continue with the next task.
# "manual": stop at the PR and wait for the PO to merge.
merge_mode = "auto"
# After all tasks of a request are merged, the PM checks the result against the request and
# may plan follow-up tasks. This caps those extra rounds per request.
max_goal_rounds = 3
# true = use built-in simulated agents (no CLI calls, no quota). `office demo` sets this.
simulate = false
sim_delay = 3.0
# Paths agents must never change (e.g. the orchestrator itself when it lives in the same repo).
protected_paths = []
# Prepares a task worktree; run by the orchestrator itself (outside the agent sandboxes, with
# network) when the worktree is created and again when an agent reports a missing dependency.
# Put the env in the worktree (`.venv/` is never committed; its bin/ goes first on the agents' PATH)
# so Codex can `pip install` into it from its sandbox.
# e.g. "python -m venv .venv && .venv/bin/python -m pip install -e '.[dev]'"
setup_cmd = ""
# Extra environment variables for the agent CLIs, read from this file (relative to .agent-office/,
# which git ignores) before every call, e.g. `CODEX_LB_API_KEY=...` when Codex runs through the
# codex-lb proxy. Never put this file in git. Empty = no file.
env_file = ".env"
# A `BLOCKED:` answer caused by a missing package/tool triggers setup_cmd and a retry, this many
# times per task, before the Tech Lead takes over.
dep_retries = 2
# Technical blockers (tests keep failing, review not approved, merge conflicts, guardrails, a
# developer `BLOCKED:`, technical questions) go to Claude as Tech Lead, never to the PO. The PO is
# asked only about unclear business requirements. Tech Lead decisions allowed per task; after that
# the task is dropped (reported to the PO) and the goal check re-plans what is still missing.
tech_lead_rounds = 3

[roles]
# Four separate agents. Each role has its own state, prompt, log, session slots and desk, and runs
# on one subscription CLI. Roles on the same CLI share that CLI's quota: when one of them hits the
# usage limit, all of them rest together (and one probe wakes them all).
pm = "claude"       # Product Manager: breakdown, specs, goal check
lead = "claude"     # Tech Lead / Reviewer: reviews, technical blockers, business-question screening
dev = "codex"       # Developer: code + unit tests (TDD)
tester = "codex"    # Tester: its own acceptance tests from the spec, runs everything, reports to dev

[claude]
cmd = "claude"
model = ""            # e.g. "opus" or "sonnet"; empty = CLI default
timeout_sec = 1800
extra_args = []
# Headless `claude -p` cannot approve permission prompts. Claude stays read-only (it plans and
# reviews); these command prefixes are allowed on top, so the reviewer can run tests itself.
allowed_commands = ["python -m pytest", "pytest", "ffprobe", "ffmpeg -version"]

[codex]
cmd = "codex"
model = ""
sandbox = "workspace-write"
timeout_sec = 3600
extra_args = []
# Network inside the workspace-write sandbox, so pip/npm can download packages. Writes stay
# limited to the worktree.
network = true

[limits]
# Rest ladder used when the CLI does not say when the limit resets.
backoff_minutes = [15, 30, 60]
# Rest ladder for a transient server error (502/503/504, connection refused, e.g. codex-lb down):
# retry soon, the last value repeats. The other CLI covers the work meanwhile.
upstream_retry_minutes = [1, 2, 5]

[parallel]
# How many sessions of each role may run at the same time. Each task has its own worktree,
# so independent tasks are coded in parallel. More sessions = faster, but quota runs out sooner.
# (Old configs with `claude = 1` / `codex = 2` still work: the number applies to every role on that CLI.)
pm = 1
lead = 1
dev = 2
tester = 1

[quality]
# Command that measures product quality in a worktree and prints JSON with the metric, e.g.
# `sportscut eval data/eval --json` -> {"f1": 0.74, "precision": 0.8, "recall": 0.69}.
# When set, a task may not lower the metric below what is already on the base branch.
eval_cmd = ""
metric = "f1"
higher_is_better = true
max_drop = 0.0

[guardrails]
# Agent calls per subscription CLI per day (local time, all its roles together); 0 = no cap.
# When reached, every role on that CLI rests until midnight.
max_calls_per_day = { claude = 0, codex = 0 }
# Most tasks the PM may create for one request (breakdown + each follow-up round).
max_tasks_per_request = 12
# A task whose diff changes more lines than this goes back to the Tech Lead to split (0 = no cap).
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
    network: bool = True
    allowed_commands: list[str] = field(default_factory=list)
    env_file: str = ""  # extra variables for the CLI (the office's `.agent-office/.env`)


@dataclass
class Config:
    base_branch: str = "main"
    worktrees_dir: str = "../{repo}-worktrees"
    test_cmd: str = ""
    open_pr: bool = True
    remote: str = "origin"
    protected_paths: list[str] = field(default_factory=list)
    setup_cmd: str = ""
    dep_retries: int = 2
    tech_lead_rounds: int = 3
    merge_mode: str = "auto"
    max_goal_rounds: int = 3
    simulate: bool = False
    sim_delay: float = 3.0
    claude: AgentConfig = field(default_factory=lambda: AgentConfig(cmd="claude"))
    codex: AgentConfig = field(default_factory=lambda: AgentConfig(cmd="codex", timeout_sec=3600))
    backoff_minutes: list[int] = field(default_factory=lambda: [15, 30, 60])
    upstream_retry_minutes: list[int] = field(default_factory=lambda: [1, 2, 5])
    roles: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PROVIDER))
    parallel: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_PARALLEL))
    max_calls_per_day: dict[str, int] = field(default_factory=lambda: {"claude": 0, "codex": 0})
    max_tasks_per_request: int = 12
    max_diff_lines: int = 4000
    block_secrets: bool = True
    eval_cmd: str = ""
    eval_metric: str = "f1"
    eval_higher_is_better: bool = True
    eval_max_drop: float = 0.0

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
        network=bool(d.get("network", True)),
        allowed_commands=[str(x) for x in d.get("allowed_commands", [])],
    )


def _roles(d: dict) -> dict[str, str]:
    out = {}
    for r in ROLES:
        p = str(d.get(r, DEFAULT_PROVIDER[r])).strip().lower()
        out[r] = p if p in PROVIDERS else DEFAULT_PROVIDER[r]
    return out


def _parallel(par: dict, roles: dict[str, str]) -> dict[str, int]:
    """Sessions per role: the role's own key, else an old per-CLI key (`codex = 2`), else the default."""
    return {r: max(1, int(par.get(r, par.get(roles[r], DEFAULT_PARALLEL[r])))) for r in ROLES}


def load_config(office_dir: Path) -> Config:
    path = office_dir / "config.toml"
    raw = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    o = raw.get("office", {})
    par = raw.get("parallel", {})
    g = raw.get("guardrails", {})
    q = raw.get("quality", {})
    caps = g.get("max_calls_per_day", {}) if isinstance(g.get("max_calls_per_day"), dict) else {}
    roles = _roles(raw.get("roles", {}))
    env_file = str(o.get("env_file", ".env"))
    env_path = str((office_dir / env_file).resolve()) if env_file else ""
    claude, codex = _agent(raw.get("claude", {}), "claude", 1800), _agent(raw.get("codex", {}), "codex", 3600)
    claude.env_file = codex.env_file = env_path
    return Config(
        base_branch=o.get("base_branch", "main"),
        worktrees_dir=o.get("worktrees_dir", "../{repo}-worktrees"),
        test_cmd=o.get("test_cmd", ""),
        open_pr=bool(o.get("open_pr", True)),
        remote=o.get("remote", "origin"),
        protected_paths=[str(x) for x in o.get("protected_paths", [])],
        setup_cmd=str(o.get("setup_cmd", "")),
        dep_retries=max(0, int(o.get("dep_retries", 2))),
        tech_lead_rounds=max(1, int(o.get("tech_lead_rounds", 3))),
        merge_mode=str(o.get("merge_mode", "auto")).lower(),
        max_goal_rounds=int(o.get("max_goal_rounds", 3)),
        simulate=bool(o.get("simulate", False)),
        sim_delay=float(o.get("sim_delay", 3.0)),
        claude=claude,
        codex=codex,
        backoff_minutes=list(raw.get("limits", {}).get("backoff_minutes", [15, 30, 60])) or [15, 30, 60],
        upstream_retry_minutes=list(raw.get("limits", {}).get("upstream_retry_minutes", [1, 2, 5])) or [1, 2, 5],
        roles=roles,
        parallel=_parallel(par, roles),
        max_calls_per_day={n: max(0, int(caps.get(n, 0))) for n in PROVIDERS},
        max_tasks_per_request=int(g.get("max_tasks_per_request", 12)),
        max_diff_lines=int(g.get("max_diff_lines", 4000)),
        block_secrets=bool(g.get("block_secrets", True)),
        eval_cmd=str(q.get("eval_cmd", "")),
        eval_metric=str(q.get("metric", "f1")),
        eval_higher_is_better=bool(q.get("higher_is_better", True)),
        eval_max_drop=float(q.get("max_drop", 0.0)),
    )


def write_default_config(office_dir: Path) -> Path:
    path = office_dir / "config.toml"
    if not path.exists():
        path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return path
