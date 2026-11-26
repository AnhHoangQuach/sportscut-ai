"""T-045 Tester acceptance tests, written from the T-045 acceptance criteria."""

from __future__ import annotations

import importlib.util
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from sportscut import eval_crop, media, reframe

ROOT = Path(__file__).resolve().parents[1]
CROP_HEADING = "## Video dọc 9:16: đo khung cắt (eval-crop)"
CAM_HEADING = "## Camera ảo bám cầu thủ (T-019)"
FIELD, RED, GREY = (40, 140, 60), (200, 30, 30), (128, 128, 128)
SPECS = ROOT / "docs" / "superpowers" / "specs"


def _frame(fill=FIELD, h=180, w=320):
    return np.full((h, w, 3), fill, np.uint8)


def _clip(path: Path, frames: np.ndarray) -> Path:
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "640x360",
           "-r", "25", "-i", "pipe:0", "-an", "-c:v", "mpeg4", "-q:v", "2", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, input=frames.tobytes(), check=True)
    return path


def _players(n):
    f = np.full((n, 360, 640, 3), FIELD, np.uint8)
    f[:, 150:182, 96:112] = RED
    f[:, 150:182, 128:144] = RED
    return f


def _grey(n):
    return np.full((n, 360, 640, 3), GREY, np.uint8)


