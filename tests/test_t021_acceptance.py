"""T-021 Tester acceptance tests (scoreboard overlay + event caption on vertical clips).

Written from the acceptance criteria in .office/TASK.md, independently of the
Developer's tests. Media is generated with ffmpeg in temporary directories only.
"""

from __future__ import annotations

import json
import logging
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import sportscut.pipeline
import sportscut.reframe
import sportscut.vertical
from sportscut import cli, media, vertical
from sportscut.media import MediaError
from sportscut.models import Segment
from sportscut.pipeline import PipelineError

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git") or "/usr/bin/git"
T004_SPEC = "docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md"
T036_SPEC = "docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md"
T043_SPEC = "docs/superpowers/specs/2026-11-24-t-043-render-vertical-9-16-clips-from-design.md"
VERT_HEADING = "## Video dọc 9:16 cho TikTok/Reels (cut --vertical)"
CROP_HEADING = "## Video dọc 9:16: đo khung cắt (eval-crop)"
T004_LAST = "Updated by T-004: sportscut.media also exposes require_ffmpeg()"
T021_NOTE = "Updated by T-021: sportscut.media also owns find_font()"
KEYS = ["start", "end", "score", "reason", "event", "event_confidence", "file"]
OLD_FILTER = "crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1"
BS3 = "\\" * 3  # three backslashes, ffmpeg's escaped apostrophe prefix
GOAL_34 = "BÀN THẮNG · 34'"
FONT = "/fonts/DejaVuSans.ttf"
DRAWTEXT_34 = (
    f"drawtext=fontfile=/fonts/DejaVuSans.ttf:text=BÀN THẮNG · 34{BS3}':expansion=none:"
    "fontsize=64:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=16:x=(w-text_w)/2:y=240"
)
BOX_GRAPH = (
    "split=2[sc_main][sc_box];[sc_main]crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,"
    "setsar=1[sc_v];[sc_box]crop=w=160:h=40:x=40:y=16,scale=640:160,setsar=1[sc_b];"
    "[sc_v][sc_b]overlay=x=220:y=40"
)


def _run(*args, **kw):
    return subprocess.run(list(args), capture_output=True, text=True, **kw)


def _ffprobe(path: Path, stream: str, entries: str) -> str:
    return _run("ffprobe", "-v", "error", "-select_streams", stream, "-show_entries",
                entries, "-of", "csv=p=0", str(path), check=True).stdout.strip()


# ---------------------------------------------------------------- fixtures
@pytest.fixture(scope="module")
def board_clip(require_ffmpeg, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("t021acc") / "board.mp4"
    vf = (
        "drawbox=x=40:y=16:w=160:h=40:color=black:t=fill,"
        "drawbox=x=120:y=24:w=24:h=24:color=white:t=fill:enable='lt(t,2)',"
        "drawbox=x=160:y=24:w=24:h=24:color=white:t=fill:enable='gte(t,2)'"
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y",
         "-f", "lavfi", "-i", "color=c=0x2E8B57:s=640x360:r=25:d=4",
         "-f", "lavfi", "-i", "anoisesrc=d=4:c=white:r=44100:a=0.02:seed=3",
         "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-t", "4", str(path)],
        check=True, capture_output=True,
    )
    return path


@pytest.fixture(scope="module")
def black_clip(require_ffmpeg, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("t021acc") / "black.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y",
         "-f", "lavfi", "-i", "color=c=black:s=160x120:r=5:d=6",
         "-f", "lavfi", "-i", "anoisesrc=d=6:c=white:r=44100:a=0.02:seed=7",
         "-c:v", "mpeg4", "-q:v", "5", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-t", "6", str(path)],
        check=True, capture_output=True,
    )
    return path


def _gray_frame(path: Path, t: float, vf: str) -> np.ndarray:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t}", "-i", str(path),
         "-frames:v", "1", "-vf", f"{vf},format=gray", "-f", "rawvideo", "-"],
        check=True, capture_output=True,
    )
    return np.frombuffer(result.stdout, np.uint8).astype(np.float64)


def _mad(a: np.ndarray, b: np.ndarray) -> float:
    assert a.shape == b.shape and a.size > 0
    return float(np.mean(np.abs(a - b)))


def _has_drawtext() -> bool:
    if shutil.which("ffmpeg") is None:
        return False
    out = _run("ffmpeg", "-hide_banner", "-filters").stdout
    return re.search(r"\sdrawtext\s", out) is not None


# ---------------------------------------------------------------- AC2
@pytest.mark.parametrize("event,start,end,expected", [
    ("goal", 2000, 2020, "BÀN THẮNG · 34'"),
    ("save", 0, 10, "CỨU THUA · 1'"),
    ("red_card", 60, 70, "THẺ ĐỎ · 2'"),
    ("controversy", 0, 10, "TRANH CÃI · 1'"),
])
def test_ac2_caption_text_examples(event, start, end, expected):
    assert vertical.caption_text(event, start, end) == expected


@pytest.mark.parametrize("event", ["other", "unknown", "", "GOAL"])
def test_ac2_caption_text_none_for_other_and_unknown(event):
    assert vertical.caption_text(event, 0, 10) is None


def test_ac2_separator_and_apostrophe_are_exact():
    text = vertical.caption_text("goal", 0, 10)
    assert " \u00b7 " in text
    assert text.endswith("1'") and "\u2019" not in text
    assert text.count("\u00b7") == 1


@pytest.mark.parametrize("start,end,minute", [
    (59.8, 60.0, 1),     # midpoint 59.9 s
    (59.0, 61.0, 2),     # midpoint exactly 60 s
    (0.0, 0.5, 1),
    (5390.0, 5410.0, 91),   # midpoint 5400 s -> floor(90)+1
    (5338.0, 5398.0, 90),   # midpoint 5368 s
])
def test_ac2_minute_formula(start, end, minute):
    assert vertical.caption_text("goal", start, end) == f"BÀN THẮNG · {minute}'"


