"""Codex CLI headless: `codex exec`, logged in with a ChatGPT plan."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from .base import AgentResult, CliAgent


class CodexAgent(CliAgent):
    name = "codex"

    def build_cmd(self, cwd: Path, extra: dict[str, Any]) -> list[str]:
        last = Path(tempfile.mkstemp(prefix="codex-last-", suffix=".txt")[1])
        extra["_last_msg"] = last
        cmd = [self.cfg.cmd, "exec", "--json", "--sandbox", self.cfg.sandbox,
               "--skip-git-repo-check", "-C", str(cwd), "--output-last-message", str(last)]
        if self.cfg.network and self.cfg.sandbox == "workspace-write":
            cmd += ["-c", "sandbox_workspace_write.network_access=true"]
        if self.cfg.model:
            cmd += ["--model", self.cfg.model]
        return cmd + list(self.cfg.extra_args) + ["-"]  # prompt comes from stdin

    def parse(self, res: AgentResult, extra: dict[str, Any]) -> None:
        last: Path | None = extra.get("_last_msg")
        if last and last.exists():
            res.text = last.read_text(encoding="utf-8", errors="replace").strip()
            last.unlink(missing_ok=True)
        for line in res.stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            sid = ev.get("thread_id") or ev.get("session_id")
            if sid and not res.session_id:
                res.session_id = str(sid)
        if not res.text:
            res.text = res.stdout.strip()[-4000:]
