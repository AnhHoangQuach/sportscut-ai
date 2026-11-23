# Plan T-038: Write the R-009 priority-scheduling design and TDD plan for the owner

Design: `docs/superpowers/specs/2026-11-23-t-038-write-the-r-009-priority-scheduling-design.md`.

## Implementation plan

# T-038: Write the R-009 priority-scheduling design and TDD plan for the owner (doc-only)

## Context
The PO wants R-009 done first: priority-based, preemptive, event-driven scheduling in Agent Office. Every change for R-009 lives in `agent-office/`, which is a protected path. Agents never edit it, and the office `test_cmd` (`python -m pytest -q tests`) never runs `agent-office/tests`. The Tech Lead chose option C: the team writes only a design and a plan under `docs/superpowers/`, and the owner builds it by hand in TDD steps, as was done for R-007. This task creates **exactly two new markdown files** and changes nothing else. The Developer READS `agent-office/` to analyse it and re-checks every citation on current main (`grep -n`) before writing.

## Files to create (nothing else)
- (a) `docs/superpowers/specs/2026-11-23-r-009-priority-scheduling-design.md`
- (b) `docs/superpowers/plans/2026-11-23-r-009-priority-scheduling.md`

Forbidden: anything under `agent-office/`, `AGENTS.md`, `CLAUDE.md`, `.agent-office/config.toml`, `docs/superpowers/INDEX.md`, `docs/superpowers/DECISIONS.md` (the orchestrator appends the index and decision entries itself, per decision T-037/R-008), and any test or script file. The Tester checks with shell commands only and commits nothing.

## Citations checked on main (9ec129b). Use these ranges; a few differ from the task brief
| Name | Location |
|---|---|
| `STAGE_PRIORITY` | agent_office/scheduler.py:16 |
| `Step` / `Plan` | scheduler.py:19-23 / 26-31 |
| `agent_available` | scheduler.py:49-56 |
| `assigned_agent` | scheduler.py:59-72 |
| `deps_done` | scheduler.py:75-76 |
| `NEVER_CONFLICT` / `_overlap` | scheduler.py:80 / 90-100 |
| `file_conflict` | scheduler.py:103-119 |
| `task_runnable` | scheduler.py:122-139 |
| `plan_steps` | scheduler.py:142-245 (inner `take` 160-170, wake loop 172-188, request loop 190-212, task techlead loop 214-219, stage loop 224-236, BLOCKED reasons 238-244) |
| `next_step` | scheduler.py:248-249 |
| `now_iso` | models.py:10-11 (real wall clock, NOT Office.clock) |
| `FAILOVER` / `STAGE_AGENT` / `STEP_ROLE` | models.py:33 / 36-45 / 47 |
| `Task` (history :114, created_at :115, from_dict :140-145) | models.py:69-145 |
| `Request` | models.py:197-217 |
| `Store.load` (Task.from_dict :52, `Request(**r)` :55) | store.py:48-57 |
| `BUSINESS_MARK` / `ENV_MARK` | pipeline.py:64 / 67 |
| `Office.__init__` (lock :143, inflight :144) | pipeline.py:127-147 |
| `_unlocked` | pipeline.py:149-162 |
| `submit` | pipeline.py:165-172 |
| `drain_inbox` | pipeline.py:174-199 (brief said 174-200) |
| `add_request` | pipeline.py:249-256 (brief said 249-257) |
| `step` | pipeline.py:259-270 |
| `free_slots` | pipeline.py:273-278 |
| `dispatch` | pipeline.py:280-296 |
| `_run_inflight` | pipeline.py:298-310 |
| `_execute` | pipeline.py:312-341 |
| `_add_tasks` | pipeline.py:542-562 (brief said 542-563) |
| `_ensure_worktree` | pipeline.py:674 |
| `DEFAULT_CONFIG` [parallel] / `Config` / `load_config` | config.py:83-90 / 125-152 / 184-220 |
| `cmd_request` | cli.py:67-75 |
| `_nap` | cli.py:78-84 |
| `cmd_run` | cli.py:87-159 (parallel dispatch loop 108-130; brief said 87-125) |
| `cmd_wake` / `main` | cli.py:257-260 / 392-457 (request parser 398-401) |
| `TextBody` / `snapshot` | dashboard/server.py:36-37 / 40-60 |
| `post_request` (POST /api/requests) | server.py:127-131 |
| `wake_agent` (POST /api/agents/{name}/wake) | server.py:143-147 |
| `renderRequests` / `renderBoard` / request-form submit | dashboard/static/app.js:195-207 / 209-235 / 393-405 |
| `Env` / `auto_env` | agent-office/tests/conftest.py:19-72 / 80-82 |
| `run_parallel` / `set_cfg` | tests/test_parallel.py:24-40 / 15-21 |
| `test_plan_steps_respects_sessions_and_busy` | tests/test_parallel.py:43-58 |
| fake CLI kinds / scripted `fail` | tests/fake_agent.py `kind_of` 17-34 / 61-63 |

