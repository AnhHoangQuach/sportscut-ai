# Decision log

Newest last. Format: date, task (request): decision.

- 2026-11-22 PO (Hoang): first sport is football; other sports come later
- 2026-11-22 PO (Hoang): no API keys; agents run on subscription CLIs (`claude -p`, `codex exec`)
- 2026-11-22 PO (Hoang): agents work autonomously and auto-merge after approval + green tests; ask the PO only when a requirement is unclear
- 2026-11-23 PO (Hoang): accuracy is measured by `sportscut eval ... --json` (F1); a change must not lower F1
- 2026-11-23 PO (Hoang): a 90-minute match must process in under 10 minutes on a laptop CPU; vision/OCR models are optional extras and never run on every frame
- 2026-11-23 PO (Hoang): every request and task commits its design, plan and decisions under `docs/superpowers/`