# ---------------------------------------------------------------- AC3
@pytest.mark.parametrize("box,w,h,expected", [
    ((10, 4, 40, 10), 640, 360, (36, 12, 168, 48)),
    ((10, 4, 40, 10), 160, 120, (8, 4, 44, 16)),
    ((0, 0, 5, 3), 1920, 1080, (0, 0, 72, 48)),
])
def test_ac3_band_box_to_source_examples(box, w, h, expected):
    assert vertical.band_box_to_source(box, w, h) == expected


def _spec_band_to_source(box, width, height):
    x, y, w, h = box
    bx0, by0 = max(0, x - 1), max(0, y - 1)
    bx1, by1 = min(160, x + w + 1), min(30, y + h + 1)
    sx0, sy0 = bx0 * width // 160, by0 * height // 90
    sx1 = min(width, -(-bx1 * width // 160))
    sy1 = min(height, -(-by1 * height // 90))
    sx0 -= sx0 % 2
    sy0 -= sy0 % 2
    sx1 = min(width - width % 2, sx1 + sx1 % 2)
    sy1 = min(height - height % 2, sy1 + sy1 % 2)
    return (sx0, sy0, sx1 - sx0, sy1 - sy0)


def test_ac3_band_box_clamps_at_band_edges():
    # whole band -> top third of the frame, clamped to 160 columns and 30 rows
    assert vertical.band_box_to_source((0, 0, 160, 30), 640, 360) == (0, 0, 640, 120)
    # box touching the right/bottom band edge is not padded past it
    assert vertical.band_box_to_source((150, 25, 10, 5), 640, 360) == _spec_band_to_source(
        (150, 25, 10, 5), 640, 360)
    sx, sy, sw, sh = vertical.band_box_to_source((150, 25, 10, 5), 640, 360)
    assert sx + sw == 640 and sy + sh == 120


def test_ac3_band_box_random_boxes_are_even_inside_and_cover():
    rng = random.Random(21)
    for _ in range(300):
        width = rng.choice([160, 320, 641, 640, 1280, 1919, 1920])
        height = rng.choice([90, 120, 361, 360, 720, 1080])
        x, y = rng.randrange(0, 159), rng.randrange(0, 29)
        w, h = rng.randint(1, 160 - x), rng.randint(1, 30 - y)
        got = vertical.band_box_to_source((x, y, w, h), width, height)
        assert got == _spec_band_to_source((x, y, w, h), width, height)
        assert all(isinstance(v, int) for v in got)
        sx, sy, sw, sh = got
        assert sx % 2 == 0 and sy % 2 == 0 and sw % 2 == 0 and sh % 2 == 0
        assert sx >= 0 and sy >= 0 and sx + sw <= width and sy + sh <= height
        # covers the unpadded box scaled to source pixels
        assert sx <= x * width / 160 and sy <= y * height / 90
        assert sx + sw >= min(width - width % 2, (x + w) * width / 160 - 1)


@pytest.mark.parametrize("box,expected", [
    ((40, 16, 160, 40), (640, 160, 220, 40)),
    ((36, 12, 168, 48), (560, 160, 260, 40)),
])
def test_ac3_score_overlay_geometry_examples(box, expected):
    assert vertical.score_overlay_geometry(box) == expected


def test_ac3_overlay_geometry_wide_box_is_limited_by_width():
    sw, sh, ox, oy = vertical.score_overlay_geometry((0, 0, 1000, 20))
    assert (sw, sh, ox, oy) == (1000, 20, 40, 40)
    sw, sh, ox, oy = vertical.score_overlay_geometry((0, 0, 1800, 10))
    assert sw == 1000 and sh <= 160 and sw % 2 == 0 and sh % 2 == 0 and sh >= 2
    assert ox == 40 and oy == 40


def test_ac3_overlay_geometry_always_fits_the_top_band():
    rng = random.Random(5)
    for _ in range(200):
        w, h = rng.randint(2, 1920), rng.randint(2, 1080)
        sw, sh, ox, oy = vertical.score_overlay_geometry((0, 0, w, h))
        assert sw % 2 == 0 and sh % 2 == 0
        assert 2 <= sw <= 1000 and 2 <= sh <= 160
        assert ox == (1080 - sw) // 2 and oy == 40


# ---------------------------------------------------------------- AC4
@pytest.mark.parametrize("box", [
    (1, 2, 3), (1, 2, 3, 4, 5), [], None, "1,2,3,4", 5,
    (True, 0, 10, 10), (0, False, 10, 10), (0.0, 0, 10, 10), (0, 0, 10.5, 10),
    ("0", 0, 10, 10),
])
def test_ac4_bad_shape_or_type(box):
    with pytest.raises(ValueError, match=r"^invalid score box: expected four integers x,y,w,h$"):
        vertical.check_score_box(box, 640, 360)


@pytest.mark.parametrize("box", [(-1, 0, 10, 10), (0, -2, 10, 10), (0, 0, 1, 10), (0, 0, 10, 1),
                                 (0, 0, 0, 0), (0, 0, -4, 10)])
def test_ac4_bad_values(box):
    with pytest.raises(ValueError, match=r"^invalid score box: x,y must be >= 0 and w,h >= 2$"):
        vertical.check_score_box(box, 640, 360)


def test_ac4_out_of_frame_exact_message():
    with pytest.raises(ValueError) as exc:
        vertical.check_score_box((0, 0, 200, 10), 160, 120)
    assert str(exc.value) == "invalid score box: 0,0,200,10 does not fit the 160x120 frame"
    with pytest.raises(ValueError, match="^invalid score box: 0,115,10,6 does not fit the 160x120 frame$"):
        vertical.check_score_box((0, 115, 10, 6), 160, 120)


def test_ac4_valid_box_returned_as_tuple_of_ints():
    assert vertical.check_score_box([1, 2, 3, 4], 640, 360) == (1, 2, 3, 4)
    got = vertical.check_score_box((0, 0, 160, 120), 160, 120)  # exactly the full frame fits
    assert got == (0, 0, 160, 120) and type(got) is tuple
    assert all(type(v) is int for v in got)


# ---------------------------------------------------------------- AC5
def test_ac5_drawtext_filter_exact():
    assert vertical.drawtext_filter(GOAL_34, FONT) == DRAWTEXT_34
    assert vertical.drawtext_filter(GOAL_34, Path(FONT)) == DRAWTEXT_34


def test_ac5_box_and_caption_exact_graph():
    got = vertical.vertical_filter([(0.0, 320.0)], 640, 360, score_box=(40, 16, 160, 40),
                                   caption=GOAL_34, fontfile=FONT)
    assert got == BOX_GRAPH + "," + DRAWTEXT_34
    assert got.startswith(BOX_GRAPH + ",drawtext=")
    assert f":text=BÀN THẮNG · 34{BS3}':expansion=none:" in got
    assert f"34{BS3 + chr(92)}'" not in got  # not four backslashes


def test_ac5_caption_only_box_only_neither():
    crop = [(0.0, 320.0)]
    assert vertical.vertical_filter(crop, 640, 360) == OLD_FILTER
    assert vertical.vertical_filter(crop, 640, 360, None, None, None) == OLD_FILTER
    assert vertical.vertical_filter(crop, 640, 360, fontfile=FONT) == OLD_FILTER
    assert (vertical.vertical_filter(crop, 640, 360, caption=GOAL_34, fontfile=FONT)
            == OLD_FILTER + "," + vertical.drawtext_filter(GOAL_34, FONT))
    box_only = vertical.vertical_filter(crop, 640, 360, score_box=(40, 16, 160, 40))
    assert box_only == BOX_GRAPH and box_only.endswith("overlay=x=220:y=40")
    assert "drawtext" not in box_only


def test_ac5_caption_without_fontfile_raises():
    with pytest.raises(ValueError, match="^caption needs a fontfile$"):
        vertical.vertical_filter([(0.0, 320.0)], 640, 360, caption=GOAL_34)
    with pytest.raises(ValueError, match="^caption needs a fontfile$"):
        vertical.vertical_filter([(0.0, 320.0)], 640, 360, score_box=(40, 16, 160, 40), caption="x")


def test_ac5_out_of_frame_box_raises_in_filter():
    with pytest.raises(ValueError, match="^invalid score box: 600,0,100,40 does not fit the 640x360 frame$"):
        vertical.vertical_filter([(0.0, 320.0)], 640, 360, score_box=(600, 0, 100, 40))


def test_ac5_fontfile_special_characters_are_escaped():
    got = vertical.drawtext_filter("A", "C:\\a,b[c];d'e")
    assert got.startswith(r"drawtext=fontfile=C\\:\\\\a\,b\[c\]\;d\\\'e:text=A:expansion=none:")


def test_ac5_caption_special_characters_are_escaped():
    got = vertical.drawtext_filter("a:b,c;d[e]f'g\\h", FONT)
    assert r":text=a\\:b\,c\;d\[e\]f\\\'g\\\\h:expansion=none:" in got


# ---------------------------------------------------------------- AC6
def _wire(monkeypatch, font=Path("/f/font.ttf")):
    calls = []
    monkeypatch.setattr(media, "probe_size", lambda p: calls.append(("probe_size", p)) or (640, 360))
    monkeypatch.setattr(media, "find_font", lambda: calls.append(("find_font",)) or font)

    def fake_filter(clip, vf, out):
        calls.append(("filter_video", clip, vf, out))
        return Path(out)

    monkeypatch.setattr(media, "filter_video", fake_filter)
    for name in ("sample_top_band", "cut_clip", "find_tool"):
        if hasattr(media, name):
            monkeypatch.setattr(media, name, lambda *a, _n=name: pytest.fail(f"{_n} called"))
    return calls


def test_ac6_no_new_arguments_makes_t043_calls(monkeypatch, tmp_path):
    calls = _wire(monkeypatch)
    out = tmp_path / "v" / "c.mp4"
    assert vertical.render_vertical("clip.mp4", [(0.0, 320.0)], out) == out
    assert calls == [("probe_size", "clip.mp4"), ("filter_video", "clip.mp4", OLD_FILTER, out)]
    assert out.parent.is_dir()


def test_ac6_caption_calls_find_font_between(monkeypatch, tmp_path):
    calls = _wire(monkeypatch, font=Path(FONT))
    out = tmp_path / "c.mp4"
    vertical.render_vertical("clip.mp4", [(0.0, 320.0)], out, caption=GOAL_34)
    assert [c[0] for c in calls] == ["probe_size", "find_font", "filter_video"]
    assert calls[2][2] == OLD_FILTER + "," + DRAWTEXT_34


def test_ac6_box_and_caption_graph(monkeypatch, tmp_path):
    calls = _wire(monkeypatch, font=Path(FONT))
    vertical.render_vertical("clip.mp4", [(0.0, 320.0)], tmp_path / "c.mp4",
                             score_box=(40, 16, 160, 40), caption=GOAL_34)
    assert [c[0] for c in calls] == ["probe_size", "find_font", "filter_video"]
    assert calls[2][2] == BOX_GRAPH + "," + DRAWTEXT_34


def test_ac6_box_only_never_calls_find_font(monkeypatch, tmp_path):
    calls = _wire(monkeypatch)
    monkeypatch.setattr(media, "find_font", lambda: pytest.fail("find_font called"))
    vertical.render_vertical("clip.mp4", [(0.0, 320.0)], tmp_path / "c.mp4", score_box=(40, 16, 160, 40))
    assert [c[0] for c in calls] == ["probe_size", "filter_video"]
    assert calls[1][2] == BOX_GRAPH


def test_ac6_none_never_calls_find_font(monkeypatch, tmp_path):
    _wire(monkeypatch)
    monkeypatch.setattr(media, "find_font", lambda: pytest.fail("find_font called"))
    vertical.render_vertical("clip.mp4", [(0.0, 320.0)], tmp_path / "c.mp4", score_box=None, caption=None)


@pytest.mark.parametrize("bad", [[], [(1.0,)], [(1.0, 2.0), (0.5, 3.0)], None])
def test_ac6_invalid_crop_path_raises_before_probe(monkeypatch, tmp_path, bad):
    calls = _wire(monkeypatch)
    with pytest.raises(ValueError, match="^invalid crop path"):
        vertical.render_vertical("clip.mp4", bad, tmp_path / "c.mp4", score_box=(0, 0, 10, 10), caption="x")
    assert calls == []


def test_ac6_missing_font_error_propagates(monkeypatch, tmp_path):
    _wire(monkeypatch)

    def no_font():
        raise MediaError("no font with Vietnamese support found; install one")

    monkeypatch.setattr(media, "find_font", no_font)
    monkeypatch.setattr(media, "filter_video", lambda *a: pytest.fail("filter_video called"))
    with pytest.raises(MediaError, match="^no font with Vietnamese support found"):
        vertical.render_vertical("clip.mp4", [(0.0, 320.0)], tmp_path / "c.mp4", caption=GOAL_34)


# ---------------------------------------------------------------- AC7
class _Proc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


def _fontconfig(monkeypatch, list_out, match_out="", match_rc=0, list_rc=0, which=None):
    calls = []
    tools = {"fc-list": "/bin/fc-list", "fc-match": "/bin/fc-match"}
    if which is not None:
        tools.update(which)
    monkeypatch.setattr(media.shutil, "which", lambda name: tools.get(name))

    def fake_run(argv, **kw):
        calls.append((list(argv), kw))
        if argv[0] == "/bin/fc-list":
            return _Proc(list_out, list_rc, "fc-list broke")
        if argv[0] == "/bin/fc-match":
            return _Proc(match_out, match_rc, "fc-match broke")
        pytest.fail(f"unexpected command {argv}")

    monkeypatch.setattr(media.subprocess, "run", fake_run)
    return calls


def test_ac7_fc_list_missing(monkeypatch):
    calls = _fontconfig(monkeypatch, "", which={"fc-list": None})
    with pytest.raises(MediaError) as exc:
        media.find_font()
    assert str(exc.value) == "fc-list not found on PATH; install fontconfig to draw captions"
    assert calls == []


def test_ac7_fc_match_missing(monkeypatch, tmp_path):
    font = tmp_path / "a.ttf"
    font.write_bytes(b"x")
    _fontconfig(monkeypatch, f"{font}\n", which={"fc-match": None})
    with pytest.raises(MediaError) as exc:
        media.find_font()
    assert str(exc.value) == "fc-match not found on PATH; install fontconfig to draw captions"


@pytest.mark.parametrize("listing", ["", "\n\n", "/nope/a.ttf\n/nope/b.ttf\n", "   \n/nope/x.otf"])
def test_ac7_no_existing_font(monkeypatch, listing):
    _fontconfig(monkeypatch, listing)
    with pytest.raises(MediaError, match="^no font with Vietnamese support found"):
        media.find_font()


def test_ac7_directory_is_not_a_font(monkeypatch, tmp_path):
    _fontconfig(monkeypatch, f"{tmp_path}\n")
    with pytest.raises(MediaError, match="^no font with Vietnamese support found"):
        media.find_font()


def test_ac7_fc_list_failure(monkeypatch):
    _fontconfig(monkeypatch, "", list_rc=1)
    with pytest.raises(MediaError, match="^fc-list failed"):
        media.find_font()


def test_ac7_preference_order_and_argv(monkeypatch, tmp_path):
    a, b = tmp_path / "A.ttf", tmp_path / "B.ttf"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    missing = tmp_path / "missing.ttf"
    calls = _fontconfig(monkeypatch, f"{a}\n  {b}  \n{missing}\n\n",
                        match_out=f"{missing}\n/other/font.ttf\n{b}\n{a}\n")
    result = media.find_font()
    assert result == b and isinstance(result, Path)
    assert [c[0] for c in calls] == [
        ["/bin/fc-list", "--format", "%{file}\n", ":lang=vi"],
        ["/bin/fc-match", "-s", "--format", "%{file}\n", "sans-serif:lang=vi"],
    ]
    for _, kw in calls:
        assert kw.get("capture_output") is True and kw.get("text") is True and kw.get("check") is False


def test_ac7_fc_match_failure_falls_back_to_sorted_first(monkeypatch, tmp_path):
    z, m = tmp_path / "z.ttf", tmp_path / "m.ttf"
    z.write_bytes(b"z")
    m.write_bytes(b"m")
    _fontconfig(monkeypatch, f"{z}\n{m}\n", match_out=f"{z}\n", match_rc=1)
    assert media.find_font() == m


def test_ac7_no_fc_match_line_in_set_falls_back_to_sorted_first(monkeypatch, tmp_path):
    z, m = tmp_path / "z.ttf", tmp_path / "m.ttf"
    z.write_bytes(b"z")
    m.write_bytes(b"m")
    _fontconfig(monkeypatch, f"{z}\n{m}\n", match_out="/a/x.ttf\n/b/y.ttf\n")
    assert media.find_font() == m


def test_ac7_real_find_font_returns_a_file():
    if shutil.which("fc-list") is None or shutil.which("fc-match") is None:
        pytest.skip("fontconfig not on PATH")
    try:
        font = media.find_font()
    except MediaError as exc:
        pytest.skip(f"no Vietnamese font: {exc}")
    assert isinstance(font, Path) and font.is_file()


def test_ac7_subprocess_only_in_media_and_incidents():
    pkg = ROOT / "sportscut"
    for name in ("vertical.py", "pipeline.py", "cli.py"):
        assert "subprocess" not in (pkg / name).read_text(encoding="utf-8"), name
    importers = sorted(
        p.relative_to(pkg).as_posix() for p in pkg.rglob("*.py")
        if re.search(r"^\s*(import subprocess|from subprocess import)", p.read_text(encoding="utf-8"), re.M)
    )
    assert importers == ["events/incidents.py", "media.py"]


# ---------------------------------------------------------------- AC8
def test_ac8_find_score_box_detects_board(board_clip):
    box = vertical.find_score_box(board_clip)
    assert box is not None
    x, y, w, h = box
    assert x <= 40 and y <= 16 and x + w >= 200 and y + h >= 56, box
    assert 40 - x <= 12 and 16 - y <= 12 and (x + w) - 200 <= 12 and (y + h) - 56 <= 12, box
    assert all(type(v) is int for v in box)


def test_ac8_find_score_box_none_on_black(burst_video, black_clip):
    assert vertical.find_score_box(black_clip) is None
    assert vertical.find_score_box(burst_video) is None


def test_ac8_find_score_box_skips_probe_when_no_band(monkeypatch):
    monkeypatch.setattr(media, "sample_top_band", lambda p: np.zeros((3, 30, 160), np.uint8))
    monkeypatch.setattr(vertical.scoreboard, "find_box", lambda frames: None)
    monkeypatch.setattr(media, "probe_size", lambda p: pytest.fail("probe_size called"))
    assert vertical.find_score_box("x.mp4") is None


def test_ac8_find_score_box_maps_band_to_source(monkeypatch):
    seen = {}
    monkeypatch.setattr(media, "sample_top_band", lambda p: seen.setdefault("frames", object()))
    monkeypatch.setattr(vertical.scoreboard, "find_box",
                        lambda frames: (10, 4, 40, 10) if frames is seen["frames"] else None)
    monkeypatch.setattr(media, "probe_size", lambda p: (640, 360))
    assert vertical.find_score_box("x.mp4") == (36, 12, 168, 48)


# ---------------------------------------------------------------- AC9
BAND_OUT = "crop=640:160:220:40"
BAND_SRC = "crop=160:40:40:16,scale=640:160"


@pytest.fixture(scope="module")
def overlay_render(board_clip, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("t021render") / "with_box.mp4"
    vertical.render_vertical(board_clip, [(0.0, 320.0)], out, score_box=(40, 16, 160, 40))
    return out


def test_ac9_render_is_1080x1920_h264(overlay_render):
    assert _ffprobe(overlay_render, "v:0", "stream=codec_name,width,height") == "h264,1080,1920"
    assert _ffprobe(overlay_render, "a:0", "stream=codec_type") == "audio"


@pytest.mark.parametrize("t", [1.0, 3.0])
def test_ac9_top_band_matches_scaled_source_box(board_clip, overlay_render, t):
    got = _gray_frame(overlay_render, t, BAND_OUT)
    expected = _gray_frame(board_clip, t, BAND_SRC)
    assert got.size == 640 * 160
    assert _mad(got, expected) <= 8


def test_ac9_scoreline_updates_live(board_clip, overlay_render):
    late = _gray_frame(overlay_render, 3.0, BAND_OUT)
    early_expected = _gray_frame(board_clip, 1.0, BAND_SRC)
    assert _mad(late, early_expected) >= 20


def test_ac9_without_box_the_band_does_not_match(board_clip, tmp_path):
    plain = tmp_path / "plain.mp4"
    vertical.render_vertical(board_clip, [(0.0, 320.0)], plain)
    got = _gray_frame(plain, 1.0, BAND_OUT)
    assert _mad(got, _gray_frame(board_clip, 1.0, BAND_SRC)) >= 40


def test_ac9_detected_box_overlay_also_shows_the_board(board_clip, tmp_path):
    box = vertical.find_score_box(board_clip)
    assert box is not None
    out = tmp_path / "detected.mp4"
    vertical.render_vertical(board_clip, [(0.0, 320.0)], out, score_box=box)
    sw, sh, ox, oy = vertical.score_overlay_geometry(box)
    bx, by, bw, bh = box
    got = _gray_frame(out, 1.0, f"crop={sw}:{sh}:{ox}:{oy}")
    expected = _gray_frame(board_clip, 1.0, f"crop={bw}:{bh}:{bx}:{by},scale={sw}:{sh}")
    assert _mad(got, expected) <= 8


@pytest.mark.skipif(not _has_drawtext(), reason="ffmpeg has no drawtext filter")
def test_ac9_real_render_with_caption_parses(board_clip, tmp_path):
    try:
        media.find_font()
    except MediaError as exc:
        pytest.skip(f"no Vietnamese font: {exc}")
    out = tmp_path / "caption.mp4"
    vertical.render_vertical(board_clip, [(0.0, 320.0)], out, score_box=(40, 16, 160, 40), caption=GOAL_34)
    assert _ffprobe(out, "v:0", "stream=width,height") == "1080,1920"
    assert _mad(_gray_frame(out, 1.0, BAND_OUT), _gray_frame(board_clip, 1.0, BAND_SRC)) <= 8


# ---------------------------------------------------------------- AC10
GOAL_SEGMENT = Segment(2.0, 8.0, 1.0, "r", "goal", 0.9)
GOAL_CAPTION = "BÀN THẮNG · 1'"


def _record_render(monkeypatch):
    renders = []

    def fake_render(clip, crop_path, dest, **kw):
        renders.append(((clip, crop_path, dest), kw))
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"v")
        return Path(dest)

    monkeypatch.setattr(sportscut.vertical, "render_vertical", fake_render)
    monkeypatch.setattr(sportscut.reframe, "plan_crop", lambda clip: [(0.0, 80.0)])
    return renders


def test_ac10_goal_without_box_forwards_caption_only(burst_video, tmp_path, monkeypatch):
    monkeypatch.setattr(sportscut.pipeline, "select_segments", lambda *a, **k: [GOAL_SEGMENT])
    renders = _record_render(monkeypatch)
    out = tmp_path / "out"
    entries = sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True)
    assert len(renders) == 1
    (clip, crop, dest), kw = renders[0]
    assert kw == {"caption": GOAL_CAPTION}
    assert Path(clip) == out / "clip_01.mp4" and Path(dest) == out / "vertical" / "clip_01.mp4"
    assert entries[0]["vertical_file"] == "vertical/clip_01.mp4"


def test_ac10_manual_box_skips_detection(burst_video, tmp_path, monkeypatch):
    monkeypatch.setattr(sportscut.pipeline, "select_segments", lambda *a, **k: [GOAL_SEGMENT])
    monkeypatch.setattr(sportscut.vertical, "find_score_box", lambda *a: pytest.fail("find_score_box called"))
    renders = _record_render(monkeypatch)
    sportscut.pipeline.run(burst_video, tmp_path / "o", top=1, min_len=4, max_len=6,
                           vertical=True, score_box=(8, 4, 44, 16))
    assert [kw for _, kw in renders] == [{"score_box": (8, 4, 44, 16), "caption": GOAL_CAPTION}]


def test_ac10_manual_box_as_list_is_forwarded_as_tuple(burst_video, tmp_path, monkeypatch):
    monkeypatch.setattr(sportscut.vertical, "find_score_box", lambda *a: pytest.fail("find_score_box called"))
    renders = _record_render(monkeypatch)
    sportscut.pipeline.run(burst_video, tmp_path / "o", top=1, min_len=4, max_len=6,
                           vertical=True, score_box=[8, 4, 44, 16])
    assert [kw for _, kw in renders] == [{"score_box": (8, 4, 44, 16)}]


def test_ac10_detected_box_is_forwarded_per_clip(burst_video, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(sportscut.vertical, "find_score_box",
                        lambda clip: seen.append(Path(clip)) or (2, 2, 20, 10))
    renders = _record_render(monkeypatch)
    out = tmp_path / "o"
    entries = sportscut.pipeline.run(burst_video, out, top=2, min_len=4, max_len=6, vertical=True)
    assert seen == [out / e["file"] for e in entries]
    assert [kw for _, kw in renders] == [{"score_box": (2, 2, 20, 10)}] * len(entries)


def test_ac10_neither_gives_exactly_three_positional_args(burst_video, tmp_path, monkeypatch):
    calls = []

    def strict_render(clip, crop_path, dest):
        calls.append((clip, crop_path, dest))
        return Path(dest)

    monkeypatch.setattr(sportscut.vertical, "render_vertical", strict_render)
    monkeypatch.setattr(sportscut.reframe, "plan_crop", lambda clip: [(0.0, 80.0)])
    entries = sportscut.pipeline.run(burst_video, tmp_path / "o", top=2, min_len=4, max_len=6, vertical=True)
    assert len(calls) == len(entries) == 2


def test_ac10_end_to_end_filter_contains_caption(burst_video, tmp_path, monkeypatch):
    monkeypatch.setattr(sportscut.pipeline, "select_segments", lambda *a, **k: [GOAL_SEGMENT])
    monkeypatch.setattr(media, "find_font", lambda: Path(FONT))
    filters = []

    def fake_filter(clip, vf, out):
        filters.append(vf)
        return Path(out)

    monkeypatch.setattr(media, "filter_video", fake_filter)
    sportscut.pipeline.run(burst_video, tmp_path / "o", top=1, min_len=4, max_len=6, vertical=True)
    assert len(filters) == 1
    assert f"text=BÀN THẮNG · 1{BS3}'" in filters[0]
    assert f"fontfile={FONT}:" in filters[0]
    assert "overlay" not in filters[0]  # black clip: no box detected


# ---------------------------------------------------------------- AC11
def test_ac11_warning_per_clip_and_vertical_still_rendered(burst_video, tmp_path, caplog):
    out = tmp_path / "o"
    with caplog.at_level(logging.WARNING, logger="sportscut.pipeline"):
        entries = sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True)
    records = [r for r in caplog.records if r.name == "sportscut.pipeline" and r.levelno == logging.WARNING]
    assert len(records) == len(entries) == 1
    message = records[0].getMessage()
    assert "no scoreboard found in clip_01.mp4" in message and "--score-box" in message
    vfile = out / "vertical" / "clip_01.mp4"
    assert vfile.is_file()
    assert _ffprobe(vfile, "v:0", "stream=width,height") == "1080,1920"
    assert list(entries[0]) == KEYS + ["vertical_file"]


def test_ac11_one_warning_per_clip_for_two_clips(burst_video, tmp_path, caplog, monkeypatch):
    _record_render(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="sportscut.pipeline"):
        entries = sportscut.pipeline.run(burst_video, tmp_path / "o", top=2, min_len=4, max_len=6, vertical=True)
    msgs = [r.getMessage() for r in caplog.records if r.name == "sportscut.pipeline"]
    assert len(entries) == 2 and len(msgs) == 2
    for entry, msg in zip(entries, msgs):
        assert f"no scoreboard found in {entry['file']}" in msg


def test_ac11_no_warning_with_manual_or_detected_box(burst_video, tmp_path, caplog, monkeypatch):
    _record_render(monkeypatch)
    with caplog.at_level(logging.WARNING, logger="sportscut.pipeline"):
        sportscut.pipeline.run(burst_video, tmp_path / "a", top=1, min_len=4, max_len=6,
                               vertical=True, score_box=(0, 0, 20, 10))
        monkeypatch.setattr(sportscut.vertical, "find_score_box", lambda clip: (0, 0, 20, 10))
        sportscut.pipeline.run(burst_video, tmp_path / "b", top=1, min_len=4, max_len=6, vertical=True)
    assert [r for r in caplog.records if r.name == "sportscut.pipeline"] == []


def test_ac11_no_warning_without_vertical(burst_video, tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="sportscut.pipeline"):
        sportscut.pipeline.run(burst_video, tmp_path / "o", top=1, min_len=4, max_len=6)
    assert [r for r in caplog.records if r.name == "sportscut.pipeline"] == []


def test_ac11_null_handler():
    handlers = logging.getLogger("sportscut.pipeline").handlers
    assert any(type(h) is logging.NullHandler for h in handlers)


def _cut(video, out, *extra):
    return subprocess.run(
        [sys.executable, "-m", "sportscut", "cut", str(video), "--out", str(out), *extra],
        cwd=ROOT, capture_output=True, text=True,
    )


def test_ac11_cli_vertical_on_black_has_empty_stderr(burst_video, tmp_path):
    out = tmp_path / "OUT"
    result = _cut(burst_video, out, "--top", "1", "--min-len", "4", "--max-len", "6", "--vertical")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == [str(out / "clip_01.mp4"), str(out / "vertical" / "clip_01.mp4")]


# ---------------------------------------------------------------- AC12
def test_ac12_out_of_frame_box_raises_before_export(burst_video, tmp_path):
    out = tmp_path / "out"
    with pytest.raises(PipelineError) as exc:
        sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6,
                               vertical=True, score_box=(0, 0, 200, 10))
    assert str(exc.value) == "invalid score box: 0,0,200,10 does not fit the 160x120 frame"
    assert not (out / "clip_01.mp4").exists()
    assert not (out / "vertical").exists()


@pytest.mark.parametrize("box", [(1, 2, 3), (0, 0, 1, 1), (True, 0, 10, 10)])
def test_ac12_malformed_box_is_pipeline_error(burst_video, tmp_path, box):
    out = tmp_path / "out"
    with pytest.raises(PipelineError, match="^invalid score box: "):
        sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True, score_box=box)
    assert not (out / "clip_01.mp4").exists()


def test_ac12_score_box_without_vertical(burst_video, tmp_path):
    out = tmp_path / "out"
    with pytest.raises(PipelineError) as exc:
        sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, score_box=(0, 0, 10, 10))
    assert str(exc.value) == "score_box needs vertical=True"
    assert not (out / "clip_01.mp4").exists()


