# T-037: Retry the waiting T-035 PR and merge now that gh is fixed

Request R-008. Request design: `docs/superpowers/specs/2026-11-23-r-008-fix-l-i-github-cli-th-design.md`. Plan: `docs/superpowers/plans/2026-11-23-t-037-retry-the-waiting-t-035-pr.md`.

## Product Owner request

đã fix lỗi github cli thử lại xem

## Goal

No product or orchestrator code changes. The office runs `office retry-github`, which runs the GitHub preflight (gh login, push permission via `-R AnhHoangQuach/sportscut-ai`, network). If the preflight passes, it clears T-035's Tech Lead wait so the approved, pushed `office/T-035` branch goes straight to PR creation and auto-merge. Do not reimplement T-035, rebase it or merge main into it. The developer's only change is a new plan file, `docs/superpowers/plans/2026-11-23-r-008-github-retry.md`, which lists these verification steps: `office retry-github` output; T-035 gets a `pr_url`, the merged PR appears on `main`, T-035 reaches `done`; T-036 moves out of `todo`. The task does not touch `INDEX.md` or `DECISIONS.md`, because T-035's branch edits both and that would cause a merge conflict. Assumptions: agent sandboxes have no GitHub credentials, so only the office performs the retry (decision 2026-11-23). If the preflight still reports a problem, T-035 stays blocked as an environment problem for the user and the fix hint is reported. It is never sent to the Tech Lead and nothing is waived.

## Acceptance criteria

- AC1: `test -f docs/superpowers/plans/2026-11-23-r-008-github-retry.md` succeeds.
- AC2: `grep -c 'office retry-github' docs/superpowers/plans/2026-11-23-r-008-github-retry.md` prints at least 1, and the file contains `pr_url`, `T-036`, `done`, `environment problem for the user`, `30227a6` and `f650dcd`.
- AC3: `git diff --name-only main...HEAD` lists only `docs/superpowers/plans/2026-11-23-r-008-github-retry.md`, the orchestrator's T-037/R-008 spec and plan files, and `docs/superpowers/INDEX.md` / `docs/superpowers/DECISIONS.md`. For those two files, `git diff --numstat main...HEAD` shows 0 deleted lines. `git diff --name-only main...HEAD -- sportscut tests pyproject.toml agent-office` prints nothing.
- AC4: `grep -nE '(ghp_|gho_|github_pat_|@gmail\.com)' docs/superpowers/plans/2026-11-23-r-008-github-retry.md` finds nothing (exit 1).
- AC5: `python -m pytest -q tests` exits 0 on this branch (the existing T-035/T-036 suite; ffmpeg-dependent tests may skip), and `git diff --check` is clean.
- AC6 (already observed): T-035 is `done` with its merge 30227a6 (PR #12) on main, and T-036 left `todo` and merged as f650dcd (PR #14).

## Out of scope

- Reimplementing, rebasing or merging `main` into `office/T-035`.
- Any change to `agent-office/` (protected path), `sportscut/`, `tests/` or `pyproject.toml`.
- Editing `docs/superpowers/INDEX.md` or `DECISIONS.md` (would conflict with T-035's branch).
- Running `gh`, `git push` or `office` commands from the agent sandbox.
- Starting or implementing T-036.
- Adding a placeholder test so pytest collects something on `main`.

## Decisions

- R-008 is an operational retry with the existing `office retry-github`. No product or orchestrator code changes.
- Only the office (on the user's machine with the user's gh credentials) pushes, opens and merges PRs. Agent sandboxes never touch GitHub (reaffirms decision 2026-11-23).
- A failing preflight keeps T-035 blocked as an environment problem for the user with the fix hint. It is never sent to the Tech Lead, and no guardrail is waived.
- Doc-only tasks must not touch INDEX.md or DECISIONS.md while another open branch appends to them. The orchestrator records index and decision entries after T-035 merges.
- Tech Lead (dev_blocked): 2026-11-23 T-037 (R-008): AC3 failed by mistake, not because of the developer's work. While T-037 was in dev, T-035 merged to main as 30227a6 (PR #12), so `git diff --name-only main` (two-dot, against the moved main) showed T-035's INDEX/DECISIONS lines as removed. The only T-037 change to those files is lines the orchestrator appended itself (T-037 spec/plan records, union merge driver, no deletions). AC3 now uses the merge base (`main...HEAD`) and allows those appended lines; the plan file already meets AC1/AC2/AC4, so retry with verification only and no file changes.
- Tech Lead (tests_failing): 2026-11-23 T-037 (R-008): restart from the latest main (f650dcd), because the test stage fails for an environment reason, not because of the work. The office test_cmd `python -m pytest -q tests` exits 4 ('file or directory not found: tests'): the T-037 worktree is based on d03a2e0, from before any product code existed, and `tests/` only reached main with T-035 (30227a6, PR #12) and T-036 (f650dcd, PR #14). A retry on the same base fails the same way, and the developer may not merge main. A fresh branch from main contains tests/, so test_cmd runs the real T-035/T-036 suite. The deliverable stays doc-only. AC5 is already met: T-035 and T-036 are both done and on main.

## Existing specs this task changes

- (none)
