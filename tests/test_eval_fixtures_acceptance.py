from __future__ import annotations

import ast
from collections import Counter
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
BUILD_PATH = ROOT / "tests" / "fixtures" / "eval" / "build.py"
EXPECTED_MATCHES = {
    "cards": {
        "duration": 180.0,
        "events": [
            ("red_card", 20),
            ("save", 50),
            ("controversy", 75),
            ("swell", 130),
            ("red_card", 155),
        ],
    },
    "controversy": {
        "duration": 180.0,
        "events": [
            ("controversy", 20),
            ("goal", 75, "away"),
            ("chant", 105),
            ("controversy", 130),
        ],
    },
    "goals_saves": {
        "duration": 180.0,
        "events": [
            ("goal", 20, "home"),
            ("save", 55),
            ("swell", 75),
            ("goal", 100, "away"),
            ("save", 140),
            ("chant", 160),
        ],
    },
    "mixed": {
        "duration": 180.0,
        "events": [
            ("save", 15),
            ("red_card", 40),
            ("goal", 70, "home"),
            ("swell", 105),
            ("goal", 125, "home"),
            ("save", 160),
        ],
    },
}
REPORT_KEYS = {
    "f1",
    "precision",
    "recall",
    "event_accuracy",
    "per_event",
    "precision_at_5",
    "per_match",
}
SCORED_EVENTS = ("goal", "save", "red_card", "controversy")