def test_ac12_manifest_unchanged_without_score_box(burst_video, tmp_path, monkeypatch):
    plain = sportscut.pipeline.run(burst_video, tmp_path / "p", top=2, min_len=4, max_len=6)
    assert all(list(e) == KEYS for e in plain)
    _record_render(monkeypatch)
    vert = sportscut.pipeline.run(burst_video, tmp_path / "v", top=2, min_len=4, max_len=6, vertical=True)
    assert all(list(e) == KEYS + ["vertical_file"] for e in vert)
    assert [{k: e[k] for k in KEYS} for e in vert] == plain
    text = (tmp_path / "v" / "highlights.json").read_text(encoding="utf-8")
    assert text == json.dumps(vert, indent=2) + "\n"


# ---------------------------------------------------------------- AC13
def _fake_cli_run(monkeypatch):
    seen = {}

    def fake_run(video, out_dir, **kwargs):
        seen.update(kwargs)
        return [{"file": "clip_01.mp4", "vertical_file": "vertical/clip_01.mp4"}]

    monkeypatch.setattr(cli, "run", fake_run)
    return seen


def test_ac13_score_box_forwarded(monkeypatch, tmp_path):
    seen = _fake_cli_run(monkeypatch)
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--vertical", "--score-box", "40,16,160,40"]) == 0
    assert seen["score_box"] == (40, 16, 160, 40) and type(seen["score_box"]) is tuple
    assert seen["vertical"] is True


