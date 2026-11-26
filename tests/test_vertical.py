import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from sportscut import media, vertical
from sportscut.vertical import crop_x_expression, render_vertical, vertical_filter


def _evaluate(expr: str, t: float) -> float:
    return eval(  # noqa: S307 - test-only evaluation of a generated expression
        expr,
        {"__builtins__": {}},
        {"t": t, "clip": lambda v, lo, hi: min(max(v, lo), hi)},
    )


def test_crop_x_expression_exact_ramp():
    assert (
        crop_x_expression([(0.0, 101.0), (1.0, 201.0)], 640, 202)
        == "0.0000+100.000000*(clip(t,0.0000,1.0000)-0.0000)"
    )


def test_crop_x_expression_static_path_is_constant():
    assert crop_x_expression([(0, 320), (1, 320)], 640, 202) == "219.0000"


def test_crop_x_expression_negative_slope_and_flat():
    expr = crop_x_expression([(0, 320), (1, 220), (2, 220)], 640, 202)
    assert expr == "219.0000-100.000000*(clip(t,0.0000,1.0000)-0.0000)"
    assert "if(" not in expr


@pytest.mark.parametrize(
    "path",
    [
        [(0.0, 101.0), (0.5, 400.0), (1.25, 300.0), (3.0, 640.0), (3.2, 0.0)],
        [(0.2, 320.0), (0.4, 330.0), (0.6, 310.0)],
        [(k / 5, 120 + 100 * k / 5) for k in range(20)],
    ],
)
def test_crop_x_expression_matches_np_interp(path):
    width, crop_w = 640, 202
    ts = [t for t, _ in path]
    lefts = [min(max(x, crop_w / 2), width - crop_w / 2) - crop_w / 2 for _, x in path]
    expr = crop_x_expression(path, width, crop_w)
    assert "if(" not in expr
    probes = list(ts)
    probes += [(a + b) / 2 for a, b in zip(ts, ts[1:])]
    probes += [ts[0] - 1.0, ts[-1] + 1.0, ts[-1] + 10.0]
    for t in probes:
        value = _evaluate(expr, t)
        assert value == pytest.approx(float(np.interp(t, ts, lefts)), abs=0.01)
        assert -0.01 <= value <= width - crop_w + 0.01


def test_crop_x_expression_clamps_to_frame():
    expr = crop_x_expression([(0, -1000), (1, 5000)], 640, 202)
    assert _evaluate(expr, 0) == pytest.approx(0, abs=0.01)
    assert _evaluate(expr, 0.5) == pytest.approx(219, abs=0.01)
    for t in (1, 2, 5):
        assert _evaluate(expr, t) == pytest.approx(438, abs=0.01)


@pytest.mark.parametrize(
    "path",
    [
        [],
        [(0, float("nan"))],
        [(0, float("inf"))],
        [(1, 5), (1, 6)],
        [(1, 5), (0.5, 6)],
        [(-1, 5)],
        [(0, True)],
        [(True, 5)],
        [(0, "5")],
        [(0,)],
        [(0, 1, 2)],
        [5],
    ],
)
def test_invalid_crop_path_raises(path):
    with pytest.raises(ValueError, match=r"^invalid crop path: "):
        crop_x_expression(path, 640, 202)


def test_crop_path_too_long_raises():
    path = [(k / 5, 100.0 + (k % 2) * 200.0) for k in range(25_000)]
    with pytest.raises(ValueError, match=r"^crop path too long: 25000 keyframes$"):
        crop_x_expression(path, 640, 202)


def test_vertical_filter_exact_string():
    assert (
        vertical_filter([(0.0, 320.0)], 640, 360)
        == "crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1"
    )


def test_render_vertical_passes_arguments_and_creates_parent(monkeypatch, tmp_path):
    calls = []
    clip = tmp_path / "clip.mp4"
    out = tmp_path / "a" / "b" / "o.mp4"

    def fake_probe(path):
        calls.append(("probe", path))
        return 640, 360

    def fake_filter(path, video_filter, dest):
        calls.append(("filter", path, video_filter, dest))
        assert Path(dest).parent.is_dir()
        return Path(dest)

    monkeypatch.setattr(media, "probe_size", fake_probe)
    monkeypatch.setattr(media, "filter_video", fake_filter)
    assert render_vertical(clip, [(0.0, 320.0)], out) == out
    assert calls == [
        ("probe", clip),
        ("filter", clip, vertical_filter([(0.0, 320.0)], 640, 360), out),
    ]


def test_render_vertical_validates_before_probing(monkeypatch, tmp_path):
    def fail(*args, **kwargs):
        pytest.fail("media must not be touched for an invalid crop path")

    monkeypatch.setattr(media, "probe_size", fail)
    monkeypatch.setattr(media, "filter_video", fail)
    with pytest.raises(ValueError, match=r"^invalid crop path: "):
        render_vertical(tmp_path / "missing.mp4", [], tmp_path / "v" / "o.mp4")
    assert not (tmp_path / "v").exists()


def test_render_vertical_on_synthetic_video(synthetic_video, tmp_path):
    out = tmp_path / "v" / "o.mp4"
    assert render_vertical(synthetic_video, [(0.0, 80.0)], out) == out
    args = ["ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type,codec_name,width,height", "-of", "json", "-i", str(out)]
    streams = json.loads(subprocess.run(
        args, check=True, capture_output=True, text=True
    ).stdout)["streams"]
    video_streams = [s for s in streams if s["codec_type"] == "video"]
    assert [(s["codec_name"], s["width"], s["height"]) for s in video_streams] == [
        ("h264", vertical.OUT_WIDTH, vertical.OUT_HEIGHT)
    ]
    assert [s["codec_name"] for s in streams if s["codec_type"] == "audio"] == ["aac"]
    assert media.probe_duration(out) == pytest.approx(
        media.probe_duration(synthetic_video), abs=0.3
    )
