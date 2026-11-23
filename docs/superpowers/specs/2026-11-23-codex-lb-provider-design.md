# Codex through codex-lb (custom model provider with its own key)

Date: 2026-11-23  
Request: PO (Hoang) 2026-11-23: "tôi muốn dùng codex-lb opensource". Codex runs through the
codex-lb proxy (`model_provider = "codex-lb"`, `env_key = "CODEX_LB_API_KEY"` in
`~/.codex/config.toml`); `codex exec` started by the office failed with
`turn.failed "Missing environment variable: CODEX_LB_API_KEY"`.

## Root cause

- codex-lb ([Soju06/codex-lb](https://github.com/Soju06/codex-lb)) is a local load balancer for
  several ChatGPT accounts (`uvx codex-lb` or Docker, dashboard on `http://localhost:2455`, Codex
  base_url `http://127.0.0.1:2455/backend-api/codex`). With API-key auth on (needed for remote
  clients, optional locally) Codex reads the key from the variable named by `env_key`.
- The office did not strip `CODEX_LB_API_KEY`, but the variable was not in the environment of the
  process that ran `office run` / `office dashboard` (exported only in an interactive shell rc, or
  never exported). Nothing in the office could supply it, `office doctor` did not look, and the
  failure counted as a failing CLI (2 failures -> 15/30/60 min "failure" rest), not as a problem
  only the user can fix.

## Design

- New `agent_office/codex_provider.py`: `provider_info()` reads `$CODEX_HOME/config.toml` (default
  `~/.codex`) -> provider name, `env_key`, `base_url`; `read_env_file()` parses `KEY=value` lines;
  `missing_env_var(output)` finds codex's "Missing environment variable" error.
- `[office] env_file = ".env"` (relative to `.agent-office/`, which git ignores): read before
  **every** CLI call and added to the child env, so a fix applies without restarting the office.
- `CodexAgent.child_env()` keeps the provider's `env_key` even when its name is in `API_KEY_VARS`
  (e.g. a proxy that uses `OPENAI_API_KEY`); every other API key is still stripped.
- `CliAgent.env_problem()` (Codex: provider has an `env_key` and the child env lacks it) is checked
  before each call: no call is spent. A run whose output has the codex error is handled the same.
- New rest cause `env`: all Codex roles rest, `failures` stay 0, one message to the PO
  (`topic=env`) with the exact fix, event `env_problem`. Every 5 minutes (`ENV_RECHECK_MIN`) the
  wake step re-checks locally (no probe call); still missing -> rest again silently; fixed -> back
  to work with an `awake` message. Like quota, an `env` rest allows role failover to Claude.
- `office doctor`: prints the Codex provider and config path, whether the `env_key` is set (from
  the shell or `.agent-office/.env`, never printing the value) with the fix, and whether the
  provider's `base_url` host:port accepts a TCP connection.

## Files

- `agent-office/agent_office/codex_provider.py`, `agents/base.py`, `agents/codex.py`, `config.py`,
  `pipeline.py`, `scheduler.py`, `models.py`, `cli.py`, `store.py` (`.agent-office/.gitignore` with `.env`),
  `dashboard/static/{app.js,office.js}`
- `agent-office/tests/test_codex_provider.py`, `tests/conftest.py`, `tests/fake_agent.py`
- `docs/02-quota-song-song-rao-chan.md` (2.8), `docs/01-multi-agent.md`, `docs/09-van-hanh.md`,
  `docs/superpowers/{INDEX.md,DECISIONS.md}`, this spec and its plan

## Acceptance criteria

1. With codex-lb configured and `CODEX_LB_API_KEY` in `.agent-office/.env`, `codex exec` gets the
   variable; the value is never printed or committed.
2. The provider's own key survives API-key stripping; other API keys are still removed.
3. A missing key never calls Codex, never counts as quota or CLI failure, tells the PO once with the
   fix, and the office resumes by itself within 5 minutes of the key appearing.
4. Codex's "Missing environment variable" output is classified the same way.
5. `office doctor` shows provider, base_url, key status (FAIL + fix when missing) and server reachability.
6. Tests never read the developer's real `~/.codex` (`CODEX_HOME` points to a temp dir).
