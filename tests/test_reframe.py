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


# --- T-045: follow the players with a smoothed virtual camera ---------------
import subprocess  # noqa: E402

import numpy as np  # noqa: E402

FIELD = (40, 140, 60)
RED = (200, 30, 30)
GREY = (128, 128, 128)


def _field(h=180, w=320, rects=()):
    frame = np.empty((h, w, 3), np.uint8)
    frame[:] = FIELD
    for r0, r1, c0, c1 in rects:
        frame[r0:r1, c0:c1] = RED
    return frame


def test_green_mask_colours():
    colours = [FIELD, (36, 128, 54), RED, (30, 60, 200), (255, 255, 255), (0, 0, 0), GREY]
    frame = np.array([colours], np.uint8)
    assert reframe.green_mask(frame).tolist() == [[True, True, False, False, False, False, False]]


def test_player_mask_eroded_rectangle_exact():
    mask = reframe.player_mask(_field(rects=[(40, 56, 100, 108)]))
    expected = np.zeros((180, 320), bool)
    expected[41:55, 101:107] = True
    assert mask.dtype == bool and mask.sum() == 84 and (mask == expected).all()


def test_player_mask_ignores_thin_line_crowd_rows_and_side_band():
    base = _field(rects=[(40, 56, 100, 108)])
    expected = reframe.player_mask(base)
    line = base.copy()
    line[:, 159:161] = (255, 255, 255)
    crowd = base.copy()
    crowd[0:30] = GREY
    crowd[5:25, 200:210] = RED
    side = base.copy()
    side[:, 0:20] = GREY
    side[100:120, 5:15] = RED
    for frame in (line, crowd, side):
        assert (reframe.player_mask(frame) == expected).all()


def test_player_mask_no_field_returns_none():
    grey = np.full((180, 320, 3), 128, np.uint8)
    assert reframe.player_mask(grey) is None
    sparse = grey.copy()
    sparse[:, :64] = FIELD  # 20% green
    assert reframe.player_mask(sparse) is None


def test_target_x_centroid_of_heaviest_window():
    frame = _field(rects=[(40, 56, 100, 108), (40, 56, 116, 124), (100, 116, 250, 258)])
    assert abs(reframe.target_x(frame, 101) - 112.0) < 1e-9


def test_target_x_low_mass_or_no_field_none():
    assert reframe.target_x(_field(rects=[(40, 44, 100, 104)]), 101) is None
    assert reframe.target_x(np.full((180, 320, 3), 128, np.uint8), 101) is None


def _smooth(targets, **kw):
    params = dict(dead_zone=0.03, ease=0.5, max_pan=0.2) | kw
    return reframe.smooth_path(targets, 640, 202, **params)


@pytest.mark.parametrize(("targets", "expected"), [
    ([None, None, 400.0], [320.0, 320.0, 345.6]),
    ([200.0, 230.0, 260.0], [200.0, 205.4, 223.1]),
    ([300.0, 310.0, 280.9, None, 319.0], [300.0] * 5),
    ([10.0], [101.0]),
    ([700.0], [539.0]),
    ([], []),
])
def test_smooth_path_exact_values(targets, expected):
    path = _smooth(targets)
    assert len(path) == len(expected)
    assert all(abs(a - b) < 1e-9 for a, b in zip(path, expected))


def test_smooth_path_converges_to_dead_zone_edge():
    path = _smooth([101.0] + [539.0] * 80)
    steps = np.diff(path)
    assert (steps >= 0).all() and (steps <= 25.6 + 1e-9).all()
    assert max(path) <= 519.8 + 1e-9 and abs(path[-1] - 519.8) < 1e-3


def test_smooth_path_pure_easing():
    path = _smooth([320, 420, 420, 420], dead_zone=0, max_pan=10)
    assert all(abs(a - b) < 1e-9 for a, b in zip(path, [320, 370, 395, 407.5]))


