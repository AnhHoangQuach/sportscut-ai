"""T-021: scoreboard overlay and event caption on vertical clips."""

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from sportscut import media, vertical
from sportscut.media import MediaError

OLD = "crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1"
DRAW = (
    "drawtext=fontfile=/fonts/DejaVuSans.ttf:text=BÀN THẮNG · 34\\\\\\':"
    "expansion=none:fontsize=64:fontcolor=white:box=1:boxcolor=black@0.6:"
    "boxborderw=16:x=(w-text_w)/2:y=240"
)
BOX_GRAPH = (
    "split=2[sc_main][sc_box];[sc_main]" + OLD + "[sc_v];"
    "[sc_box]crop=w=160:h=40:x=40:y=16,scale=640:160,setsar=1[sc_b];"
    "[sc_v][sc_b]overlay=x=220:y=40"
)


# caption_text

@pytest.mark.parametrize("event, start, end, expected", [
    ("goal", 2000, 2020, "BÀN THẮNG · 34'"),
    ("save", 0, 10, "CỨU THUA · 1'"),
    ("red_card", 60, 70, "THẺ ĐỎ · 2'"),
    ("controversy", 0, 10, "TRANH CÃI · 1'"),
    ("goal", 59.8, 60.0, "BÀN THẮNG · 1'"),   # midpoint 59.9 s
    ("goal", 59.0, 61.0, "BÀN THẮNG · 2'"),   # midpoint 60.0 s
])
def test_caption_text(event, start, end, expected):
    assert vertical.caption_text(event, start, end) == expected
    assert "\u00b7" in expected


@pytest.mark.parametrize("event", ["other", "penalty", ""])
def test_caption_text_none_for_other_or_unknown(event):
    assert vertical.caption_text(event, 0, 10) is None


# check_score_box

def test_check_score_box_returns_int_tuple():
    assert vertical.check_score_box([40, 16, 160, 40], 640, 360) == (40, 16, 160, 40)
    assert vertical.check_score_box((0, 0, 160, 120), 160, 120) == (0, 0, 160, 120)


@pytest.mark.parametrize("box", [
    (1, 2, 3), (1, 2, 3, 4, 5), "1,2,3,4", None, 5,
    (True, 0, 4, 4), (0, 0, 4.0, 4), (0, 0, "4", 4),
])
def test_check_score_box_shape_errors(box):
    with pytest.raises(ValueError) as exc:
        vertical.check_score_box(box, 640, 360)
    assert str(exc.value) == "invalid score box: expected four integers x,y,w,h"


@pytest.mark.parametrize("box", [(-1, 0, 4, 4), (0, -2, 4, 4), (0, 0, 1, 4), (0, 0, 4, 0)])
def test_check_score_box_range_errors(box):
    with pytest.raises(ValueError) as exc:
        vertical.check_score_box(box, 640, 360)
    assert str(exc.value) == "invalid score box: x,y must be >= 0 and w,h >= 2"


@pytest.mark.parametrize("box", [(0, 0, 200, 10), (0, 115, 10, 10)])
def test_check_score_box_out_of_frame(box):
    with pytest.raises(ValueError) as exc:
        vertical.check_score_box(box, 160, 120)
    x, y, w, h = box
    assert str(exc.value) == (
        f"invalid score box: {x},{y},{w},{h} does not fit the 160x120 frame"
    )


# band_box_to_source

@pytest.mark.parametrize("box, size, expected", [
    ((10, 4, 40, 10), (640, 360), (36, 12, 168, 48)),
    ((10, 4, 40, 10), (160, 120), (8, 4, 44, 16)),
    ((0, 0, 5, 3), (1920, 1080), (0, 0, 72, 48)),
    ((150, 25, 10, 5), (640, 360), (596, 96, 44, 24)),  # clamped at right/bottom of band
])
def test_band_box_to_source(box, size, expected):
    assert vertical.band_box_to_source(box, *size) == expected


