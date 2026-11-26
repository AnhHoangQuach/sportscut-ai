"""T-044 Tester acceptance tests.

Only checks that stay true after the merge and on later branches: no file
freezing or hash checks (those are verified by command in TEST_REPORT.md).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ROUND2 = ROOT / "tests" / "test_t042_round2_acceptance.py"
T023 = ROOT / "tests" / "test_t023_acceptance.py"
EVAL_CROP_BUILD = ROOT / "tests" / "fixtures" / "eval_crop" / "build.py"
CROP_HEADING = "Video dọc 9:16: đo khung cắt (eval-crop)"
CASES = ["long_pass", "occluded", "slow_dribble", "white_distractor"]
AC10_FILES = [
    "tests/test_t023_acceptance.py",
    "tests/test_t042_acceptance.py",
    "tests/test_t042_round2_acceptance.py",
    "tests/test_t042_tester_acceptance.py",
    "tests/test_t044_acceptance.py",
]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _readme_crop_section() -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"## {CROP_HEADING}" in readme
    return readme.split(f"## {CROP_HEADING}", 1)[1]


def _readme_baseline() -> dict:
    section = _readme_crop_section()
    return json.loads(section.split("```json", 1)[1].split("```", 1)[0])


def _without_timings(report: dict) -> dict:
    clean = json.loads(json.dumps(report))
    clean.pop("seconds_per_min", None)
    for clip in clean["per_clip"]:
        clip.pop("seconds_per_min", None)
    return clean


# (a) T-019 Step 0 markers -------------------------------------------------


def test_a_t019_step0_markers_present():
    reframe_src = (ROOT / "sportscut" / "reframe.py").read_text(encoding="utf-8")
    assert "def plan_crop" in reframe_src
    assert "def sample_times" in reframe_src
    assert "def probe_size" in (ROOT / "sportscut" / "media.py").read_text(
        encoding="utf-8"
    )
    assert (ROOT / "sportscut" / "eval_crop.py").is_file()
    assert EVAL_CROP_BUILD.is_file()
    assert "eval-crop" in (ROOT / "sportscut" / "cli.py").read_text(encoding="utf-8")
    assert (ROOT / "tests" / "test_t017_acceptance.py").is_file()


def test_a_public_functions_importable():
    from sportscut import eval_crop, media, reframe

    assert callable(reframe.plan_crop)
    assert callable(reframe.sample_times)
    assert callable(reframe.crop_width)
    assert callable(media.probe_size)
    assert callable(media.sample_top_band)  # main's T-013 helper is kept
    assert callable(eval_crop.evaluate_dir)


def test_a_cli_eval_crop_help_exits_zero(capsys):
    from sportscut import cli

    try:
        code = cli.main(["eval-crop", "--help"])
    except SystemExit as exc:
        code = exc.code
    assert code in (0, None)
    out = capsys.readouterr().out
    assert "DIRECTORY" in out
    assert "--json" in out


def test_a_t019_step0_shell_command_prints_ready():
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("sh is required")
    command = (
        "test -f sportscut/reframe.py && grep -q 'def plan_crop' sportscut/reframe.py"
        " && grep -q 'def sample_times' sportscut/reframe.py"
        " && grep -q 'def probe_size' sportscut/media.py"
        " && test -f sportscut/eval_crop.py"
        " && test -f tests/fixtures/eval_crop/build.py"
        " && grep -q 'eval-crop' sportscut/cli.py"
        " && test -f tests/test_t017_acceptance.py && echo READY"
    )
    result = subprocess.run(
        [sh, "-c", command], cwd=ROOT, text=True, capture_output=True, check=False
    )
    assert result.stdout == "READY\n"


# CLI edge cases from the user side (T-017 AC12/AC17 contract) --------------


def test_cli_eval_crop_empty_directory_exits_2(tmp_path, capsys):
    from sportscut import cli

    assert cli.main(["eval-crop", str(tmp_path), "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("sportscut eval-crop: error: ")
    assert captured.out == ""


def test_cli_eval_crop_missing_directory_exits_2(tmp_path, capsys):
    from sportscut import cli

    assert cli.main(["eval-crop", str(tmp_path / "nope")]) == 2
    assert capsys.readouterr().err.startswith("sportscut eval-crop: error: ")


def test_cli_eval_crop_case_without_clip_exits_2_with_build_hint(tmp_path, capsys):
    from sportscut import cli

    case = tmp_path / "only_labels"
    case.mkdir()
    (case / "labels.json").write_text(json.dumps([{"t": 0.0, "ball": None}]))
    assert cli.main(["eval-crop", str(tmp_path), "--json"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("sportscut eval-crop: error: ")
    assert "run python tests/fixtures/eval_crop/build.py" in err


# (b) round-2 test_ac3 is safe on main (empty numstat) and still active ------


def _round2_with_numstat(monkeypatch, stdout: str):
    module = _load("t042_round2_under_test", ROUND2)
    calls = []

    def fake_git(*args):
        calls.append(list(args))
        return subprocess.CompletedProcess(list(args), 0, stdout=stdout, stderr="")

    monkeypatch.setattr(module, "_merge_base", lambda: "abc123")
    monkeypatch.setattr(module, "_git", fake_git)
    return module, calls


def test_b_round2_ac3_passes_when_numstat_is_empty(monkeypatch):
    module, calls = _round2_with_numstat(monkeypatch, "")
    module.test_ac3_shared_files_are_append_only()
    assert calls == [["diff", "--numstat", "abc123", "--", *module.SHARED_FILES]]


def test_b_round2_ac3_passes_for_pure_additions(monkeypatch):
    module, _ = _round2_with_numstat(monkeypatch, "23\t0\tsportscut/media.py\n")
    module.test_ac3_shared_files_are_append_only()


def test_b_round2_ac3_still_rejects_deleted_lines(monkeypatch):
    module, _ = _round2_with_numstat(
        monkeypatch, "23\t0\tsportscut/media.py\n5\t3\tsportscut/cli.py\n"
    )
    with pytest.raises(AssertionError):
        module.test_ac3_shared_files_are_append_only()


# (c) test_t023 AC16 uses the merge base and main's protected list ----------


def _t023_with_runs(monkeypatch, responses):
    module = _load("t023_under_test_t044", T023)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        return responses[len(calls) - 1]

    monkeypatch.setattr(module.shutil, "which", lambda name, **kwargs: "git")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return module, calls


def _done(code: int, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr=stderr)


PROTECTED = ["sportscut/export.py", "tests/conftest.py"]


def test_c_t023_ac16_exact_calls_and_clean_pass(monkeypatch):
    module, calls = _t023_with_runs(
        monkeypatch, [_done(0, "abc123\n"), _done(0, "")]
    )
    module.test_ac16_protected_implementation_files_are_unchanged_from_main()
    assert calls == [
        ["git", "merge-base", "main", "HEAD"],
        ["git", "diff", "--name-only", "abc123", "--", *PROTECTED],
    ]


@pytest.mark.parametrize(
    "base", [_done(128, "", "fatal: Not a valid object name main"), _done(0, "")]
)
def test_c_t023_ac16_skips_without_merge_base(monkeypatch, base):
    module, calls = _t023_with_runs(monkeypatch, [base])
    with pytest.raises(pytest.skip.Exception, match="main is required for scope check"):
        module.test_ac16_protected_implementation_files_are_unchanged_from_main()
    assert calls == [["git", "merge-base", "main", "HEAD"]]


def test_c_t023_ac16_fails_when_protected_file_changed(monkeypatch):
    module, _ = _t023_with_runs(
        monkeypatch, [_done(0, "abc123\n"), _done(0, "pyproject.toml\n")]
    )
    with pytest.raises(AssertionError):
        module.test_ac16_protected_implementation_files_are_unchanged_from_main()


# (d) README eval-crop section and baseline ---------------------------------


def test_d_readme_crop_section_and_baseline_values():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    headings = [line[3:].strip() for line in readme.splitlines() if line.startswith("## ")]
    assert CROP_HEADING in headings
    baseline = _readme_baseline()
    assert baseline["ball_in_crop"] == 0.2821
    assert baseline["players_in_crop"] == 0.4024
    assert baseline["jitter"] == 0.0
    assert [clip["clip"] for clip in baseline["per_clip"]] == CASES
    section = _readme_crop_section()
    assert "python tests/fixtures/eval_crop/build.py" in section
    assert "python -m sportscut eval-crop tests/fixtures/eval_crop --json" in section


def test_d_readme_keeps_main_web_section():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "Trang trả về lỗi 404 nếu `JOB_ID` không tồn tại." in readme


# (e) Building the fixtures and running eval-crop reproduces the baseline ----


def test_e_eval_crop_cli_on_built_fixtures_matches_readme(tmp_path):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe are required")
    build = _load("eval_crop_build_t044", EVAL_CROP_BUILD)
    clips = build.build_all(tmp_path)
    assert sorted(p.parent.name for p in clips) == CASES
    result = subprocess.run(
        [sys.executable, "-m", "sportscut", "eval-crop", str(tmp_path), "--json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1
    report = json.loads(lines[0])
    assert list(report) == [
        "ball_in_crop", "players_in_crop", "jitter", "seconds_per_min", "per_clip"
    ]
    assert report["ball_in_crop"] == 0.2821
    assert report["players_in_crop"] == 0.4024
    assert report["jitter"] == 0.0
    assert _without_timings(report) == _without_timings(_readme_baseline())


# (f) AC10: no two-dot `main` in scope/diff tests ---------------------------


def test_f_no_two_dot_main_in_scope_tests():
    grep = shutil.which("grep")
    if grep is None:
        pytest.skip("grep is required")
    pattern = '"(--name-only|--numstat|--stat|--quiet)", "main"'
    result = subprocess.run(
        [grep, "-n", "-E", pattern, *AC10_FILES],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert result.stdout == ""
