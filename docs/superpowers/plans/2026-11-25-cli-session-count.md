# Plan: số phiên Claude Code / Codex chạy cùng lúc

Design: `docs/superpowers/specs/2026-11-25-cli-session-count-design.md`.

1. Tests first: `agent-office/tests/test_cli_sessions.py` (config, plan_steps, failover, dispatch,
   simulated run, stats). Run and see them fail.
2. `config.py`: `Config.cli_parallel`, default config `claude = 2`, `codex = 3`.
3. `scheduler.py`: `plan_steps(cli_slots=...)`, `take()` checks and uses the CLI slot.
4. `pipeline.py`: `free_cli_slots()`, pass it to `plan_steps`, `_report_idle` names a full CLI.
5. `cli.py`, `stats.py`, `dashboard/server.py`, `dashboard/static/app.js`: show the CLI caps.
6. Docs 01, 02.2, 06, 07, agent-office/README.md, INDEX.md, DECISIONS.md.
7. Verify: `python -m pytest -q agent-office/tests`.
