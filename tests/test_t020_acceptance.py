"""T-020 Tester acceptance tests, written from the T-020 acceptance criteria (not the Developer's tests)."""

from __future__ import annotations

import importlib.util
import inspect
import json
import math
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from sportscut import eval_crop, reframe

ROOT = Path(__file__).resolve().parents[1]
BALL_HEADING = "## Camera bám bóng (T-020)"
CAM_HEADING = "## Camera ảo bám cầu thủ (T-019)"
CROP_HEADING = "## Video dọc 9:16: đo khung cắt (eval-crop)"
FIELD, RED, GREY, WHITE = (40, 140, 60), (200, 30, 30), (128, 128, 128), (255, 255, 255)
T045_SPEC = ROOT / "docs/superpowers/specs/2026-11-25-t-045-follow-the-players-with-a-smoothed-design.md"


def _cap() -> float:
    return reframe.BALL_MAX_PAN * 640 / 5 + 1e-6


def _frame(fill=FIELD, h=180, w=320):
    return np.full((h, w, 3), fill, np.uint8)


def _clip(path: Path, frames: np.ndarray) -> Path:
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "640x360",
           "-r", "25", "-i", "pipe:0", "-an", "-c:v", "mpeg4", "-q:v", "2", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, input=frames.tobytes(), check=True)
    return path


def _field(n):
    return np.full((n, 360, 640, 3), FIELD, np.uint8)


def _two_red_players(f):
    f[:, 150:182, 96:112] = RED
    f[:, 150:182, 128:144] = RED
    return f


_YY, _XX = np.mgrid[0:360, 0:640]


def _disk(frame, cx, cy, r=4):
    frame[(_XX - cx) ** 2 + (_YY - cy) ** 2 <= r * r] = WHITE


def _steps_ok(plan):
    xs = [x for _, x in plan]
    return all(abs(b - a) <= _cap() for a, b in zip(xs, xs[1:]))


def _close(got, expected, tol=1e-9):
    return len(got) == len(expected) and all(
        all(abs(a - b) <= tol for a, b in zip(g, e)) for g, e in zip(got, expected))