def test_smooth_path_random_bounds_speed_and_hold():
    rng = np.random.default_rng(0)
    values = rng.uniform(0, 640, 200)
    targets = [None if hole else float(v) for v, hole in zip(values, rng.random(200) < 0.2)]
    path = _smooth(targets)
    assert (np.abs(np.diff(path)) <= 25.6 + 1e-9).all()
    assert all(101 <= x <= 539 for x in path)
    assert all(path[i] == path[i - 1] for i in range(1, 200) if targets[i] is None)


def test_center_plan_is_t017_baseline(synthetic_video, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("center_plan decoded frames")

    monkeypatch.setattr(reframe.media, "sample_frames", boom)
    assert reframe.center_plan(synthetic_video) == [
        (t, 80.0) for t in reframe.sample_times(reframe.media.probe_duration(synthetic_video))
    ]


def _clip(tmp_path, frames, name="clip.mp4"):
    out = tmp_path / name
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", "640x360", "-r", "25", "-i", "pipe:0", "-an", "-c:v", "mpeg4",
        "-q:v", "2", "-pix_fmt", "yuv420p", str(out),
    ], input=np.stack(frames).tobytes(), check=True, capture_output=True)
    return out


PLAYERS = _field(360, 640, rects=[(150, 182, 96, 112), (150, 182, 128, 144)])
GREY_FRAME = np.full((360, 640, 3), 128, np.uint8)


def test_plan_crop_follows_static_players(require_ffmpeg, tmp_path):
    plan = reframe.plan_crop(_clip(tmp_path, [PLAYERS] * 100))
    assert [t for t, _ in plan] == reframe.sample_times(4.0)
    assert all(101 <= x <= 140 for _, x in plan)


def test_plan_crop_no_field_is_centre(require_ffmpeg, tmp_path):
    plan = reframe.plan_crop(_clip(tmp_path, [GREY_FRAME] * 100))
    assert len(plan) == len(reframe.sample_times(4.0))
    assert all(x == 320.0 for _, x in plan)


def test_plan_crop_starts_centre_then_eases(require_ffmpeg, tmp_path):
    plan = reframe.plan_crop(_clip(tmp_path, [GREY_FRAME] * 50 + [PLAYERS] * 50))
    assert all(x == 320.0 for t, x in plan if t <= 1.8)
    later = [x for t, x in plan if t >= 1.8]
    steps = np.diff(later)
    assert (steps <= 0).all() and (np.abs(steps) <= 25.6 + 1e-6).all() and later[-1] < 320


def test_plan_crop_holds_when_field_lost(require_ffmpeg, tmp_path):
    plan = dict(reframe.plan_crop(_clip(tmp_path, [PLAYERS] * 50 + [GREY_FRAME] * 50)))
    assert all(x == plan[1.8] for t, x in plan.items() if t >= 2.0)


# --- T-020: ball detection drives the crop, player cluster as fallback ------
WHITE = (255, 255, 255)


def _white(frame, r0, r1, c0, c1, colour=WHITE):
    frame[r0:r1, c0:c1] = colour
    return frame


def test_field_mask_inside_region_and_none():
    frame = _field()
    frame[0:30] = GREY
    frame[:, 0:20] = GREY
    expected = np.zeros((180, 320), bool)
    expected[30:180, 20:320] = True
    mask = reframe.field_mask(frame)
    assert mask.dtype == bool and (mask == expected).all()
    grey = np.full((180, 320, 3), 128, np.uint8)
    assert reframe.field_mask(grey) is None
    sparse = grey.copy()
    sparse[:, :64] = FIELD
    assert reframe.field_mask(sparse) is None


@pytest.mark.parametrize(("max_pan", "expected"), [
    ([0.1, 0.5, 0.5], [101.0, 165.0, 229.0]),
    ([0.5, 0.1, 0.5], [101.0, 113.8, 177.8]),
])
def test_smooth_path_per_sample_gains_exact(max_pan, expected):
    path = reframe.smooth_path(
        [101.0, 539.0, 539.0], 640, 202,
        dead_zone=[0, 0, 0], ease=[1, 1, 0.5], max_pan=max_pan,
    )
    assert len(path) == 3 and all(abs(a - b) < 1e-9 for a, b in zip(path, expected))