def test_band_box_to_source_odd_frame_stays_inside():
    x, y, w, h = vertical.band_box_to_source((150, 0, 10, 30), 641, 361)
    assert x + w <= 640 and y + h <= 360
    assert x % 2 == y % 2 == w % 2 == h % 2 == 0


# score_overlay_geometry

@pytest.mark.parametrize("box, expected", [
    ((40, 16, 160, 40), (640, 160, 220, 40)),
    ((36, 12, 168, 48), (560, 160, 260, 40)),
    ((0, 0, 600, 20), (1000, 34, 40, 40)),  # very wide: limited by width
])
def test_score_overlay_geometry(box, expected):
    assert vertical.score_overlay_geometry(box) == expected


# escaping and drawtext

def test_drawtext_filter_exact():
    assert vertical.drawtext_filter("BÀN THẮNG · 34'", "/fonts/DejaVuSans.ttf") == DRAW


def test_drawtext_filter_accepts_path():
    assert vertical.drawtext_filter("BÀN THẮNG · 34'", Path("/fonts/DejaVuSans.ttf")) == DRAW


@pytest.mark.parametrize("raw, escaped", [
    ("a:b", "a\\\\:b"),
    ("a,b", "a\\,b"),
    ("a[b]", "a\\[b\\]"),
    ("a;b", "a\\;b"),
    ("a\\b", "a\\\\\\\\b"),
    ("it's", "it\\\\\\'s"),
])
def test_escape_two_levels(raw, escaped):
    assert vertical._escape(raw) == escaped


def test_drawtext_filter_escapes_fontfile():
    result = vertical.drawtext_filter("X", "C:/my,fonts[1];a\\b.ttf")
    assert result.startswith(
        "drawtext=fontfile=C\\\\:/my\\,fonts\\[1\\]\\;a\\\\\\\\b.ttf:text=X:"
    )


# vertical_filter

CROP = [(0.0, 320.0)]


def test_vertical_filter_unchanged_without_overlays():
    assert vertical.vertical_filter(CROP, 640, 360) == OLD
    assert vertical.vertical_filter(CROP, 640, 360, None, None, None) == OLD


def test_vertical_filter_box_and_caption_exact():
    result = vertical.vertical_filter(
        CROP, 640, 360, score_box=(40, 16, 160, 40),
        caption="BÀN THẮNG · 34'", fontfile="/fonts/DejaVuSans.ttf",
    )
    assert result == BOX_GRAPH + "," + DRAW
    assert ":text=BÀN THẮNG · 34\\\\\\':expansion=none:" in result


def test_vertical_filter_caption_only():
    result = vertical.vertical_filter(
        CROP, 640, 360, caption="BÀN THẮNG · 34'", fontfile="/fonts/DejaVuSans.ttf"
    )
    assert result == OLD + "," + DRAW


def test_vertical_filter_box_only():
    result = vertical.vertical_filter(CROP, 640, 360, score_box=(40, 16, 160, 40))
    assert result == BOX_GRAPH
    assert result.endswith("overlay=x=220:y=40")


def test_vertical_filter_caption_needs_fontfile():
    with pytest.raises(ValueError) as exc:
        vertical.vertical_filter(CROP, 640, 360, caption="CỨU THUA · 1'")
    assert str(exc.value) == "caption needs a fontfile"


def test_vertical_filter_rejects_out_of_frame_box():
    with pytest.raises(ValueError, match="^invalid score box: 600,0,100,10 does not fit the 640x360 frame$"):
        vertical.vertical_filter(CROP, 640, 360, score_box=(600, 0, 100, 10))


# render_vertical wiring

@pytest.fixture
def media_calls(monkeypatch):
    calls = []

    def probe_size(clip):
        calls.append(("probe_size", clip))
        return (640, 360)

    def find_font():
        calls.append(("find_font",))
        return Path("/fonts/DejaVuSans.ttf")

    def filter_video(clip, video_filter, out):
        calls.append(("filter_video", clip, video_filter, out))
        return Path(out)

    monkeypatch.setattr(vertical.media, "probe_size", probe_size)
    monkeypatch.setattr(vertical.media, "find_font", find_font)
    monkeypatch.setattr(vertical.media, "filter_video", filter_video)
    return calls


