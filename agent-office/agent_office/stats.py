"""Usage and throughput numbers for `office stats`, the dashboard and the 3D office."""
from __future__ import annotations

import json
from typing import Any

from .config import Config
from .models import ROLE_TITLE, Stage
from .store import Store


def collect(store: Store, cfg: Config) -> dict[str, Any]:
    counts = {"merge_conflict": 0, "conflict_resolved": 0, "guardrail": 0, "agent_resting": 0,
              "agent_failed": 0, "agent_failover": 0, "pr_merged": 0}
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
            "provider": a.provider, "title": ROLE_TITLE.get(name, name),
            "status": a.status.value, "sessions": len(a.active), "max_sessions": cfg.parallel.get(name, 1),
            "working_on": list(a.active), "calls_today": a.calls_today, "calls_day": a.calls_day,
            "calls_total": a.calls_total, "rests_total": a.rests_total, "limits_today": a.limits_today,
            "rest_until": a.rest_until,
        }
    # One subscription per CLI: its quota, daily budget and rests are shared by all its roles.
    providers = {}
    for p in store.providers():
        mates = store.roles_of(p)
        day = max((m.calls_day for m in mates), default="")
        providers[p] = {
            "roles": [m.name for m in mates], "status": "resting" if mates[0].status.value == "resting" else (
                "working" if any(m.status.value == "working" for m in mates) else "idle"),
            "rest_until": mates[0].rest_until, "rest_cause": mates[0].rest_cause,
            "calls_today": sum(m.calls_today for m in mates if m.calls_day == day), "calls_day": day,
            "max_calls_per_day": cfg.max_calls_per_day.get(p, 0),
            "sessions": sum(len(m.active) for m in mates), "max_sessions": cfg.cli_parallel.get(p, 0),
            "calls_total": sum(m.calls_total for m in mates), "rests_total": sum(m.rests_total for m in mates),
            "limits_today": sum(m.limits_today for m in mates if m.calls_day == day),
        }
    tasks = list(store.tasks.values())
    done = [t for t in tasks if t.stage == Stage.DONE]
    return {
        "agents": agents,
        "providers": providers,
        "tasks": {s.value: sum(1 for t in tasks if t.stage == s) for s in Stage},
        "done": len(done),
        "avg_review_rounds": round(sum(t.review_round for t in done) / len(done), 2) if done else 0,
        "events": counts,
        "eval": {"metric": cfg.eval_metric, "enabled": bool(cfg.eval_cmd),
                 "baseline": store.meta.get("eval_baseline"),
                 "history": store.meta.get("eval_history", [])[-20:]},
    }


def render(st: dict[str, Any]) -> str:
    lines = ["Subscriptions (quota shared by their roles):"]
    for name, p in st.get("providers", {}).items():
        cap = p["max_calls_per_day"] or "∞"
        rest = f", resting until {p['rest_until']} ({p['rest_cause']})" if p["rest_until"] else ""
        lines.append(f"  {name:<6} {p['status']:<8} roles {', '.join(p['roles'])} | calls today "
                     f"{p['calls_today']}/{cap}, total {p['calls_total']} | limits today {p['limits_today']}, "
                     f"rests total {p['rests_total']}{rest}")
    lines.append("Agents (one per role):")
    for name, a in st["agents"].items():
        busy = f" on {', '.join(a['working_on'])}" if a["working_on"] else ""
        lines.append(f"  {name:<6} @{a['provider']:<6} {a['status']:<8} sessions {a['sessions']}/{a['max_sessions']}"
                     f"{busy} | calls today {a['calls_today']}, total {a['calls_total']}")
    t = st["tasks"]
    lines.append("Tasks: " + (", ".join(f"{k} {v}" for k, v in t.items() if v) or "none"))
    e = st["events"]
    lines.append(f"Merged {e['pr_merged']} | avg review rounds {st['avg_review_rounds']} | conflicts "
                 f"{e['merge_conflict']} (resolved {e['conflict_resolved']}) | guardrail stops {e['guardrail']} | "
                 f"agent failures {e['agent_failed']} | failovers {e['agent_failover']}")
    ev = st["eval"]
    if ev["enabled"]:
        hist = " → ".join(f"{h['score']:.3f}" for h in ev["history"][-8:]) or "no merges measured yet"
        lines.append(f"Quality ({ev['metric']}): {hist}")
    return "\n".join(lines)
