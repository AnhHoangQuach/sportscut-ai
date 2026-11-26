"""Independent acceptance coverage for T-017's public crop-eval ruler."""

from __future__ import annotations

import ast
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np
import pytest

from sportscut import cli, eval_crop, media, reframe


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "eval_crop"
BUILD_PATH = FIXTURE_ROOT / "build.py"
CASE_NAMES = ("long_pass", "occluded", "slow_dribble", "white_distractor")
TOP_LEVEL_KEYS = (
    "ball_in_crop",
    "players_in_crop",
    "jitter",
    "seconds_per_min",
    "per_clip",
)
PER_CLIP_KEYS = (
    "clip",
    "duration",
    "labels",
    "ball_labels",
    "player_boxes",
    "ball_in_crop",
    "players_in_crop",
    "jitter",
    "seconds_per_min",
)


@pytest.fixture(scope="module")
def crop_builder():
    spec = importlib.util.spec_from_file_location("t017_acceptance_builder", BUILD_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built_eval_dir(tmp_path_factory, require_ffmpeg, crop_builder) -> Path:
    root = tmp_path_factory.mktemp("t017_acceptance_eval")
    assert len(crop_builder.build_all(root)) == 4
    return root


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sportscut", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _labels(root: Path, name: str) -> list[dict]:
    return json.loads((root / name / "labels.json").read_text())


def _independent_center_crop_score(root: Path) -> float:
    balls = [
        entry["ball"]
        for name in CASE_NAMES
        for entry in _labels(root, name)
        if entry["ball"] is not None
    ]
    return round(sum(219 <= ball[0] <= 421 for ball in balls) / len(balls), 4)


def test_ac2_probe_size_video_missing_and_audio_only(
    synthetic_video: Path, tmp_path: Path, require_ffmpeg
) -> None:
    assert media.probe_size(synthetic_video) == (160, 120)

    missing = tmp_path / "missing.mp4"
    with pytest.raises(media.MediaError, match=f"^media file not found: {missing}$"):
        media.probe_size(missing)

    audio = tmp_path / "silent-pictureless.wav"
    subprocess.run(
        [
            shutil.which("ffmpeg") or "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=8000:cl=mono",
            "-t",
            "0.1",
            "-y",
            str(audio),
        ],
        check=True,
    )
    with pytest.raises(media.MediaError, match=f"^no video stream in {audio}$"):
        media.probe_size(audio)


@pytest.mark.parametrize(
    ("width", "height", "aspect"),
    [
        (0, 360, 9 / 16),
        (-1, 360, 9 / 16),
        (True, 360, 9 / 16),
        (640, 0, 9 / 16),
        (640, False, 9 / 16),
        (640, 360, 0),
        (640, 360, -1),
        (640, 360, math.nan),
        (640, 360, math.inf),
        (640, 360, True),
    ],
)
def test_ac3_crop_width_geometry_and_rejects_invalid_values(
    width, height, aspect
) -> None:
    with pytest.raises(ValueError):
        reframe.crop_width(width, height, aspect)


def test_ac3_crop_width_examples() -> None:
    assert reframe.crop_width(640, 360) == 202
    assert reframe.crop_width(1920, 1080) == 606
    assert reframe.crop_width(720, 1920) == 720


def test_ac4_sample_times_handles_match_and_very_short_clips() -> None:
    times = reframe.sample_times(12.0)
    assert times == [round(i / 5, 4) for i in range(60)]
    assert times[0] == 0.0
    assert times[-1] == 11.8
    assert reframe.sample_times(0.1) == [0.0]
    for invalid in (0, -1, math.nan, math.inf, True):
        with pytest.raises(ValueError):
            reframe.sample_times(invalid)


def test_ac5_plan_crop_is_static_and_validates_before_duration(
    synthetic_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert reframe.plan_crop(synthetic_video) == [
        (t, 80.0) for t in reframe.sample_times(6.0)
    ]

    missing = tmp_path / "missing.mp4"
    with pytest.raises(media.MediaError, match="media file not found"):
        reframe.plan_crop(missing)

    def duration_must_not_run(_path):
        raise AssertionError("probe_duration ran before aspect validation")

    monkeypatch.setattr(media, "probe_duration", duration_must_not_run)
    with pytest.raises(ValueError):
        reframe.plan_crop(synthetic_video, aspect=0)


def test_ac11_load_labels_accepts_sparse_unsorted_and_optional_players(
    tmp_path: Path,
) -> None:
    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps(
            [
                {"t": 9.5, "ball": None},
                {"t": 0, "ball": [12, 34], "players": [[1, 2, 3, 4]]},
            ]
        )
    )
    labels = eval_crop.load_labels(path)
    assert [label.t for label in labels] == [0.0, 9.5]
    assert labels[0].ball == (12.0, 34.0)
    assert labels[0].players == ((1.0, 2.0, 3.0, 4.0),)
    assert labels[1].ball is None
    assert labels[1].players == ()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("not json", "Expecting value"),
        (json.dumps({}), "top level must be a list"),
        (json.dumps([]), "no labels"),
        (json.dumps([None]), r"\[0\] must be an object"),
        (json.dumps([{"ball": None}]), r"\[0\]\.t must be"),
        (json.dumps([{"t": True, "ball": None}]), r"\[0\]\.t must be"),
        (json.dumps([{"t": -0.1, "ball": None}]), r"\[0\]\.t must be"),
        (json.dumps([{"t": 0}]), r"\[0\]\.ball must be"),
        (json.dumps([{"t": 0, "ball": [1]}]), r"\[0\]\.ball must be"),
        (
            json.dumps([{"t": 0, "ball": None, "players": [[0, 0, 0, 2]]}]),
            r"\[0\]\.players must be",
        ),
    ],
)
def test_ac11_load_labels_rejects_malformed_data_with_path_prefix(
    tmp_path: Path, raw: str, message: str
) -> None:
    path = tmp_path / "bad.json"
    path.write_text(raw)
    with pytest.raises(ValueError, match=message) as exc_info:
        eval_crop.load_labels(path)
    assert str(exc_info.value).startswith(f"{path}:")


