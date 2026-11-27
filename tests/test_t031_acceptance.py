"""Tester acceptance checks for T-031 (touch candidates by any player).

Written from the acceptance criteria in .office/TASK.md, not from the Developer's tests.
"""

import importlib.util
import inspect
import json
import math
from pathlib import Path
import re
import subprocess

import numpy as np
import pytest

from sportscut import media, player, reframe
from sportscut.cli import main
from sportscut.eval_player import evaluate_dir
from sportscut.media import MediaError


ROOT = Path(__file__).resolve().parent.parent
BUILD_PATH = ROOT / "tests/fixtures/eval_player/build.py"
GRASS = (40, 140, 60)
RED = (200, 30, 30)


def _load_build():
    spec = importlib.util.spec_from_file_location("t031_acceptance_build", BUILD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load_build()


# ---------------------------------------------------------------- helpers

def _field(w: int = 320, h: int = 180) -> np.ndarray:
    frame = np.empty((h, w, 3), dtype=np.uint8)
    frame[:] = GRASS
    return frame


def _rect(frame, x, y, w, h, rgb=RED):
    frame[y:y + h, x:x + w] = rgb


def _disc(frame, cx, cy, r=2):
    yy, xx = np.ogrid[: frame.shape[0], : frame.shape[1]]
    frame[(xx - cx) ** 2 + (yy - cy) ** 2 <= r * r] = 255


def _path_turning(n, turn_at, start, v_in, v_out):
    """Hit list: constant v_in up to turn_at, then constant v_out."""
    pts = []
    x, y = start
    for i in range(n):
        pts.append((float(x), float(y)))
        vx, vy = v_in if i < turn_at else v_out
        x, y = x + vx, y + vy
    return pts


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def _own_branch() -> bool:
    return _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip().startswith("office/T-031")


def _require_own_branch():
    if not _own_branch():
        pytest.skip("git-diff scope check only runs on the office/T-031 branch")


def _merge_base() -> str:
    result = _git("merge-base", "main", "HEAD")
    if result.returncode != 0:
        pytest.skip("no local main to diff against")
    return result.stdout.strip()


def _box_gap(point, box):
    x, y = point
    bx, by, w, h = box
    return math.hypot(max(bx - x, 0, x - (bx + w)), max(by - y, 0, y - (by + h)))


def near_miss_moments(name: str = "near_miss") -> list[float]:
    """Independent of the implementation: AC8's definition, from build.py only."""
    case = build.CASES[name]
    touch_times = [t for t, _, _ in case["touches"]]
    authors = {(team, number) for _, team, number in case["touches"]}
    bystanders = [who for who in case["players"] if who not in authors]
    moments = []
    for k in range(round(case["duration"] * 5) + 1):
        t = round(k * 0.2, 4)
        if any(abs(t - tt) < 1.0 - 1e-9 for tt in touch_times):
            continue
        ball = build.ball_pos(name, t)
        for who in bystanders:
            if 6 <= _box_gap(ball, build.player_box(name, *who, t)) <= 14:
                moments.append(t)
                break
    return moments


def check_near_miss(detected_times, name: str = "near_miss") -> list[str]:
    """Return AC8 violations for a list of detected touch times."""
    labels = [t for t, _, _ in build.CASES[name]["touches"]]
    moments = near_miss_moments(name)
    problems = []
    for t in detected_times:
        if all(abs(t - lt) > 0.5 + 1e-9 for lt in labels):
            problems.append(f"false positive at {t}")
        if any(abs(t - m) <= 0.5 + 1e-9 for m in moments):
            problems.append(f"touch at {t} next to a near-miss moment")
    return problems


# ---------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def eval_set(require_ffmpeg, tmp_path_factory):
    directory = tmp_path_factory.mktemp("t031_eval_player")
    build.build_all(directory)
    return directory


@pytest.fixture(scope="module")
def detections(eval_set):
    return {name: player.detect_touches(eval_set / name / "clip.mp4") for name in build.CASES}


# ---------------------------------------------------------------- AC2 player_blobs

def test_ac2_single_red_rect_exact_bbox():
    frame = _field()
    _rect(frame, 100, 60, 8, 16)
    assert player.player_blobs(frame) == [(100, 60, 8, 16)]


def test_ac2_lone_ball_and_no_field_give_nothing():
    frame = _field()
    _disc(frame, 200, 100, 2)
    assert player.player_blobs(frame) == []
    gray = np.full((180, 320, 3), 128, dtype=np.uint8)
    _rect(gray, 100, 60, 8, 16)
    assert player.player_blobs(gray) == []


def test_ac2_sorted_by_y_then_x_and_ints():
    frame = _field()
    _rect(frame, 200, 40, 8, 16)   # top right
    _rect(frame, 50, 100, 8, 16)   # bottom left
    _rect(frame, 20, 40, 8, 16)    # top left
    blobs = player.player_blobs(frame)
    assert blobs == [(20, 40, 8, 16), (200, 40, 8, 16), (50, 100, 8, 16)]
    assert all(type(v) is int for box in blobs for v in box)


def test_ac2_bbox_is_clipped_to_frame():
    frame = _field()
    _rect(frame, 0, 0, 8, 16)            # touches the top-left corner
    _rect(frame, 312, 164, 8, 16)        # touches the bottom-right corner
    for x, y, w, h in player.player_blobs(frame):
        assert x >= 0 and y >= 0 and x + w <= 320 and y + h <= 180


def test_ac2_small_blob_below_min_area_dropped():
    frame = _field()
    _rect(frame, 100, 60, 4, 4)   # erodes to 2x2 = 4 px < BLOB_MIN_AREA
    assert player.player_blobs(frame) == []


# ---------------------------------------------------------------- AC3 find_kicks

def _assert_valid(kicks, hits):
    span = player.KICK_SPAN
    for i, s in kicks:
        assert 0 < s <= 1
        assert span <= i < len(hits) - span
        assert hits[i - span] is not None and hits[i] is not None and hits[i + span] is not None
    assert [i for i, _ in kicks] == sorted(i for i, _ in kicks)


def test_ac3_constant_velocity_no_kick():
    hits = _path_turning(15, 99, (20, 90), (4, 0), (4, 0))
    assert player.find_kicks(hits, 320) == []
    diagonal = _path_turning(15, 99, (20, 20), (3, 3), (3, 3))
    assert player.find_kicks(diagonal, 320) == []


def test_ac3_right_angle_turn_peaks_at_turn():
    hits = _path_turning(15, 7, (20, 90), (4, 0), (0, 4))
    kicks = player.find_kicks(hits, 320)
    _assert_valid(kicks, hits)
    assert max(kicks, key=lambda k: k[1])[0] == 7


def test_ac3_start_from_rest_strength_one():
    hits = [(100.0, 90.0)] * 6 + [(100.0 + 4 * k, 90.0) for k in range(1, 10)]
    kicks = player.find_kicks(hits, 320)
    _assert_valid(kicks, hits)
    assert (5, 1.0) in kicks


def test_ac3_coming_to_rest_no_kick():
    hits = [(20.0 + 4 * k, 90.0) for k in range(8)] + [(48.0, 90.0)] * 7
    kicks = player.find_kicks(hits, 320)
    assert [i for i, _ in kicks if i >= 6] == []


def test_ac3_near_miss_wobble_no_kick():
    a = math.radians(3)
    hits = _path_turning(15, 7, (20, 90), (4, 0), (4 * 1.05 * math.cos(a), 4 * 1.05 * math.sin(a)))
    assert player.find_kicks(hits, 320) == []


def test_ac3_gaps_and_short_lists():
    hits = _path_turning(15, 7, (20, 90), (4, 0), (0, 4))
    hits[7] = None
    kicks = player.find_kicks(hits, 320)
    _assert_valid(kicks, hits)
    assert 7 not in [i for i, _ in kicks]
    assert player.find_kicks([], 320) == []
    assert player.find_kicks([(1.0, 1.0)], 320) == []
    assert player.find_kicks([None] * 10, 320) == []


def test_ac3_strength_in_unit_interval_for_reversal():
    hits = _path_turning(15, 7, (100, 90), (6, 0), (-6, 0))
    kicks = player.find_kicks(hits, 320)
    _assert_valid(kicks, hits)
    assert kicks


# ---------------------------------------------------------------- AC4 suppress_touches

def _t(t, c):
    return player.Touch(t, None, None, c, None)


def test_ac4_nms_examples():
    got = player.suppress_touches([_t(1.0, .6), _t(1.2, .9), _t(1.4, .5), _t(1.6, .9), _t(2.0, .7)])
    assert [x.t for x in got] == [1.2, 2.0]
    assert [x.t for x in player.suppress_touches([_t(1.0, .9), _t(1.4, .5)])] == [1.0]
    assert [x.t for x in player.suppress_touches([_t(1.6, .2), _t(1.0, .9)])] == [1.0, 1.6]
    assert [x.t for x in player.suppress_touches([_t(1.2, .5), _t(1.0, .5)])] == [1.0]
    assert player.suppress_touches([]) == []


def test_ac4_result_sorted_by_t():
    got = player.suppress_touches([_t(5.0, .9), _t(1.0, .3), _t(3.0, .6)])
    assert [x.t for x in got] == [1.0, 3.0, 5.0]


# ---------------------------------------------------------------- AC5 detect_touches (unit)

def _scene(w, h, ball_path, player_box, n):
    frames = np.empty((n, h, w, 3), dtype=np.uint8)
    for i in range(n):
        frame = _field(w, h)
        _rect(frame, *player_box)
        bx, by = ball_path[i]
        _disc(frame, round(bx), round(by), 2)
        frames[i] = frame
    return frames


def _patch_media(monkeypatch, size, frames, calls):
    monkeypatch.setattr(media, "probe_size", lambda video: size)

    def fake_sample(video, fps, width, height):
        calls.append((str(video), fps, width, height))
        return frames
    monkeypatch.setattr(media, "sample_frames", fake_sample)


def test_ac5_turn_next_to_player_gives_one_scaled_touch(monkeypatch):
    # Player 8x16 at (150, 60) -> bottom at y=76; ball turns 90 deg 4 px below at sample 7.
    path = _path_turning(15, 7, (154 - 7 * 6, 82), (6, 0), (0, 6))
    frames = _scene(320, 180, path, (150, 60, 8, 16), 15)
    calls = []
    _patch_media(monkeypatch, (640, 360), frames, calls)
    touches = player.detect_touches("clip.mp4")
    assert calls == [("clip.mp4", reframe.SAMPLE_HZ, 320, 180)]
    assert len(touches) == 1
    touch = touches[0]
    assert touch.t == 1.4 and touch.team is None and touch.number is None
    assert 0 < touch.confidence <= 1
    blob = player.player_blobs(frames[7])
    assert len(blob) == 1
    assert touch.bbox == tuple(2 * v for v in blob[0])
    assert all(type(v) is int for v in touch.bbox)


def test_ac5_turn_far_from_any_player_is_not_a_touch(monkeypatch):
    path = _path_turning(15, 7, (154 - 7 * 6, 140), (6, 0), (0, -5))
    frames = _scene(320, 180, path, (150, 20, 8, 16), 15)   # player ~100 px away
    _patch_media(monkeypatch, (640, 360), frames, [])
    assert player.detect_touches("clip.mp4") == []


def test_ac5_narrow_video_not_upscaled(monkeypatch):
    path = _path_turning(15, 7, (74 - 7 * 4, 52), (4, 0), (0, 4))
    frames = _scene(160, 90, path, (70, 30, 8, 16), 15)
    calls = []
    _patch_media(monkeypatch, (160, 90), frames, calls)
    touches = player.detect_touches("narrow.mp4")
    assert calls == [("narrow.mp4", reframe.SAMPLE_HZ, 160, 90)]
    assert len(touches) == 1
    assert touches[0].bbox == player.player_blobs(frames[7])[0]


@pytest.mark.parametrize("n", [0, 1, 2])
def test_ac5_too_few_frames_gives_empty(monkeypatch, n):
    frames = np.zeros((n, 180, 320, 3), dtype=np.uint8)
    frames[:] = GRASS
    _patch_media(monkeypatch, (640, 360), frames, [])
    assert player.detect_touches("short.mp4") == []


def test_ac5_coasted_tracker_positions_are_not_hits(monkeypatch):
    """Review focus 1: a held (coasted) tracker position must not fake a stop and a kick.

    The ball rolls at constant velocity just under a player; the detector misses it at
    samples 6 and 7, so the real tracker holds sample 5's position there. If held positions
    were used as hits, samples 5-6-7 would look like a ball at rest that starts moving at 7.
    """
    n = 15
    path = [(100.0 + 6 * i, 82.0) for i in range(n)]
    frames = _scene(320, 180, path, (126, 60, 8, 16), n)
    _patch_media(monkeypatch, (640, 360), frames, [])

    def run(missing):
        counter = {"i": -1}

        def fake_candidates(frame):
            counter["i"] += 1
            i = counter["i"]
            return [] if i in missing else [(path[i][0], path[i][1], 1.0)]
        monkeypatch.setattr(reframe, "ball_candidates", fake_candidates)
        return player.detect_touches("clip.mp4")

    track = reframe.track_ball([[] if i in (6, 7) else [(x, y, 1.0)] for i, (x, y) in enumerate(path)],
                               reframe.BALL_GATE * 320, reframe.BALL_LOST)
    assert track[6] == track[7] == path[5]      # the tracker really coasts here
    assert run(set()) == []
    assert run({6, 7}) == []


def test_ac5_grep_player_has_no_own_reader_or_detector():
    text = (ROOT / "sportscut/player.py").read_text()
    pattern = re.compile(r"subprocess|ffmpeg|green_mask|cumsum|def (sample_frames|field_mask|ball_candidates|track_ball)")
    assert [line for line in text.splitlines() if pattern.search(line)] == []


# ---------------------------------------------------------------- AC5/AC6 on real media

def test_ac5_real_set_touch_shape(detections):
    for name, touches in detections.items():
        assert touches, name
        assert [t.t for t in touches] == sorted(t.t for t in touches)
        for touch in touches:
            assert isinstance(touch, player.Touch)
            assert touch.team is None and touch.number is None
            assert 0 < touch.confidence <= 1
            assert abs(touch.t * 5 - round(touch.t * 5)) < 1e-6
            assert touch.t == round(touch.t, 4)
            assert len(touch.bbox) == 4 and all(type(v) is int for v in touch.bbox)
            x, y, w, h = touch.bbox
            assert 0 <= x and 0 <= y and x + w <= build.W + 2 and y + h <= build.H + 2
        for a, b in zip(touches, touches[1:]):
            assert b.t - a.t > player.TOUCH_NMS


def test_ac6_closeup_without_field_gives_nothing(synthetic_video, tmp_path):
    assert player.detect_touches(synthetic_video) == []
    gray = tmp_path / "gray.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
         "color=c=gray:s=640x360:r=25:d=3", "-c:v", "mpeg4", "-pix_fmt", "yuv420p", str(gray)],
        check=True, capture_output=True,
    )
    assert player.detect_touches(gray) == []


