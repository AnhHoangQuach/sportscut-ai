import importlib.util
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_t023_acceptance():
    path = ROOT / "tests" / "test_t023_acceptance.py"
    spec = importlib.util.spec_from_file_location("t023_acceptance_for_t042", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scope_check_diffs_from_merge_base(monkeypatch):
    module = _load_t023_acceptance()
    calls: list[list[str]] = []

    def record(args, **_kwargs):
        calls.append(args)
        stdout = "abc123\n" if args[1] == "merge-base" else ""
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(module.shutil, "which", lambda *_args, **_kwargs: "/usr/bin/git")
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


@pytest.mark.parametrize(
    ("returncode", "stdout"),
    [(128, "fatal: no main\n"), (0, "")],
)
def test_scope_check_skips_when_merge_base_is_unavailable(
    monkeypatch, returncode, stdout
):
    module = _load_t023_acceptance()
    result = subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")
    monkeypatch.setattr(module.shutil, "which", lambda *_args, **_kwargs: "/usr/bin/git")
    monkeypatch.setattr(module.subprocess, "run", lambda *_args, **_kwargs: result)

    with pytest.raises(pytest.skip.Exception, match="main is required for scope check"):
        module.test_ac16_protected_implementation_files_are_unchanged_from_main()


def test_scope_check_still_fails_for_a_changed_protected_file(monkeypatch):
    module = _load_t023_acceptance()
    results = iter(
        [
            subprocess.CompletedProcess([], 0, stdout="abc123\n", stderr=""),
            subprocess.CompletedProcess(
                [], 0, stdout="sportscut/export.py\n", stderr=""
            ),
        ]
    )
    monkeypatch.setattr(module.shutil, "which", lambda *_args, **_kwargs: "/usr/bin/git")
    monkeypatch.setattr(
        module.subprocess, "run", lambda *_args, **_kwargs: next(results)
    )

    with pytest.raises(AssertionError):
        module.test_ac16_protected_implementation_files_are_unchanged_from_main()
