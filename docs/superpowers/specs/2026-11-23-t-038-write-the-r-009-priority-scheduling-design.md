# T-038: Write the R-009 priority-scheduling design and TDD plan for the owner

Request R-009. Request design: `docs/superpowers/specs/2026-11-23-r-009-u-ti-n-task-n-y-design.md`. Plan: `docs/superpowers/plans/2026-11-23-t-038-write-the-r-009-priority-scheduling.md`.

## Product Owner request

Ưu tiên task này lên trên đầu giúp tôi

Optimize the current Multi-Agent Office orchestration for **maximum parallelism, priority-based scheduling, and asynchronous execution**.

Requirements:

1. **Parallel Execution:** All available agents work simultaneously on independent tasks.
2. **Priority-based Scheduling:** Prioritize tasks by `Critical > High > Medium > Low`, considering dependencies, urgency, and business impact.
3. **Critical Task Preemption:** Schedule critical tasks first; safely pause lower-priority work only when necessary, without losing progress.
4. **Non-blocking Workflow:** Agents never wait for unrelated tasks.
5. **Continuous Assignment:** Immediately assign the highest-priority READY task whenever an agent becomes available.
6. **Async Pipeline:** PM plans, Tech Lead designs/reviews, Developer codes, and Tester validates concurrently.
7. **Dependency-aware Scheduling:** Block only tasks with unmet dependencies; prioritize tasks that unblock multiple downstream tasks.
8. **Worktree Isolation:** Use separate Git worktrees to avoid code conflicts.
9. **Event-driven Scheduling:** Reassign work immediately after task completion, failure, or dependency resolution.
10. **Failure Isolation:** Failed or blocked tasks must not stop independent tasks.
11. **Resource Optimization:** Respect concurrency limits, prevent duplicate assignments, avoid starvation, and minimize idle time.
12. **Dynamic Reprioritization:** Support changing task priorities during execution without disrupting unrelated work.

**Goal:** Keep all agents continuously productive, executing the highest-value available tasks asynchronously while maximizing throughput and maintaining code quality.

Analyze the existing scheduler, implement the improvements, and add automated tests for concurrency, priority ordering, dependency handling, and failure recovery.

## Goal

Doc-only task. Create exactly two new files and change nothing else. Not agent-office/, AGENTS.md, CLAUDE.md, .agent-office/config.toml, docs/superpowers/INDEX.md or DECISIONS.md: the orchestrator appends the index and decision entries itself, per decision T-037/R-008. The files are (a) docs/superpowers/specs/2026-11-23-r-009-priority-scheduling-design.md and (b) docs/superpowers/plans/2026-11-23-r-009-priority-scheduling.md. Read agent-office/agent_office/{scheduler,pipeline,models,config,cli,store}.py, dashboard/server.py plus static/app.js, and tests/{test_parallel,fake_agent,conftest}.py first. Cite real function names with line ranges and check them against main before writing: plan_steps scheduler.py:142-245, STAGE_PRIORITY :16, file_conflict :103-119, task_runnable :122-139, deps_done :75, Office.dispatch pipeline.py:280-296, free_slots :273-278, _run_inflight :298-310, drain_inbox :174-200, add_request :249-257, _add_tasks :542-563, cmd_run cli.py:87-125, POST /api/requests server.py:127-131.

The design file has five parts. (1) What already exists, with citations: parallel sessions, event-driven dispatch, no duplicate assignment through inflight/busy, dependency gating, file-overlap serialisation, a worktree per task, failure isolation and quota failover. (2) What is missing: the priority field and its persistence, the ordering function, aging, the reprioritise command plus a dashboard control, the unblock-count tiebreak, and file_conflict ignoring priority. (3) The ordering key in this order: effective priority, then transitive downstream count (more first), then stage rank, then id. Stage rank is techlead, PR, REVIEW, TEST, DEV, SPEC/breakdown/goal, TODO, and wake steps stay first. (4) The aging rule: one level per aging_minutes, capped at High; the waiting clock is the `at` of the task's last history entry, else Task.created_at. (5) Preemption only at step boundaries, plus an explicit out-of-scope list: hard kill, cross-request priority inheritance, and the PM setting priorities.

