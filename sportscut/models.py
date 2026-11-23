from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    score: float
    reason: str

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError("start must be non-negative")
        if self.end <= self.start:
            raise ValueError("end must be greater than start")

    def to_dict(self) -> dict[str, float | str]:
        return {
            "start": float(self.start),
            "end": float(self.end),
            "score": float(self.score),
            "reason": str(self.reason),
        }
