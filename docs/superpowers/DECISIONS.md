# Decision log

Newest last. Format: date, task (request): decision.

- 2026-11-22 PO (Hoang): first sport is football; other sports come later
- 2026-11-22 PO (Hoang): no API keys; agents run on subscription CLIs (`claude -p`, `codex exec`)
- 2026-11-22 PO (Hoang): agents work autonomously and auto-merge after approval + green tests; ask the PO only when a requirement is unclear
- 2026-11-23 PO (Hoang): accuracy is measured by `sportscut eval ... --json` (F1); a change must not lower F1
- 2026-11-23 PO (Hoang): a 90-minute match must process in under 10 minutes on a laptop CPU; vision/OCR models are optional extras and never run on every frame
- 2026-11-23 PO (Hoang): every request and task commits its design, plan and decisions under `docs/superpowers/`
- 2026-11-23 PO (Hoang): the PO only sends requests; PM + Tech Lead resolve every technical and coordination blocker; the PO is asked only when a business requirement is unclear (refines the 2026-11-22 "ask only when unclear" decision)
- 2026-11-23 Tech Lead: every former technical escalation goes to a `techlead` step (retry / restart / split / wait / drop, or business_questions for the PO); `blocked` now means only "business question for the PO"
- 2026-11-23 Tech Lead: guardrails are fixed, never waived; a secret in a diff discards (deletes) the branch and restarts from the base
- 2026-11-23 Tech Lead: `tech_lead_rounds = 3` per task, then the task is dropped with a report to the PO and the goal check re-plans; requests pause 60 min instead; the goal-check cap closes the request with a report
- 2026-11-23 Tech Lead: specs list `files`; tasks that change the same files never code at the same time (already-coding or lower id first)
- 2026-11-23 Tech Lead: on every office start (and `office triage`) tasks/requests blocked for the PO without the Tech Lead's business mark are handed back to the Tech Lead; an old goal-round-cap block closes the request with a report
- 2026-11-23 PO (R-007): if exactly one agent is quota-limited, the other agent may take over its work; if both are limited the office rests; if both are available the original role assignment remains unchanged
- 2026-11-23 R-007: failover is triggered only by quota or daily-budget rest, not by busy sessions or repeated CLI failures; the replacement receives permissions for the role being covered
- 2026-11-23 Tech Lead: GitHub login/permission failures (and network failures after 2/5/10/15 min retries) on push/PR/merge are an environment problem on the user's machine: the office blocks the task as "environment problem for the user" with the exact fix from a preflight, never hands it to the Tech Lead (whose sandbox has no network/credentials), and resumes by itself when the preflight passes; `gh` is pinned with `-R owner/repo` from the remote
- 2026-11-23 Tech Lead: a CLI run that exits 0 is never a usage limit, and a failed run is checked for limit phrases only in the last 2000 chars of stdout/stderr; repeated CLI failures rest as `failure` (never reported as quota) with the CLI's error line and log path; the sleep message lists every waiting reason
- 2026-11-23 Tech Lead: `office retry-github` is the PO's way to retry PR/merge immediately after fixing gh; it only acts when the GitHub preflight passes
- 2026-11-23 T-035 (R-001): T-035 is the package/model/CLI foundation split from the oversized T-001 attempt; T-036 owns all ffmpeg media work and depends on this task.
- 2026-11-23 T-035 (R-001): Use setuptools and dynamic package versioning with `sportscut.__version__` as the single source of version 0.1.0.
- 2026-11-23 T-035 (R-001): Keep NumPy as a runtime dependency in the foundation because dependent T-036 requires it for audio arrays; pytest is available only through the `dev` extra.
- 2026-11-23 T-035 (R-001): Configure root pytest with `testpaths = ['tests']` and `pythonpath = ['.']` so fresh worktrees import product code while excluding the separate `agent-office/tests` suite.
- 2026-11-23 T-035 (R-001): The console script and `python -m sportscut` share `sportscut.cli.main`; no-argument invocation prints help and succeeds.
- 2026-11-23 T-035 (R-001): `Segment` is a frozen dataclass; it validates only temporal bounds, permits unbounded scores, and converts output fields to native JSON-safe primitives in `to_dict()`.
- 2026-11-23 T-035 (R-001): Genuine red-before-green evidence must be preserved separately for CLI and model behavior; existing implementation from the discarded T-001 attempt must not be copied into the branch before those failing runs.
- 2026-11-23 T-035 (R-001): Offline verification uses a worktree-local gitignored virtual environment, `--no-build-isolation`, and `--no-index`; no files under the protected Agent Office project are modified.
- 2026-11-23 T-035 (R-001): Only concise task-specific design, plan, index, and decision records are added; persistent infrastructure already on the base is preserved rather than recreated.
- 2026-11-23 T-035 (R-001): Tech Lead (merge_failed): 2026-11-23 T-035: Wait 60 minutes before retrying PR creation because the approved branch is clean and pushed, but GitHub CLI authentication lacks valid collaborator access and network resolution is currently unavailable.
- 2026-11-23 T-035 (R-001): Tech Lead (git_error): 2026-11-23 T-035: restart from the latest main instead of retrying, because the merge failure is a loop in the office, not a code problem: on every dev step `_ensure_worktree` -> `specdocs.write_task_docs` appends new Tech Lead decision lines to docs/superpowers/DECISIONS.md without committing them, right before `wt.start_merge(main)`, so `git merge main` always aborts on that dirty file (and a retry would add this decision's line too). A fresh branch from main clears the merge flag. There is nothing to resolve by hand: DECISIONS.md and INDEX.md use the union merge driver. The old office/T-035 branch is kept only as a reference.
- 2026-11-23 R-001: Tech Lead: T-001 'Scaffold the sportscut package with an ffmpeg media layer and synthetic test fixtures' not merged: split into T-035, T-036: 2026-11-23 T-001 (R-001): split the oversized 740-line attempt into a package/model/CLI foundation and a dependent ffmpeg-media slice, both rebuilt test-first from the latest base; persistent-spec infrastructure remains required and must not be deleted, while genuine red-bef
