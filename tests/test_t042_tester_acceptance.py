from __future__ import annotations

import ast
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EVAL_CROP_HEADING = "## Video dọc 9:16: đo khung cắt (eval-crop)"
PORTED_PATHS = [
    "sportscut/reframe.py",
    "sportscut/eval_crop.py",
    "tests/fixtures/eval_crop",
    "tests/test_reframe.py",
    "tests/test_eval_crop.py",
    "tests/test_eval_crop_fixtures.py",
    "tests/test_t017_acceptance.py",
    "docs/superpowers/specs/2026-11-23-t-017-add-a-measurable-9-16-reframing-design.md",
    "docs/superpowers/plans/2026-11-23-t-017-add-a-measurable-9-16-reframing.md",
]
SHARED_PATHS = [
    "sportscut/media.py",
    "tests/test_media.py",
    "tests/test_cli.py",
    "README.md",
    "docs/superpowers/DECISIONS.md",
    "docs/superpowers/INDEX.md",
    "docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md",
]
PROTECTED_PATHS = [
    "sportscut/evaluate.py",
    "sportscut/eval_player.py",
    "sportscut/export.py",
    "tests/conftest.py",
    "agent-office/",
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), cwd=ROOT, text=True, capture_output=True, check=False
    )


def _git() -> str:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is required for scope check")
    return git


def _merge_base(git: str) -> str:
    result = _run(git, "merge-base", "main", "HEAD")
    if result.returncode != 0 or not result.stdout.strip():
        pytest.skip("main is required for scope check")
    return result.stdout.strip()


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    node = next(
        item
        for item in tree.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == name
    )
    assert node.end_lineno is not None
    return "\n".join(source.splitlines()[node.lineno - 1 : node.end_lineno])


def _readme_baseline() -> dict:
    section = (ROOT / "README.md").read_text(encoding="utf-8").split(
        EVAL_CROP_HEADING, 1
    )[1]
    block = section.split("```json", 1)[1].split("```", 1)[0]
    return json.loads(block)


def _without_timings(report: dict) -> dict:
    result = dict(report)
    result.pop("seconds_per_min", None)
    result["per_clip"] = []
    for item in report["per_clip"]:
        cleaned = dict(item)
        cleaned.pop("seconds_per_min", None)
        result["per_clip"].append(cleaned)
    return result


def _require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required on PATH")


def test_ac1_ac2_crop_contract_is_static_even_full_height_and_five_hz():
    from sportscut import reframe

    assert reframe.crop_width(640, 360) == 202
    assert reframe.crop_width(1920, 1080) == 606
    assert reframe.crop_width(720, 1920) == 720
    assert reframe.crop_width(640, 360) % 2 == 0
    assert reframe.sample_times(0.01) == [0.0]
    times = reframe.sample_times(12.0)
    assert len(times) == 60
    assert times[0] == 0.0
    assert times[-1] == 11.8
    assert all(right - left == pytest.approx(0.2) for left, right in zip(times, times[1:]))
    with pytest.raises(ValueError):
        reframe.crop_width(True, 360)
    with pytest.raises(ValueError):
        reframe.sample_times(0.0)


def test_ac2_plan_crop_handles_a_very_short_silent_video(tmp_path):
    from sportscut.media import probe_size
    from sportscut.reframe import plan_crop

    _require_ffmpeg()
    video = tmp_path / "short-silent.mp4"
    encoded = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=100x60:r=25:d=0.08",
            "-an",
            "-c:v",
            "mpeg4",
            "-y",
            str(video),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert encoded.returncode == 0, encoded.stderr
    assert probe_size(video) == (100, 60)
    assert plan_crop(video) == [(0.0, 50.0)]


def test_ac2_scoring_linearly_interpolates_the_crop_plan(tmp_path, monkeypatch):
    from sportscut import eval_crop

    case = tmp_path / "linear"
    case.mkdir()
    (case / "clip.mp4").write_bytes(b"")
    (case / "labels.json").write_text(
        json.dumps([{"t": 0.4, "ball": [320, 10], "players": [[310, 0, 20, 20]]}]),
        encoding="utf-8",
    )
    monkeypatch.setattr(eval_crop.media, "probe_size", lambda _path: (640, 360))
    monkeypatch.setattr(eval_crop.media, "probe_duration", lambda _path: 1.0)
    monkeypatch.setattr(
        eval_crop.reframe,
        "plan_crop",
        lambda _path: [(0.0, 101.0), (0.8, 539.0)],
    )

    report = eval_crop.evaluate_dir(tmp_path)

    assert report["ball_in_crop"] == 1.0
    assert report["players_in_crop"] == 1.0


