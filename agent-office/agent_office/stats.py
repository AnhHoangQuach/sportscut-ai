"""Usage and throughput numbers for `office stats`, the dashboard and the 3D office."""
from __future__ import annotations

import json
from typing import Any

from .config import Config
from .models import Stage
from .store import Store


def collect(store: Store, cfg: Config) -> dict[str, Any]:
    counts = {"merge_conflict": 0, "conflict_resolved": 0, "guardrail": 0, "agent_resting": 0,
              "agent_failed": 0, "pr_merged": 0}
    if store.events_path.exists():
        with store.events_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    name = json.loads(line).get("event")
                except json.JSONDecodeError:
                    continue
                if name in counts:
                    counts[name] += 1
    agents = {}
    for name, a in store.agents.items():
        agents[name] = {
            "status": a.status.value, "sessions": len(a.active), "max_sessions": cfg.parallel.get(name, 1),
            "working_on": list(a.active), "calls_today": a.calls_today, "calls_day": a.calls_day,
            "max_calls_per_day": cfg.max_calls_per_day.get(name, 0), "calls_total": a.calls_total,
            "rests_total": a.rests_total, "limits_today": a.limits_today, "rest_until": a.rest_until,
        }
    tasks = list(store.tasks.values())
    done = [t for t in tasks if t.stage == Stage.DONE]
    return {
        "agents": agents,
        "tasks": {s.value: sum(1 for t in tasks if t.stage == s) for s in Stage},
        "done": len(done),
        "avg_review_rounds": round(sum(t.review_round for t in done) / len(done), 2) if done else 0,
        "events": counts,
    }


def render(st: dict[str, Any]) -> str:
    lines = ["Agents:"]
    for name, a in st["agents"].items():
        cap = a["max_calls_per_day"] or "∞"
        busy = f" on {', '.join(a['working_on'])}" if a["working_on"] else ""
        rest = f", resting until {a['rest_until']}" if a["rest_until"] else ""
        lines.append(f"  {name:<6} {a['status']:<8} sessions {a['sessions']}/{a['max_sessions']}{busy} | "
                     f"calls today {a['calls_today']}/{cap}, total {a['calls_total']} | "
                     f"limits today {a['limits_today']}, rests total {a['rests_total']}{rest}")
    t = st["tasks"]
    lines.append("Tasks: " + (", ".join(f"{k} {v}" for k, v in t.items() if v) or "none"))
    e = st["events"]
    lines.append(f"Merged {e['pr_merged']} | avg review rounds {st['avg_review_rounds']} | conflicts "
                 f"{e['merge_conflict']} (resolved {e['conflict_resolved']}) | guardrail stops {e['guardrail']} | "
                 f"agent failures {e['agent_failed']}")
    return "\n".join(lines)
