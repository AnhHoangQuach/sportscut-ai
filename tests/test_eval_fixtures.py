import ast
import importlib.util
import json
from collections import Counter
from functools import lru_cache
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest


BUILD_PATH = Path(__file__).parent / "fixtures/eval/build.py"


def load_build():
    spec = importlib.util.spec_from_file_location("event_eval_build", BUILD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_build()


@pytest.fixture(scope="module")
def eval_set(require_ffmpeg, tmp_path_factory):
    directory = tmp_path_factory.mktemp("event_eval")
    build.build_all(directory)
    return directory


def test_fixture_interface() -> None:
    assert build.HERE == BUILD_PATH.parent
    assert (build.W, build.H, build.FPS) == (160, 90, 10)
    assert build.AUDIO_RATE == 16_000
    assert build.SCOREBOARD == (2, 2, 30, 14)
    assert tuple(build.MATCHES) == ("cards", "controversy", "goals_saves", "mixed")
    assert build.MATCHES == {
        "cards": {"duration": 180.0, "events": [
            ("red_card", 20), ("save", 50), ("controversy", 75),
            ("swell", 130), ("red_card", 155),
        ]},
        "controversy": {"duration": 180.0, "events": [
            ("controversy", 20), ("goal", 75, "away"), ("chant", 105),
            ("controversy", 130),
        ]},
        "goals_saves": {"duration": 180.0, "events": [
            ("goal", 20, "home"), ("save", 55), ("swell", 75),
            ("goal", 100, "away"), ("save", 140), ("chant", 160),
        ]},
        "mixed": {"duration": 180.0, "events": [
            ("save", 15), ("red_card", 40), ("goal", 70, "home"),
            ("swell", 105), ("goal", 125, "home"), ("save", 160),
        ]},
    }
    assert build.SEEDS == {name: 1101 + index for index, name in enumerate(build.MATCHES)}
    assert build.DISTRACTORS == ("swell", "chant")
    for name in ("match_labels", "footprints", "score_at", "play_clock",
                 "render_frame", "audio_track", "build_all"):
        assert callable(getattr(build, name))
    imports = set()
    for node in ast.walk(ast.parse(BUILD_PATH.read_text())):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    assert imports <= sys.stdlib_module_names | {"numpy"}


def test_committed_labels_match_generator() -> None:
    allowed = {"goal", "save", "red_card", "controversy"}
    expected_counts = {"cards": 4, "controversy": 3, "goals_saves": 4, "mixed": 5}
    for name in build.MATCHES:
        labels = build.match_labels(name)
        expected = json.dumps(labels, indent=1) + "\n"
        assert (BUILD_PATH.parent / name / "labels.json").read_text() == expected
        assert len(labels) == expected_counts[name]
        assert all(set(item) == {"start", "end", "type"} for item in labels)
        assert all(item["type"] in allowed for item in labels)
        assert labels == sorted(labels, key=lambda item: item["start"])


def test_set_coverage_and_spacing() -> None:
    labels = [label for name in build.MATCHES for label in build.match_labels(name)]
    assert Counter(label["type"] for label in labels) == {
        "goal": 5, "save": 5, "red_card": 3, "controversy": 3,
    }
    assert sum(event[0] in build.DISTRACTORS
               for match in build.MATCHES.values() for event in match["events"]) == 5
    for name, match in build.MATCHES.items():
        assert match["duration"] == 180.0
        spans = build.footprints(name)
        assert all(10 <= start < end <= 170 for _, start, end in spans)
        assert all(right[1] - left[2] >= 12 for left, right in zip(spans, spans[1:]))


def test_untracked_video() -> None:
    try:
        output = subprocess.run(
            ["git", "ls-files", "tests/fixtures/eval"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        pytest.skip("git is required to check tracked fixture files")
    assert not any(line.endswith((".mp4", ".wav")) for line in output.splitlines())


def events(name: str, kind: str):
    return [event for event in build.MATCHES[name]["events"] if event[0] == kind]


def scoreboard(frame: np.ndarray) -> np.ndarray:
    x, y, w, h = build.SCOREBOARD
    return frame[y:y + h, x:x + w]


def red_share(frame: np.ndarray) -> float:
    red = (frame[:, :, 0] >= 150) & (frame[:, :, 1] <= 60) & (frame[:, :, 2] <= 60)
    return float(np.mean(red))


def test_scoreboard_changes_only_at_goals() -> None:
    for name, match in build.MATCHES.items():
        crops = [scoreboard(build.render_frame(name, k / 10))
                 for k in range(round(match["duration"] * 10))]
        changed = [k / 10 for k in range(1, len(crops))
                   if not np.array_equal(crops[k - 1], crops[k])]
        expected = [event[1] + 1.0 for event in events(name, "goal")]
        assert changed == expected
        assert build.score_at(name, 0.0) == (0, 0)
        running = [0, 0]
        for _, t0, team in events(name, "goal"):
            assert build.score_at(name, (10 * t0 + 9) / 10) == tuple(running)
            running[team == "away"] += 1
            assert build.score_at(name, (10 * t0 + 10) / 10) == tuple(running)
        assert build.score_at(name, match["duration"]) == tuple(running)


def test_red_closeup_only_for_red_cards() -> None:
    for name, match in build.MATCHES.items():
        red_windows = [(event[1] + 4, event[1] + 8) for event in events(name, "red_card")]
        for k in range(round(match["duration"] * 10)):
            t = k / 10
            share = red_share(build.render_frame(name, t))
            inside = any(start <= t < end for start, end in red_windows)
            assert share >= 0.6 if inside else share <= 0.05


def _picture_exclusions(name: str):
    spans = []
    for kind, t0, *_ in build.MATCHES[name]["events"]:
        if kind == "goal":
            spans.append((t0 + 13, t0 + 18))
        elif kind == "controversy":
            spans.extend(((t0, t0 + 36), (t0 + 20, t0 + 26)))
        elif kind == "red_card":
            spans.extend(((t0, t0 + 12), (t0 + 4, t0 + 8)))
    return spans


def test_replays_repeat_source_and_play_moves() -> None:
    x, y, w, h = build.SCOREBOARD
    outside_score = np.ones((build.H, build.W), dtype=bool)
    outside_score[y:y + h, x:x + w] = False
    for name, match in build.MATCHES.items():
        for _, t0, _team in events(name, "goal"):
            for k in range(50):
                replay = build.render_frame(name, (10 * t0 + 130 + k) / 10)
                source = build.render_frame(name, (10 * t0 - 30 + k) / 10)
                assert np.array_equal(replay[outside_score], source[outside_score])
        for _, t0 in events(name, "controversy"):
            for k in range(60):
                replay = build.render_frame(name, (10 * t0 + 200 + k) / 10)
                source = build.render_frame(name, (10 * t0 - 60 + k) / 10)
                assert np.array_equal(replay, source)

        excluded = _picture_exclusions(name)
        eligible = [k / 10 for k in range(10, round(match["duration"] * 10))
                    if all(not (start <= point < end)
                           for point in (k / 10, (k - 10) / 10)
                           for start, end in excluded)]
        moving = sum(not np.array_equal(build.render_frame(name, t),
                                        build.render_frame(name, t - 1.0))
                     for t in eligible)
        assert moving / len(eligible) >= 0.95

        for kind, t0, *_ in match["events"]:
            if kind not in ("red_card", "controversy"):
                continue
            end = t0 + (12 if kind == "red_card" else 36)
            replay = (t0 + 20, t0 + 26) if kind == "controversy" else (-1, -1)
            closeup = (t0 + 4, t0 + 8) if kind == "red_card" else (-1, -1)
            for k in range(10 * t0 + 1, 10 * end + 1):
                pair = ((k - 1) / 10, k / 10)
                if any(start <= point < stop for point in pair
                       for start, stop in (replay, closeup)):
                    continue
                assert np.array_equal(build.render_frame(name, pair[0]),
                                      build.render_frame(name, pair[1]))


@lru_cache
def audio(name: str) -> np.ndarray:
    return build.audio_track(name)


def _levels(name: str) -> np.ndarray:
    samples = audio(name).reshape(-1, build.AUDIO_RATE // 10)
    rms = np.sqrt(np.mean(samples.astype(np.float64) ** 2, axis=1))
    return 20 * np.log10(rms + 1e-12)


def _first_index(indices, condition) -> int:
    return next(index for index in indices if condition(index))


def test_audio_level_cues() -> None:
    murmur_db = 20 * np.log10(0.02)
    for name, match in build.MATCHES.items():
        samples = audio(name)
        assert samples.dtype == np.float32
        assert len(samples) == round(match["duration"] * build.AUDIO_RATE)
        levels = _levels(name)
        for _, t0, *_ in events(name, "goal"):
            indices = range(10 * t0, 10 * (t0 + 10))
            loud = [index for index in indices if levels[index] >= murmur_db + 12]
            runs = np.split(loud, np.where(np.diff(loud) != 1)[0] + 1)
            run = max(runs, key=len)
            assert len(run) >= 80
            assert run[0] - 10 * t0 <= 5
        for _, t0, *_ in events(name, "save"):
            start, end = 10 * (t0 - 4), 10 * (t0 + 4)
            loud = np.count_nonzero(levels[start:end] >= murmur_db + 12)
            assert 20 <= loud <= 30
        for _, t0, *_ in events(name, "red_card"):
            assert np.all(levels[10 * t0 + 15:10 * t0 + 115] <= murmur_db - 6)

        footprint_by_event = list(zip(match["events"], build.footprints(name)))
        for event, (_kind, start, end) in footprint_by_event:
            kind, t0 = event[:2]
            if kind not in build.DISTRACTORS and kind != "save":
                continue
            footprint_levels = levels[round(start * 10):round(end * 10)]
            peak_db = float(np.max(footprint_levels))
            search = range(10 * (t0 - 1), round(end * 10) + 1)
            near_peak = _first_index(search, lambda index: levels[index] >= peak_db - 2)
            above_murmur = _first_index(search, lambda index: levels[index] >= murmur_db + 3)
            rise = near_peak - above_murmur
            if kind == "save":
                assert rise <= 2
                continue
            one_second = [
                20 * np.log10(np.sqrt(np.mean(samples[index * 1600:index * 1600 + 16000]
                                                .astype(np.float64) ** 2)) + 1e-12)
                for index in range(round(start * 10), round((end - 1) * 10) + 1)
            ]
            assert murmur_db + 6 <= max(one_second) <= murmur_db + 16
            assert rise >= 10


def _band_share(samples: np.ndarray, low: float, high: float) -> float:
    spectrum = np.fft.rfft(samples.astype(np.float64))
    frequencies = np.fft.rfftfreq(len(samples), 1 / build.AUDIO_RATE)
    energy = np.abs(spectrum) ** 2
    return float(np.sum(energy[(frequencies >= low) & (frequencies <= high)]) / np.sum(energy))


def test_audio_spectral_cues() -> None:
    for name, match in build.MATCHES.items():
        samples = audio(name)
        whistle_starts = [event[1] for event in match["events"]
                          if event[0] in ("red_card", "controversy")]
        boo_spans = [(event[1] + 3, event[1] + 33) for event in events(name, "controversy")]
        for t0 in whistle_starts:
            segment = samples[(10 * t0 + 1) * 1600:(10 * t0 + 9) * 1600]
            assert _band_share(segment, 2800, 3200) >= 0.8
        for second in range(round(match["duration"])):
            segment = samples[second * build.AUDIO_RATE:(second + 1) * build.AUDIO_RATE]
            if all(not (second < start + 1 and start < second + 1)
                   for start in whistle_starts):
                assert _band_share(segment, 2800, 3200) <= 0.05
            if all(not (second < end and start < second + 1) for start, end in boo_spans):
                assert _band_share(segment, 0, 220) <= 0.2
        for _, t0 in events(name, "controversy"):
            for second in range(t0 + 4, t0 + 32):
                segment = samples[second * build.AUDIO_RATE:(second + 1) * build.AUDIO_RATE]
                assert _band_share(segment, 0, 220) >= 0.6


def test_encoded_format_ffprobe(eval_set: Path) -> None:
    for name in build.MATCHES:
        video = eval_set / name / "video.mp4"
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type,codec_name,width,height,r_frame_rate,channels,sample_rate:format=duration",
            "-of", "json", str(video),
        ], capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        streams = {stream["codec_type"]: stream for stream in data["streams"]}
        video_stream, audio_stream = streams["video"], streams["audio"]
        assert (video_stream["codec_name"], video_stream["width"],
                video_stream["height"], video_stream["r_frame_rate"]) == (
                    "mpeg4", 160, 90, "10/1")
        assert (audio_stream["codec_name"], audio_stream["channels"],
                audio_stream["sample_rate"]) == ("aac", 1, "16000")
        assert float(data["format"]["duration"]) == pytest.approx(180.0, abs=0.2)
        assert not (video.parent / ".video.tmp.mp4").exists()


def _decoded_frame(video: Path, t: float) -> np.ndarray:
    result = subprocess.run([
        "ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video),
        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ], capture_output=True, check=True)
    return np.frombuffer(result.stdout, dtype=np.uint8).reshape(build.H, build.W, 3)


def test_decoded_cues_survive_encoding(eval_set: Path) -> None:
    from sportscut.media import extract_audio

    for name in build.MATCHES:
        video = eval_set / name / "video.mp4"
        for _, t0, _team in events(name, "goal"):
            after = scoreboard(_decoded_frame(video, t0 + 3))
            before = scoreboard(_decoded_frame(video, t0 - 1))
            expected = scoreboard(build.render_frame(name, t0 + 3))
            assert np.mean(np.abs(after.astype(int) - expected.astype(int))) <= 20
            assert np.mean(np.abs(after.astype(int) - before.astype(int))) >= 10
        for _, t0 in events(name, "red_card"):
            assert red_share(_decoded_frame(video, t0 + 6)) >= 0.6
        decoded_audio = extract_audio(video)
        for event in build.MATCHES[name]["events"]:
            if event[0] not in ("red_card", "controversy"):
                continue
            t0 = event[1]
            segment = decoded_audio[(10 * t0 + 1) * 1600:(10 * t0 + 9) * 1600]
            assert _band_share(segment, 2800, 3200) >= 0.5


def test_build_is_idempotent(eval_set: Path) -> None:
    videos = list(eval_set.glob("*/video.mp4"))
    labels = list(eval_set.glob("*/labels.json"))
    mtimes = {path: path.stat().st_mtime_ns for path in videos}
    contents = {path: path.read_bytes() for path in labels}
    build.build_all(eval_set)
    assert {path: path.stat().st_mtime_ns for path in videos} == mtimes
    assert {path: path.read_bytes() for path in labels} == contents


def test_force_and_changed_labels_rebuild(eval_set: Path) -> None:
    videos = {name: eval_set / name / "video.mp4" for name in build.MATCHES}
    before = {name: path.stat().st_mtime_ns for name, path in videos.items()}
    build.build_all(eval_set, force=True)
    forced = {name: path.stat().st_mtime_ns for name, path in videos.items()}
    assert all(forced[name] != before[name] for name in build.MATCHES)

    label = eval_set / "cards" / "labels.json"
    label.unlink()
    build.build_all(eval_set)
    changed = {name: path.stat().st_mtime_ns for name, path in videos.items()}
    assert changed["cards"] != forced["cards"]
    assert all(changed[name] == forced[name] for name in build.MATCHES if name != "cards")
    assert label.read_text() == json.dumps(build.match_labels("cards"), indent=1) + "\n"

    label.write_text("[]\n")
    before_edit = changed["cards"]
    build.build_all(eval_set)
    edited = {name: path.stat().st_mtime_ns for name, path in videos.items()}
    assert edited["cards"] != before_edit
    assert all(edited[name] == changed[name] for name in build.MATCHES if name != "cards")
    assert label.read_text() == json.dumps(build.match_labels("cards"), indent=1) + "\n"


def test_ffmpeg_failure_removes_temporary_file(tmp_path: Path, monkeypatch) -> None:
    class BrokenInput:
        def write(self, _data):
            raise BrokenPipeError("encoder closed")

        def close(self):
            raise BrokenPipeError("encoder closed")

    class FailedProcess:
        stdin = BrokenInput()

        def wait(self):
            return 1

        def kill(self):
            return None

    def fail(command, stdin, stderr):
        Path(command[-1]).write_bytes(b"partial")
        stderr.write(b"synthetic encoder failure")
        return FailedProcess()

    monkeypatch.setattr(build, "audio_track", lambda name: np.zeros(
        round(build.MATCHES[name]["duration"] * build.AUDIO_RATE), dtype=np.float32))
    monkeypatch.setattr(build.subprocess, "Popen", fail)
    with pytest.raises(RuntimeError, match="synthetic encoder failure"):
        build.build_all(tmp_path)
    assert not (tmp_path / "cards" / ".video.tmp.mp4").exists()


def _label_segments(video: Path, event_override: str | None = None):
    from sportscut.models import Segment

    labels = json.loads((Path(video).parent / "labels.json").read_text())
    return [Segment(item["start"], item["end"], 1.0, "oracle",
                    event_override or item["type"]) for item in labels]


def test_eval_oracle_matches_all_labels(eval_set: Path, monkeypatch) -> None:
    from sportscut import detect
    from sportscut.evaluate import evaluate_dir

    monkeypatch.setattr(detect, "find_highlights", _label_segments)
    report = evaluate_dir(eval_set)
    assert report["f1"] == report["precision"] == report["recall"] == 1.0
    assert report["event_accuracy"] == 1.0
    assert all(report["per_event"][kind]["recall"] == 1.0
               for kind in ("goal", "save", "red_card", "controversy"))
    assert [item["match"] for item in report["per_match"]] == sorted(build.MATCHES)
    assert [item["labels"] for item in report["per_match"]] == [4, 3, 4, 5]


def test_eval_all_other_baseline_shape(eval_set: Path, monkeypatch) -> None:
    from sportscut import detect
    from sportscut.events import scoreboard
    from sportscut.evaluate import evaluate_dir

    monkeypatch.setattr(detect, "find_highlights",
                        lambda video: _label_segments(video, "other"))
    monkeypatch.setattr(scoreboard, "tag_goals",
                        lambda video, segments, **kw: list(segments))
    report = evaluate_dir(eval_set)
    assert report["f1"] == report["precision"] == report["recall"] == 1.0
    assert report["event_accuracy"] == 0.0
    assert all(report["per_event"][kind]["recall"] == 0.0
               for kind in ("goal", "save", "red_card", "controversy"))
    assert [item["labels"] for item in report["per_match"]] == [4, 3, 4, 5]


def test_eval_cli_real_detector_json(eval_set: Path, capsys) -> None:
    from sportscut.cli import main

    assert main(["eval", str(eval_set), "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert len(captured.out.splitlines()) == 1
    report = json.loads(captured.out)
    assert set(report) == {
        "f1", "precision", "recall", "event_accuracy", "per_event",
        "precision_at_5", "per_match",
    }
    assert [item["match"] for item in report["per_match"]] == sorted(build.MATCHES)
    assert sum(item["predictions"] for item in report["per_match"]) > 0


def test_readme_baseline() -> None:
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    heading = "## Highlight theo sự kiện: đo độ chính xác (eval)"
    assert heading in readme
    section = readme.split(heading, 1)[1]
    assert "python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json" in section
    assert "<thư-mục>/<trận>/{video.mp4,labels.json}" in section
    assert '[{"start":18.0,"end":30.0,"type":"goal"}]' in section
    assert all(f"`{cue}`" in section for cue in (
        "goal", "save", "red_card", "controversy", "distractor"))
    marker = "Baseline đo trong T-011 (mọi đoạn đều là `other`):"
    assert marker in section
    after = section.split(marker, 1)[1]
    assert after.startswith("\n\n```json\n")
    report = json.loads(after.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert set(report) == {
        "f1", "precision", "recall", "event_accuracy", "per_event",
        "precision_at_5", "per_match",
    }
    assert [item["match"] for item in report["per_match"]] == sorted(build.MATCHES)
    assert [item["labels"] for item in report["per_match"]] == [4, 3, 4, 5]
    assert sum(item["predictions"] for item in report["per_match"]) > 0
    assert report["precision"] < 1.0
    assert report["event_accuracy"] in (0.0, None)
    for kind in ("goal", "save", "red_card", "controversy"):
        assert report["per_event"][kind]["precision"] is None
        assert report["per_event"][kind]["recall"] == 0.0
    assert report["per_event"]["other"]["recall"] is None
    assert "Mục tiêu tiếp theo: recall mỗi sự kiện ≥ 0.9, recall bàn thắng ≥ 0.95, F1 không giảm." in section
