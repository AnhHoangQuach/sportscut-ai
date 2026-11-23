# Plan T-037: Retry the waiting T-035 PR and merge now that gh is fixed

Design: `docs/superpowers/specs/2026-11-23-t-037-retry-the-waiting-t-035-pr-design.md`.

## Implementation plan

# T-037 (R-008): Record the GitHub retry for T-035 now that gh is fixed

## Context (2026-11-23)
- The PO fixed the GitHub CLI and asked for a retry. The office ran `office retry-github`. T-035 merged as 30227a6 (PR #12), and T-036 then ran and merged as f650dcd (PR #14).
- The first T-037 attempt was based on d03a2e0, which had no tests/, so the office test_cmd `python -m pytest -q tests` exited 4. This attempt starts from the latest main, which has tests/.

## Design
This is a doc-only task. The office performs the operational retry (`Office.retry_github`, `agent-office/agent_office/pipeline.py`) with the user's gh credentials. Agent sandboxes have no GitHub credentials or network (decision 2026-11-23), so the developer only writes the plan file that records the steps, the verification and the observed outcome.

## Files
- CREATE `docs/superpowers/plans/2026-11-23-r-008-github-retry.md`. No other file is touched by the developer.
- Do NOT touch `docs/superpowers/INDEX.md` or `docs/superpowers/DECISIONS.md` (orchestrator-only, union merge), `sportscut/`, `tests/`, `pyproject.toml` or `agent-office/` (protected).

## Plan file sections
1. Title `# R-008: Retry GitHub PR/merge for T-035 after the gh fix`, `Date: 2026-11-23`, `Request: PO 2026-11-23 "đã fix lỗi github cli thử lại xem"`.
2. `## Why no code changes`.
3. `## Steps (run by the office / on the PO's machine)`: office doctor, office retry-github, office status (pr_url), git log/ls-tree on origin/main, T-035 done and T-036 out of todo.
4. `## Outcome (observed 2026-11-23)`: 30227a6 (PR #12), f650dcd (PR #14).
5. `## If the preflight still fails`: blocked, "environment problem for the user", fix hint to the PO, never sent to the Tech Lead, nothing waived, re-checked every 5 minutes.
6. `## Related`: ../specs/2026-11-23-github-pr-environment-design.md, ../specs/2026-11-23-rest-reasons-design.md.

## Assumptions
- The branch starts from main f650dcd, which contains tests/ from T-035/T-036, so `python -m pytest -q tests` runs the existing suite. This task adds no tests because it changes no behaviour.
- The PR repository is pinned to `AnhHoangQuach/sportscut-ai` with `-R`.

## Test plan

- No new automated tests: the task is docs-only. The behaviour it uses is already covered by `agent-office/tests/test_github.py::test_retry_github_runs_waiting_prs_now_once_github_is_fixed` (the agent must not edit `agent-office/`).
- Verify the file with the AC1, AC2 and AC4 shell commands, and the scope with `git diff --name-only main` (AC3).
- Run `python -m pytest -q` in the worktree. It is expected to pass or report "no tests ran" (exit 5) because `main` has no `tests/` yet. Quote the summary line.
- Operational check (office, not agent): `office doctor`, then `office retry-github`, then `office status`, then `git log origin/main --oneline -5`, as listed in the plan file.
