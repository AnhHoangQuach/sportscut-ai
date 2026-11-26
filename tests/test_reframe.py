import math

import pytest

from sportscut import reframe
from sportscut.media import MediaError


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [(640, 360, 202), (1920, 1080, 606), (720, 1920, 720)],
)
def test_crop_width_examples(width, height, expected):
    assert reframe.crop_width(width, height) == expected


@pytest.mark.parametrize("aspect", [0, -1, math.nan, math.inf, True])
def test_crop_width_rejects_invalid_aspect(aspect):
    with pytest.raises(ValueError):
        reframe.crop_width(640, 360, aspect)


@pytest.mark.parametrize(
    ("width", "height"),
    [(0, 360), (-1, 360), (True, 360), (640, 0), (640, -1), (640, True)],
)
def test_crop_width_rejects_invalid_dimensions(width, height):
    with pytest.raises(ValueError):
        reframe.crop_width(width, height)


def test_sample_times_at_five_hz():
    times = reframe.sample_times(12.0)
    assert len(times) == 60
    assert times[0] == 0.0
    assert times[-1] == 11.8
    assert times == [round(i / 5, 4) for i in range(60)]
    assert reframe.sample_times(0.1) == [0.0]


@pytest.mark.parametrize("duration", [0, -1, math.nan, math.inf])
def test_sample_times_rejects_invalid_duration(duration):
    with pytest.raises(ValueError):
        reframe.sample_times(duration)


def test_plan_crop_returns_static_center_plan(synthetic_video):
    assert reframe.plan_crop(synthetic_video) == [
        (t, 80.0) for t in reframe.sample_times(6.0)
    ]


def test_plan_crop_missing_file_raises(tmp_path):
    missing = tmp_path / "missing.mp4"
    with pytest.raises(MediaError, match="media file not found"):
        reframe.plan_crop(missing)


def test_plan_crop_rejects_bad_aspect_before_duration(monkeypatch):
    monkeypatch.setattr("sportscut.reframe.media.probe_size", lambda path: (640, 360))
    called = False

    def duration(path):
        nonlocal called
        called = True
        return 12.0

    monkeypatch.setattr("sportscut.reframe.media.probe_duration", duration)
    with pytest.raises(ValueError):
        reframe.plan_crop("clip.mp4", aspect=0)
    assert called is False
