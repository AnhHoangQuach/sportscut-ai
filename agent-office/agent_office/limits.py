"""Usage-limit detection for subscription CLIs (claude -p, codex exec).

ALL detection patterns live in this module. When a CLI changes its wording, add
the new phrase to STRONG_PATTERNS or WEAK_PATTERNS (and a test in tests/test_limits.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Phrases that mean "this account is out of quota for now". Matched on any run.
STRONG_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"usage limit reached",
        r"usage_limit_reached",
        r"hit your (?:usage )?limit",
        r"\b(?:5-hour|five-hour|weekly|daily|session|opus) limit reached",
        r"limit reached\s*[∙·|•-]?\s*resets",
        r"quota (?:exceeded|exhausted)",
    ]
]

# Weaker hints: only trusted when the CLI also exited non-zero, because agent
# output (code, diffs, logs) can legitimately contain these words.
WEAK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"rate[ _-]?limit(?:ed| exceeded|_error)",
        r"too many requests",
        r"(?:status|error|code|http)\D{0,6}429\b",
        r"out of (?:credits|quota)",
        r"try again (?:in|at) ",
    ]
]

# Safety margin added to any reset time we parse.
RESET_MARGIN = timedelta(minutes=1)

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


@dataclass
class LimitHit:
    agent: str
    matched: str
    reset_at: datetime | None  # aware UTC datetime, None if the CLI did not say


def detect(agent: str, stdout: str, stderr: str, exit_code: int | None,
           now: datetime | None = None) -> LimitHit | None:
    """Return a LimitHit if the CLI output says the usage limit was reached."""
    text = f"{stdout}\n{stderr}"
    pats = STRONG_PATTERNS + (WEAK_PATTERNS if exit_code not in (0, None) else [])
    for pat in pats:
        m = pat.search(text)
        if m:
            return LimitHit(agent=agent, matched=m.group(0), reset_at=parse_reset(text, now))
    return None


def parse_reset(text: str, now: datetime | None = None) -> datetime | None:
    now = now or datetime.now(timezone.utc)
    for fn in (_epoch, _seconds_field, _relative, _clock):
        r = fn(text, now)
        if r is not None:
            return r + RESET_MARGIN
    return None


def _epoch(text: str, now: datetime) -> datetime | None:
    # "Claude AI usage limit reached|1764000000"
    m = re.search(r"limit reached\|(\d{10})", text, re.IGNORECASE)
    if m:
        return datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc)
    return None


def _seconds_field(text: str, now: datetime) -> datetime | None:
    # codex --json: {"type":"usage_limit_reached","resets_in_seconds":12345}
    m = re.search(r'"?resets?_in_seconds"?\s*[:=]\s*(\d+)', text)
    if m:
        return now + timedelta(seconds=int(m.group(1)))
    m = re.search(r'"?resets?_at"?\s*[:=]\s*(\d{10})', text)
    if m:
        return datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc)
    return None


_UNIT = {"day": 86400, "hour": 3600, "hr": 3600, "minute": 60, "min": 60, "second": 1, "sec": 1}


def _relative(text: str, now: datetime) -> datetime | None:
    # "try again in 2 days 3 hours 5 minutes", "resets in 45 min"
    m = re.search(r"(?:try again|resets?|retry)\s+in\s+((?:\d+\s*[a-z]+[\s,and]*)+)", text, re.IGNORECASE)
    if not m:
        return None
    total = 0
    for num, unit in re.findall(r"(\d+)\s*([a-z]+)", m.group(1), re.IGNORECASE):
        unit = unit.lower().rstrip("s")
        for key, secs in _UNIT.items():
            if unit.startswith(key):
                total += int(num) * secs
                break
    return now + timedelta(seconds=total) if total else None


def _clock(text: str, now: datetime) -> datetime | None:
    # "resets 3pm", "resets 8pm (Asia/Saigon)", "try again at 3:05 PM", "resets Mon 9am"
    m = re.search(
        r"(?:resets?|try again)(?:\s+at)?\s+(?:(mon|tue|wed|thu|fri|sat|sun)[a-z]*\s+)?"
        r"(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?(?:\s*\(([A-Za-z_]+/[A-Za-z_]+|UTC)\))?",
        text, re.IGNORECASE)
    if not m:
        return None
    wd, hh, mm, ampm, tzname = m.groups()
    if ampm is None and mm is None:
        return None  # a bare number is not a clock time
    hour, minute = int(hh), int(mm or 0)
    if ampm:
        ap = ampm.lower().replace(".", "")
        hour = hour % 12 + (12 if ap == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    # CLIs print reset times in the user's local zone unless they name one.
    tz = datetime.now().astimezone().tzinfo or timezone.utc
    if tzname == "UTC":
        tz = timezone.utc
    elif tzname:
        try:
            tz = ZoneInfo(tzname)
        except ZoneInfoNotFoundError:
            pass  # no tz database (e.g. Windows without `tzdata`): local time is the best guess
    local_now = now.astimezone(tz)
    target = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if wd:
        days = (_WEEKDAYS.index(wd.lower()[:3]) - local_now.weekday()) % 7
        target += timedelta(days=days)
    if target <= local_now:
        target += timedelta(days=7 if wd else 1)
    return target.astimezone(timezone.utc)


def rest_until(hit_reset: datetime | None, backoff_level: int, ladder: list[int],
               now: datetime | None = None) -> tuple[datetime, bool]:
    """When the agent may work again. Returns (time, reset_was_known)."""
    now = now or datetime.now(timezone.utc)
    if hit_reset is not None and hit_reset > now:
        return hit_reset, True
    minutes = ladder[min(backoff_level, len(ladder) - 1)]
    return now + timedelta(minutes=minutes), False