def test_ac13_score_box_default_none(monkeypatch, tmp_path):
    seen = _fake_cli_run(monkeypatch)
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--vertical"]) == 0
    assert "score_box" in seen and seen["score_box"] is None


@pytest.mark.parametrize("value", ["1,2,3", "a,b,c,d", "1,2,3,4,5", "1.5,2,3,4", "", "1;2;3;4"])
def test_ac13_bad_format_exits_2(monkeypatch, tmp_path, capsys, value):
    _fake_cli_run(monkeypatch)
    with pytest.raises(SystemExit) as exc:
        cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--vertical", "--score-box", value])
    assert exc.value.code == 2
    assert "expected x,y,w,h as four non-negative integers" in capsys.readouterr().err


def test_ac13_score_box_needs_vertical(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "run", lambda *a, **k: pytest.fail("run called"))
    with pytest.raises(SystemExit) as exc:
        cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--score-box", "1,2,3,4"])
    assert exc.value.code == 2
    assert "--score-box needs --vertical" in capsys.readouterr().err


def test_ac13_media_error_exits_1(monkeypatch, tmp_path, capsys):
    msg = "no font with Vietnamese support found; install one"

    def fake_run(video, out_dir, **kwargs):
        raise MediaError(msg)

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--vertical"]) == 1
    assert capsys.readouterr().err == f"sportscut: error: {msg}\n"


