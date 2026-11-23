# GitHub PR / merge: environment problems are reported, not waited on

Date: 2026-11-23  
Request: PO (Hoang) 2026-11-23: the office could not open/merge PRs; the Tech Lead decided "wait
60 minutes ... GitHub CLI authentication lacks valid collaborator access and network resolution is
currently unavailable".

## Root cause

- `git push` and `gh pr create/merge` already run in the office process (`agent_office/worktree.py`)
  with the user's environment, but every failure went to the Tech Lead as `merge_failed`.
- The Tech Lead (`claude -p`) runs in a read-only sandbox without network or GitHub credentials.
  Its own `gh`/DNS checks fail there, so it diagnosed its sandbox, not the office, and could only
  choose `wait`. A login/permission problem never fixes itself, so the wait repeated.
- `gh` picked the repository from the checkout; with a fork or several remotes it can target a repo
  the account cannot write.

## Design

- New `agent_office/github.py`: `run_gh` (office env + `GH_PROMPT_DISABLED`), `repo_slug` from the
  remote URL, `classify(error)` -> auth | permission | network | other, `preflight()` (gh on PATH,
  github.com remote, TCP to api.github.com:443, `gh api user`, REST `repos/{owner}/{repo}` permissions) with
  Vietnamese fix hints.
- `worktree.py`: every `gh pr create/view` gets `-R owner/repo`; all `gh` calls go through `run_gh`.
- `pipeline._pr` failure -> `_github_failed`: auth/permission -> preflight, block with
  `ENV_MARK` ("environment problem for the user"), message the PO with the fix; network -> retry
  after 2/5/10/15 min (`Task.net_retries`), then report the same way; other -> Tech Lead.
- `recheck_environment()` (every step, throttled to 5 min): when the preflight passes, env-blocked
  tasks go back to `pr`. `triage` leaves env blocks alone.
- `office doctor` shows the GitHub preflight; failures fail the doctor when `open_pr = true`.
- Tech Lead prompt: its sandbox says nothing about GitHub access; `wait` is not for login/permission.

## Files

- `agent-office/agent_office/github.py`, `worktree.py`, `pipeline.py`, `models.py`, `cli.py`,
  `prompts/tech_lead.md`
- `agent-office/tests/test_github.py`
- `docs/09-van-hanh.md`, `docs/superpowers/{INDEX.md,DECISIONS.md}`, this spec and its plan

## Acceptance criteria

- A permission/auth failure blocks the task with the fix, sends no Tech Lead step, survives `triage`,
  and resumes to `pr` by itself after the preflight passes (rechecked at most every 5 minutes).
- Network failures back off 2/5/10/15 min, then are reported; other failures still reach the Tech Lead.
- `gh pr create` is called with `-R <owner>/<repo>` of the github.com remote.
- `office doctor` prints the failing GitHub check with a `->` fix line and exits 1.
- Updates `specs/2026-11-23-tech-lead-owns-blockers-design.md` in one point: `blocked` can now also
  mean "environment problem for the user" (GitHub access), besides business questions.
