import json
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from sportscut.models import Segment


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
    }
    assert list(result) == ["start", "end", "score", "reason"]
    assert [type(value) for value in result.values()] == [float, float, float, str]


def test_to_dict_is_json_safe_for_numpy_scalars() -> None:
    result = Segment(
        start=np.float32(1.0),
        end=np.float32(3.5),
        score=np.float32(0.8),
        reason=np.str_("crowd noise"),
    ).to_dict()

    json.dumps(result)
    assert type(result["start"]) is float
    assert type(result["end"]) is float
    assert type(result["score"]) is float
    assert type(result["reason"]) is str


def test_segment_is_frozen() -> None:
    segment = Segment(start=1.0, end=2.0, score=0.5, reason="cheer")

    with pytest.raises(FrozenInstanceError):
        segment.start = 0.0


@pytest.mark.parametrize(
    ("start", "end"),
    [(-1, 2), (5, 5), (5, 4)],
)
def test_invalid_time_bounds_raise(start: float, end: float) -> None:
    with pytest.raises(ValueError):
        Segment(start=start, end=end, score=0.5, reason="invalid")


@pytest.mark.parametrize("score", [-1.0, 2.0])
def test_score_is_not_range_limited(score: float) -> None:
    segment = Segment(start=1.0, end=2.0, score=score, reason="detector score")

    assert segment.score == score