def test_ac13_real_cli_out_of_frame_box_exits_1(burst_video, tmp_path):
    out = tmp_path / "OUT"
    result = _cut(burst_video, out, "--top", "1", "--min-len", "4", "--max-len", "6",
                  "--vertical", "--score-box", "0,0,200,10")
    assert result.returncode == 1
    assert result.stderr == "sportscut: error: invalid score box: 0,0,200,10 does not fit the 160x120 frame\n"
    assert not (out / "clip_01.mp4").exists()


def test_ac13_real_cli_manual_box_on_board_clip(board_clip, tmp_path):
    out = tmp_path / "o"
    result = _cut(board_clip, out, "--top", "1", "--min-len", "2", "--max-len", "4",
                  "--vertical", "--score-box", "40,16,160,40")
    assert result.returncode == 0, result.stderr
    for line in result.stdout.splitlines():
        assert Path(line).is_file()


def test_ac13_real_cli_manual_box_end_to_end_pixels(burst_video, tmp_path):
    # burst_video is black: a manual box makes the vertical clip's top band
    # equal the (black) source crop instead of the black centre crop -> just check it renders.
    out = tmp_path / "o"
    result = _cut(burst_video, out, "--top", "1", "--min-len", "4", "--max-len", "6",
                  "--vertical", "--score-box", "8,4,44,16")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [str(out / "clip_01.mp4"), str(out / "vertical" / "clip_01.mp4")]
    assert _ffprobe(out / "vertical" / "clip_01.mp4", "v:0", "stream=width,height") == "1080,1920"