When the files are written, the Developer re-runs `grep -n` for each name. If a line moved, use the current line.

## (a) Design file content
Title `# R-009: Priority scheduling for Agent Office (design)`. Header lines: Request R-009, Task T-038, link to the plan file, and `Status: the owner implements this by hand; agents never edit agent-office/ (protected path)`. Then exactly these five `##` sections:

### `## 1. What already exists`
One bullet per item, each with a citation:
- **Parallel sessions per role:** `Office.dispatch` passes `busy=set(self.inflight)` and `slots=self.free_slots()` to `plan_steps`. `free_slots` is `cfg.parallel[role]` minus the sessions in flight. `cmd_run` runs dispatch on a ThreadPoolExecutor. The defaults are pm=1 lead=1 dev=2 tester=1.
- **Event-driven dispatch:** the `cmd_run` loop waits FIRST_COMPLETED (timeout 2 s) and calls `dispatch` again. Each dispatch first runs `drain_inbox`, so PO commands land before the next scheduling decision, and `_nap` wakes early when an inbox file appears.
- **No duplicate assignment:** the `inflight` target-to-agent map is guarded by an RLock. `plan_steps` skips `busy` ids, `_run_inflight` pops the entry in `finally`, and `_unlocked` releases the lock only while a CLI runs.
- **Dependency gating:** `deps_done` plus the TODO branch of `task_runnable`.
- **File-overlap serialisation:** `file_conflict`, `_overlap` and `NEVER_CONFLICT`.
- **Worktree per task:** `_ensure_worktree`, plus `Task.worktree` and `Task.branch`.
- **Failure isolation:** `_run_inflight` catches every exception and emits `step_crashed`. `task_runnable` skips BLOCKED tasks, and `tl_issue` routes a task to the Tech Lead without stopping others.
- **Quota failover:** `assigned_agent`, `FAILOVER`, and resting CLIs woken first (plan_steps 172-188).
- **Today's order:** wake steps; then request steps in insertion order; then task techlead steps by id; then `STAGE_PRIORITY` × task id. `take` uses up slots in that loop order, so the first come is the first served.

### `## 2. What is missing`
- The priority field and its persistence. Neither `Task` nor `Request` has one. `Store.load` uses `Task.from_dict` (which drops unknown keys) and `Request(**r)`, so a new field that defaults to `medium` loads an old state.json.
- An ordering function. `plan_steps` takes steps in loop order and has no sort key.
- Aging. There is none.
- A reprioritise command and a dashboard control. `drain_inbox` knows only request/retry/answer/triage/retry_github/wake. `cmd_request` has no `--priority`. POST /api/requests accepts only `TextBody(text)`.
- The unblock-count tiebreak. Dependencies are checked forward only.
- `file_conflict` ignores priority: between two tasks that are not yet coding, the lower id always wins.
- Note for testing: `now_iso` uses the real clock, while tests run on `Env.now` (2026-11-22 12:00 UTC).

### `## 3. Ordering key`
`PRIORITIES = ('critical', 'high', 'medium', 'low')` (rank 0-3, stored as lowercase strings). Ready candidates are sorted ascending by `(effective_priority, -downstream_count, stage_rank, target_id)`.
- `stage_rank`: techlead (request or task) 0, pr 1, review 2, test 3, dev 4, spec/breakdown/goal 5, todo 6.
- Wake steps are not ranked. They stay first, as today.
- Request steps (breakdown, goal, request techlead) use `Request.priority`, wait since `Request.created_at`, and have a downstream count of 0.
- Task steps use `Task.priority` and `downstream_count(store, task_id)`: the number of distinct, not-DONE tasks that depend on the task directly or transitively. It walks reverse `depends_on` with a visited set, so a cycle cannot loop.
- `plan_steps` builds the candidate list first, sorts it, then calls `take`. A candidate whose agent has no free slot logs the same reason as today and does not stop lower candidates for other roles (non-blocking).
- Kept unchanged: dependency gating, file overlap, per-role slots, the busy skip, failure isolation, dispatch on every completion, and `next_step` (`limit=1`), which returns the first candidate by key.
- Include a worked example: with dev x1, a Critical DEV task takes the dev session before a Low one, and a Medium tie goes to the task that unblocks more.

