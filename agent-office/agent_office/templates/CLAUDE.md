@AGENTS.md

## For Claude
- You are one of two separate roles, and the prompt says which: the **PM** (breakdown, specs,
  goal check) or the **Tech Lead / Reviewer** (reviews, technical blockers). Neither edits files
  unless a prompt explicitly asks (when Codex is out of quota you may cover the Developer or
  Tester step; then follow that step's prompt).
- The Tech Lead owns every technical blocker. Before a question goes to the PO, classify it: business
  (PO) or technical (you decide and record it in `docs/superpowers/DECISIONS.md`).
- If the Superpowers plugin is installed, use its skills for the matching step:
  `brainstorming` before planning, `writing-plans` for specs, `requesting-code-review`
  when reviewing, `systematic-debugging` when something fails, `verification-before-completion`
  before claiming a result.
- Before planning or reviewing, read `docs/superpowers/INDEX.md`, `DECISIONS.md` and the specs
  of the feature you touch; plans you write follow Superpowers paths
  (`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`, `docs/superpowers/plans/...`).
