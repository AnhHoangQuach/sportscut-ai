import ast
import importlib.util
import json
import shutil
import subprocess
import types
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
T023_ACCEPTANCE = ROOT / "tests" / "test_t023_acceptance.py"
SHARED_FILES = (
    "sportscut/media.py",
    "tests/test_media.py",
    "tests/test_cli.py",
    "README.md",
    "docs/superpowers/DECISIONS.md",
    "docs/superpowers/INDEX.md",
    "docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md",
)
PROTECTED_FILES = (
    "sportscut/evaluate.py",
    "sportscut/eval_player.py",
    "sportscut/export.py",
    "tests/conftest.py",
    "agent-office/",
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
)
PORTED_PATHS = (
    "sportscut/reframe.py",
    "sportscut/eval_crop.py",
    "tests/fixtures/eval_crop",
    "tests/test_reframe.py",
    "tests/test_eval_crop.py",
    "tests/test_eval_crop_fixtures.py",
    "tests/test_t017_acceptance.py",
    "docs/superpowers/specs/2026-11-23-t-017-add-a-measurable-9-16-reframing-design.md",
    "docs/superpowers/plans/2026-11-23-t-017-add-a-measurable-9-16-reframing.md",
)
CHANGED_BY_T019 = (
    "sportscut/reframe.py",
    "tests/test_reframe.py",
    "tests/test_eval_crop_fixtures.py",
    "tests/test_t017_acceptance.py",
    "docs/superpowers/specs/2026-11-23-t-017-add-a-measurable-9-16-reframing-design.md",
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    git = shutil.which("git")
    if git is None:
        pytest.skip("git is required for scope check")
    return subprocess.run(
        [git, *args], cwd=ROOT, text=True, capture_output=True, check=False
    )


def _merge_base() -> str:
    result = _git("merge-base", "main", "HEAD")
    if result.returncode != 0 or not result.stdout.strip():
        pytest.skip("main is required for scope check")
    return result.stdout.strip()


def _function_source(source: str, name: str) -> str:
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    segment = ast.get_source_segment(source, function)
    assert segment is not None
    return segment


def _without_timings(report: dict) -> dict:
    clean = json.loads(json.dumps(report))
    clean.pop("seconds_per_min", None)
    for clip in clean["per_clip"]:
        clip.pop("seconds_per_min", None)
    return clean


def _read_readme_crop_baseline() -> dict:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Video dọc 9:16: đo khung cắt (eval-crop)", 1)[1]
    return json.loads(section.split("```json", 1)[1].split("```", 1)[0])


def _scope_module(monkeypatch, responses):
    module = _load_module("t023_scope_under_test", T023_ACCEPTANCE)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return responses[len(calls) - 1]

    monkeypatch.setattr(module.shutil, "which", lambda name, **kwargs: "/test/git")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return module, calls


def test_ac1_ac2_public_crop_contract_and_short_duration(monkeypatch):
    from sportscut import media, reframe

    assert callable(reframe.plan_crop)
    assert callable(reframe.crop_width)
    assert callable(media.probe_size)
    assert reframe.crop_width(640, 360) == 202
    assert reframe.crop_width(1920, 1080) == 606
    assert reframe.crop_width(720, 1920) == 720
    assert reframe.sample_times(0.1) == [0.0]
    with pytest.raises(ValueError):
        reframe.crop_width(True, 360)

    monkeypatch.setattr(reframe.media, "probe_duration", lambda path: 0.4)
    monkeypatch.setattr(reframe.media, "probe_size", lambda path: (640, 360))
    monkeypatch.setattr(
        reframe.media, "sample_frames", lambda *a, **k: np.zeros((0, 2, 2, 3), np.uint8)
    )
    assert reframe.plan_crop("short-silent.mp4") == [
        (0.0, 320.0),
        (0.2, 320.0),
    ]


def test_ac2_scoring_linearly_interpolates_plan(tmp_path, monkeypatch):
    from sportscut import eval_crop

    case = tmp_path / "interpolation"
    case.mkdir()
    (case / "clip.mp4").touch()
    (case / "labels.json").write_text(
        json.dumps(
            [
                {"t": 0.25, "ball": [66, 50]},
                {"t": 0.75, "ball": [34, 50]},
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(eval_crop.media, "probe_duration", lambda path: 1.0)
    monkeypatch.setattr(eval_crop.media, "probe_size", lambda path: (100, 100))
    monkeypatch.setattr(
        eval_crop.reframe, "plan_crop", lambda path: [(0.0, 28.0), (1.0, 72.0)]
    )

    report = eval_crop.evaluate_dir(tmp_path)

    assert list(report) == [
        "ball_in_crop",
        "players_in_crop",
        "jitter",
        "seconds_per_min",
        "per_clip",
    ]
    assert report["ball_in_crop"] == 1.0
    assert report["players_in_crop"] is None


def test_ac2_ported_files_and_probe_size_match_reviewed_t017():
    unchanged = [p for p in PORTED_PATHS if p not in CHANGED_BY_T019]
    result = _git("diff", "--quiet", "office/T-017-r2", "--", *unchanged)
    assert result.returncode == 0, result.stderr

    reviewed = _git("show", "314d171:sportscut/media.py")
    assert reviewed.returncode == 0, reviewed.stderr
    current = (ROOT / "sportscut" / "media.py").read_text(encoding="utf-8")
    assert _function_source(current, "probe_size") == _function_source(
        reviewed.stdout, "probe_size"
    )


def test_ac3_shared_files_are_append_only():
    if _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip().startswith("office/T-042"):
        result = _git("diff", "--numstat", _merge_base(), "--", *SHARED_FILES)
        assert result.returncode == 0, result.stderr
        stats = {
            parts[2]: (parts[0], parts[1])
            for line in result.stdout.splitlines()
            if len(parts := line.split("\t", 2)) == 3
        }
        assert all(deleted == "0" for _, deleted in stats.values())


def test_ac3_existing_cli_commands_and_readme_sections_remain(capsys):
    from sportscut import cli

    assert cli.main(["eval-meta", "tests/fixtures/eval_meta", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["score"] == 1.0

    with pytest.raises(SystemExit) as exc:
        cli.main(["cut", "x.mp4", "--events", "bogus"])
    assert exc.value.code == 2
    assert "argument --events: unknown event" in capsys.readouterr().err

    missing = "/nonexistent-t042-player"
    assert cli.main(["eval-player", missing, "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("sportscut eval-player: error:")

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Bình luận AI: đo chất lượng tiêu đề, caption, hashtag (eval-meta)" in readme
    assert "## Trang web: tải lên, xem trước và chỉnh mốc cắt" in readme


def test_ac4_eval_crop_cli_json_modes_and_module_patch(monkeypatch, capsys):
    from sportscut import cli

    report = {
        "ball_in_crop": 0.5,
        "players_in_crop": None,
        "jitter": 0.0,
        "seconds_per_min": 0.1,
        "per_clip": [],
    }
    assert isinstance(cli.eval_crop, types.ModuleType)
    monkeypatch.setattr(cli.eval_crop, "evaluate_dir", lambda directory: report)

    assert cli.main(["eval-crop", "anywhere", "--json"]) == 0
    compact = capsys.readouterr()
    assert compact.err == ""
    assert compact.out.count("\n") == 1
    assert json.loads(compact.out) == report

    assert cli.main(["eval-crop", "anywhere"]) == 0
    indented = capsys.readouterr()
    assert indented.err == ""
    assert "\n  \"ball_in_crop\"" in indented.out
    assert json.loads(indented.out) == report


@pytest.mark.parametrize(
    ("error_kind", "message"),
    [
        ("value", "bad labels"),
        ("os", "disk error"),
        ("media", "bad media"),
    ],
    ids=["value-error", "os-error", "media-error"],
)
def test_ac4_eval_crop_cli_user_errors(error_kind, message, monkeypatch, capsys):
    from sportscut import cli
    from sportscut.media import MediaError

    error_type = {"value": ValueError, "os": OSError, "media": MediaError}[error_kind]
    error = error_type(message)

    def fail(directory):
        raise error

    monkeypatch.setattr(cli.eval_crop, "evaluate_dir", fail)
    assert cli.main(["eval-crop", "anywhere", "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"sportscut eval-crop: error: {error}\n"


def test_ac4_empty_eval_directory_is_a_user_error(tmp_path, capsys):
    from sportscut import cli

    assert cli.main(["eval-crop", str(tmp_path), "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("sportscut eval-crop: error:")


def test_ac5_eval_crop_matches_readme_baseline(tmp_path, monkeypatch):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required on PATH")
    from sportscut import eval_crop, reframe

    build = _load_module(
        "t042_eval_crop_build", ROOT / "tests" / "fixtures" / "eval_crop" / "build.py"
    )
    build.build_all(tmp_path)
    monkeypatch.setattr(eval_crop.reframe, "plan_crop", reframe.center_plan)
    report = eval_crop.evaluate_dir(tmp_path)
    expected = _read_readme_crop_baseline()

    assert report["ball_in_crop"] == 0.2821
    assert report["players_in_crop"] == 0.4024
    assert report["jitter"] == 0.0
    assert _without_timings(report) == _without_timings(expected)


def test_ac7_docs_match_reviewed_t017_and_readme_section_is_last():
    reviewed = _git("show", "314d171:README.md")
    assert reviewed.returncode == 0, reviewed.stderr
    heading = "## Video dọc 9:16: đo khung cắt (eval-crop)"
    expected_section = heading + reviewed.stdout.split(heading, 1)[1]
    current = (ROOT / "README.md").read_text(encoding="utf-8")
    assert current.endswith(expected_section)

    t036 = (
        ROOT
        / "docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md"
    ).read_text(encoding="utf-8")
    assert "T-017: same exception for the reframing eval set" in t036


def test_ac8_scope_check_uses_merge_base(monkeypatch):
    responses = [
        subprocess.CompletedProcess([], 0, "abc123\n", ""),
        subprocess.CompletedProcess([], 0, "", ""),
    ]
    module, calls = _scope_module(monkeypatch, responses)

    module.test_ac16_protected_implementation_files_are_unchanged_from_main()

    assert calls[0] == ["/test/git", "merge-base", "main", "HEAD"]
    assert calls[1] == [
        "/test/git",
        "diff",
        "--name-only",
        "abc123",
        "--",
        "sportscut/export.py",
        "tests/conftest.py",
    ]
    assert calls[1][3] != "main"


@pytest.mark.parametrize(
    ("returncode", "stdout"), [(128, ""), (0, "")], ids=["failure", "empty"]
)
def test_ac8_scope_check_skips_without_main(returncode, stdout, monkeypatch):
    responses = [subprocess.CompletedProcess([], returncode, stdout, "fatal")]
    module, calls = _scope_module(monkeypatch, responses)

    with pytest.raises(pytest.skip.Exception, match="main is required for scope check"):
        module.test_ac16_protected_implementation_files_are_unchanged_from_main()

    assert len(calls) == 1


def test_ac8_scope_check_still_fails_for_changed_protected_file(monkeypatch):
    responses = [
        subprocess.CompletedProcess([], 0, "abc123\n", ""),
        subprocess.CompletedProcess([], 0, "sportscut/export.py\n", ""),
    ]
    module, _ = _scope_module(monkeypatch, responses)

    with pytest.raises(AssertionError):
        module.test_ac16_protected_implementation_files_are_unchanged_from_main()


def test_ac10_protected_paths_untouched_and_no_tracked_mp4():
    if _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip().startswith("office/T-042"):
        changed = _git("diff", "--name-only", _merge_base(), "--", *PROTECTED_FILES)
        assert changed.returncode == 0, changed.stderr
        assert changed.stdout == ""

    media = _git("ls-files", "*.mp4")
    assert media.returncode == 0, media.stderr
    assert media.stdout == ""
