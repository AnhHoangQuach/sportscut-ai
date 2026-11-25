"""Claude Code headless: `claude -p --output-format json`, logged in with Pro/Max."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .base import AgentResult, CliAgent

# Claude only reads the repo; the orchestrator owns every write.
READ_ONLY_TOOLS = ["Read", "Grep", "Glob", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)",
                   "Bash(ls:*)"]
WRITE_TOOLS = ["Edit", "Write", "Bash"]


class ClaudeAgent(CliAgent):
    name = "claude"

    def build_cmd(self, cwd: Path, extra: dict[str, Any]) -> list[str]:
        cmd = [self.cfg.cmd, "-p", "--output-format", "json"]
        model = extra.get("model") or self.cfg.model  # the role's own model, else the CLI's
        if model:
            cmd += ["--model", model]
        if not extra.get("probe"):
            tools = WRITE_TOOLS if extra.get("role") == "write" else READ_ONLY_TOOLS
            cmd += ["--allowedTools", *tools,
                    *(f"Bash({c.strip()}:*)" for c in self.cfg.allowed_commands if c.strip())]
        return cmd + list(self.cfg.extra_args)

    def parse(self, res: AgentResult, extra: dict[str, Any]) -> None:
        out = res.stdout.strip()
        try:
            data = json.loads(out.splitlines()[-1] if out else "{}")
        except json.JSONDecodeError:
            res.text = out
            return
        if isinstance(data, dict):
            res.text = str(data.get("result", ""))
            res.session_id = str(data.get("session_id", ""))
            if data.get("is_error") and res.exit_code == 0:
                res.exit_code = 1
