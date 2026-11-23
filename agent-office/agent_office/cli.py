"""`office` command line."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

from .agents.base import API_KEY_VARS, subscription_env
from .config import load_config, write_default_config
from .models import AgentStatus, Stage
from .scheduler import next_step
from .store import Store

STAGE_ORDER = [s.value for s in Stage]


def _repo(args) -> Path:
    return Path(args.repo).resolve()


def write_team_rules(repo: Path) -> list[str]:
    """AGENTS.md (Codex) and CLAUDE.md (Claude) with the team's practices, if the repo has none."""
    from importlib import resources
    written = []
    for name in ("AGENTS.md", "CLAUDE.md"):
        if not (repo / name).exists():
            text = resources.files("agent_office.templates").joinpath(name).read_text(encoding="utf-8")
            (repo / name).write_text(text, encoding="utf-8")
            written.append(name)
    return written


def superpowers_installed() -> bool:
    root = Path.home() / ".claude" / "plugins"
    return root.exists() and any("superpowers" in p.name for p in root.rglob("*") if p.is_dir())


def cmd_init(args) -> int:
    repo = _repo(args)
    if not (repo / ".git").exists():
        print(f"{repo} is not a git repository (run `git init` first)")
        return 1
    store = Store(repo)
    store.init()
    cfg = write_default_config(store.dir)
    print(f"Agent office ready in {store.dir}\nEdit {cfg} (base_branch, test_cmd), then `office doctor`.")
    written = write_team_rules(repo)
    if written:
        print(f"Wrote team rules {', '.join(written)} (TDD, evidence before claims, measure first). "
              "Fill in 'Project specifics' and commit them so every worktree has them.")
    return 0


def _office(args):
    from .pipeline import Office
    return Office(_repo(args))


def cmd_request(args) -> int:
    text = Path(args.file).read_text(encoding="utf-8") if args.file else " ".join(args.text)
    if not text.strip():
        print("empty request")
        return 1
    for line in _office(args).submit({"cmd": "request", "text": text}):
        print(line)
    print("Run `office run` (or press Start in `office dashboard`) to let the team plan and build it.")
    return 0


