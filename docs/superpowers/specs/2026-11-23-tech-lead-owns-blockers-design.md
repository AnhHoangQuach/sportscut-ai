# Tech Lead owns every technical blocker; the PO is asked only about business

PO request (Hoang, 2026-11-23): "the PO only sends project requests; making sure work does not
block each other during delivery is the job of the PM and Tech Lead, not a question for the PO.
Ask only when the business is unclear."

## Goal and how we know it is reached

- No code path moves a task or request to `blocked` (waiting for the PO) for a technical reason.
  `blocked` means one thing: a business question the Tech Lead could not answer.
- Every former escalation is handled by Claude as Tech Lead, decided and logged in `DECISIONS.md`.
- Parallel tasks that change the same files do not run at the same time.
- Measured by the fake-agent suite: `cd agent-office && python -m pytest -q`
  (`tests/test_techlead.py` + updated tests in `test_pipeline.py`, `test_environment.py`,
  `test_parallel.py`, `test_autonomy.py`, `test_dashboard.py`).

## Audit: where the office used to ask the PO

| Where | Trigger | Now (`tl_kind`) |
|---|---|---|
| breakdown / goal check | questions, unreadable output | request-level Tech Lead (`questions`, `parse_error`) |
| spec | questions, unreadable output | `questions`, `parse_error` |
| dev | `BLOCKED:` answer | `dev_blocked` (or `missing_dependency` after `dep_retries`) |
| dev | `git merge` failed, conflict markers left | `git_error`, `merge_conflict` |
| dev | guardrail: secret / protected path / diff size | `secret`, `protected_paths`, `diff_size` |
| test | still failing after `MAX_TEST_ATTEMPTS` | `tests_failing` |
| review | unreadable, not approved after `MAX_REVIEW_ROUNDS` | `parse_error`, `review_rejected` |
| pr | conflicts after `MAX_CONFLICT_ROUNDS`, merge failed | `merge_conflict`, `merge_failed` |
| goal check | more than `max_goal_rounds` | close the request with a report (no question) |

Unchanged: quota limits and `max_calls_per_day` (the agent rests, then resumes), `merge_mode =
"manual"` (the PO chose to merge PRs).

## Approaches considered

1. Keep `blocked`, add an "auto-answer" that sends a canned reply. Rejected: no judgement, loops.
2. A new `techlead` stage in the state machine. Rejected: every UI, sim and transition table
   would change for something that is a property of a stuck task, not a stage.
3. **Chosen:** a technical blocker marks the task (`tl_issue`, `tl_kind`) where it is; the scheduler
   gives it a `techlead` step first. Claude classifies (business vs technical) and returns one
   action: `retry` (with guidance, optional new spec/ACs/files), `restart` (fresh branch from the
   base, optional `after`), `split`, `wait` (minutes), `drop`; or `business_questions` for the PO.

## Decisions

- Guardrails are fixed, never waived. A secret forces `restart` and deletes the branch, so the
  secret never reaches git history; guardrails are re-checked after every dev run.
- `[office] tech_lead_rounds = 3` per task. Out of rounds: the task is dropped (not merged), the PO
  gets a report (not a question), and the goal check re-plans what is missing. Requests cannot be
  dropped: out of rounds they pause 60 minutes and try again.
- The goal-check cap closes the request with what is merged plus a report of what is left.
- Specs list `files`; the scheduler keeps a task that has not started coding in `dev` while another
  active task (already coding, or a lower id) changes an overlapping file. `INDEX.md` and
  `DECISIONS.md` (merge=union) never count. The breakdown prompt makes such tasks depend on each other.
- Tech Lead decisions land in `task.decisions` / `req.decisions` and are appended (missing lines
  only) to `docs/superpowers/DECISIONS.md` on the next commit; decisions made before a spec is
  written survive the spec.

## Out of scope

- Reading file lists from the breakdown (only the spec declares `files`).
- Changing the 3D office scene (it already shows `blocked` as "PO must answer", now correct).

Updated 2026-11-23 (re-triage): blocks saved before the Tech Lead existed are re-classified on office start and by `office triage`; only blocks marked `business question for the PO` keep waiting for the PO.