### `## 4. Aging`
`effective_priority(level, waiting_since, now, aging_minutes) -> int` = `rank - floor(waited_min / aging_minutes)`, never below 1 (High).
- Critical stays 0 and High stays 1.
- A negative wait counts as 0.
- `aging_minutes <= 0` turns aging off.
- Waiting clock: the `at` of the task's last `history` entry, else `Task.created_at`. Request steps use `Request.created_at`.
- Config: `[scheduling] aging_minutes = 30` becomes `Config.aging_minutes`. `Office.step` and `Office.dispatch` pass it to `plan_steps`, `next_step`, `task_runnable` and `file_conflict` (new keyword, default 30).
- A priority change does not add a history entry, so it does not reset the clock.
- Example: a Low task ready at 12:00 becomes Medium at 12:30 and High at 13:00, and never becomes Critical.

### `## 5. Preemption at step boundaries only; out of scope`
- A running agent call is never killed. Priority changes never touch `inflight`.
- When a session frees up, the next dispatch gives it to the best key, so a ready Critical step takes it before any lower step.
- A lower task between steps stays in its stage with its worktree, branch and checkpoint, and continues later. This is how the design meets 'pause without losing progress'.
- `file_conflict`: between tasks with no worktree, the better `(effective_priority, id)` goes first. A task that already has a worktree (already coding) still goes first.
- Only the PO sets priority: `office request --priority <level>`, the dashboard, and `office priority R-xxx|T-xxx <level>`.
  - `R-xxx` changes the request and every unfinished task in it. Tasks created later inherit the new level.
  - `T-xxx` overrides one task.
  - The PM never sets a priority. Prompts are unchanged, and any priority key in PM JSON is ignored.
  - A change affects only the next dispatch decision.
- **Out of scope:** hard kill or interruption of a running call; cross-request priority inheritance (no cross-request dependencies exist today); the PM setting priorities; per-priority session reservations or quotas.

## (b) Plan file content
Use the Superpowers writing-plans header: Goal, Architecture, Tech Stack, and the note that the owner implements this by hand and agents never edit agent-office/. Then a `## Tests` table listing every test name below with its step, then exactly five sections `### Step 1` … `### Step 5`.

Each step has these parts:
- **Files:** exact `agent-office/...` paths.
- **Failing test first:** in `agent-office/tests/test_priority.py`, using the conftest `auto_env`/`Env` (fake_agent.py CLIs) and `run_parallel`/`set_cfg` imported from `test_parallel`. Include the expected failure.
- **Minimal code.**
- **Verify:** `python -m pytest -q agent-office/tests`.

The plan defines one small helper in test_priority.py, `make_tasks(office, items)`. It uses `office.add_request` plus `req.status = 'planned'` plus `office._add_tasks`, then sets stage, priority, depends_on, history and created_at on each task. This is the same pattern as `test_plan_steps_keeps_normal_roles_when_both_agents_have_quota`. Aging tests set `history=[{'at': (env.now - timedelta(minutes=M)).isoformat(), ...}]`, because `now_iso` is the real clock.

### Step 1: Priority field, persistence and input
**Files:** agent_office/models.py, pipeline.py, cli.py, dashboard/server.py, dashboard/static/index.html, dashboard/static/app.js.

**Tests:**
- `test_priority_defaults_to_medium_and_old_state_loads`: delete the `priority` keys from state.json, then `Store(repo).load()` gives medium.
- `test_request_priority_is_inherited_by_tasks`: `add_request('x', 'critical')`, then `_add_tasks` gives critical tasks.
- `test_invalid_priority_is_rejected`: `add_request('x', 'urgent')` raises ValueError. `office request --priority urgent x` gives SystemExit 2. The inbox `{'cmd': 'request', 'text': 'x', 'priority': 'urgent'}` gives 'request failed: …' and no new request.
- `test_cli_and_dashboard_set_request_priority`: `office request --priority high Cut` gives R-001 high. POST /api/requests `{'text', 'priority': 'low'}` gives low. An invalid level gives 400. The test uses `pytest.importorskip('fastapi')`.

