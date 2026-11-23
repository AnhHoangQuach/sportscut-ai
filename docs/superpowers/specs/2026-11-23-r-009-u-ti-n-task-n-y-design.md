# R-009 design

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

## Design (goal, approaches, choice)

R-009 design (PM, 2026-11-23). Goal: the PO wants the Agent Office to always give a free agent session the most valuable ready step. That means Critical > High > Medium > Low, aging so Low work is never starved, and among equal priorities the task that unblocks the most downstream work goes first. All of the existing parallelism and isolation must stay. The PO asked for this request to go first. Following the Tech Lead's decision (option C), R-009 produces only a design and an implementation plan under docs/superpowers/. The owner then builds it by hand in agent-office/, which is a protected path agents never change, the same way R-007 was built. How we will know it is reached: (1) for this request, a design and a plan that cite the real scheduler code are committed, and the diff contains nothing outside those two docs. (2) For the owner's build, every test the plan lists passes with `python -m pytest -q agent-office/tests`, and the current test_parallel.py suite still passes unchanged, because with every task at Medium today's order must stay the same. What already exists (read on main 9ec129b): parallel sessions per role through Office.dispatch (agent_office/pipeline.py:280-296) using free_slots (pipeline.py:273-278) and cfg.parallel. cmd_run starts a ThreadPoolExecutor and re-dispatches after every step through wait(FIRST_COMPLETED, timeout=2) (agent_office/cli.py:87-125). That covers event-driven, continuous assignment. _nap wakes early when an inbox command arrives (cli.py:78-84). No duplicate assignment: Office.inflight is keyed by target, and plan_steps skips `busy` (scheduler.py:142-245). Dependency gating: deps_done (scheduler.py:75) and task_runnable (scheduler.py:122-139). File-overlap serialisation: file_conflict (scheduler.py:103-119). One worktree per task (worktree.py, pipeline._ensure_worktree). Failure isolation: _run_inflight catches crashes per step (pipeline.py:298-310), and BLOCKED tasks are skipped. Quota failover is in assigned_agent (scheduler.py:59-72). What is missing: Task and Request have no priority field. Today the order is fixed: wakes, then request steps (techlead/breakdown/goal) in insertion order, then task techlead steps by id, then STAGE_PRIORITY (scheduler.py:16), then task id (scheduler.py:214, 224). There is also no aging or starvation guard, no `office priority` command, no dashboard control, no count of how many tasks a task unblocks, and file_conflict lets the lower id win even when the other task is Critical. Approaches considered: (A) Rewrite the office as an async event loop with a separate priority-queue service and hard preemption that kills running agent calls. Rejected: it throws away paid quota and in-progress work, rewrites working concurrency code, and fails YAGNI. (B) Keep the existing dispatch loop and make plan_steps build every candidate step first, then sort them with one pure ordering key. The key is: effective priority (base level raised by aging, capped at High) first, then the number of transitive downstream tasks the step unblocks (more first), then stage rank, then id. After sorting, apply the existing take() and slot limits. Preemption happens only at step boundaries: a running call is never killed, and a lower task between steps keeps its stage and worktree. (C) Add a separate priority-ordered ready queue kept in state.json and updated by events. Rejected: it duplicates state that plan_steps already derives from the store each dispatch, and it can drift from the store. Chosen: B. It is the smallest change that meets all 12 requirements: 8 of them already hold, and the other four need one field, one sort key, one command and one config value. It keeps every current guarantee. Because the sort is stable and all-Medium keys reduce to today's order, nothing regresses. Decisions taken by the Tech Lead and recorded here: the levels are Critical > High > Medium > Low. Priority is set per request with `office request --priority` or on the dashboard, and the default is Medium. Tasks inherit it. `office priority T-xxx <level>` overrides one task, and `office priority R-xxx <level>` updates every unfinished task of that request. The PM never sets priority. A priority change only affects the next dispatch and never cancels running work. Aging raises a step one level per N minutes of waiting, N = [scheduling] aging_minutes with a default of 30, never above High. Hard interruption is out of scope.

## Tasks

See the rows for R-009 in `INDEX.md`.