def test_ac12_all_cases_are_validated_before_planning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("a-valid", "z-missing"):
        case = tmp_path / name
        case.mkdir()
        (case / "labels.json").write_text('[{"t": 0, "ball": null}]')
    (tmp_path / "a-valid" / "clip.mp4").touch()

    calls: list[Path] = []
    monkeypatch.setattr(reframe, "plan_crop", lambda path: calls.append(Path(path)))
    with pytest.raises(ValueError, match="run python tests/fixtures/eval_crop/build.py"):
        eval_crop.evaluate_dir(tmp_path)
    assert calls == []

    with pytest.raises(ValueError, match="not a directory"):
        eval_crop.evaluate_dir(tmp_path / "absent")
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ValueError, match="no eval-crop cases found"):
        eval_crop.evaluate_dir(empty)


@pytest.mark.parametrize(
    "plan",
    [
        [],
        [(0, 320), (0, 320)],
        [(math.nan, 320)],
        [(0, math.inf)],
        [(0, 100.9)],
        [(0, 539.1)],
        [(0,)],
    ],
)
def test_ac13_invalid_plans_are_rejected(plan) -> None:
    with pytest.raises(
        ValueError, match="^plan_crop returned an invalid plan for sample:"
    ):
        eval_crop.validate_plan(plan, width=640, cw=202, where="sample")


def test_ac14_scoring_edges_interpolation_jitter_and_empty_metrics() -> None:
    labels = [
        eval_crop.Label(0.0, (219.0, 10.0), ((410.0, 0.0, 20.0, 30.0),)),
        eval_crop.Label(0.5, (218.9, 10.0), ()),
        eval_crop.Label(2.0, (421.0, 10.0), ()),
    ]
    counts = eval_crop.score_clip(labels, [(0.0, 320.0)], 640, 202, 2.1)
    assert counts["ball_hits"] == 2
    assert counts["ball_total"] == 3
    assert counts["player_hits"] == 1

    interpolated = eval_crop.score_clip(
        [eval_crop.Label(1.0, (320.0, 10.0), ())],
        [(0.0, 101.0), (2.0, 539.0)],
        640,
        202,
        2.1,
    )
    assert interpolated["ball_hits"] == interpolated["ball_total"] == 1

    jitter_counts = eval_crop.score_clip(
        [], [(0, 320), (0.2, 340), (0.4, 320), (0.6, 340)], 640, 202, 0.8
    )
    jitter_metrics = eval_crop.metrics(jitter_counts, seconds=1.0, minutes=2.0)
    assert jitter_metrics == {
        "ball_in_crop": None,
        "players_in_crop": None,
        "jitter": round(40 / 640, 6),
        "seconds_per_min": 0.5,
    }