**Code:**
- models.py: `PRIORITIES` and `check_priority(level) -> str` (strip and lowercase, ValueError naming the levels). `Task.priority = 'medium'` and `Request.priority = 'medium'`.
- pipeline.py: `add_request(text, priority='medium')`. `_add_tasks` passes `priority=req.priority`. The drain_inbox 'request' branch reads `c.get('priority', 'medium')`.
- cli.py: `--priority` with `choices=PRIORITIES`, `type=str.lower`, default medium.
- server.py: `RequestBody(text, priority='medium')`.
- index.html: a `select#request-priority`.
- app.js: send the priority with the request, and show a priority badge on cards and request rows.

### Step 2: Ordering key and aging
**Files:** scheduler.py, config.py, pipeline.py.

**Tests:**
- `test_priority_orders_critical_before_low`: two DEV tasks in the same stage, T-001 low and T-002 critical. With dev slots 1, `plan_steps` gives `['T-002']` and `next_step` gives T-002.
- `test_aging_raises_low_to_high_never_critical`:
  - Unit checks for low: 0/29/30/59/60/600 min give 3/3/2/2/1/1. Critical always gives 0. Medium at 30 min gives 1. `aging_minutes=0` gives 3.
  - Plan checks: a Low task that waited 60 min beats a fresh Medium task and loses to a fresh Critical task.
- `test_no_starvation_with_fresh_medium_stream`: a Low task that waited 2xN min is picked before newly added Medium tasks.
- `test_aging_minutes_config`: the template default is 30, `set_cfg` to 5 gives 5, and a config without the section gives 30.
- `test_dependency_blocked_critical_is_never_picked`: Critical T-002 in TODO depends on Medium T-001. Only T-001 is picked, and the reasons contain 'T-002 waits for T-001'.
- The existing `test_plan_steps_respects_sessions_and_busy` passes unchanged.

**Code:**
- scheduler.py: `STAGE_RANK` replaces `STAGE_PRIORITY` (grep for other users first), plus new `effective_priority`, `waiting_since` and `_sort_key`. `plan_steps(..., aging_minutes=30)` collects candidates, sorts them, then calls `take`. `next_step` passes `aging_minutes` through.
- config.py: `Config.aging_minutes = 30`, a `[scheduling]` block in DEFAULT_CONFIG, and `load_config` reading `max(0, int(...))`.
- pipeline.py: `step` and `dispatch` pass `self.cfg.aging_minutes`.

### Step 3: Unblock-count tiebreak and priority-aware file_conflict
**Files:** scheduler.py.

**Tests:**
- `test_unblock_count_breaks_ties`: T-001 and T-002 are Medium DEV tasks. T-003 (TODO) depends on T-002, and T-004 (TODO) depends on T-003. With dev slots 1, T-002 is picked.
- `test_downstream_count_is_transitive_and_skips_done`: the count follows the chain, skips DONE tasks, and is cycle-safe.
- `test_file_conflict_higher_priority_wins_before_coding`: T-001 low and T-002 critical, both DEV with no worktree and `files=['sportscut/cli.py']`. T-002 is runnable, and T-001 waits for T-002.
- `test_file_conflict_coding_task_still_goes_first`: the same setup, but T-001 has a worktree, so T-002 waits.

**Code:**
- New `downstream_count(store, task_id)`.
- `file_conflict(store, task, now=None, aging_minutes=30)`: replace `u.id < task.id` with `(eff(u), u.id) < (eff(task), task.id)`. With `now` None, use the base rank.
- `task_runnable` passes `now` and `aging_minutes` through.

### Step 4: Reprioritise command and dashboard control
**Files:** pipeline.py, cli.py, dashboard/server.py, dashboard/static/app.js.

**Tests:**
- `test_set_priority_request_updates_unfinished_tasks`: a DONE task keeps its level. The `priority_changed` event has id, level, frm and tasks. No history entry is added.
- `test_priority_command_cli_and_inbox`: `office priority T-001 critical` returns 0. An unknown id gives 'priority failed: …'. A bad level gives argparse exit 2.
- `test_reprioritise_in_flight_keeps_step_and_applies_next_dispatch`:
  1. Three Low DEV tasks.
  2. Set `office.inflight['T-001'] = 'dev'`.
  3. Run `office.store.append_inbox({'cmd': 'priority', 'id': 'T-003', 'level': 'critical'})`.
  4. Call `office.dispatch(RecordingPool())`. RecordingPool's submit records the step and returns an unfinished `concurrent.futures.Future`.
  5. Check: T-001's inflight entry and stage are unchanged, no cancel or crash event is emitted, and the step started is T-003, not T-002.
