# R-009: Priority scheduling implementation plan

**Goal:** Make every free Agent Office session select the highest-value ready step using explicit priority, aging, dependency impact, and deterministic stage/id tiebreaks, while preserving current parallelism and isolation.

**Architecture:** Keep the existing event-driven dispatch loop. Derive all ready candidates from persistent state on every dispatch, sort them with one pure key, then apply the existing busy and per-role slot limits. Persist priority on requests and tasks; apply reprioritisation only to future dispatch decisions.

**Tech Stack:** Python 3.11 dataclasses, argparse, TOML configuration, FastAPI/Pydantic dashboard API, vanilla JavaScript, pytest, and the existing fake subscription CLIs.

The owner implements this plan by hand. Agents never edit `agent-office/`, which is a protected path.

Use one test helper in `agent-office/tests/test_priority.py`: `make_tasks(office, items)` **(new)** calls `office.add_request`, sets `req.status = 'planned'`, calls `office._add_tasks`, then applies each item's stage, priority, `depends_on`, history, and `created_at`. This follows `test_plan_steps_keeps_normal_roles_when_both_agents_have_quota` in `agent-office/tests/test_parallel.py:61-70`. Aging tests explicitly set `history=[{'at': (env.now - timedelta(minutes=M)).isoformat(), ...}]`, because `now_iso` uses wall time while `Env.now` is fixed (`agent-office/agent_office/models.py:10-11`; `agent-office/tests/conftest.py:19-72`). Tests use the `auto_env`/`Env` helpers and fake CLIs from `agent-office/tests/conftest.py:19-82` and `fake_agent.py:17-34,61-63`, and import `run_parallel`/`set_cfg` from `agent-office/tests/test_parallel.py:15-40`.

## Tests

| Step | Tests written first in `agent-office/tests/test_priority.py` |
|---|---|
| 1 | `test_priority_defaults_to_medium_and_old_state_loads`; `test_request_priority_is_inherited_by_tasks`; `test_invalid_priority_is_rejected`; `test_cli_and_dashboard_set_request_priority` |
| 2 | `test_priority_orders_critical_before_low`; `test_aging_raises_low_to_high_never_critical`; `test_no_starvation_with_fresh_medium_stream`; `test_aging_minutes_config`; `test_dependency_blocked_critical_is_never_picked`; existing `test_plan_steps_respects_sessions_and_busy` passes unchanged |
| 3 | `test_unblock_count_breaks_ties`; `test_downstream_count_is_transitive_and_skips_done`; `test_file_conflict_higher_priority_wins_before_coding`; `test_file_conflict_coding_task_still_goes_first` |
| 4 | `test_set_priority_request_updates_unfinished_tasks`; `test_priority_command_cli_and_inbox`; `test_reprioritise_in_flight_keeps_step_and_applies_next_dispatch`; `test_priority_api` |
| 5 | `test_blocked_task_does_not_stop_independent_task`; `test_no_duplicate_assignment_and_peak_within_parallel` |

### Step 1: Priority field, persistence, and input

**Files:** `agent-office/agent_office/models.py`, `agent-office/agent_office/pipeline.py`, `agent-office/agent_office/cli.py`, `agent-office/agent_office/dashboard/server.py`, `agent-office/agent_office/dashboard/static/index.html`, `agent-office/agent_office/dashboard/static/app.js`, and `agent-office/tests/test_priority.py` **(new)**.

**Failing test first:** Add the four Step 1 tests to `agent-office/tests/test_priority.py`. `test_priority_defaults_to_medium_and_old_state_loads` saves request/task state, deletes both `priority` keys from `state.json`, and asserts `Store(repo).load()` restores `medium`. `test_request_priority_is_inherited_by_tasks` calls `add_request('x', 'critical')`, then `_add_tasks`, and expects Critical tasks. `test_invalid_priority_is_rejected` expects `add_request('x', 'urgent')` to raise `ValueError`, `office request --priority urgent x` to raise `SystemExit(2)`, and an invalid request inbox command to report `request failed: …` without adding a request. `test_cli_and_dashboard_set_request_priority` expects `office request --priority high Cut` to create a High R-001; POST `/api/requests` with `{'text': 'Cut', 'priority': 'low'}` to create Low; and invalid priority to return 400, guarded by `pytest.importorskip('fastapi')`. First run should fail because models, method signatures, CLI option, and request body do not yet expose priority.

