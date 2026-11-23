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
