from collections.abc import Iterable

from sportscut.models import EVENT_TYPES, Segment

EVENT_PRIORITY = {"goal": 5, "red_card": 4, "controversy": 3, "save": 2, "other": 1}
_CHOICES = ", ".join(EVENT_TYPES)


def _validate_event(name: str) -> None:
    if name not in EVENT_TYPES:
        raise ValueError(f"unknown event {name!r}; choose from {_CHOICES}")


def parse_events(text: str) -> tuple[str, ...]:
    names = tuple(item.strip().lower() for item in text.split(","))
    for name in names:
        _validate_event(name)
    return tuple(dict.fromkeys(names))


def select_segments(
    segments: Iterable[Segment], top: int, events: Iterable[str] | None = None
) -> list[Segment]:
    if top < 1:
        raise ValueError("top must be >= 1")
    selected = list(segments)
    if events is not None:
        names = tuple(events)
        for name in names:
            _validate_event(name)
        selected = [segment for segment in selected if segment.event in names]
    ranked = sorted(selected, key=lambda segment: (
        -(segment.score * EVENT_PRIORITY[segment.event]),  # type: ignore[operator]
        -EVENT_PRIORITY[segment.event], segment.start, segment.end,
    ))[:top]
    return sorted(ranked, key=lambda segment: (segment.start, segment.end))