# ---------------------------------------------------------------- AC14
def _git_show(ref_path: str) -> str | None:
    result = _run(GIT, "show", ref_path, cwd=ROOT)
    return result.stdout if result.returncode == 0 else None


def test_ac14_readme():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert VERT_HEADING in readme
    section = readme.split(VERT_HEADING, 1)[1].split("\n## ", 1)[0]
    for needle in ("--score-box", "BÀN THẮNG · 34'", "fc-list :lang=vi"):
        assert needle in section, needle
    assert "sportscut cut match.mp4 --out out --vertical --score-box 40,16,160,40" in section
    assert readme.index(VERT_HEADING) < readme.index(CROP_HEADING)
    tail = readme[readme.index(CROP_HEADING):]
    base = _git_show("main:README.md")
    if base is not None and CROP_HEADING in base:
        assert tail == base[base.index(CROP_HEADING):]
        old_section = base.split(VERT_HEADING, 1)[1].split("\n## ", 1)[0]
        assert section.startswith(old_section.rstrip("\n"))


def test_ac14_t036_spec():
    text = (ROOT / T036_SPEC).read_text(encoding="utf-8")
    assert T021_NOTE in text
    last = text.rstrip().split("\n\n")[-1]
    assert last.startswith(T004_LAST)
    assert text.index(T021_NOTE) < text.index(T004_LAST)
    para = [p for p in text.split("\n\n") if p.startswith(T021_NOTE)]
    assert para and "fc-list :lang=vi" in para[0] and "MediaError" in para[0]


