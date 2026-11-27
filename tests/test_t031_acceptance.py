"""Tester acceptance checks for T-031, written from the ACs in .office/TASK.md."""
import importlib.util, json, math, re, subprocess
from pathlib import Path

import numpy as np
import pytest

from sportscut import media, player, reframe
from sportscut.cli import main
from sportscut.eval_player import evaluate_dir, load_labels
from sportscut.media import MediaError

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("t031_build", ROOT / "tests/fixtures/eval_player/build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)
T = player.Touch

def _field(w=320, h=180):
    f = np.empty((h, w, 3), np.uint8); f[:] = (40, 140, 60); return f
def _rect(f, x, y, w, h): f[y:y + h, x:x + w] = (200, 30, 30)
def _disc(f, cx, cy, r=2):
    yy, xx = np.ogrid[: f.shape[0], : f.shape[1]]; f[(xx - cx) ** 2 + (yy - cy) ** 2 <= r * r] = 255
def _path(n, at, start, v_in, v_out):
    pts, (x, y) = [], start
    for i in range(n):
        pts.append((float(x), float(y))); vx, vy = v_in if i < at else v_out; x, y = x + vx, y + vy
    return pts
def _git(*a): return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout
def _own_base():  # Tech Lead round 2: git-diff scope checks run only on the T-031 branch
    if not _git("rev-parse", "--abbrev-ref", "HEAD").strip().startswith("office/T-031"):
        pytest.skip("scope check only runs on office/T-031*")
    return _git("merge-base", "main", "HEAD").strip() or pytest.skip("no main")
def _gap(p, b): return math.hypot(max(b[0] - p[0], 0, p[0] - b[0] - b[2]), max(b[1] - p[1], 0, p[1] - b[1] - b[3]))
def near_miss_moments(name="near_miss"):  # AC8 definition, from build.py only
    case = build.CASES[name]; times = [t for t, _, _ in case["touches"]]
    authors = {(team, n) for _, team, n in case["touches"]}
    out = []
    for k in range(round(case["duration"] * 5) + 1):
        t = round(k * 0.2, 4)
        if all(abs(t - tt) >= 1.0 - 1e-9 for tt in times) and any(
                6 <= _gap(build.ball_pos(name, t), build.player_box(name, *who, t)) <= 14
                for who in case["players"] if who not in authors):
            out.append(t)
    return out
def near_miss_problems(detected, name="near_miss"):
    labels, moments = [t for t, _, _ in build.CASES[name]["touches"]], near_miss_moments(name)
    return ([f"FP {t}" for t in detected if all(abs(t - l) > 0.5 + 1e-9 for l in labels)]
            + [f"near-miss {t}" for t in detected if any(abs(t - m) <= 0.5 + 1e-9 for m in moments)])
@pytest.fixture(scope="module")
def eval_set(require_ffmpeg, tmp_path_factory):
    d = tmp_path_factory.mktemp("t031_eval"); build.build_all(d); return d
@pytest.fixture(scope="module")
def detections(eval_set):
    return {n: player.detect_touches(eval_set / n / "clip.mp4") for n in build.CASES}
def test_ac2_player_blobs():
    f = _field(); _rect(f, 100, 60, 8, 16); assert player.player_blobs(f) == [(100, 60, 8, 16)]
    f = _field(); _disc(f, 200, 100); _rect(f, 10, 10, 4, 4); assert player.player_blobs(f) == []
    f = _field(); _rect(f, 200, 40, 8, 16); _rect(f, 50, 100, 8, 16); _rect(f, 20, 40, 8, 16)
    assert player.player_blobs(f) == [(20, 40, 8, 16), (200, 40, 8, 16), (50, 100, 8, 16)]
    f = _field(); _rect(f, 0, 0, 8, 16); _rect(f, 312, 164, 8, 16)
    assert all(x >= 0 and y >= 0 and x + w <= 320 and y + h <= 180 for x, y, w, h in player.player_blobs(f))
    g = np.full((180, 320, 3), 128, np.uint8); _rect(g, 100, 60, 8, 16); assert player.player_blobs(g) == []
def test_ac3_find_kicks():
    fk, S = player.find_kicks, player.KICK_SPAN
    assert fk(_path(15, 99, (20, 90), (4, 0), (4, 0)), 320) == []
    turn = _path(15, 7, (20, 90), (4, 0), (0, 4)); kicks = fk(turn, 320)
    assert max(kicks, key=lambda k: k[1])[0] == 7
    assert all(0 < s <= 1 and S <= i < 15 - S for i, s in kicks)
    rest = [(100.0, 90.0)] * 6 + [(100.0 + 4 * k, 90.0) for k in range(1, 10)]
    assert (5, 1.0) in fk(rest, 320)
    stop = [(20.0 + 4 * k, 90.0) for k in range(8)] + [(48.0, 90.0)] * 7
    assert [i for i, _ in fk(stop, 320) if i >= 6] == []
    a = math.radians(3)
    assert fk(_path(15, 7, (20, 90), (4, 0), (4.2 * math.cos(a), 4.2 * math.sin(a))), 320) == []
    turn[7] = None; assert 7 not in [i for i, _ in fk(turn, 320)]
    assert fk([], 320) == fk([(1.0, 1.0)], 320) == fk([None] * 9, 320) == []
def test_ac4_suppress_touches():
    def ts(pairs): return [x.t for x in player.suppress_touches([T(t, None, None, c, None) for t, c in pairs])]
    assert ts([(1.0, .6), (1.2, .9), (1.4, .5), (1.6, .9), (2.0, .7)]) == [1.2, 2.0]
    assert ts([(1.0, .9), (1.4, .5)]) == [1.0] and ts([(1.6, .2), (1.0, .9)]) == [1.0, 1.6]
    assert ts([(1.2, .5), (1.0, .5)]) == [1.0] and ts([(5.0, .9), (1.0, .3), (3.0, .6)]) == [1.0, 3.0, 5.0]
def _patch(mp, size, path, box, w=320, h=180):
    frames = np.stack([_field(w, h) for _ in path]) if path else np.zeros((0, h, w, 3), np.uint8)
    for f, (bx, by) in zip(frames, path): _rect(f, *box); _disc(f, round(bx), round(by))
    calls = []
    mp.setattr(media, "probe_size", lambda v: size)
    mp.setattr(media, "sample_frames", lambda v, fps, aw, ah: calls.append((str(v), fps, aw, ah)) or frames)
    return frames, calls
def test_ac5_detect_touches_unit(monkeypatch):
    frames, calls = _patch(monkeypatch, (640, 360), _path(15, 7, (112, 82), (6, 0), (0, 6)), (150, 60, 8, 16))
    (touch,) = player.detect_touches("c.mp4")
    assert calls == [("c.mp4", reframe.SAMPLE_HZ, 320, 180)]
    assert touch.t == 1.4 and touch.team is None and touch.number is None and 0 < touch.confidence <= 1
    assert touch.bbox == tuple(2 * v for v in player.player_blobs(frames[7])[0])
    _patch(monkeypatch, (640, 360), _path(15, 7, (112, 140), (6, 0), (0, -5)), (150, 20, 8, 16))
    assert player.detect_touches("far.mp4") == []  # turn far from any player
    frames, calls = _patch(monkeypatch, (160, 90), _path(15, 7, (46, 52), (4, 0), (0, 4)), (70, 30, 8, 16), 160, 90)
    assert [t.bbox for t in player.detect_touches("n.mp4")] == [player.player_blobs(frames[7])[0]]
    assert calls[0][2:] == (160, 90)  # narrow video is not upscaled
    for n in (0, 1, 2):
        _patch(monkeypatch, (640, 360), [(5.0, 5.0)] * n, (150, 60, 8, 16))
        assert player.detect_touches("short.mp4") == []
def test_ac5_coasted_positions_are_not_hits(monkeypatch):
    path = [(100.0 + 6 * i, 82.0) for i in range(15)]
    _patch(monkeypatch, (640, 360), path, (126, 60, 8, 16))
    track = reframe.track_ball([[] if i in (6, 7) else [(x, y, 1.0)] for i, (x, y) in enumerate(path)],
                               reframe.BALL_GATE * 320, reframe.BALL_LOST)
    assert track[6] == track[7] == path[5]  # the tracker really holds the position
    seen = iter(range(15))
    monkeypatch.setattr(reframe, "ball_candidates",
                        lambda f, i=None: (lambda k: [] if k in (6, 7) else [(*path[k], 1.0)])(next(seen)))
    assert player.detect_touches("c.mp4") == []
def test_ac5_no_own_reader_or_detector_in_player():
    pat = re.compile(r"subprocess|ffmpeg|green_mask|cumsum|def (sample_frames|field_mask|ball_candidates|track_ball)")
    assert [l for l in (ROOT / "sportscut/player.py").read_text().splitlines() if pat.search(l)] == []
def test_ac5_real_set_touch_shape(detections):
    for name, touches in detections.items():
        assert touches and [t.t for t in touches] == sorted(t.t for t in touches), name
        for t in touches:
            assert t.team is None and t.number is None and 0 < t.confidence <= 1
            assert abs(t.t * 5 - round(t.t * 5)) < 1e-6 and t.t == round(t.t, 4)
            assert len(t.bbox) == 4 and all(type(v) is int for v in t.bbox)
def test_ac6_closeups_and_missing_file(synthetic_video, tmp_path):
    assert player.detect_touches(synthetic_video) == []
    gray = tmp_path / "gray.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=25:d=3",
                    "-c:v", "mpeg4", "-pix_fmt", "yuv420p", str(gray)], check=True, capture_output=True)
    assert player.detect_touches(gray) == []
    with pytest.raises(MediaError):
        player.detect_touches("missing-x.mp4")
