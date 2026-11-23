# R-009: Priority scheduling for Agent Office (design)

Request: R-009  
Task: T-038  
Plan: [2026-11-23-r-009-priority-scheduling.md](../plans/2026-11-23-r-009-priority-scheduling.md)  
Status: the owner implements this by hand; agents never edit agent-office/ (protected path)

## 1. What already exists

- **Parallel sessions per role:** `Office.dispatch` passes `busy=set(self.inflight)` and `slots=self.free_slots()` to `plan_steps` (`agent-office/agent_office/pipeline.py:280-296`; `agent-office/agent_office/scheduler.py:142-245`). `free_slots` subtracts sessions in flight from `cfg.parallel[role]` (`pipeline.py:273-278`). `cmd_run` drives dispatch through a `ThreadPoolExecutor` (`agent-office/agent_office/cli.py:87-159`, especially 108-130). The configured defaults are pm=1, lead=1, dev=2, tester=1 (`agent-office/agent_office/config.py:83-90`).
- **Event-driven dispatch:** the `cmd_run` loop waits with `FIRST_COMPLETED` and a two-second timeout, then dispatches again (`agent-office/agent_office/cli.py:87-159`). Each `Office.dispatch` first calls `drain_inbox` (`agent-office/agent_office/pipeline.py:280-296`; `drain_inbox`, 174-199), so PO commands land before the next scheduling decision. `_nap` wakes early when an inbox file appears (`agent-office/agent_office/cli.py:78-84`).
- **No duplicate assignment:** `Office.inflight`, a target-to-agent map, and the `RLock` are created at `agent-office/agent_office/pipeline.py:127-147`. `plan_steps` skips busy target ids (`agent-office/agent_office/scheduler.py:142-245`), `_run_inflight` removes its target in `finally` (`pipeline.py:298-310`), and `_unlocked` releases the lock only while a CLI runs (`pipeline.py:149-162`).
- **Dependency gating:** `deps_done` requires every known dependency to be DONE (`agent-office/agent_office/scheduler.py:75-76`), and the TODO branch of `task_runnable` reports unmet dependencies (`scheduler.py:122-139`).
- **File-overlap serialisation:** `_overlap` compares normalized paths while excluding `NEVER_CONFLICT` append-only files (`agent-office/agent_office/scheduler.py:80,90-100`); `file_conflict` serializes active tasks that touch the same files (`scheduler.py:103-119`).
- **Worktree per task:** `_ensure_worktree` creates or reuses the isolated task worktree (`agent-office/agent_office/pipeline.py:674`); `Task.worktree` and `Task.branch` persist its location and branch (`agent-office/agent_office/models.py:69-145`).
- **Failure isolation:** `_run_inflight` catches every exception for one step and emits `step_crashed` before removing only that inflight entry (`agent-office/agent_office/pipeline.py:298-310`). `task_runnable` skips BLOCKED tasks (`agent-office/agent_office/scheduler.py:122-139`), while `tl_issue` is scheduled as an independent Tech Lead step by `plan_steps` (`scheduler.py:214-219`) rather than stopping unrelated work.
- **Quota failover:** `assigned_agent` chooses a role on the other subscription only for quota or budget rest (`agent-office/agent_office/scheduler.py:59-72`), using the `FAILOVER` mapping (`agent-office/agent_office/models.py:33`). `plan_steps` wakes expired resting CLIs before ordinary work (`scheduler.py:172-188`).
- **Today's order:** `plan_steps` emits wake steps first, request steps in insertion order, task Tech Lead steps by id, then `STAGE_PRIORITY` times task id (`agent-office/agent_office/scheduler.py:16,142-245`). Its inner `take` consumes slots in loop order (`scheduler.py:160-170`), so the first candidate encountered is served first.

## 2. What is missing

- **The priority field and its persistence:** neither `Task` (`agent-office/agent_office/models.py:69-145`) nor `Request` (`models.py:197-217`) has one. `Store.load` uses `Task.from_dict` and `Request(**r)` (`agent-office/agent_office/store.py:48-57`). Adding a default of `medium` to both models lets old `state.json` files without the field load safely; `Task.from_dict` already filters to known dataclass fields.
- **An ordering function:** `plan_steps` calls `take` directly in loop order and has no common sort key (`agent-office/agent_office/scheduler.py:142-245`).
- **Aging:** no waiting-time adjustment exists.
- **A reprioritise command plus dashboard control:** `drain_inbox` knows request, retry, answer, triage, retry_github and wake only (`agent-office/agent_office/pipeline.py:174-199`). `cmd_request` has no `--priority` (`agent-office/agent_office/cli.py:67-75`), and `post_request` accepts only `TextBody(text)` (`agent-office/agent_office/dashboard/server.py:36-37,127-131`).
- **The unblock-count tiebreak:** dependencies are checked only in the forward direction by `deps_done`; the scheduler does not count reverse, transitive dependants (`agent-office/agent_office/scheduler.py:75-76`).
- **`file_conflict` ignoring priority:** between two tasks not yet coding, the lower id always wins (`agent-office/agent_office/scheduler.py:103-119`).
- **Testing clock caveat:** `now_iso` uses the real wall clock (`agent-office/agent_office/models.py:10-11`), whereas `Env.now` is fixed at 2026-11-22 12:00 UTC (`agent-office/tests/conftest.py:19-72`). Aging fixtures must therefore set history timestamps explicitly.

