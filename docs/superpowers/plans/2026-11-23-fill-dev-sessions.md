# Plan: fill every Developer session

Design: `docs/superpowers/specs/2026-11-23-fill-dev-sessions-design.md`.

1. Tests first: `agent-office/tests/test_techlead.py` (file_conflict only while coding),
   `test_practices.py` (breakdown prompt), `test_parallel.py` (`slots_idle`), `test_dashboard.py`
   (complete waiting list). Run them and see all four fail.
2. `agent-office/agent_office/scheduler.py`: `_coding()` + `file_conflict` uses it.
3. `agent-office/agent_office/prompts/pm_breakdown.md`: dependency rule.
4. `agent-office/agent_office/pipeline.py`: `_idle_seen`, `_report_idle()` called from `dispatch`.
5. `agent-office/agent_office/dashboard/server.py`: `plan_steps(busy, slots)` instead of `next_step`.
6. Docs 01 and 02.2, DECISIONS.md, INDEX.md.
7. Verify: `python -m pytest -q agent-office/tests` and `python -m pytest -q tests`.
