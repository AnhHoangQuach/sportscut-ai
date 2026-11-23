# Plan: fast retry on server errors + failover for every rest

Design: `docs/superpowers/specs/2026-11-23-upstream-retry-design.md`.

1. Tests first: `agent-office/tests/test_upstream.py` (patterns, 1/2/5 ladder, single message,
   failover for `upstream`/`failure`, end-to-end 502 → Claude covers dev, no probe while codex-lb
   is down, awake message), `test_dashboard.py` (`covered_by`). See them fail.
2. `limits.py` patterns + `transient_error`; `config.py` `upstream_retry_minutes`.
3. `codex_provider.port_problem` (moved from `cli._port_open`), `CliAgent/CodexAgent.server_problem`.
4. `scheduler.FAILOVER_CAUSES`; `pipeline._call/_rest/_wake` cause `upstream`.
5. Dashboard server `covered_by`, `app.js`/`office.js` labels.
6. Docs 01, 02.1, DECISIONS.md, INDEX.md.
7. Verify: `cd agent-office && python -m pytest -q`.
