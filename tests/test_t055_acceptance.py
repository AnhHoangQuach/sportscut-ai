"""T-055 Tester acceptance tests: phone eval set, goal_coverage, eval with top=None."""
import importlib.util, inspect, json, subprocess, sys
from pathlib import Path
import numpy as np, pytest
from sportscut import detect, evaluate
from sportscut.events import audio_cues, incidents, scoreboard
from sportscut.models import Segment

ROOT = Path(__file__).resolve().parents[1]
PHONE, SPECS = ROOT / "tests" / "fixtures" / "eval_phone", ROOT / "docs" / "superpowers" / "specs"
CASES = {"pitch_a": (1501, [(120.0, 7.0), (395.0, 8.0)], [(50.0, 2.0), (270.0, 2.5), (520.0, 3.0)], (300.0, 8.0), [75, 160, 245, 330, 420, 500, 580]),
         "pitch_b": (1502, [(200.0, 7.5), (450.0, 8.0)], [(90.0, 3.0), (330.0, 2.0), (540.0, 2.5)], (150.0, 10.0), [65, 140, 235, 300, 390, 475, 560])}
LABELS = {"pitch_a": [(46, 54, "chance"), (110, 126, "goal"), (266, 274, "chance"), (385, 401, "goal"), (516, 524, "chance")],
          "pitch_b": [(86, 94, "chance"), (190, 206, "goal"), (326, 334, "chance"), (440, 456, "goal"), (536, 544, "chance")]}
PHONE_CMD = "python tests/fixtures/eval_phone/build.py && python -m sportscut eval tests/fixtures/eval_phone --json"
PLAYER = "## Theo dõi cầu thủ: xuất video tổng hợp (player)"

def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    spec.loader.exec_module(module := importlib.util.module_from_spec(spec))
    return module
B = _load(PHONE / "build.py", "t055_acc_phone_build")

def test_ac1_builder_reuses_broadcast_helpers_and_case_table():
    assert (B.W, B.H, B.FPS, B.AUDIO_RATE) == (160, 90, 10, 16000)
    assert sorted(B.CASES) == ["pitch_a", "pitch_b"] and all(
        fn.__code__.co_filename.replace("\\", "/").endswith("tests/fixtures/eval/build.py") for fn in (B._band_noise, B._ramp))
    for name, (seed, goals, chances, gust, pans) in CASES.items():
        c = B.CASES[name]
        assert (c["seed"], c["goals"], c["chances"], tuple(c["gust"]), c["pans"]) == (seed, goals, chances, gust, pans)
        assert all(60 <= b - a <= 100 for a, b in zip(pans, pans[1:]))

def test_ac3_labels_oracle_and_committed_files():
    for name, (_, goals, chances, _, _) in CASES.items():
        oracle = sorted([{"start": t - 10.0, "end": t + 6.0, "type": "goal"} for t, _ in goals]
                        + [{"start": t - 4.0, "end": t + 4.0, "type": "chance"} for t, _ in chances], key=lambda x: x["start"])
        assert (got := B.case_labels(name)) == oracle == [{"start": s, "end": e, "type": k} for s, e, k in LABELS[name]]
        assert all(isinstance(x["start"], float) and isinstance(x["end"], float) for x in got)
        assert (PHONE / name / "labels.json").read_text() == json.dumps(got, indent=1) + "\n"
    assert subprocess.run(["git", "ls-files", "*.mp4"], cwd=ROOT, capture_output=True, text=True).stdout == ""

@pytest.mark.parametrize("name", list(CASES))
def test_ac4_picture_band_fence_pans_and_ball(name):
    band = lambda t: B.render_frame(name, t)[:30].astype(int)
    gray = band(1.0).mean(axis=2)
    assert np.any(((gray[:, 1:] >= 200) & (gray[:, :-1] <= 60)) | ((gray[:, :-1] >= 200) & (gray[:, 1:] <= 60)))
    pans = CASES[name][4]
    for a, b in zip([0] + pans, pans + [600]):
        assert all(np.array_equal(band(float(t)), band(a + 0.1)) for t in np.linspace(a + 0.1, b - 0.2, 7)), (name, a)
    for p in pans:
        before, after = band(p - 0.1), band(float(p))
        assert not np.array_equal(before, after) and np.array_equal(after, np.roll(before, 3, axis=1)), (name, p)
    allowed = {(170, 190, 210), (30, 30, 30), (60, 60, 60), (230, 230, 230), (40, 140, 60)}
    for t in (0.0, 33.3, 299.9, 599.9):  # only sky/roof/fence/posts/grass up top: no digits, no box
        frame = B.render_frame(name, t)
        assert frame.shape == (90, 160, 3) and frame.dtype == np.uint8 and {tuple(px) for px in frame[:30].reshape(-1, 3)} <= allowed
    assert all(not np.array_equal(B.render_frame(name, t)[30:], B.render_frame(name, t + 1)[30:]) for t in (3.0, 100.0, 450.5))

