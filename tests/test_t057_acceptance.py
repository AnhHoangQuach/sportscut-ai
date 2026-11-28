"""T-057 Tester acceptance tests: ignore an implausible top-band 'scoreboard'."""
import importlib.util, json, subprocess, sys
from pathlib import Path
import numpy as np, pytest
from sportscut import detect
from sportscut.events import scoreboard
from sportscut.events.scoreboard import plausible_board

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "docs" / "superpowers" / "specs"
PLAYER = "## Theo dõi cầu thủ: xuất video tổng hợp (player)"
BOX = (2, 2, 30, 14)
Z = lambda n: np.zeros((n, 30, 160), np.uint8)


def test_ac1_width_limit_is_half_the_band():
    frames = Z(600)
    assert plausible_board(frames, (0, 0, 80, 5), []) is True
    assert plausible_board(frames, (0, 0, 81, 5), []) is False
    assert plausible_board(frames, (80, 3, 80, 2), []) is True  # right half, exactly 80 wide
    assert plausible_board(frames, (0, 7, 160, 1), []) is False  # full-width sky line


@pytest.mark.parametrize("samples, allowed", [(600, 4), (3600, 6), (300, 4), (6000, 10), (2, 4)])
def test_ac2_change_count_limit_is_max_4_or_seconds_over_600(samples, allowed):
    frames = Z(samples)
    times = [float(i) for i in range(allowed + 1)]
    assert plausible_board(frames, BOX, times[:allowed]) is True
    assert plausible_board(frames, BOX, times) is False


def _busy(flip_at):
    """101 samples; the box toggles 0/255 at the listed transitions (1-based sample index)."""
    frames, on = Z(101), False
    for i in range(1, 101):
        on ^= i in flip_at
        if on:
            frames[i, 2:16, 2:32] = 255
    return frames


def test_ac3_busy_rule_boundary_with_spread_out_flips():
    every4 = set(range(4, 101, 4))  # 25 transitions spread across the clip
    assert len(every4) == 25
    assert plausible_board(_busy(every4), BOX, []) is True
    assert plausible_board(_busy(every4 | {1}), BOX, []) is False
    flipping_outside = _busy(set(range(1, 101)))
    flipping_outside[:, 2:16, 2:32] = 0  # change only outside the box: never busy
    flipping_outside[1::2, 20:30, 100:150] = 255
    assert plausible_board(flipping_outside, BOX, []) is True


def test_ac3_fewer_than_two_samples_is_plausible():
    assert plausible_board(Z(1), BOX, []) is True
    assert plausible_board(Z(0), BOX, []) is True


def _patch(monkeypatch, frames, box, changes):
    calls = []
    monkeypatch.setattr(scoreboard, "sample_top_band", lambda v: calls.append("band") or frames)
    monkeypatch.setattr(scoreboard, "find_box", lambda f: calls.append("box") or box)
    monkeypatch.setattr(scoreboard, "score_changes", lambda f, b: calls.append("changes") or changes)
    return calls


@pytest.mark.parametrize("frames, box, changes", [
    (Z(600), (0, 7, 160, 1), []),                 # too wide
    (Z(600), BOX, [10.0, 20.0, 30.0, 40.0, 50.0]),  # too many changes
    (_busy(set(range(1, 101))), BOX, []),           # running clock
])
def test_ac4_implausible_board_means_no_board(monkeypatch, frames, box, changes):
    calls = _patch(monkeypatch, frames, box, changes)
    monkeypatch.setattr(scoreboard, "find_reverts", lambda *a: pytest.fail("find_reverts must not run"))
    assert scoreboard.board_changes("m.mp4") is None
    assert calls == ["band", "box", "changes"]
    assert scoreboard.board_reverts("m.mp4") == []
    assert calls == ["band", "box", "changes"] * 2


