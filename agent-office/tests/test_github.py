"""PR creation and merging run in the office process with the user's own gh login and network.
When GitHub refuses (not logged in, no permission, no network) the office reports the exact fix to
the user instead of letting the Tech Lead guess and wait; it resumes by itself once it is fixed."""
import json
import os
import sys

import pytest

from agent_office import github
from agent_office.cli import main as office_main
from agent_office.github import Check
from agent_office.models import Stage
from agent_office.pipeline import ENV_MARK

from conftest import sh
from test_practices import set_cfg
from test_techlead import events, po_messages

FAKE_GH = """\
import json, os, sys
spec = json.load(open(os.environ["FAKE_GH"]))
args = sys.argv[1:]
with open(os.environ["FAKE_GH"] + ".calls", "a") as f:
    f.write(json.dumps(args) + "\\n")
r = spec.get(" ".join(args[:2]), {"rc": 0, "out": "https://github.com/o/r/pull/1"})
sys.stdout.write(r.get("out", "") + "\\n")
sys.stderr.write(r.get("err", ""))
sys.exit(r.get("rc", 0))
"""

OK = [Check("network", True, "ok"), Check("gh auth", True, "đăng nhập là AnhHoangQuach"),
      Check("repo permission", True, "ADMIN")]
DENIED = [Check("gh auth", True, "đăng nhập là other-account"),
          Check("repo permission", False, "other-account không có quyền ghi trên AnhHoangQuach/sportscut-ai",
                "`gh auth switch --user AnhHoangQuach`")]


@pytest.fixture
def gh(env, monkeypatch):
    """open_pr = true against a local bare remote, with a scripted `gh` first on PATH."""
    bare = env.tmp / "remote.git"
    sh(env.tmp, "git", "init", "-q", "--bare", str(bare))
    sh(env.repo, "git", "remote", "add", "origin", str(bare))
    sh(env.repo, "git", "push", "-q", "origin", "main")
    set_cfg(env, ("open_pr = false", "open_pr = true"))
    exe = env.tmp / "bin" / "gh"
    exe.write_text(f"#!/bin/sh\nexec {sys.executable} {env.tmp / 'fake_gh.py'} \"$@\"\n")
    exe.chmod(0o755)
    (env.tmp / "fake_gh.py").write_text(FAKE_GH)
    spec = env.tmp / "gh.json"
    monkeypatch.setenv("FAKE_GH", str(spec))
    monkeypatch.setenv("PATH", f"{env.tmp / 'bin'}:{os.environ['PATH']}")

    def script(**cmds):
        spec.write_text(json.dumps({k.replace("_", " "): v for k, v in cmds.items()}))
    script()
    return script


def office_with(env, checks):
    office = env.office()
    calls = []

    def fake_preflight(repo, remote):
        calls.append(remote)
        return checks()
    office.github_preflight = fake_preflight
    return office, calls


@pytest.mark.parametrize("err,kind", [
    ("gh pr create failed: GraphQL: must be a collaborator (createPullRequest)", "permission"),
    ("git push -u origin x failed: remote: Permission to A/b.git denied to c.\nfatal: ... error: 403", "permission"),
    ("gh pr create failed: To get started with GitHub CLI, please run:  gh auth login", "auth"),
    ("gh pr create failed: HTTP 401: Bad credentials (https://api.github.com/graphql)", "auth"),
    ("git push failed: fatal: unable to access 'https://github.com/a/b.git/': Could not resolve host: github.com",
     "network"),
    ("gh pr create failed: error connecting to api.github.com", "network"),
    ("gh pr merge failed: Pull request is not mergeable: the base branch policy prohibits the merge", "other"),
])
def test_github_errors_are_classified(err, kind):
    assert github.classify(err) == kind


def test_repo_slug_from_remote_urls():
    assert github.slug_from_url("https://github.com/AnhHoangQuach/sportscut-ai.git") == "AnhHoangQuach/sportscut-ai"
    assert github.slug_from_url("git@github.com:AnhHoangQuach/sportscut-ai.git") == "AnhHoangQuach/sportscut-ai"
    assert github.slug_from_url("https://x-access-token@github.com/o/r") == "o/r"
    assert github.slug_from_url("/tmp/remote.git") == ""


def test_permission_failure_is_reported_to_the_user_not_waited_on_by_the_tech_lead(env, gh):
    gh(pr_create={"rc": 1, "err": "GraphQL: must be a collaborator (createPullRequest)"})
    state = {"checks": DENIED}
    office, calls = office_with(env, lambda: state["checks"])
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    assert t1.stage == Stage.BLOCKED and t1.blocked_reason.startswith(ENV_MARK) and not t1.tl_issue
    assert "gh auth switch --user AnhHoangQuach" in t1.blocked_reason
    assert not [c for c in env.calls() if c["kind"] == "techlead"]
    msg = next(e for e in po_messages(env.repo) if e["topic"] == "env" and e["task_id"] == "T-001")
    assert "Cần anh sửa trên máy" in msg["text"] and "office doctor" in msg["text"]
    assert [e for e in events(env.repo) if e["event"] == "env_problem"]
    # A new office start does not hand it to the Tech Lead either.
    assert office.triage() == []
    # Fixed on the machine: within the recheck interval nothing is checked, after it the PR step resumes.
    state["checks"], n = OK, len(calls)
    gh()
    office.step()
    assert len(calls) == n and t1.stage == Stage.BLOCKED
    env.advance(minutes=6)
    assert "T-001" in office.recheck_environment()
    assert t1.stage == Stage.PR and t1.blocked_reason == ""
    env.run_all(office)
    assert t1.pr_url and t1.stage == Stage.PR  # manual merge mode: the PR is open for the PO


