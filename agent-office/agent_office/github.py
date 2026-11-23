"""GitHub access for PRs and merges, checked from the office process itself.

`gh` and `git push` always run in the office process with the user's own environment (HOME,
keychain, GH_TOKEN, network): never inside an agent sandbox. When they fail, the office tells
apart an environment problem only the user can fix on their machine (not logged in, no
permission on the repo, no network) from a technical one for the Tech Lead.
"""
from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

API_HOST = "api.github.com"
WRITE_PERMISSIONS = ("ADMIN", "MAINTAIN", "WRITE")
PERMISSION_JQ = ('.permissions | if .admin then "ADMIN" elif .maintain then "MAINTAIN" elif .push then "WRITE" '
                 'elif .triage then "TRIAGE" else "READ" end')

_NETWORK = re.compile(
    r"could not resolve host|no such host|name resolution|nodename nor servname|dial tcp|i/o timeout|"
    r"connection (?:refused|reset|timed out)|network is unreachable|TLS handshake timeout|"
    r"error connecting to|operation timed out|unable to access .*: (?:Failed|Could not)", re.IGNORECASE)
_AUTH = re.compile(
    r"gh auth login|not logged (?:in|into)|authentication (?:failed|required)|HTTP 401|bad credentials|"
    r"requires authentication|token .*(?:invalid|expired)|Permission denied \(publickey\)|"
    r"could not read Username|terminal prompts disabled", re.IGNORECASE)
_PERMISSION = re.compile(
    r"HTTP 403|must be a collaborator|resource not accessible|does not have (?:the correct )?permission|"
    r"permission to .* denied|not have access|Could not resolve to a Repository|repository not found|"
    r"HTTP 404", re.IGNORECASE)


def classify(error: str) -> str:
    """network | auth | permission | other (for a failed `git push` / `gh` command)."""
    if _AUTH.search(error):
        return "auth"
    if _PERMISSION.search(error):
        return "permission"
    if _NETWORK.search(error):
        return "network"
    return "other"


def gh_env() -> dict[str, str]:
    """The office's own environment (the user's gh login/keychain/GH_TOKEN), never prompting."""
    env = dict(os.environ)
    env["GH_PROMPT_DISABLED"] = "1"
    env["GH_NO_UPDATE_NOTIFIER"] = "1"
    env.setdefault("NO_COLOR", "1")
    return env


def run_gh(args: list[str], cwd: Path, input: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["gh", *args], cwd=cwd, input=input, capture_output=True, text=True,
                              env=gh_env(), timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["gh", *args], 1, "", f"gh {' '.join(args[:2])}: operation timed out")


def repo_slug(repo: Path, remote: str) -> str:
    """owner/name of a github.com remote, or '' when the remote is not on github.com."""
    p = subprocess.run(["git", "remote", "get-url", remote], cwd=repo, capture_output=True, text=True)
    return slug_from_url(p.stdout.strip()) if p.returncode == 0 else ""


def slug_from_url(url: str) -> str:
    m = re.match(r"^(?:https?://(?:[^@/]+@)?github\.com/|(?:ssh://)?git@github\.com[:/])"
                 r"([^/]+)/([^/]+?)(?:\.git)?/?$", url.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else ""


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hint: str = ""   # Vietnamese: what to run on the user's machine


def _reachable(host: str, timeout: float = 5.0) -> str:
    try:
        socket.create_connection((host, 443), timeout=timeout).close()
        return ""
    except OSError as e:
        return str(e) or e.__class__.__name__


def preflight(repo: Path, remote: str = "origin") -> list[Check]:
    """What PR creation and merging need, checked from this process. Stops at the first failure
    that makes the later checks meaningless."""
    checks: list[Check] = []
    if not shutil.which("gh"):
        return [Check("gh", False, "`gh` không có trên PATH của tiến trình office",
                      "Cài GitHub CLI: `brew install gh`, rồi `gh auth login`.")]
    slug = repo_slug(repo, remote)
    if slug:
        checks.append(Check("remote", True, f"{remote} -> github.com/{slug}"))
    else:
        url = subprocess.run(["git", "remote", "get-url", remote], cwd=repo, capture_output=True,
                             text=True).stdout.strip()
        checks.append(Check("remote", False, f"remote `{remote}` không trỏ tới github.com ({url or 'không có'})",
                            f"`git remote add {remote} https://github.com/<owner>/<repo>.git` "
                            f"(hoặc `git remote set-url {remote} ...`), hoặc sửa `remote` trong config.toml."))
        return checks
    err = _reachable(API_HOST)
    if err:
        checks.append(Check("network", False, f"không kết nối được {API_HOST}:443 ({err})",
                            "Kiểm tra mạng/VPN/proxy. Nếu đang chạy office bên trong sandbox (ví dụ do "
                            "Claude Code hay Codex khởi động), hãy chạy `office run` trong Terminal thường."))
        return checks
    checks.append(Check("network", True, f"{API_HOST}:443 kết nối được"))
    token_vars = [v for v in ("GH_TOKEN", "GITHUB_TOKEN") if os.environ.get(v)]
    p = run_gh(["api", "user", "--jq", ".login"], repo, timeout=30)
    if p.returncode != 0:
        why = (p.stderr or p.stdout).strip().splitlines()[:1]
        hint = "Chạy `gh auth login --hostname github.com --git-protocol https --web`, rồi `gh auth status`."
        if token_vars:
            hint = (f"{' và '.join(token_vars)} đang được đặt và ghi đè lần đăng nhập của gh. Chạy "
                    f"`unset {' '.join(token_vars)}` (và xoá khỏi ~/.zshrc nếu có), rồi `gh auth login`.")
        checks.append(Check("gh auth", False, f"gh chưa đăng nhập được ({why[0] if why else 'lỗi không rõ'})", hint))
        return checks
    login = p.stdout.strip()
    checks.append(Check("gh auth", True, f"đăng nhập là {login}" + (f" (qua {token_vars[0]})" if token_vars else "")))
    # REST, not GraphQL: works wherever `gh api` works (proxies that only allow REST included).
    p = run_gh(["api", f"repos/{slug}", "--jq", PERMISSION_JQ], repo, timeout=30)
    perm = p.stdout.strip() if p.returncode == 0 else ""
    if perm in WRITE_PERMISSIONS:
        checks.append(Check("repo permission", True, f"{login} có quyền {perm} trên {slug}"))
    else:
        owner = slug.split("/")[0]
        why = perm or ((p.stderr or p.stdout).strip().splitlines() or ["không đọc được repo"])[0]
        checks.append(Check("repo permission", False, f"{login} không có quyền ghi trên {slug} ({why})",
                            f"Tài khoản gh đang dùng là {login}. Nếu repo của tài khoản {owner}: "
                            f"`gh auth login` (hoặc `gh auth switch --user {owner}` nếu đã đăng nhập cả hai), "
                            f"rồi `gh auth setup-git`. Nếu không, thêm {login} làm collaborator có quyền Write."))
    return checks


def problems(checks: list[Check]) -> list[Check]:
    return [c for c in checks if not c.ok]


def report(checks: list[Check]) -> str:
    """Vietnamese, for the PO message and the task: what failed and what to run."""
    bad = problems(checks)
    if not bad:
        return "Kiểm tra GitHub đều ổn."
    return " ".join(f"[{c.name}] {c.detail}. Cách sửa: {c.hint}" for c in bad)