def _nap(office, seconds: float) -> None:
    """Sleep, but wake early when a PO command lands in the inbox."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if office.store.inbox_path.exists():
            return
        time.sleep(min(2.0, max(0.0, end - time.monotonic())))


def cmd_run(args) -> int:
    office = _office(args)
    if not office.store.claim_runner():
        print(f"Another `office run` is already working on this repo (pid {office.store.runner_pid()}).")
        return 1
    office.is_runner = True
    for a in office.store.agents.values():  # sessions left over from a runner that was killed
        a.active = []
        if a.status == AgentStatus.WORKING:
            a.status = AgentStatus.IDLE
    office.store.save()
    office.store.event("runner_started", pid=os.getpid(), watch=bool(args.watch),
                       parallel=office.cfg.parallel)
    steps = 0
    sequential = args.once or args.max_steps or args.sequential
    if not sequential:
        print("Parallel mode: " + ", ".join(f"{n} x{k}" for n, k in office.cfg.parallel.items()) + " sessions.",
              flush=True)
    try:
        if not sequential:
            pool = ThreadPoolExecutor(max_workers=sum(office.cfg.parallel.values()) + 2,
                                      thread_name_prefix="office")
            running: set = set()
            try:
                while True:
                    running |= set(office.dispatch(pool))
                    if running:
                        done, running = wait(running, timeout=2, return_when=FIRST_COMPLETED)
                        steps += len(done)
                        continue
                    plan = next_step(office.store, office.clock(), office.cfg.merge_mode == "auto")
                    if plan.wait_until and not args.no_wait:
                        delay = max(5.0, (plan.wait_until - datetime.now(timezone.utc)).total_seconds())
                        print(f"Nothing to do while agents rest; sleeping {int(delay // 60)} min until "
                              f"{plan.wait_until.astimezone().strftime('%H:%M')} (Ctrl+C to stop, state is saved).",
                              flush=True)
                        _nap(office, min(delay, args.poll_max))
                        continue
                    if args.watch:
                        _nap(office, 5)
                        continue
                    for why in plan.waiting_on or []:
                        print(f"  waiting: {why}")
                    break
            finally:
                pool.shutdown(wait=True, cancel_futures=True)
        while sequential:
            s = office.step()
            if s is not None:
                steps += 1
                if args.once or (args.max_steps and steps >= args.max_steps):
                    break
                continue
            plan = next_step(office.store, office.clock(), office.cfg.merge_mode == "auto")
            if plan.wait_until and not args.no_wait:
                delay = max(5.0, (plan.wait_until - datetime.now(timezone.utc)).total_seconds())
                print(f"Nothing to do while agents rest; sleeping {int(delay // 60)} min until "
                      f"{plan.wait_until.astimezone().strftime('%H:%M')} (Ctrl+C to stop, state is saved).",
                      flush=True)
                _nap(office, min(delay, args.poll_max))
                continue
            if args.watch:
                _nap(office, 5)
                continue
            for why in plan.waiting_on or []:
                print(f"  waiting: {why}")
            break
    finally:
        office.store.release_runner()
        office.store.event("runner_stopped", pid=os.getpid(), steps=steps)
    print(f"{steps} step(s) done.")
    _print_status(office.store)
    if not office.store.requests:
        print("\nNo requests yet. Give the team something to build first, for example:\n"
              "  office request -f agent-office/examples/sportscut/po_request.md\n"
              "then run `office run` again.")
    return 0


def _print_status(store: Store) -> None:
    print("\nAgents:")
    for a in store.agents.values():
        extra = f" until {a.rest_until}" if a.rest_until else ""
        print(f"  {a.name:<7} {a.status.value}{extra}")
    if store.requests:
        print("Requests:")
        for r in store.requests.values():
            print(f"  {r.id} [{r.status}] {(r.text.strip().splitlines() or [''])[0][:70]}" + (f" ({r.note})" if r.note else ""))
    print("Tasks:")
    if not store.tasks:
        print("  (none)")
    for t in sorted(store.tasks.values(), key=lambda t: t.id):
        bits = []
        if t.review_round:
            bits.append(f"review {t.review_round}/3")
        if t.checkpoint:
            bits.append("checkpointed")
        if t.pr_url:
            bits.append(t.pr_url)
        if t.tl_issue:
            bits.append(f"Tech Lead: {t.tl_kind}")
        if t.dropped:
            bits.append(f"dropped: {t.dropped[:60]}")
        if t.blocked_reason:
            bits.append("PO: " + t.blocked_reason[:80])
        print(f"  {t.id} {t.stage.value:<8} {t.title[:50]:<50} {' | '.join(bits)}")


def cmd_status(args) -> int:
    store = Store(_repo(args)).load()
    _print_status(store)
    return 0


def cmd_board(args) -> int:
    store = Store(_repo(args)).load()
    cols = [s for s in STAGE_ORDER]
    for c in cols:
        items = [t for t in sorted(store.tasks.values(), key=lambda t: t.id) if t.stage.value == c]
        print(f"[{c.upper()}] " + (", ".join(f"{t.id} {t.title[:30]}" for t in items) or "-"))
    return 0


def cmd_show(args) -> int:
    store = Store(_repo(args)).load()
    t = store.tasks.get(args.task_id)
    if not t:
        print(f"no task {args.task_id}")
        return 1
    print(f"{t.id} [{t.stage.value}] {t.title}\n\n{t.brief}\n")
    if t.spec:
        print(f"Spec:\n{t.spec}\n")
    for label, items in (("Acceptance criteria", t.acceptance_criteria), ("Test plan", t.test_plan)):
        if items:
            print(label + ":\n" + "\n".join(f"  - {i}" for i in items) + "\n")
    for k in ("branch", "worktree", "pr_url", "blocked_reason"):
        if getattr(t, k):
            print(f"{k}: {getattr(t, k)}")
    if t.review_comments:
        print("Review comments:")
        for c in t.review_comments:
            print(f"  [{c.get('severity')}] {c.get('file')}:{c.get('line')} {c.get('text')}")
    print("\nHistory:")
    for h in t.history:
        if "from" in h:
            print(f"  {h['at']} {h['from']} -> {h['to']} {h.get('note', '')}")
    logs = store.logs_dir / t.id
    if logs.exists():
        print(f"\nLogs: {logs}")
    return 0


def cmd_answer(args) -> int:
    office = _office(args)
    cmd = {"cmd": "answer", "id": args.id, "text": " ".join(args.text)}
    for line in office.submit(cmd):
        print(line)
    return 0


def cmd_wake(args) -> int:
    for line in _office(args).submit({"cmd": "wake", "agent": args.agent}):
        print(line)
    return 0


def cmd_dashboard(args) -> int:
    try:
        from .dashboard.server import serve
    except ImportError as e:
        print(f"Dashboard dependencies missing ({e.name}). Install them with:\n"
              "  pip install -e './agent-office[dashboard]'")
        return 1
    Store(_repo(args)).load()  # fail early with a clear message if not initialised
    return serve(_repo(args), args.host, args.port, open_browser=not args.no_browser, page=args.page)


DEMO_REQUEST = """# SportsCut MVP: tự động cắt highlight trận bóng đá

