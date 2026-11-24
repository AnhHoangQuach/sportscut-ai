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


# Roles are separate agents (own state, prompt, log, session slots, desk). Each runs on one
# subscription CLI ("provider"); roles on the same CLI share its quota and rest together.
ROLES = ("pm", "lead", "dev", "tester")
PROVIDERS = ("claude", "codex")
DEFAULT_PROVIDER = {"pm": "claude", "lead": "claude", "dev": "codex", "tester": "codex"}
ROLE_TITLE = {"pm": "Product Manager", "lead": "Tech Lead · Reviewer", "dev": "Developer", "tester": "Tester"}
# While a CLI rests (out of quota, budget, env or failing), a role on the other CLI covers its work (creating <-> creating,
# checking <-> checking). The covering role keeps its own identity; permissions follow the step.
# A task left half-done (checkpoint) stays with the CLI whose session it is; the cover takes other tasks.
FAILOVER = {"pm": "dev", "dev": "pm", "lead": "tester", "tester": "lead"}

# Which role does the work for a task sitting in a stage (None = orchestrator only).
STAGE_AGENT: dict[Stage, str | None] = {
    Stage.TODO: "pm",
    Stage.SPEC: "pm",
    Stage.DEV: "dev",
    Stage.TEST: "tester",
    Stage.REVIEW: "lead",
    Stage.PR: None,
    Stage.DONE: None,
    Stage.BLOCKED: None,
}
# Request-level steps.
STEP_ROLE = {"breakdown": "pm", "goal": "pm", "techlead": "lead"}

TRANSITIONS: dict[Stage, set[Stage]] = {
    Stage.TODO: {Stage.SPEC, Stage.BLOCKED},
    Stage.SPEC: {Stage.DEV, Stage.BLOCKED},
    Stage.DEV: {Stage.TEST, Stage.BLOCKED},
    Stage.TEST: {Stage.REVIEW, Stage.DEV, Stage.BLOCKED},
    Stage.REVIEW: {Stage.PR, Stage.DEV, Stage.BLOCKED},
    Stage.PR: {Stage.DONE, Stage.DEV, Stage.BLOCKED},  # dev: merge conflict to resolve
    Stage.DONE: set(),
    Stage.BLOCKED: {Stage.SPEC, Stage.DEV, Stage.TEST, Stage.REVIEW, Stage.PR},
}

MAX_REVIEW_ROUNDS = 3
MAX_TEST_ATTEMPTS = 3
MAX_CONFLICT_ROUNDS = 2  # times the developer may resolve a merge conflict on one task


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
    decisions: list[str] = field(default_factory=list)       # logged in docs/superpowers/DECISIONS.md
    related_specs: list[str] = field(default_factory=list)   # existing spec files this task must update
    branch: str = ""
    worktree: str = ""
    base_ref: str = ""
    review_round: int = 0
    test_attempts: int = 0
    env_fixes: int = 0            # times setup_cmd was re-run because the agent lacked a dependency
    env_note: str = ""            # what the last environment fix found, shown to the next dev run
    review_comments: list[dict[str, Any]] = field(default_factory=list)
    test_output: str = ""
    blocked_reason: str = ""
    blocked_from: str = ""
    po_answer: str = ""
    questions: list[str] = field(default_factory=list)
    checkpoint: dict[str, Any] | None = None
    pr_url: str = ""
    eval_score: float | None = None  # quality metric measured on this task's branch (eval_cmd)
    conflicts: int = 0            # merge conflicts with the base branch so far
    merge_conflict: bool = False  # the next dev step must merge the base branch and resolve
    files: list[str] = field(default_factory=list)  # files the spec says this task changes (overlap -> serial)
    tester_files: list[str] = field(default_factory=list)       # files the Tester wrote (its own tests)
    dev_changed_tests: list[str] = field(default_factory=list)  # Tester files the Developer edited since
    # Tech Lead triage: a technical blocker is handled by Claude as Tech Lead, never sent to the PO.
    tl_issue: str = ""            # what went wrong (non-empty = the next step is the Tech Lead's)
    tl_kind: str = ""             # questions | tests_failing | review_rejected | merge_conflict | guardrail ...
    tl_rounds: int = 0            # Tech Lead decisions on this task so far (capped by tech_lead_rounds)
    tl_guidance: str = ""         # latest Tech Lead instruction for the next developer run
    tl_notes: list[str] = field(default_factory=list)  # every Tech Lead answer/decision, shown to later steps
    retry_at: str = ""            # Tech Lead chose to wait: no step for this task before this time
    net_retries: int = 0          # short automatic retries after a GitHub network error
    attempt: int = 0              # fresh restarts from the base branch (branch office/T-xxx-r<n>)
    dropped: str = ""             # why the Tech Lead retired the task without merging it (split/drop)
    history: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=now_iso)

    def reroute(self, to: Stage, note: str = "") -> None:
        """Tech Lead decision: send the task to any working stage (or retire it to done)."""
        if to not in (Stage.TODO, Stage.SPEC, Stage.DEV, Stage.DONE):
            raise InvalidTransition(f"{self.id}: Tech Lead cannot reroute to {to.value}")
        self.history.append({"at": now_iso(), "from": self.stage.value, "to": to.value, "note": note})
        self.stage = to

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
    """One role (pm, lead, dev, tester). Rest fields are kept equal for all roles of a provider."""
    name: str
    provider: str = ""    # subscription CLI this role runs on (claude | codex)
    status: AgentStatus = AgentStatus.IDLE
    rest_until: str = ""  # ISO timestamp, empty when not resting
    backoff_level: int = 0
    reset_known: bool = False
    failures: int = 0  # consecutive non-limit failures
    last_error: str = ""
    rest_cause: str = ""  # quota | budget | env | upstream (server error) | failure; each lets the other CLI cover (failover)
    rest_detail: str = ""  # the CLI's own error line that caused the rest
    rest_log: str = ""     # log file of the call that caused the rest
    active: list[str] = field(default_factory=list)  # task/request ids this agent works on right now
    calls_day: str = ""     # local date (YYYY-MM-DD) that calls_today counts
    calls_today: int = 0
    calls_total: int = 0
    rests_total: int = 0
    limits_today: int = 0

    def count_call(self, day: str) -> None:
        if self.calls_day != day:
            self.calls_day, self.calls_today, self.limits_today = day, 0, 0
        self.calls_today += 1
        self.calls_total += 1

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Agent":
        d = dict(d)
        d["status"] = AgentStatus(d["status"])
        if d["status"] == AgentStatus.RESTING and not d.get("rest_cause"):
            error = str(d.get("last_error", "")).lower()
            d["rest_cause"] = "failure" if error in ("repeated failures", "probe failed") else "quota"
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
    design: str = ""              # breakdown's goal/approaches/choice, committed as a design spec
    tl_issue: str = ""            # technical problem the Tech Lead must decide on before planning goes on
    tl_kind: str = ""
    tl_rounds: int = 0
    tl_questions: list[str] = field(default_factory=list)
    tl_notes: list[str] = field(default_factory=list)   # Tech Lead answers, fed back into planning prompts
    decisions: list[str] = field(default_factory=list)  # request-level decisions for DECISIONS.md
    retry_at: str = ""
