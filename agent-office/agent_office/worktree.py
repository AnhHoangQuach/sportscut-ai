"""Git helpers: one worktree + one branch per task. Only the orchestrator commits."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

# Orchestrator notes for agents (TASK.md, CHECKPOINT.md, REVIEW.md) live here inside each
# worktree and are never committed.
NOTES_DIR = ".office"


class GitError(RuntimeError):
    pass


def git(cwd: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout.strip()


def ensure_excluded(repo: Path) -> None:
    common = Path(git(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (repo / common).resolve()
    exclude = common / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    lines = exclude.read_text().splitlines() if exclude.exists() else []
    for entry in (f"{NOTES_DIR}/", ".agent-office/"):
        if entry not in lines:
            lines.append(entry)
    exclude.write_text("\n".join(lines) + "\n")


def ensure_worktree(repo: Path, root: Path, task_id: str, base_branch: str) -> tuple[Path, str, str]:
    """Create (or reuse) the task worktree. Returns (path, branch, base_sha)."""
    ensure_excluded(repo)
    branch = f"office/{task_id}"
    path = root / task_id
    base_sha = git(repo, "rev-parse", base_branch)
    if path.exists() and (path / ".git").exists():
        return path, branch, base_sha
    root.mkdir(parents=True, exist_ok=True)
    exists = git(repo, "branch", "--list", branch)
    if exists:
        git(repo, "worktree", "add", str(path), branch)
    else:
        git(repo, "worktree", "add", "-b", branch, str(path), base_branch)
    return path, branch, base_sha


def notes_dir(wt: Path) -> Path:
    d = wt / NOTES_DIR
    d.mkdir(exist_ok=True)
    return d


def has_changes(wt: Path) -> bool:
    return bool(git(wt, "status", "--porcelain"))


def commit_all(wt: Path, message: str) -> bool:
    if not has_changes(wt):
        return False
    git(wt, "add", "-A")
    git(wt, "-c", "user.name=Agent Office", "-c", "user.email=agent-office@localhost",
        "commit", "-q", "-m", message)
    return True


def diff(wt: Path, base_sha: str, max_chars: int = 120_000) -> str:
    d = git(wt, "diff", f"{base_sha}...HEAD")
    if len(d) > max_chars:
        d = d[:max_chars] + f"\n\n[diff truncated at {max_chars} chars; read files directly]"
    return d


def diff_stat(wt: Path, base_sha: str) -> str:
    return git(wt, "diff", "--stat", f"{base_sha}...HEAD")


def commits_since(wt: Path, base_sha: str) -> int:
    return int(git(wt, "rev-list", "--count", f"{base_sha}..HEAD") or 0)


def remove_worktree(repo: Path, path: Path) -> None:
    git(repo, "worktree", "remove", "--force", str(path), check=False)


def push_and_open_pr(wt: Path, remote: str, branch: str, base: str, title: str, body: str) -> str:
    """Push the task branch and open a PR with gh. Returns the PR URL."""
    git(wt, "push", "-u", remote, branch)
    if not shutil.which("gh"):
        raise GitError("gh CLI not found; branch pushed, open the PR manually")
    p = subprocess.run(
        ["gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body-file", "-"],
        cwd=wt, input=body, capture_output=True, text=True,
    )
    if p.returncode != 0:
        if "already exists" in p.stderr:
            v = subprocess.run(["gh", "pr", "view", branch, "--json", "url", "-q", ".url"],
                               cwd=wt, capture_output=True, text=True)
            return v.stdout.strip()
        raise GitError(f"gh pr create failed: {p.stderr.strip()}")
    return p.stdout.strip().splitlines()[-1]


def pr_state(wt_or_repo: Path, url: str) -> str:
    """MERGED / OPEN / CLOSED, or '' if unknown."""
    if not shutil.which("gh"):
        return ""
    p = subprocess.run(["gh", "pr", "view", url, "--json", "state", "-q", ".state"],
                       cwd=wt_or_repo, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ""