Tôi cần CLI `sportscut cut match.mp4` tự tìm khoảnh khắc hay trong video bóng đá và xuất
tối đa 10 clip 10-30 giây, một file highlights.mp4 ghép lại và highlights.json liệt kê thời điểm.
Chỉ dùng tín hiệu rẻ (audio + chuyển cảnh), dùng ffmpeg, có test tự động.
"""


def cmd_demo(args) -> int:
    try:
        from .dashboard.server import serve
    except ImportError as e:
        print(f"Dashboard dependencies missing ({e.name}). Install them with:\n"
              "  pip install -e './agent-office[dashboard]'")
        return 1
    from . import runner_proc
    from .pipeline import Office

    repo = Path(args.dir).expanduser().resolve()
    fresh = not (repo / ".agent-office" / "state.json").exists()
    if fresh:
        repo.mkdir(parents=True, exist_ok=True)
        if not (repo / ".git").exists():
            ident = ["-c", "user.name=Agent Office", "-c", "user.email=agent-office@localhost"]
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
            (repo / "README.md").write_text("# SportsCut (demo)\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", *ident, "commit", "-q", "-m", "init"], cwd=repo, check=True)
        store = Store(repo)
        store.init()
        cfg = write_default_config(store.dir)
        text = cfg.read_text(encoding="utf-8")
        text = (text.replace("simulate = false", "simulate = true")
                    .replace("sim_delay = 3.0", f"sim_delay = {args.delay}")
                    .replace("open_pr = true", "open_pr = false"))
        cfg.write_text(text, encoding="utf-8")
        Office(repo).submit({"cmd": "request", "text": DEMO_REQUEST})
        print(f"Demo office created in {repo} (simulated agents, no quota used).")
    else:
        print(f"Reusing demo office in {repo}. Delete the folder to start over.")
    runner_proc.start(repo)
    return serve(repo, args.host, args.port, open_browser=not args.no_browser, page="office")


def cmd_stats(args) -> int:
    from . import stats
    store = Store(_repo(args)).load()
    st = stats.collect(store, load_config(store.dir))
    print(json.dumps(st, indent=2, ensure_ascii=False) if args.json else stats.render(st))
    return 0


def cmd_sync(args) -> int:
    merged = _office(args).sync_merged()
    print("merged: " + (", ".join(merged) if merged else "none"))
    return 0


def cmd_doctor(args) -> int:
    repo = _repo(args)
    ok = True
    leaked = [v for v in API_KEY_VARS if v in os.environ]
    if leaked:
        print(f"note: {', '.join(leaked)} set in your shell; Agent Office strips them so the CLIs use "
              "your subscription login.")
    store = Store(repo)
    cfg = load_config(store.dir) if store.exists() else None
    checks = [("git", ["git", "--version"]), ("gh", ["gh", "auth", "status"])]
    if cfg:
        checks += [("claude", [cfg.claude.cmd, "--version"]), ("codex", [cfg.codex.cmd, "--version"])]
    for name, cmd in checks:
        if not shutil.which(cmd[0]):
            print(f"MISSING {name}: `{cmd[0]}` not on PATH")
            ok = ok and name == "gh"
            continue
        p = subprocess.run(cmd, capture_output=True, text=True, env=subscription_env())
        print(f"{'ok' if p.returncode == 0 else 'FAIL':<7} {name}: {(p.stdout or p.stderr).strip().splitlines()[0:1]}")
        ok = ok and (p.returncode == 0 or name == "gh")
    for name in ("AGENTS.md", "CLAUDE.md"):
        print(f"{'ok' if (repo / name).exists() else 'note':<7} {name}: "
              + ("found" if (repo / name).exists() else "missing (`office init` writes a template)"))
    print(f"{'ok' if superpowers_installed() else 'note':<7} superpowers plugin for claude: "
          + ("installed" if superpowers_installed() else "not found (optional; the practices are also in the prompts)"))
    if not store.exists():
        print("FAIL    office: not initialised here (run `office init`)")
        return 1
    if args.live:
        from .pipeline import Office, prompt
        office = Office(repo)
        for name, agent in office.agents.items():
            res = agent.run(prompt("probe"), repo, None, probe=True)
            state = "limit" if res.limit else ("ok" if res.ok else "FAIL")
            print(f"{state:<7} {name} login probe: {res.text[:60]!r}")
            ok = ok and res.ok
    else:
        print("tip: `office doctor --live` sends one tiny prompt to each agent to confirm the login works")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="office", description="Agent Office: Claude (PM/TL) + Codex (dev/test)")
    p.add_argument("--repo", default=".", help="target git repository (default: current dir)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create .agent-office/ in the target repo").set_defaults(fn=cmd_init)
    r = sub.add_parser("request", help="add a Product Owner request")
    r.add_argument("text", nargs="*")
    r.add_argument("-f", "--file", help="read the request from a file")
    r.set_defaults(fn=cmd_request)
    run = sub.add_parser("run", help="work through the backlog")
    run.add_argument("--once", action="store_true", help="do a single step")
    run.add_argument("--max-steps", type=int, default=0)
    run.add_argument("--sequential", action="store_true", help="one step at a time (no parallel sessions)")
    run.add_argument("--no-wait", action="store_true", help="exit instead of sleeping while agents rest")
    run.add_argument("--watch", action="store_true",
                     help="keep running and wait for new requests instead of exiting when idle")
    run.add_argument("--poll-max", type=float, default=600, help=argparse.SUPPRESS)
    run.set_defaults(fn=cmd_run)
    sub.add_parser("status", help="agents, requests, tasks").set_defaults(fn=cmd_status)
    sub.add_parser("board", help="kanban view").set_defaults(fn=cmd_board)
    s = sub.add_parser("show", help="details of one task")
    s.add_argument("task_id")
    s.set_defaults(fn=cmd_show)
    a = sub.add_parser("answer", help="answer a blocked task (or retry a blocked request R-xxx)")
    a.add_argument("id")
    a.add_argument("text", nargs="*")
    a.set_defaults(fn=cmd_answer)
    w = sub.add_parser("wake", help="mark a resting agent available now")
    w.add_argument("agent", choices=["claude", "codex"])
    w.set_defaults(fn=cmd_wake)
    db = sub.add_parser("dashboard", help="open the 2D dashboard (needs: pip install './agent-office[dashboard]')")
    db.add_argument("--host", default="127.0.0.1")
    db.add_argument("--port", type=int, default=8765)
    db.add_argument("--no-browser", action="store_true")
    db.add_argument("--page", default="", choices=["", "office"], help="open the 3D office directly")
    db.set_defaults(fn=cmd_dashboard)
    dm = sub.add_parser("demo", help="watch simulated Claude + Codex build SportsCut in the 3D office (free)")
    dm.add_argument("--dir", default=str(Path.home() / "agent-office-demo"))
    dm.add_argument("--delay", type=float, default=3.0, help="seconds per simulated agent call")
    dm.add_argument("--host", default="127.0.0.1")
    dm.add_argument("--port", type=int, default=8765)
    dm.add_argument("--no-browser", action="store_true")
    dm.set_defaults(fn=cmd_demo)
    st = sub.add_parser("stats", help="agent usage, quota rests, conflicts and guardrail stops")
    st.add_argument("--json", action="store_true")
    st.set_defaults(fn=cmd_stats)
    sub.add_parser("sync", help="mark tasks done whose PRs were merged").set_defaults(fn=cmd_sync)
    d = sub.add_parser("doctor", help="check CLIs, logins and config")
    d.add_argument("--live", action="store_true")
    d.set_defaults(fn=cmd_doctor)
    args = p.parse_args(argv)
    try:
        return args.fn(args)
    except FileNotFoundError as e:
        print(e)
        return 1
    except KeyboardInterrupt:
        print("\nstopped; state is saved")
        return 130


if __name__ == "__main__":
    sys.exit(main())
