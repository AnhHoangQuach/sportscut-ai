import json

import numpy as np
import pytest

from sportscut.player import PlayerQuery, Touch, detect_touches, find_touches, normalize_team


def test_normalize_team_names_and_hex() -> None:
    assert normalize_team(" RED ") == "red"
    assert normalize_team("#FF0000") == "#ff0000"
    for value in ("maroon", "#ff00", ""):
        with pytest.raises(ValueError, match="black.*#rrggbb"):
            normalize_team(value)


@pytest.mark.parametrize("number", [0, 100, "10", 10.0, True])
def test_player_query_number_validation(number: object) -> None:
    with pytest.raises(ValueError):
        PlayerQuery("red", number)  # type: ignore[arg-type]

    assert {PlayerQuery("red", 1): "ok"}[PlayerQuery(" RED ", 1)] == "ok"
    assert PlayerQuery("blue", 99).number == 99


def test_touch_to_dict_and_validation() -> None:
    touch = Touch(1.5, "Blue", 4, 0.8, (1, 2, 16, 32))
    assert touch.to_dict() == {
        "t": 1.5,
        "team": "blue",
        "number": 4,
        "confidence": 0.8,
        "bbox": [1, 2, 16, 32],
    }
    native = Touch(np.float64(2), None, None, np.float32(0.5), None).to_dict()
    json.dumps(native)
    assert native == {"t": 2.0, "team": None, "number": None, "confidence": 0.5, "bbox": None}
    with pytest.raises(ValueError):
        Touch(-1, None, None, 0.5, None)
    for confidence in (1.5, float("nan")):
        with pytest.raises(ValueError):
            Touch(1, None, None, confidence, None)


def test_detect_touches_stub_and_find_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    assert detect_touches("x.mp4") == []
    values = [
        Touch(1, "red", 10, 1, None),
        Touch(2, "red", 7, 1, None),
        Touch(3, "blue", 10, 1, None),
    ]
    monkeypatch.setattr("sportscut.player.detect_touches", lambda _: values)
    assert find_touches("x.mp4", PlayerQuery("red", 10)) == values[:1]
