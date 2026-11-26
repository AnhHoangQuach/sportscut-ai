"""T-018 (implemented by T-043) Tester acceptance tests.

Written from the acceptance criteria in .office/TASK.md, independently of the
Developer's tests. Media is generated with ffmpeg in temporary directories only.
"""

from __future__ import annotations

import json
import math
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
from sportscut import cli, media, reframe, vertical
from sportscut.media import MediaError

ROOT = Path(__file__).resolve().parents[1]
GIT = shutil.which("git") or "/usr/bin/git"
T004_SPEC = "docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md"
T036_SPEC = "docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md"
NEW_HEADING = "## Video dọc 9:16 cho TikTok/Reels (cut --vertical)"
CROP_HEADING = "## Video dọc 9:16: đo khung cắt (eval-crop)"
T004_LAST = "Updated by T-004: sportscut.media also exposes require_ffmpeg()"
T018_NOTE = "Updated by T-018: sportscut.media also owns filter_video"
KEYS = ["start", "end", "score", "reason", "event", "event_confidence", "file"]


def _clip(v, lo, hi):
    return min(max(v, lo), hi)


def _eval(expr: str, t: float) -> float:
    return eval(expr, {"__builtins__": {}}, {"t": t, "clip": _clip})  # noqa: S307


def _ffprobe(path: Path, stream: str, entries: str) -> str:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries",
         entries, "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def _gray_frame(path: Path, t: float) -> np.ndarray:
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
        capture_output=True, check=True,
    )
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(1920, 1080)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([GIT, *args], cwd=ROOT, capture_output=True, text=True)


def _own_branch_or_skip() -> str:
    branch = _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if not branch.startswith("office/T-043"):
        pytest.skip("T-043 scope check runs only on its own office/T-043 branch")
    base = _git("merge-base", "main", "HEAD")
    if base.returncode:
        pytest.skip("no main branch to diff against")
    return base.stdout.strip()


@pytest.fixture(scope="module")
def marker_clip(require_ffmpeg, tmp_path_factory) -> Path:
    """640x360, 25 fps, 4 s, 20x20 white marker centred at x = 120 + 100*t."""
    path = tmp_path_factory.mktemp("t018") / "marker.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y",
         "-f", "lavfi", "-i", "color=c=0x1e7a32:s=640x360:r=25:d=4",
         "-f", "lavfi", "-i", "color=c=white:s=20x20:r=25:d=4",
         "-f", "lavfi", "-i", "anoisesrc=d=4:c=white:r=44100:a=0.05:seed=3",
         "-filter_complex", "[0:v][1:v]overlay=x='110+100*t':y=170[v]",
         "-map", "[v]", "-map", "2:a", "-c:v", "mpeg4", "-q:v", "2",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "4", str(path)],
        check=True, capture_output=True,
    )
    return path


# AC1 -----------------------------------------------------------------------
def test_ac1_precondition_symbols_exist():
    reframe_src = (ROOT / "sportscut" / "reframe.py").read_text(encoding="utf-8")
    media_src = (ROOT / "sportscut" / "media.py").read_text(encoding="utf-8")
    assert "def plan_crop" in reframe_src
    assert "def crop_width" in reframe_src
    assert "def probe_size" in media_src


# AC2 -----------------------------------------------------------------------
def test_ac2_filter_video_missing_input(tmp_path, monkeypatch):
    missing = tmp_path / "nope.mp4"
    monkeypatch.setattr(media, "find_tool", lambda name: pytest.fail("tool lookup before file check"))
    with pytest.raises(MediaError) as excinfo:
        media.filter_video(missing, "scale=32:24", tmp_path / "o.mp4")
    assert str(excinfo.value) == f"media file not found: {missing}"


def test_ac2_filter_video_scales_and_keeps_aac(synthetic_video, tmp_path):
    dest = tmp_path / "o.mp4"
    result = media.filter_video(synthetic_video, "scale=32:24", dest)
    assert result == Path(dest)
    assert isinstance(result, Path)
    assert media.probe_size(dest) == (32, 24)
    assert _ffprobe(dest, "v:0", "stream=codec_name") == "h264"
    assert _ffprobe(dest, "a:0", "stream=codec_name") == "aac"


