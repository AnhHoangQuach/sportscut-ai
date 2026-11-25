# Plan: chọn CLI và model cho từng vai trên dashboard

Design: `docs/superpowers/specs/2026-11-25-role-cli-from-dashboard-design.md`.

1. Tests first: `agent-office/tests/test_role_settings.py` (config edit, submit, live runner, model
   flag, rest follows CLI, in-flight switch, dashboard API). Run and see them fail.
2. `config.py`: `Config.role_models`, `[roles] <role>_model`, `set_role()` (line edit + tomllib check).
3. `store.py`: `_sync_roles` hands a moved role its new CLI's rest state.
4. `pipeline.py`: `set_role` inbox command (write config, reload, sync, event, message); `_call` passes
   the role's model; `_rest` rests the CLI that answered (`hit.agent`), not the role's current CLI.
5. `agents/{claude,codex}.py`: `extra["model"]` overrides the CLI model.
6. `dashboard`: `POST /api/roles/{role}`, `roles[].model`, `config.models`; "Vai & model" panel.
7. Docs 01, 06, 09, agent-office/README.md, INDEX.md, DECISIONS.md.
8. Verify: `python -m pytest -q agent-office/tests`.
