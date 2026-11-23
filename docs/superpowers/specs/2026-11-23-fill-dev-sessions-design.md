# Fill every Developer session

## Request (PO, 2026-11-23)

"setting lại triển khai lên 3 dev": the PO set `[parallel] dev = 3` and restarted `office run`, but
only one Codex Developer ever worked.

## Root cause

`[parallel]` was read correctly (`free_slots`, `plan_steps(slots=...)`); a session only starts when a
task is ready, and two rules made almost every task wait on the one before it:

1. `pm_breakdown.md` told the PM to make a task depend on an earlier one whenever both change the
   same file (CLI entry point, `pyproject.toml`). In a small CLI nearly every slice touches those, so
   the breakdown was a single chain, and `depends_on` waits until the other task is **merged**.
2. `file_conflict` held a task's files from `dev` until merge (test, review and PR included), stricter
   than the decision "tasks on the same files never *code* at the same time".

Nothing said why the other sessions were idle: the runner prints reasons only when nothing runs, and
the dashboard computed `waiting_on` with `next_step` (limit 1), which stops collecting reasons after
the first runnable step.

## Design

- `file_conflict` counts another task only while it codes: stage `dev`, or `blocked` out of `dev`
  with its worktree. A task sent back to `dev` (failed tests, merge conflict) holds its files again.
  Merge conflicts that follow are resolved by the existing Developer conflict round (docs 2.3).
- `pm_breakdown.md`: `depends_on` only when the task needs code from the other one; shared files
  never need a dependency; prefer independent tasks so the Developers work in parallel.
- `Office.dispatch` calls `_report_idle`: for every role with more than one session and idle
  sessions, emit `slots_idle {role, idle, sessions, waiting_on}` and echo
  `dev: 2/3 sessions idle; waiting: ...`, only when the idle count or reasons change.
- Dashboard `snapshot` uses `plan_steps` with `busy` = tasks in agents' `active` and per-role free
  slots, so "Đang chờ" lists every waiting task.

## Acceptance criteria

- AC1: a task in `dev` whose files overlap a task in test/review is runnable; one overlapping a task
  in `dev` still waits (`test_shared_files_hold_a_task_only_while_the_other_one_codes`).
- AC2: the breakdown prompt no longer asks to chain tasks on shared files and says `depends_on` is
  only for needed code (`test_breakdown_prompt_keeps_tasks_independent`).
- AC3: with `dev = 3`, one dev task running and one task waiting on it, dispatch records
  `slots_idle` (dev, 2 of 3) with the reason, echoes it once, and does not repeat it
  (`test_dispatch_says_why_dev_sessions_stay_idle`).
- AC4: the dashboard waiting list contains `T-002 waits for T-001 to be merged` while T-001 is being
  coded (`test_waiting_list_explains_idle_sessions_while_a_task_runs`).
- AC5: `python -m pytest -q agent-office/tests` passes.

## Out of scope

Rewriting an already-planned chain in an existing `state.json` (tasks keep the `depends_on` they were
created with); priority scheduling (R-009 plan).