def test_ac2_reviewed_files_and_probe_size_match_the_reviewed_commit():
    git = _git()
    ported = _run(git, "diff", "--quiet", "office/T-017-r2", "--", *PORTED_PATHS)
    assert ported.returncode == 0, ported.stderr or ported.stdout

    reviewed = _run(git, "show", "314d171:sportscut/media.py")
    assert reviewed.returncode == 0, reviewed.stderr
    current = (ROOT / "sportscut/media.py").read_text(encoding="utf-8")
    assert _function_source(current, "probe_size") == _function_source(
        reviewed.stdout, "probe_size"
    )


def test_ac3_shared_files_are_append_only_and_existing_commands_work(capsys):
    from sportscut import cli

    git = _git()
    base = _merge_base(git)
    diff = _run(git, "diff", "--numstat", base, "--", *SHARED_PATHS)
    assert diff.returncode == 0, diff.stderr
    for line in diff.stdout.splitlines():
        _added, deleted, _path = line.split("\t", 2)
        assert deleted == "0", line

    assert cli.main(["eval-meta", "tests/fixtures/eval_meta", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["score"] == 1.0

    with pytest.raises(SystemExit) as exc:
        cli.main(["cut", "x.mp4", "--events", "bogus"])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "bogus" in captured.err


def test_ac4_eval_crop_cli_formats_success_and_all_user_errors(monkeypatch, capsys):
    from sportscut import cli
    from sportscut.media import MediaError

    report = {
        "ball_in_crop": 0.5,
        "players_in_crop": None,
        "jitter": 0.0,
        "seconds_per_min": 0.1,
        "per_clip": [],
    }
    monkeypatch.setattr(cli.eval_crop, "evaluate_dir", lambda _directory: report)

    assert cli.main(["eval-crop", "unused", "--json"]) == 0
    compact = capsys.readouterr()
    assert compact.err == ""
    assert compact.out == json.dumps(report) + "\n"

    assert cli.main(["eval-crop", "unused"]) == 0
    indented = capsys.readouterr()
    assert indented.err == ""
    assert indented.out == json.dumps(report, indent=2) + "\n"

    for error in (ValueError("bad labels"), OSError("disk error"), MediaError("bad media")):
        def fail(_directory, error=error):
            raise error

        monkeypatch.setattr(cli.eval_crop, "evaluate_dir", fail)
        assert cli.main(["eval-crop", "unused", "--json"]) == 2
        failed = capsys.readouterr()
        assert failed.out == ""
        assert failed.err == f"sportscut eval-crop: error: {error}\n"


def test_ac4_empty_and_missing_directories_are_user_errors(tmp_path, capsys):
    from sportscut import cli

    assert cli.main(["eval-crop", str(tmp_path), "--json"]) == 2
    empty = capsys.readouterr()
    assert empty.out == ""
    assert empty.err.startswith("sportscut eval-crop: error: ")

    missing = tmp_path / "missing"
    assert cli.main(["eval-crop", str(missing), "--json"]) == 2
    absent = capsys.readouterr()
    assert absent.out == ""
    assert absent.err.startswith("sportscut eval-crop: error: not a directory")


def test_ac5_eval_crop_cli_matches_the_readme_baseline(tmp_path, capsys):
    from sportscut import cli

    _require_ffmpeg()
    build = _load_module(
        ROOT / "tests/fixtures/eval_crop/build.py", "t042_tester_eval_crop_build"
    )
    build.build_all(tmp_path)
    capsys.readouterr()

    assert cli.main(["eval-crop", str(tmp_path), "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    report = json.loads(captured.out)
    assert report["ball_in_crop"] == 0.2821
    assert report["players_in_crop"] == 0.4024
    assert report["jitter"] == 0.0
    assert _without_timings(report) == _without_timings(_readme_baseline())


def test_ac6_existing_event_eval_f1_is_unchanged(capsys):
    from sportscut import cli

    _require_ffmpeg()
    fixture = ROOT / "tests/fixtures/eval"
    expected_videos = [fixture / name / "video.mp4" for name in (
        "cards", "controversy", "goals_saves", "mixed"
    )]
    if not all(path.exists() for path in expected_videos):
        build = _load_module(fixture / "build.py", "t042_tester_event_eval_build")
        build.build_all(fixture)
    capsys.readouterr()

    assert cli.main(["eval", str(fixture), "--json"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["f1"] == 0.8421


def test_ac7_documentation_is_the_reviewed_trailing_section():
    git = _git()
    reviewed = _run(git, "show", "314d171:README.md")
    assert reviewed.returncode == 0, reviewed.stderr
    expected_section = EVAL_CROP_HEADING + reviewed.stdout.split(EVAL_CROP_HEADING, 1)[1]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.endswith(expected_section)

    t036 = (ROOT / SHARED_PATHS[-1]).read_text(encoding="utf-8")
    assert "T-017: same exception for the reframing eval set" in t036
    decisions = (ROOT / "docs/superpowers/DECISIONS.md").read_text(encoding="utf-8")
    index = (ROOT / "docs/superpowers/INDEX.md").read_text(encoding="utf-8")
    assert "2026-11-23 T-017 (R-004)" in decisions
    assert "T-017" in index and "9:16" in index


def _scope_module():
    return _load_module(
        ROOT / "tests/test_t023_acceptance.py", "t042_tester_scope_target"
    )


def test_ac8_scope_check_uses_merge_base_and_the_same_protected_list(monkeypatch):
    module = _scope_module()
    calls = []

    def record(args, **_kwargs):
        calls.append(args)
        if args[1] == "merge-base":
            return subprocess.CompletedProcess(args, 0, "abc123\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(
        module.shutil, "which", lambda _name, **_kwargs: "/usr/bin/git"
    )
    monkeypatch.setattr(module.subprocess, "run", record)
    module.test_ac16_protected_implementation_files_are_unchanged_from_main()

    assert calls == [
        ["/usr/bin/git", "merge-base", "main", "HEAD"],
        [
            "/usr/bin/git",
            "diff",
            "--name-only",
            "abc123",
            "--",
            "sportscut/export.py",
            "tests/conftest.py",
        ],
    ]


@pytest.mark.parametrize("returncode,stdout", [(128, ""), (0, "")])
def test_ac8_scope_check_skips_when_main_is_unavailable(
    monkeypatch, returncode, stdout
):
    module = _scope_module()
    monkeypatch.setattr(
        module.shutil, "which", lambda _name, **_kwargs: "/usr/bin/git"
    )
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda args, **_kwargs: subprocess.CompletedProcess(
            args, returncode, stdout, "missing main"
        ),
    )

    with pytest.raises(pytest.skip.Exception, match="main is required for scope check"):
        module.test_ac16_protected_implementation_files_are_unchanged_from_main()


def test_ac8_scope_check_still_fails_for_a_changed_protected_file(monkeypatch):
    module = _scope_module()

    def record(args, **_kwargs):
        if args[1] == "merge-base":
            return subprocess.CompletedProcess(args, 0, "abc123\n", "")
        return subprocess.CompletedProcess(args, 0, "sportscut/export.py\n", "")

    monkeypatch.setattr(
        module.shutil, "which", lambda _name, **_kwargs: "/usr/bin/git"
    )
    monkeypatch.setattr(module.subprocess, "run", record)
    with pytest.raises(AssertionError):
        module.test_ac16_protected_implementation_files_are_unchanged_from_main()


def test_ac10_protected_paths_are_untouched_and_no_mp4_is_tracked():
    git = _git()
    base = _merge_base(git)
    protected = _run(git, "diff", "--name-only", base, "--", *PROTECTED_PATHS)
    assert protected.returncode == 0, protected.stderr
    assert protected.stdout == ""

    media = _run(git, "ls-files", "*.mp4")
    assert media.returncode == 0, media.stderr
    assert media.stdout == ""