**Minimal code:** Add `PRIORITIES` **(new)** and `check_priority(level) -> str` **(new)** to models; normalize by stripping/lowercasing and raise `ValueError` that names the valid levels. Add `priority='medium'` to `Task` and `Request`. Change `Office.add_request` (`agent-office/agent_office/pipeline.py:249-256`) to `add_request(text, priority='medium')`, pass `req.priority` from `_add_tasks` (`pipeline.py:542-562`), and make the request branch of `drain_inbox` (`pipeline.py:174-199`) read `c.get('priority', 'medium')`. Add `--priority` with `choices=PRIORITIES`, `type=str.lower`, default Medium to `cmd_request` and its parser (`agent-office/agent_office/cli.py:67-75,398-401`). Replace `TextBody` for requests with `RequestBody` **(new)** carrying `text` and `priority='medium'` in `post_request` (`agent-office/agent_office/dashboard/server.py:36-37,127-131`). Add `select#request-priority` to index.html; send its value and render priority badges in request rows/cards in `app.js` (`renderRequests` 195-207, `renderBoard` 209-235, submit 393-405).

**Verify:** `python -m pytest -q agent-office/tests`

### Step 2: Ordering key and aging

**Files:** `agent-office/agent_office/scheduler.py`, `agent-office/agent_office/config.py`, `agent-office/agent_office/pipeline.py`, and `agent-office/tests/test_priority.py`.

**Failing test first:** Add the five Step 2 tests. `test_priority_orders_critical_before_low` creates Low T-001 and Critical T-002 at DEV with dev x1 and expects both `plan_steps` and `next_step` to choose T-002. `test_aging_raises_low_to_high_never_critical` checks Low at 0/29/30/59/60/600 minutes gives 3/3/2/2/1/1, Critical always gives 0, Medium at 30 gives 1, and `aging_minutes=0` leaves Low at 3; in a plan, a 60-minute Low beats fresh Medium but loses to fresh Critical. `test_no_starvation_with_fresh_medium_stream` expects a Low waiting `2*N` minutes to beat newly added Medium candidates. `test_aging_minutes_config` checks the template default is 30, `set_cfg` changes it to 5, and absence of `[scheduling]` still gives 30. `test_dependency_blocked_critical_is_never_picked` makes Critical TODO T-002 depend on Medium T-001 and expects only T-001 plus a `T-002 waits for T-001` reason. Also run existing `test_plan_steps_respects_sessions_and_busy` unchanged (`agent-office/tests/test_parallel.py:43-58`). Initial failures should show current id/stage loop ordering and missing aging/config APIs, while the dependency assertion protects current gating.

**Minimal code:** Grep for all `STAGE_PRIORITY` users, then replace it with `STAGE_RANK` **(new)** and add `effective_priority`, `waiting_since`, and `_sort_key` **(new)**. Change `plan_steps` (`agent-office/agent_office/scheduler.py:142-245`) to collect ready candidates before sorting and calling `take`, with `aging_minutes=30`; preserve wake-first behavior and non-blocking per-role capacity. Thread `aging_minutes` through `next_step` (`scheduler.py:248-249`). Add `[scheduling] aging_minutes = 30` to `DEFAULT_CONFIG`, `Config.aging_minutes = 30`, and `load_config` reading `max(0, int(...))` (`agent-office/agent_office/config.py:83-90,125-152,184-220`). Have `Office.step` and `Office.dispatch` pass `self.cfg.aging_minutes` (`agent-office/agent_office/pipeline.py:259-296`).

**Verify:** `python -m pytest -q agent-office/tests`

### Step 3: Unblock-count tiebreak and priority-aware file conflicts

**Files:** `agent-office/agent_office/scheduler.py` and `agent-office/tests/test_priority.py`.

**Failing test first:** Add the four Step 3 tests. `test_unblock_count_breaks_ties` makes Medium DEV T-001/T-002, TODO T-003 depend on T-002, and TODO T-004 depend on T-003; dev x1 must choose T-002. `test_downstream_count_is_transitive_and_skips_done` verifies the chain, excludes DONE dependants, and terminates on cycles. `test_file_conflict_higher_priority_wins_before_coding` gives Low T-001 and Critical T-002 the same `sportscut/cli.py` file with no worktrees: T-002 runs and T-001 waits. `test_file_conflict_coding_task_still_goes_first` gives T-001 a worktree and expects T-002 to wait despite priority. Initial failures should show no downstream API and lower-id conflict precedence.

**Minimal code:** Add `downstream_count(store, task_id)` **(new)** using reverse dependency traversal, a visited set, and only distinct non-DONE dependants. Extend `file_conflict(store, task, now=None, aging_minutes=30)` (`agent-office/agent_office/scheduler.py:103-119`): keep an existing-worktree task first; otherwise replace lower-id precedence with `(effective_priority, id)`. With `now=None`, compare base ranks. Extend `task_runnable` (`scheduler.py:122-139`) to pass `now` and `aging_minutes` through. Include the count in the common candidate key.

