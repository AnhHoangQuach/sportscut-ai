# Plan: Codex through codex-lb

Spec: [../specs/2026-11-23-codex-lb-provider-design.md](../specs/2026-11-23-codex-lb-provider-design.md)

1. Test first: `agent-office/tests/test_codex_provider.py` (config parsing, `.env` parsing, codex
   error parsing, child env keeps the provider key, pre-call check, office rest/resume, doctor).
   The fake codex prints `{"type":"turn.failed",...Missing environment variable...}` for
   `{"missing_env": VAR}` and records `CODEX_LB*` variables it received. Watch it fail (no module).
2. `codex_provider.py`; `subscription_env(cwd, env_file, keep)`; `CliAgent.child_env/env_problem`;
   `CodexAgent` overrides; `[office] env_file` in config.
3. `Office._env_rest`, pre-call check in `_call`, output check after a failed run, `env` branch in
   `_wake`; `rest_reason` and failover in `scheduler.py`; dashboard labels.
4. `office doctor`: `doctor_codex_provider()`.
5. Docs: 02 §2.8 (codex-lb setup), 01 §1.2 exception, 09 troubleshooting row; INDEX + DECISIONS.
6. Verify: `cd agent-office && python -m pytest -q`.