def _share(chunk, lo, hi):
    power = np.abs(np.fft.rfft(chunk.astype(np.float64))) ** 2
    freqs = np.fft.rfftfreq(len(chunk), 1 / 16000)
    return power[(freqs >= lo) & (freqs <= hi)].sum() / power.sum()
@pytest.mark.parametrize("name", list(CASES))
def test_ac5_audio_levels_bands_and_whistles(name):
    (_, goals, chances, gust, _), audio = CASES[name], B.audio_track(name)
    assert audio.dtype == np.float32 and audio.shape == (600 * 16000,) and audio.min() >= -1 and audio.max() <= 1 and np.array_equal(audio, B.audio_track(name))
    sec = audio.astype(np.float64).reshape(600, 16000)
    base = np.median(db := 20 * np.log10(np.sqrt((sec ** 2).mean(axis=1))))
    inside = lambda t0, d: [s for s in range(600) if s >= t0 + 0.3 and s + 1 <= t0 + d - 0.3]
    assert all(11.0 <= db[s] - base <= 13.0 for t0, d in goals + chances + [gust] for s in inside(t0, d)), (name, db - base)
    assert all(_share(sec[s], 300, 3000) >= 0.90 for t0, d in goals + chances for s in inside(t0, d)), name
    assert len(inside(*gust)) >= 6 and all(_share(sec[s], 0, 300) >= 0.85 for s in inside(*gust))
    assert all(_share(audio[round((t0 + 40) * 16000):][:16000], 2900, 3100) >= 0.80 for t0, _ in goals), name
    spans = goals + chances + [gust] + [(t0 + 40, 1.0) for t0, _ in goals]
    quiet = [s for s in range(600) if all(s + 1 < a - 15 or s > a + d + 15 for a, d in spans)]
    assert len(quiet) > 100 and all(abs(db[s] - base) <= 1.0 for s in quiet)

def _stub_eval(monkeypatch, root, cases):
    calls = []
    for name, (labels, _) in cases.items():
        (root / name).mkdir(parents=True), (root / name / "video.mp4").touch()
        (root / name / "labels.json").write_text(json.dumps([{"start": s, "end": e, "type": k} for s, e, k in labels]))
    def find(video, *args, **kwargs):
        calls.append((Path(video), args, kwargs))
        return [Segment(s, e, 1.0, "stub", ev) for s, e, ev in cases[Path(video).parent.name][1]]
    monkeypatch.setattr(detect, "find_highlights", find)
    for module, attr in ((scoreboard, "tag_goals"), (incidents, "tag_incidents"), (audio_cues, "tag_saves")):
        monkeypatch.setattr(module, attr, lambda video, segs, *a, **k: segs)
    return calls
# case a: goal segments exactly [t0-10, t0+6]; case b: 12 s windows [t0-6, t0+6] plus 'other' segments around the labels
ORACLE = {"a": ([(110, 126, "goal"), (266, 274, "chance"), (385, 401, "goal")], [(110, 126, "goal"), (385, 401, "goal")]),
          "b": ([(190, 206, "goal"), (440, 456, "goal")], [(194, 206, "goal"), (444, 456, "goal"), (180, 210, "other"), (430, 460, "other")])}

def test_ac6_ac7_coverage_oracle_top_none_and_key_order(monkeypatch, tmp_path):
    calls = _stub_eval(monkeypatch, tmp_path, ORACLE)
    report = evaluate.evaluate_dir(tmp_path)
    assert calls == [(tmp_path / "a" / "video.mp4", (), {"top": None}), (tmp_path / "b" / "video.mp4", (), {"top": None})]
    assert report["goal_coverage"] == 0.5
    assert list(report) == ["f1", "precision", "recall", "event_accuracy", "per_event", "precision_at_5", "goal_coverage", "per_match"]
    assert [list(m) for m in report["per_match"]] == [["match", "labels", "predictions", "f1", "precision", "recall", "event_accuracy", "precision_at_5"]] * 2
    L, G = (lambda s, e, k: evaluate.Label(float(s), float(e), k)), (lambda s, e, ev="goal": Segment(float(s), float(e), 1.0, "x", ev))
    cases = [([G(10, 26)], [L(10, 26, "goal")], 1), ([G(11, 26)], [L(10, 26, "goal")], 0), ([G(0, 50, "other")], [L(10, 26, "goal")], 0),
             ([G(0, 50)], [L(10, 26, "chance"), L(30, 40, "goal")], 1), ([G(0, 50)], [L(1, 9, "goal"), L(30, 40, "goal")], 2), ([], [], 0)]
    assert [evaluate.covered_goals(segs, labels) for segs, labels, _ in cases] == [want for _, _, want in cases]

