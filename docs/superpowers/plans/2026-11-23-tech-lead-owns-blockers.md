# Plan: Tech Lead owns every technical blocker

Design: `specs/2026-11-23-tech-lead-owns-blockers-design.md`.

1. `models.py`: Task gets `files`, `tl_issue`, `tl_kind`, `tl_rounds`, `tl_guidance`, `tl_notes`,
   `retry_at`, `attempt`, `dropped`, and `reroute()` (Tech Lead override to todo/spec/dev/done).
   Request gets `tl_issue`, `tl_kind`, `tl_rounds`, `tl_questions`, `tl_notes`, `decisions`, `retry_at`.
2. `config.py`: `[office] tech_lead_rounds = 3`; comments for `dep_retries` / `max_diff_lines`.
3. `scheduler.py`: `techlead` steps first; `retry_at` waits (and feeds `wait_until`);
   `file_conflict()` ordering for `dev` tasks without a worktree.
4. `pipeline.py`: `_escalate` / `_escalate_request` replace every technical `_block`;
   `_tech_lead`, `_tech_lead_request`, `_retire`, `_reroute`; TL guidance in the dev prompt
   (`TECH LEAD DECISION`) and `TASK.md`; TL notes in spec/breakdown prompts; goal cap closes with a report.
5. `worktree.py`: `task_branch(attempt)`, `discard_branch()`.
6. `specdocs.py`: append missing decision lines (task + request) instead of once per task.
7. Prompts: new `tech_lead.md`; `pm_breakdown` / `pm_spec` / `pm_goal` ask only business questions,
   `pm_spec` returns `files`, breakdown orders same-file tasks; `dev.md` says the Tech Lead reads `BLOCKED:`.
8. Sim agent + fake agent answer the Tech Lead prompt; dashboard badges/events; CLI status.
9. Team rules (`AGENTS.md`, `CLAUDE.md` + templates) and `docs/` (01 §1.10, 02, 06, 09, README).

## Test plan

- `tests/test_techlead.py`: technical spec/breakdown questions answered by the Tech Lead; failing
  tests get a new approach; split rewires dependents; restart with `after` cuts `office/T-xxx-r2`;
  wait pauses; unreadable TL answers then drop + report; request-level pause; goal cap report;
  file-overlap ordering; spec `files` recorded; prompts and config defaults.
- Updated: review loop, protected paths, secret (branch deleted, not in `git log --all`),
  dependency retries, business blocker via Tech Lead, PO questions in autonomy/dashboard tests.
- Verify: `cd agent-office && python -m pytest -q`.
