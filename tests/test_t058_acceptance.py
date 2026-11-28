"""T-058 Tester acceptance tests: one goal clip from build-up to celebration (shape_goals)."""
import copy, importlib.util, json, subprocess, sys
from pathlib import Path
import numpy as np, pytest
from sportscut import detect
from sportscut.evaluate import evaluate_dir
from sportscut.events import scoreboard
from sportscut.models import Segment as S

ROOT = Path(__file__).resolve().parents[1]
PLAYER, PHONE_H = "## Theo dõi cầu thủ: xuất video tổng hợp (player)", "### Kết quả đo video quay điện thoại (R-010)"

def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    spec.loader.exec_module(module := importlib.util.module_from_spec(spec))
    return module

def res(*runs, n=200, level=10.0):
    r = np.zeros(n)
    for a, b in runs: r[a:b] = level
    return r

shape = lambda segments, residual, duration=200, **kw: scoreboard.shape_goals(segments, residual, duration, **kw)
span = lambda seg: (seg.start, seg.end)

def _eval_line(path):
    run = subprocess.run([sys.executable, "-m", "sportscut", "eval", str(path), "--json"], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    (line,) = run.stdout.strip().splitlines()  # exactly one JSON line
    return line

def test_ac1_reshape_roar_goal_to_onset_window():
    for conf in (0.4, 0.9):
        assert shape([S(36, 48, 5.0, "r", "goal", conf)], res((40, 48))) == [S(28.0, 50.0, 5.0, "r", "goal", conf)]
    assert shape([S(70, 82, 2.5, "q", "goal", 0.4)], res((73, 81))) == [S(61.0, 83.0, 2.5, "q", "goal", 0.4)]
    # mutation oracle: peak 5 s after the onset; a peak-anchored window would start at 93
    r = res((100, 110), level=8.0)
    r[105] = 20.0
    assert span(shape([S(98, 110, 2.0, "g", "goal", 0.4)], r)[0]) == (88.0, 110.0)

def test_ac2_ac3_clamp_ratio_and_media_bounds():
    g, r = S(36, 48, 5.0, "r", "goal", 0.4), res((40, 48))
    assert span(shape([g], r, max_len=11)[0]) == (34.0, 45.0)
    out = shape([g], r, min_len=30, max_len=30)[0]
    assert span(out) == (pytest.approx(40 - 30 * 12 / 22), pytest.approx(40 + 30 * 10 / 22))
    out = shape([g], r, min_len=25)[0]  # min_len > 22 widens with the default max_len
    assert span(out) == (pytest.approx(40 - 25 * 12 / 22), pytest.approx(40 + 25 * 10 / 22))
    assert span(shape([S(1, 13, 5, "r", "goal", 0.4)], res((5, 13)))[0]) == (0.0, 22.0)
    assert span(shape([S(48, 58, 5, "r", "goal", 0.4)], res((52, 58), n=60), 60)[0]) == (38.0, 60.0)

def test_ac4_not_reshaped():
    r, board = res((40, 48)), S(25, 55, 3.0, "board", "goal", 0.6)
    assert shape([board], r) == [board]
    for residual in (np.zeros(200), res((40, 45))):
        assert shape([S(36, 48, 5.0, "r", "goal", 0.4)], residual) == [S(36, 48, 5.0, "r", "goal", 0.4)]
    for seg in (S(36, 48, 5.0, "o"), S(36, 48, 5.0, "s", "save", 0.6)):
        assert shape([seg], r) == [seg]

def test_ac5_merge_overlapping_goals_and_chain():
    r = res((40, 48), (55, 62))
    a, b = S(36, 48, 5, "a", "goal", 0.4), S(51, 63, 7, "b", "goal", 0.9)
    assert shape([a, b], r) == shape([b, a], r) == [S(28.0, 65.0, 7, "b", "goal", 0.9)]
    g, touching = S(36, 48, 5.0, "r", "goal", 0.4), S(50, 80, 3.0, "board", "goal", 0.6)
    assert shape([g, S(45, 75, 3.0, "board", "goal", 0.6)], res((40, 48))) == [S(28.0, 75.0, 5.0, "r", "goal", 0.6)]
    assert shape([g, touching], res((40, 48))) == [S(28.0, 50.0, 5.0, "r", "goal", 0.4), touching]
    assert shape([S(36, 48, None, "n", "goal", 0.9), S(51, 63, 1.0, "s", "goal", 0.4)], r) == [S(28.0, 65.0, 1.0, "s", "goal", 0.9)]
    # three-way chain; an 'other' overlapping only the merged C part is dropped (AC6)
    r = res((40, 47), (60, 67), (80, 87))  # windows [28,50] [48,70] [68,90]: only neighbours overlap
    goals = [S(36, 48, 1.0, "a", "goal", 0.4), S(56, 68, 9.0, "b", "goal", 0.4), S(76, 88, 4.0, "c", "goal", 0.9)]
    out = shape(goals + [S(88, 95, 20.0, "late"), S(90, 100, 1.0, "touch")], r)
    assert out == [S(28.0, 90.0, 9.0, "b", "goal", 0.9), S(90, 100, 1.0, "touch")]

def test_ac6_drop_keep_sort_and_no_mutation():
    g, far, touch = S(36, 48, 5.0, "r", "goal", 0.4), S(70, 82, 4, "y"), S(50, 62, 4, "x")
    inp = [far, S(45, 57, 9, "o"), touch, g, S(20, 30, 3, "s", "save", 0.6)]
    before = copy.deepcopy(inp)
    out = shape(inp, res((40, 48)))
    assert out == [S(28.0, 50.0, 5.0, "r", "goal", 0.4), touch, far]
    assert inp == before and out is not inp

def test_ac7_roar_unchanged_and_tag_goals_calls_shape_goals(monkeypatch):
    assert scoreboard.roar(res((40, 48)), 36, 48) == (40.5, 8) and scoreboard.roar(np.zeros(50), 10, 20) == (10.5, 0)
    resid, tagged, calls = np.zeros(30), [S(1, 12, 1.0, "m", "goal", 0.4)], []
    for name, fake in (("probe_duration", lambda v: 123.0), ("extract_audio", lambda v: "audio"),
                       ("loudness_residual", lambda a: resid), ("board_changes", lambda v: None),
                       ("match_goals", lambda *a: tagged), ("shape_goals", lambda *a: calls.append(a) or ["sentinel"])):
        monkeypatch.setattr(scoreboard, name, fake)
    assert scoreboard.tag_goals("v.mp4", [], 11, 29) == ["sentinel"]
    assert len(calls) == 1 and calls[0][0] is tagged and calls[0][1] is resid and calls[0][2:] == (123.0, 11, 29)

def _no_goal_overlap(segments):
    goals = sorted((s for s in segments if s.event == "goal"), key=span)
    return all(a.end <= b.start for a, b in zip(goals, goals[1:]))

@pytest.fixture(scope="module")
def broadcast(require_ffmpeg, tmp_path_factory):
    out = tmp_path_factory.mktemp("t058_broadcast")
    _load(ROOT / "tests/fixtures/eval/build.py", "t058_broadcast_build").build_all(out)
    return out

def test_ac8_broadcast_goal_windows_and_eval(broadcast):
    for case in sorted(p for p in broadcast.iterdir() if p.is_dir()):
        labels = [l for l in json.loads((case / "labels.json").read_text()) if l["type"] == "goal"]
        out = scoreboard.tag_goals(case / "video.mp4", detect.find_highlights(case / "video.mp4", top=None))
        goals = [s for s in out if s.event == "goal"]
        assert len(goals) == len(labels) and _no_goal_overlap(out), case.name
        for label in labels:
            (g,) = [s for s in goals if s.start <= label["start"] and label["end"] <= s.end]
            assert g.event_confidence == 0.9 and g.end - g.start == 22.0, (case.name, g)
    after = (ROOT / "README.md").read_text(encoding="utf-8").split("Kết quả sau T-015", 1)[1]
    expected = json.loads(after.split("```json\n", 1)[1].split("\n```", 1)[0])
    report = evaluate_dir(broadcast)
    for key in ("f1", "precision", "recall", "event_accuracy", "per_event", "precision_at_5"):
        assert report[key] == expected[key], key
    assert all(report["per_event"]["goal"][k] == 1.0 for k in ("precision", "recall", "f1"))
    assert report["goal_coverage"] == 1.0

@pytest.fixture(scope="module")
def phone(require_ffmpeg, tmp_path_factory):
    out = tmp_path_factory.mktemp("t058_phone")
    _load(ROOT / "tests/fixtures/eval_phone/build.py", "t058_phone_build").build_all(out)
    return out, _eval_line(out)

def test_ac9_phone_goal_coverage_and_no_overlap(phone):
    out, line = phone
    report = json.loads(line)
    assert report["goal_coverage"] >= 0.9, line
    for key, value in (("f1", 0.7692), ("precision", 0.625), ("recall", 1.0), ("precision_at_5", 0.8)):
        assert report[key] == pytest.approx(value, abs=5e-5), key
    for name in ("pitch_a", "pitch_b"):
        video = out / name / "video.mp4"
        assert _no_goal_overlap(scoreboard.tag_goals(video, detect.find_highlights(video, top=None))), name

def test_ac10_readme_and_decisions_hold_live_eval_lines(phone, broadcast):
    line, text = phone[1], (ROOT / "README.md").read_text(encoding="utf-8")
    section, marker = text[text.index(PHONE_H):text.index(PLAYER)], "Kết quả sau T-058:\n\n```json\n"
    assert text.count("Kết quả sau T-058:") == 1 and section.count(marker) == 1
    head, tail = section.split(marker)
    assert tail.split("\n```", 1)[0] == line
    assert "Baseline đo trong T-055:" in head and "Kết quả sau T-0" not in tail  # newest block, after the earlier ones
    decisions = (ROOT / "docs/superpowers/DECISIONS.md").read_text(encoding="utf-8").splitlines()
    phone_lines = [l for l in decisions if "T-058 (R-010): phone eval after T-058" in l]
    assert len(phone_lines) == 1 and phone_lines[0].endswith(line)
    bc = [l for l in decisions if "T-058 (R-010): broadcast eval after T-058" in l]
    assert len(bc) == 1 and bc[0].endswith(_eval_line(broadcast))
    # AC11: T-013 spec line order
    spec = ROOT / "docs/superpowers/specs/2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md"
    lines = spec.read_text(encoding="utf-8").rstrip("\n").splitlines()
    assert lines[-1].startswith("Updated by T-055:") and lines[-2].startswith("Updated by T-058:")
    assert sum(l.startswith("Updated by T-058:") for l in lines) == 1