**Verify:** `python -m pytest -q agent-office/tests`

### Step 4: Reprioritise command and dashboard control

**Files:** `agent-office/agent_office/pipeline.py`, `agent-office/agent_office/cli.py`, `agent-office/agent_office/dashboard/server.py`, `agent-office/agent_office/dashboard/static/app.js`, and `agent-office/tests/test_priority.py`.

**Failing test first:** Add the four Step 4 tests. `test_set_priority_request_updates_unfinished_tasks` verifies an R-id updates its request and unfinished tasks, leaves a DONE task unchanged, emits `priority_changed` with `id`, `level`, `frm`, and `tasks`, and adds no history entry. `test_priority_command_cli_and_inbox` expects `office priority T-001 critical` to return 0, unknown ids to report `priority failed: …`, and argparse to reject a bad level with exit 2. `test_reprioritise_in_flight_keeps_step_and_applies_next_dispatch` creates three Low DEV tasks, sets `office.inflight['T-001']='dev'`, appends `{'cmd':'priority','id':'T-003','level':'critical'}`, and dispatches through a `RecordingPool` whose `submit` records the step and returns an unfinished `concurrent.futures.Future`; T-001's inflight entry/stage must be unchanged, no cancel or crash event occurs, and T-003 starts instead of T-002. `test_priority_api`, guarded by `importorskip('fastapi')`, expects POST `/api/priority` to accept a valid body, reject invalid level with 400, and `app.js` to contain `/api/priority`. Initial failures should show no setter, command, inbox branch, or endpoint.

**Minimal code:** Add `Office.set_priority(target_id, level) -> list[str]` **(new)**: validate levels, raise `KeyError` for unknown ids, update one T-id or an R-id plus only its unfinished tasks, persist, emit `priority_changed`, and do not modify history or inflight. New tasks continue inheriting request priority. Add a `priority` branch to `drain_inbox` (`agent-office/agent_office/pipeline.py:174-199`) returning `<id> priority <level> (<n> task(s))`. Add `cmd_priority` **(new)** and a `priority` subparser with id and `choices=PRIORITIES` level in cli.py. Add `PriorityBody` **(new)** and POST `/api/priority` in server.py, submitting the inbox command and mapping validation errors to 400. In `app.js`, render `select[data-priority-id]` on task cards and request rows; on change call `api('/api/priority', {id, level})`. An `R-xxx` change updates only unfinished tasks, and every priority change affects only the next dispatch.

**Verify:** `python -m pytest -q agent-office/tests`

### Step 5: Concurrency and failure isolation

**Files:** `agent-office/tests/test_priority.py` only. Production code changes only if one of these tests exposes a defect.

**Failing test first:** Add `test_blocked_task_does_not_stop_independent_task`: Critical T-001 is BLOCKED with a reason beginning with `BUSINESS_MARK`, independent Low T-002 is TODO, and after `env.run_all(office)`, T-002 is DONE while T-001 remains BLOCKED. Add `test_no_duplicate_assignment_and_peak_within_parallel`: using `auto_env`, script `claude_breakdown` for three independent tasks and assign Critical, Low, and Medium. Wrap `office._execute` with a guard holding its own `threading.Lock`, track running targets in a set, and record a duplicate if one starts twice. Run `peak = run_parallel(env, office)`. Assert no duplicates; `peak[role] <= office.cfg.parallel[role]` for every role; all tasks are DONE; and no `step_crashed` event exists. Before production fixes, deliberately confirm each new guard can fail—for example, temporarily make its assertion stricter or invoke the guarded duplicate path—then restore the acceptance assertion. These tests should pass without production changes if Steps 1-4 preserved isolation and concurrency; any real failure must be fixed at its root cause.

**Minimal code:** None expected. If a test fails, make only the smallest production correction required by the acceptance behavior; never weaken either test. Run the entire Agent Office suite, including unchanged `test_plan_steps_respects_sessions_and_busy`.

**Verify:** `python -m pytest -q agent-office/tests`

## Owner follow-up (by hand)

The office `test_cmd` covers only `tests/`; it does not run the orchestrator's own suite. The owner must add `python -m pytest -q agent-office/tests` to their own check (pre-push or CI) and document that command in README.

## Assumptions

- The file names in every step are the current paths listed above.
- No cross-request dependencies exist today, so cross-request priority inheritance is YAGNI.
- Proposed identifiers `PRIORITIES`, `check_priority`, `effective_priority`, `waiting_since`, `downstream_count`, `STAGE_RANK`, `set_priority`, `cmd_priority`, `RequestBody`, `PriorityBody`, `aging_minutes`, and `make_tasks` are **(new)** and do not exist yet. Every unmarked cited identifier already exists.