def test_network_errors_back_off_briefly_then_are_reported(env, gh):
    gh(pr_create={"rc": 1, "err": "error connecting to api.github.com"})
    office, calls = office_with(env, lambda: [Check("network", False, "không kết nối được api.github.com:443",
                                                    "Kiểm tra mạng/VPN/proxy.")])
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    waits = []
    for _ in range(4):
        assert t1.stage == Stage.PR and t1.retry_at and not t1.tl_issue
        waits.append(t1.retry_at)
        env.advance(minutes=16)
        env.run_all(office)
    assert len(set(waits)) == 4
    assert t1.stage == Stage.BLOCKED and t1.blocked_reason.startswith(ENV_MARK) and "api.github.com" in t1.blocked_reason
    assert not [c for c in env.calls() if c["kind"] == "techlead"]
    retries = [e for e in events(env.repo) if e["event"] == "github_retry" and e["task_id"] == "T-001"]
    assert [e["minutes"] for e in retries] == [2, 5, 10, 15]


def test_other_merge_failures_still_go_to_the_tech_lead(env, gh):
    gh(pr_create={"rc": 1, "err": "Pull request is not mergeable: the base branch policy prohibits the merge"})
    office, calls = office_with(env, lambda: OK)
    office.add_request("Cut highlights")
    env.run_all(office)
    t1 = office.store.tasks["T-001"]
    tl = [c for c in env.calls() if c["kind"] == "techlead"]
    assert tl and "merge_failed" in tl[0]["prompt"] and "not mergeable" in tl[0]["prompt"]
    assert not t1.blocked_reason.startswith(ENV_MARK) and calls == []


def test_gh_is_pinned_to_the_remote_repo(env, gh):
    gh()
    sh(env.repo, "git", "remote", "set-url", "origin", "https://github.com/AnhHoangQuach/sportscut-ai.git")
    sh(env.repo, "git", "remote", "set-url", "--push", "origin", str(env.tmp / "remote.git"))
    office, _ = office_with(env, lambda: OK)
    office.add_request("Cut highlights")
    env.run_all(office)
    created = [json.loads(x) for x in (env.tmp / "gh.json.calls").read_text().splitlines() if '"create"' in x]
    assert created and all(c[2:4] == ["-R", "AnhHoangQuach/sportscut-ai"] for c in created)


def test_preflight_names_the_account_and_the_fix(env, gh, monkeypatch):
    sh(env.repo, "git", "remote", "set-url", "origin", "https://github.com/AnhHoangQuach/sportscut-ai.git")
    monkeypatch.setattr(github, "_reachable", lambda host, timeout=5.0: "")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    gh(api_user={"out": "other-account"}, **{"api_repos/AnhHoangQuach/sportscut-ai": {"out": "READ"}})
    checks = github.preflight(env.repo)
    assert [c.name for c in checks] == ["remote", "network", "gh auth", "repo permission"]
    bad = github.problems(checks)
    assert [c.name for c in bad] == ["repo permission"]
    assert "other-account" in bad[0].detail and "gh auth switch --user AnhHoangQuach" in bad[0].hint
    gh(api_user={"rc": 1, "err": "To get started with GitHub CLI, please run:  gh auth login"})
    monkeypatch.setenv("GH_TOKEN", "stale")
    bad = github.problems(github.preflight(env.repo))
    assert bad[0].name == "gh auth" and "unset GH_TOKEN" in bad[0].hint
    gh(api_user={"out": "AnhHoangQuach"}, **{"api_repos/AnhHoangQuach/sportscut-ai": {"out": "ADMIN"}})
    monkeypatch.delenv("GH_TOKEN")
    assert github.problems(github.preflight(env.repo)) == []


def test_doctor_fails_with_a_vietnamese_fix_when_github_is_not_usable(env, gh, monkeypatch, capsys):
    monkeypatch.setattr(github, "preflight", lambda repo, remote="origin": DENIED)
    assert office_main(["--repo", str(env.repo), "doctor"]) == 1
    out = capsys.readouterr().out
    assert "FAIL    repo permission" in out and "-> `gh auth switch --user AnhHoangQuach`" in out
    monkeypatch.setattr(github, "preflight", lambda repo, remote="origin": OK)
    office_main(["--repo", str(env.repo), "doctor"])  # the fake codex has no --version: only GitHub matters
    out = capsys.readouterr().out
    assert "ok      repo permission" in out and "-> " not in out
