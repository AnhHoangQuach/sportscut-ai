"""Phase 2 dashboard: FastAPI + WebSocket over the files Phase 1 already writes.

The dashboard never mutates state.json directly. PO actions go through the inbox
(Office.submit), so they are safe while `office run` is working in another process.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import runner_proc
from ..config import load_config
from ..models import PROVIDERS, ROLE_TITLE, ROLES
from ..scheduler import assigned_agent, plan_steps
from ..store import Store
from ..worktree import NOTES_DIR

STATIC = Path(__file__).parent / "static"
SAFE_NAME = re.compile(r"^[A-Za-z0-9._-]+$")
POLL_SEC = 0.5
EVENTS_ON_CONNECT = 300


class TextBody(BaseModel):
    text: str


def snapshot(repo: Path) -> dict[str, Any]:
    store = Store(repo)
    if not store.exists():
        raise HTTPException(404, "office not initialised (run `office init`)")
    raw = json.loads(store.state_path.read_text(encoding="utf-8"))
    store.load()
    cfg = load_config(store.dir)
    # The runner's view: tasks being worked on are busy and use a session, so the list says why
    # every other task (and every idle session) waits, not only why the next step cannot start.
    busy = {t for a in store.agents.values() for t in a.active}
    slots = {n: cfg.parallel.get(n, 1) - len(a.active) for n, a in store.agents.items()}
    cli_slots = {p: cap - sum(len(m.active) for m in store.roles_of(p))
                 for p, cap in cfg.cli_parallel.items() if cap > 0}
    plan = plan_steps(store, datetime.now(timezone.utc), cfg.merge_mode == "auto", busy=busy, slots=slots,
                      cli_slots=cli_slots)
    raw["config"] = {"merge_mode": cfg.merge_mode, "base_branch": cfg.base_branch, "open_pr": cfg.open_pr,
                     "max_goal_rounds": cfg.max_goal_rounds, "parallel": cfg.parallel,
                     "cli_parallel": cfg.cli_parallel,
                     "max_calls_per_day": cfg.max_calls_per_day}
    # One desk per role; old events name a CLI ("claude"/"codex"): show them at its first role.
    now = datetime.now(timezone.utc)
    raw["agents"] = [a.to_dict() for a in store.agents.values()]
    for d in raw["agents"]:  # while a role rests, the role on the other CLI that takes its work
        other = assigned_agent(store, d["name"], now)
        d["covered_by"] = other if other != d["name"] else ""
    raw["roles"] = [{"name": a.name, "provider": a.provider, "title": ROLE_TITLE.get(a.name, a.name)}
                    for a in store.agents.values()]
    raw["legacy_agents"] = {p: next((a.name for a in store.roles_of(p)), "") for p in store.providers()}
    raw["repo"] = {"name": repo.name, "path": str(repo)}
    raw["runner"] = {"pid": store.runner_pid(), "running": store.runner_pid() is not None}
    raw["waiting_on"] = plan.waiting_on or []
    raw["inbox_pending"] = store.inbox_path.exists()
    return raw


def read_events(store: Store, offset: int) -> tuple[list[dict[str, Any]], int]:
    """Events appended after byte `offset`. Returns (events, new_offset)."""
    p = store.events_path
    if not p.exists():
        return [], 0
    size = p.stat().st_size
    if size < offset:  # file was truncated/rotated
        offset = 0
    if size == offset:
        return [], offset
    with p.open("rb") as f:
        f.seek(offset)
        chunk = f.read()
    end = chunk.rfind(b"\n") + 1  # only whole lines
    events = []
    for line in chunk[:end].decode("utf-8", "replace").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events, offset + end


def tail_events(store: Store, n: int) -> tuple[list[dict[str, Any]], int]:
    events, end = read_events(store, 0)
    return events[-n:], end


def create_app(repo: Path) -> FastAPI:
    repo = Path(repo).resolve()
    app = FastAPI(title="Agent Office", docs_url=None, redoc_url=None)

    def office():
        from ..pipeline import Office
        return Office(repo)

    def store() -> Store:
        return Store(repo).load()

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/office")
    def office_3d():
        return FileResponse(STATIC / "office.html")

    @app.get("/api/state")
    def get_state():
        return snapshot(repo)

    @app.get("/api/stats")
    def get_stats():
        from .. import stats
        store = Store(repo)
        if not store.exists():
            raise HTTPException(404, "office not initialised (run `office init`)")
        store.load()
        return stats.collect(store, load_config(store.dir))

    @app.get("/api/events")
    def get_events(limit: int = 200):
        return tail_events(Store(repo), min(limit, 2000))[0]

    @app.post("/api/requests")
    def post_request(body: TextBody):
        if not body.text.strip():
            raise HTTPException(400, "empty request")
        return {"results": office().submit({"cmd": "request", "text": body.text})}

    @app.post("/api/requests/{rid}/retry")
    def retry_request(rid: str):
        return {"results": office().submit({"cmd": "retry", "id": rid})}

    @app.post("/api/tasks/{tid}/answer")
    def answer_task(tid: str, body: TextBody):
        if not body.text.strip():
            raise HTTPException(400, "empty answer")
        return {"results": office().submit({"cmd": "answer", "id": tid, "text": body.text})}

    @app.post("/api/agents/{name}/wake")
    def wake_agent(name: str):
        if name not in (*ROLES, *PROVIDERS):
            raise HTTPException(404, "unknown agent")
        return {"results": office().submit({"cmd": "wake", "agent": name})}

    @app.get("/api/tasks/{tid}/logs")
    def list_logs(tid: str):
        if not SAFE_NAME.match(tid):
            raise HTTPException(400, "bad id")
        d = Store(repo).logs_dir / tid
        return sorted(p.name for p in d.iterdir()) if d.exists() else []

    @app.get("/api/tasks/{tid}/logs/{name}", response_class=PlainTextResponse)
    def read_log(tid: str, name: str):
        if not (SAFE_NAME.match(tid) and SAFE_NAME.match(name)):
            raise HTTPException(400, "bad name")
        p = Store(repo).logs_dir / tid / name
        if not p.is_file():
            raise HTTPException(404, "no such log")
        return p.read_text(encoding="utf-8", errors="replace")[-200_000:]

    @app.get("/api/tasks/{tid}/notes")
    def task_notes(tid: str):
        t = store().tasks.get(tid)
        if t is None:
            raise HTTPException(404, "no such task")
        notes: dict[str, str] = {}
        d = Path(t.worktree) / NOTES_DIR if t.worktree else None
        if d and d.is_dir():
            for p in sorted(d.glob("*.md")):
                notes[p.name] = p.read_text(encoding="utf-8", errors="replace")[-50_000:]
        return notes

    # ---------- runner control ----------
    @app.post("/api/runner/start")
    def start_runner():
        return {"running": True, "pid": runner_proc.start(repo)}

    @app.post("/api/runner/stop")
    def stop_runner():
        pid = runner_proc.stop(repo)
        return {"running": bool(pid), "stopping": pid}

    @app.get("/api/runner/log", response_class=PlainTextResponse)
    def runner_log():
        p = Store(repo).logs_dir / "runner.log"
        return p.read_text(encoding="utf-8", errors="replace")[-30_000:] if p.exists() else ""

    # ---------- realtime ----------
    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        s = Store(repo)
        events, offset = tail_events(s, EVENTS_ON_CONNECT)
        state = snapshot(repo)
        await sock.send_json({"type": "snapshot", "state": state, "events": events})
        last_sig = _signature(s)
        try:
            while True:
                await asyncio.sleep(POLL_SEC)
                new, offset = read_events(s, offset)
                for e in new:
                    await sock.send_json({"type": "event", "event": e})
                sig = _signature(s)
                if new or sig != last_sig:
                    last_sig = sig
                    await sock.send_json({"type": "state", "state": snapshot(repo)})
        except (WebSocketDisconnect, RuntimeError):
            return

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def _signature(s: Store) -> tuple:
    try:
        m = s.state_path.stat().st_mtime_ns
    except OSError:
        m = 0
    return m, s.runner_pid(), s.inbox_path.exists()


def serve(repo: Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True,
          page: str = "") -> int:
    import uvicorn
    url = f"http://{host}:{port}/{page}"
    print(f"Agent Office dashboard: {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(repo), host=host, port=port, log_level="warning")
    return 0