The plan file has 5 owner TDD steps. Each names exact files, the failing test to write first in agent-office/tests (fake_agent.py plus the conftest Env/auto_env helpers, new file test_priority.py), the minimal code, and the verify command `python -m pytest -q agent-office/tests`. The steps: (1) PRIORITIES constant plus Task.priority and Request.priority defaulting to medium, loaded from an old state.json without the field. Inherited in _add_tasks, set through add_request(text, priority), the drain_inbox 'request' command, `office request --priority` and the dashboard POST body; an invalid level is rejected. (2) effective_priority plus the sort key in scheduler.py, with plan_steps collecting candidates before take(), and [scheduling] aging_minutes=30 in config.py and its template. (3) A downstream_count(store, task_id) transitive tiebreak, and file_conflict letting the higher effective priority win among tasks not yet coding (a task already coding still goes first). (4) An 'priority' inbox command → Office.set_priority, `office priority ID LEVEL` in cli.py, POST /api/priority in server.py plus a select control in static/app.js, and a priority_changed event. (5) Concurrency and failure tests.

The plan must list these tests: priority ordering (Critical before Low, same stage, dev x1); aging and no starvation (Low reaches High after 2xN minutes and never passes Critical); a dependency-blocked Critical task that is never picked; unblock-count ordering; a failed or BLOCKED task that does not stop an independent one from reaching done; reprioritising while a step is in flight (the inflight entry is untouched, the step is not cancelled, and the next dispatch uses the new order); no duplicate assignment and peak sessions ≤ cfg.parallel under run_parallel; and the existing test_plan_steps_respects_sessions_and_busy passing unchanged. End with the owner's follow-up: office test_cmd covers only tests/, so the owner must add `python -m pytest -q agent-office/tests` to their own check (and README). Assumptions: the file names above; no cross-request dependencies exist today, so priority inheritance is YAGNI. Verify: `git diff --name-only main...HEAD` lists only the two new files, every cited `def` name is found by grep in agent-office/, and `python -m pytest -q tests` still passes.

## Acceptance criteria

