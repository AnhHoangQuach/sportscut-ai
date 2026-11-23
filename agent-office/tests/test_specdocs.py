"""Specs, plans and decisions are committed to docs/superpowers/ so later agents follow them."""
import json
import subprocess

from agent_office import specdocs
from agent_office import worktree as wt
from agent_office.models import Request, Stage, Task
from agent_office.pipeline import prompt

SPEC = {"spec": "1. Write test_scene. 2. Add sportscut/scene.py.", "acceptance_criteria": ["AC1 cuts scenes"],
        "test_plan": ["test_scene_cut"], "out_of_scope": ["OCR"],
        "decisions": ["Use ffmpeg scene filter, not OpenCV"], "related_specs": []}
DESIGN = "Goal: highlights. Approach: audio peaks (simplest); rejected: vision model (too slow)."


def show(repo, ref, path):
    p = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=repo, capture_output=True, text=True)
    assert p.returncode == 0, f"{path} not committed on {ref}: {p.stderr}"
    return p.stdout


def test_request_design_task_spec_plan_and_decisions_are_committed(env):
    env.script(claude_breakdown=[{"result": json.dumps({"design": DESIGN, "tasks": [
        {"key": "1", "title": "Scene cuts", "brief": "Cut at scenes.", "depends_on": []}]})}],
               claude_spec=[{"spec": SPEC}])
    office = env.office()
    office.add_request("Cut highlights\n\nfrom football matches")
    env.run_all(office)
    t = office.store.tasks["T-001"]
    assert t.stage == Stage.PR and t.decisions == SPEC["decisions"]
    assert office.store.requests["R-001"].design == DESIGN
    day = t.created_at[:10]
    design = show(env.repo, t.branch, f"docs/superpowers/specs/{day}-t-001-scene-cuts-design.md")
    assert "AC1 cuts scenes" in design and "Cut at scenes." in design and "OCR" in design
    assert "Use ffmpeg scene filter" in design and "R-001" in design
    plan = show(env.repo, t.branch, f"docs/superpowers/plans/{day}-t-001-scene-cuts.md")
    assert "Add sportscut/scene.py" in plan and "test_scene_cut" in plan
    req_design = show(env.repo, t.branch, f"docs/superpowers/specs/{day}-r-001-cut-highlights-design.md")
    assert DESIGN in req_design
    index = show(env.repo, t.branch, "docs/superpowers/INDEX.md")
    assert "T-001" in index and f"specs/{day}-t-001-scene-cuts-design.md" in index
    assert "Use ffmpeg scene filter, not OpenCV" in show(env.repo, t.branch, "docs/superpowers/DECISIONS.md")
    assert "merge=union" in show(env.repo, t.branch, ".gitattributes")
    task_md = (env.tmp / "sportscut-worktrees" / "T-001" / ".office" / "TASK.md").read_text()
    assert f"docs/superpowers/plans/{day}-t-001-scene-cuts.md" in task_md


def test_every_role_gets_the_existing_specs_and_decisions(env):
    d = env.repo / "docs/superpowers"
    d.mkdir(parents=True)
    (d / "INDEX.md").write_text("| 2026-11-01 | T-009 | Audio peaks | specs/2026-11-01-t-009-audio-design.md |\n")
    (d / "DECISIONS.md").write_text("- 2026-11-01 T-009: clips are 8 s before and 4 s after a peak\n")
    subprocess.run(["git", "add", "."], cwd=env.repo, check=True)
    subprocess.run(["git", "commit", "-qm", "specs"], cwd=env.repo, check=True)
    env.script(claude_spec=[{"spec": dict(SPEC, related_specs=["docs/superpowers/specs/2026-11-01-t-009-audio-design.md"])}])
    office = env.office()
    office.add_request("Cut highlights")
    env.run_all(office)
    calls = env.calls()
    for kind in ("breakdown", "spec", "review"):
        p = next(c["prompt"] for c in calls if c["kind"] == kind)
        assert "T-009" in p and "8 s before and 4 s after" in p, kind
    review = next(c["prompt"] for c in calls if c["kind"] == "review")
    assert "2026-11-01-t-009-audio-design.md" in review and "contradicts" in review
    dev = next(c["prompt"] for c in calls if c["kind"] == "dev")
    assert "docs/superpowers" in dev


def test_prompts_require_reading_and_updating_specs():
    for name, kw in (("pm_breakdown", dict(request="x", request_id="R-001")),
                     ("pm_spec", dict(request="x", task_id="T-001", title="t", brief="b", po_answer="")),
                     ("dev", dict(task_id="T-001", mode="")),
                     ("review", dict(task_id="T-001", round=1, max_rounds=3, spec="", acceptance_criteria="",
                                     test_summary="", dev_notes="", diff="")),
                     ("pm_goal", dict(request="x", request_id="R-001", done_tasks="", round=1, max_rounds=2))):
        assert "docs/superpowers" in prompt(name, **kw), name
    assert '"decisions"' in prompt("pm_spec") and '"related_specs"' in prompt("pm_spec")
    assert '"design"' in prompt("pm_breakdown")


def test_index_and_decisions_from_parallel_tasks_merge_without_conflict(env):
    root = env.tmp / "wts"
    req = Request(id="R-001", text="x")
    paths = []
    for tid in ("T-001", "T-002"):
        path, branch, _ = wt.ensure_worktree(env.repo, root, tid, "main")
        task = Task(id=tid, title=f"Feature {tid}", brief="b", request_id="R-001", spec="s",
                    decisions=[f"decision of {tid}"])
        specdocs.write_task_docs(path, task, req)
        assert wt.commit_all(path, tid)
        paths.append((path, branch))
    env.merge(paths[0][1])
    assert wt.update_from_base(paths[1][0], "main"), "INDEX.md/DECISIONS.md conflicted"
    index = (paths[1][0] / "docs/superpowers/INDEX.md").read_text()
    decisions = (paths[1][0] / "docs/superpowers/DECISIONS.md").read_text()
    assert "T-001" in index and "T-002" in index
    assert "decision of T-001" in decisions and "decision of T-002" in decisions


def test_spec_docs_do_not_count_toward_the_diff_size_limit(env):
    path, _, base = wt.ensure_worktree(env.repo, env.tmp / "wts", "T-001", "main")
    specdocs.write_task_docs(path, Task(id="T-001", title="t", brief="b", request_id="R-001",
                                        spec="\n".join(["step"] * 300)), None)
    (path / "code.py").write_text("x = 1\n")
    wt.commit_all(path, "c")
    assert wt.changed_line_count(path, base) == 1 + 2  # code.py + the two .gitattributes lines
