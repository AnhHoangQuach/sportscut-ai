"""The Office: executes one step at a time and moves tasks through the state machine."""
from __future__ import annotations

import json
import re
import subprocess
import threading
from concurrent.futures import Executor, Future
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from string import Template
from typing import Callable

from . import github, specdocs
from . import worktree as wt
from .agents import AgentResult, ClaudeAgent, CliAgent, CodexAgent, extract_json, subscription_env
from .config import Config, load_config
from .limits import LimitHit, detect, rest_until
from .models import (MAX_CONFLICT_ROUNDS, MAX_REVIEW_ROUNDS, MAX_TEST_ATTEMPTS, AgentStatus, Request, Stage, Task,
                     now_iso)
from .scheduler import Step, next_step, plan_steps
from .store import Store

# After this many consecutive unexplained failures, an agent is treated as rate limited.
FAILURES_BEFORE_REST = 2

# Things that look like credentials in added lines (guardrail `block_secrets`).
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id
    re.compile(r"\bsk-(?:ant-|proj-)?[A-Za-z0-9_-]{20,}"),       # Anthropic / OpenAI style keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),              # GitHub tokens
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),               # Slack tokens
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),                   # Google API key
]

# A `BLOCKED:` answer that matches one of these is an environment problem the office repairs itself.
MISSING_DEP = re.compile(
    r"ModuleNotFoundError|No module named|ImportError|command not found|not found on PATH|is not installed|"
    r"not installed|missing (?:dependency|dependencies|package|module|tool)|Could not find a version|"
    r"No matching distribution|Cannot find module|ENOTFOUND|Temporary failure in name resolution|"
    r"network is (?:disabled|unreachable)|Permission denied.*site-packages", re.IGNORECASE)


# What a technical blocker is, in the words the office uses when it hands one to the Tech Lead.
TL_KINDS = {
    "questions": "the planner asked questions",
    "parse_error": "an agent answer could not be read",
    "dev_blocked": "the developer stopped with BLOCKED",
    "missing_dependency": "a dependency still fails to install after the automatic retries",
    "git_error": "a git operation failed",
    "merge_conflict": "the branch keeps conflicting with the base branch",
    "merge_failed": "merging the approved change failed",
    "tests_failing": "tests or the eval keep failing",
    "review_rejected": "the review is still not approved after the last round",
    "secret": "guardrail: the diff adds something that looks like a secret",
    "protected_paths": "guardrail: the diff changes protected paths",
    "diff_size": "guardrail: the diff is larger than max_diff_lines",
}
TL_ACTIONS = ("retry", "restart", "split", "wait", "drop")
REQUEST_PAUSE_MIN = 60  # request-level Tech Lead out of rounds: pause, then try again
BUSINESS_MARK = "business question for the PO"  # blocked_reason / note of a Tech-Lead-screened question
# blocked_reason of a task whose PR/merge failed because of the user's machine (gh login, repo
# permission, network): only the user can fix it, so it is reported, not guessed at by the Tech Lead.
ENV_MARK = "environment problem for the user"
NET_BACKOFF_MIN = (2, 5, 10, 15)  # short retries for a network error before it is reported
ENV_RECHECK_MIN = 5               # how often a GitHub preflight checks whether the user fixed it

# Reasons a pre-Tech-Lead office wrote when it blocked a task, mapped to the Tech Lead kind.
LEGACY_KINDS = [
    ("not parseable", "parse_error"), ("tests still failing", "tests_failing"),
    ("review not approved", "review_rejected"), ("conflict", "merge_conflict"),
    ("protected path", "protected_paths"), ("secret", "secret"), ("diff changes", "diff_size"),
    ("could not merge", "merge_failed"), ("PM needs answers", "questions"),
]


def legacy_kind(task: Task) -> str:
    reason = task.blocked_reason
    if task.questions:
        return "questions"
    for needle, kind in LEGACY_KINDS:
        if needle.lower() in reason.lower():
            return "git_error" if kind == "merge_failed" and task.blocked_from != "pr" else kind
    return "missing_dependency" if MISSING_DEP.search(reason) else "dev_blocked"


def _minutes(value: object) -> int:
    """Tech Lead `wait` length, clamped to 5 min .. 1 day (30 when missing or unreadable)."""
    try:
        m = int(float(str(value).strip().rstrip("m") or 30))
    except ValueError:
        m = 30
    return min(24 * 60, max(5, m or 30))


def prompt(name: str, **vars: object) -> str:
    text = resources.files("agent_office.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")
    return Template(text).safe_substitute({k: str(v) for k, v in vars.items()})


def _first(text: str, n: int = 240) -> str:
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return line[:n] or "xong"


def bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) or "- (none)"