def _merge_base() -> str:
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    r = subprocess.run(["git", "merge-base", "main", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        pytest.skip("main unavailable")
    return r.stdout.strip()


def _numstat(base: str) -> dict[str, tuple[int, int]]:
    out = subprocess.run(["git", "diff", "--numstat", base], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    rows = [line.split("\t") for line in out.splitlines() if line]
    return {p: (int(a) if a != "-" else 0, int(d) if d != "-" else 0) for a, d, p in rows}


# AC1 / AC13 --------------------------------------------------------------------
def test_ac1_ac13_forbidden_paths_untouched_and_append_only():
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if not branch.startswith("office/T-045"):
        pytest.skip("T-045 scope check runs only on its own office/T-045 branch")
    base = _merge_base()
    stat = _numstat(base)
    forbidden = ("sportscut/eval_crop.py", "sportscut/cli.py", "sportscut/pipeline.py", "sportscut/evaluate.py",
                 "sportscut/eval_player.py", "sportscut/export.py", "sportscut/events/", "tests/fixtures/eval_crop/",
                 "tests/test_eval_crop.py", "tests/conftest.py", "pyproject.toml", ".gitignore", "agent-office/",
                 "docs/superpowers/plans/2026-11-23-t-017-add-a-measurable-9-16-reframing.md")
    for path in stat:
        assert not path.startswith(forbidden), path
        assert not path.endswith(".mp4"), path
    for path in ("tests/test_media.py", "tests/test_reframe.py", "sportscut/media.py", "README.md"):
        assert stat.get(path, (0, 0))[1] == 0, f"{path} has deleted lines"
    tracked = subprocess.run(["git", "ls-files", "*.mp4"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert tracked.stdout.strip() == ""


# AC2 ---------------------------------------------------------------------------
def test_ac2_sample_frames_on_synthetic_video(synthetic_video):
    frames = media.sample_frames(synthetic_video, 5, 80, 60)
    assert isinstance(frames, np.ndarray) and frames.dtype == np.uint8
    assert frames.ndim == 4 and frames.shape[1:] == (60, 80, 3) and 29 <= frames.shape[0] <= 31
    assert all(frames[i].mean() < 30 for i in range(14))
    assert all(frames[i].mean() > 225 for i in range(16, frames.shape[0]))


def test_ac2_sample_frames_errors_and_no_subprocess_in_reframe(tmp_path, require_ffmpeg):
    missing = tmp_path / "nope.mp4"
    with pytest.raises(media.MediaError, match=r"^media file not found: "):
        media.sample_frames(missing, 5, 80, 60)
    audio = tmp_path / "a.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "1",
                    "-c:a", "aac", str(audio)], check=True)
    with pytest.raises(media.MediaError, match=r"^ffmpeg failed for "):
        media.sample_frames(audio, 5, 80, 60)
    assert "import subprocess" not in (ROOT / "sportscut" / "reframe.py").read_text(encoding="utf-8")


# AC3 / AC4 ---------------------------------------------------------------------
@pytest.mark.parametrize("rgb,expected", [((40, 140, 60), True), ((36, 128, 54), True), ((200, 30, 30), False),
                                          ((30, 60, 200), False), ((255, 255, 255), False), ((0, 0, 0), False),
                                          ((128, 128, 128), False)])
def test_ac3_green_mask(rgb, expected):
    mask = reframe.green_mask(_frame(rgb, 4, 5))
    assert mask.dtype == bool and mask.shape == (4, 5) and bool(mask.all()) is expected and bool(mask.any()) is expected


def test_ac4_player_mask_exact_and_ignores_lines_crowd_and_side_band():
    f = _frame()
    f[40:56, 100:108] = RED
    expected = np.zeros((180, 320), bool)
    expected[41:55, 101:107] = True
    assert expected.sum() == 84
    assert np.array_equal(reframe.player_mask(f), expected)
    f[:, 159:161] = (255, 255, 255)
    f[0:30] = GREY
    f[5:25, 200:210] = RED
    f[:, 0:20] = GREY
    f[100:120, 5:15] = RED
    assert np.array_equal(reframe.player_mask(f), expected)


def test_ac4_no_field_returns_none():
    assert reframe.player_mask(_frame(GREY)) is None
    f = _frame(GREY)
    f[:, :64] = FIELD  # exactly 20% green
    assert reframe.player_mask(f) is None


# AC5 ---------------------------------------------------------------------------
def test_ac5_target_x_heaviest_window_and_none_cases():
    f = _frame()
    for r, c in ((40, 100), (40, 116), (100, 250)):
        f[r:r + 16, c:c + 8] = RED
    assert abs(reframe.target_x(f, 101) - 112.0) < 1e-9
    small = _frame()
    small[50:54, 50:54] = RED
    assert reframe.target_x(small, 101) is None
    assert reframe.target_x(_frame(GREY), 101) is None


# AC6 ---------------------------------------------------------------------------
P = dict(width=640, cw=202, dead_zone=0.03, ease=0.5, max_pan=0.2)


def _assert_bounded_held(smoother, targets):
    xs = smoother(targets, **P)
    assert len(xs) == len(targets)
    for i in range(1, len(xs)):
        assert abs(xs[i] - xs[i - 1]) <= 25.6 + 1e-9
        if targets[i] is None:
            assert xs[i] == xs[i - 1]
    assert all(101 <= x <= 539 for x in xs)


@pytest.mark.parametrize("targets,expected", [([None, None, 400.0], [320.0, 320.0, 345.6]),
                                              ([200.0, 230.0, 260.0], [200.0, 205.4, 223.1]),
                                              ([300.0, 310.0, 280.9, None, 319.0], [300.0] * 5),
                                              ([10.0], [101.0]), ([700.0], [539.0]), ([], [])])
def test_ac6_smooth_path_exact(targets, expected):
    got = reframe.smooth_path(targets, **P)
    assert len(got) == len(expected) and all(abs(a - b) < 1e-9 for a, b in zip(got, expected))


def test_ac6_converges_easing_and_random():
    xs = reframe.smooth_path([101.0] + [539.0] * 80, **P)
    assert all(b >= a and b - a <= 25.6 + 1e-9 for a, b in zip(xs, xs[1:]))
    assert max(xs) <= 519.8 + 1e-9 and abs(xs[-1] - 519.8) < 1e-3
    pure = reframe.smooth_path([320, 420, 420, 420], 640, 202, dead_zone=0, ease=0.5, max_pan=10)
    assert all(abs(a - b) < 1e-9 for a, b in zip(pure, [320, 370, 395, 407.5]))
    rng = np.random.default_rng(0)
    vals, holes = rng.uniform(0, 640, 200), rng.random(200) < 0.2
    _assert_bounded_held(reframe.smooth_path, [None if h else float(v) for v, h in zip(vals, holes)])


def _uncapped(targets, width, cw, dead_zone, ease, max_pan):
    return reframe.smooth_path(targets, width, cw, dead_zone, ease, max_pan=1e9)


def _recentre_on_none(targets, width, cw, dead_zone, ease, max_pan):
    xs = reframe.smooth_path(targets, width, cw, dead_zone, ease, max_pan)
    return [width / 2 if t is None else x for t, x in zip(targets, xs)]


def test_ac6_ac9_checks_can_fail_on_broken_smoothers():
    jumpy = [101.0, 539.0, 101.0, 539.0]
    with pytest.raises(AssertionError):
        _assert_bounded_held(_uncapped, jumpy)
    with pytest.raises(AssertionError):
        _assert_bounded_held(_recentre_on_none, [200.0, 200.0, None, None])


# AC7 ---------------------------------------------------------------------------
def test_ac7_center_plan_and_plan_crop_contract(synthetic_video, monkeypatch, tmp_path):
    expected = [(t, 80.0) for t in reframe.sample_times(6.0)]
    assert reframe.plan_crop(synthetic_video) == expected
    with pytest.raises(media.MediaError):
        reframe.plan_crop(tmp_path / "missing.mp4")

    def boom(*a, **k):
        raise AssertionError("must not run")

    monkeypatch.setattr(reframe.media, "sample_frames", boom)
    assert reframe.center_plan(synthetic_video) == expected
    monkeypatch.setattr(reframe.media, "probe_duration", boom)
    with pytest.raises(ValueError):
        reframe.plan_crop(synthetic_video, aspect=0)


# AC8 / AC9 ---------------------------------------------------------------------
def test_ac8_follows_static_players_and_no_field_is_centre(tmp_path, require_ffmpeg):
    plan = reframe.plan_crop(_clip(tmp_path / "p.mp4", _players(100)))
    assert [t for t, _ in plan] == reframe.sample_times(4.0)
    assert all(101 <= x <= 140 for _, x in plan)
    assert all(x == 320.0 for _, x in reframe.plan_crop(_clip(tmp_path / "g.mp4", _grey(100))))


def test_ac9_starts_centre_eases_then_holds(tmp_path, require_ffmpeg):
    plan = reframe.plan_crop(_clip(tmp_path / "gp.mp4", np.concatenate([_grey(50), _players(50)])))
    assert all(x == 320.0 for t, x in plan if t <= 1.8)
    later = [x for t, x in plan if t >= 1.8]
    assert all(b <= a and a - b <= 25.6 + 1e-6 for a, b in zip(later, later[1:]))
    assert later[-1] < 320
    plan = dict(reframe.plan_crop(_clip(tmp_path / "pg.mp4", np.concatenate([_players(50), _grey(50)]))))
    assert all(x == plan[1.8] for t, x in plan.items() if t >= 2.0)


def test_design3_moving_plan_renders_vertically(tmp_path, require_ffmpeg):
    # Design 3 / T-043: the 5 Hz moving plan is consumed by the vertical renderer as-is.
    from sportscut import vertical
    clip = _clip(tmp_path / "gp.mp4", np.concatenate([_grey(50), _players(50)]))
    plan = reframe.plan_crop(clip)
    assert len({x for _, x in plan}) > 1
    out = vertical.render_vertical(clip, plan, tmp_path / "v" / "gp.mp4")
    assert media.probe_size(out) == (1080, 1920) and media.probe_duration(out) > 3.5


# AC10 / AC11 -------------------------------------------------------------------
@pytest.fixture(scope="module")
def built(tmp_path_factory, require_ffmpeg):
    spec = importlib.util.spec_from_file_location("t045_build", ROOT / "tests/fixtures/eval_crop/build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path_factory.mktemp("t045_eval_crop")
    mod.build_all(out)
    return out


def _no_timing(report):
    r = json.loads(json.dumps(report))
    r.pop("seconds_per_min")
    for c in r["per_clip"]:
        c.pop("seconds_per_min")
    return r


def test_ac10_before_after_gate(built, monkeypatch):
    after = eval_crop.evaluate_dir(built)
    clip = next(built.glob("*/clip.mp4"))
    assert reframe.plan_crop(clip) == reframe.plan_crop(clip)
    monkeypatch.setattr(reframe, "plan_crop", reframe.center_plan)
    before = eval_crop.evaluate_dir(built)
    assert after["ball_in_crop"] > before["ball_in_crop"]
    assert after["players_in_crop"] > before["players_in_crop"]
    assert after["jitter"] <= 0.002 and after["seconds_per_min"] <= 6.0
    readme = (ROOT / "README.md").read_text(encoding="utf-8").split(CROP_HEADING, 1)[1]
    assert _no_timing(before) == _no_timing(json.loads(readme.split("```json", 1)[1].split("```", 1)[0]))


def test_ac11_cli_json(built):
    r = subprocess.run([sys.executable, "-m", "sportscut", "eval-crop", str(built), "--json"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert len(lines) == 1
    report = json.loads(lines[0])
    assert list(report) == ["ball_in_crop", "players_in_crop", "jitter", "seconds_per_min", "per_clip"]
    assert len(report["per_clip"]) == 4 and report["jitter"] <= 0.002


# AC12 --------------------------------------------------------------------------
def test_ac12_readme_and_specs():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    cam, crop = readme.index(CAM_HEADING), readme.index(CROP_HEADING)
    assert cam < crop and "\n## " not in readme[crop + 3:]
    section = readme[cam:readme.index("\n## ", cam + 3)]
    for s in ("Ngưỡng jitter: jitter ≤ 0.002", "Trước (T-017, center crop):", "Sau (T-019):",
              "DEAD_ZONE", "EASE", "MAX_PAN"):
        assert s in section, s
    assert "eval-crop)" not in section and "```json" not in section
    for name, needles in (("2026-11-23-t-017-add-a-measurable-9-16-reframing-design.md", ("(updated by T-019)", "center_plan")),
                          ("2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md", ("(updated by T-019)", "sample_frames")),
                          ("2026-11-24-t-042-land-the-t-017-9-16-design.md", ("Updated by T-045",)),
                          ("2026-11-25-t-044-re-land-the-reviewed-t-017-design.md", ("Updated by T-045",))):
        text = (SPECS / name).read_text(encoding="utf-8")
        assert all(n in text for n in needles), name


def test_ac12_readme_constants_match_code():
    section = (ROOT / "README.md").read_text(encoding="utf-8").split(CAM_HEADING, 1)[1].split("\n## ", 1)[0]
    for name in ("DEAD_ZONE", "EASE", "MAX_PAN"):
        assert f"`{name} = {getattr(reframe, name)}`" in section, name
    assert 0.02 <= reframe.DEAD_ZONE <= 0.08 and 0.2 <= reframe.EASE <= 0.6 and 0.1 <= reframe.MAX_PAN <= 0.3
    assert not math.isnan(reframe.EASE)
