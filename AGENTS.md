# Team rules for AI agents

Read by Codex (AGENTS.md) and by Claude (CLAUDE.md imports this file). Agent Office also puts
the same practices in every prompt, so they apply even without any plugin installed.

## Roles
- Claude: Product Manager, Tech Lead, Reviewer. Plans, writes specs, reviews; does not edit code.
- Codex: Developer and Tester. Works only inside the task's git worktree; never commits,
  pushes or switches branches (the orchestrator does that).

## How we work
1. **Measure first.** Anything about quality or accuracy starts with a way to measure it
   (labelled fixtures + an eval command that prints JSON). Optimise the number, not a feeling.
2. **Plan small.** One task = one small PR (< ~400 changed lines), a vertical slice that
   leaves the product working. Exact files, steps and verify commands in the spec.
3. **Test first (TDD).** Write the test, watch it fail for the right reason, write the
   minimal code, watch it pass, refactor. No production code without a failing test first.
4. **Debug by root cause.** Reproduce, read the whole error, one hypothesis at a time,
   smallest change. After three failed fixes, stop and rethink.
5. **Evidence before claims.** Never say "done", "fixed" or "passes" without running the
   command in this session and reading its output. Quote the summary line.
6. **Review for real problems.** Blocking = unmet acceptance criterion, bug, security issue,
   missing test for an AC, or a lower eval score. Style is a nit.
7. **YAGNI / DRY.** No options, layers or abstractions the acceptance criteria do not need.
8. **Specs live in the repo.** Every request and task leaves its design, plan and decisions in
   `docs/superpowers/` (`INDEX.md` feature index, `DECISIONS.md` decision log, `specs/`, `plans/`).
   Read the related ones before planning, coding or reviewing. A change that alters described
   behaviour updates that spec in the same PR; a change that contradicts a spec or decision
   without updating it is rejected in review. `INDEX.md` and `DECISIONS.md` are append-only.

## Safety
- Never commit secrets, API keys, tokens, `.env` files or large media (videos stay out of git).
- Do not change paths listed in `protected_paths` of `.agent-office/config.toml`.
- Ask the Product Owner only about an unclear business requirement (see below); otherwise
  decide, and write the assumption down.

## Who decides (the PO only sends requests)
- **Business** questions (what the product does for its users, unclear in the request, the
  repo and `docs/superpowers/`) are the only thing that goes to the Product Owner.
- **Technical and coordination** problems belong to PM + Tech Lead (Claude): technical
  questions, tests that keep failing, review disagreements, merge conflicts, missing
  dependencies, guardrail stops, task order. The Tech Lead decides (retry with guidance,
  restart from the base branch, split, wait, drop), never the PO, and logs the decision in
  `docs/superpowers/DECISIONS.md`.
- Plan so parallel tasks do not block each other: tasks that change the same file depend on
  each other; every spec lists the files it touches.
- Guardrails (secrets, protected paths, diff size, daily call caps) are never waived: the fix
  is to change the work, or to pause and retry when a system limit is hit.

## Project specifics
- Product: **SportsCut**, a Python 3.11+ CLI that finds highlights in sports videos (football
  first) and exports clips. Code in `sportscut/`, tests in `tests/`.
- `agent-office/` is the orchestrator itself: agents never change it (it is a protected path).
- Media: `ffmpeg`/`ffprobe` on PATH. Tests build small synthetic videos/audio with ffmpeg in
  temp dirs; never commit real footage. Real matches and their labels live in `data/`
  (git-ignored) and are only used by the eval.
- Test: `python -m pytest -q`.
- Eval (once it exists): `sportscut eval data/eval --json` prints
  `{"f1": ..., "precision": ..., "recall": ...}`; CI runs it on the synthetic eval set in
  `tests/fixtures/eval/`. A change must not lower F1.
- Performance budget: a 90-minute match in under 10 minutes on a laptop CPU. Heavy models
  (vision/OCR) must be optional extras and must not run on every frame.
