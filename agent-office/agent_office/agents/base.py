"""Shared plumbing for headless CLI agents. No API keys, ever."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..codex_provider import missing_env_var, read_env_file
from ..limits import LimitHit, detect

# Removed from the child environment so each CLI falls back to its subscription login.
API_KEY_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "AZURE_OPENAI_API_KEY",
)


def subscription_env(cwd: Path | None = None, env_file: Path | str | None = None,
                     keep: tuple[str, ...] = ()) -> dict[str, str]:
    """Child env without API keys. A `.venv/` in cwd (made by setup_cmd) goes first on PATH.

    `keep` names variables the CLI itself needs even if they look like API keys (the key of a
    custom Codex provider such as codex-lb). Variables in `env_file` (`.agent-office/.env`, never
    committed) are added as written: the user put them there for the agents on purpose."""
    env = {k: v for k, v in os.environ.items() if k not in API_KEY_VARS or k in keep}
    env.update(read_env_file(env_file))
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

    def child_env(self, cwd: Path | None = None) -> dict[str, str]:
        return subscription_env(cwd, getattr(self.cfg, "env_file", ""))

    def env_problem(self) -> str:
        """Name of a variable the CLI needs but will not get ("" = none known)."""
        return ""

    def server_problem(self) -> str:
        """Why the CLI's own model server cannot be reached right now ("" = fine or unknown)."""
        return ""

    def env_summary(self, env: dict[str, str]) -> str:
        """Where the extra variables came from, names only (never values): written to every call log."""
        path = getattr(self.cfg, "env_file", "") or ""
        if not path:
            return "no env_file"
        names = sorted(read_env_file(path))
        state = "exists" if Path(path).is_file() else "missing"
        return f"env_file {path} ({state}) gives {', '.join(names) or 'nothing'}"

    def run(self, prompt: str, cwd: Path, log_path: Path | None = None, **extra: Any) -> AgentResult:
        """Run the CLI. Output goes to the log as it arrives (`tail -f` it); a CLI that reports a
        missing environment variable is stopped at once, since it cannot recover by itself."""
        cmd = self.build_cmd(Path(cwd), extra)
        env = self.child_env(Path(cwd))
        log = None
        if log_path:
            log = log_path.open("w", encoding="utf-8")
            log.write(f"$ {' '.join(cmd)}\n--- env: {self.env_summary(env)} ---\n--- prompt ---\n{prompt}\n"
                      "--- live output ---\n")
            log.flush()
            res_log = str(log_path)
        try:
            res = self._spawn(cmd, prompt, cwd, env, log)
        finally:
            if log:
                log.close()
        self.parse(res, extra)
        res.limit = detect(self.name, res.stdout, res.stderr, res.exit_code)
        if log_path:
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"--- exit {res.exit_code} timed_out={res.timed_out} limit={res.limit} ---\n"
                        f"--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}\n")
            res.log_path = res_log
        return res

    def _spawn(self, cmd: list[str], prompt: str, cwd: Path, env: dict[str, str], log) -> AgentResult:
        try:
            p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return AgentResult(self.name, 127, "", f"command not found: {cmd[0]}")
        out: dict[str, list[str]] = {"stdout": [], "stderr": []}
        lock = threading.Lock()
        fatal = threading.Event()

        def pump(stream, key: str) -> None:
            for line in stream:
                with lock:
                    out[key].append(line)
                    if log:
                        log.write(line)
                        log.flush()
                if missing_env_var(line):
                    fatal.set()

        readers = [threading.Thread(target=pump, args=(p.stdout, "stdout"), daemon=True),
                   threading.Thread(target=pump, args=(p.stderr, "stderr"), daemon=True)]
        for t in readers:
            t.start()
        try:
            p.stdin.write(prompt)
            p.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        deadline = time.monotonic() + self.cfg.timeout_sec
        timed_out = False
        while p.poll() is None:
            if fatal.is_set():
                time.sleep(0.5)  # let the CLI finish printing, then stop it
                if p.poll() is None:
                    p.terminate()
                break
            if time.monotonic() > deadline:
                timed_out = True
                p.kill()
                break
            try:
                p.wait(timeout=0.2)  # returns as soon as the CLI exits
            except subprocess.TimeoutExpired:
                pass
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
        for t in readers:
            t.join(timeout=5)
        code = None if timed_out else p.returncode
        if fatal.is_set() and code == 0:
            code = 1
        return AgentResult(self.name, code, "".join(out["stdout"]), "".join(out["stderr"]), timed_out=timed_out)


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