## 3. Ordering key

Add `PRIORITIES = ('critical', 'high', 'medium', 'low')` **(new)**. Values are stored as lowercase strings with ranks 0 through 3. Sort ready candidates ascending by:

`(effective_priority, -downstream_count, stage_rank, target_id)`

- `effective_priority` **(new)** comes first; smaller is more urgent.
- `downstream_count` **(new)** is transitive and more dependants sort first through the negative value.
- `STAGE_RANK` **(new)** is: Tech Lead (request or task) 0, PR 1, REVIEW 2, TEST 3, DEV 4, SPEC/breakdown/goal 5, TODO 6.
- Target id is the deterministic final tiebreak.
- Wake steps are not ranked and stay first, as today.
- Request breakdown, goal and request-Tech-Lead steps use `Request.priority`, wait since `Request.created_at`, and have downstream count zero.
- Task steps use `Task.priority` and `downstream_count(store, task_id)` **(new)**: the number of distinct, not-DONE tasks that directly or transitively depend on that task. It walks reverse `depends_on` edges with a visited set, so a cycle cannot loop.
- `plan_steps` first builds all ready candidates, sorts them, then calls `take`. A candidate whose agent has no free slot records the same reason as today but does not prevent a lower-ranked candidate for another role from starting; scheduling remains non-blocking.
- Dependency gating, file overlap, per-role slots, busy skipping, failure isolation, and dispatch after every completion remain unchanged. `next_step` (`agent-office/agent_office/scheduler.py:248-249`) keeps `limit=1` and returns the first candidate under the same key.

Worked example: with dev x1, a Critical DEV candidate gets the session before a Low DEV candidate. If two Medium DEV candidates otherwise tie, the one that transitively unblocks more unfinished tasks goes first.

## 4. Aging

`effective_priority(level, waiting_since, now, aging_minutes) -> int` **(new)** is `rank - floor(waited_minutes / aging_minutes)`, never below 1 (High).

- Critical remains rank 0 and High remains rank 1.
- Negative waiting time counts as zero.
- `aging_minutes <= 0` disables aging.
- A task's waiting clock starts at the `at` value of its last `history` entry, or at `Task.created_at` when history is empty. Request steps use `Request.created_at`.
- Add `[scheduling] aging_minutes = 30` and `Config.aging_minutes` **(new)**. `Office.step` and `Office.dispatch` pass it to `next_step`, `plan_steps`, `task_runnable`, and `file_conflict` through new keyword parameters defaulting to 30 (`agent-office/agent_office/pipeline.py:259-296`; existing scheduler definitions at `scheduler.py:103-119,122-142,248-249`).
- A priority change does not append task history, so it does not reset the waiting clock.

For example, a Low task ready at 12:00 becomes Medium at 12:30 and High at 13:00. It remains High thereafter and never ages into Critical.

## 5. Preemption at step boundaries only; out of scope

- A running agent call is never killed, and a priority change never touches `Office.inflight` (`agent-office/agent_office/pipeline.py:127-147`).
- When a session becomes free, the next dispatch gives it to the best ordering key, so a ready Critical step starts before any lower-priority candidate for that session.
- A lower-priority task between steps remains in its current stage with its worktree, branch, and checkpoint and resumes later. This is the safe “pause without losing progress” promised by the design.
- For `file_conflict`, when neither task has a worktree, the better `(effective_priority, id)` wins. A task with a worktree—already coding—still goes first.
- Only the PO sets priority through `office request --priority <level>`, the dashboard, or `office priority R-xxx|T-xxx <level>`.
  - An `R-xxx` change updates the request and every unfinished task belonging to it; later tasks inherit the request's new level.
  - A `T-xxx` change overrides that task only.
  - The PM never sets priority. Prompts remain unchanged, and priority keys in PM JSON are ignored.
  - A change affects only the next dispatch decision.
- **Out of scope:** hard kill or interruption of a running call; cross-request priority inheritance, because no cross-request dependencies exist today; the PM setting priorities; per-priority session reservations or quotas.
