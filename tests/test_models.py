from dataclasses import FrozenInstanceError
import json

import numpy as np
import pytest

from sportscut.models import EVENT_TYPES, Segment


def test_to_dict_shape_order_and_values() -> None:
    result = Segment(
        start=1.0,
        end=3.5,
        score=0.8,
        reason="crowd noise",
    ).to_dict()

    assert result == {
        "start": 1.0,
        "end": 3.5,
        "score": 0.8,
        "reason": "crowd noise",
        "event": "other",
    }
    assert list(result) == ["start", "end", "score", "reason", "event"]
    assert [type(value) for value in result.values()] == [float, float, float, str, str]


def test_to_dict_is_json_safe_for_numpy_scalars() -> None:
    result = Segment(
        start=np.float32(1.0),
        end=np.float32(3.5),
        score=np.float32(0.8),
        reason=np.str_("crowd noise"),
    ).to_dict()

    json.dumps(result)
    assert all(type(result[key]) is float for key in ("start", "end", "score"))
    assert type(result["reason"]) is str


def test_event_roundtrip() -> None:
    assert Segment(1, 2, 0.5, "goal", event="goal").to_dict()["event"] == "goal"
    result = Segment(1, 2, 0.5, "save", event=np.str_("save")).to_dict()
    assert type(result["event"]) is str


@pytest.mark.parametrize("event", ["penalty", "Goal", ""])
def test_invalid_event_raises(event: str) -> None:
    with pytest.raises(ValueError):
        Segment(1, 2, 0.5, "invalid", event=event)


def test_event_types_constant() -> None:
    assert EVENT_TYPES == ("goal", "save", "red_card", "controversy", "other")


def test_segment_is_frozen() -> None:
    segment = Segment(start=1.0, end=2.0, score=0.5, reason="goal")

    with pytest.raises(FrozenInstanceError):
        segment.start = 0.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("start", "end"),
    [(-1, 2), (5, 5), (5, 4)],
)
def test_invalid_time_bounds_raise(start: float, end: float) -> None:
    with pytest.raises(ValueError):
        Segment(start=start, end=end, score=0.5, reason="invalid")


@pytest.mark.parametrize("score", [-1.0, 2.0])
def test_score_is_not_range_limited(score: float) -> None:
    segment = Segment(start=1.0, end=2.0, score=score, reason="raw score")

    assert segment.score == score
