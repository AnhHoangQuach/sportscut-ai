"""Pick the next unit of work, honouring per-agent rest periods.

Agents rest independently: if Codex is out of quota, Claude can still write specs
and reviews for other tasks.
"""
from __future__ import annotations

from dataclasses import dataclass
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


def task_runnable(store: Store, task: Task) -> tuple[bool, str]:
    if task.stage in (Stage.DONE, Stage.BLOCKED):
        return False, ""
    if task.stage == Stage.TODO and not deps_done(store, task):
        pending = [d for d in task.depends_on if store.tasks.get(d) and store.tasks[d].stage != Stage.DONE]
        return False, f"{task.id} waits for {', '.join(pending)} to be merged"
    if task.stage == Stage.PR and task.pr_url:
        return False, f"{task.id} waits for PO to merge {task.pr_url}"
    return True, ""


def next_step(store: Store, now: datetime | None = None) -> Plan:
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    resting_wakes: list[datetime] = []

    # Resting agents whose rest has expired get woken (probed) first.
    for a in store.agents.values():
        if a.status == AgentStatus.RESTING:
            until = _parse(a.rest_until)
            if until is None or now >= until:
                return Plan(Step("wake", a.name, a.name))
            resting_wakes.append(until)
            reasons.append(f"{a.name} resting until {a.rest_until}")

    for req in store.requests.values():
        if req.status == "new":
            if agent_available(store, "claude", now):
                return Plan(Step("breakdown", req.id, "claude"))
            reasons.append(f"{req.id} waits for claude")

    tasks = sorted(store.tasks.values(), key=lambda t: t.id)
    for stage in STAGE_PRIORITY:
        for t in tasks:
            if t.stage != stage:
                continue
            ok, why = task_runnable(store, t)
            if not ok:
                if why:
                    reasons.append(why)
                continue
            agent = STAGE_AGENT[stage]
            if stage == Stage.TODO:
                agent = None  # todo -> spec is a bookkeeping move
            if agent_available(store, agent, now):
                return Plan(Step("task", t.id, agent))
            reasons.append(f"{t.id} ({stage.value}) waits for {agent}")

    return Plan(None, min(resting_wakes) if resting_wakes else None, reasons)