def test_render_vertical_with_caption_calls_find_font(media_calls, tmp_path):
    out = tmp_path / "v" / "o.mp4"
    assert vertical.render_vertical("c.mp4", CROP, out, caption="BÀN THẮNG · 34'") == out
    assert media_calls == [
        ("probe_size", "c.mp4"),
        ("find_font",),
        ("filter_video", "c.mp4", OLD + "," + DRAW, out),
    ]
    assert out.parent.is_dir()


def test_render_vertical_box_only_skips_find_font(media_calls, tmp_path):
    out = tmp_path / "o.mp4"
    vertical.render_vertical("c.mp4", CROP, out, score_box=(40, 16, 160, 40))
    assert media_calls == [
        ("probe_size", "c.mp4"),
        ("filter_video", "c.mp4", BOX_GRAPH, out),
    ]


def test_render_vertical_box_and_caption(media_calls, tmp_path):
    out = tmp_path / "o.mp4"
    vertical.render_vertical(
        "c.mp4", CROP, out, score_box=(40, 16, 160, 40), caption="BÀN THẮNG · 34'"
    )
    assert [c[0] for c in media_calls] == ["probe_size", "find_font", "filter_video"]
    assert media_calls[-1][2] == BOX_GRAPH + "," + DRAW


def test_render_vertical_without_overlays_unchanged(media_calls, tmp_path):
    out = tmp_path / "o.mp4"
    vertical.render_vertical("c.mp4", CROP, out)
    assert media_calls == [("probe_size", "c.mp4"), ("filter_video", "c.mp4", OLD, out)]


def test_render_vertical_invalid_path_raises_before_probe(media_calls, tmp_path):
    with pytest.raises(ValueError, match="^invalid crop path"):
        vertical.render_vertical("c.mp4", [], tmp_path / "o.mp4", caption="X")
    assert media_calls == []


def test_find_score_box_maps_band_box(monkeypatch):
    frames = object()
    monkeypatch.setattr(vertical.media, "sample_top_band", lambda clip: frames)
    monkeypatch.setattr(
        vertical.scoreboard, "find_box",
        lambda got: (10, 4, 40, 10) if got is frames else pytest.fail("wrong frames"),
    )
    monkeypatch.setattr(vertical.media, "probe_size", lambda clip: (640, 360))
    assert vertical.find_score_box("c.mp4") == (36, 12, 168, 48)


def test_find_score_box_none_skips_probe(monkeypatch):
    monkeypatch.setattr(vertical.media, "sample_top_band", lambda clip: [])
    monkeypatch.setattr(vertical.scoreboard, "find_box", lambda frames: None)
    monkeypatch.setattr(vertical.media, "probe_size", lambda clip: pytest.fail("no probe"))
    assert vertical.find_score_box("c.mp4") is None


def test_vertical_module_has_no_subprocess_string():
    source = Path(vertical.__file__).read_text(encoding="utf-8")
    assert "subprocess" not in source


# Real ffmpeg: synthetic broadcast board (AC8, AC9)

BOARD = (40, 16, 160, 40)


@pytest.fixture(scope="module")
def board_clip(require_ffmpeg, tmp_path_factory):
    path = tmp_path_factory.mktemp("board") / "board.mp4"
    video = (
        "color=c=0x2E8B57:s=640x360:r=25:d=4,"
        "drawbox=x=40:y=16:w=160:h=40:color=black:t=fill,"
        "drawbox=x=120:y=24:w=24:h=24:color=white:t=fill:enable='lt(t,2)',"
        "drawbox=x=160:y=24:w=24:h=24:color=white:t=fill:enable='gte(t,2)'"
    )
    subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", video,
        "-f", "lavfi", "-i", "anoisesrc=d=4:c=white:a=0.05:seed=3",
        "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-t", "4", str(path),
    ], check=True, capture_output=True)
    return path