def test_ac14_evaluate_dir_micro_averages_and_orders_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    samples = {
        "z-three-hits": [320, 320, 320],
        "a-one-of-two": [320, 100],
    }
    for name, xs in samples.items():
        case = tmp_path / name
        case.mkdir()
        (case / "clip.mp4").touch()
        (case / "labels.json").write_text(
            json.dumps(
                [
                    {"t": index * 0.2, "ball": [x, 50], "players": []}
                    for index, x in enumerate(xs)
                ]
            )
        )

    monkeypatch.setattr(media, "probe_size", lambda _path: (640, 360))
    monkeypatch.setattr(media, "probe_duration", lambda _path: 1.0)
    monkeypatch.setattr(reframe, "plan_crop", lambda _path: [(0.0, 320.0)])

    report = eval_crop.evaluate_dir(tmp_path)
    assert list(report) == list(TOP_LEVEL_KEYS)
    assert report["ball_in_crop"] == 0.8
    assert [entry["clip"] for entry in report["per_clip"]] == sorted(samples)
    assert all(list(entry) == list(PER_CLIP_KEYS) for entry in report["per_clip"])


def test_ac6_ac8_ac9_ac10_committed_fixture_contract(crop_builder) -> None:
    source = BUILD_PATH.read_text()
    tree = ast.parse(source)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    assert not any(name == "sportscut" or name.startswith("sportscut.") for name in imported_modules)
    assert tuple(sorted(crop_builder.CASES)) == CASE_NAMES

    null_cases: dict[str, list[float]] = {}
    for name in CASE_NAMES:
        path = FIXTURE_ROOT / name / "labels.json"
        assert path.read_text() == crop_builder.labels_text(name)
        entries = json.loads(path.read_text())
        assert [entry["t"] for entry in entries] == [round(i / 5, 1) for i in range(60)]
        for entry in entries:
            assert set(entry) == {"t", "ball", "players"}
            if entry["ball"] is None:
                null_cases.setdefault(name, []).append(entry["t"])
            else:
                x, y = entry["ball"]
                assert all(isinstance(value, int) and not isinstance(value, bool) for value in (x, y))
                assert 4 <= x <= 635 and 4 <= y <= 355
            for x, y, width, height in entry["players"]:
                assert all(isinstance(value, int) and not isinstance(value, bool) for value in (x, y, width, height))
                assert 0 <= x and 0 <= y and x + width <= 640 and y + height <= 360

    assert set(null_cases) == {"occluded"}
    hidden_times = null_cases["occluded"]
    assert 4 <= len(hidden_times) <= 8
    assert hidden_times == [round(hidden_times[0] + 0.2 * i, 1) for i in range(len(hidden_times))]
    assert 4.6 <= hidden_times[0] <= hidden_times[-1] <= 6.4

    def maximum_speed(name: str) -> float:
        visible = [entry for entry in _labels(FIXTURE_ROOT, name) if entry["ball"] is not None]
        return max(
            math.dist(left["ball"], right["ball"]) / (right["t"] - left["t"])
            for left, right in zip(visible, visible[1:])
        )

    assert maximum_speed("long_pass") >= 300
    assert maximum_speed("slow_dribble") <= 60
    assert all(entry["ball"][0] > 421 for entry in _labels(FIXTURE_ROOT, "white_distractor"))

    hidden_frame = crop_builder.render_frame("occluded", hidden_times[0])
    visible_frame = crop_builder.render_frame("occluded", 0.0)
    assert np.count_nonzero(np.all(hidden_frame == 255, axis=2)) == 0
    assert np.count_nonzero(np.all(visible_frame == 255, axis=2)) >= 20

    distractor = crop_builder.render_frame("white_distractor", 0.0).copy()
    bx, by = map(round, crop_builder.ball_pos("white_distractor", 0.0))
    distractor[by - 4 : by + 5, bx - 4 : bx + 5] = 0
    assert np.count_nonzero(np.all(distractor == 255, axis=2)) >= 200