def test_ac4_plausible_board_passes_the_same_objects(monkeypatch):
    frames, changes, reverts = Z(600), [100.0, 200.0], [(100.0, 200.0)]
    calls = _patch(monkeypatch, frames, BOX, changes)
    seen = []
    monkeypatch.setattr(scoreboard, "find_reverts", lambda f, b, c: seen.append((f, b, c)) or reverts)
    assert scoreboard.board_changes("m.mp4") is changes
    assert scoreboard.board_reverts("m.mp4") is reverts
    assert seen[0][0] is frames and seen[0][1] is BOX and seen[0][2] is changes
    assert calls == ["band", "box", "changes"] * 2


@pytest.fixture(scope="module")
def phone(require_ffmpeg, tmp_path_factory):
    spec = importlib.util.spec_from_file_location("t057_phone_build", ROOT / "tests/fixtures/eval_phone/build.py")
    spec.loader.exec_module(build := importlib.util.module_from_spec(spec))
    root = tmp_path_factory.mktemp("phone")
    return root, build.build_all(root)


def test_ac6_phone_cases_fall_back_to_the_roar_rule(phone):
    _, videos = phone
    for video in videos:
        assert scoreboard.board_changes(video) is None
        assert scoreboard.board_reverts(video) == []
        goals = [s for s in scoreboard.tag_goals(video, detect.find_highlights(str(video), top=None)) if s.event == "goal"]
        assert goals, video
        assert all(g.event_confidence == 0.4 for g in goals), goals
        assert not any("scoreboard change" in g.reason for g in goals), goals


def test_ac7_ac9_phone_eval_cli_readme_and_decisions(phone):
    root, _ = phone
    run = subprocess.run([sys.executable, "-m", "sportscut", "eval", str(root), "--json"], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    (line,) = run.stdout.strip().splitlines()
    report = json.loads(line)
    goal = report["per_event"]["goal"]
    assert goal["precision"] is not None and goal["precision"] > 0 and goal["recall"] > 0.0, goal
    assert (report["f1"], report["precision"], report["recall"], report["precision_at_5"]) == (0.7692, 0.625, 1.0, 0.8)
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    # T-058 changed the live line (goal_coverage); the historic T-057 block must equal its DECISIONS line
    block = text.split("Kết quả sau T-057:\n\n```json\n", 1)[1].split("\n```", 1)[0]
    marker = "Kết quả sau T-057:\n\n```json\n" + block + "\n```\n"
    assert text.count("Kết quả sau T-057:") == 1 and text.count(marker) == 1
    assert text.index("Baseline đo trong T-055:") < text.index(marker) < text.index(PLAYER)
    hits = [l for l in (ROOT / "docs/superpowers/DECISIONS.md").read_text(encoding="utf-8").splitlines()
            if "T-057 (R-010): phone eval after T-057" in l]
    assert len(hits) == 1 and hits[0].endswith(block) and "phone eval baseline" not in hits[0]


def test_ac9_earlier_readme_blocks_unchanged():
    old = subprocess.run(["git", "show", "fedde1c:README.md"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    new = (ROOT / "README.md").read_text(encoding="utf-8")
    added = new.replace(old.split(PLAYER)[0], "", 1)
    assert new.startswith(old.split(PLAYER)[0]) and new.endswith(PLAYER + old.split(PLAYER, 1)[1])
    assert "Kết quả sau T-057:" in added


def test_ac10_spec_notes():
    def lines(slug):
        return (SPECS / f"2026-11-23-{slug}-design.md").read_text(encoding="utf-8").rstrip("\n").splitlines()
    for slug in ("t-013-tag-goals-from-scoreboard-region-changes", "t-015-tag-red-cards-and-controversial-incidents"):
        got = [l for l in lines(slug) if not l.startswith("Updated by T-058:")]  # T-058 inserts before T-055
        assert got[-1].startswith("Updated by T-055:") and got[-2].startswith("Updated by T-057:"), slug
        assert sum(l.startswith("Updated by T-057:") for l in got) == 1
    t014 = lines("t-014-tag-saves-using-whistle-detection-and")
    assert t014[-1].startswith("Updated by T-057:") and "plausible_board" in t014[-1]