def test_ac7_goal_coverage_rounding_and_none(monkeypatch, tmp_path):
    _stub_eval(monkeypatch, tmp_path / "x", {"c": ([(10, 20, "goal"), (40, 50, "goal"), (70, 80, "goal")], [(9, 21, "goal")])})
    assert evaluate.evaluate_dir(tmp_path / "x")["goal_coverage"] == 0.3333
    _stub_eval(monkeypatch, tmp_path / "y", {"d": ([(10, 20, "foul"), (40, 50, "chance")], [(0, 60, "goal")])})
    assert evaluate.evaluate_dir(tmp_path / "y")["goal_coverage"] is None

def test_mutations_are_caught_by_the_coverage_oracle(monkeypatch, tmp_path):
    _stub_eval(monkeypatch, tmp_path / "e", ORACLE)
    ignores_event = lambda segs, labels: sum(any(s.start <= l.start and l.end <= s.end for s in segs) for l in labels if l.type == "goal")
    monkeypatch.setattr(evaluate, "covered_goals", ignores_event)
    assert evaluate.evaluate_dir(tmp_path / "e")["goal_coverage"] == 1.0  # oracle expects 0.5, so the mutant is caught
    monkeypatch.undo()
    calls = _stub_eval(monkeypatch, tmp_path / "m", ORACLE)
    assert (source := inspect.getsource(evaluate.evaluate_dir)).count("detect.find_highlights(video, top=None)") == 1
    exec(source.replace("detect.find_highlights(video, top=None)", "detect.find_highlights(video)"), namespace := dict(vars(evaluate)))
    namespace["evaluate_dir"](tmp_path / "m")
    assert [kwargs for _, _, kwargs in calls] == [{}, {}]  # the top=None assertion above would fail on this mutant

def test_ac9_ac10_ac11_phone_eval_matches_readme_and_decisions(require_ffmpeg, tmp_path):
    assert B.build_all(tmp_path) == [tmp_path / "pitch_a" / "video.mp4", tmp_path / "pitch_b" / "video.mp4"]
    run = subprocess.run([sys.executable, "-m", "sportscut", "eval", str(tmp_path), "--json"], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    (line,) = run.stdout.strip().splitlines()
    report = json.loads(line)
    assert [(m["match"], m["labels"]) for m in report["per_match"]] == [("pitch_a", 5), ("pitch_b", 5)]
    assert report["goal_coverage"] in (0.0, 0.25, 0.5, 0.75, 1.0)
    text, heading = (ROOT / "README.md").read_text(encoding="utf-8"), "### Kết quả đo video quay điện thoại (R-010)"
    assert text.count(heading) == 1 and text.index("Kết quả sau T-015") < text.index(heading) < text.index(PLAYER)
    section = text[text.index(heading):text.index(PLAYER)]
    assert all(w in section for w in (PHONE_CMD, "goal_coverage", "top=None"))
    assert (block := section.split("Baseline đo trong T-055:\n\n```json\n", 1)[1].split("\n```", 1)[0]) == line
    decisions = [l for l in (ROOT / "docs/superpowers/DECISIONS.md").read_text(encoding="utf-8").splitlines()
                 if "T-055 (R-010)" in l and "phone eval baseline" in l]
    assert len(decisions) == 1 and decisions[0].endswith(block)
    for spec in ("t-010-add-event-types-to-segments-and", "t-013-tag-goals-from-scoreboard-region-changes",
                 "t-015-tag-red-cards-and-controversial-incidents"):
        last = (SPECS / f"2026-11-23-{spec}-design.md").read_text(encoding="utf-8").rstrip("\n").splitlines()[-1]
        assert last.startswith("Updated by T-055:") and "top=None" in last and "goal_coverage" in last
