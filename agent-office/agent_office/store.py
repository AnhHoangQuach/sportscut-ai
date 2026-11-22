"""Persistent state (state.json) and the append-only event log (events.jsonl).

Everything lives in <target repo>/.agent-office/. Phase 2/3 dashboards only read
these two files, so they are the contract between the orchestrator and any UI.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .models import Agent, Request, Task, now_iso

OFFICE_DIR = ".agent-office"
AGENT_NAMES = ("claude", "codex")


class Store:
    def __init__(self, repo: Path):
        self.repo = Path(repo).resolve()
        self.dir = self.repo / OFFICE_DIR
        self.state_path = self.dir / "state.json"
        self.events_path = self.dir / "events.jsonl"
        self.logs_dir = self.dir / "logs"
        self.tasks: dict[str, Task] = {}
        self.agents: dict[str, Agent] = {}
        self.requests: dict[str, Request] = {}

    # ---------- lifecycle ----------
    def exists(self) -> bool:
        return self.state_path.exists()

    def init(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
        if not self.exists():
            self.agents = {n: Agent(name=n) for n in AGENT_NAMES}
            self.save()
            self.event("office_initialized", repo=str(self.repo))

    def load(self) -> "Store":
        if not self.exists():
            raise FileNotFoundError(f"No agent office here. Run `office init` in {self.repo}")
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.tasks = {t["id"]: Task.from_dict(t) for t in data.get("tasks", [])}
        self.agents = {a["name"]: Agent.from_dict(a) for a in data.get("agents", [])}
        for n in AGENT_NAMES:
            self.agents.setdefault(n, Agent(name=n))
        self.requests = {r["id"]: Request(**r) for r in data.get("requests", [])}
        return self

    def save(self) -> None:
        data = {
            "version": 1,
            "updated_at": now_iso(),
            "agents": [a.to_dict() for a in self.agents.values()],
            "requests": [asdict(r) for r in self.requests.values()],
            "tasks": [t.to_dict() for t in self.tasks.values()],
        }
        self.dir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.dir, prefix=".state.", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.state_path)

    # ---------- events ----------
    def event(self, kind: str, **fields: Any) -> None:
        rec = {"at": now_iso(), "event": kind, **fields}
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ---------- ids ----------
    def next_task_id(self) -> str:
        return f"T-{len(self.tasks) + 1:03d}"

    def next_request_id(self) -> str:
        return f"R-{len(self.requests) + 1:03d}"

    # ---------- logs ----------
    def log_path(self, task_id: str, label: str) -> Path:
        d = self.logs_dir / task_id
        d.mkdir(parents=True, exist_ok=True)
        n = len(list(d.iterdir())) + 1
        return d / f"{n:03d}-{label}.log"

    # ---------- inbox (commands from the CLI / dashboard while a runner may be active) ----------
    @property
    def inbox_path(self) -> Path:
        return self.dir / "inbox.jsonl"

    @property
    def pid_path(self) -> Path:
        return self.dir / "runner.pid"

    def append_inbox(self, cmd: dict[str, Any]) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with self.inbox_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": now_iso(), **cmd}, ensure_ascii=False) + "\n")

    def take_inbox(self) -> list[dict[str, Any]]:
        """Atomically take every queued command (new appends go to a fresh file)."""
        if not self.inbox_path.exists():
            return []
        taking = self.dir / f".inbox.{os.getpid()}.jsonl"
        os.replace(self.inbox_path, taking)
        cmds = []
        for line in taking.read_text(encoding="utf-8").splitlines():
            try:
                cmds.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        taking.unlink(missing_ok=True)
        return cmds

    # ---------- runner process ----------
    def runner_pid(self) -> int | None:
        try:
            pid = int(self.pid_path.read_text().strip())
        except (OSError, ValueError):
            return None
        return pid if pid_alive(pid) else None

    def claim_runner(self) -> bool:
        other = self.runner_pid()
        if other and other != os.getpid():
            return False
        self.dir.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(str(os.getpid()))
        return True

    def release_runner(self) -> None:
        if self.runner_pid() == os.getpid():
            self.pid_path.unlink(missing_ok=True)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":  # pragma: no cover
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