def test_ac6_missing_file_raises_media_error(tmp_path):
    with pytest.raises(MediaError):
        player.detect_touches("missing-x.mp4")
    with pytest.raises(MediaError):
        player.detect_touches(tmp_path / "nope.mp4")


# ---------------------------------------------------------------- AC7 eval gate

def test_ac7_eval_player_cli_gate(eval_set, capsys):
    assert main(["eval-player", str(eval_set), "--json"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    report = json.loads(out)
    assert report["touch_f1_any"] >= 0.9
    assert report["f1"] == report["precision"] == report["recall"] == 0.0
    assert 0 < report["seconds_per_min"] <= 6.0
    assert report["seconds_per_min"] * 90 <= 540


# ---------------------------------------------------------------- AC8 near miss

def test_ac8_near_miss_moments_exist_in_fixture():
    moments = near_miss_moments()
    assert moments, "fixture must have near-miss moments"
    # The spec names them around 4.4 s and 9.6 s.
    assert any(abs(m - 4.4) <= 0.6 for m in moments)
    assert any(abs(m - 9.6) <= 0.6 for m in moments)


def test_ac8_near_miss_not_counted(detections):
    assert check_near_miss([t.t for t in detections["near_miss"]]) == []


def test_ac8_checker_can_fail():
    """A detector that fires at every near-miss moment must be caught by the AC8 check."""
    moments = near_miss_moments()
    assert check_near_miss(moments)
    labels = [t for t, _, _ in build.CASES["near_miss"]["touches"]]
    assert check_near_miss(labels) == []


def test_ac8_checker_fails_on_patched_detector(eval_set, monkeypatch):
    fake = [player.Touch(m, None, None, 0.9, (0, 0, 1, 1)) for m in near_miss_moments()]
    monkeypatch.setattr(player, "detect_touches", lambda video: list(fake))
    got = player.detect_touches(eval_set / "near_miss" / "clip.mp4")
    assert check_near_miss([t.t for t in got]) != []


# ---------------------------------------------------------------- AC9 --debug

def test_ac9_debug_candidates_match_detect_touches(eval_set, detections, capsys):
    assert main(["eval-player", str(eval_set), "--json", "--debug"]) == 0
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    report = json.loads(out)
    plain = evaluate_dir(eval_set)
    assert set(report) == set(plain)
    for entry in report["per_clip"]:
        assert list(entry)[-1] == "candidates"
        assert entry["candidates"] == [t.to_dict() for t in detections[entry["clip"]]]
    for entry in plain["per_clip"]:
        assert "candidates" not in entry


def test_ac9_without_debug_no_candidates_and_same_keys(eval_set, capsys):
    assert main(["eval-player", str(eval_set), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert set(report) == {"f1", "precision", "recall", "touch_f1_any", "team_accuracy",
                           "id_accuracy", "seconds_per_min", "per_clip"}
    assert all("candidates" not in entry for entry in report["per_clip"])


# ---------------------------------------------------------------- AC10 find_touches

def test_ac10_find_touches_empty_for_every_query(eval_set, monkeypatch, detections):
    # Reuse the real detections (same function find_touches calls) to keep this fast,
    # and also check one real end-to-end find_touches call.
    from sportscut.eval_player import load_labels
    first = True
    for name in build.CASES:
        clip = eval_set / name / "clip.mp4"
        _, queries = load_labels(eval_set / name / "labels.json")
        assert queries
        if first:
            assert player.find_touches(clip, queries[0]) == []
            first = False
        with monkeypatch.context() as m:
            m.setattr(player, "detect_touches", lambda video, n=name: detections[n])
            for query in queries:
                assert player.find_touches(clip, query) == []


def test_ac10_find_touches_and_models_unchanged():
    _require_own_branch()
    base = _merge_base()
    old = _git("show", f"{base}:sportscut/player.py").stdout
    new = (ROOT / "sportscut/player.py").read_text()

    def block(src, start):
        lines = src.splitlines()
        i = next(k for k, line in enumerate(lines) if line.startswith(start))
        out = [lines[i]]
        for line in lines[i + 1:]:
            if line and not line[0].isspace():
                break
            out.append(line)
        return "\n".join(out).rstrip()
    for start in ("def find_touches", "class PlayerQuery", "class Touch", "def normalize_team"):
        assert block(new, start) == block(old, start), start
    assert inspect.signature(player.find_touches).parameters.keys() == {"video", "query"}


# ---------------------------------------------------------------- AC11 / AC12 / AC14 scope

PROTECTED = ["sportscut/reframe.py", "sportscut/media.py", "tests/conftest.py",
             "tests/fixtures/eval_player", "pyproject.toml"]


def test_ac12_protected_paths_untouched_and_no_mp4():
    assert _git("ls-files", "*.mp4").stdout == ""
    _require_own_branch()
    base = _merge_base()
    assert _git("diff", "--stat", base, "--", *PROTECTED).stdout == ""
    assert _git("status", "--porcelain", "--", *PROTECTED).stdout == ""


def test_ac11_only_allowed_edits_to_existing_tests():
    _require_own_branch()
    base = _merge_base()
    changed = set(_git("diff", "--name-only", "--diff-filter=MDR", base, "--", "tests").stdout.split())
    allowed = {"tests/test_player.py", "tests/test_eval_player_fixtures.py",
               "tests/test_t042_round2_acceptance.py", "tests/test_t042_tester_acceptance.py"}
    assert changed <= allowed
    diff = _git("diff", "-U0", base, "--", "tests/test_player.py").stdout
    removed = [l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
    assert any('detect_touches("x.mp4") == []' in l or "detect_touches('x.mp4') == []" in l for l in removed)
    diff = _git("diff", "-U0", base, "--", "tests/test_eval_player_fixtures.py").stdout
    removed = [l for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")]
    assert len(removed) == 2


def test_ac14_diff_size_under_600():
    _require_own_branch()
    base = _merge_base()
    total = 0
    for line in _git("diff", "--numstat", base, "--", ".", ":!docs/superpowers").stdout.splitlines():
        added, deleted, _ = line.split("\t", 2)
        if added != "-":
            total += int(added) + int(deleted)
    untracked = _git("ls-files", "--others", "--exclude-standard", "--", "sportscut", "tests", "README.md").stdout.split()
    for path in untracked:
        if path.endswith(".py") or path.endswith(".md"):
            total += len((ROOT / path).read_text().splitlines())
    assert total < 600, total


# ---------------------------------------------------------------- AC13 docs

def test_ac13_readme_section_and_report():
    text = (ROOT / "README.md").read_text()
    heads = [line for line in text.splitlines() if line.startswith("## ")]
    i = heads.index("## Phát hiện chạm bóng (T-031)")
    assert heads[i + 1] == "## Highlight theo sự kiện: đo độ chính xác (eval)"
    section = text.split("## Phát hiện chạm bóng (T-031)", 1)[1].split("\n## ", 1)[0]
    assert "python -m sportscut eval-player tests/fixtures/eval_player --json --debug" in section
    blocks = re.findall(r"```text\n(.*?)```", section, re.S)
    assert blocks
    for name in ("KICK_SPAN", "TURN_DEG", "SPEED_JUMP", "MIN_SPEED", "REACH", "BLOB_MIN_AREA", "TOUCH_NMS"):
        m = re.search(rf"^{name}\s*=\s*([0-9.]+)", blocks[0], re.M)
        assert m, name
        assert float(m.group(1)) == float(getattr(player, name)), name
    after = section.split("Kết quả đo trong T-031:", 1)[1]
    js = re.search(r"```json\n(.*?)\n```", after, re.S).group(1)
    assert "\n" not in js.strip()
    report = json.loads(js)
    assert report["touch_f1_any"] >= 0.9
    assert report["f1"] == report["precision"] == report["recall"] == 0.0
    assert report["seconds_per_min"] <= 6.0


def test_ac13_readme_insert_only_and_t029_bullet():
    spec = (ROOT / "docs/superpowers/specs/2026-11-23-t-029-build-the-player-touch-eval-synthetic-design.md").read_text()
    assert ("- T-031 (2026-11-27): detect_touches now returns touch candidates by any player "
            "(team/number None); find_touches still returns [] until T-032/T-033. "
            "The T-029 README baseline is kept as history.") in spec
    _require_own_branch()
    base = _merge_base()
    numstat = _git("diff", "--numstat", base, "--", "README.md").stdout.split()
    assert numstat and numstat[1] == "0"
