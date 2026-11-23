import os
import re
from dataclasses import dataclass


TEAM_NAMES = (
    "black", "blue", "green", "orange", "pink", "purple", "red", "sky", "white", "yellow"
)


def normalize_team(team: str) -> str:
    value = team.strip().lower() if isinstance(team, str) else ""
    if value in TEAM_NAMES or re.fullmatch(r"#[0-9a-f]{6}", value):
        return value
    choices = ", ".join(TEAM_NAMES)
    raise ValueError(f"unknown team colour {team!r}: use one of {choices} or #rrggbb")


@dataclass(frozen=True)
class PlayerQuery:
    team: str
    number: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "team", normalize_team(self.team))
        if type(self.number) is not int or not 1 <= self.number <= 99:
            raise ValueError("player number must be an integer from 1 to 99")


@dataclass(frozen=True)
class Touch:
    t: float
    team: str | None
    number: int | None
    confidence: float
    bbox: tuple[int, int, int, int] | None

    def __post_init__(self) -> None:
        if self.t < 0:
            raise ValueError("touch time must be >= 0")
        if not 0 <= self.confidence <= 1:
            raise ValueError("touch confidence must be between 0 and 1")
        if self.team is not None:
            object.__setattr__(self, "team", normalize_team(self.team))

    def to_dict(self) -> dict:
        return {
            "t": float(self.t),
            "team": self.team,
            "number": None if self.number is None else int(self.number),
            "confidence": float(self.confidence),
            "bbox": None if self.bbox is None else [int(value) for value in self.bbox],
        }


def detect_touches(video: str | os.PathLike[str]) -> list[Touch]:
    return []


def find_touches(video: str | os.PathLike[str], query: PlayerQuery) -> list[Touch]:
    return [
        touch
        for touch in detect_touches(video)
        if touch.team == query.team and touch.number == query.number
    ]
