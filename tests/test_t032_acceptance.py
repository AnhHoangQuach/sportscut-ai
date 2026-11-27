"""Tester acceptance checks for T-032, written from the ACs in .office/TASK.md."""
import dataclasses, importlib.util, json, re, subprocess
from pathlib import Path
import numpy as np, pytest
from sportscut import media, player as P
from sportscut.cli import main
from sportscut.eval_player import evaluate_dir, load_labels
ROOT = Path(__file__).resolve().parent.parent; _s = importlib.util.spec_from_file_location("t032_build", ROOT / "tests/fixtures/eval_player/build.py")
build = importlib.util.module_from_spec(_s); _s.loader.exec_module(build); RED, BLUE, Q = (200, 30, 30), (30, 60, 200), P.PlayerQuery
def F(*rgb): return P.colour_features(np.array([rgb], np.uint8))[0]
C = P.TeamColours((tuple(F(255, 0, 0)), tuple(F(0, 0, 255))), ("red", "blue"))
def _frame(shirts, ball=None, digits=True):
    f = np.empty((180, 320, 3), np.uint8); f[:] = (40, 140, 60); yy, xx = np.ogrid[:180, :320]
    for (x, y), c in shirts: f[y:y + 16, x:x + 8] = c; f[y + 4:y + 6, x + 3:x + 5] = 255 if digits else c
    if ball: f[(xx - ball[0]) ** 2 + (yy - ball[1]) ** 2 <= 4] = 255
    return f
