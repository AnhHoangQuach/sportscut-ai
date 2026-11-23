# Specs, plans and decisions

Written by Agent Office for every Product Owner request and task, committed with the code.
Agents read this folder before planning, coding or reviewing, and keep it true.

- `INDEX.md`: feature index, one row per task, newest last.
- `DECISIONS.md`: decision log. A later change that reverses a decision adds a new line saying so.
- `specs/*-design.md`: what to build and why (request design, task acceptance criteria).
- `plans/*.md`: how it was built (steps, test plan).

Rules: a change that alters behaviour described in an existing spec updates that spec in the
same pull request (add a line `Updated by T-xxx: ...`). Reviewers reject a change that
contradicts a spec or decision here without updating it.
