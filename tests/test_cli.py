import subprocess
import sys
from pathlib import Path

import pytest

from sportscut.cli import main


def test_version_flag_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == "sportscut 0.1.0\n"
    assert captured.err == ""


def test_no_args_prints_help_and_returns_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0

    captured = capsys.readouterr()
    assert "usage: sportscut" in captured.out
    assert captured.err == ""


def test_module_entry_point() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "sportscut", "--version"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "sportscut 0.1.0\n"
    assert result.stderr == ""
