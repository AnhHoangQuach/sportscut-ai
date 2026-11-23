# Plan: persistent specs, plans and decisions

Design: `docs/superpowers/specs/2026-11-23-persistent-specs-design.md`.

1. Test first: `agent-office/tests/test_specdocs.py` (files committed on the task branch, prompts
   carry the index/decisions, parallel tasks merge INDEX/DECISIONS cleanly, diff-size guardrail
   ignores spec docs). Seen failing: `5 failed`.
2. `agent_office/specdocs.py`: paths, `write_task_docs(worktree, task, request)`, `context(repo)`.
3. `models.py`: `Task.decisions`, `Task.related_specs`, `Request.design`.
4. `pipeline.py`: pass `specs=specdocs.context(...)` to breakdown/spec/goal/review prompts, store the
   new fields, call `write_task_docs` in `_ensure_worktree`, list the files in `.office/TASK.md`.
5. `worktree.changed_line_count`: exclude `docs/superpowers`.
6. Prompts: read/follow/update rules; reviewer blocker rule; JSON fields.
7. Team rules (AGENTS.md / CLAUDE.md + templates), seed `docs/superpowers/` and `.gitattributes`,
   Vietnamese docs (03, 06, 07).
8. Verify: `cd agent-office && python -m pytest -q`.