def test_ac6_ac7_builder_video_shape_duration_and_idempotence(
    built_eval_dir: Path, crop_builder
) -> None:
    paths = sorted(crop_builder.build_all(built_eval_dir))
    assert [path.parent.name for path in paths] == list(CASE_NAMES)
    for clip in paths:
        assert media.probe_size(clip) == (640, 360)
        assert media.probe_duration(clip) == pytest.approx(12.0, abs=0.05)

    before = {path: path.stat().st_mtime_ns for path in paths}
    assert sorted(crop_builder.build_all(built_eval_dir)) == paths
    assert {path: path.stat().st_mtime_ns for path in paths} == before

    time.sleep(0.01)
    assert sorted(crop_builder.build_all(built_eval_dir, force=True)) == paths
    assert all(path.stat().st_mtime_ns > before[path] for path in paths)

    tracked = subprocess.run(
        ["git", "ls-files", "tests/fixtures/eval_crop"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert not [path for path in tracked if path.endswith(".mp4")]
    for name in CASE_NAMES:
        ignored = subprocess.run(
            ["git", "check-ignore", f"tests/fixtures/eval_crop/{name}/clip.mp4"],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert ignored.returncode == 0


def test_ac15_cli_json_matches_independent_baseline(built_eval_dir: Path) -> None:
    result = _run_cli("eval-crop", str(built_eval_dir), "--json")
    assert result.returncode == 0, result.stderr
    assert len(result.stdout.splitlines()) == 1
    report = json.loads(result.stdout)
    assert list(report) == list(TOP_LEVEL_KEYS)
    assert len(report["per_clip"]) == 4
    assert report["jitter"] == 0.0
    assert report["ball_in_crop"] == _independent_center_crop_score(built_eval_dir)
    assert report["ball_in_crop"] < 0.95


def test_ac16_ball_following_oracle_reaches_one(
    built_eval_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def oracle(clip: Path) -> list[tuple[float, float]]:
        entries = _labels(Path(clip).parent.parent, Path(clip).parent.name)
        return [
            (entry["t"], float(np.clip(entry["ball"][0], 101, 539)))
            for entry in entries
            if entry["ball"] is not None
        ]

    monkeypatch.setattr(reframe, "plan_crop", oracle)
    assert eval_crop.evaluate_dir(built_eval_dir)["ball_in_crop"] == 1.0


def test_ac17_cli_pretty_output_and_nonexistent_error(built_eval_dir: Path) -> None:
    pretty = _run_cli("eval-crop", str(built_eval_dir))
    assert pretty.returncode == 0, pretty.stderr
    assert len(pretty.stdout.splitlines()) > 1
    assert json.loads(pretty.stdout)["jitter"] == 0.0

    missing = _run_cli("eval-crop", "/nonexistent-t017", "--json")
    assert missing.returncode == 2
    assert missing.stdout == ""
    assert missing.stderr.startswith(
        "sportscut eval-crop: error: not a directory: /nonexistent-t017"
    )


@pytest.mark.parametrize(
    "error", [ValueError("bad value"), OSError("bad os"), media.MediaError("bad media")]
)
def test_ac17_cli_handles_all_documented_errors(
    error: Exception, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(_path):
        raise error

    monkeypatch.setattr(eval_crop, "evaluate_dir", fail)
    assert cli.main(["eval-crop", "irrelevant", "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"sportscut eval-crop: error: {error}\n"


def test_ac18_docs_describe_reproducible_eval_and_exception() -> None:
    readme = (ROOT / "README.md").read_text()
    assert "## Video dọc 9:16: đo khung cắt (eval-crop)" in readme
    for required in (
        "python tests/fixtures/eval_crop/build.py",
        "python -m sportscut eval-crop tests/fixtures/eval_crop --json",
        "data/eval_crop/<name>/{clip.mp4,labels.json}",
        "ball_in_crop",
        "players_in_crop",
        "jitter",
        "seconds_per_min",
        "Baseline đo trong T-017 (center crop):",
        "Mục tiêu: ball_in_crop ≥ 0.95 với jitter thấp",
    ):
        assert required in readme

    design = (
        ROOT
        / "docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md"
    ).read_text()
    assert (
        "T-017: same exception for the reframing eval set — "
        "tests/fixtures/eval_crop/build.py may write git-ignored clip.mp4 files inside "
        "tests/fixtures/eval_crop/; pytest builds only in temp dirs and no media is committed."
    ) in design
