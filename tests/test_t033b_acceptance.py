"""T-052 (T-033 slice B) Tester acceptance tests, written from the acceptance criteria in .office/TASK.md."""
import dataclasses, importlib.util, json, math, re, subprocess, sys
from pathlib import Path
import numpy as np, pytest
from sportscut import jersey, media, player as P
from sportscut.cli import main
from sportscut.eval_player import evaluate_dir, load_labels
ROOT = Path(__file__).resolve().parent.parent
_s = importlib.util.spec_from_file_location("t052_build", ROOT / "tests/fixtures/eval_player/build.py")
build = importlib.util.module_from_spec(_s); _s.loader.exec_module(build)
GRASS, RED, BLUE, Q, T = (40, 140, 60), (200, 30, 30), (30, 60, 200), P.PlayerQuery, P.Touch
MSG = "min confidence must be between 0 and 1"
class Fake:
    """probe_size/sample_window fakes; frames are a pure function of the absolute time start + k/fps."""
    def __init__(self, mp, scene, keep=1.0):
        self.scene, self.keep, self.calls, self.probes, self.bases = scene, keep, [], [], []
        mp.setattr(media, "probe_size", lambda v: self.probes.append(v) or (640, 360))
        mp.setattr(media, "sample_window", self.window)
    def window(self, video, start, duration, fps, width, height):
        assert (width, height) == (640, 360)
        self.calls.append((start, duration)); n = round(duration * fps); n = max(1, int(n * self.keep)) if self.keep < 1 else n
        out = np.empty((n, 360, 640, 3), np.uint8)
        for k in range(n):
            out[k] = GRASS
            for x, y, rgb, num in self.scene(start + k / fps):
                out[k, y:y + 32, x:x + 16] = rgb
                if num is not None: build._draw_number(out[k], num, x, y)
        self.bases.append((out.__array_interface__["data"][0], out.strides[0] if n else 0, n, start, fps)); return out
    def time_of(self, crop):
        addr = crop.__array_interface__["data"][0]
        for base, stride, n, start, fps in reversed(self.bases):
            if 0 <= addr - base < stride * n: return start + ((addr - base) // stride) / fps
class Rec:
    def __init__(self, fake=None, max_reads=None):
        self.inner, self.fake, self.max_reads, self.name, self.log = jersey.DigitReader(), fake, max_reads, "rec", []
    def read(self, crop):
        r = self.inner.read(crop); self.log.append((self.fake.time_of(crop) if self.fake else None, r[0])); return r
def moving(t0, hide=None, jump=None):  # red 7, 6 px per 0.2 s; number blank within +-hide of t0; +100 px from t0+jump
    def scene(t):
        x = round(100 + 30 * t) + (100 if jump is not None and t >= t0 + jump - 1e-9 else 0)
        return [(x, 150, RED, None if hide is not None and abs(t - t0) <= hide + 1e-9 else 7)]
    return scene
def box(scene, t): x, y, _, _ = scene(t)[0]; return (x, y, 16, 32)
def touch(scene, t): return T(t, "red", None, .5, box(scene, t))
def on_grid(v): return v >= 0 and abs(v * 5 - round(v * 5)) < 1e-6
def test_ac2_query_and_constants():
    assert Q("red", 10) == Q("red", 10, P.MIN_CONFIDENCE) and hash(Q("red", 10)) == hash(Q("red", 10, P.MIN_CONFIDENCE))
    assert type(Q("red", 10, 1).min_confidence) is float and Q("red", 10, 0).min_confidence == 0.0 and Q("red", 10, 1).min_confidence == 1.0
    for bad in (-0.1, 1.01, float("nan"), float("inf"), True, "0.5"):
        with pytest.raises(ValueError) as e: Q("red", 10, bad)
        assert str(e.value) == MSG
    assert P.NUMBER_SPAN == 2.0 and P.NUMBER_WIDTH == 1280 and 0.5 <= P.TRACK_GATE <= 2.0 and 1.2 <= P.TRACK_MERGE <= 1.6 and 0.3 <= P.MIN_CONFIDENCE <= 0.8 and P.NUMBER_GROUP_MAX == 20.0
def test_ac3_hidden_number_far_box_none_and_no_decode(monkeypatch):
    sc = moving(5.0, hide=1.0); fk = Fake(monkeypatch, sc); rd = Rec(fk)
    ((n, c),) = P._read_numbers("v.mp4", [touch(sc, 5.0)], rd)
    assert n == 7 and c >= P.MIN_CONFIDENCE and any(r == 7 for _, r in rd.log)
    assert all(abs(tt - 5.0) > 1.0 for tt, r in rd.log if r == 7)  # read from neighbour frames only
    far, none = T(5.0, "red", None, .5, (560, 300, 16, 32)), T(5.0, "red", None, .5, None)
    assert P._read_numbers("v.mp4", [far, none], Rec()) == [(None, 0.0), (None, 0.0)]
    fk.calls.clear(); fk.probes.clear()
    assert P._read_numbers("v.mp4", [], Rec()) == [] and P._read_numbers("v.mp4", [none, none], Rec()) == [(None, 0.0)] * 2
    assert fk.calls == [] and fk.probes == []
def test_ac3_jump_and_max_reads(monkeypatch):
    sc = moving(5.0, jump=1.0); fk = Fake(monkeypatch, sc); rd = Rec(fk)
    (n, _), = P._read_numbers("v.mp4", [touch(sc, 5.0)], rd)
    assert n == 7 and rd.log and all(tt <= 5.8 + 1e-6 for tt, _ in rd.log)
    sc2 = moving(5.0); Fake(monkeypatch, sc2); two = Rec(max_reads=2)
    P._read_numbers("v.mp4", [touch(sc2, 5.0), touch(sc2, 15.0)], two)
    assert len(two.log) == 4
def test_ac3_windows_grouping_and_clip_end(monkeypatch):
    sc = moving(-99); fk = Fake(monkeypatch, sc); a, b = touch(sc, 5.1), touch(sc, 6.1)
    pair = P._read_numbers("v.mp4", [b, a], Rec()); assert len(fk.calls) == 1 and on_grid(fk.calls[0][0]) and pair[0][0] == pair[1][0] == 7
    assert [P._read_numbers("v.mp4", [x], Rec())[0] for x in (b, a)] == pair  # vote independent of grouping
    fk.calls.clear(); P._read_numbers("v.mp4", [a, touch(sc, 15.1)], Rec()); assert len(fk.calls) == 2 and all(on_grid(s) for s, _ in fk.calls)
    fk.calls.clear(); (v,) = P._read_numbers("v.mp4", [touch(sc, 0.4)], Rec()); assert fk.calls[0][0] == 0.0 and v[0] == 7
    hs = moving(5.0, hide=1.0); Fake(monkeypatch, hs); alone = P._read_numbers("v.mp4", [touch(hs, 5.0)], Rec())
    Fake(monkeypatch, hs); assert P._read_numbers("v.mp4", [touch(hs, 5.0), touch(hs, 6.0)], Rec())[0] == alone[0]
    Fake(monkeypatch, sc, keep=0.5); out = P._read_numbers("v.mp4", [a, b, touch(sc, 15.1)], Rec())
    assert len(out) == 3 and all(isinstance(c, float) for _, c in out)
    fk = Fake(monkeypatch, lambda t: [(300, 150, RED, 7)]); chain = [T(5.1 + 3 * i, "red", None, .5, (300, 150, 16, 32)) for i in range(10)]
    votes = P._read_numbers("v.mp4", chain, Rec()); assert len(fk.calls) >= 2 and all(on_grid(s) and d <= P.NUMBER_GROUP_MAX + .2 + 1e-6 for s, d in fk.calls)
    assert all(any(s - 1e-6 <= x.t - 2 and x.t + 2 <= s + d + 1e-6 for s, d in fk.calls) for x in chain) and votes == [P._read_numbers("v.mp4", [x], Rec())[0] for x in chain] and votes[0][0] == 7
def test_ac4_identity_kept_through_crossing(monkeypatch):
    def scene(t): return [(300, 150, RED, 9), (round(300 + 40 * (t - 5.6)), 150, RED, 7)]  # 8 px / 0.2 s, crossing at 5.6
    fk = Fake(monkeypatch, scene); rd = Rec(fk)
    ((n, c),) = P._read_numbers("v.mp4", [T(4.6, "red", None, .5, (260, 150, 16, 32))], rd)
    assert n == 7 and c >= P.MIN_CONFIDENCE and {r for _, r in rd.log} <= {7, None}
    assert any(tt > 6.0 and r == 7 for tt, r in rd.log)  # the track is kept after the crossing
B = (10, 10, 16, 32)
def _ac5(mp, colours, record):
    ts = [T(1.0, "red", None, .5, B), T(2.0, "blue", None, .5, B), T(3.0, "red", None, .5, B), T(4.0, None, None, .5, B)]
    votes = {1.0: (10, .9), 2.0: (10, .9), 3.0: (7, .4)}
    mp.setattr(P, "_analyse", lambda v: record.append("analyse") or (ts, colours))
    mp.setattr(P, "_read_numbers", lambda v, xs, r: record.append(list(xs)) or [votes[x.t] for x in xs]); return ts
def test_ac5_detect_and_find_filter(monkeypatch):
    F = lambda *rgb: tuple(P.colour_features(np.array([rgb], np.uint8))[0])
    C, rec = P.TeamColours((F(255, 0, 0), F(0, 0, 255)), ("red", "blue")), []
    r1, b2, r3, n4 = ts = _ac5(monkeypatch, C, rec); R = dataclasses.replace
    assert P.find_touches("x", Q("red", 10)) == [R(r1, number=10)] and rec == ["analyse", [r1, r3]]
    assert P.find_touches("x", Q("red", 7)) == [] and P.find_touches("x", Q("red", 7, 0.3)) == [R(r3, number=7)]
    rec.clear(); assert P.find_touches("x", Q("#0000ff", 10)) == [R(b2, number=10)] and rec == ["analyse", [b2]]
    rec.clear(); got = P.detect_touches("x"); assert rec == ["analyse", [r1, b2, r3]]
    assert [t.number for t in got] == [10, 10, None, None] and [(t.t, t.team, t.confidence, t.bbox) for t in got] == [(t.t, t.team, t.confidence, t.bbox) for t in ts]
    rec.clear()
    with pytest.raises(ValueError, match="equally close"): P.find_touches("x", Q("#ff00ff", 7))
    assert rec == ["analyse"]
    _ac5(monkeypatch, None, rec2 := []); assert P.find_touches("x", Q("red", 10)) == [] and rec2 == ["analyse"]
    def boom(): raise ValueError("x")
    monkeypatch.setattr(jersey, "get_reader", boom); rec2.clear()
    for call in (lambda: P.detect_touches("x"), lambda: P.find_touches("x", Q("red", 10))):
        with pytest.raises(ValueError, match="^x$"): call()
    assert rec2 == []
def test_ac6_cli_min_confidence(monkeypatch, tmp_path, capsys):
    p = subprocess.run([sys.executable, "-m", "sportscut", "player", str(tmp_path / "c.mp4"), "--team", "blue", "--number", "8",
                        "--min-confidence", "1.5", "--out", str(tmp_path / "D")], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 2 and f"sportscut player: error: {MSG}" in p.stderr and not (tmp_path / "D").exists()
    for bad in ("-0.1", "nan"):
        assert main(["player", "c.mp4", "--team", "blue", "--number", "8", "--min-confidence", bad, "--out", str(tmp_path / bad)]) == 2
        assert MSG in capsys.readouterr().err and not (tmp_path / bad).exists()
    seen = []; monkeypatch.setattr(P, "find_touches", lambda v, q: seen.append(q) or []); monkeypatch.setattr("sportscut.reel.probe_duration", lambda v: 10.0)
    for extra in (["--min-confidence", "0.3"], []): assert main(["player", "c.mp4", "--team", "blue", "--number", "8", *extra, "--out", str(tmp_path / "o")]) == 0
    assert seen == [Q("blue", 8, 0.3), Q("blue", 8)] and seen[0].min_confidence == 0.3
    with pytest.raises(SystemExit): main(["player", "--help"])
    assert "--min-confidence" in capsys.readouterr().out
@pytest.fixture(scope="module")
def built(require_ffmpeg, tmp_path_factory): d = tmp_path_factory.mktemp("t052_set"); build.build_all(d); return d
def _hidden_only(built, tmp_path): (tmp_path / "number_hidden").symlink_to(built / "number_hidden"); return tmp_path
def _clip(r, name): return next(c for c in r["per_clip"] if c["clip"] == name)
def test_ac7_merge_gate_and_find_subset_of_detect(built, tmp_path):
    r = evaluate_dir(built); nh = _clip(r, "number_hidden")
    assert r["f1"] >= .85 and nh["f1"] >= .85 and r["id_accuracy"] >= .75 and r["precision"] > .4205 and r["team_accuracy"] >= .95 and r["touch_f1_any"] >= .9737
    assert all(_clip(r, k)["touch_f1_any"] >= v for k, v in {"dribble": 1, "near_miss": 1, "number_hidden": 1, "short_passes": .9091}.items())
    assert 0 < r["seconds_per_min"] <= 6.0
    for case in sorted(p for p in built.iterdir() if (p / "labels.json").is_file()):
        clip, (_, queries) = case / "clip.mp4", load_labels(case / "labels.json"); det = P.detect_touches(clip)
        for q in queries:
            for t in P.find_touches(clip, q): assert t in det and t.team == q.team and t.number == q.number
    out = tmp_path / "D"; p = subprocess.run([sys.executable, "-m", "sportscut", "player", str(built / "number_hidden/clip.mp4"), "--team", "blue", "--number", "8", "--out", str(out)], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr; ts = json.loads((out / "player.json").read_text())["touches"]
    assert ts and all(t["team"] == "blue" and t["number"] == 8 for t in ts) and sum(any(abs(t["t"] - x) <= .5 for t in ts) for x in (4.0, 5.2, 9.0, 14.0)) >= 3
def test_ac8_gate_can_fail(built, tmp_path, monkeypatch):
    clip = built / "number_hidden/clip.mp4"
    sets = [{(t.t, t.number) for t in P.find_touches(clip, Q("blue", 8, m))} for m in (0.0, P.MIN_CONFIDENCE, 1.0)]
    assert sets[0] >= sets[1] >= sets[2] and sets[1]
    class Blind: name, max_reads = "blind", None; read = lambda self, crop: (None, 0.0)
    monkeypatch.setattr(jersey, "get_reader", Blind); r = evaluate_dir(built); assert r["f1"] == 0.0 and r["id_accuracy"] == 0.0
    monkeypatch.undo(); monkeypatch.setattr(P, "NUMBER_SPAN", 0.4)
    assert evaluate_dir(_hidden_only(built, tmp_path))["per_clip"][0]["f1"] < .85
def test_ac9_frames_sampled_only_around_touches(built, monkeypatch):
    sf, sw, an = media.sample_frames, media.sample_window, P._analyse; log = {"frames": 0, "win": [], "touches": []}
    monkeypatch.setattr(media, "sample_frames", lambda *a, **k: log.__setitem__("frames", log["frames"] + 1) or sf(*a, **k))
    monkeypatch.setattr(media, "sample_window", lambda v, s, d, *a: log["win"].append((s, d)) or sw(v, s, d, *a))
    monkeypatch.setattr(P, "_analyse", lambda v: (res := an(v)) and log["touches"].append(res) or res)
    for case, q in (("short_passes", Q("red", 7)), ("dribble", Q("red", 10)), ("near_miss", Q("red", 11)), ("number_hidden", Q("blue", 8))):
        log.update(frames=0, win=[], touches=[]); P.find_touches(built / case / "clip.mp4", q)
        (touches, colours), = log["touches"]; team = P.pick_team(q.team, colours); ts = [t.t for t in touches if t.team == team]
        assert log["frames"] == 1 and log["win"], case
        for s, d in log["win"]:
            assert on_grid(s), (case, s)
            assert _covered(s, s + d, ts), (case, s, d)
        if case == "short_passes": assert not any(s <= 12.0 <= s + d for s, d in log["win"])
def _covered(a, b, ts):  # [a, b] inside the union of the per-touch allowed intervals
    iv = sorted((t - P.NUMBER_SPAN - .2, t + P.NUMBER_SPAN + .4) for t in ts); x = a
    for lo, hi in iv:
        if lo <= x + 1e-6: x = max(x, hi)
    return x >= b - 1e-6
def _section(text):
    i = text.index("## Số áo cầu thủ (T-033)"); j = text.index("\n## ", i + 3); return text[i:j]
def test_ac11_readme_section():
    text = (ROOT / "README.md").read_text(); heads = re.findall(r"^## .*$", text, re.M); i = heads.index("## Số áo cầu thủ (T-033)")
    assert heads.count(heads[i]) == 1 and heads[i - 1] == "## Theo dõi cầu thủ: xuất video tổng hợp (player)" and heads[i + 1] == "## Đội theo màu áo (T-032)"
    s = _section(text)
    for need in ("--min-confidence", "python -m sportscut player match.mp4 --team red --number 10 --min-confidence 0.3 --out reel", "góc rộng", "data/eval_player/"): assert need in s
    for need in ("SPORTSCUT_NUMBER_READER", "pip install 'sportscut[ocr]'", "download-models --ocr"): assert need in s
    block = re.search(r"```text\n(.*?)```", s, re.S).group(1); consts = dict(re.findall(r"^(\w+) = ([\d.]+)", block, re.M))
    for mod, names in ((P, "NUMBER_SPAN NUMBER_WIDTH TRACK_GATE TRACK_MERGE MIN_CONFIDENCE NUMBER_GROUP_MAX"), (jersey, "VOTE_MIN_READS INK_CONTRAST INK_MIN_PIXELS NUMBER_TOP DIGIT_MIN_SCORE")):
        for name in names.split(): assert float(consts[name]) == getattr(mod, name), name
    before, after = (json.loads(re.search(label + r"\s*```json\n(.*)\n```", s).group(1)) for label in ("Trước T-033:", "Sau T-033:"))
    assert before["id_accuracy"] == 0.0 and after["f1"] >= .85 and after["id_accuracy"] >= .75
def test_ac12_spec_endings():
    specs = ROOT / "docs/superpowers/specs"
    for pat in ("*t-030-*design.md", "*t-031-*design.md", "*t-032-*design.md"):
        (f,) = specs.glob("2026-11-23-" + pat); text = f.read_text(); last = text[text.rindex("\n## "):]
        assert last.startswith("\n## Updated by T-033") and all(w in last for w in ("--min-confidence", "number vote", "find_touches")), f.name
    (f,) = specs.glob("2026-11-23-t-033-*design.md"); text = f.read_text(); last = text[text.rindex("\n## "):]
    assert last.startswith("\n## Updated by T-051"); para = text.rstrip().split("\n\n")[-1]
    assert para.startswith("Updated by T-052:") and "TRACK_MERGE" in para and "T-053" in para