def test_ac2_filter_video_accepts_str_paths(synthetic_video, tmp_path):
    dest = str(tmp_path / "s.mp4")
    assert media.filter_video(str(synthetic_video), "scale=32:24", dest) == Path(dest)


def test_ac2_filter_video_invalid_filter(synthetic_video, tmp_path):
    with pytest.raises(MediaError) as excinfo:
        media.filter_video(synthetic_video, "nosuchfilter", tmp_path / "o.mp4")
    assert re.match(rf"^ffmpeg failed for {re.escape(str(synthetic_video))}: .+", str(excinfo.value))


def test_ac2_filter_video_tolerates_clip_without_audio(require_ffmpeg, tmp_path):
    src = tmp_path / "silent.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
         "color=c=black:s=64x48:r=10:d=1", "-c:v", "mpeg4", str(src)],
        check=True, capture_output=True,
    )
    dest = media.filter_video(src, "scale=32:24", tmp_path / "o.mp4")
    assert media.probe_size(dest) == (32, 24)
    assert _ffprobe(dest, "a", "stream=codec_name") == ""


def test_ac2_new_modules_do_not_run_subprocess():
    importers = sorted(
        p.relative_to(ROOT / "sportscut").as_posix()
        for p in (ROOT / "sportscut").rglob("*.py")
        if re.search(r"^\s*(import subprocess|from subprocess import)", p.read_text(encoding="utf-8"), re.M)
    )
    # events/incidents.py already imported subprocess on the base (T-015 decision);
    # T-043 must not add any importer.
    assert importers == ["events/incidents.py", "media.py"]
    for name in ("vertical.py", "pipeline.py", "cli.py"):
        assert "subprocess" not in (ROOT / "sportscut" / name).read_text(encoding="utf-8")


# AC3 -----------------------------------------------------------------------
def test_ac3_exact_expressions():
    assert (
        vertical.crop_x_expression([(0.0, 101.0), (1.0, 201.0)], 640, 202)
        == "0.0000+100.000000*(clip(t,0.0000,1.0000)-0.0000)"
    )
    assert vertical.crop_x_expression([(0, 320), (1, 320)], 640, 202) == "219.0000"


def test_ac3_expression_is_flat_without_if():
    path = [(0, 100), (0.5, 400), (1.2, 50), (3, 300), (3.4, 300), (4, 600)]
    expr = vertical.crop_x_expression(path, 640, 202)
    assert "if(" not in expr
    term = r"[+-]\d+\.\d{6}\*\(clip\(t,\d+\.\d{4},\d+\.\d{4}\)-\d+\.\d{4}\)"
    assert re.fullmatch(rf"\d+\.\d{{4}}(?:{term})*", expr), expr
    # one term per non-flat segment: the (3, 300)->(3.4, 300) pair is skipped
    assert expr.count("clip(") == 4
    signs = re.findall(r"([+-])\d+\.\d{6}\*\(clip", expr)
    assert signs == ["+", "-", "+", "+"]


# AC4 -----------------------------------------------------------------------
def _check_against_interp(path, width, crop_w):
    expr = vertical.crop_x_expression(path, width, crop_w)
    ts = [float(t) for t, _ in path]
    half = crop_w / 2
    lefts = [min(max(float(x), half), width - half) - half for _, x in path]
    probes = list(ts)
    probes += [(a + b) / 2 for a, b in zip(ts, ts[1:])]
    probes += [ts[0] - 1.0, ts[0] - 0.01, ts[-1] + 0.01, ts[-1] + 10.0]
    probes = [p for p in probes if p >= 0] + [0.0]
    for t in probes:
        got = _eval(expr, t)
        want = float(np.interp(t, ts, lefts))
        assert abs(got - want) <= 0.01, (t, got, want, expr)
        # bounds within the AC4 0.01 px tolerance (spec mandates .4f/.6f rounding)
        assert -0.01 <= got <= width - crop_w + 0.01


def test_ac4_matches_np_interp_on_random_paths():
    rng = random.Random(18)
    for _ in range(60):
        width = rng.choice([160, 640, 1280, 1920])
        height = rng.choice([120, 360, 720, 1080])
        crop_w = reframe.crop_width(width, height)
        n = rng.randint(1, 40)
        t = round(rng.uniform(0, 3), 4)
        path = []
        for _ in range(n):
            path.append((t, rng.uniform(-200, width + 200)))
            t = round(t + rng.choice([0.2, 0.0001, 0.5, rng.uniform(0.001, 2)]) + 0.0001, 4)
        _check_against_interp(path, width, crop_w)


