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
    kind: str            # "breakdown" | "task" | "wake"
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


def task_runnable(store: Store, task: Task, auto_merge: bool = False) -> tuple[bool, str]:
    if task.stage in (Stage.DONE, Stage.BLOCKED):
        return False, ""
    if task.stage == Stage.TODO and not deps_done(store, task):
        pending = [d for d in task.depends_on if store.tasks.get(d) and store.tasks[d].stage != Stage.DONE]
        return False, f"{task.id} waits for {', '.join(pending)} to be merged"
    if task.stage == Stage.PR and task.pr_url and not auto_merge:
        return False, f"{task.id} waits for PO to merge {task.pr_url}"
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
        if req.status == "new":
            if not take(Step("breakdown", req.id, "claude")):
                reasons.append(f"{req.id} waits for claude")
        elif req.status == "planned" and req.task_ids and all(
                store.tasks[t].stage == Stage.DONE for t in req.task_ids if t in store.tasks):
            if not take(Step("goal", req.id, "claude")):
                reasons.append(f"{req.id} goal check waits for claude")
        elif req.status == "blocked":
            reasons.append(f"{req.id} waits for the PO to answer: {req.note}")

    tasks = sorted(store.tasks.values(), key=lambda t: t.id)
    for stage in STAGE_PRIORITY:
        for t in tasks:
            if t.stage != stage or t.id in busy or full():
                continue
            ok, why = task_runnable(store, t, auto_merge)
            if not ok:
                if why:
                    reasons.append(why)
                continue
            agent = None if stage == Stage.TODO else STAGE_AGENT[stage]  # todo -> spec is bookkeeping
            if not take(Step("task", t.id, agent)):
                reasons.append(f"{t.id} ({stage.value}) waits for {agent}")

    for t in tasks:
        if t.stage == Stage.BLOCKED:
            reasons.append(f"{t.id} waits for the PO to answer: {t.blocked_reason[:200]}")
    return Plan(steps[0] if steps else None, min(resting_wakes) if resting_wakes else None, reasons, steps)


def next_step(store: Store, now: datetime | None = None, auto_merge: bool = False) -> Plan:
    return plan_steps(store, now, auto_merge, limit=1)