def test_ac7_eval_player_gate(eval_set, capsys):
    assert main(["eval-player", str(eval_set), "--json"]) == 0
    out = capsys.readouterr().out; report = json.loads(out)
    assert out.count("\n") == 1 and report["touch_f1_any"] >= 0.9
    assert report["f1"] == report["precision"] == report["recall"] == 0.0
    assert 0 < report["seconds_per_min"] <= 6.0
def test_ac8_near_miss_not_counted(detections):
    moments = near_miss_moments()
    assert any(abs(m - 4.4) <= 0.6 for m in moments) and any(abs(m - 9.6) <= 0.6 for m in moments)
    assert near_miss_problems(moments)  # the check can fail: a touch at each near-miss moment is caught
    assert near_miss_problems([t for t, _, _ in build.CASES["near_miss"]["touches"]]) == []
    assert near_miss_problems([t.t for t in detections["near_miss"]]) == []
def test_ac9_debug_candidates(eval_set, detections, capsys):
    assert main(["eval-player", str(eval_set), "--json", "--debug"]) == 0
    out = capsys.readouterr().out
    report, plain = json.loads(out), evaluate_dir(eval_set)
    assert out.count("\n") == 1 and set(report) == set(plain) == {
        "f1", "precision", "recall", "touch_f1_any", "team_accuracy", "id_accuracy", "seconds_per_min", "per_clip"}
    for entry in report["per_clip"]:
        assert list(entry)[-1] == "candidates"
        assert entry["candidates"] == [t.to_dict() for t in detections[entry["clip"]]]
    assert all("candidates" not in e for e in plain["per_clip"])
