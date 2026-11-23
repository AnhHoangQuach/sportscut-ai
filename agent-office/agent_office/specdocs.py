"""Persistent specs, plans and decisions in the target repo (Superpowers layout).

Every task commits, together with its code:
  docs/superpowers/specs/YYYY-MM-DD-<request>-<topic>-design.md   request design (breakdown)
  docs/superpowers/specs/YYYY-MM-DD-<task>-<topic>-design.md      what to build and why
  docs/superpowers/plans/YYYY-MM-DD-<task>-<topic>.md             how it was built
  docs/superpowers/INDEX.md      one row per task (feature index)
  docs/superpowers/DECISIONS.md  one line per decision
INDEX.md and DECISIONS.md only ever get lines appended and use git's `union` merge driver, so
parallel tasks never conflict on them. Later prompts read them (see `context`).
"""
from __future__ import annotations

import re
from pathlib import Path

from .models import Request, Task

SPECS_DIR = "docs/superpowers"
UNION_FILES = ("INDEX.md", "DECISIONS.md")

README = f"""# Specs, plans and decisions

Written by Agent Office for every Product Owner request and task, committed with the code.
Agents read this folder before planning, coding or reviewing, and keep it true.

- `INDEX.md`: feature index, one row per task, newest last.
- `DECISIONS.md`: decision log. A later change that reverses a decision adds a new line saying so.
- `specs/*-design.md`: what to build and why (request design, task acceptance criteria).
- `plans/*.md`: how it was built (steps, test plan).

Rules: a change that alters behaviour described in an existing spec updates that spec in the
same pull request (add a line `Updated by T-xxx: ...`). Reviewers reject a change that
contradicts a spec or decision here without updating it.
"""
INDEX_HEAD = ("# Feature index\n\n| Date | Task | Title | Request | Design | Plan | Updates specs |\n"
              "|---|---|---|---|---|---|---|\n")
DECISIONS_HEAD = "# Decision log\n\nNewest last. Format: date, task (request): decision.\n\n"


def slug(text: str, words: int = 6) -> str:
    first = next((ln.strip("# ").strip() for ln in text.splitlines() if ln.strip()), "")
    parts = re.findall(r"[a-z0-9]+", first.lower())[:words]
    return "-".join(parts) or "task"


def _name(item_id: str, created_at: str, title: str) -> str:
    return f"{created_at[:10]}-{item_id.lower()}-{slug(title)}"


def request_design_path(req: Request) -> str:
    return f"{SPECS_DIR}/specs/{_name(req.id, req.created_at, req.text)}-design.md"


def design_path(task: Task) -> str:
    return f"{SPECS_DIR}/specs/{_name(task.id, task.created_at, task.title)}-design.md"


def plan_path(task: Task) -> str:
    return f"{SPECS_DIR}/plans/{_name(task.id, task.created_at, task.title)}.md"


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) or "- (none)"


def _write_once(path: Path, text: str) -> None:
    """Only the first write wins: later edits (by the developer or later tasks) are kept."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _append_once(path: Path, head: str, marker: str, lines: list[str]) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else head
    if marker in text or not lines:
        if not path.exists():
            path.write_text(text, encoding="utf-8")
        return
    if not text.endswith("\n"):
        text += "\n"
    path.write_text(text + "\n".join(lines) + "\n", encoding="utf-8")


def _ensure_union(wt: Path) -> None:
    ga = wt / ".gitattributes"
    text = ga.read_text(encoding="utf-8") if ga.exists() else ""
    missing = [f"{SPECS_DIR}/{f} merge=union" for f in UNION_FILES if f"{SPECS_DIR}/{f} merge=union" not in text]
    if missing:
        ga.write_text(text + ("" if not text or text.endswith("\n") else "\n") + "\n".join(missing) + "\n",
                      encoding="utf-8")


def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ").strip()


def write_task_docs(wt: Path, task: Task, req: Request | None) -> list[str]:
    """Create the task's committed spec files in its worktree. Idempotent. Returns repo paths."""
    root = wt / SPECS_DIR
    _write_once(root / "README.md", README)
    _ensure_union(wt)
    paths = []
    req_link = ""
    if req is not None and req.design.strip():
        rp = request_design_path(req)
        _write_once(wt / rp, f"# {req.id} design\n\n## Product Owner request\n\n{req.text}\n\n"
                             f"## Design (goal, approaches, choice)\n\n{req.design}\n\n"
                             f"## Tasks\n\nSee the rows for {req.id} in `INDEX.md`.\n")
        paths.append(rp)
        req_link = f" Request design: `{rp}`."
    dp, pp = design_path(task), plan_path(task)
    related = _bullets([f"`{s}`" for s in task.related_specs])
    _write_once(wt / dp, (
        f"# {task.id}: {task.title}\n\nRequest {task.request_id}.{req_link} Plan: `{pp}`.\n\n"
        + (f"## Product Owner request\n\n{req.text}\n\n" if req is not None else "")
        + f"## Goal\n\n{task.brief}\n\n## Acceptance criteria\n\n{_bullets(task.acceptance_criteria)}\n\n"
        f"## Out of scope\n\n{_bullets(task.out_of_scope)}\n\n## Decisions\n\n{_bullets(task.decisions)}\n\n"
        f"## Existing specs this task changes\n\n{related}\n"
        + (f"\n## Product Owner answers\n\n{task.po_answer}\n" if task.po_answer else "")))
    _write_once(wt / pp, f"# Plan {task.id}: {task.title}\n\nDesign: `{dp}`.\n\n## Implementation plan\n\n"
                         f"{task.spec}\n\n## Test plan\n\n{_bullets(task.test_plan)}\n")
    paths += [dp, pp]
    day = task.created_at[:10]
    rel = lambda p: p[len(SPECS_DIR) + 1:]  # noqa: E731 - links relative to INDEX.md
    _append_once(root / "INDEX.md", INDEX_HEAD, f"| {task.id} |", [
        f"| {day} | {task.id} | {_cell(task.title)} | {task.request_id} | [design]({rel(dp)}) | "
        f"[plan]({rel(pp)}) | {_cell(', '.join(task.related_specs)) or '-'} |"])
    lines = [f"- {day} {task.id} ({task.request_id}): {_cell(d)}" for d in task.decisions]
    if req is not None:
        lines += [f"- {day} {req.id}: {_cell(d)}" for d in req.decisions]
    _append_missing(root / "DECISIONS.md", DECISIONS_HEAD, lines)
    return paths


def _append_missing(path: Path, head: str, lines: list[str]) -> None:
    """Append each line not in the file yet (decisions added later, e.g. by the Tech Lead, land too)."""
    text = path.read_text(encoding="utf-8") if path.exists() else head
    have = set(text.splitlines())
    new = [ln for ln in dict.fromkeys(lines) if ln not in have]
    if not new and path.exists():
        return
    if new and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + "".join(ln + "\n" for ln in new), encoding="utf-8")


def context(repo: Path, max_chars: int = 6000) -> str:
    """What prompts show of the committed specs: the feature index and the decision log."""
    root = repo / SPECS_DIR
    parts = []
    for name in UNION_FILES:
        f = root / name
        if f.exists():
            text = f.read_text(encoding="utf-8")
            if len(text) > max_chars:
                text = "...(older lines cut; read the file)\n" + text[-max_chars:]
            parts.append(f"### {SPECS_DIR}/{name}\n\n{text.strip()}")
    return "\n\n".join(parts) or f"(no {SPECS_DIR}/ yet: this is the first spec)"
