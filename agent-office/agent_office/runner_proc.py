"""Start/stop `office run --watch` as a background process (used by the dashboard and `office demo`)."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from .store import Store


def start(repo: Path) -> int:
    s = Store(repo)
    pid = s.runner_pid()
    if pid:
        return pid
    s.logs_dir.mkdir(parents=True, exist_ok=True)
    log = (s.logs_dir / "runner.log").open("a", encoding="utf-8")
    kw: dict[str, Any] = {"start_new_session": True} if os.name != "nt" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
    proc = subprocess.Popen(
        [sys.executable, "-m", "agent_office", "--repo", str(repo), "run", "--watch"],
        cwd=repo, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        env={**os.environ, "PYTHONUNBUFFERED": "1"}, **kw)
    return proc.pid


def stop(repo: Path) -> int | None:
    pid = Store(repo).runner_pid()
    if pid:
        sig = signal.SIGINT if os.name != "nt" else signal.CTRL_BREAK_EVENT  # type: ignore[attr-defined]
        os.kill(pid, sig)
    return pid