@pytest.mark.parametrize("name", ["dead_zone", "ease", "max_pan"])
def test_smooth_path_sequence_length_mismatch_raises(name):
    with pytest.raises(ValueError):
        reframe.smooth_path([101.0, 300.0, 400.0], 640, 202, **{name: [0.1, 0.1]})


def test_smooth_path_scalar_equals_constant_sequences():
    rng = np.random.default_rng(0)
    values = rng.uniform(0, 640, 200)
    targets = [None if hole else float(v) for v, hole in zip(values, rng.random(200) < 0.2)]
    scalar = _smooth(targets)
    seq = _smooth(targets, dead_zone=[0.03] * 200, ease=[0.5] * 200, max_pan=[0.2] * 200)
    assert seq == scalar


def _close(got, expected):
    return len(got) == len(expected) and all(
        all(abs(a - b) < 1e-9 for a, b in zip(g, e)) for g, e in zip(got, expected)
    )


def test_ball_candidates_single_3x3():
    got = reframe.ball_candidates(_white(_field(), 88, 91, 98, 101))
    assert _close(got, [(99.5, 89.5, 1.0)])


def test_ball_candidates_two_blobs_order():
    frame = _white(_white(_field(), 88, 91, 98, 101), 120, 123, 250, 253)
    got = reframe.ball_candidates(frame)
    assert _close(got, [(99.5, 89.5, 1.0), (251.5, 121.5, 1.0)])


def test_ball_candidates_4x4_score():
    got = reframe.ball_candidates(_white(_field(), 60, 64, 200, 204))
    assert _close(got, [(202.0, 62.0, 0.64)])


def _outside_field():
    frame = _field()
    frame[0:30] = GREY
    return _white(frame, 10, 13, 150, 153)


@pytest.mark.parametrize("frame", [
    _white(_field(), 0, 180, 159, 161),
    _white(_field(), 80, 95, 100, 107),
    _white(_field(), 80, 88, 100, 108),
    _white(_field(), 88, 91, 98, 101, RED),
    _white(_field(), 88, 91, 98, 101, GREY),
    _outside_field(),
    np.full((180, 320, 3), 128, np.uint8),
], ids=["line", "white_7x15", "white_8x8", "red", "grey", "outside_field", "all_grey"])
def test_ball_candidates_rejects(frame):
    assert reframe.ball_candidates(frame) == []


def test_track_ball_steady():
    samples = [[(10, 10, 1)], [(20, 10, 1)], [(30, 10, 1)]]
    assert reframe.track_ball(samples, 15) == [(10, 10), (20, 10), (30, 10)]


def test_track_ball_constant_velocity_beats_nearer_distractor():
    samples = [[(0, 0, 1)], [(40, 0, 1)], [(80, 0, 1)], [(90, 0, 1), (120, 0, 1)]]
    assert reframe.track_ball(samples, 50) == [(0, 0), (40, 0), (80, 0), (120, 0)]


def test_track_ball_gated_miss_holds():
    samples = [[(100, 100, 1)], [(100, 100, 1)], [(300, 100, 1)]]
    assert reframe.track_ball(samples, 50) == [(100, 100)] * 3


def test_track_ball_lost_then_reacquire():
    samples = [[(5, 5, 1)], [], [], [], [(300, 40, 1)]]
    got = reframe.track_ball(samples, 50, lost_after=3)
    assert got == [(5, 5), (5, 5), (5, 5), None, (300, 40)]


def test_track_ball_velocity_across_gap():
    samples = [[(0, 0, 1)], [(10, 0, 1)], [], [(30, 0, 1)]]
    assert reframe.track_ball(samples, 12) == [(0, 0), (10, 0), (10, 0), (30, 0)]


def test_track_ball_acquires_highest_score():
    assert reframe.track_ball([[(10, 0, 0.5), (200, 0, 0.9)]], 50) == [(200, 0)]