def test_ac10_find_touches_empty(eval_set, detections, monkeypatch):
    assert player.find_touches(eval_set / "near_miss" / "clip.mp4", load_labels(eval_set / "near_miss" / "labels.json")[1][0]) == []
    for name in build.CASES:
        monkeypatch.setattr(player, "detect_touches", lambda v, n=name: detections[n])
        for q in load_labels(eval_set / name / "labels.json")[1]:
            assert player.find_touches(eval_set / name / "clip.mp4", q) == []
def test_ac10_ac12_scope_and_unchanged_api():
    assert _git("ls-files", "*.mp4") == ""
    base = _own_base()
    prot = ["sportscut/reframe.py", "sportscut/media.py", "tests/conftest.py", "tests/fixtures/eval_player", "pyproject.toml"]
    assert _git("diff", "--stat", base, "--", *prot) == "" and _git("status", "--porcelain", "--", *prot) == ""
    old, new = _git("show", f"{base}:sportscut/player.py"), (ROOT / "sportscut/player.py").read_text()
    for start in ("def normalize_team", "class PlayerQuery", "class Touch", "def find_touches"):
        assert re.search(rf"^{start}.*?(?=^\S|\Z)", old, re.M | re.S).group(0).rstrip() == \
            re.search(rf"^{start}.*?(?=^\S|\Z)", new, re.M | re.S).group(0).rstrip(), start
def test_ac11_ac14_test_edits_and_size():
    base = _own_base()
    changed = set(_git("diff", "--name-only", "--diff-filter=MDR", base, "--", "tests").split())
    assert changed <= {"tests/test_player.py", "tests/test_eval_player_fixtures.py",
                       "tests/test_t042_round2_acceptance.py", "tests/test_t042_tester_acceptance.py"}
    rows = [l.split("\t") for l in _git("diff", "--numstat", base, "--", ".", ":!docs/superpowers").splitlines()]
    total = sum(int(a) + int(d) for a, d, _ in rows if a != "-")
    total += sum(len((ROOT / p).read_text().splitlines())
                 for p in _git("ls-files", "--others", "--exclude-standard", "--", "sportscut", "tests").split())
    assert total < 600, total
def test_ac13_readme_and_t029_bullet():
    text = (ROOT / "README.md").read_text()
    heads = [l for l in text.splitlines() if l.startswith("## ")]
    assert heads[heads.index("## Phát hiện chạm bóng (T-031)") + 1] == "## Highlight theo sự kiện: đo độ chính xác (eval)"
    sec = text.split("## Phát hiện chạm bóng (T-031)", 1)[1].split("\n## ", 1)[0]
    assert "python -m sportscut eval-player tests/fixtures/eval_player --json --debug" in sec
    consts = re.findall(r"```text\n(.*?)```", sec, re.S)[0]
    for name in ("KICK_SPAN", "TURN_DEG", "SPEED_JUMP", "MIN_SPEED", "REACH", "BLOB_MIN_AREA", "TOUCH_NMS"):
        assert float(re.search(rf"^{name}\s*=\s*([0-9.]+)", consts, re.M).group(1)) == getattr(player, name)
    js = re.search(r"```json\n(.*?)\n```", sec.split("Kết quả đo trong T-031:", 1)[1], re.S).group(1)
    assert "\n" not in js.strip() and json.loads(js)["touch_f1_any"] >= 0.9 and json.loads(js)["seconds_per_min"] <= 6.0
    spec = ROOT / "docs/superpowers/specs/2026-11-23-t-029-build-the-player-touch-eval-synthetic-design.md"
    assert ("- T-031 (2026-11-27): detect_touches now returns touch candidates by any player (team/number None); "
            "find_touches still returns [] until T-032/T-033. The T-029 README baseline is kept as history.") in spec.read_text()
    numstat = _git("diff", "--numstat", _own_base(), "--", "README.md").split()
    assert numstat and numstat[1] == "0"  # insert-only vs the merge-base
