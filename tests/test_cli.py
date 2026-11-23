from pathlib import Path
import json
import subprocess
import sys

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
    assert "detect" in captured.out
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


def test_detect_json(burst_video, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["detect", str(burst_video), "--json"]) == 0
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1
    items = json.loads(captured.out)
    assert len(items) == 3
    assert all(set(item) == {"start", "end", "score", "reason"} for item in items)
    assert captured.err == ""


def test_detect_passes_options(burst_video, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["detect", str(burst_video), "--top", "1", "--min-len", "4", "--max-len", "6", "--json"]
    assert main(args) == 0
    item = json.loads(capsys.readouterr().out)[0]
    assert item["end"] - item["start"] == pytest.approx(6, abs=0.01)


def test_detect_text_output(burst_video, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["detect", str(burst_video)]) == 0
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 3
    assert all(len(line.split("\t")) == 4 for line in captured.out.splitlines())
    assert captured.err == ""


def test_detect_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "missing.mp4"
    assert main(["detect", str(path), "--json"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"sportscut: error: media file not found: {path}\n"


def test_detect_invalid_options(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "missing.mp4"
    assert main(["detect", str(path), "--min-len", "20", "--max-len", "10"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "min_len must be <= max_len" in captured.err


@pytest.mark.parametrize("kind", ["missing", "empty", "no_clip"])
def test_eval_player_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str) -> None:
    path = tmp_path / kind
    if kind != "missing":
        path.mkdir()
    if kind == "no_clip":
        case = path / "case"
        case.mkdir()
        (case / "labels.json").write_text('{"touches": []}')
    assert main(["eval-player", str(path), "--json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "sportscut eval-player: error:" in captured.err
    if kind == "no_clip":
        assert "build.py" in captured.err