def test_ac4_real_plan_crop_grid_matches_interp():
    path = [(k / 5, 320 + 200 * math.sin(k / 3)) for k in range(450)]  # 90 s at 5 Hz
    _check_against_interp(path, 640, 202)


def test_ac4_clamped_example():
    expr = vertical.crop_x_expression([(0, -1000), (1, 5000)], 640, 202)
    assert _eval(expr, 0) == pytest.approx(0, abs=0.01)
    assert _eval(expr, 0.5) == pytest.approx(219, abs=0.01)
    for t in (1, 2, 5, 100):
        assert _eval(expr, t) == pytest.approx(438, abs=0.01)
    for k in range(101):
        assert 0 <= _eval(expr, k / 50) <= 438


def test_ac4_single_keyframe_holds_everywhere():
    expr = vertical.crop_x_expression([(2.0, 80.0)], 160, 66)
    for t in (0, 1, 2, 3, 99):
        assert _eval(expr, t) == pytest.approx(47.0, abs=0.01)


# AC5 -----------------------------------------------------------------------
INVALID_PATHS = [
    [],
    (),
    [(0, float("nan"))],
    [(0, float("inf"))],
    [(float("nan"), 5)],
    [(1, 5), (1, 6)],
    [(0, 5), (2, 6), (1, 7)],
    [(-1, 5)],
    [(-0.0001, 5)],
    [(0, True)],
    [(False, 5)],
    [(0,)],
    [(0, 1, 2)],
    [(0, "5")],
    [None],
    [5],
]


@pytest.mark.parametrize("path", INVALID_PATHS, ids=repr)
def test_ac5_invalid_paths_raise(path):
    with pytest.raises(ValueError) as excinfo:
        vertical.crop_x_expression(path, 640, 202)
    assert str(excinfo.value).startswith("invalid crop path: ")
    with pytest.raises(ValueError) as excinfo:
        vertical.vertical_filter(path, 640, 360)
    assert str(excinfo.value).startswith("invalid crop path: ")


def test_ac5_valid_variants_are_accepted():
    vertical.crop_x_expression([[0, 5]], 640, 202)
    vertical.crop_x_expression([(np.float64(0.0), np.int64(300))], 640, 202)
    vertical.crop_x_expression([(0, -99999), (1, 99999)], 640, 202)


@pytest.mark.parametrize("path", [[], [(1, 5), (0, 5)], [(0, float("nan"))]], ids=repr)
def test_ac5_render_vertical_validates_before_probing(path, tmp_path, monkeypatch):
    monkeypatch.setattr(media, "probe_size", lambda *a: pytest.fail("probe_size called"))
    monkeypatch.setattr(media, "filter_video", lambda *a: pytest.fail("filter_video called"))
    out = tmp_path / "v" / "o.mp4"
    with pytest.raises(ValueError) as excinfo:
        vertical.render_vertical(tmp_path / "missing.mp4", path, out)
    assert str(excinfo.value).startswith("invalid crop path: ")
    assert not out.parent.exists()


def test_ac5_render_vertical_invalid_path_unpatched_missing_clip(tmp_path):
    with pytest.raises(ValueError, match=r"^invalid crop path: "):
        vertical.render_vertical(tmp_path / "missing.mp4", [], tmp_path / "o.mp4")


def test_ac5_too_long_expression():
    path = [(k / 5, 101 + (k % 2) * 300) for k in range(25_000)]
    with pytest.raises(ValueError) as excinfo:
        vertical.crop_x_expression(path, 640, 202)
    assert str(excinfo.value) == "crop path too long: 25000 keyframes"
    assert vertical.MAX_EXPRESSION == 100_000


def test_ac5_long_but_flat_path_is_fine():
    path = [(k / 5, 320.0) for k in range(25_000)]
    assert vertical.crop_x_expression(path, 640, 202) == "219.0000"


# AC6 -----------------------------------------------------------------------
def test_ac6_vertical_filter_exact():
    assert (
        vertical.vertical_filter([(0.0, 320.0)], 640, 360)
        == "crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1"
    )
    assert vertical.OUT_WIDTH == 1080 and vertical.OUT_HEIGHT == 1920


