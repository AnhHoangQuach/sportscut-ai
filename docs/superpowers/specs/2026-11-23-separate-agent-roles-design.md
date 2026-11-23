# Separate agents per role: PM, Tech Lead, Developer, Tester

Date: 2026-11-23  
Request: PO (Hoang) 2026-11-23: "tách biệt codex thành 1 developer và 1 tester có được không. tương tự làm với claude"

## Goal

Each role is its own agent: own state, prompt, session/log, scheduler slot, dashboard card,
3D desk and stats, with explicit handoffs (PM → Developer → Tester → Tech Lead). The Tester checks
the Developer's work independently instead of trusting the Developer's tests.

## Reading of the request (Tech Lead, no PO question needed)

"Tương tự với Claude" = Claude splits into **PM** (breakdown, spec, goal check) and **Tech Lead /
Reviewer** (review, technical-blocker triage per the Tech Lead design). This matches the role split
already used in prompts and in `docs/01`. Recorded in DECISIONS.md.

## Design

- Roles `pm`, `lead`, `dev`, `tester` (`models.ROLES`); each `Agent` has a `provider` (`claude` |
  `codex`). `[roles]` in `config.toml` maps role → CLI (default pm/lead = claude, dev/tester = codex).
- **Quota is per provider.** A limit, daily budget or repeated failure on any role rests every
  role of that CLI with the same `rest_until`/cause/detail/log (`Office._rest`); one `wake` step
  per CLI probes once and wakes all its roles (`Office._wake`). Two consecutive failures counted
  across the CLI's roles. `max_calls_per_day` stays per CLI and sums its roles' calls.
- Scheduler: `STAGE_AGENT` → roles (spec pm, dev dev, test tester, review lead), `STEP_ROLE`
  (breakdown/goal pm, techlead lead). Slots per role from `[parallel] pm/lead/dev/tester`.
- Failover (R-007) keeps working by role pairs `pm ↔ dev`, `lead ↔ tester` (`FAILOVER`); the
  covering role keeps its name and its CLI, permissions follow the step; `agent_failover` records
  both roles and providers.
- `office wake <role|cli>` and `POST /api/agents/<role|cli>/wake` wake every role of that CLI.
- Logs: `logs/<task>/NNN-<label>-<role>.log`; probe: `logs/_probe/NNN-<cli>.log`.
- Messages use role names; handoffs pm→dev (`assign`), dev→tester (`handoff`), tester→dev
  (`test_fail`) or tester→lead (`handoff`), lead→dev (`approve`/`changes`), lead→po (`merged`).
- **Independent Tester.** `test.md`: write own `*_acceptance*` tests from the ACs, check the
  developer's tests can fail, never fix production code, report failures in `TEST_REPORT.md`
  ("Failures for the Developer") + `RESULT: FAIL`. The office commits the Tester's files
  (`task.tester_files`), sends answer + report to the Developer (`task.test_output`, `TASK.md`
  "Tester's tests"), and if the Developer edits a Tester file it emits `tests_changed_by_dev` and
  warns the Tester on the next run (`task.dev_changed_tests`).
- Stats: per role (`agents`, with `provider`) and per CLI (`providers`: roles, calls, rests).
- Dashboard + 3D office: four cards / four desks (Claude roles left, Codex roles right), role
  labels, provider colours; old events named `claude`/`codex` shown at `pm`/`dev`.
- `office demo`: the simulated Tester rejects T-002 once, so the Tester → Developer loop is visible.

## Backward compatibility

- `state.json` with agents `claude`/`codex` is split on load (`Store._sync_roles`): rest state copied
  to every role of that CLI, usage counters kept on the first role so per-CLI totals stay right.
- Old `[parallel] claude = 1 / codex = 2` (no role keys) apply to every role on that CLI; no `[roles]`
  = default mapping. Guardrails, docs/superpowers persistence and escalation rules are unchanged.

## Files

`agent_office/{models,config,store,scheduler,pipeline,stats,cli,worktree}.py`, `agents/sim.py`,
`prompts/{dev,test,pm_spec,tech_lead,review}.md`, `dashboard/server.py`,
`dashboard/static/{app.js,office.js,office.html,index.html,style.css}`, templates, AGENTS.md,
CLAUDE.md, `docs/01,02,04,06,07,09,README`, `agent-office/README.md`, tests (`test_roles.py` new;
role names in existing tests).
