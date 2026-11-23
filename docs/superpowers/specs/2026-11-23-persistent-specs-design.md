# Persistent specs, plans and decisions

Requested by the PO (Hoang) on 2026-11-23: when a new request comes in, the requirements and the
way they were built must be saved (Superpowers style) so that agents who later change or extend
a feature follow them.

## Problem

Specs, acceptance criteria and decisions lived only in `.agent-office/state.json` and in
`.office/TASK.md` inside the task worktree. Both are git-ignored and the worktree is deleted
after merge, so nothing reached `main`. The next request started from code alone.

## Goal and how we know

- Each merged task leaves, on `main`, a design spec, a plan, a feature-index row and its decisions.
- Every role (PM breakdown, PM spec, PM goal check, developer, reviewer) sees the index and the
  decision log in its prompt and is told to follow and update them.
- Reviewer treats "contradicts a spec / decision without updating it" as a blocker.
- Verified by `agent-office/tests/test_specdocs.py`.

## Approaches considered

1. PM agent writes the files itself. Rejected: the PM runs read-only on the main checkout, and
   whether it writes would depend on the model obeying.
2. **Orchestrator writes the files into the task worktree from the PM's JSON** (chosen): files
   are committed with the code in the same PR, reviewed with it, and merged with it. Works
   without the Superpowers plugin.
3. A separate "docs" PR per request. Rejected: extra merges and specs drifting from code.

## Layout (Superpowers paths)

- `docs/superpowers/specs/YYYY-MM-DD-r-xxx-<topic>-design.md`: request design (goal, approaches, choice)
- `docs/superpowers/specs/YYYY-MM-DD-t-xxx-<topic>-design.md`: task goal, ACs, out of scope, decisions
- `docs/superpowers/plans/YYYY-MM-DD-t-xxx-<topic>.md`: implementation steps and test plan
- `docs/superpowers/INDEX.md`, `DECISIONS.md`: append-only, `merge=union` in `.gitattributes`
  so parallel tasks never conflict on them.

## Decisions

- Spec files are written once; later edits by the developer (deviations) or later tasks are kept.
- `docs/superpowers/` does not count toward `max_diff_lines`.
- New PM JSON fields are optional (`design`, `decisions`, `related_specs`): old outputs still work.