def _load_build():
    spec = importlib.util.spec_from_file_location("tester_eval_build", BUILD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load_build()
_audio_cache: dict[str, np.ndarray] = {}


def _events(name: str, kind: str):
    return [event for event in build.MATCHES[name]["events"] if event[0] == kind]


def _audio(name: str) -> np.ndarray:
    if name not in _audio_cache:
        _audio_cache[name] = build.audio_track(name)
    return _audio_cache[name]


def _db(value: float | np.ndarray) -> float | np.ndarray:
    return 20 * np.log10(np.maximum(value, 1e-12))


def _levels(signal: np.ndarray) -> np.ndarray:
    windows = signal.reshape(-1, build.AUDIO_RATE // 10)
    return _db(np.sqrt(np.mean(windows.astype(np.float64) ** 2, axis=1)))


def _band_share(signal: np.ndarray, low: float, high: float) -> float:
    spectrum = np.abs(np.fft.rfft(signal.astype(np.float64))) ** 2
    frequencies = np.fft.rfftfreq(len(signal), 1 / build.AUDIO_RATE)
    total = float(spectrum.sum())
    return float(spectrum[(frequencies >= low) & (frequencies <= high)].sum() / total)


def _inside(t: float, spans: list[tuple[float, float]]) -> bool:
    return any(start <= t < end for start, end in spans)


def _picture_spans(name: str):
    frozen = []
    replay = []
    red = []
    for event in build.MATCHES[name]["events"]:
        kind, t0 = event[:2]
        if kind == "red_card":
            frozen.append((t0, t0 + 12))
            red.append((t0 + 4, t0 + 8))
        elif kind == "controversy":
            frozen.append((t0, t0 + 36))
            replay.append((t0 + 20, t0 + 26))
        elif kind == "goal":
            replay.append((t0 + 13, t0 + 18))
    return frozen, replay, red


def _score_crop(frame: np.ndarray) -> np.ndarray:
    x, y, width, height = build.SCOREBOARD
    return frame[y : y + height, x : x + width]


def _without_scoreboard(frame: np.ndarray) -> np.ndarray:
    result = frame.copy()
    x, y, width, height = build.SCOREBOARD
    result[y : y + height, x : x + width] = 0
    return result


def _red_share(frame: np.ndarray) -> float:
    red = (frame[:, :, 0] >= 150) & (frame[:, :, 1] <= 60) & (frame[:, :, 2] <= 60)
    return float(red.mean())


def _decode_frame(video: Path, timestamp: float) -> np.ndarray:
    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(video),
            "-ss",
            f"{timestamp:.1f}",
            "-frames:v",
            "1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(build.H, build.W, 3)


@pytest.fixture(scope="module")
def acceptance_eval_set(tmp_path_factory, require_ffmpeg):
    output = tmp_path_factory.mktemp("tester-event-eval")
    paths = build.build_all(output)
    return output, paths


def test_acceptance_public_generator_contract():
    assert BUILD_PATH.is_file()
    imported = set()
    for node in ast.walk(ast.parse(BUILD_PATH.read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "sportscut" not in imported
    assert imported <= set(sys.stdlib_module_names) | {"numpy"}
    assert build.HERE == BUILD_PATH.parent
    assert (build.W, build.H, build.FPS, build.AUDIO_RATE) == (160, 90, 10, 16000)
    assert build.SCOREBOARD == (2, 2, 30, 14)
    assert build.MATCHES == EXPECTED_MATCHES
    assert build.SEEDS == {name: 1101 + index for index, name in enumerate(EXPECTED_MATCHES)}
    assert build.DISTRACTORS == ("swell", "chant")
    for name in (
        "match_labels",
        "footprints",
        "score_at",
        "play_clock",
        "render_frame",
        "audio_track",
        "build_all",
    ):
        assert callable(getattr(build, name))


def test_acceptance_committed_label_oracle_and_untracked_media():
    per_match = {"cards": 4, "controversy": 3, "goals_saves": 4, "mixed": 5}
    totals = Counter()
    for name, expected_count in per_match.items():
        labels = build.match_labels(name)
        expected = json.dumps(labels, indent=1) + "\n"
        assert (BUILD_PATH.parent / name / "labels.json").read_text() == expected
        assert len(labels) == expected_count
        assert [label["start"] for label in labels] == sorted(label["start"] for label in labels)
        for label in labels:
            assert set(label) == {"start", "end", "type"}
            assert label["type"] in SCORED_EVENTS
            totals[label["type"]] += 1
    assert totals == Counter(goal=5, save=5, red_card=3, controversy=3)
    distractors = [
        event
        for match in build.MATCHES.values()
        for event in match["events"]
        if event[0] in build.DISTRACTORS
    ]
    assert len(distractors) == 5
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "tests/fixtures/eval"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("git is required to check tracked fixture files")
    assert not any(path.endswith((".mp4", ".mkv", ".mov", ".wav")) for path in tracked)


def test_acceptance_footprints_are_bounded_and_separated():
    for name, match in build.MATCHES.items():
        assert match["duration"] == 180.0
        footprints = build.footprints(name)
        assert footprints == sorted(footprints, key=lambda item: item[1])
        assert len(footprints) == len(match["events"])
        assert all(10 <= start < end <= 170 for _, start, end in footprints)
        assert all(right[1] - left[2] >= 12 for left, right in zip(footprints, footprints[1:]))


def test_acceptance_scoreboard_changes_once_per_goal():
    for name, match in build.MATCHES.items():
        crops = [_score_crop(build.render_frame(name, k / 10)) for k in range(1800)]
        changes = [k / 10 for k in range(1, 1800) if not np.array_equal(crops[k], crops[k - 1])]
        assert changes == [event[1] + 1.0 for event in match["events"] if event[0] == "goal"]
        score = [0, 0]
        assert build.score_at(name, 0.0) == (0, 0)
        for kind, t0, *team in match["events"]:
            if kind != "goal":
                continue
            assert build.score_at(name, t0 + 0.9) == tuple(score)
            score[0 if team[0] == "home" else 1] += 1
            assert build.score_at(name, t0 + 1.0) == tuple(score)


def test_acceptance_red_closeup_exists_only_in_red_card_windows():
    for name in build.MATCHES:
        red_windows = [(event[1] + 4, event[1] + 8) for event in _events(name, "red_card")]
        for k in range(1800):
            t = k / 10
            share = _red_share(build.render_frame(name, t))
            if _inside(t, red_windows):
                assert share >= 0.6, (name, t, share)
            else:
                assert share <= 0.05, (name, t, share)


def test_acceptance_replay_motion_and_freeze_geometry():
    for name in build.MATCHES:
        for _, t0, *_ in _events(name, "goal"):
            for k in range(50):
                replay = _without_scoreboard(build.render_frame(name, t0 + 13 + k / 10))
                source = _without_scoreboard(build.render_frame(name, t0 - 3 + k / 10))
                assert np.array_equal(replay, source), (name, t0, k)
        for _, t0, *_ in _events(name, "controversy"):
            for k in range(60):
                replay = build.render_frame(name, t0 + 20 + k / 10)
                source = build.render_frame(name, t0 - 6 + k / 10)
                assert np.array_equal(replay, source), (name, t0, k)

        frozen, replay, red = _picture_spans(name)
        eligible = []
        for k in range(10, 1800):
            t = k / 10
            previous = (k - 10) / 10
            excluded = frozen + replay + red
            if not _inside(t, excluded) and not _inside(previous, excluded):
                eligible.append(not np.array_equal(build.render_frame(name, t), build.render_frame(name, previous)))
        assert sum(eligible) / len(eligible) >= 0.95

        for start, end in frozen:
            for k in range(int(start * 10) + 1, int(end * 10)):
                t, previous = k / 10, (k - 1) / 10
                if _inside(t, replay + red) or _inside(previous, replay + red):
                    continue
                assert np.array_equal(build.render_frame(name, t), build.render_frame(name, previous))


def test_acceptance_audio_levels_and_rise_times():
    murmur_db = float(_db(0.02))
    for name in build.MATCHES:
        signal = _audio(name)
        assert signal.dtype == np.float32
        assert len(signal) == 180 * build.AUDIO_RATE
        levels = _levels(signal)
        for _, t0, *_ in _events(name, "goal"):
            start, end = int((t0 - 1) * 10), int((t0 + 11) * 10)
            above = levels[start:end] >= murmur_db + 12
            runs = []
            run_start = None
            for index, value in enumerate(above):
                if value and run_start is None:
                    run_start = index
                if run_start is not None and (not value or index == len(above) - 1):
                    stop = index + 1 if value and index == len(above) - 1 else index
                    runs.append((run_start, stop))
                    run_start = None
            assert any(stop - begin >= 80 and begin <= 15 for begin, stop in runs), (name, t0, runs)

        for _, t0, *_ in _events(name, "save"):
            footprint = levels[int((t0 - 4) * 10) : int((t0 + 4) * 10)]
            assert 20 <= int(np.count_nonzero(footprint >= murmur_db + 12)) <= 30
            region = levels[int((t0 - 1) * 10) : int((t0 + 4) * 10)]
            peak = float(region.max())
            first_rise = int(np.flatnonzero(region >= murmur_db + 3)[0])
            first_peak = int(np.flatnonzero(region >= peak - 2)[0])
            assert first_peak - first_rise <= 2

        for _, t0, *_ in _events(name, "red_card"):
            quiet = levels[int((t0 + 1.5) * 10) : int((t0 + 11.5) * 10)]
            assert np.all(quiet <= murmur_db - 6)

        for kind, t0, *_ in [event for event in build.MATCHES[name]["events"] if event[0] in build.DISTRACTORS]:
            footprint_end = t0 + (5 if kind == "swell" else 6)
            one_second = []
            for k in range(int(t0 * 10), int((footprint_end - 1) * 10) + 1):
                window = signal[k * 1600 : k * 1600 + build.AUDIO_RATE]
                one_second.append(float(_db(np.sqrt(np.mean(window.astype(np.float64) ** 2)))))
            assert murmur_db + 6 <= max(one_second) <= murmur_db + 16
            region = levels[int((t0 - 1) * 10) : int(footprint_end * 10)]
            peak = float(region.max())
            first_rise = int(np.flatnonzero(region >= murmur_db + 3)[0])
            first_peak = int(np.flatnonzero(region >= peak - 2)[0])
            assert first_peak - first_rise >= 10, (name, kind, t0, first_peak - first_rise)


def test_acceptance_audio_whistle_and_boo_spectra():
    for name in build.MATCHES:
        signal = _audio(name)
        whistle_spans = [(event[1], event[1] + 1) for event in build.MATCHES[name]["events"] if event[0] in ("red_card", "controversy")]
        boo_spans = [(event[1] + 3, event[1] + 33) for event in _events(name, "controversy")]
        for start, _ in whistle_spans:
            sample = signal[int((start + 0.1) * build.AUDIO_RATE) : int((start + 0.9) * build.AUDIO_RATE)]
            assert _band_share(sample, 2800, 3200) >= 0.8
        for second in range(180):
            sample = signal[second * build.AUDIO_RATE : (second + 1) * build.AUDIO_RATE]
            if not any(second < end and second + 1 > start for start, end in whistle_spans):
                assert _band_share(sample, 2800, 3200) <= 0.05
            if not any(second < end and second + 1 > start for start, end in boo_spans):
                assert _band_share(sample, 0, 220) <= 0.2
        for _, t0, *_ in _events(name, "controversy"):
            for second in range(t0 + 4, t0 + 32):
                sample = signal[second * build.AUDIO_RATE : (second + 1) * build.AUDIO_RATE]
                assert _band_share(sample, 0, 220) >= 0.6


def test_acceptance_encoded_streams_and_cues(acceptance_eval_set):
    from sportscut.media import extract_audio

    output, paths = acceptance_eval_set
    assert paths == [output / name / "video.mp4" for name in EXPECTED_MATCHES]
    for name, video in zip(EXPECTED_MATCHES, paths):
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video)],
            check=True,
            capture_output=True,
            text=True,
        )
        metadata = json.loads(probe.stdout)
        video_stream = next(stream for stream in metadata["streams"] if stream["codec_type"] == "video")
        audio_stream = next(stream for stream in metadata["streams"] if stream["codec_type"] == "audio")
        assert (video_stream["codec_name"], video_stream["width"], video_stream["height"]) == ("mpeg4", 160, 90)
        assert video_stream["r_frame_rate"] == "10/1"
        assert audio_stream["codec_name"] == "aac"
        assert (int(audio_stream["channels"]), int(audio_stream["sample_rate"])) == (1, 16000)
        assert float(metadata["format"]["duration"]) == pytest.approx(180, abs=0.2)
        assert not (video.parent / ".video.tmp.mp4").exists()

        for _, t0, *_ in _events(name, "goal"):
            after = _score_crop(_decode_frame(video, t0 + 3)).astype(np.float32)
            expected = _score_crop(build.render_frame(name, t0 + 3)).astype(np.float32)
            before = _score_crop(_decode_frame(video, t0 - 1)).astype(np.float32)
            assert np.mean(np.abs(after - expected)) <= 20
            assert np.mean(np.abs(after - before)) >= 10
        for _, t0, *_ in _events(name, "red_card"):
            assert _red_share(_decode_frame(video, t0 + 6)) >= 0.6

        decoded_audio = extract_audio(video)
        for event in build.MATCHES[name]["events"]:
            if event[0] not in ("red_card", "controversy"):
                continue
            t0 = event[1]
            whistle = decoded_audio[int((t0 + 0.1) * 16000) : int((t0 + 0.9) * 16000)]
            assert _band_share(whistle, 2800, 3200) >= 0.5


def test_acceptance_build_reuse_force_and_label_recovery(acceptance_eval_set):
    output, paths = acceptance_eval_set
    initial_mtimes = {path: path.stat().st_mtime_ns for path in paths}
    labels = {name: (output / name / "labels.json").read_bytes() for name in EXPECTED_MATCHES}
    assert build.build_all(output) == paths
    assert {path: path.stat().st_mtime_ns for path in paths} == initial_mtimes
    assert {name: (output / name / "labels.json").read_bytes() for name in EXPECTED_MATCHES} == labels

    build.build_all(output, force=True)
    forced_mtimes = {path: path.stat().st_mtime_ns for path in paths}
    assert all(forced_mtimes[path] > initial_mtimes[path] for path in paths)

    target = output / "cards" / "labels.json"
    target.unlink()
    before_missing = paths[0].stat().st_mtime_ns
    build.build_all(output)
    assert target.read_bytes() == labels["cards"]
    assert paths[0].stat().st_mtime_ns > before_missing

    target.write_text("[]\n")
    before_edited = paths[0].stat().st_mtime_ns
    build.build_all(output)
    assert target.read_bytes() == labels["cards"]
    assert paths[0].stat().st_mtime_ns > before_edited


@pytest.mark.parametrize("reported_event", ["oracle", "other"])
def test_acceptance_eval_oracles(acceptance_eval_set, monkeypatch, reported_event):
    from sportscut import detect
    from sportscut.evaluate import evaluate_dir
    from sportscut.models import Segment

    output, _ = acceptance_eval_set

    def fake_find_highlights(video):
        labels = json.loads((Path(video).parent / "labels.json").read_text())
        return [
            Segment(
                start=label["start"],
                end=label["end"],
                score=1.0,
                reason="tester oracle",
                event=label["type"] if reported_event == "oracle" else "other",
            )
            for label in labels
        ]

    monkeypatch.setattr(detect, "find_highlights", fake_find_highlights)
    report = evaluate_dir(output)
    assert (report["f1"], report["precision"], report["recall"]) == (1.0, 1.0, 1.0)
    expected_accuracy = 1.0 if reported_event == "oracle" else 0.0
    assert report["event_accuracy"] == expected_accuracy
    assert [row["match"] for row in report["per_match"]] == list(EXPECTED_MATCHES)
    assert [row["labels"] for row in report["per_match"]] == [4, 3, 4, 5]
    for kind in SCORED_EVENTS:
        expected_recall = 1.0 if reported_event == "oracle" else 0.0
        assert report["per_event"][kind]["recall"] == expected_recall


def test_acceptance_real_eval_cli_json(acceptance_eval_set, capsys):
    from sportscut.cli import main

    output, _ = acceptance_eval_set
    assert main(["eval", str(output), "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    report = json.loads(captured.out)
    assert set(report) == REPORT_KEYS
    assert [row["match"] for row in report["per_match"]] == list(EXPECTED_MATCHES)
    assert sum(row["predictions"] for row in report["per_match"]) > 0


def test_acceptance_readme_baseline_contract():
    readme = (ROOT / "README.md").read_text()
    heading = "## Highlight theo sự kiện: đo độ chính xác (eval)"
    command = "python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json"
    marker = "Baseline đo trong T-011"
    assert heading in readme
    section = readme.split(heading, 1)[1]
    assert command in section
    baseline = section.split(marker, 1)[1]
    fence = chr(96) * 3
    payload = baseline.split(fence + "json", 1)[1].split(fence, 1)[0].strip()
    assert len(payload.splitlines()) == 1
    report = json.loads(payload)
    assert set(report) == REPORT_KEYS
    assert [row["match"] for row in report["per_match"]] == list(EXPECTED_MATCHES)
    assert [row["labels"] for row in report["per_match"]] == [4, 3, 4, 5]
    assert sum(row["predictions"] for row in report["per_match"]) > 0
    assert report["precision"] < 1.0
    assert report["event_accuracy"] in (0.0, None)
    for kind in SCORED_EVENTS:
        assert report["per_event"][kind]["recall"] == 0.0
        assert report["per_event"][kind]["precision"] is None
    assert report["per_event"]["other"]["recall"] is None
