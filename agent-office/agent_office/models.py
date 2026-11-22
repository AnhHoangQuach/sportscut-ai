"""Task and agent data model plus the legal stage transitions."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Stage(str, Enum):
    TODO = "todo"
    SPEC = "spec"
    DEV = "dev"
    TEST = "test"
    REVIEW = "review"
    PR = "pr"
    DONE = "done"
    BLOCKED = "blocked"


# Which agent does the work for a task sitting in a stage (None = orchestrator only).
STAGE_AGENT: dict[Stage, str | None] = {
    Stage.TODO: "claude",
    Stage.SPEC: "claude",
    Stage.DEV: "codex",
    Stage.TEST: "codex",
    Stage.REVIEW: "claude",
    Stage.PR: None,
    Stage.DONE: None,
    Stage.BLOCKED: None,
}

TRANSITIONS: dict[Stage, set[Stage]] = {
    Stage.TODO: {Stage.SPEC, Stage.BLOCKED},
    Stage.SPEC: {Stage.DEV, Stage.BLOCKED},
    Stage.DEV: {Stage.TEST, Stage.BLOCKED},
    Stage.TEST: {Stage.REVIEW, Stage.DEV, Stage.BLOCKED},
    Stage.REVIEW: {Stage.PR, Stage.DEV, Stage.BLOCKED},
    Stage.PR: {Stage.DONE, Stage.BLOCKED},
    Stage.DONE: set(),
    Stage.BLOCKED: {Stage.SPEC, Stage.DEV, Stage.TEST, Stage.REVIEW, Stage.PR},
}

MAX_REVIEW_ROUNDS = 3
MAX_TEST_ATTEMPTS = 3


class InvalidTransition(Exception):
    pass


@dataclass
class Task:
    id: str
    title: str
    brief: str
    request_id: str
    stage: Stage = Stage.TODO
    depends_on: list[str] = field(default_factory=list)
    spec: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    test_plan: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    branch: str = ""
    worktree: str = ""
    base_ref: str = ""
    review_round: int = 0
    test_attempts: int = 0
    review_comments: list[dict[str, Any]] = field(default_factory=list)
    test_output: str = ""
    blocked_reason: str = ""
    blocked_from: str = ""
    po_answer: str = ""
    questions: list[str] = field(default_factory=list)
    checkpoint: dict[str, Any] | None = None
    pr_url: str = ""
    history: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)

    def move(self, to: Stage, note: str = "") -> None:
        if to not in TRANSITIONS[self.stage]:
            raise InvalidTransition(f"{self.id}: {self.stage.value} -> {to.value} is not allowed")
        self.history.append({"at": now_iso(), "from": self.stage.value, "to": to.value, "note": note})
        self.stage = to

    def block(self, reason: str) -> None:
        self.blocked_from = self.stage.value
        self.blocked_reason = reason
        self.move(Stage.BLOCKED, reason)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["stage"] = self.stage.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        d = dict(d)
        d["stage"] = Stage(d["stage"])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


class AgentStatus(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    RESTING = "resting"


@dataclass
class Agent:
    name: str
    status: AgentStatus = AgentStatus.IDLE
    rest_until: str = ""  # ISO timestamp, empty when not resting
    backoff_level: int = 0
    reset_known: bool = False
    failures: int = 0  # consecutive non-limit failures
    last_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Agent":
        d = dict(d)
        d["status"] = AgentStatus(d["status"])
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Request:
    id: str
    text: str
    created_at: str = field(default_factory=now_iso)
    task_ids: list[str] = field(default_factory=list)
    status: str = "new"  # new -> planned -> done; blocked when the PO must answer
    note: str = ""
    goal_rounds: int = 0          # follow-up planning rounds done by the goal check
    blocked_stage: str = ""       # "new" or "planned": where an answer sends it back
    po_answers: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    summary: str = ""
