import pytest

from sportscut.models import Segment
from sportscut.ranking import EVENT_PRIORITY, parse_events, select_segments


def segments():
    values = [(0, 5, 10, "other"), (30, 40, 2, "goal"), (50, 60, 3, "save"),
              (70, 80, 5, "red_card"), (85, 89, 6, "controversy")]
    return [Segment(start, end, score, event, event) for start, end, score, event in values]


def test_parse_events() -> None:
    assert EVENT_PRIORITY == {"goal": 5, "red_card": 4, "controversy": 3, "save": 2, "other": 1}
    assert parse_events("Goal, save,goal") == ("goal", "save")
    for text in ("", "goal,", "goal,,save", "penalty"):
        with pytest.raises(ValueError, match="^unknown event"):
            parse_events(text)


@pytest.mark.parametrize("top,events,starts", [
    (3, None, [30, 70, 85]), (4, None, [0, 30, 70, 85]),
    (10, ("goal",), [30]), (5, ("save", "goal"), [30, 50]), (1, ("other",), [0]),
    (1, ("controversy", "red_card"), [70]), (10, (), []),
])
def test_select_segments(top, events, starts) -> None:
    assert [item.start for item in select_segments(segments(), top, events)] == starts


def test_select_segments_validation_and_tie() -> None:
    tied = [Segment(30, 31, 4, "late"), Segment(10, 11, 4, "early")]
    assert select_segments(tied, 1)[0].start == 10
    with pytest.raises(ValueError, match="^top must be >= 1$"):
        select_segments([], 0)
    with pytest.raises(ValueError, match="^unknown event 'penalty'"):
        select_segments([], 1, ("penalty",))