def test_ac14_t004_spec():
    text = (ROOT / T004_SPEC).read_text(encoding="utf-8")
    headings = re.findall(r"^## .*$", text, re.M)
    assert headings[-1] == "## Updated by T-021"
    assert text.index("## Updated by T-018") < text.index("## Updated by T-021")
    section = text.split("## Updated by T-021", 1)[1]
    assert "score_box=None" in section and "--score-box" in section


def test_ac14_t043_spec():
    text = (ROOT / T043_SPEC).read_text(encoding="utf-8")
    headings = re.findall(r"^## .*$", text, re.M)
    assert headings[-1] == "## Updated by T-021"
    section = text.split("## Updated by T-021", 1)[1]
    for needle in ("score_box", "caption", "WARNING", "NullHandler"):
        assert needle in section, needle


# ---------------------------------------------------------------- AC15
def _own_branch_base() -> str:
    branch = _run(GIT, "rev-parse", "--abbrev-ref", "HEAD", cwd=ROOT).stdout.strip()
    if not branch.startswith("office/T-021"):
        pytest.skip("scope checks only run on the T-021 branch")
    base = _run(GIT, "merge-base", "main", "HEAD", cwd=ROOT)
    if base.returncode != 0:
        pytest.skip("no main branch to compare against")
    return base.stdout.strip()