def test_ac6_vertical_filter_uses_reframe_crop_width(monkeypatch):
    monkeypatch.setattr(reframe, "crop_width", lambda w, h: 100)
    assert vertical.vertical_filter([(0.0, 320.0)], 640, 360).startswith(
        "crop=w=100:h=360:x='270.0000'"
    )


# AC7 -----------------------------------------------------------------------
def test_ac7_render_vertical_monkeypatched_wiring(tmp_path, monkeypatch):
    calls = []
    clip = tmp_path / "clip.mp4"
    out = tmp_path / "a" / "b" / "o.mp4"
    monkeypatch.setattr(media, "probe_size", lambda p: calls.append(("probe", p)) or (640, 360))

    def fake_filter(p, vf, dest):
        assert Path(dest).parent.is_dir()
        calls.append(("filter", p, vf, dest))
        return Path(dest)

    monkeypatch.setattr(media, "filter_video", fake_filter)
    assert vertical.render_vertical(clip, [(0.0, 320.0)], out) == out
    assert calls == [
        ("probe", clip),
        ("filter", clip, "crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1", out),
    ]


def test_ac7_render_vertical_real_ffmpeg(synthetic_video, tmp_path):
    out = tmp_path / "missing" / "dir" / "o.mp4"
    result = vertical.render_vertical(synthetic_video, [(0.0, 80.0)], out)
    assert result == Path(out)
    assert out.is_file()
    assert _ffprobe(out, "v:0", "stream=codec_name,width,height") == "h264,1080,1920"
    assert _ffprobe(out, "a:0", "stream=codec_name") == "aac"
    assert abs(_duration(out) - _duration(synthetic_video)) <= 0.3


def test_ac7_render_vertical_missing_clip_is_media_error(tmp_path):
    with pytest.raises(MediaError, match="media file not found"):
        vertical.render_vertical(tmp_path / "missing.mp4", [(0.0, 80.0)], tmp_path / "o.mp4")


# AC8 -----------------------------------------------------------------------
def _white_columns(frame: np.ndarray) -> np.ndarray:
    return np.nonzero(frame > 200)[1]


def test_ac8_moving_path_keeps_marker_centred(marker_clip, tmp_path):
    out = tmp_path / "moving.mp4"
    path = [(k / 5, 120 + 100 * k / 5) for k in range(20)]
    vertical.render_vertical(marker_clip, path, out)
    for t in (0.5, 1.5, 2.5, 3.5):
        cols = _white_columns(_gray_frame(out, t))
        assert cols.size > 0, f"no marker at t={t}"
        assert abs(cols.mean() - 540) <= 108, (t, cols.mean())


def test_ac8_static_centre_loses_marker(marker_clip, tmp_path):
    out = tmp_path / "static.mp4"
    vertical.render_vertical(marker_clip, [(0.0, 320.0)], out)
    for t in (0.5, 3.5):
        assert _white_columns(_gray_frame(out, t)).size == 0, f"marker visible at t={t}"


# AC9 -----------------------------------------------------------------------
def test_ac9_pipeline_vertical_end_to_end(burst_video, tmp_path):
    out = tmp_path / "out"
    entries = sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True)
    assert len(entries) == 1
    entry = entries[0]
    assert list(entry) == KEYS + ["vertical_file"]
    assert entry["file"] == "clip_01.mp4"
    assert entry["vertical_file"] == "vertical/clip_01.mp4"
    vfile = out / "vertical" / "clip_01.mp4"
    assert _ffprobe(vfile, "v:0", "stream=codec_name,width,height") == "h264,1080,1920"
    assert _ffprobe(vfile, "a:0", "stream=codec_name") == "aac"
    assert abs(_duration(vfile) - _duration(out / "clip_01.mp4")) <= 0.3
    manifest = out / "highlights.json"
    assert entries == json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest.read_text(encoding="utf-8") == json.dumps(entries, indent=2) + "\n"