@pytest.fixture(scope="module")
def black_clip(require_ffmpeg, tmp_path_factory):
    path = tmp_path_factory.mktemp("black") / "black.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
        "color=c=black:s=160x120:r=5:d=6", "-f", "lavfi", "-i",
        "anoisesrc=d=6:c=white:a=0.02:seed=7", "-map", "0:v", "-map", "1:a",
        "-c:v", "mpeg4", "-q:v", "5", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-t", "6", str(path),
    ], check=True, capture_output=True)
    return path


def _gray_frame(path, t, vf):
    width, height = media.probe_size(path) if vf is None else (None, None)
    filters = "format=gray" if vf is None else f"{vf},format=gray"
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-ss", str(t), "-i", str(path),
        "-frames:v", "1", "-vf", filters, "-f", "rawvideo", "-",
    ], check=True, capture_output=True)
    data = np.frombuffer(result.stdout, np.uint8).astype(np.float64)
    if vf is None:
        return data.reshape(height, width)
    return data


def _expected_band(clip, t):
    x, y, w, h = BOARD
    return _gray_frame(clip, t, f"crop={w}:{h}:{x}:{y},scale=640:160").reshape(160, 640)


def _band(out, t):
    return _gray_frame(out, t, None)[40:200, 220:860]


def _mad(a, b):
    return float(np.mean(np.abs(a - b)))


def test_find_score_box_detects_board(board_clip):
    box = vertical.find_score_box(board_clip)
    assert box is not None
    x, y, w, h = box
    bx, by, bw, bh = BOARD
    assert x <= bx and y <= by and x + w >= bx + bw and y + h >= by + bh
    assert bx - x <= 12 and by - y <= 12
    assert (x + w) - (bx + bw) <= 12 and (y + h) - (by + bh) <= 12


def test_find_score_box_none_on_black(black_clip):
    assert vertical.find_score_box(black_clip) is None


@pytest.fixture(scope="module")
def board_renders(board_clip, tmp_path_factory):
    root = tmp_path_factory.mktemp("renders")
    with_box = vertical.render_vertical(board_clip, CROP, root / "box.mp4", score_box=BOARD)
    plain = vertical.render_vertical(board_clip, CROP, root / "plain.mp4")
    return with_box, plain


def test_render_with_box_is_1080x1920_h264(board_renders):
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,width,height", "-of", "csv=p=0", str(board_renders[0])],
        check=True, capture_output=True, text=True,
    )
    assert probe.stdout.strip() == "h264,1080,1920"


@pytest.mark.parametrize("t", [1.0, 3.0])
def test_top_band_matches_scaled_source_box(board_clip, board_renders, t):
    assert _mad(_band(board_renders[0], t), _expected_band(board_clip, t)) <= 8


def test_top_band_updates_live(board_clip, board_renders):
    assert _mad(_band(board_renders[0], 3.0), _expected_band(board_clip, 1.0)) >= 20


def test_top_band_check_can_fail_without_overlay(board_clip, board_renders):
    assert _mad(_band(board_renders[1], 1.0), _expected_band(board_clip, 1.0)) >= 40


def _has_drawtext():
    if shutil.which("ffmpeg") is None:
        return False
    filters = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True
    ).stdout
    return " drawtext " in filters


def test_render_with_box_and_caption_parses(board_clip, tmp_path):
    if not _has_drawtext():
        pytest.skip("ffmpeg has no drawtext filter")
    try:
        media.find_font()
    except MediaError as exc:
        pytest.skip(str(exc))
    out = vertical.render_vertical(
        board_clip, CROP, tmp_path / "cap.mp4", score_box=BOARD, caption="BÀN THẮNG · 34'"
    )
    assert media.probe_size(out) == (1080, 1920)
    assert _mad(_band(out, 1.0), _expected_band(board_clip, 1.0)) <= 8
