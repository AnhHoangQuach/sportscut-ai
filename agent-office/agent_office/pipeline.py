"""The Office: executes one step at a time and moves tasks through the state machine."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from string import Template
from typing import Callable

from . import worktree as wt
from .agents import AgentResult, ClaudeAgent, CliAgent, CodexAgent, extract_json
from .config import Config, load_config
from .limits import LimitHit, detect, rest_until
from .models import (MAX_REVIEW_ROUNDS, MAX_TEST_ATTEMPTS, AgentStatus, Request, Stage, Task,
                     now_iso)
from .scheduler import Step, next_step
from .store import Store

# After this many consecutive unexplained failures, an agent is treated as rate limited.
FAILURES_BEFORE_REST = 2


def prompt(name: str, **vars: object) -> str:
    text = resources.files("agent_office.prompts").joinpath(f"{name}.md").read_text(encoding="utf-8")
    return Template(text).safe_substitute({k: str(v) for k, v in vars.items()})


def bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) or "- (none)"


class Office:
    def __init__(self, repo: Path, agents: dict[str, CliAgent] | None = None,
                 clock: Callable[[], datetime] | None = None, echo: Callable[[str], None] | None = None):
        self.store = Store(repo).load()
        self.repo = self.store.repo
        self.cfg: Config = load_config(self.store.dir)
        self.agents = agents or {"claude": ClaudeAgent(self.cfg.claude), "codex": CodexAgent(self.cfg.codex)}
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.echo = echo or (lambda msg: print(msg, flush=True))

    # ------------------------------------------------------------------ requests
    def add_request(self, text: str) -> Request:
        req = Request(id=self.store.next_request_id(), text=text.strip())
        self.store.requests[req.id] = req
        self.store.save()
        self.store.event("request_added", request_id=req.id, text=req.text[:500])
        return req

    # ------------------------------------------------------------------ main step
    def step(self) -> Step | None:
        self.sync_merged()
        plan = next_step(self.store, self.clock())
        if plan.step is None:
            return None
        s = plan.step
        if s.kind == "wake":
            self._wake(s.target)
        elif s.kind == "breakdown":
            self._breakdown(self.store.requests[s.target])
        else:
            task = self.store.tasks[s.target]
            handler = {
                Stage.TODO: self._todo, Stage.SPEC: self._spec, Stage.DEV: self._dev,
                Stage.TEST: self._test, Stage.REVIEW: self._review, Stage.PR: self._pr,
            }[task.stage]
            handler(task)
        self.store.save()
        return s

    # ------------------------------------------------------------------ agent calls
    def _call(self, agent_name: str, text: str, cwd: Path, task_id: str, label: str,
              task: Task | None = None) -> AgentResult | None:
        """Run an agent. Returns None if it hit a limit/failed (agent is then resting)."""
        agent = self.store.agents[agent_name]
        agent.status = AgentStatus.WORKING
        self.store.save()
        self.store.event("agent_working", agent=agent_name, task_id=task_id, label=label)
        self.echo(f"  [{agent_name}] {label} ({task_id})...")
        res = self.agents[agent_name].run(text, cwd, self.store.log_path(task_id, f"{label}-{agent_name}"))
        agent.status = AgentStatus.IDLE

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
                self._rest(agent_name, LimitHit(agent_name, "repeated failures", None), task, label, res)
            elif task is not None:
                self._checkpoint(task, label, f"{agent_name} failed (exit {res.exit_code})", res)
            return None
        agent.failures = 0
        agent.last_error = ""
        self.store.event("agent_done", agent=agent_name, task_id=task_id, label=label, log=res.log_path)
        return res

    def _rest(self, agent_name: str, hit: LimitHit, task: Task | None, label: str,
              res: AgentResult | None) -> None:
        a = self.store.agents[agent_name]
        until, known = rest_until(hit.reset_at, a.backoff_level, self.cfg.backoff_minutes, self.clock())
        if not known:
            a.backoff_level += 1
        a.status = AgentStatus.RESTING
        a.rest_until = until.isoformat(timespec="seconds")
        a.reset_known = known
        a.failures = 0
        a.last_error = hit.matched
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
            res = self.agents[agent_name].run(prompt("probe"), self.repo,
                                              self.store.log_path("_probe", agent_name), probe=True)
            if res.limit is not None or res.exit_code != 0:
                self._rest(agent_name, res.limit or LimitHit(agent_name, "probe failed", None), None,
                           "probe", res)
                return
        a.status = AgentStatus.IDLE
        a.rest_until = ""
        a.reset_known = False
        a.backoff_level = 0
        self.store.event("agent_awake", agent=agent_name)
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
            if wt.commit_all(w, f"wip(office): checkpoint {task.id} {label}"):
                cp["wip_commit"] = wt.git(w, "rev-parse", "HEAD")
        self.store.event("task_checkpoint", task_id=task.id, **{k: v for k, v in cp.items() if k != "log_tail"})

    def _clear_checkpoint(self, task: Task) -> None:
        task.checkpoint = None
        if task.worktree:
            (Path(task.worktree) / wt.NOTES_DIR / "CHECKPOINT.md").unlink(missing_ok=True)

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
    def _breakdown(self, req: Request) -> None:
        res = self._call("claude", prompt("pm_breakdown", request=req.text, request_id=req.id),
                         self.repo, req.id, "breakdown")
        if res is None:
            return
        try:
            items = extract_json(res.text)["tasks"]
            assert isinstance(items, list) and items
        except Exception as e:  # noqa: BLE001
            req.status, req.note = "blocked", f"could not parse task list: {e}"
            self.store.event("request_blocked", request_id=req.id, note=req.note)
            self.echo(f"{req.id}: blocked ({req.note}); see {res.log_path}")
            return
        key_to_id: dict[str, str] = {}
        for i, it in enumerate(items, 1):
            tid = self.store.next_task_id()
            key_to_id[str(it.get("key", i))] = tid
            deps = [key_to_id[str(k)] for k in it.get("depends_on", []) if str(k) in key_to_id]
            t = Task(id=tid, title=str(it.get("title", f"Task {i}"))[:120], brief=str(it.get("brief", "")),
                     request_id=req.id, depends_on=deps)
            self.store.tasks[tid] = t
            req.task_ids.append(tid)
            self.store.event("task_created", task_id=tid, title=t.title, depends_on=deps, request_id=req.id)
            self.echo(f"{tid}: created '{t.title}'" + (f" (after {', '.join(deps)})" if deps else ""))
        req.status = "planned"

    def _todo(self, task: Task) -> None:
        self._move(task, Stage.SPEC, "dependencies done")

    def _spec(self, task: Task) -> None:
        req = self.store.requests.get(task.request_id)
        po = f"## Product Owner answer to an earlier question\n\n{task.po_answer}" if task.po_answer else ""
        res = self._call("claude", prompt("pm_spec", request=req.text if req else "", task_id=task.id,
                                          title=task.title, brief=task.brief, po_answer=po),
                         self.repo, task.id, "spec", task)
        if res is None:
            return
        try:
            d = extract_json(res.text)
            task.spec = str(d["spec"])
            task.acceptance_criteria = [str(x) for x in d.get("acceptance_criteria", [])]
            task.test_plan = [str(x) for x in d.get("test_plan", [])]
            task.out_of_scope = [str(x) for x in d.get("out_of_scope", [])]
        except Exception as e:  # noqa: BLE001
            self._block(task, f"spec output not parseable: {e}")
            return
        self._clear_checkpoint(task)
        self._move(task, Stage.DEV, f"{len(task.acceptance_criteria)} acceptance criteria")

    def _ensure_worktree(self, task: Task) -> Path:
        path, branch, base = wt.ensure_worktree(self.repo, self.cfg.worktrees_path(self.repo), task.id,
                                                self.cfg.base_branch)
        if not task.worktree:
            task.worktree, task.branch, task.base_ref = str(path), branch, base
            self.store.event("worktree_ready", task_id=task.id, path=str(path), branch=branch)
        self._write_task_md(task, path)
        return path

    def _write_task_md(self, task: Task, path: Path) -> None:
        parts = [f"# {task.id}: {task.title}\n\n{task.brief}\n", f"## Spec\n\n{task.spec}\n",
                 f"## Acceptance criteria\n\n{bullets(task.acceptance_criteria)}\n",
                 f"## Test plan\n\n{bullets(task.test_plan)}\n",
                 f"## Out of scope\n\n{bullets(task.out_of_scope)}\n"]
        if task.po_answer:
            parts.append(f"## Product Owner answer\n\n{task.po_answer}\n")
        if task.review_comments:
            parts.append(f"## Review feedback to address (round {task.review_round})\n\n" + "\n".join(
                f"- [{c.get('severity', '')}] {c.get('file', '')}:{c.get('line', '')} {c.get('text', '')}"
                for c in task.review_comments) + "\n")
        if task.test_output:
            parts.append(f"## Last failing test output\n\n```\n{task.test_output[-4000:]}\n```\n")
        (wt.notes_dir(path) / "TASK.md").write_text("\n".join(parts), encoding="utf-8")

    def _dev(self, task: Task) -> None:
        path = self._ensure_worktree(task)
        if task.checkpoint:
            mode = ("RESUMING: a previous run was interrupted. Read `.office/CHECKPOINT.md` and "
                    "`git log` to see what is already done, then continue; do not redo finished work.")
        elif task.review_comments:
            mode = "This is a revision: address every blocker/major item under 'Review feedback' in TASK.md."
        elif task.test_output:
            mode = "Tests failed last time: see 'Last failing test output' in TASK.md and fix the cause."
        else:
            mode = "This is a fresh start on the task."
        res = self._call("codex", prompt("dev", task_id=task.id, mode=mode), path, task.id, "dev", task)
        if res is None:
            return
        if res.text.lstrip().startswith("BLOCKED:"):
            wt.commit_all(path, f"wip(office): {task.id} blocked")
            self._block(task, res.text.strip()[:1000])
            return
        wt.commit_all(path, f"feat({task.id}): {task.title}")
        self._clear_checkpoint(task)
        touched = self._protected_changes(task, path)
        if touched:
            self._block(task, f"changed protected paths: {', '.join(touched[:5])}")
            return
        self._move(task, Stage.TEST)

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
                           timeout=1800)
        return p.returncode == 0, f"$ {self.cfg.test_cmd}\n(exit {p.returncode})\n{p.stdout[-6000:]}\n{p.stderr[-3000:]}"

    def _test(self, task: Task) -> None:
        path = self._ensure_worktree(task)
        extra = f"The orchestrator will also run: `{self.cfg.test_cmd}`" if self.cfg.test_cmd else ""
        res = self._call("codex", prompt("test", task_id=task.id, extra=extra), path, task.id, "test", task)
        if res is None:
            return
        wt.commit_all(path, f"test({task.id}): tests for {task.title}")
        agent_pass = "RESULT: FAIL" not in res.text
        cmd_pass, cmd_out = self._run_test_cmd(path)
        self._clear_checkpoint(task)
        if agent_pass and cmd_pass:
            task.test_output = ""
            report = path / wt.NOTES_DIR / "TEST_REPORT.md"
            agent_summary = report.read_text(encoding="utf-8")[-3000:] if report.exists() else res.text[-2000:]
            (wt.notes_dir(path) / "TEST_SUMMARY.md").write_text(f"{agent_summary}\n\n{cmd_out[-2000:]}",
                                                                encoding="utf-8")
            self._move(task, Stage.REVIEW, "tests pass")
            return
        task.test_attempts += 1
        task.test_output = (cmd_out if not cmd_pass else res.text)[-6000:]
        if task.test_attempts >= MAX_TEST_ATTEMPTS:
            self._block(task, f"tests still failing after {task.test_attempts} attempts")
        else:
            self._move(task, Stage.DEV, f"tests failed (attempt {task.test_attempts}/{MAX_TEST_ATTEMPTS})")

    def _review(self, task: Task) -> None:
        path = self._ensure_worktree(task)
        summary_file = path / wt.NOTES_DIR / "TEST_SUMMARY.md"
        test_summary = summary_file.read_text(encoding="utf-8") if summary_file.exists() else "(not recorded)"
        rnd = task.review_round + 1
        res = self._call("claude", prompt(
            "review", task_id=task.id, round=rnd, max_rounds=MAX_REVIEW_ROUNDS, spec=task.spec,
            acceptance_criteria=bullets(task.acceptance_criteria), test_summary=test_summary,
            diff=wt.diff(path, task.base_ref) or "(empty diff)"), path, task.id, f"review{rnd}", task)
        if res is None:
            return
        try:
            d = extract_json(res.text)
            verdict = str(d.get("verdict", "")).lower()
            comments = [c for c in d.get("comments", []) if isinstance(c, dict)]
        except Exception as e:  # noqa: BLE001
            self._block(task, f"review output not parseable: {e}")
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
            return
        task.review_comments = comments
        if rnd >= MAX_REVIEW_ROUNDS:
            self._block(task, f"review not approved after {rnd} rounds: {str(d.get('summary', ''))[:500]}")
        else:
            self._move(task, Stage.DEV, f"changes requested in round {rnd} ({len(comments)} comments)")

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
        if not self.cfg.open_pr:
            task.pr_url = f"local:{task.branch}"
            self.store.event("pr_ready", task_id=task.id, url=task.pr_url)
            self.echo(f"{task.id}: branch {task.branch} ready to merge (open_pr = false)")
            return
        try:
            url = wt.push_and_open_pr(path, self.cfg.remote, task.branch, self.cfg.base_branch,
                                      f"{task.id}: {task.title}", self._pr_body(task))
        except wt.GitError as e:
            self._block(task, f"could not open PR: {e}")
            return
        task.pr_url = url
        self.store.event("pr_opened", task_id=task.id, url=url)
        self.echo(f"{task.id}: PR opened {url}")

    # ------------------------------------------------------------------ merges
    def sync_merged(self) -> list[str]:
        merged = []
        for t in self.store.tasks.values():
            if t.stage != Stage.PR or not t.pr_url:
                continue
            if t.pr_url.startswith("local:"):
                out = wt.git(self.repo, "branch", "--merged", self.cfg.base_branch, check=False)
                is_merged = t.branch in [b.strip("*+ ") for b in out.splitlines()]
            else:
                is_merged = wt.pr_state(self.repo, t.pr_url) == "MERGED"
            if is_merged:
                self._move(t, Stage.DONE, "merged by PO")
                if t.worktree:
                    wt.remove_worktree(self.repo, Path(t.worktree))
                merged.append(t.id)
        if merged:
            self.store.save()
        return merged

    # ------------------------------------------------------------------ PO actions
    def retry_request(self, request_id: str) -> Request:
        req = self.store.requests[request_id]
        req.status, req.note = "new", ""
        self.store.save()
        return req

    def answer(self, task_id: str, text: str) -> Task:
        task = self.store.tasks[task_id]
        if task.stage != Stage.BLOCKED:
            raise ValueError(f"{task_id} is {task.stage.value}, not blocked")
        task.po_answer = (task.po_answer + "\n\n" + text).strip()
        back = Stage(task.blocked_from) if task.blocked_from in {"spec", "dev", "test", "review", "pr"} else Stage.DEV
        if back in (Stage.TEST, Stage.REVIEW):
            back = Stage.DEV
        task.review_round = 0
        task.test_attempts = 0
        task.blocked_reason = ""
        self._move(task, back, "PO answered")
        self.store.save()
        return task

    def wake(self, agent_name: str) -> None:
        a = self.store.agents[agent_name]
        a.status, a.rest_until, a.reset_known, a.failures = AgentStatus.IDLE, "", False, 0
        self.store.event("agent_awake", agent=agent_name, manual=True)
        self.store.save()