# AC10 ----------------------------------------------------------------------
def test_ac10_plan_crop_result_forwarded_per_clip(burst_video, tmp_path, monkeypatch):
    out = tmp_path / "out"
    sentinels = {}
    renders = []

    def fake_plan(clip):
        sentinels[Path(clip)] = object()
        return sentinels[Path(clip)]

    def fake_render(clip, crop_path, dest):
        renders.append((clip, crop_path, dest))
        return Path(dest)

    monkeypatch.setattr(sportscut.reframe, "plan_crop", fake_plan)
    monkeypatch.setattr(sportscut.vertical, "render_vertical", fake_render)
    entries = sportscut.pipeline.run(burst_video, out, top=2, min_len=4, max_len=6, vertical=True)
    assert len(entries) == 2
    expected = [
        (out / e["file"], sentinels[out / e["file"]], out / "vertical" / e["file"]) for e in entries
    ]
    assert list(sentinels) == [out / e["file"] for e in entries]
    assert len(renders) == 2
    for (clip, crop_path, dest), (eclip, epath, edest) in zip(renders, expected):
        assert Path(clip) == eclip
        assert crop_path is epath
        assert Path(dest) == edest
    assert [e["vertical_file"] for e in entries] == [f"vertical/{e['file']}" for e in entries]


def test_ac10_render_failure_propagates_and_keeps_manifest(burst_video, tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(sportscut.reframe, "plan_crop", lambda clip: [(0.0, 80.0)])

    def boom(*args):
        raise MediaError("ffmpeg failed for x: boom")

    monkeypatch.setattr(sportscut.vertical, "render_vertical", boom)
    with pytest.raises(MediaError, match="boom"):
        sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True)
    entries = json.loads((out / "highlights.json").read_text(encoding="utf-8"))
    assert entries and all("vertical_file" not in e for e in entries)


def test_ac10_empty_selection_renders_nothing(burst_video, tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(sportscut.pipeline, "select_segments", lambda *a, **k: [])
    monkeypatch.setattr(sportscut.reframe, "plan_crop", lambda *a: pytest.fail("plan_crop called"))
    monkeypatch.setattr(sportscut.vertical, "render_vertical", lambda *a: pytest.fail("render called"))
    assert sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True) == []


# AC11 ----------------------------------------------------------------------
def test_ac11_default_run_never_renders(burst_video, tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setattr(sportscut.reframe, "plan_crop", lambda *a: pytest.fail("plan_crop called"))
    monkeypatch.setattr(sportscut.vertical, "render_vertical", lambda *a: pytest.fail("render called"))
    entries = sportscut.pipeline.run(burst_video, out, top=1, min_len=4, max_len=6)
    explicit = sportscut.pipeline.run(burst_video, tmp_path / "o2", top=1, min_len=4, max_len=6, vertical=False)
    assert not (out / "vertical").exists()
    assert not (tmp_path / "o2" / "vertical").exists()
    assert entries and all(list(e) == KEYS for e in entries)
    assert entries == explicit
    text = (out / "highlights.json").read_text(encoding="utf-8")
    assert "vertical_file" not in text
    assert json.loads(text) == entries


# AC12 ----------------------------------------------------------------------
def _cut(video, out, *extra):
    return subprocess.run(
        [sys.executable, "-m", "sportscut", "cut", str(video), "--out", str(out),
         "--top", "1", "--min-len", "4", "--max-len", "6", *extra],
        cwd=ROOT, capture_output=True, text=True,
    )


def test_ac12_cli_vertical_prints_two_lines(burst_video, tmp_path):
    out = tmp_path / "OUT"
    result = _cut(burst_video, out, "--vertical")
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.splitlines() == [str(out / "clip_01.mp4"), str(out / "vertical" / "clip_01.mp4")]
    assert _ffprobe(out / "vertical" / "clip_01.mp4", "v:0", "stream=width,height") == "1080,1920"


def test_ac12_cli_without_flag_is_unchanged(burst_video, tmp_path):
    out = tmp_path / "OUT"
    result = _cut(burst_video, out)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [str(out / "clip_01.mp4")]
    assert not (out / "vertical").exists()


@pytest.mark.parametrize("flag,expected", [(["--vertical"], True), ([], False)])
def test_ac12_cli_forwards_vertical(flag, expected, tmp_path, monkeypatch, capsys):
    seen = {}

    def fake_run(video, out_dir, **kwargs):
        seen.update(kwargs)
        return [{"file": "clip_01.mp4"}]

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), *flag]) == 0
    assert seen["vertical"] is expected
    assert capsys.readouterr().out.splitlines() == [str(tmp_path / "clip_01.mp4")]


