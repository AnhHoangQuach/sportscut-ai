"""Pick the next unit of work, honouring per-CLI rest periods.

Each role (pm, lead, dev, tester) is its own agent with its own session slots. Roles on the same
CLI share its quota and rest together; roles on the other CLI keep working (if Codex is out of
quota, the PM can still write specs and the Tech Lead can still review other tasks).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .models import FAILOVER, STAGE_AGENT, STEP_ROLE, AgentStatus, Stage, Task
from .store import Store

# Finish work in flight before starting new work.
STAGE_PRIORITY = [Stage.PR, Stage.REVIEW, Stage.TEST, Stage.DEV, Stage.SPEC, Stage.TODO]


@dataclass
class Step:
    kind: str            # "breakdown" | "goal" | "task" | "techlead" | "wake"
    target: str          # request id, task id, or provider name (wake)
    agent: str | None    # role that runs it (None = orchestrator only)


@dataclass
class Plan:
    step: Step | None
    wait_until: datetime | None = None   # earliest moment a resting agent can work
    waiting_on: list[str] | None = None  # human-readable reasons nothing can run
    steps: list[Step] = field(default_factory=list)  # everything that may start now (plan_steps)


def _parse(ts: str) -> datetime | None:
    return datetime.fromisoformat(ts) if ts else None


def rest_reason(a) -> str:
    detail = a.rest_detail or a.last_error
    if a.rest_cause == "budget":
        text = f"daily call budget used: {detail}"
    elif a.rest_cause == "failure":
        text = f"CLI failed repeatedly, not quota: {detail}"
    else:
        text = f"quota: {detail}" + ("" if a.reset_known else "; reset time unknown, probing after the rest")
    return text + (f"; log {a.rest_log}" if a.rest_log else "")


def agent_available(store: Store, name: str | None, now: datetime) -> bool:
    if name is None:
        return True
    a = store.agents[name]
    if a.status != AgentStatus.RESTING:
        return True
    until = _parse(a.rest_until)
    return until is None or now >= until


def assigned_agent(store: Store, preferred: str, now: datetime) -> str:
    """Use a role on the other subscription only while the preferred role's CLI is quota-resting.

    Busy/session limits are handled separately by ``take`` and never cause failover.
    An expired rest is also not bypassed: the preferred CLI must pass its wake probe first.
    """
    agent = store.agents[preferred]
    if agent.status != AgentStatus.RESTING or agent.rest_cause not in ("quota", "budget"):
        return preferred
    for name in [FAILOVER.get(preferred, ""), *store.agents]:
        other = store.agents.get(name)
        if other is not None and other.provider != agent.provider and other.status != AgentStatus.RESTING:
            return other.name
    return preferred


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
        why = f"GitHub network retry {task.net_retries}/4" if task.net_retries else "Tech Lead decision"
        return False, f"{task.id} waits until {task.retry_at} ({why})"
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

    # Resting CLIs whose rest has expired get woken (one probe for all their roles) first.
    seen: set[str] = set()
    for a in store.agents.values():
        if a.status != AgentStatus.RESTING:
            continue
        unavailable.add(a.name)
        if a.provider in seen:
            continue
        seen.add(a.provider)
        until = _parse(a.rest_until)
        if until is None or now >= until:
            if a.provider not in busy and not full():
                steps.append(Step("wake", a.provider, None))
            continue
        resting_wakes.append(until)
        roles = ", ".join(r.name for r in store.roles_of(a.provider) if r.status == AgentStatus.RESTING)
        reasons.append(f"{a.provider} resting until {a.rest_until} (roles {roles}; {rest_reason(a)})")

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
            if not take(Step("techlead", req.id, assigned_agent(store, STEP_ROLE["techlead"], now))):
                reasons.append(f"{req.id} waits for the Tech Lead (lead)")
            continue
        if req.status == "new":
            if not take(Step("breakdown", req.id, assigned_agent(store, STEP_ROLE["breakdown"], now))):
                reasons.append(f"{req.id} waits for the PM (pm)")
        elif req.status == "planned" and req.task_ids and all(
                store.tasks[t].stage == Stage.DONE for t in req.task_ids if t in store.tasks):
            if not take(Step("goal", req.id, assigned_agent(store, STEP_ROLE["goal"], now))):
                reasons.append(f"{req.id} goal check waits for the PM (pm)")
        elif req.status == "blocked":
            reasons.append(f"{req.id} waits for the PO to answer a business question: {req.note}")

    tasks = sorted(store.tasks.values(), key=lambda t: t.id)
    # Technical blockers first: the Tech Lead unblocks a task before new work starts.
    for t in tasks:
        if t.tl_issue and t.stage not in (Stage.DONE, Stage.BLOCKED) and t.id not in busy and not full():
            if not take(Step("techlead", t.id, assigned_agent(store, STEP_ROLE["techlead"], now))):
                reasons.append(f"{t.id} waits for the Tech Lead (lead): {t.tl_kind}")
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
            preferred = None if stage == Stage.TODO else STAGE_AGENT[stage]  # todo -> spec is bookkeeping
            agent = assigned_agent(store, preferred, now) if preferred else None
            if not take(Step("task", t.id, agent)):
                reasons.append(f"{t.id} ({stage.value}) waits for {agent}")

    for t in tasks:
        if t.stage == Stage.BLOCKED:
            if t.blocked_reason.startswith("environment problem for the user"):
                reasons.append(f"{t.id} waits for you to fix GitHub on this machine (`office doctor`): "
                               f"{t.blocked_reason[:200]}")
            else:
                reasons.append(f"{t.id} waits for the PO to answer a business question: {t.blocked_reason[:200]}")
    return Plan(steps[0] if steps else None, min(resting_wakes) if resting_wakes else None, reasons, steps)


def next_step(store: Store, now: datetime | None = None, auto_merge: bool = False) -> Plan:
    return plan_steps(store, now, auto_merge, limit=1)
