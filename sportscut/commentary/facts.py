import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from sportscut import detect
from sportscut.models import EVENT_TYPES

MATCH_KEYS = frozenset({"home", "away", "competition", "score", "kickoff"})


@dataclass(frozen=True)
class ClipFacts:
    event: str
    minute: int | None = None
    home: str | None = None
    away: str | None = None
    competition: str | None = None
    score: str | None = None

    def __post_init__(self) -> None:
        if self.event not in EVENT_TYPES:
            raise ValueError(f"event must be one of {', '.join(EVENT_TYPES)}")
        if self.minute is not None and (
            isinstance(self.minute, bool)
            or not isinstance(self.minute, int)
            or not 1 <= self.minute <= 130
        ):
            raise ValueError("minute must be an integer from 1 to 130")
        for field in ("home", "away", "competition"):
            value = getattr(self, field)
            if value is not None and (
                not isinstance(value, str)
                or not value
                or value != value.strip()
                or len(value) > 40
            ):
                raise ValueError(f"{field} must be a stripped string of 1 to 40 characters")
        if self.score is not None and (
            not isinstance(self.score, str) or re.fullmatch(r"\d{1,2}-\d{1,2}", self.score) is None
        ):
            raise ValueError("score must match H-A")


def _finite_number(value, field: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{field} must be a finite number")
    return float(value)


def _match_string(value, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    result = unicodedata.normalize("NFC", value).strip()
    return result or None


def facts_from_entry(entry: Mapping, match: Mapping | None = None) -> ClipFacts:
    match = {} if match is None else match
    if not isinstance(match, Mapping):
        raise ValueError("match must be a mapping")
    for key in match:
        if key not in MATCH_KEYS:
            raise ValueError(f"unknown match key: {key}")

    start = _finite_number(entry["start"], "start")
    end = _finite_number(entry["end"], "end")
    if end <= start:
        raise ValueError("end must be greater than start")

    kickoff = match.get("kickoff")
    minute = None
    if kickoff is not None:
        kickoff = _finite_number(kickoff, "kickoff")
        if kickoff < 0:
            raise ValueError("kickoff must be non-negative")
        anchor = start + (end - start) * detect.PRE_SEC / (detect.PRE_SEC + detect.POST_SEC)
        elapsed = anchor - kickoff
        minute = None if elapsed < 0 else min(int(elapsed // 60) + 1, 130)

    values = {name: _match_string(match.get(name), name) for name in ("home", "away", "competition")}
    score = _match_string(match.get("score"), "score")
    if score is not None:
        score = re.sub(r"\s*-\s*", "-", score)
    return ClipFacts(entry["event"], minute, score=score, **values)