- `test_priority_api`: POST /api/priority `{'id', 'level'}` returns 200, and an invalid level returns 400. app.js contains '/api/priority'. The test uses `importorskip('fastapi')`.

**Code:**
- `Office.set_priority(target_id, level) -> list[str]`: raises ValueError for a bad level and KeyError for an unknown id, saves state, and emits the event.
- The drain_inbox 'priority' branch returns `'<id> priority <level> (<n> task(s))'`.
- `cmd_priority` plus a `priority` subparser (id, level with `choices=PRIORITIES`).
- server.py: `PriorityBody` plus POST /api/priority, which uses submit.
- app.js: a `select[data-priority-id]` on task cards and request rows. On change it calls `api('/api/priority', {id, level})`.

### Step 5: Concurrency and failure tests
**Files:** tests only. Production code changes only if a test fails.

**Tests:**
- `test_blocked_task_does_not_stop_independent_task`: Critical T-001 is BLOCKED with a reason starting with `BUSINESS_MARK`, so triage keeps it with the PO. Independent Low T-002 is in TODO. After `env.run_all(office)`, T-002 is DONE and T-001 is still BLOCKED.
- `test_no_duplicate_assignment_and_peak_within_parallel`:
  - Use `auto_env`, a scripted `claude_breakdown` with 3 independent tasks, then set the priorities critical, low and medium.
  - Wrap `office._execute` with a guard. The guard uses its own `threading.Lock` and a set of running targets, and records an error if a target starts while it is already running.
  - Run `peak = run_parallel(env, office)`.
  - Assert: no duplicates, `peak[r] <= office.cfg.parallel[r]` for every role, all tasks DONE, and no `step_crashed`.
- Then run the whole suite.

End the plan with `## Owner follow-up (by hand)`. The office `test_cmd` covers only `tests/`, so the owner must add `python -m pytest -q agent-office/tests` to their own check (pre-push or CI) and to README. After that comes `## Assumptions`: the file names above; no cross-request dependencies today, so priority inheritance is YAGNI; names marked (new) do not exist yet.

## Assumptions
- The two file names are fixed by the Tech Lead.
- New names proposed in the files (`PRIORITIES`, `check_priority`, `effective_priority`, `waiting_since`, `downstream_count`, `STAGE_RANK`, `set_priority`, `cmd_priority`, `RequestBody`, `PriorityBody`, `aging_minutes`) must be marked **(new)**, so the grep check applies only to existing names.
- The citation ranges above were checked on main 9ec129b.
- The product suite `python -m pytest -q tests` is unaffected because no code changes.

## Test plan

- Tester check by commands only (no test files committed): `git diff --name-status main...HEAD` shows exactly two A lines for the two target paths (AC1).
- `grep -n '^## [1-5]\.' docs/superpowers/specs/2026-11-23-r-009-priority-scheduling-design.md` prints five headings in order 1-5 (AC2).
- For each name in [plan_steps, file_conflict, task_runnable, deps_done, assigned_agent, dispatch, free_slots, _run_inflight, drain_inbox, add_request, _add_tasks, _execute, submit, cmd_run, cmd_request, load_config, post_request, run_parallel, test_plan_steps_respects_sessions_and_busy] that appears in either file: `grep -rn "def $name" agent-office/` must find it. `grep -n 'STAGE_PRIORITY =' agent-office/agent_office/scheduler.py` must match line 16. Spot-check 5 cited ranges with `sed -n 'A,Bp'` (AC6).
- `grep -c '^### Step [1-5]' docs/superpowers/plans/2026-11-23-r-009-priority-scheduling.md` prints 5. Inside each step section, check for 'agent-office/tests/test_priority.py' and 'python -m pytest -q agent-office/tests' (AC7).
- `grep -c` for each of the 7 required test names plus test_plan_steps_respects_sessions_and_busy in the plan file is at least 1 (AC8).
- `grep -n` in the plan file for '--priority', 'office priority', '/api/priority', 'priority_changed' and 'app.js' finds each (AC9).
- `grep -n 'agent-office/tests' docs/superpowers/plans/2026-11-23-r-009-priority-scheduling.md` finds the owner follow-up section, which mentions README (AC10).
- Read sections 3-5 of the design and check the key order, the stage rank, the High cap with the default 30, the waiting clock and the three out-of-scope items (AC5).
- Run `python -m pytest -q tests` and quote its summary line (AC11).
