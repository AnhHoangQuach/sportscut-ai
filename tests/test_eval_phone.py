"""T-055: phone/pitch-side eval fixture, goal_coverage and the top=None eval call."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from sportscut import detect, media
from sportscut.cli import main
from sportscut.evaluate import Label, covered_goals, evaluate_dir
from sportscut.events import audio_cues, incidents, scoreboard
from sportscut.models import Segment

ROOT = Path(__file__).resolve().parents[1]

def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

B = _load(ROOT / "tests/fixtures/eval_phone/build.py", "t055_phone_build")
EXPECTED = {
    "pitch_a": [(46, 54, "chance"), (110, 126, "goal"), (266, 274, "chance"), (385, 401, "goal"), (516, 524, "chance")],
    "pitch_b": [(86, 94, "chance"), (190, 206, "goal"), (326, 334, "chance"), (440, 456, "goal"), (536, 544, "chance")],
}

def test_reuses_broadcast_helpers() -> None:
    assert (B.W, B.H, B.FPS, B.AUDIO_RATE) == (160, 90, 10, 16000)
    for helper in (B._band_noise, B._ramp):
        assert helper.__code__.co_filename.endswith("tests/fixtures/eval/build.py")

def test_case_tables() -> None:
    assert list(B.CASES) == ["pitch_a", "pitch_b"]
    for case in B.CASES.values():
        assert len(case["goals"]) == 2 and all(7 <= d <= 8 for _, d in case["goals"])
        assert len(case["chances"]) == 3 and all(2 <= d <= 3 for _, d in case["chances"])
        assert 8 <= case["gust"][1] <= 10
        assert all(60 <= b - a <= 100 for a, b in zip(case["pans"], case["pans"][1:]))

def test_case_labels_exact_and_committed() -> None:
    for name, expected in EXPECTED.items():
        labels = B.case_labels(name)
        assert labels == [{"start": float(s), "end": float(e), "type": k} for s, e, k in expected]
        assert all(isinstance(item["start"], float) and isinstance(item["end"], float) for item in labels)
        committed = (ROOT / "tests/fixtures/eval_phone" / name / "labels.json").read_text()
        assert committed == json.dumps(labels, indent=1) + "\n"

def test_top_band_static_between_pans_and_shifts_at_pans() -> None:
    allowed = {(170, 190, 210), (30, 30, 30), (60, 60, 60), (230, 230, 230), (40, 140, 60), (255, 255, 255)}
    for name, case in B.CASES.items():
        edges = [0.0, *case["pans"], B.DURATION]
        for a, b in zip(edges, edges[1:]):
            bands = [B.render_frame(name, t)[:30] for t in np.linspace(a, b - 0.1, 6)]
            assert all(np.array_equal(bands[0], band) for band in bands)
        for p in case["pans"]:
            before, after = B.render_frame(name, p - 0.1)[:30], B.render_frame(name, p)[:30]
            assert np.array_equal(after, np.roll(before, 3, axis=1)) and not np.array_equal(after, before)
        for t in (0.0, 33.3, 250.0):
            frame = B.render_frame(name, t)
            assert frame.shape == (B.H, B.W, 3) and frame.dtype == np.uint8
            bright, dark = frame[:30].min(axis=2) >= 200, frame[:30].max(axis=2) <= 60
            assert (bright[:, 1:] & dark[:, :-1]).any() or (bright[:, :-1] & dark[:, 1:]).any()
            assert not np.array_equal(frame[30:], B.render_frame(name, t + 1)[30:])
            assert {tuple(int(v) for v in px) for px in frame.reshape(-1, 3)} <= allowed

def _band_share(chunk: np.ndarray, low: float, high: float) -> float:
    power = np.abs(np.fft.rfft(chunk.astype(np.float64))) ** 2
    freqs = np.fft.rfftfreq(len(chunk), 1 / B.AUDIO_RATE)
    return power[(freqs >= low) & (freqs <= high)].sum() / power.sum()

def test_audio_levels_and_bands() -> None:
    rate = B.AUDIO_RATE
    for name, case in B.CASES.items():
        audio = B.audio_track(name)
        assert audio.dtype == np.float32 and len(audio) == round(B.DURATION * rate)
        assert audio.min() >= -1 and audio.max() <= 1 and np.array_equal(audio, B.audio_track(name))
        seconds = audio.astype(np.float64).reshape(-1, rate)
        db = 10 * np.log10(np.mean(seconds ** 2, axis=1))
        base = np.median(db)
        events = [*case["goals"], *case["chances"], case["gust"]]
        spans = events + [(t0 + 40, 1.0) for t0, _ in case["goals"]]
        for t0, d in events:
            inside = range(int(np.ceil(t0 + 0.3)), int(np.floor(t0 + d - 0.3)))
            assert len(inside) >= 1 or d < 3.6  # a 2-3 s shout may hold no whole plateau second
            assert all(11.0 <= db[s] - base <= 13.0 for s in inside), (name, t0)
        quiet = [s for s in range(len(db)) if all(s + 1 < t0 - 15 or s > t0 + d + 15 for t0, d in spans)]
        assert len(quiet) > 100 and all(abs(db[s] - base) <= 1.0 for s in quiet)
        for t0, _ in case["goals"]:
            assert _band_share(seconds[int(t0) + 2], 300, 3000) >= 0.9
            assert _band_share(audio[round((t0 + 40) * rate):round((t0 + 41) * rate)], 2900, 3100) >= 0.8
        assert _band_share(seconds[int(case["gust"][0]) + 2], 0, 300) >= 0.85

@pytest.fixture(scope="module")
def phone_set(require_ffmpeg, tmp_path_factory):
    out = tmp_path_factory.mktemp("eval_phone")
    return out, B.build_all(out)

def test_build_all_outputs_and_idempotence(phone_set) -> None:
    out, videos = phone_set
    assert videos == [out / "pitch_a" / "video.mp4", out / "pitch_b" / "video.mp4"]
    for video in videos:
        assert abs(media.probe_duration(video) - 600) <= 0.2
        assert media.probe_size(video) == (160, 90) and media.has_audio(video)
        rate = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                               "stream=r_frame_rate", "-of", "csv=p=0", str(video)],
                              capture_output=True, text=True, check=True).stdout.strip()
        assert rate == "10/1"
    mtimes = [v.stat().st_mtime_ns for v in videos]
    assert B.build_all(out) == videos and [v.stat().st_mtime_ns for v in videos] == mtimes
    B.build_all(out, force=True)
    assert all(v.stat().st_mtime_ns != m for v, m in zip(videos, mtimes))
    assert subprocess.run([sys.executable, str(ROOT / "tests/fixtures/eval_phone/build.py")], cwd=ROOT).returncode == 0

def seg(start, end, event="other"):
    return Segment(float(start), float(end), 1.0, "test", event)

def test_covered_goals_rules() -> None:
    goal, other = Label(10, 26, "goal"), Label(40, 48, "goal")
    assert covered_goals([seg(10, 26, "goal")], [goal]) == 1
    assert covered_goals([seg(11, 26, "goal")], [goal]) == 0
    assert covered_goals([seg(0, 60, "other")], [goal]) == 0
    assert covered_goals([seg(0, 60, "goal")], [Label(10, 20, "chance")]) == 0
    assert covered_goals([seg(0, 60, "goal")], [goal, other, Label(50, 55, "chance")]) == 2

def _fake_eval(tmp_path, monkeypatch, cases, segments_for):
    calls = []
    for name, labels in cases.items():
        (tmp_path / name).mkdir()
        (tmp_path / name / "labels.json").write_text(json.dumps(labels))
        (tmp_path / name / "video.mp4").touch()
    monkeypatch.setattr(detect, "find_highlights",
                        lambda video, *args, **kw: calls.append((video, args, kw)) or segments_for(video))
    for module, name in ((scoreboard, "tag_goals"), (incidents, "tag_incidents"), (audio_cues, "tag_saves")):
        monkeypatch.setattr(module, name, lambda video, segments, **kw: list(segments))
    return evaluate_dir(tmp_path), calls

def test_evaluate_dir_calls_top_none_and_pools_coverage(tmp_path: Path, monkeypatch) -> None:
    cases = {"a": [{"start": 10, "end": 26, "type": "goal"}], "b": [{"start": 50, "end": 66, "type": "goal"}]}
    spans = {"a": seg(10, 26, "goal"), "b": seg(54, 66, "goal")}
    report, calls = _fake_eval(tmp_path, monkeypatch, cases, lambda video: [spans[Path(video).parent.name]])
    assert calls == [(tmp_path / n / "video.mp4", (), {"top": None}) for n in ("a", "b")]
    assert report["goal_coverage"] == 0.5
    assert list(report)[-3:] == ["precision_at_5", "goal_coverage", "per_match"]
    assert list(report["per_match"][0]) == ["match", "labels", "predictions", "f1", "precision",
                                            "recall", "event_accuracy", "precision_at_5"]

def test_evaluate_dir_goal_coverage_none_without_goal_labels(tmp_path: Path, monkeypatch) -> None:
    cases = {"a": [{"start": 2, "end": 3, "type": "foul"}], "b": [{"start": 5, "end": 9, "type": "chance"}]}
    report, _ = _fake_eval(tmp_path, monkeypatch, cases, lambda video: [seg(0, 20, "goal")])
    assert report["goal_coverage"] is None

def test_broadcast_eval_unchanged(require_ffmpeg, tmp_path: Path) -> None:
    _load(ROOT / "tests/fixtures/eval/build.py", "t055_broadcast_build").build_all(tmp_path)
    after = (ROOT / "README.md").read_text().split("Kết quả sau T-015", 1)[1]
    expected = json.loads(after.split("```json\n", 1)[1].split("\n```", 1)[0])
    report = evaluate_dir(tmp_path)
    for key in ("f1", "precision", "recall", "event_accuracy", "per_event", "precision_at_5"):
        assert report[key] == expected[key], key

def test_phone_eval_smoke(phone_set, capsys) -> None:
    assert main(["eval", str(phone_set[0]), "--json"]) == 0
    (line,) = capsys.readouterr().out.splitlines()  # exactly one JSON line
    report = json.loads(line)
    assert [m["match"] for m in report["per_match"]] == ["pitch_a", "pitch_b"]
    assert [m["labels"] for m in report["per_match"]] == [5, 5]
    assert report["goal_coverage"] in {0.0, 0.25, 0.5, 0.75, 1.0}
