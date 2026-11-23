from dataclasses import dataclass

EVENT_TYPES = ("goal", "save", "red_card", "controversy", "other")


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    score: float | None
    reason: str
    event: str = "other"

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("start must be non-negative")
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if self.event not in EVENT_TYPES:
            raise ValueError(
                "event must be one of goal, save, red_card, controversy, other"
            )

    def to_dict(self) -> dict[str, float | str | None]:
        return {
            "start": float(self.start),
            "end": float(self.end),
            "score": None if self.score is None else float(self.score),
            "reason": str(self.reason),
            "event": str(self.event),
        }
