import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from agent_office.cli import main as office_main
from agent_office.pipeline import Office

FAKE = Path(__file__).parent / "fake_agent.py"


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout


class Env:
    def __init__(self, tmp: Path, monkeypatch):
        self.tmp = tmp
        self.repo = tmp / "sportscut"
        self.repo.mkdir()
        sh(self.repo, "git", "init", "-q", "-b", "main")
        sh(self.repo, "git", "config", "user.email", "t@t")
        sh(self.repo, "git", "config", "user.name", "t")
        (self.repo / "README.md").write_text("# sportscut\n")
        sh(self.repo, "git", "add", ".")
        sh(self.repo, "git", "commit", "-q", "-m", "init")
        bindir = tmp / "bin"
        bindir.mkdir()
        for name in ("claude", "codex"):
            p = bindir / name
            p.write_text(f"#!/bin/sh\nexec {sys.executable} {FAKE} {name} \"$@\"\n")
            p.chmod(0o755)
        self.scenario = tmp / "scenario.json"
        monkeypatch.setenv("FAKE_SCENARIO", str(self.scenario))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-stripped")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-should-be-stripped")
        assert office_main(["--repo", str(self.repo), "init"]) == 0
        cfg = self.repo / ".agent-office" / "config.toml"
        text = cfg.read_text()
        text = text.replace('cmd = "claude"', f'cmd = "{bindir / "claude"}"')
        text = text.replace('cmd = "codex"', f'cmd = "{bindir / "codex"}"')
        text = text.replace("open_pr = true", "open_pr = false")
        cfg.write_text(text)
        self.now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
        self.lines: list[str] = []

    def script(self, **queues):
        self.scenario.write_text(json.dumps({k.replace("_", ":", 1): v for k, v in queues.items()}))

    def office(self) -> Office:
        return Office(self.repo, clock=lambda: self.now, echo=self.lines.append)

    def advance(self, **kw):
        self.now += timedelta(**kw)

    def run_all(self, office: Office | None = None, limit: int = 50) -> Office:
        office = office or self.office()
        for _ in range(limit):
            if office.step() is None:
                return office
        raise AssertionError("pipeline did not settle")

    def calls(self):
        p = Path(str(self.scenario) + ".calls")
        return [json.loads(line) for line in p.read_text().splitlines()] if p.exists() else []

    def merge(self, branch: str):
        sh(self.repo, "git", "merge", "-q", "--no-ff", "-m", f"merge {branch}", branch)


@pytest.fixture
def env(tmp_path, monkeypatch):
    return Env(tmp_path, monkeypatch)