def _frames(cols, **kw): return np.stack([_frame([((20 + 28 * (i % 10), 20 + 40 * (i // 10)), c) for i, c in enumerate(cols)], **kw)] * 6)
def _git(*a): return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout
def _base():  # Tech Lead pattern: git-diff scope checks only run on the T-032 branch
    if not _git("rev-parse", "--abbrev-ref", "HEAD").strip().startswith("office/T-032"): pytest.skip("office/T-032* only")
    return _git("merge-base", "main", "HEAD").strip() or pytest.skip("no main")
@pytest.fixture(scope="module")
def eval_set(require_ffmpeg, tmp_path_factory): d = tmp_path_factory.mktemp("t032_eval"); build.build_all(d); return d
def test_ac2_ac3_ac5_features_kmeans_names():
    got = P.colour_features(np.array([[255, 0, 0], [0, 0, 255], [255, 255, 255], [0, 0, 0], [200, 30, 30]], np.uint8))
    assert got.dtype == np.float64 and np.allclose(got, [[1, 0, 1], [-.5, -.866025, 1], [0, 0, 1], [0, 0, 0], [.85, 0, .784314]], atol=1e-5)
    assert tuple(P.TEAM_RGB) == P.TEAM_NAMES and P.TEAM_RGB == {"black": (0, 0, 0), "blue": (0, 0, 255), "green": (0, 128, 0), "orange": (255, 165, 0), "pink": (255, 105, 180), "purple": (128, 0, 128), "red": (255, 0, 0), "sky": (135, 206, 235), "white": (255, 255, 255), "yellow": (255, 255, 0)}
    assert P.name_teams(np.array([F(*RED), F(*BLUE)])) == ("red", "blue") and P.name_teams(np.array([F(*BLUE), F(*RED)])) == ("blue", "red")
    pair = P.name_teams(np.array([F(*RED), F(180, 25, 25)])); assert pair[0] != pair[1] and "red" in pair and set(pair) <= set(P.TEAM_NAMES)
    a, b = np.array([[1, 0, 1]] * 30) + np.linspace(-.02, .02, 90).reshape(30, 3), np.array([[-.5, -.87, 1]] * 20) + np.linspace(.03, -.03, 60).reshape(20, 3)
    (c1, l1), (c2, l2) = P.kmeans(np.concatenate([b[:10], a, b[10:]]), 2), P.kmeans(np.concatenate([b[:10], a, b[10:]]), 2)
    la, lb = set(l1[10:40]), set(l1[:10]) | set(l1[40:]); assert np.array_equal(c1, c2) and np.array_equal(l1, l2) and len(la) == len(lb) == 1 and la != lb
    assert c1.shape == (2, 3) and np.linalg.norm(c1[min(la)] - a.mean(0)) < .05 and np.linalg.norm(c1[min(lb)] - b.mean(0)) < .05
    for pts, k in ((np.array([[0, 0, 0]] * 5 + [[1, 1, 1]] * 4, float), 3), (np.zeros((2, 3)), 3)): c, l = P.kmeans(pts, k); assert c.shape == (k, 3) and l.shape == (len(pts),)
def test_ac4_team_colours():
    for frames in (_frames(cols := [RED] * 6 + [BLUE] * 4 + [(240, 140, 20)], ball=(300, 150)), _frames(cols, digits=False), _frames(cols)[:1]):
        tc = P.team_colours(frames); assert tc == P.team_colours(frames.copy()) and isinstance(tc, P.TeamColours)
        assert tc.names == ("red", "blue") and np.linalg.norm(np.array(tc.centroids[0]) - F(*RED)) < .03
    assert P.team_colours(_frames([BLUE] * 6 + [RED] * 4)).names == ("blue", "red")
    assert [P.team_colours(f) for f in (_frames([RED] * 8), _frames([RED] * 10 + [(240, 140, 20)]), _frames([RED] * 5 + [(180, 25, 25)] * 5), _frames([(250, 250, 250)] * 5 + [(20, 20, 20)] * 5),
                                       np.full((6, 180, 320, 3), 128, np.uint8), np.zeros((0, 180, 320, 3), np.uint8))] == [None] * 6
def test_ac6_ac7_shirt_pixels_team_of_pick_team():
    f, tc = _frames([RED, BLUE], ball=(300, 150))[0], P.team_colours(_frames([RED] * 6 + [BLUE] * 4)); every, red = P.shirt_pixels(f), P.shirt_pixels(f, (20, 20, 8, 16))
    assert P.shirt_pixels(np.full((180, 320, 3), 128, np.uint8)).shape == (0, 3) and 0 < len(red) < len(every) and np.allclose(red, F(*RED)) and (np.hypot(every[:, 0], every[:, 1]) >= P.TEAM_MIN_SAT).all()
    assert [P.team_of(f, b, tc) for b in ((20, 20, 8, 16), (48, 20, 8, 16), (20, 20, 34, 16), (150, 100, 10, 10), (296, 146, 9, 9))] + [P.team_of(f, (20, 20, 8, 16), None)] == ["red", "blue", "red", None, None, None]
    assert [P.pick_team(t, C) for t in ("blue", "red", "#ff0000", "orange", "sky", "#0000ff")] == ["blue", "red", "red", "red", "blue", "blue"]
    with pytest.raises(ValueError) as e: P.pick_team("#ff00ff", C)
    assert str(e.value) == "team colour '#ff00ff' is equally close to both team shirts (red, blue); use --team red, --team blue or a closer #rrggbb"
def _patch(mp, shirts):
    frames = np.stack([_frame(shirts, (112 + 6 * min(i, 7), 82 + 6 * max(i - 7, 0)), False) for i in range(15)])
    mp.setattr(media, "probe_size", lambda v: (640, 360)); mp.setattr(media, "sample_frames", lambda *a: frames)
def test_ac8_detect_touches_team(monkeypatch):
    for toucher, team in ((RED, "red"), (BLUE, "blue")):
        _patch(monkeypatch, [((150, 60), toucher), ((20, 20), BLUE), ((60, 140), BLUE), ((280, 30), BLUE), ((250, 140), RED), ((20, 100), RED)])
        (t,) = P.detect_touches("c.mp4"); assert (t.t, t.team, t.number) == (1.4, team, None) and P._analyse("c.mp4")[0] == [t]
    _patch(monkeypatch, [((150, 60), RED)]); assert [t.team for t in P.detect_touches("c.mp4")] == [None]
def test_ac9_find_touches_and_cli(monkeypatch, synthetic_video, tmp_path, capsys):
    ts, calls = [P.Touch(1.0, "red", None, .5, None), P.Touch(2.0, "blue", None, .5, None), P.Touch(3.0, "red", 7, .5, None), P.Touch(4.0, None, None, .5, None)], []
    def fake(colours): monkeypatch.setattr(P, "_analyse", lambda v: calls.append(v) or (ts, colours))
    fake(C); assert P.find_touches("x.mp4", Q("red", 10)) == [ts[0], ts[2]] and calls == ["x.mp4"]
    assert P.find_touches("x", Q("sky", 99)) == [ts[1]] and P.find_touches("x", Q("#ff1010", 1)) == [ts[0], ts[2]] and P.detect_touches("x") == ts
    with pytest.raises(ValueError, match="equally close"): P.find_touches("x", Q("#ff00ff", 7))
    fake(None); assert P.find_touches("x", Q("red", 10)) == []
    fake(C); assert main(["player", str(synthetic_video), "--team", "#ff00ff", "--number", "7", "--out", str(tmp_path / "o")]) == 2
    err = capsys.readouterr().err; assert "sportscut player: error:" in err and "equally close" in err
def test_ac10_eval_player_gate_and_queries(eval_set, capsys):
    assert main(["eval-player", str(eval_set), "--json"]) == 0; r = json.loads(capsys.readouterr().out); floor = {"dribble": 1, "near_miss": 1, "number_hidden": 1, "short_passes": .9091}
    assert r["team_accuracy"] >= .95 and r["touch_f1_any"] >= .9737 and r["f1"] > 0 and r["id_accuracy"] == 0 and 0 < r["seconds_per_min"] <= 6
    assert {e["clip"]: e["touch_f1_any"] >= floor[e["clip"]] for e in r["per_clip"]} == dict.fromkeys(floor, True)
    for name in build.CASES:
        clip = eval_set / name / "clip.mp4"; det = P.detect_touches(clip); assert det and {t.team for t in det} <= {"red", "blue"}
        for q in load_labels(eval_set / name / "labels.json")[1]: assert all(t in det and t.team == q.team for t in P.find_touches(clip, q))
    red, blue = P.find_touches(clip := eval_set / "short_passes/clip.mp4", Q("red", 7)), P.find_touches(clip, Q("blue", 4))
    assert red and blue and P.find_touches(clip, Q("#c81e1e", 7)) == red and P.find_touches(clip, Q("sky", 4)) == blue
def test_ac10_gate_can_fail_with_swapped_teams(eval_set, monkeypatch):
    real, sw = P._analyse, {"red": "blue", "blue": "red"}; monkeypatch.setattr(P, "_analyse", lambda v: (lambda ts, c: ([dataclasses.replace(t, team=sw.get(t.team)) for t in ts], c))(*real(v)))
    assert evaluate_dir(eval_set)["team_accuracy"] < .95
def test_ac8_ac11_ac12_ac14_scope():
    assert _git("ls-files", "*.mp4") == "" and not re.search(r"subprocess|ffmpeg|green_mask|cumsum|def (sample_frames|field_mask|ball_candidates|track_ball)", (ROOT / "sportscut/player.py").read_text())
    b = _base(); prot = [f"sportscut/{m}.py" for m in ("reframe", "media", "eval_player", "cli", "reel", "api")] + ["tests/conftest.py", "tests/fixtures/eval_player", "pyproject.toml"]
    assert _git("diff", "--stat", b, "--", *prot) == "" and _git("status", "--porcelain", "--", *prot) == ""
    old, new = _git("show", f"{b}:sportscut/player.py"), (ROOT / "sportscut/player.py").read_text(); blocks = lambda s, src: [m.group(0).rstrip() for m in re.finditer(rf"^{s}.*?(?=^\S|\Z)", src, re.M | re.S)]
    for s in ("def normalize_team", "class PlayerQuery", "class Touch", "def player_blobs", "def find_kicks", "def suppress_touches", "def _box_gap", "KICK_SPAN ", "TURN_DEG ", "SPEED_JUMP ", "MIN_SPEED ", "REACH ", "BLOB_MIN_AREA ", "TOUCH_NMS ", "TEAM_NAMES "):
        assert blocks(s, old) == blocks(s, new) != [], s
    changed = _git("diff", "--name-only", "--diff-filter=MDR", b, "--", "tests").split(); assert set(changed) <= {"tests/test_player.py", "tests/test_touches.py", "tests/test_eval_player_fixtures.py", "tests/test_t031_acceptance.py"}
    for f in changed: assert re.findall(r"def (test_\w+)", _git("show", f"{b}:{f}")) == re.findall(r"def (test_\w+)", (ROOT / f).read_text()), f
    assert not re.search(r"^\+.*(skip|xfail)", _git("diff", b, "--", *changed), re.M)
    rows = [l.split("\t") for l in _git("diff", "--numstat", b, "--", ".", ":!docs/superpowers").splitlines()]
    total = sum(int(x) + int(y) for x, y, _ in rows if x != "-") + sum(len((ROOT / p).read_text().splitlines()) for p in _git("ls-files", "--others", "--exclude-standard", "--", "sportscut", "tests").split())
    assert total < 600, total
def test_ac13_readme_and_spec_bullets():
    text, h = (ROOT / "README.md").read_text(), "## Đội theo màu áo (T-032)"; heads = [l for l in text.splitlines() if l.startswith("## ")]; sec = text.split(h + "\n", 1)[1].split("\n## ", 1)[0]
    assert heads.count(h) == 1 and heads[heads.index(h) + 1] == "## API HTTP" and all(w in sec for w in ("--team", "#rrggbb", "equally close", "T-033", "trùng màu áo", "trắng", "đen", "xám", "một đội"))
    consts, names = re.findall(r"```text\n(.*?)```", sec, re.S)[0], sorted(n for n in vars(P) if n.startswith("TEAM_") and n not in ("TEAM_NAMES", "TEAM_RGB"))
    assert sorted(re.findall(r"^(TEAM_\w+)\s*=", consts, re.M)) == names and all(float(re.search(rf"^{n}\s*=\s*([0-9.]+)", consts, re.M).group(1)) == getattr(P, n) for n in names)
    js = [re.search(r"```json\n(.*?)\n```", sec.split(k, 1)[1], re.S).group(1) for k in ("Trước T-032:", "Sau T-032:")]; before, after = map(json.loads, js)
    assert "\n" not in "".join(js) and before["team_accuracy"] == 0.0 and after["team_accuracy"] >= .95 and after["touch_f1_any"] >= before["touch_f1_any"]
    bullet = "- T-032 (2026-11-27): detect_touches fills Touch.team from two shirt-colour clusters; find_touches returns every touch by the queried team (number ignored until T-033), superseding T-031 AC10 (find_touches == [])."
    for s in ("t-031-detect-ball-touches-by-any-player", "t-029-build-the-player-touch-eval-synthetic"):
        lst = (ROOT / f"docs/superpowers/specs/2026-11-23-{s}-design.md").read_text().split("## Existing specs this task changes", 1)[1].split("\n## ", 1)[0]
        assert [l for l in lst.splitlines() if l.startswith("- ")][-1] == bullet, s
    numstat = _git("diff", "--numstat", _base(), "--", "README.md").split(); assert numstat and numstat[1] == "0"
