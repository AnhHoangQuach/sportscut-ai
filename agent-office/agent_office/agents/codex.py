"""Codex CLI headless: `codex exec`, logged in with a ChatGPT plan."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from ..codex_provider import provider_info
from .base import AgentResult, CliAgent, subscription_env


class CodexAgent(CliAgent):
    name = "codex"

    def build_cmd(self, cwd: Path, extra: dict[str, Any]) -> list[str]:
        last = Path(tempfile.mkstemp(prefix="codex-last-", suffix=".txt")[1])
        extra["_last_msg"] = last
        sandbox = "read-only" if extra.get("role") == "read" else self.cfg.sandbox
        cmd = [self.cfg.cmd, "exec", "--json", "--sandbox", sandbox,
               "--skip-git-repo-check", "-C", str(cwd), "--output-last-message", str(last)]
        if self.cfg.network and sandbox == "workspace-write":
            cmd += ["-c", "sandbox_workspace_write.network_access=true"]
        if self.cfg.model:
            cmd += ["--model", self.cfg.model]
        return cmd + list(self.cfg.extra_args) + ["-"]  # prompt comes from stdin

    def child_env(self, cwd: Path | None = None) -> dict[str, str]:
        """The provider's own key (e.g. CODEX_LB_API_KEY for codex-lb) is passed through."""
        key = provider_info().env_key
        return subscription_env(cwd, self.cfg.env_file, keep=(key,) if key else ())

    def env_summary(self, env: dict[str, str]) -> str:
        info = provider_info()
        need = (f"; provider {info.name} needs {info.env_key}: {'set' if env.get(info.env_key) else 'MISSING'}"
                if info.env_key else f"; provider {info.name} (no env_key)")
        return super().env_summary(env) + need

    def env_problem(self) -> str:
        key = provider_info().env_key
        return key if key and not self.child_env().get(key) else ""

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