# AC1 ---------------------------------------------------------------------------
def test_ac1_scope():
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    if not branch.startswith("office/T-020"):
        pytest.skip("T-020 scope check runs only on office/T-020 branches")
    mb = subprocess.run(["git", "merge-base", "main", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    if mb.returncode:
        pytest.skip("main unavailable")
    base = mb.stdout.strip()
    names = subprocess.run(["git", "diff", "--name-only", base], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout.split()
    allowed = {"sportscut/reframe.py", "tests/test_reframe.py", "tests/test_t020_acceptance.py", "README.md"}
    for name in names:
        assert name in allowed or name.startswith("docs/superpowers/"), name
        assert not name.endswith(".mp4"), name
    numstat = subprocess.run(["git", "diff", "--numstat", base], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    for line in numstat.splitlines():
        added, deleted, path = line.split("\t")
        if path in ("tests/test_reframe.py", "README.md"):
            assert deleted == "0", f"{path} deletes {deleted} lines"
    assert subprocess.run(["git", "ls-files", "*.mp4"], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip() == ""
    src = (ROOT / "sportscut/reframe.py").read_text(encoding="utf-8")
    assert "import subprocess" not in src and "cv2" not in src


# AC2 ---------------------------------------------------------------------------
def test_ac2_field_mask_region_and_none():
    f = _frame()
    f[0:30] = GREY
    f[:, 0:20] = GREY
    expected = np.zeros((180, 320), bool)
    expected[30:180, 20:320] = True
    got = reframe.field_mask(f)
    assert got is not None and got.dtype == bool and got.shape == (180, 320)
    assert np.array_equal(got, expected)
    assert reframe.field_mask(_frame(GREY)) is None
    f20 = _frame(GREY)
    f20[:, 0:64] = FIELD  # exactly 20% green
    assert reframe.field_mask(f20) is None


def test_ac2_player_mask_unchanged_by_refactor():
    f = _frame()
    f[40:56, 100:108] = RED
    f[:, 159:161] = WHITE
    f[0:30] = GREY
    f[:, 0:20] = GREY
    expected = np.zeros((180, 320), bool)
    expected[41:55, 101:107] = True
    assert np.array_equal(reframe.player_mask(f), expected)


# AC3 ---------------------------------------------------------------------------
def test_ac3a_single_3x3():
    f = _frame()
    f[88:91, 98:101] = WHITE
    assert _close(reframe.ball_candidates(f), [(99.5, 89.5, 1.0)])


def test_ac3b_two_blobs_in_order():
    f = _frame()
    f[88:91, 98:101] = WHITE
    f[120:123, 250:253] = WHITE
    assert _close(reframe.ball_candidates(f), [(99.5, 89.5, 1.0), (251.5, 121.5, 1.0)])


def test_ac3c_lone_4x4_one_candidate():
    f = _frame()
    f[60:64, 200:204] = WHITE
    got = reframe.ball_candidates(f)
    assert _close(got, [(202.0, 62.0, 0.64)])
    assert all(isinstance(v, float) for v in got[0])


def _line(f):
    f[:, 159:161] = WHITE


def _white_7x15(f):
    f[80:87, 100:115] = WHITE


def _white_8x8(f):
    f[80:88, 100:108] = WHITE


def _red_3x3(f):
    f[88:91, 98:101] = RED


def _grey_3x3(f):
    f[88:91, 98:101] = GREY


def _outside_field(f):
    f[0:30] = GREY
    f[10:13, 150:153] = WHITE


def _all_grey(f):
    f[:] = GREY


@pytest.mark.parametrize("paint", [_line, _white_7x15, _white_8x8, _red_3x3, _grey_3x3, _outside_field, _all_grey])
def test_ac3d_e_rejects(paint):
    f = _frame()
    paint(f)
    assert reframe.ball_candidates(f) == []


def test_ac3_mutation_dropping_ring_accepts_line(monkeypatch):
    """Mutation (3): without the empty-ring test the 2-px line becomes a candidate, so AC3(d) can fail."""
    monkeypatch.setattr(reframe, "BALL_RING", 0)
    f = _frame()
    _line(f)
    assert reframe.ball_candidates(f) != []


# AC4 ---------------------------------------------------------------------------
AC4_CASES = [
    ([[(10, 10, 1)], [(20, 10, 1)], [(30, 10, 1)]], dict(gate=15), [(10, 10), (20, 10), (30, 10)]),
    ([[(0, 0, 1)], [(40, 0, 1)], [(80, 0, 1)], [(90, 0, 1), (120, 0, 1)]], dict(gate=50),
     [(0, 0), (40, 0), (80, 0), (120, 0)]),
    ([[(100, 100, 1)], [(100, 100, 1)], [(300, 100, 1)]], dict(gate=50), [(100, 100), (100, 100), (100, 100)]),
    ([[(5, 5, 1)], [], [], [], [(300, 40, 1)]], dict(gate=50, lost_after=3),
     [(5, 5), (5, 5), (5, 5), None, (300, 40)]),
    ([[(0, 0, 1)], [(10, 0, 1)], [], [(30, 0, 1)]], dict(gate=12), [(0, 0), (10, 0), (10, 0), (30, 0)]),
    ([[(10, 0, 0.5), (200, 0, 0.9)]], dict(gate=50), [(200, 0)]),
    ([], dict(gate=50), []),
]


def _as_tuples(out):
    return [None if p is None else tuple(float(v) for v in p) for p in out]


def _check_ac4(fn, samples, kwargs, expected):
    got = _as_tuples(fn(samples, **kwargs))
    exp = [None if e is None else tuple(float(v) for v in e) for e in expected]
    assert got == exp


@pytest.mark.parametrize("samples,kwargs,expected", AC4_CASES)
def test_ac4_track_ball_exact(samples, kwargs, expected):
    _check_ac4(reframe.track_ball, samples, kwargs, expected)


def test_ac4_default_lost_after_is_ball_lost():
    sig = inspect.signature(reframe.track_ball)
    assert sig.parameters["lost_after"].default == reframe.BALL_LOST


def test_ac4_mutation_no_velocity_fails_constant_velocity_case():
    """Mutation (1): a tracker that ignores velocity (pred = pos) must fail AC4 case 2."""
    src = textwrap.dedent(inspect.getsource(reframe.track_ball))
    old = "pred = (pos[0] + vel[0] * n, pos[1] + vel[1] * n)"
    if old not in src:
        pytest.skip("prediction line not found; mutation verified manually in TEST_REPORT")
    ns = dict(vars(reframe))
    exec(src.replace(old, "pred = pos"), ns)
    mutant = ns["track_ball"]
    samples, kwargs, expected = AC4_CASES[1]
    with pytest.raises(AssertionError):
        _check_ac4(mutant, samples, kwargs, expected)


# AC5 ---------------------------------------------------------------------------
def test_ac5_blend_weights():
    got = reframe.blend_weights([None, "b", "b", "b", "b", "b", None, None], 0.25)
    assert len(got) == 8 and all(abs(a - b) < 1e-12 for a, b in
                                 zip(got, [0.0, 0.25, 0.5, 0.75, 1.0, 1.0, 0.75, 0.5]))
    assert reframe.blend_weights(["b", None], 0.25) == [1.0, 0.75]
    assert reframe.blend_weights([], 0.25) == []
    assert all(0.0 <= v <= 1.0 for v in reframe.blend_weights(["b"] * 30 + [None] * 30, 0.3))


# AC6 ---------------------------------------------------------------------------
def _three_reds():
    f = _frame()
    f[40:56, 100:108] = RED
    f[40:56, 116:124] = RED
    f[100:116, 250:258] = RED
    return f


def test_ac6_framed_x():
    f = _three_reds()
    assert abs(reframe.framed_x(f, 101, 60.0, 40.0) - 100.0) < 1e-9
    assert abs(reframe.framed_x(f, 101, 240.0, 60.0) - 254.0) < 1e-9
    assert abs(reframe.framed_x(_frame(), 101, 150.0, 60.0) - 150.0) < 1e-9
    assert abs(reframe.framed_x(_frame(GREY), 101, 150.0, 60.0) - 150.0) < 1e-9


# AC7 ---------------------------------------------------------------------------
def test_ac7_per_sample_gains_exact():
    a = reframe.smooth_path([101.0, 539.0, 539.0], 640, 202, dead_zone=[0, 0, 0], ease=[1, 1, 0.5],
                            max_pan=[0.1, 0.5, 0.5])
    assert len(a) == 3 and all(abs(x - y) < 1e-9 for x, y in zip(a, [101, 165, 229]))
    b = reframe.smooth_path([101.0, 539.0, 539.0], 640, 202, dead_zone=[0, 0, 0], ease=[1, 1, 0.5],
                            max_pan=[0.5, 0.1, 0.5])
    assert len(b) == 3 and all(abs(x - y) < 1e-9 for x, y in zip(b, [101, 113.8, 177.8]))


@pytest.mark.parametrize("bad", ["dead_zone", "ease", "max_pan"])
@pytest.mark.parametrize("length", [2, 4])
def test_ac7_length_mismatch_raises(bad, length):
    kw = dict(dead_zone=0.03, ease=0.5, max_pan=0.2)
    kw[bad] = [kw[bad]] * length
    with pytest.raises(ValueError):
        reframe.smooth_path([101.0, 300.0, 539.0], 640, 202, **kw)


def test_ac7_sequences_equal_scalars_on_random_targets():
    rng = np.random.default_rng(0)
    vals, holes = rng.uniform(0, 640, 200), rng.random(200) < 0.2
    targets = [None if h else float(v) for v, h in zip(vals, holes)]
    scalar = reframe.smooth_path(targets, 640, 202, dead_zone=0.03, ease=0.5, max_pan=0.2)
    seq = reframe.smooth_path(targets, 640, 202, dead_zone=[0.03] * 200, ease=[0.5] * 200, max_pan=[0.2] * 200)
    assert scalar == seq
    assert reframe.smooth_path([200.0, 230.0, 260.0], 640, 202, 0.03, 0.5, 0.2) == pytest.approx(
        [200.0, 205.4, 223.1], abs=1e-9)


# AC8 ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ac8_clip(tmp_path_factory, require_ffmpeg):
    f = _two_red_players(_field(100))
    f[:, :, 319:321] = WHITE
    return _clip(tmp_path_factory.mktemp("t020_ac8") / "line.mp4", f)


def test_ac8_no_ball_is_t045_plan(ac8_clip, monkeypatch, synthetic_video):
    plan = reframe.plan_crop(ac8_clip)
    assert plan == reframe.plan_crop(ac8_clip)
    assert [t for t, _ in plan] == reframe.sample_times(4.0)
    assert reframe.plan_crop(synthetic_video) == [(t, 80.0) for t in reframe.sample_times(6.0)]
    monkeypatch.setattr(reframe, "ball_candidates", lambda frame: [])
    assert plan == reframe.plan_crop(ac8_clip)


# AC9 ---------------------------------------------------------------------------
def test_ac9_follows_moving_ball(tmp_path, require_ffmpeg):
    f = _field(100)
    f[:, 60:90, 40:54] = RED
    for j in range(100):
        _disk(f[j], round(120 + 100 * j / 25), 180)
    plan = reframe.plan_crop(_clip(tmp_path / "move.mp4", f))
    assert [t for t, _ in plan] == reframe.sample_times(4.0)
    for t, x in plan:
        assert abs(x - (120 + 100 * t)) <= 101, (t, x)
    assert _steps_ok(plan)


# AC10 --------------------------------------------------------------------------
def _pass_x(t):
    if t < 2.0:
        return 100.0
    if t >= 3.2:
        return 540.0
    return 100.0 + (t - 2.0) / 1.2 * 440.0


def test_ac10_pass_catches_up(tmp_path, require_ffmpeg):
    f = _field(150)
    for j in range(150):
        _disk(f[j], round(_pass_x(j / 25)), 180)
    plan = reframe.plan_crop(_clip(tmp_path / "pass.mp4", f))
    assert [t for t, _ in plan] == reframe.sample_times(6.0)
    for t, x in plan:
        if t <= 2.0 or t >= 5.0:
            assert abs(x - _pass_x(t)) <= 101, (t, x)
    assert _steps_ok(plan)


# AC11 --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ac11_clip(tmp_path_factory, require_ffmpeg):
    f = _two_red_players(_field(150))
    for j in range(50):  # t < 2.0
        _disk(f[j], 500, 180)
    return _clip(tmp_path_factory.mktemp("t020_ac11") / "lost.mp4", f)


def _check_ac11(plan):
    d = dict(plan)
    for t, x in plan:
        if t <= 1.8:
            assert abs(x - 500) <= 101, (t, x)
    later = [x for t, x in plan if t >= 2.0]
    assert all(b <= a for a, b in zip(later, later[1:])), later
    assert d[5.8] < d[2.0]
    assert _steps_ok(plan)


def test_ac11_fallback_without_jump(ac11_clip):
    plan = reframe.plan_crop(ac11_clip)
    assert [t for t, _ in plan] == reframe.sample_times(6.0)
    _check_ac11(plan)


def _spy_targets(monkeypatch, clip):
    seen = []
    real_smooth = reframe.smooth_path

    def spy(targets, *a, **k):
        seen.append(list(targets))
        return real_smooth(targets, *a, **k)

    monkeypatch.setattr(reframe, "smooth_path", spy)
    reframe.plan_crop(clip)
    return seen[-1]


def _check_crossfade(targets):
    # Static scene: the ball-to-player switch is a target cross-fade, so the target may move at
    # most BLEND_STEP * width per sample (never an instant jump from the ball to the players).
    pairs = [(a, b) for a, b in zip(targets, targets[1:]) if a is not None and b is not None]
    assert pairs and all(abs(b - a) <= reframe.BLEND_STEP * 640 + 1e-6 for a, b in pairs), targets
    assert targets[0] is not None and abs(targets[0] - 500) <= 101
    assert targets[-1] is not None and targets[-1] < 300  # ended on the players (cols 96:144)


def test_ac11_target_crossfades_to_players(ac11_clip, monkeypatch):
    _check_crossfade(_spy_targets(monkeypatch, ac11_clip))


def test_ac11_mutation_hard_switch_is_caught(ac11_clip, monkeypatch):
    """Mutation (2): hard 0/1 blend weights. The plan step cap cannot see it (the smoother caps
    every step), but the target cross-fade check must fail."""
    monkeypatch.setattr(reframe, "blend_weights",
                        lambda ball, step=0.1: [1.0 if b is not None else 0.0 for b in ball])
    targets = _spy_targets(monkeypatch, ac11_clip)
    with pytest.raises(AssertionError):
        _check_crossfade(targets)


# AC12 / AC13 -------------------------------------------------------------------
@pytest.fixture(scope="module")
def built(tmp_path_factory, require_ffmpeg):
    spec = importlib.util.spec_from_file_location("t020_build", ROOT / "tests/fixtures/eval_crop/build.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path_factory.mktemp("t020_eval_crop")
    mod.build_all(out)
    return out


@pytest.fixture(scope="module")
def after(built):
    return eval_crop.evaluate_dir(built)


def _gate(after, before):
    per = {c["clip"]: c for c in after["per_clip"]}
    assert after["ball_in_crop"] >= 0.95, after["ball_in_crop"]
    assert per["occluded"]["ball_in_crop"] >= 0.9
    assert per["white_distractor"]["ball_in_crop"] >= 0.9
    assert after["ball_in_crop"] > before["ball_in_crop"]
    assert after["players_in_crop"] >= before["players_in_crop"] - 0.03
    assert after["jitter"] <= 0.002
    assert after["seconds_per_min"] <= 6.0


def test_ac12_eval_gate(built, after, monkeypatch):
    monkeypatch.setattr(reframe, "ball_candidates", lambda frame: [])
    before = eval_crop.evaluate_dir(built)
    assert abs(before["players_in_crop"] - 0.5988) < 1e-4  # T-045 camera reference
    assert abs(before["ball_in_crop"] - 0.5812) < 1e-4
    _gate(after, before)


def test_ac12_mutation_center_plan_fails_gate(built, after, monkeypatch):
    """Mutation (4): plan_crop replaced by center_plan must fail the AC12 gate."""
    monkeypatch.setattr(reframe, "plan_crop", reframe.center_plan)
    centre = eval_crop.evaluate_dir(built)
    with pytest.raises(AssertionError):
        _gate(centre, after)


def test_ac13_cli_json(built):
    r = subprocess.run([sys.executable, "-m", "sportscut", "eval-crop", str(built), "--json"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.strip().splitlines()
    assert len(lines) == 1
    report = json.loads(lines[0])
    assert list(report) == ["ball_in_crop", "players_in_crop", "jitter", "seconds_per_min", "per_clip"]
    assert len(report["per_clip"]) == 4
    assert report["ball_in_crop"] >= 0.95 and report["jitter"] <= 0.002


# AC15 --------------------------------------------------------------------------
RANGES = {
    "BALL_LEVEL": (140, 200), "BALL_FILL": (0.3, 0.6), "BALL_GATE": (0.2, 0.4), "BALL_LOST": (3, 10),
    "BLEND_STEP": (0.1, 0.5), "BALL_EDGE": (0.05, 0.3), "BALL_DEAD_ZONE": (0.01, 0.06),
    "BALL_EASE": (0.3, 0.8), "BALL_MAX_PAN": (0.2, 0.6),
}


def _readme():
    return (ROOT / "README.md").read_text(encoding="utf-8")


def test_ac15_readme_section_position_and_content():
    readme = _readme()
    cam, ball, crop = readme.index(CAM_HEADING), readme.index(BALL_HEADING), readme.index(CROP_HEADING)
    assert cam < ball < crop
    section = readme[ball:crop]
    assert section.count("\n## ") == 0  # immediately before the eval-crop section
    assert "Trước (T-045, chỉ cầu thủ):" in section and "Sau (T-020):" in section
    assert "```json" not in section and "eval-crop)" not in section
    for name, (lo, hi) in RANGES.items():
        value = getattr(reframe, name)
        assert f"`{name} = {value}`" in section, name
        assert lo <= value <= hi, (name, value)
    assert (reframe.DEAD_ZONE, reframe.EASE, reframe.MAX_PAN) == (0.06, 0.2, 0.1)
    assert reframe.BALL_BOXES == (3, 5) and reframe.BALL_RING == 2 and reframe.BALL_NMS == 3.0


def test_ac15_eval_crop_section_last_and_unchanged_vs_main():
    readme = _readme()
    crop = readme.index(CROP_HEADING)
    assert "\n## " not in readme[crop + 3:]
    if shutil.which("git") is None:
        pytest.skip("git unavailable")
    r = subprocess.run(["git", "show", "main:README.md"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode:
        pytest.skip("main unavailable")
    main = r.stdout
    assert readme[crop:] == main[main.index(CROP_HEADING):]


def test_ac15_t045_spec_note():
    assert "Updated by T-020" in T045_SPEC.read_text(encoding="utf-8")


# AC16 --------------------------------------------------------------------------
def test_ac16_eval_f1_unchanged(require_ffmpeg):
    r = subprocess.run([sys.executable, "-m", "sportscut", "eval", "tests/fixtures/eval", "--json"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout.strip().splitlines()[-1])["f1"] == 0.8421