def test_track_ball_empty():
    assert reframe.track_ball([], 50) == []


def test_blend_weights_ramp_and_edges():
    ball = [None, "b", "b", "b", "b", "b", None, None]
    assert reframe.blend_weights(ball, 0.25) == [0.0, 0.25, 0.5, 0.75, 1.0, 1.0, 0.75, 0.5]
    assert reframe.blend_weights(["b", None], 0.25) == [1.0, 0.75]
    assert reframe.blend_weights([], 0.25) == []


def test_framed_x_clamp_window_and_fallbacks():
    frame = _field(rects=[(40, 56, 100, 108), (40, 56, 116, 124), (100, 116, 250, 258)])
    assert abs(reframe.framed_x(frame, 101, 60.0, 40.0) - 100.0) < 1e-9
    assert abs(reframe.framed_x(frame, 101, 240.0, 60.0) - 254.0) < 1e-9
    grey = np.full((180, 320, 3), 128, np.uint8)
    for plain in (_field(), grey):
        assert abs(reframe.framed_x(plain, 101, 150.0, 60.0) - 150.0) < 1e-9


def _ball_frame(base, ball_x=None, ball_y=180):
    frame = base.copy()
    if ball_x is not None:
        yy, xx = np.ogrid[-4:5, -4:5]
        frame[ball_y - 4 : ball_y + 5, ball_x - 4 : ball_x + 5][xx * xx + yy * yy <= 16] = 255
    return frame


def _ball_clip(tmp_path, seconds, base, ball_at):
    frames = [_ball_frame(base, ball_at(n / 25)) for n in range(round(seconds * 25))]
    return _clip(tmp_path, frames)


MAX_BALL_STEP = reframe.BALL_MAX_PAN * 640 / 5 + 1e-6


def _steps_capped(plan):
    return (np.abs(np.diff([x for _, x in plan])) <= MAX_BALL_STEP).all()


def test_plan_crop_no_ball_equals_t045_plan(require_ffmpeg, tmp_path, monkeypatch, synthetic_video):
    base = PLAYERS.copy()
    base[:, 319:321] = 255
    clip = _clip(tmp_path, [base] * 100)
    after = reframe.plan_crop(clip)
    assert reframe.plan_crop(clip) == after
    assert reframe.plan_crop(synthetic_video) == [(t, 80.0) for t in reframe.sample_times(6.0)]
    monkeypatch.setattr(reframe, "ball_candidates", lambda frame: [])
    assert reframe.plan_crop(clip) == after


def test_plan_crop_follows_moving_ball(require_ffmpeg, tmp_path):
    base = _field(360, 640, rects=[(60, 90, 40, 54)])
    plan = reframe.plan_crop(_ball_clip(tmp_path, 4, base, lambda t: round(120 + 100 * t)))
    assert len(plan) == 20
    assert all(abs(x - (120 + 100 * t)) <= 101 for t, x in plan)
    assert _steps_capped(plan)


def _pass_x(t):
    return 100 if t < 2.0 else min(540, round(100 + 440 * (t - 2.0) / 1.2))


def test_plan_crop_pass_catches_up(require_ffmpeg, tmp_path):
    plan = reframe.plan_crop(_ball_clip(tmp_path, 6, _field(360, 640), _pass_x))
    assert len(plan) == 30
    assert all(abs(x - _pass_x(t)) <= 101 for t, x in plan if t <= 2.0 or t >= 5.0)
    assert _steps_capped(plan)


def test_plan_crop_ball_lost_falls_back_smoothly(require_ffmpeg, tmp_path):
    plan = reframe.plan_crop(
        _ball_clip(tmp_path, 6, PLAYERS, lambda t: 500 if t < 2.0 else None)
    )
    xs = dict(plan)
    assert all(abs(x - 500) <= 101 for t, x in plan if t <= 1.8)
    later = [x for t, x in plan if t >= 2.0]
    assert (np.diff(later) <= 0).all() and xs[5.8] < xs[2.0]
    assert _steps_capped(plan)
