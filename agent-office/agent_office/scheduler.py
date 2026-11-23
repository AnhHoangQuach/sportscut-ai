"""Pick the next unit of work, honouring per-agent rest periods.

Agents rest independently: if Codex is out of quota, Claude can still write specs
and reviews for other tasks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import STAGE_AGENT, AgentStatus, Stage, Task
from .store import Store

# Finish work in flight before starting new work.
STAGE_PRIORITY = [Stage.PR, Stage.REVIEW, Stage.TEST, Stage.DEV, Stage.SPEC, Stage.TODO]


@dataclass
class Step:
    kind: str            # "breakdown" | "goal" | "task" | "techlead" | "wake"
    target: str          # request id, task id, or agent name
    agent: str | None


@dataclass
class Plan:
    step: Step | None
    wait_until: datetime | None = None   # earliest moment a resting agent can work
    waiting_on: list[str] | None = None  # human-readable reasons nothing can run
    steps: list[Step] = field(default_factory=list)  # everything that may start now (plan_steps)


def _parse(ts: str) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


def agent_available(store: Store, name: str | None, now: datetime) -> bool:
    if name is None:
        return True
    a = store.agents[name]
    if a.status != AgentStatus.RESTING:
        return True
    until = _parse(a.rest_until)
    return until is None or now >= until


def deps_done(store: Store, task: Task) -> bool:
    return all(store.tasks[d].stage == Stage.DONE for d in task.depends_on if d in store.tasks)


# Append-only files with git's union merge driver never conflict, so they never serialize tasks.
NEVER_CONFLICT = ("docs/superpowers/INDEX.md", "docs/superpowers/DECISIONS.md")


def _norm(path: str) -> str:
    p = path.strip().strip("`").replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def _overlap(a: list[str], b: list[str]) -> list[str]:
    """Paths in `a` that are the same as, inside, or contain a path in `b`."""
    out = []
    bs = [_norm(x).rstrip("/") for x in b if _norm(x) and _norm(x) not in NEVER_CONFLICT]
    for x in a:
        x = _norm(x).rstrip("/")
        if not x or x in NEVER_CONFLICT:
            continue
        if any(x == y or x.startswith(y + "/") or y.startswith(x + "/") for y in bs):
            out.append(x)
    return out


def file_conflict(store: Store, task: Task) -> tuple[str, list[str]]:
    """Tech Lead ordering rule: a task that has not started coding waits while another active task
    changes the same files (the one already coding, else the lower id, goes first). This keeps
    parallel sessions from producing merge conflicts. Returns (other task id, shared files)."""
    if task.worktree or not task.files:
        return "", []
    for u in sorted(store.tasks.values(), key=lambda t: t.id):
        if u.id == task.id or u.stage in (Stage.DONE, Stage.TODO, Stage.SPEC) or not u.files:
            continue
        if u.stage == Stage.BLOCKED and not u.worktree:
            continue
        if not (u.worktree or u.id < task.id):
            continue
        shared = _overlap(task.files, u.files)
        if shared:
            return u.id, shared
    return "", []


def task_runnable(store: Store, task: Task, auto_merge: bool = False,
                  now: datetime | None = None) -> tuple[bool, str]:
    if task.stage in (Stage.DONE, Stage.BLOCKED):
        return False, ""
    until = _parse(task.retry_at)
    if until is not None and now is not None and now < until:
        return False, f"{task.id} waits until {task.retry_at} (Tech Lead decision)"
    if task.stage == Stage.TODO and not deps_done(store, task):
        pending = [d for d in task.depends_on if store.tasks.get(d) and store.tasks[d].stage != Stage.DONE]
        return False, f"{task.id} waits for {', '.join(pending)} to be merged"
    if task.stage == Stage.PR and task.pr_url and not auto_merge:
        return False, f"{task.id} waits for PO to merge {task.pr_url}"
    if task.stage == Stage.DEV:
        other, shared = file_conflict(store, task)
        if other:
            return False, f"{task.id} waits for {other}: both change {', '.join(shared[:3])}"
    return True, ""


def plan_steps(store: Store, now: datetime | None = None, auto_merge: bool = False,
               busy: set[str] | frozenset[str] = frozenset(), slots: dict[str, int] | None = None,
               limit: int | None = None) -> Plan:
    """Every step that can start now, in priority order.

    busy: request/task ids/agent names that already have a step running (skipped).
    slots: free sessions per agent (None = no cap; each chosen step uses one slot).
    """
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    resting_wakes: list[datetime] = []
    steps: list[Step] = []
    free = dict(slots) if slots is not None else None
    unavailable: set[str] = set()

    def full() -> bool:
        return limit is not None and len(steps) >= limit

    def take(step: Step) -> bool:
        a = step.agent
        if a is not None:
            if a in unavailable:
                return False
            if free is not None:
                if free.get(a, 0) <= 0:
                    return False
                free[a] -= 1
        steps.append(step)
        return True

    # Resting agents whose rest has expired get woken (probed) before they do anything else.
    for a in store.agents.values():
        if a.status != AgentStatus.RESTING:
            continue
        unavailable.add(a.name)
        until = _parse(a.rest_until)
        if until is None or now >= until:
            if a.name not in busy and not full():
                steps.append(Step("wake", a.name, a.name))
            continue
        resting_wakes.append(until)
        reasons.append(f"{a.name} resting until {a.rest_until}")

    for req in store.requests.values():
        if full():
            break
        if req.id in busy:
            continue
        until = _parse(req.retry_at)
        if req.status in ("new", "planned") and until is not None and now < until:
            resting_wakes.append(until)
            reasons.append(f"{req.id} waits until {req.retry_at} (Tech Lead decision)")
            continue
        if req.tl_issue and req.status in ("new", "planned"):
            if not take(Step("techlead", req.id, "claude")):
                reasons.append(f"{req.id} waits for the Tech Lead (claude)")
            continue
        if req.status == "new":
            if not take(Step("breakdown", req.id, "claude")):
                reasons.append(f"{req.id} waits for claude")
        elif req.status == "planned" and req.task_ids and all(
                store.tasks[t].stage == Stage.DONE for t in req.task_ids if t in store.tasks):
            if not take(Step("goal", req.id, "claude")):
                reasons.append(f"{req.id} goal check waits for claude")
        elif req.status == "blocked":
            reasons.append(f"{req.id} waits for the PO to answer a business question: {req.note}")

    tasks = sorted(store.tasks.values(), key=lambda t: t.id)
    # Technical blockers first: the Tech Lead unblocks a task before new work starts.
    for t in tasks:
        if t.tl_issue and t.stage not in (Stage.DONE, Stage.BLOCKED) and t.id not in busy and not full():
            if not take(Step("techlead", t.id, "claude")):
                reasons.append(f"{t.id} waits for the Tech Lead (claude): {t.tl_kind}")
    for t in tasks:
        until = _parse(t.retry_at)
        if until is not None and now < until and t.stage not in (Stage.DONE, Stage.BLOCKED):
            resting_wakes.append(until)
    for stage in STAGE_PRIORITY:
        for t in tasks:
            if t.stage != stage or t.id in busy or full() or t.tl_issue:
                continue
            ok, why = task_runnable(store, t, auto_merge, now)
            if not ok:
                if why:
                    reasons.append(why)
                continue
            agent = None if stage == Stage.TODO else STAGE_AGENT[stage]  # todo -> spec is bookkeeping
            if not take(Step("task", t.id, agent)):
                reasons.append(f"{t.id} ({stage.value}) waits for {agent}")

    for t in tasks:
        if t.stage == Stage.BLOCKED:
            reasons.append(f"{t.id} waits for the PO to answer a business question: {t.blocked_reason[:200]}")
    return Plan(steps[0] if steps else None, min(resting_wakes) if resting_wakes else None, reasons, steps)


def next_step(store: Store, now: datetime | None = None, auto_merge: bool = False) -> Plan:
    return plan_steps(store, now, auto_merge, limit=1)
