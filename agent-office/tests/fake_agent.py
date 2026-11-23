"""Stand-in for the `claude` and `codex` CLIs in tests.

Usage: fake_agent.py <claude|codex> [cli args...]   (prompt on stdin)

Behaviour is scripted through the JSON file in $FAKE_SCENARIO:
  {"codex:dev": [{"limit": "You've hit your usage limit. Try again in 2 hours.", "write": "half.py"}],
   "claude:review": [{"verdict": "changes"}, {"verdict": "approve"}]}
Each call pops the first scripted response for "<agent>:<kind>"; with none left it
uses the default happy-path behaviour. Every call is appended to $FAKE_SCENARIO.calls.
"""
import json
import os
import sys
from pathlib import Path


def kind_of(agent: str, prompt: str) -> str:
    if "Reply with exactly: OK" in prompt:
        return "probe"
    if agent == "claude":
        if "Split the request" in prompt:
            return "breakdown"
        if "implementation spec" in prompt:
            return "spec"
        if "Tech Lead reviewer" in prompt:
            return "review"
        if "has been built, reviewed and merged" in prompt:
            return "goal"
    else:
        if "**Tester**" in prompt:
            return "test"
        if "**Developer**" in prompt:
            return "dev"
    return "unknown"


def main() -> int:
    agent, args = sys.argv[1], sys.argv[2:]
    prompt = sys.stdin.read()
    kind = kind_of(agent, prompt)
    scen_path = Path(os.environ["FAKE_SCENARIO"])
    scen = json.loads(scen_path.read_text()) if scen_path.exists() else {}
    queue = scen.get(f"{agent}:{kind}", [])
    resp = queue.pop(0) if queue else {}
    scen[f"{agent}:{kind}"] = queue
    scen_path.write_text(json.dumps(scen))
    cwd = Path(args[args.index("-C") + 1]) if "-C" in args else Path.cwd()
    with open(str(scen_path) + ".calls", "a") as f:
        f.write(json.dumps({"agent": agent, "kind": kind, "cwd": str(cwd), "prompt": prompt,
                            "has_api_key": any(k in os.environ for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")),
                            "args": args, "path0": os.environ.get("PATH", "").split(os.pathsep)[0]}) + "\n")

    if resp.get("write"):
        (cwd / resp["write"]).write_text(resp.get("text", "# partial work\n"))
    if resp.get("limit"):
        sys.stderr.write(resp["limit"] + "\n")
        if agent == "claude":
            print(json.dumps({"type": "result", "is_error": True, "result": resp["limit"]}))
        return 1
    if resp.get("fail"):
        sys.stderr.write("boom\n")
        return 2

    if agent == "claude" and resp.get("questions"):
        out = json.dumps({"questions": resp["questions"]})
        print(json.dumps({"type": "result", "is_error": False, "result": out}))
        return 0
    if agent == "claude":
        if kind == "goal":
            out = json.dumps(resp.get("goal") or {"done": True, "summary": "Highlights CLI works."})
        elif kind == "breakdown":
            out = resp.get("result") or json.dumps({"tasks": [
                {"key": "1", "title": "Scaffold CLI", "brief": "Create the sportscut CLI.", "depends_on": []},
                {"key": "2", "title": "Audio excitement score", "brief": "Score audio.", "depends_on": ["1"]},
            ]})
        elif kind == "spec":
            out = "Here is the spec:\n```json\n" + json.dumps({
                "spec": "Add module.", "acceptance_criteria": ["AC1 works"], "test_plan": ["test_ac1"],
                "out_of_scope": []}) + "\n```"
        elif kind == "review":
            v = resp.get("verdict", "approve")
            out = json.dumps({"verdict": v, "summary": f"{v} summary",
                              "comments": [] if v == "approve" else
                              [{"file": "x.py", "line": 1, "severity": "blocker", "text": "fix it"}]})
        else:
            out = "OK"
        print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": out,
                          "session_id": "sess-1"}))
        return 0

    # codex
    last = Path(args[args.index("--output-last-message") + 1])
    if kind == "dev":
        n = len(list(cwd.glob("feature_*.py"))) + 1
        (cwd / f"feature_{n}.py").write_text(f"VALUE = {n}\n")
        msg = resp.get("message", "Implemented.")
    elif kind == "test":
        (cwd / ".office").mkdir(exist_ok=True)
        (cwd / ".office" / "TEST_REPORT.md").write_text("AC1 -> test_ac1 -> pass\n")
        msg = resp.get("message", "All good.\nRESULT: PASS")
    else:
        msg = "OK"
    print(json.dumps({"type": "thread.started", "thread_id": "th-1"}))
    last.write_text(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