def test_ac15_no_deleted_lines_in_protected_files():
    base = _own_branch_base()
    files = ["sportscut/media.py", "sportscut/cli.py", "tests/test_media.py", "tests/test_cli.py",
             "tests/test_pipeline.py", "README.md", T004_SPEC, T036_SPEC, T043_SPEC,
             "docs/superpowers/DECISIONS.md", "docs/superpowers/INDEX.md"]
    result = _run(GIT, "diff", "--numstat", base, "--", *files, cwd=ROOT)
    assert result.returncode == 0
    for line in result.stdout.splitlines():
        added, deleted, name = line.split("\t")
        assert deleted == "0", line


def test_ac15_untouched_paths_and_no_mp4():
    base = _own_branch_base()
    paths = ["sportscut/events/", "sportscut/reframe.py", "sportscut/export.py",
             "tests/conftest.py", "tests/fixtures/"]
    result = _run(GIT, "diff", "--name-only", base, "--", *paths, cwd=ROOT)
    assert result.returncode == 0 and result.stdout.strip() == ""
    untracked = _run(GIT, "status", "--porcelain", "--", *paths, cwd=ROOT).stdout
    assert untracked.strip() == "" or all(
        l.endswith(".pyc") or "__pycache__" in l or "eval_crop" in l for l in untracked.splitlines())
    assert _run(GIT, "ls-files", "*.mp4", cwd=ROOT).stdout.strip() == ""


def test_ac15_preexisting_tests_unedited():
    base = _own_branch_base()
    result = _run(GIT, "diff", "--numstat", base, "--", "tests/", cwd=ROOT)
    for line in result.stdout.splitlines():
        added, deleted, name = line.split("\t")
        assert deleted == "0", line