- AC1: `git diff --name-only main...HEAD` prints exactly two lines: docs/superpowers/specs/2026-11-23-r-009-priority-scheduling-design.md and docs/superpowers/plans/2026-11-23-r-009-priority-scheduling.md (both newly added; `git diff --name-status main...HEAD` shows A for both).
- AC2: The design file contains these five headings in this order: `## 1. What already exists`, `## 2. What is missing`, `## 3. Ordering key`, `## 4. Aging`, `## 5. Preemption` (the heading text may continue after these words), checked with `grep -n '^## [1-5]\.'`.
- AC3: Section 1 of the design cites (name plus file:line or line range) Office.dispatch, free_slots, _run_inflight, drain_inbox, plan_steps, deps_done, task_runnable, file_conflict, assigned_agent and cmd_run, covering parallel sessions, event-driven dispatch, no duplicate assignment, dependency gating, file-overlap serialisation, worktree per task, failure isolation and quota failover.
- AC4: Section 2 of the design names all six gaps: the priority field and its persistence, the ordering function, aging, the reprioritise command plus a dashboard control, the unblock-count tiebreak, and file_conflict ignoring priority.
- AC5: Section 3 gives the key (effective priority, then transitive downstream count with more first, then stage rank, then id), gives the stage rank techlead < pr < review < test < dev < spec/breakdown/goal < todo, and says wake steps stay first. Section 4 says one level per aging_minutes (default 30), capped at High, with the clock taken from the last history `at`, else created_at. Section 5 says steps are preempted only at step boundaries and lists hard kill, cross-request priority inheritance and the PM setting priorities as out of scope.
- AC6: For every existing name cited in either file, `grep -rn 'def <name>' agent-office/` (or `grep -rn '<NAME> =' agent-office/agent_office` for constants) finds a match. Each cited line range contains that definition on main. Names that do not exist yet are marked (new).
- AC7: The plan file has exactly five step headings `### Step 1` … `### Step 5`. Each step names its exact agent-office files, a failing test in agent-office/tests/test_priority.py, the minimal code, and the verify command `python -m pytest -q agent-office/tests`.
- AC8: The plan file names these tests: test_priority_orders_critical_before_low, test_aging_raises_low_to_high_never_critical, test_dependency_blocked_critical_is_never_picked, test_unblock_count_breaks_ties, test_blocked_task_does_not_stop_independent_task, test_reprioritise_in_flight_keeps_step_and_applies_next_dispatch and test_no_duplicate_assignment_and_peak_within_parallel. It also says the existing test_plan_steps_respects_sessions_and_busy must pass unchanged.
- AC9: The plan file covers priority input and change: `office request --priority`, the dashboard POST body, `office priority R-xxx|T-xxx <level>`, POST /api/priority, a select control in app.js and a priority_changed event. It says R-xxx updates only unfinished tasks and that a change affects only the next dispatch.
- AC10: The plan file ends with an owner follow-up section stating that office test_cmd covers only tests/ and that the owner must add `python -m pytest -q agent-office/tests` to their own check and to README.
- AC11: `python -m pytest -q tests` still passes on the task branch (the summary line shows no failures).

## Out of scope

- Any change under agent-office/ (code, tests, fake_agent.py, dashboard): the owner implements the plan by hand.
- Editing AGENTS.md, CLAUDE.md, .agent-office/config.toml, README.md, docs/superpowers/INDEX.md or docs/superpowers/DECISIONS.md.
- Asking the PO to change protected_paths or test_cmd.
- Hard kill or interruption of a running agent call.
- Cross-request priority inheritance or cross-request dependencies.
- The PM setting or suggesting priorities.
- Per-priority session reservations, quotas or a persistent run queue.

## Decisions

- R-009 is delivered as a design plus a plan only (Tech Lead option C). The owner implements it by hand, and agents never edit agent-office/.
- Priority levels are critical > high > medium > low, stored lowercase on Task.priority and Request.priority, default medium. Tasks inherit the request level in _add_tasks. `office priority R-xxx` updates the request and its unfinished tasks; `office priority T-xxx` overrides one task.
- Only the PO sets priority (CLI, dashboard, inbox command). A change affects only the next dispatch, never touches inflight, and adds no history entry, so the aging clock is not reset.
- Sort key for ready steps: (effective priority, -transitive not-DONE downstream count, stage rank, target id). Stage rank: techlead 0, pr 1, review 2, test 3, dev 4, spec/breakdown/goal 5, todo 6. Wake steps stay first. Request steps use the request's priority and created_at, with a downstream count of 0.
- Aging lowers the rank by one level per aging_minutes (config [scheduling] aging_minutes, default 30; 0 turns aging off) and never goes past High. A negative wait counts as 0. The clock is the last history `at`, else created_at.
- Preemption happens only at step boundaries: a freed session goes to the best ready step, and lower tasks keep their stage and worktree.
- file_conflict: between tasks without a worktree, the better (effective priority, id) goes first. A task that already has a worktree still goes first.
- Aging tests set history and created_at relative to Env.now, because models.now_iso uses the real wall clock.
- Line ranges are cited as checked on main 9ec129b (drain_inbox 174-199, add_request 249-256, _add_tasks 542-562, cmd_run 87-159), not as the slightly different ranges in the task brief.
- Doc-only tasks are checked with shell commands; the Tester commits no test or script files, so the diff stays at exactly two files.

## Existing specs this task changes

- (none)
