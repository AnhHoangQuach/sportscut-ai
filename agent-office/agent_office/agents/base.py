"""Shared plumbing for headless CLI agents. No API keys, ever."""
from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..limits import LimitHit, detect

# Removed from the child environment so each CLI falls back to its subscription login.
API_KEY_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "AZURE_OPENAI_API_KEY",
)


def subscription_env(cwd: Path | None = None) -> dict[str, str]:
    """Child env without API keys. A `.venv/` in cwd (made by setup_cmd) goes first on PATH."""
    env = {k: v for k, v in os.environ.items() if k not in API_KEY_VARS}
    env.setdefault("NO_COLOR", "1")
    venv = Path(cwd) / ".venv" if cwd else None
    if venv is not None:
        bindir = venv / ("Scripts" if os.name == "nt" else "bin")
        if bindir.is_dir():
            env["VIRTUAL_ENV"] = str(venv)
            env["PATH"] = str(bindir) + os.pathsep + env.get("PATH", "")
    return env


@dataclass
class AgentResult:
    agent: str
    exit_code: int | None
    stdout: str
    stderr: str
    text: str = ""            # the agent's final answer
    session_id: str = ""
    limit: LimitHit | None = None
    timed_out: bool = False
    log_path: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.limit is None and not self.timed_out

    def tail(self, n: int = 2000) -> str:
        return (self.stdout + "\n" + self.stderr)[-n:]


class CliAgent:
    name = "base"

    def __init__(self, cfg):
        self.cfg = cfg

    def build_cmd(self, cwd: Path, extra: dict[str, Any]) -> list[str]:  # pragma: no cover
        raise NotImplementedError

    def parse(self, res: AgentResult, extra: dict[str, Any]) -> None:
        res.text = res.stdout.strip()

    def run(self, prompt: str, cwd: Path, log_path: Path | None = None, **extra: Any) -> AgentResult:
        cmd = self.build_cmd(Path(cwd), extra)
        try:
            p = subprocess.run(
                cmd, input=prompt, cwd=cwd, env=subscription_env(Path(cwd)), capture_output=True,
                text=True, timeout=self.cfg.timeout_sec,
            )
            res = AgentResult(self.name, p.returncode, p.stdout, p.stderr)
        except subprocess.TimeoutExpired as e:
            res = AgentResult(self.name, None, _s(e.stdout), _s(e.stderr), timed_out=True)
        except FileNotFoundError:
            res = AgentResult(self.name, 127, "", f"command not found: {cmd[0]}")
        self.parse(res, extra)
        res.limit = detect(self.name, res.stdout, res.stderr, res.exit_code)
        if log_path:
            log_path.write_text(
                f"$ {' '.join(cmd)}\n--- prompt ---\n{prompt}\n--- exit {res.exit_code} "
                f"timed_out={res.timed_out} limit={res.limit} ---\n--- stdout ---\n{res.stdout}\n"
                f"--- stderr ---\n{res.stderr}\n",
                encoding="utf-8",
            )
            res.log_path = str(log_path)
        return res


def _s(b) -> str:
    if b is None:
        return ""
    return b.decode("utf-8", "replace") if isinstance(b, bytes) else b


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of an LLM answer (fenced or bare)."""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            elif c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object found in agent output")