def test_ac12_cli_vertical_media_error_is_reported(tmp_path, monkeypatch, capsys):
    def fake_run(video, out_dir, **kwargs):
        raise MediaError("ffmpeg failed for clip: boom")

    monkeypatch.setattr(cli, "run", fake_run)
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--vertical"]) == 1
    assert capsys.readouterr().err == "sportscut: error: ffmpeg failed for clip: boom\n"


# AC13 ----------------------------------------------------------------------
def test_ac13_documentation():
    t004 = (ROOT / T004_SPEC).read_text(encoding="utf-8")
    assert "## Updated by T-018" in t004
    section = t004.split("## Updated by T-018", 1)[1]
    assert t004.index("## Updated by T-039") < t004.index("## Updated by T-018")
    for needle in ("vertical=False", "vertical_file", "--vertical"):
        assert needle in section
    ac1 = [line for line in t004.splitlines() if re.match(r"^\W*AC1\b", line)]
    assert ac1 and "events=None" in ac1[0]

    t036 = (ROOT / T036_SPEC).read_text(encoding="utf-8")
    assert T018_NOTE in t036
    last_para = t036.rstrip().split("\n\n")[-1]
    assert last_para.startswith(T004_LAST)
    assert t036.index(T018_NOTE) < t036.index(T004_LAST)

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert NEW_HEADING in readme
    section = readme.split(NEW_HEADING, 1)[1].split("\n## ", 1)[0]
    for needle in ("sportscut cut match.mp4 --out out --vertical", "out/vertical/clip_NN.mp4",
                   "1080x1920", "vertical_file", "plan_crop"):
        assert needle in section


# AC14 ----------------------------------------------------------------------
def test_ac14_no_tracked_mp4():
    result = _git("ls-files", "*.mp4")
    if result.returncode:
        pytest.skip("not a git checkout")
    assert result.stdout.strip() == ""


# AC15 (git scope checks; gated to the T-043 branch) -------------------------
APPEND_ONLY = [
    "sportscut/media.py", "sportscut/cli.py", "README.md",
    "tests/test_media.py", "tests/test_pipeline.py", "tests/test_cli.py",
    T004_SPEC, T036_SPEC,
]
FROZEN = [
    "tests/conftest.py", "sportscut/reframe.py", "sportscut/eval_crop.py", "sportscut/export.py",
    "sportscut/api.py", "sportscut/evaluate.py", "sportscut/eval_player.py", "sportscut/detect.py",
    "sportscut/events", "tests/fixtures", "pyproject.toml", ".gitignore", "agent-office",
    "AGENTS.md", "CLAUDE.md",
]
GATE_FILES = [
    "tests/test_t014_acceptance.py", "tests/test_t034b_acceptance.py", "tests/test_t017_acceptance.py",
    "tests/test_t042_acceptance.py", "tests/test_t042_round2_acceptance.py",
    "tests/test_t042_tester_acceptance.py", "tests/test_t044_acceptance.py",
]


def test_ac15_append_only_files_have_no_deleted_lines():
    base = _own_branch_or_skip()
    result = _git("diff", "--numstat", base, "--", *APPEND_ONLY)
    assert result.returncode == 0, result.stderr
    for line in result.stdout.splitlines():
        added, deleted, name = line.split("\t")
        assert deleted == "0", f"{name} deletes {deleted} lines"


def test_ac15_frozen_paths_untouched():
    base = _own_branch_or_skip()
    result = _git("diff", "--name-only", base, "--", *FROZEN)
    assert result.stdout.strip() == ""


def test_ac15_scope_gates_only_add_a_branch_skip():
    base = _own_branch_or_skip()
    diff = _git("diff", "-U0", base, "--", *GATE_FILES).stdout
    removed = [l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
    added = [l for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++")]
    assert removed == []
    for line in added:
        assert re.search(r"rev-parse|branch|startswith|pytest\.skip|^\+\s*$", line), line


def test_ac15_readme_new_section_before_untouched_eval_crop_section():
    base = _own_branch_or_skip()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    old = _git("show", f"{base}:README.md").stdout
    assert readme.index(NEW_HEADING) < readme.index(CROP_HEADING)
    assert readme.count(CROP_HEADING) == 1
    old_tail = old[old.index(CROP_HEADING):]
    assert readme.endswith(old_tail)
    assert "\n## " not in readme[readme.index(CROP_HEADING) + 3:]