class Office:
    def __init__(self, repo: Path, agents: dict[str, CliAgent] | None = None,
                 clock: Callable[[], datetime] | None = None, echo: Callable[[str], None] | None = None):
        self.store = Store(repo).load()
        self.repo = self.store.repo
        self.cfg: Config = load_config(self.store.dir)
        if agents is None and self.cfg.simulate:
            from .agents.sim import SimAgent
            sim_state = self.store.dir / "sim_state.json"
            agents = {n: SimAgent(n, self.cfg.sim_delay, sim_state) for n in ("claude", "codex")}
        self.agents = agents or {"claude": ClaudeAgent(self.cfg.claude), "codex": CodexAgent(self.cfg.codex)}
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.echo = echo or (lambda msg: print(msg, flush=True))
        self.is_runner = False
        # Parallel runner: one lock around all state changes; it is released only while an agent
        # CLI or the test command runs, so other steps can start meanwhile.
        self.lock = threading.RLock()
        self.inflight: dict[str, str | None] = {}  # target id -> agent running it
        self._triaged = False  # old PO-waiting blocks re-classified once per office start
        self.github_preflight = github.preflight  # replaceable in tests
        self._env_checked_at: datetime | None = None

    @contextmanager
    def _unlocked(self):
        held = 0
        while True:
            try:
                self.lock.release()
            except RuntimeError:
                break
            held += 1
        try:
            yield
        finally:
            for _ in range(held):
                self.lock.acquire()

    # ------------------------------------------------------------------ inbox
    def submit(self, cmd: dict) -> list[str]:
        """Queue a PO command. Applied now if no runner owns the state, else on its next step."""
        self.store.append_inbox(cmd)
        if self.is_runner or self.store.runner_pid() is None:
            if not self.is_runner:
                self.store.load()  # the runner may have just exited: start from disk
            return self.drain_inbox()
        return [f"queued for the running office: {cmd.get('cmd')}"]

    def drain_inbox(self) -> list[str]:
        results = []
        for c in self.store.take_inbox():
            kind = c.get("cmd")
            try:
                if kind == "request":
                    results.append(f"{self.add_request(str(c['text'])).id} added")
                elif kind == "retry" or (kind == "answer" and str(c.get("id", "")).startswith("R-")):
                    r = self.retry_request(str(c["id"]), str(c.get("text", "")))
                    results.append(f"{r.id} back to {r.status}")
                elif kind == "answer":
                    t = self.answer(str(c["id"]), str(c.get("text", "")))
                    results.append(f"{t.id} back to {t.stage.value}")
                elif kind == "triage":
                    results += self.triage() or ["nothing waits for the PO except business questions"]
                elif kind == "wake":
                    self.wake(str(c["agent"]))
                    results.append(f"{c['agent']} marked available")
                else:
                    results.append(f"unknown command {kind!r}")
            except (KeyError, ValueError) as e:
                results.append(f"{kind} failed: {e}")
                self.store.event("command_failed", cmd=kind, error=str(e))
        return results

    # ------------------------------------------------------------------ triage
    def _triage_once(self) -> None:
        if not self._triaged:
            self._triaged = True
            self.triage()

    def triage(self) -> list[str]:
        """Hand every block that waits for the PO but was never screened by the Tech Lead (e.g. state
        saved before the Tech Lead existed) back to the Tech Lead. Business questions it already
        screened stay with the PO. Returns one line per item moved."""
        out = []
        for t in sorted(self.store.tasks.values(), key=lambda t: t.id):
            if t.stage != Stage.BLOCKED or t.blocked_reason.startswith((BUSINESS_MARK, ENV_MARK)):
                continue
            kind, reason = legacy_kind(t), t.blocked_reason or "blocked (no reason recorded)"
            back = Stage(t.blocked_from) if t.blocked_from in {"spec", "dev", "test", "review", "pr"} else Stage.DEV
            t.blocked_reason = ""
            self._move(t, back, "re-triaged: Tech Lead, not the PO")
            t.tl_issue, t.tl_kind = reason[:6000], kind  # questions stay on the task for the Tech Lead
            self.store.event("triaged", task_id=t.id, issue=kind)
            self.store.event("techlead_needed", task_id=t.id, issue=kind, reason=reason[:500],
                             round=t.tl_rounds + 1, of=self.cfg.tech_lead_rounds)
            out.append(f"{t.id}: {kind} -> Tech Lead")
        for r in self.store.requests.values():
            if r.status != "blocked" or r.note.startswith(BUSINESS_MARK):
                continue
            note = r.note or "blocked (no reason recorded)"
            r.status = r.blocked_stage if r.blocked_stage in ("new", "planned") else "new"
            r.note = ""
            if note.startswith("still not done after"):
                out.append(f"{r.id}: goal-round cap -> closes with a report")  # the goal check closes it
            else:
                kind = "questions" if r.questions else "parse_error"
                r.tl_issue, r.tl_kind, r.tl_questions = note[:6000], kind, list(r.questions)
                self.store.event("techlead_needed", request_id=r.id, issue=kind, reason=note[:500],
                                 round=r.tl_rounds + 1, of=self.cfg.tech_lead_rounds)
                out.append(f"{r.id}: {kind} -> Tech Lead")
            r.questions = []
            self.store.event("triaged", request_id=r.id)
        if out:
            self.say("claude", "po", "Em nhận lại các việc đang chờ anh nhưng thuộc kỹ thuật: "
                     + "; ".join(out)[:900] + ". Chỉ câu hỏi nghiệp vụ mới chờ anh.", kind="report")
            self.store.save()
            for line in out:
                self.echo(f"triage: {line}")
        return out

    # ------------------------------------------------------------------ requests
    def add_request(self, text: str) -> Request:
        req = Request(id=self.store.next_request_id(), text=text.strip())
        self.store.requests[req.id] = req
        self.store.save()
        self.store.event("request_added", request_id=req.id, text=req.text[:500])
        first = next((ln.strip("# ").strip() for ln in req.text.splitlines() if ln.strip()), req.text)
        self.say("po", "claude", f"Yêu cầu mới {req.id}: {first[:300]}", kind="request")
        return req

    # ------------------------------------------------------------------ main step
    def step(self) -> Step | None:
        """Run the single highest-priority step to completion (sequential mode)."""
        self.recheck_environment()
        with self.lock:
            self._triage_once()
            self.drain_inbox()
            self.sync_merged()
            plan = next_step(self.store, self.clock(), self.cfg.merge_mode == "auto")
            if plan.step is None:
                return None
            self._execute(plan.step)
            return plan.step

    # ------------------------------------------------------------------ parallel
    def free_slots(self) -> dict[str, int]:
        used: dict[str, int] = {}
        for agent in self.inflight.values():
            if agent:
                used[agent] = used.get(agent, 0) + 1
        return {n: self.cfg.parallel.get(n, 1) - used.get(n, 0) for n in self.agents}

    def dispatch(self, pool: Executor) -> list[Future]:
        """Start every step that fits in the free agent sessions. Returns the new futures."""
        self.recheck_environment()
        with self.lock:
            self._triage_once()
            self.drain_inbox()
            self.sync_merged()
            plan = plan_steps(self.store, self.clock(), self.cfg.merge_mode == "auto",
                              busy=set(self.inflight), slots=self.free_slots())
            started = []
            for s in plan.steps:
                self.inflight[s.target] = s.agent
                started.append(pool.submit(self._run_inflight, s))
            if started:
                self.store.event("dispatch", steps=[f"{s.kind}:{s.target}" for s in plan.steps],
                                 running=sorted(self.inflight))
            return started

    def _run_inflight(self, s: Step) -> Step:
        try:
            with self.lock:
                self._execute(s)
        except Exception as e:  # noqa: BLE001 - one broken step must not stop the office
            with self.lock:
                self.store.event("step_crashed", kind=s.kind, target=s.target, error=repr(e)[:500])
                self.echo(f"  step {s.kind} {s.target} crashed: {e!r}")
                self.store.save()
        finally:
            with self.lock:
                self.inflight.pop(s.target, None)
        return s

    def _execute(self, s: Step) -> None:
        preferred = None
        if s.kind in ("breakdown", "goal", "techlead"):
            preferred = "claude"
        elif s.kind == "task" and s.target in self.store.tasks:
            stage = self.store.tasks[s.target].stage
            preferred = "claude" if stage in (Stage.SPEC, Stage.REVIEW) else (
                "codex" if stage in (Stage.DEV, Stage.TEST) else None)
        if preferred and s.agent and s.agent != preferred:
            self.store.event("agent_failover", task_id=s.target, preferred=preferred, agent=s.agent,
                             step_kind=s.kind, reason=self.store.agents[preferred].rest_cause)
            self.echo(f"  [{s.agent}] covering {preferred} for {s.kind} ({s.target})")
        if s.kind == "wake":
            self._wake(s.target)
        elif s.kind == "breakdown":
            self._breakdown(self.store.requests[s.target], s.agent or "claude")
        elif s.kind == "goal":
            self._goal_check(self.store.requests[s.target], s.agent or "claude")
        elif s.kind == "techlead":
            if s.target in self.store.requests:
                self._tech_lead_request(self.store.requests[s.target], s.agent or "claude")
            else:
                self._tech_lead(self.store.tasks[s.target], s.agent or "claude")
        else:
            task = self.store.tasks[s.target]
            handler = {
                Stage.TODO: self._todo, Stage.SPEC: self._spec, Stage.DEV: self._dev,
                Stage.TEST: self._test, Stage.REVIEW: self._review, Stage.PR: self._pr,
            }[task.stage]
            handler(task) if s.agent is None else handler(task, s.agent)
        self.store.save()

    # ------------------------------------------------------------------ agent calls
    def _call(self, agent_name: str, text: str, cwd: Path, task_id: str, label: str,
              task: Task | None = None) -> AgentResult | None:
        """Run an agent. Returns None if it hit a limit/failed (agent is then resting)."""
        agent = self.store.agents[agent_name]
        if agent.status == AgentStatus.RESTING:  # another session of this agent just hit a limit
            return None
        now = self.clock()
        day = now.astimezone().date().isoformat()
        cap = self.cfg.max_calls_per_day.get(agent_name, 0)
        if cap and agent.calls_day == day and agent.calls_today >= cap:
            midnight = (now.astimezone() + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            self.store.event("budget_reached", agent=agent_name, calls=agent.calls_today, cap=cap)
            self._rest(agent_name, LimitHit(agent_name, f"daily budget of {cap} calls used", midnight), None,
                       label, None, budget=True)
            return None
        agent.count_call(day)
        agent.active.append(task_id)
        agent.status = AgentStatus.WORKING
        self.store.save()
        self.store.event("agent_working", agent=agent_name, task_id=task_id, label=label,
                         sessions=len(agent.active))
        self.echo(f"  [{agent_name}] {label} ({task_id})...")
        log_path = self.store.log_path(task_id, f"{label}-{agent_name}")
        try:
            with self._unlocked():
                role = "write" if label == "dev" or label == "test" else "read"
                res = self.agents[agent_name].run(text, cwd, log_path, role=role)
        finally:
            if task_id in agent.active:
                agent.active.remove(task_id)
            if agent.status != AgentStatus.RESTING:
                agent.status = AgentStatus.WORKING if agent.active else AgentStatus.IDLE

        if res.limit is not None:
            res.limit = detect(agent_name, res.stdout, res.stderr, res.exit_code, self.clock()) or res.limit
            self._rest(agent_name, res.limit, task, label, res)
            return None
        if not res.ok:
            agent.failures += 1
            agent.last_error = (res.stderr or res.stdout)[-500:] or f"exit {res.exit_code}"
            self.store.event("agent_failed", agent=agent_name, task_id=task_id, exit_code=res.exit_code,
                             timed_out=res.timed_out, log=res.log_path)
            self.echo(f"  [{agent_name}] failed (exit {res.exit_code}); see {res.log_path}")
            if agent.failures >= FAILURES_BEFORE_REST:
                self._rest(agent_name, LimitHit(agent_name, "repeated failures", None), task, label, res,
                           cause="failure")
            elif task is not None:
                self._checkpoint(task, label, f"{agent_name} failed (exit {res.exit_code})", res)
            return None
        agent.failures = 0
        agent.last_error = ""
        self.store.event("agent_done", agent=agent_name, task_id=task_id, label=label, log=res.log_path)
        return res

    def _rest(self, agent_name: str, hit: LimitHit, task: Task | None, label: str,
              res: AgentResult | None, budget: bool = False, cause: str = "quota") -> None:
        a = self.store.agents[agent_name]
        if a.status == AgentStatus.RESTING and a.rest_until and datetime.fromisoformat(a.rest_until) > self.clock():
            # A parallel session of the same agent already hit the limit: just save this task's progress.
            if task is not None:
                self._checkpoint(task, label, f"{agent_name} usage limit: {hit.matched}", res)
            return
        until, known = rest_until(hit.reset_at, a.backoff_level, self.cfg.backoff_minutes, self.clock())
        if budget:
            until, known = hit.reset_at, True
        a.rests_total += 1
        if not budget:
            a.limits_today += 1
        if not known:
            a.backoff_level += 1
        a.status = AgentStatus.RESTING
        a.rest_until = until.isoformat(timespec="seconds")
        a.reset_known = known
        a.failures = 0
        a.last_error = hit.matched
        a.rest_cause = "budget" if budget else cause
        if budget:
            self.say(agent_name, "all", f"Mình dùng hết ngân sách hôm nay ({hit.matched}), mai làm tiếp.",
                     kind="rest")
        else:
            self.say(agent_name, "all", f"Mình hết quota rồi, nghỉ tới {until.astimezone().strftime('%H:%M')}. "
                     "Việc đang dở đã lưu checkpoint.", task.id if task else "", kind="rest")
        self.store.event("agent_resting", agent=agent_name, until=a.rest_until, reset_known=known,
                         matched=hit.matched)
        self.echo(f"  [{agent_name}] usage limit ({hit.matched!r}); resting until {a.rest_until}")
        if task is not None:
            self._checkpoint(task, label, f"{agent_name} usage limit: {hit.matched}", res)

    def _wake(self, agent_name: str) -> None:
        a = self.store.agents[agent_name]
        if not a.reset_known:
            # Rest length was a guess: spend one tiny prompt to check before real work.
            self.echo(f"  [{agent_name}] probing after rest...")
            log_path = self.store.log_path("_probe", agent_name)
            with self._unlocked():
                res = self.agents[agent_name].run(prompt("probe"), self.repo, log_path, probe=True)
            if res.limit is not None or res.exit_code != 0:
                self._rest(agent_name, res.limit or LimitHit(agent_name, "probe failed", None), None,
                           "probe", res, cause="quota" if res.limit is not None else "failure")
                return
        a.status = AgentStatus.IDLE
        a.rest_until = ""
        a.rest_cause = ""
        a.reset_known = False
        a.backoff_level = 0
        self.store.event("agent_awake", agent=agent_name)
        self.say(agent_name, "all", "Có quota lại rồi, làm tiếp nhé.", kind="awake")
        self.echo(f"  [{agent_name}] back to work")

    # ------------------------------------------------------------------ checkpoint
    def _checkpoint(self, task: Task, label: str, reason: str, res: AgentResult | None) -> None:
        cp = {"stage": task.stage.value, "label": label, "reason": reason, "at": now_iso(),
              "session_id": res.session_id if res else "", "log": res.log_path if res else "",
              "log_tail": res.tail(1500) if res else ""}
        task.checkpoint = cp
        if task.worktree and Path(task.worktree).exists():
            w = Path(task.worktree)
            (wt.notes_dir(w) / "CHECKPOINT.md").write_text(
                f"# Checkpoint for {task.id}\n\n- stage: {cp['stage']}\n- step: {label}\n"
                f"- reason: {reason}\n- at: {cp['at']}\n\n## Last output\n\n```\n{cp['log_tail']}\n```\n",
                encoding="utf-8")
            wt.abort_merge(w)  # never commit conflict markers; the merge is redone on resume
            if wt.commit_all(w, f"wip(office): checkpoint {task.id} {label}"):
                cp["wip_commit"] = wt.git(w, "rev-parse", "HEAD")
        self.store.event("task_checkpoint", task_id=task.id, **{k: v for k, v in cp.items() if k != "log_tail"})

    def _clear_checkpoint(self, task: Task) -> None:
        task.checkpoint = None
        if task.worktree:
            (Path(task.worktree) / wt.NOTES_DIR / "CHECKPOINT.md").unlink(missing_ok=True)

    def say(self, frm: str, to: str, text: str, task_id: str = "", kind: str = "") -> None:
        """A line in the office conversation (shown as chat + speech bubbles in the dashboard)."""
        self.store.event("message", frm=frm, to=to, text=text[:1200], task_id=task_id, topic=kind)

    def _move(self, task: Task, to: Stage, note: str = "") -> None:
        frm = task.stage
        task.move(to, note)
        self.store.event("stage_changed", task_id=task.id, frm=frm.value, to=to.value, note=note)
        self.echo(f"{task.id}: {frm.value} -> {to.value}" + (f" ({note})" if note else ""))

    def _block(self, task: Task, reason: str) -> None:
        frm = task.stage
        task.block(reason)
        self.store.event("stage_changed", task_id=task.id, frm=frm.value, to="blocked", note=reason)
        self.echo(f"{task.id}: {frm.value} -> blocked: {reason}")

    # ------------------------------------------------------------------ stages
    def _request_text(self, req: Request) -> str:
        text = req.text
        if req.po_answers:
            text += "\n\n## Product Owner answers to earlier questions\n\n" + "\n\n".join(req.po_answers)
        if req.tl_notes:
            text += ("\n\n## Tech Lead decisions (technical questions are decided by the team, not the PO)\n\n"
                     + "\n\n".join(req.tl_notes))
        return text

    def _block_request(self, req: Request, note: str, questions: list[str] | None = None) -> None:
        req.blocked_stage = req.status if req.status in ("new", "planned") else "new"
        req.status, req.note, req.questions = "blocked", note, questions or []
        self.store.event("request_blocked", request_id=req.id, note=note, questions=req.questions)
        self.echo(f"{req.id}: blocked ({note})")

    def _add_tasks(self, req: Request, items: list[dict]) -> list[str]:
        key_to_id: dict[str, str] = {}
        created = []
        room = max(0, self.cfg.max_tasks_per_request - len(req.task_ids))
        if len(items) > room:
            self.store.event("guardrail", request_id=req.id, rule="max_tasks_per_request",
                             asked=len(items), kept=room)
            self.echo(f"{req.id}: keeping {room} of {len(items)} tasks (max_tasks_per_request)")
            items = items[:room]
        for i, it in enumerate(items, 1):
            tid = self.store.next_task_id()
            key_to_id[str(it.get("key", i))] = tid
            deps = [key_to_id[str(k)] for k in it.get("depends_on", []) if str(k) in key_to_id]
            t = Task(id=tid, title=str(it.get("title", f"Task {i}"))[:120], brief=str(it.get("brief", "")),
                     request_id=req.id, depends_on=deps)
            self.store.tasks[tid] = t
            req.task_ids.append(tid)
            created.append(tid)
            self.store.event("task_created", task_id=tid, title=t.title, depends_on=deps, request_id=req.id)
            self.echo(f"{tid}: created '{t.title}'" + (f" (after {', '.join(deps)})" if deps else ""))
        return created

    def _breakdown(self, req: Request, agent_name: str = "claude") -> None:
        res = self._call(agent_name, prompt("pm_breakdown", request=self._request_text(req), request_id=req.id,
                                         specs=specdocs.context(self.repo)),
                         self.repo, req.id, "breakdown")
        if res is None:
            return
        try:
            d = extract_json(res.text)
            questions = [str(q) for q in d.get("questions", [])]
            items = d.get("tasks", [])
            assert questions or (isinstance(items, list) and items)
        except Exception as e:  # noqa: BLE001
            self._escalate_request(req, "parse_error", f"breakdown output not parseable: {e}\n{res.text[-1500:]}")
            return
        if questions:
            self._escalate_request(req, "questions", "PM has questions before planning", questions)
            return
        req.tl_rounds = 0
        req.design = str(d.get("design", "")).strip() or req.design
        created = self._add_tasks(req, items)
        req.status = "planned"
        self.say("claude", "po", f"Em tách {req.id} thành {len(created)} task: "
                 + "; ".join(f"{t} {self.store.tasks[t].title}" for t in created), kind="plan")

    def _goal_check(self, req: Request, agent_name: str = "claude") -> None:
        done = [self.store.tasks[t] for t in req.task_ids if t in self.store.tasks]
        listing = "\n".join(f"- {t.id} {t.title}: {t.brief}"
                            + (f" (DROPPED, not merged: {t.dropped[:300]})" if t.dropped else "")
                            for t in done) or "- (none)"
        rnd = req.goal_rounds + 1
        res = self._call(agent_name, prompt("pm_goal", request=self._request_text(req), request_id=req.id,
                                          done_tasks=listing, round=rnd, max_rounds=self.cfg.max_goal_rounds,
                                          specs=specdocs.context(self.repo)),
                         self.repo, req.id, f"goal{rnd}")
        if res is None:
            return
        try:
            d = extract_json(res.text)
        except Exception as e:  # noqa: BLE001
            self._escalate_request(req, "parse_error", f"goal check output not parseable: {e}\n{res.text[-1500:]}")
            return
        questions = [str(q) for q in d.get("questions", [])]
        if questions:
            self._escalate_request(req, "questions", "PM has questions before finishing the request", questions)
            return
        req.tl_rounds = 0
        req.goal_rounds = rnd
        req.summary = str(d.get("summary", ""))[:4000]
        items = d.get("tasks") or []
        if d.get("done") or not items:
            req.status = "done"
            self.store.event("request_done", request_id=req.id, summary=req.summary, rounds=rnd)
            self.say("claude", "po", f"{req.id} đã xong. {req.summary[:600]}", kind="done")
            self.echo(f"{req.id}: delivered. {req.summary[:200]}")
            return
        if rnd > self.cfg.max_goal_rounds:
            # A hard cap, not a question: deliver what is merged and report what is left.
            req.status = "done"
            req.note = f"stopped after {self.cfg.max_goal_rounds} follow-up rounds; still missing: {req.summary[:300]}"
            req.decisions.append(f"Tech Lead: closed after {self.cfg.max_goal_rounds} follow-up rounds; "
                                 f"left for a new request: {req.summary[:300]}")
            self.store.event("request_done", request_id=req.id, summary=req.summary, rounds=rnd, partial=True)
            self.say("claude", "po", f"Báo cáo {req.id}: đã làm {self.cfg.max_goal_rounds} vòng bổ sung, phần đã "
                     f"merge dùng được. Còn thiếu: {req.summary[:500]}. Gửi yêu cầu mới nếu anh muốn làm tiếp.",
                     kind="report")
            self.echo(f"{req.id}: closed after {self.cfg.max_goal_rounds} follow-up rounds (partial)")
            return
        created = self._add_tasks(req, items)
        self.store.event("request_followup", request_id=req.id, round=rnd, tasks=created, summary=req.summary)
        self.say("claude", "po", f"Kiểm tra {req.id}: còn thiếu ({req.summary[:300]}). Em thêm "
                 + ", ".join(created) + ".", kind="plan")

    def _todo(self, task: Task) -> None:
        self._move(task, Stage.SPEC, "dependencies done")

    def _spec(self, task: Task, agent_name: str = "claude") -> None:
        req = self.store.requests.get(task.request_id)
        po = f"## Product Owner answer to an earlier question\n\n{task.po_answer}" if task.po_answer else ""
        if task.tl_notes:
            po += "\n\n## Tech Lead decisions (follow them; do not ask these again)\n\n" + "\n\n".join(task.tl_notes)
        res = self._call(agent_name, prompt("pm_spec", request=self._request_text(req) if req else "", task_id=task.id,
                                          title=task.title, brief=task.brief, po_answer=po,
                                          specs=specdocs.context(self.repo)),
                         self.repo, task.id, "spec", task)
        if res is None:
            return
        try:
            d = extract_json(res.text)
            questions = [str(q) for q in d.get("questions", [])]
            if questions:
                self._clear_checkpoint(task)
                self._escalate(task, "questions", "PM has questions: " + " | ".join(questions)[:800], questions)
                return
            task.spec = str(d["spec"])
            task.acceptance_criteria = [str(x) for x in d.get("acceptance_criteria", [])]
            task.test_plan = [str(x) for x in d.get("test_plan", [])]
            task.out_of_scope = [str(x) for x in d.get("out_of_scope", [])]
            kept = [x for x in task.decisions if x.startswith("Tech Lead")]  # decided before this spec
            task.decisions = list(dict.fromkeys([str(x) for x in d.get("decisions", [])] + kept))
            task.related_specs = [str(x) for x in d.get("related_specs", [])]
            task.files = [str(x) for x in d.get("files", [])] or task.files
        except Exception as e:  # noqa: BLE001
            self._escalate(task, "parse_error", f"spec output not parseable: {e}\n{res.text[-1500:]}")
            return
        self._clear_checkpoint(task)
        self._move(task, Stage.DEV, f"{len(task.acceptance_criteria)} acceptance criteria")
        acs = "; ".join(task.acceptance_criteria[:4])
        self.say("claude", "codex", f"Giao {task.id} '{task.title}'. Spec ở .office/TASK.md. "
                 f"Cần đạt: {acs}", task.id, kind="assign")

    def _ensure_worktree(self, task: Task) -> Path:
        path, branch, base = wt.ensure_worktree(self.repo, self.cfg.worktrees_path(self.repo), task.id,
                                                self.cfg.base_branch, task.attempt)
        if not task.worktree:
            task.worktree, task.branch, task.base_ref = str(path), branch, base
            self.store.event("worktree_ready", task_id=task.id, path=str(path), branch=branch)
            self._setup_env(task, path, "new worktree")
        self._write_task_md(task, path)
        specdocs.write_task_docs(path, task, self.store.requests.get(task.request_id))
        return path

    def _setup_env(self, task: Task, path: Path, why: str) -> tuple[bool, str]:
        """Run setup_cmd in the worktree as the orchestrator (network, no sandbox)."""
        if not self.cfg.setup_cmd:
            return True, "(no setup_cmd configured)"
        self.echo(f"  [office] setup env for {task.id} ({why})...")
        with self._unlocked():
            try:
                p = subprocess.run(self.cfg.setup_cmd, shell=True, cwd=path, capture_output=True, text=True,
                                   timeout=1800, env=subscription_env(path))
                ok, out = p.returncode == 0, f"(exit {p.returncode})\n{p.stdout[-2000:]}\n{p.stderr[-2000:]}"
            except subprocess.TimeoutExpired:
                ok, out = False, "(timed out after 1800s)"
        self.store.event("env_setup", task_id=task.id, why=why, ok=ok)
        return ok, f"$ {self.cfg.setup_cmd}\n{out}"

    def _write_task_md(self, task: Task, path: Path) -> None:
        parts = [f"# {task.id}: {task.title}\n\n{task.brief}\n", f"## Spec\n\n{task.spec}\n",
                 f"## Acceptance criteria\n\n{bullets(task.acceptance_criteria)}\n",
                 f"## Test plan\n\n{bullets(task.test_plan)}\n",
                 f"## Out of scope\n\n{bullets(task.out_of_scope)}\n",
                 f"## Persistent spec (committed with your change)\n\n"
                 f"- design: `{specdocs.design_path(task)}`\n- plan: `{specdocs.plan_path(task)}`\n"
                 f"- decisions: `{specdocs.SPECS_DIR}/DECISIONS.md`, index: `{specdocs.SPECS_DIR}/INDEX.md`\n"
                 f"- existing specs you must keep true (update them if behaviour changes):\n"
                 f"{bullets(task.related_specs)}\n"]
        if task.po_answer:
            parts.append(f"## Product Owner answer\n\n{task.po_answer}\n")
        if task.tl_notes:
            parts.append("## Tech Lead decisions (follow them)\n\n" + "\n".join(f"- {n}" for n in task.tl_notes) + "\n")
        if task.review_comments:
            parts.append(f"## Review feedback to address (round {task.review_round})\n\n" + "\n".join(
                f"- [{c.get('severity', '')}] {c.get('file', '')}:{c.get('line', '')} {c.get('text', '')}"
                for c in task.review_comments) + "\n")
        if task.test_output:
            parts.append(f"## Last failing test output\n\n```\n{task.test_output[-4000:]}\n```\n")
        (wt.notes_dir(path) / "TASK.md").write_text("\n".join(parts), encoding="utf-8")

    def _dev(self, task: Task, agent_name: str = "codex") -> None:
        path = self._ensure_worktree(task)
        conflict_files: list[str] = []
        if task.merge_conflict:
            try:
                conflict_files = wt.start_merge(path, self.cfg.base_branch)
            except wt.GitError as e:
                self._escalate(task, "git_error", f"could not merge {self.cfg.base_branch}: {e}")
                return
            if not conflict_files:  # the base moved again and now merges cleanly
                task.merge_conflict = False
                self._move(task, Stage.TEST, f"{self.cfg.base_branch} merged cleanly")
                return
        if conflict_files:
            mode = (f"MERGE CONFLICT: `git merge {self.cfg.base_branch}` is in progress in this worktree and "
                    f"these files conflict: {', '.join(conflict_files[:20])}. Resolve every conflict so that "
                    f"both this task and the work already on {self.cfg.base_branch} keep working, remove all "
                    "conflict markers, `git add` the files, run the tests. Do not commit or abort the merge.")
        elif task.tl_guidance:
            mode = ("TECH LEAD DECISION: the Tech Lead looked at why this task was stuck and decided how to "
                    f"continue. Follow it exactly (it is also under 'Tech Lead decisions' in TASK.md).\n\n"
                    f"{task.tl_guidance}")
        elif task.env_note:
            mode = ("ENVIRONMENT: last time you stopped on a missing dependency. The office re-ran the setup "
                    f"command; result below. Install whatever is still missing yourself (see Rules), then "
                    f"continue the task.\n\n{task.env_note}")
        elif task.checkpoint:
            mode = ("RESUMING: a previous run was interrupted. Read `.office/CHECKPOINT.md` and "
                    "`git log` to see what is already done, then continue; do not redo finished work.")
        elif task.review_comments:
            mode = "This is a revision: address every blocker/major item under 'Review feedback' in TASK.md."
        elif task.test_output:
            mode = ("Tests or the eval failed last time: see 'Last failing test output' in TASK.md. Debug it "
                    "systematically: reproduce, find the root cause, add a test that captures it, then fix.")
        else:
            mode = "This is a fresh start on the task."
        res = self._call(agent_name, prompt("dev", task_id=task.id, mode=mode), path, task.id, "dev", task)
        if res is None:
            return
        if res.text.lstrip().startswith("BLOCKED:"):
            wt.commit_all(path, f"wip(office): {task.id} blocked")
            reason = res.text.strip()
            if MISSING_DEP.search(reason) and task.env_fixes < self.cfg.dep_retries:
                task.env_fixes += 1
                ok, out = self._setup_env(task, path, "missing dependency")
                task.env_note = f"You reported:\n{reason[:1500]}\n\nSetup {'ok' if ok else 'FAILED'}:\n{out[-2500:]}"
                self.store.event("env_retry", task_id=task.id, attempt=task.env_fixes, of=self.cfg.dep_retries)
                self.say("codex", "all", f"{task.id} thiếu dependency, tự cài lại môi trường và thử lại "
                         f"({task.env_fixes}/{self.cfg.dep_retries}).", task.id, kind="env_retry")
                return  # still in DEV: the next step runs the developer again
            self.say("codex", "claude", f"{task.id} bị chặn: {res.text.strip()[8:400]}", task.id, kind="blocked")
            kind = "missing_dependency" if MISSING_DEP.search(reason) else "dev_blocked"
            self._escalate(task, kind, reason[:3000])
            return
        if conflict_files:
            left = wt.conflict_markers(path)
            if left:
                wt.abort_merge(path)
                self._escalate(task, "merge_conflict", f"conflict markers left in {', '.join(left[:5])}")
                return
            wt.finish_merge(path, f"merge {self.cfg.base_branch} into {task.branch} "
                                  f"(conflicts resolved by {agent_name})")
            task.merge_conflict = False
            self.store.event("conflict_resolved", task_id=task.id, files=conflict_files[:50])
        else:
            wt.commit_all(path, f"feat({task.id}): {task.title}")
        task.env_note = ""
        task.tl_guidance = ""
        self._clear_checkpoint(task)
        rule, problem = self._guardrail_problem(task, path)
        if problem:
            # The guardrail stays a hard stop for the change; the Tech Lead decides how to fix it.
            self._escalate(task, rule, problem)
            return
        self._move(task, Stage.TEST)
        self.say("codex", "all", f"{task.id} code xong: {_first(res.text)}. Giờ mình chạy test.", task.id,
                 kind="dev_done")

    def _guardrail_problem(self, task: Task, path: Path) -> tuple[str, str]:
        """(rule, problem) for the first guardrail the branch breaks, ("", "") if none."""
        touched = self._protected_changes(task, path)
        if touched:
            self.store.event("guardrail", task_id=task.id, rule="protected_paths", files=touched[:20])
            return "protected_paths", (f"changed protected paths: {', '.join(touched[:5])}; these must not be "
                                       "changed by this team")
        if self.cfg.block_secrets:
            for f, line in wt.added_lines(path, task.base_ref):
                if any(p.search(line) for p in SECRET_PATTERNS):
                    self.store.event("guardrail", task_id=task.id, rule="secret", file=f)
                    return "secret", f"diff adds something that looks like a secret in {f}; remove it before review"
        if self.cfg.max_diff_lines:
            n = wt.changed_line_count(path, task.base_ref)
            if n > self.cfg.max_diff_lines:
                self.store.event("guardrail", task_id=task.id, rule="diff_size", lines=n)
                return "diff_size", (f"diff changes {n} lines (limit {self.cfg.max_diff_lines}); split the task "
                                     "into smaller ones")
        return "", ""

    def _protected_changes(self, task: Task, path: Path) -> list[str]:
        if not self.cfg.protected_paths:
            return []
        changed = wt.git(path, "diff", "--name-only", f"{task.base_ref}...HEAD").splitlines()
        return [f for f in changed if any(f == p.rstrip("/") or f.startswith(p.rstrip("/") + "/")
                                          for p in self.cfg.protected_paths)]

    def _run_test_cmd(self, path: Path) -> tuple[bool, str]:
        if not self.cfg.test_cmd:
            return True, "(no test_cmd configured)"
        p = subprocess.run(self.cfg.test_cmd, shell=True, cwd=path, capture_output=True, text=True,
                           timeout=1800, env=subscription_env(path))
        return p.returncode == 0, f"$ {self.cfg.test_cmd}\n(exit {p.returncode})\n{p.stdout[-6000:]}\n{p.stderr[-3000:]}"

    def _run_eval(self, path: Path) -> tuple[float | None, str]:
        """Run eval_cmd and read the metric from the last JSON object it prints."""
        try:
            p = subprocess.run(self.cfg.eval_cmd, shell=True, cwd=path, capture_output=True, text=True,
                               timeout=3600, env=subscription_env(path))
        except subprocess.TimeoutExpired:
            return None, f"$ {self.cfg.eval_cmd}\n(timed out)"
        out = f"$ {self.cfg.eval_cmd}\n(exit {p.returncode})\n{p.stdout[-3000:]}\n{p.stderr[-1500:]}"
        if p.returncode != 0:
            return None, out
        for line in reversed(p.stdout.strip().splitlines()):
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(d, dict) and isinstance(d.get(self.cfg.eval_metric), (int, float)):
                return float(d[self.cfg.eval_metric]), out
        try:
            d = extract_json(p.stdout)
            return float(d[self.cfg.eval_metric]), out
        except Exception:  # noqa: BLE001
            return None, out + f"\n(no JSON with \"{self.cfg.eval_metric}\" in the output)"

    def _eval_problem(self, task: Task, path: Path) -> str:
        """Measure the task's branch; return why it is worse than the base branch ('' if fine)."""
        if not self.cfg.eval_cmd:
            return ""
        with self._unlocked():
            score, out = self._run_eval(path)
        m = self.cfg.eval_metric
        if score is None:
            return f"eval command failed or printed no {m}:\n{out[-3000:]}"
        task.eval_score = score
        base = self.store.meta.get("eval_baseline")
        self.store.event("eval", task_id=task.id, metric=m, score=score, baseline=base)
        if base is None:
            return ""
        drop = (base - score) if self.cfg.eval_higher_is_better else (score - base)
        if drop > self.cfg.eval_max_drop:
            return (f"eval {m} got worse: {score:.4f} vs {base:.4f} on {self.cfg.base_branch} "
                    f"(allowed drop {self.cfg.eval_max_drop}). Find what lowered it and fix it.\n{out[-2500:]}")
        return ""

    def _test(self, task: Task, agent_name: str = "codex") -> None:
        path = self._ensure_worktree(task)
        extra = f"The orchestrator will also run: `{self.cfg.test_cmd}`" if self.cfg.test_cmd else ""
        res = self._call(agent_name, prompt("test", task_id=task.id, extra=extra), path, task.id, "test", task)
        if res is None:
            return
        wt.commit_all(path, f"test({task.id}): tests for {task.title}")
        agent_pass = "RESULT: FAIL" not in res.text
        with self._unlocked():
            cmd_pass, cmd_out = self._run_test_cmd(path)
        self._clear_checkpoint(task)
        if agent_pass and cmd_pass:
            problem = self._eval_problem(task, path)
            if problem:
                cmd_pass, cmd_out = False, problem
        if agent_pass and cmd_pass:
            task.test_output = ""
            report = path / wt.NOTES_DIR / "TEST_REPORT.md"
            agent_summary = report.read_text(encoding="utf-8")[-3000:] if report.exists() else res.text[-2000:]
            score = (f"\n\nEval {self.cfg.eval_metric}: {task.eval_score:.4f} (base branch: "
                     f"{self.store.meta.get('eval_baseline', 'none yet')})" if task.eval_score is not None else "")
            (wt.notes_dir(path) / "TEST_SUMMARY.md").write_text(f"{agent_summary}\n\n{cmd_out[-2000:]}{score}",
                                                                encoding="utf-8")
            self._move(task, Stage.REVIEW, "tests pass")
            self.say("codex", "claude", f"{task.id} test pass, nhờ Claude review.", task.id, kind="handoff")
            return
        task.test_attempts += 1
        task.test_output = (cmd_out if not cmd_pass else res.text)[-6000:]
        if task.test_attempts >= MAX_TEST_ATTEMPTS:
            self._escalate(task, "tests_failing", f"tests still failing after {task.test_attempts} attempts:\n"
                                                  f"{task.test_output[-3000:]}")
        else:
            self._move(task, Stage.DEV, f"tests failed (attempt {task.test_attempts}/{MAX_TEST_ATTEMPTS})")
            self.say("codex", "all", f"{task.id} test fail ({task.test_attempts}/{MAX_TEST_ATTEMPTS}), "
                     "mình sửa lại.", task.id, kind="test_fail")

    def _review(self, task: Task, agent_name: str = "claude") -> None:
        path = self._ensure_worktree(task)
        summary_file = path / wt.NOTES_DIR / "TEST_SUMMARY.md"
        test_summary = summary_file.read_text(encoding="utf-8") if summary_file.exists() else "(not recorded)"
        notes_file = path / wt.NOTES_DIR / "DEV_NOTES.md"
        dev_notes = notes_file.read_text(encoding="utf-8")[-6000:] if notes_file.exists() else "(none written)"
        rnd = task.review_round + 1
        res = self._call(agent_name, prompt(
            "review", task_id=task.id, round=rnd, max_rounds=MAX_REVIEW_ROUNDS, spec=task.spec,
            acceptance_criteria=bullets(task.acceptance_criteria), test_summary=test_summary, dev_notes=dev_notes,
            specs=specdocs.context(path), spec_files=bullets([specdocs.design_path(task), specdocs.plan_path(task)]),
            related_specs=bullets(task.related_specs),
            diff=wt.diff(path, task.base_ref) or "(empty diff)"), path, task.id, f"review{rnd}", task)
        if res is None:
            return
        try:
            d = extract_json(res.text)
            verdict = str(d.get("verdict", "")).lower()
            comments = [c for c in d.get("comments", []) if isinstance(c, dict)]
        except Exception as e:  # noqa: BLE001
            self._escalate(task, "parse_error", f"review output not parseable: {e}\n{res.text[-1500:]}")
            return
        task.review_round = rnd
        self._clear_checkpoint(task)
        self.store.event("review_done", task_id=task.id, round=rnd, verdict=verdict,
                         summary=str(d.get("summary", ""))[:1000], comments=len(comments))
        (wt.notes_dir(path) / f"REVIEW-{rnd}.md").write_text(json.dumps(d, indent=2, ensure_ascii=False))
        if verdict == "approve":
            task.review_comments = [c for c in comments if c.get("severity") == "nit"]
            task.history.append({"at": now_iso(), "review_summary": str(d.get("summary", ""))[:2000]})
            self._move(task, Stage.PR, f"approved in round {rnd}")
            self.say("claude", "codex", f"Approve {task.id}. {str(d.get('summary', ''))[:400]}", task.id,
                     kind="approve")
            return
        task.review_comments = comments
        if rnd >= MAX_REVIEW_ROUNDS:
            self._escalate(task, "review_rejected", f"review not approved after {rnd} rounds: "
                                                    f"{str(d.get('summary', ''))[:1500]}")
        else:
            self._move(task, Stage.DEV, f"changes requested in round {rnd} ({len(comments)} comments)")
            asks = "; ".join(f"{c.get('file', '')}: {c.get('text', '')}" for c in comments[:4])
            self.say("claude", "codex", f"{task.id} cần sửa (vòng {rnd}/{MAX_REVIEW_ROUNDS}): {asks}", task.id,
                     kind="changes")

    def _pr_body(self, task: Task) -> str:
        review = next((h["review_summary"] for h in reversed(task.history) if "review_summary" in h), "")
        nits = "\n".join(f"- {c.get('file', '')}: {c.get('text', '')}" for c in task.review_comments)
        return (f"## {task.id}: {task.title}\n\n{task.brief}\n\n### Acceptance criteria\n\n"
                + "\n".join(f"- [x] {a}" for a in task.acceptance_criteria)
                + f"\n\n### Spec\n\n{task.spec}\n\n### Review (Claude, round {task.review_round})\n\n{review}\n"
                + (f"\n### Non-blocking notes\n\n{nits}\n" if nits else "")
                + f"\n---\nBuilt by Agent Office: spec + review by Claude, code + tests by Codex. "
                  f"Request {task.request_id}.\n")

    def _pr(self, task: Task) -> None:
        path = self._ensure_worktree(task)
        auto = self.cfg.merge_mode == "auto"
        before = wt.git(path, "rev-parse", "HEAD")
        if auto and not wt.update_from_base(path, self.cfg.base_branch):
            # Another task merged first and touched the same lines: Codex merges and resolves.
            task.conflicts += 1
            self.store.event("merge_conflict", task_id=task.id, round=task.conflicts)
            if task.conflicts > MAX_CONFLICT_ROUNDS:
                self._escalate(task, "merge_conflict", f"merge conflict with {self.cfg.base_branch} still there "
                                                       f"after {MAX_CONFLICT_ROUNDS} attempts")
                return
            task.merge_conflict = True
            self._move(task, Stage.DEV, f"merge conflict with {self.cfg.base_branch} ({task.conflicts}/"
                                        f"{MAX_CONFLICT_ROUNDS})")
            self.say("claude", "codex", f"{task.id} xung đột với {self.cfg.base_branch} (task khác vừa merge). "
                     "Codex merge lại và gỡ xung đột nhé.", task.id, kind="conflict")
            return
        if auto and wt.git(path, "rev-parse", "HEAD") != before and (self.cfg.test_cmd or self.cfg.eval_cmd):
            # Other tasks merged meanwhile: make sure the combination still passes before merging.
            ok, out = True, ""
            if self.cfg.test_cmd:
                with self._unlocked():
                    ok, out = self._run_test_cmd(path)
            if ok:
                out = self._eval_problem(task, path)
                ok = not out
            if not ok:
                task.test_output = out[-6000:]
                self._move(task, Stage.DEV, f"tests fail after merging the latest {self.cfg.base_branch}")
                self.say("claude", "codex", f"{task.id}: sau khi gộp {self.cfg.base_branch} mới thì test fail, "
                         "Codex sửa giúp nhé.", task.id, kind="test_fail")
                return
        try:
            if not self.cfg.open_pr:
                task.pr_url = f"local:{task.branch}"
                if auto:
                    wt.merge_local(self.repo, task.branch, self.cfg.base_branch)
                else:
                    self.store.event("pr_ready", task_id=task.id, url=task.pr_url)
                    self.echo(f"{task.id}: branch {task.branch} ready to merge (open_pr = false)")
                    return
            else:
                if not task.pr_url:
                    task.pr_url = wt.push_and_open_pr(path, self.cfg.remote, task.branch, self.cfg.base_branch,
                                                      f"{task.id}: {task.title}", self._pr_body(task))
                    self.store.event("pr_opened", task_id=task.id, url=task.pr_url)
                    self.echo(f"{task.id}: PR opened {task.pr_url}")
                if not auto:
                    return
                wt.merge_pr(self.repo, task.pr_url, self.cfg.remote, self.cfg.base_branch)
        except wt.GitError as e:
            self._github_failed(task, str(e))
            return
        self.store.event("pr_merged", task_id=task.id, url=task.pr_url, by="auto")
        if task.eval_score is not None:
            self.store.meta["eval_baseline"] = task.eval_score
            self.store.meta.setdefault("eval_history", []).append(
                {"task_id": task.id, "score": task.eval_score, "at": now_iso()})
        self._finish(task, "auto-merged after approval")
        self.say("claude", "po", f"Đã merge {task.id} '{task.title}' vào {self.cfg.base_branch}.", task.id,
                 kind="merged")

    # ------------------------------------------------------------------ GitHub environment
    def _github_failed(self, task: Task, error: str) -> None:
        """A push / PR / merge failed. Login, permission and lasting network problems are the
        user's machine: report them with the exact fix. Anything else goes to the Tech Lead."""
        kind = github.classify(error)
        if kind == "other":
            task.net_retries = 0
            self._escalate(task, "merge_failed", f"could not merge: {error}")
            return
        if kind == "network" and task.net_retries < len(NET_BACKOFF_MIN):
            minutes = NET_BACKOFF_MIN[task.net_retries]
            task.net_retries += 1
            task.retry_at = (self.clock() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
            self.store.event("github_retry", task_id=task.id, issue=kind, minutes=minutes,
                             attempt=task.net_retries, error=error[:300])
            self.echo(f"{task.id}: GitHub network error, retrying in {minutes} min")
            return
        with self._unlocked():
            checks = self.github_preflight(self.repo, self.cfg.remote)
        bad = github.problems(checks)
        text = github.report(checks) if bad else f"lỗi từ GitHub: {error[:300]}"
        task.retry_at, task.tl_issue, task.tl_kind = "", "", ""
        self._block(task, f"{ENV_MARK}: {kind}: {text}"[:1500])
        self._env_checked_at = self.clock()
        self.store.event("env_problem", task_id=task.id, issue=kind, error=error[:500],
                         checks=[{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks])
        self.say("claude", "po", f"Cần anh sửa trên máy (không phải lỗi code): {task.id} đã được duyệt nhưng "
                 f"office không tạo/merge được PR vì {kind}. {text} Chạy `office doctor` để kiểm tra lại; "
                 f"khi ổn, office tự tạo PR và merge tiếp (kiểm tra lại mỗi {ENV_RECHECK_MIN} phút).",
                 task.id, kind="env")
        self.echo(f"{task.id}: GitHub {kind} problem on this machine -> reported to the PO")

    def recheck_environment(self, force: bool = False) -> list[str]:
        """Tasks waiting for the user to fix GitHub go back to the PR step once the preflight passes."""
        with self.lock:
            waiting = [t for t in self.store.tasks.values()
                       if t.stage == Stage.BLOCKED and t.blocked_reason.startswith(ENV_MARK)]
            now = self.clock()
            if not waiting or (not force and self._env_checked_at is not None
                               and now - self._env_checked_at < timedelta(minutes=ENV_RECHECK_MIN)):
                return []
            self._env_checked_at = now
        checks = self.github_preflight(self.repo, self.cfg.remote)
        if github.problems(checks):
            return []
        with self.lock:
            moved = []
            for t in waiting:
                if t.stage != Stage.BLOCKED:
                    continue
                t.blocked_reason, t.net_retries = "", 0
                self._move(t, Stage.PR, "GitHub OK again")
                self.store.event("env_fixed", task_id=t.id)
                moved.append(t.id)
            if moved:
                self.say("claude", "po", f"GitHub đã ổn, office tạo PR / merge tiếp: {', '.join(moved)}.", kind="env")
                self.store.save()
            return moved

    def _finish(self, task: Task, note: str) -> None:
        self._move(task, Stage.DONE, note)
        if task.worktree:
            wt.remove_worktree(self.repo, Path(task.worktree))

    # ------------------------------------------------------------------ Tech Lead
    # Technical blockers never go to the PO. The office hands them to Claude as Tech Lead, who
    # either decides (retry with guidance, restart from the base, split, wait, drop) or, only for
    # a genuinely unclear business requirement, asks the PO.
    def _escalate(self, task: Task, kind: str, reason: str, questions: list[str] | None = None) -> None:
        if task.tl_rounds >= self.cfg.tech_lead_rounds:
            self._retire(task, f"Tech Lead out of rounds ({task.tl_rounds}) on {kind}: {reason[:300]}", report=True)
            return
        task.tl_issue, task.tl_kind, task.questions = reason[:6000], kind, list(questions or [])
        self.store.event("techlead_needed", task_id=task.id, issue=kind, reason=reason[:500],
                         round=task.tl_rounds + 1, of=self.cfg.tech_lead_rounds)
        frm = "codex" if task.stage in (Stage.DEV, Stage.TEST) else "claude"
        self.say(frm, "claude", f"{task.id}: {TL_KINDS.get(kind, kind)}. Tech Lead xử lý, không hỏi PO.",
                 task.id, kind="escalate")
        self.echo(f"{task.id}: technical blocker ({kind}) -> Tech Lead")

    def _escalate_request(self, req: Request, kind: str, reason: str, questions: list[str] | None = None) -> None:
        if req.tl_rounds >= self.cfg.tech_lead_rounds:
            # A request cannot be dropped: pause, then plan again with fresh rounds.
            until = self.clock() + timedelta(minutes=REQUEST_PAUSE_MIN)
            req.retry_at, req.tl_rounds, req.tl_issue = until.isoformat(timespec="seconds"), 0, ""
            self.store.event("techlead_paused", request_id=req.id, issue=kind, until=req.retry_at)
            self.echo(f"{req.id}: Tech Lead out of rounds on {kind}; trying again at {req.retry_at}")
            return
        req.tl_issue, req.tl_kind, req.tl_questions = reason[:6000], kind, list(questions or [])
        self.store.event("techlead_needed", request_id=req.id, issue=kind, reason=reason[:500],
                         round=req.tl_rounds + 1, of=self.cfg.tech_lead_rounds)
        self.say("claude", "claude", f"{req.id}: {TL_KINDS.get(kind, kind)}. Tech Lead xử lý, không hỏi PO.",
                 kind="escalate")
        self.echo(f"{req.id}: technical blocker ({kind}) -> Tech Lead")

    def _others(self, task: Task | None) -> str:
        rows = []
        for u in sorted(self.store.tasks.values(), key=lambda t: t.id):
            if task is not None and u.id == task.id:
                continue
            state = u.stage.value + (f", dropped: {u.dropped[:80]}" if u.dropped else "")
            rows.append(f"- {u.id} [{state}] {u.title}" + (f"; files: {', '.join(u.files[:8])}" if u.files else "")
                        + (f"; after {', '.join(u.depends_on)}" if u.depends_on else ""))
        return "\n".join(rows) or "- (none)"

    def _tl_prompt(self, target: str, kind: str, issue: str, questions: list[str], rnd: int, context: str) -> str:
        return prompt("tech_lead", target=target, kind=kind, kind_text=TL_KINDS.get(kind, kind),
                      issue=issue, questions=bullets(questions), round=rnd, max_rounds=self.cfg.tech_lead_rounds,
                      context=context, specs=specdocs.context(self.repo))

    def _tech_lead(self, task: Task, agent_name: str = "claude") -> None:
        rnd = task.tl_rounds + 1
        req = self.store.requests.get(task.request_id)
        context = (f"## Product Owner request\n\n{self._request_text(req) if req else ''}\n\n"
                   f"## Task {task.id}: {task.title} (stage {task.stage.value}, branch {task.branch or '-'})\n\n"
                   f"{task.brief}\n\n### Spec\n\n{task.spec or '(not written yet)'}\n\n### Acceptance criteria\n\n"
                   f"{bullets(task.acceptance_criteria)}\n\n### Files it changes\n\n{bullets(task.files)}\n\n"
                   f"### Counters\n\ntest attempts {task.test_attempts}, review rounds {task.review_round}, merge "
                   f"conflicts {task.conflicts}, dependency fixes {task.env_fixes}, restarts {task.attempt}\n\n"
                   f"### Earlier Tech Lead decisions\n\n{bullets(task.tl_notes)}\n\n### Review comments\n\n"
                   + bullets([f"[{c.get('severity', '')}] {c.get('file', '')}: {c.get('text', '')}"
                              for c in task.review_comments])
                   + f"\n\n### Last failing test output\n\n```\n{task.test_output[-2500:]}\n```\n\n"
                   f"## Other tasks (ordering and file overlap)\n\n{self._others(task)}")
        cwd = Path(task.worktree) if task.worktree and Path(task.worktree).exists() else self.repo
        res = self._call(agent_name, self._tl_prompt(f"task {task.id}", task.tl_kind, task.tl_issue, task.questions,
                                                   rnd, context), cwd, task.id, f"techlead{rnd}", task)
        if res is None:
            return  # resting: the issue stays and is picked up again
        task.tl_rounds = rnd
        try:
            d = extract_json(res.text)
            business = [str(q) for q in d.get("business_questions", []) if str(q).strip()]
            action = str(d.get("action", "")).lower()
            assert business or action in TL_ACTIONS, f"unknown action {action!r}"
        except Exception as e:  # noqa: BLE001
            self.store.event("techlead_unparseable", task_id=task.id, round=rnd, error=str(e)[:300])
            if rnd >= self.cfg.tech_lead_rounds:
                self._retire(task, f"Tech Lead answer not readable after {rnd} rounds ({task.tl_kind})", report=True)
            return
        kind = task.tl_kind
        task.tl_issue, task.tl_kind = "", ""
        if business:
            task.questions = business
            self.store.event("techlead_decision", task_id=task.id, issue=kind, action="ask_po", round=rnd)
            self.say("claude", "po", f"{task.id}: câu hỏi nghiệp vụ, cần anh quyết: " + " | ".join(business),
                     task.id, kind="question")
            self._block(task, f"{BUSINESS_MARK}: " + " | ".join(business)[:800])
            return
        decision = str(d.get("decision", "")).strip() or f"{action} after {kind}"
        guidance = str(d.get("guidance", "")).strip()
        task.decisions.append(f"Tech Lead ({kind}): {decision}")
        task.tl_notes.append(f"[{kind}] {decision}" + (f" | {guidance}" if guidance else ""))
        task.questions = []
        self.store.event("techlead_decision", task_id=task.id, issue=kind, action=action, round=rnd,
                         decision=decision[:500])
        self.say("claude", "codex" if action in ("retry", "restart") else "all",
                 f"Tech Lead quyết {task.id} ({action}): {decision[:400]}", task.id, kind="decision")
        self.echo(f"{task.id}: Tech Lead -> {action}: {decision[:160]}")
        if action == "drop":
            self._retire(task, f"dropped by the Tech Lead: {decision}", report=True)
            return
        if action == "split":
            items = [it for it in d.get("tasks", []) if isinstance(it, dict)]
            req = self.store.requests.get(task.request_id)
            created = self._add_tasks(req, items) if req and items else []
            if not created:
                task.tl_notes.append("split was not possible (no room for new tasks); retrying instead")
                action = "retry"
            else:
                for tid in created:
                    nt = self.store.tasks[tid]
                    nt.depends_on = list(dict.fromkeys(task.depends_on + nt.depends_on))
                for u in self.store.tasks.values():
                    if task.id in u.depends_on and u.id not in created:
                        u.depends_on = [x for x in u.depends_on if x != task.id] + created
                self._retire(task, f"split into {', '.join(created)}: {decision}")
                return
        for key in ("spec",):
            if str(d.get(key, "")).strip():
                task.spec = str(d[key])
        for key in ("acceptance_criteria", "test_plan", "files"):
            if isinstance(d.get(key), list) and d[key]:
                setattr(task, key, [str(x) for x in d[key]])
        task.tl_guidance = guidance or decision
        task.test_attempts = task.review_round = task.env_fixes = 0
        if action == "wait":
            minutes = _minutes(d.get("minutes"))
            task.retry_at = (self.clock() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
            if kind in ("merge_conflict",):
                task.conflicts = 0
            return
        task.retry_at = ""
        if action == "restart" or kind == "secret":
            # Fresh branch from the latest base. A branch that held a secret is deleted, never merged.
            if task.worktree:
                wt.discard_branch(self.repo, Path(task.worktree), task.branch, delete=kind == "secret")
            task.attempt += 1
            task.worktree = task.branch = task.base_ref = task.pr_url = ""
            task.merge_conflict, task.conflicts, task.test_output = False, 0, ""
            task.review_comments, task.checkpoint = [], None
            after = [str(x) for x in d.get("after", []) if str(x) in self.store.tasks and str(x) != task.id]
            task.depends_on = list(dict.fromkeys(task.depends_on + after))
            to = Stage.TODO if after else (Stage.SPEC if not task.spec else Stage.DEV)
            self._reroute(task, to, f"Tech Lead restart ({kind})" + (f" after {', '.join(after)}" if after else ""))
            return
        # retry: run the stuck step again with the Tech Lead's guidance
        if kind == "merge_conflict":
            task.conflicts, task.merge_conflict = 0, bool(task.worktree)
        if task.stage == Stage.SPEC or (kind in ("parse_error", "merge_failed") and task.stage != Stage.TEST):
            return  # same step again (spec / review / merge)
        if task.stage != Stage.DEV:
            self._reroute(task, Stage.DEV, f"Tech Lead retry ({kind})")

    def _reroute(self, task: Task, to: Stage, note: str) -> None:
        frm = task.stage
        task.reroute(to, note)
        self.store.event("stage_changed", task_id=task.id, frm=frm.value, to=to.value, note=note)
        self.echo(f"{task.id}: {frm.value} -> {to.value} ({note})")

    def _retire(self, task: Task, why: str, report: bool = False) -> None:
        """Take a task off the board without merging it; the goal check re-plans what is missing."""
        task.dropped = why[:1000]
        task.tl_issue = task.tl_kind = ""
        req = self.store.requests.get(task.request_id)
        if req is not None:
            req.decisions.append(f"Tech Lead: {task.id} '{task.title}' not merged: {why[:300]}")
        if task.worktree:
            wt.discard_branch(self.repo, Path(task.worktree), task.branch, delete=True)
        self._reroute(task, Stage.DONE, why[:200])
        self.store.event("task_dropped", task_id=task.id, why=why[:500])
        if report:
            self.say("claude", "po", f"Báo cáo (không cần anh làm gì): {task.id} '{task.title}' được gác lại, "
                     f"không merge. Lý do: {why[:400]}. Khi kiểm tra mục tiêu em sẽ lên kế hoạch lại phần còn thiếu.",
                     task.id, kind="report")

    def _tech_lead_request(self, req: Request, agent_name: str = "claude") -> None:
        rnd = req.tl_rounds + 1
        context = (f"## Product Owner request {req.id} (status {req.status})\n\n{self._request_text(req)}\n\n"
                   f"## Tasks so far\n\n{self._others(None)}")
        res = self._call(agent_name, self._tl_prompt(f"request {req.id}", req.tl_kind, req.tl_issue, req.tl_questions,
                                                   rnd, context), self.repo, req.id, f"techlead{rnd}")
        if res is None:
            return
        req.tl_rounds = rnd
        try:
            d = extract_json(res.text)
            business = [str(q) for q in d.get("business_questions", []) if str(q).strip()]
            action = str(d.get("action", "retry")).lower()
        except Exception as e:  # noqa: BLE001
            self.store.event("techlead_unparseable", request_id=req.id, round=rnd, error=str(e)[:300])
            if rnd >= self.cfg.tech_lead_rounds:
                self._escalate_request(req, req.tl_kind, req.tl_issue, req.tl_questions)
            return
        kind = req.tl_kind
        req.tl_issue, req.tl_kind = "", ""
        if business:
            req.tl_questions = []
            self.store.event("techlead_decision", request_id=req.id, issue=kind, action="ask_po", round=rnd)
            self.say("claude", "po", f"{req.id}: câu hỏi nghiệp vụ, cần anh quyết: " + " | ".join(business),
                     kind="question")
            self._block_request(req, BUSINESS_MARK, business)
            return
        decision = str(d.get("decision", "")).strip() or f"{action} after {kind}"
        guidance = str(d.get("guidance", "")).strip()
        qs = "\n".join(f"Q: {q}" for q in req.tl_questions)
        req.tl_notes.append((qs + "\nA: " if qs else f"[{kind}] ") + (guidance or decision))
        req.decisions.append(f"Tech Lead ({kind}): {decision}")
        req.tl_questions = []
        self.store.event("techlead_decision", request_id=req.id, issue=kind, action=action, round=rnd,
                         decision=decision[:500])
        self.say("claude", "all", f"Tech Lead quyết {req.id}: {decision[:400]}", kind="decision")
        if action == "wait":
            minutes = _minutes(d.get("minutes"))
            req.retry_at = (self.clock() + timedelta(minutes=minutes)).isoformat(timespec="seconds")

    # ------------------------------------------------------------------ merges
    def sync_merged(self) -> list[str]:
        merged = []
        for t in self.store.tasks.values():
            if t.stage != Stage.PR or not t.pr_url or t.id in self.inflight:
                continue
            if t.pr_url.startswith("local:"):
                out = wt.git(self.repo, "branch", "--merged", self.cfg.base_branch, check=False)
                is_merged = t.branch in [b.strip("*+ ") for b in out.splitlines()]
            else:
                is_merged = wt.pr_state(self.repo, t.pr_url) == "MERGED"
            if is_merged:
                if t.eval_score is not None:
                    self.store.meta["eval_baseline"] = t.eval_score
                self._finish(t, "merged by PO")
                merged.append(t.id)
        if merged:
            self.store.save()
        return merged

    # ------------------------------------------------------------------ PO actions
    def retry_request(self, request_id: str, text: str = "") -> Request:
        req = self.store.requests[request_id]
        if text.strip():
            qs = "\n".join(f"Q: {q}" for q in req.questions)
            req.po_answers.append((qs + "\nA: " if qs else "") + text.strip())
        back = req.blocked_stage if req.status == "blocked" else req.status
        req.status, req.note, req.questions = (back if back in ("new", "planned") else "new"), "", []
        if req.status == "planned" and req.goal_rounds > self.cfg.max_goal_rounds:
            req.goal_rounds = self.cfg.max_goal_rounds  # one more follow-up round after the PO weighs in
        self.store.event("request_answered", request_id=req.id)
        if text.strip():
            self.say("po", "claude", f"Trả lời {req.id}: {text.strip()[:400]}", kind="answer")
        self.store.save()
        return req

    def answer(self, task_id: str, text: str) -> Task:
        task = self.store.tasks[task_id]
        if task.stage != Stage.BLOCKED:
            raise ValueError(f"{task_id} is {task.stage.value}, not blocked")
        qs = "\n".join(f"Q: {q}" for q in task.questions)
        task.po_answer = (task.po_answer + "\n\n" + (qs + "\nA: " if qs else "") + text).strip()
        task.questions = []
        back = Stage(task.blocked_from) if task.blocked_from in {"spec", "dev", "test", "review", "pr"} else Stage.DEV
        if back in (Stage.TEST, Stage.REVIEW):
            back = Stage.DEV
        task.review_round = 0
        task.test_attempts = 0
        task.env_fixes = 0
        task.blocked_reason = ""
        task.tl_issue = task.tl_kind = ""
        self._move(task, back, "PO answered")
        self.say("po", "claude", f"Trả lời {task.id}: {text.strip()[:400]}", task.id, kind="answer")
        self.store.save()
        return task

    def wake(self, agent_name: str) -> None:
        a = self.store.agents[agent_name]
        a.status, a.rest_until, a.reset_known, a.failures = AgentStatus.IDLE, "", False, 0
        self.store.event("agent_awake", agent=agent_name, manual=True)
        self.store.save()
