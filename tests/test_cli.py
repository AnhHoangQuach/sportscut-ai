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
    assert "cut" in captured.out
    assert "serve" in captured.out
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
    assert all(set(item) == {"start", "end", "score", "reason", "event", "event_confidence"} for item in items)
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


def test_cut_end_to_end(burst_video, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["cut", str(burst_video), "--out", str(out)]) == 0
    captured = capsys.readouterr()
    expected = [str(out / f"clip_{i:02d}.mp4") for i in range(1, 4)]
    assert captured.out.splitlines() == expected
    assert captured.err == ""
    assert all(Path(path).is_file() for path in expected)
    manifest = json.loads((out / "highlights.json").read_text())
    assert [entry["file"] for entry in manifest] == [Path(path).name for path in expected]


def test_cut_passes_options(burst_video, tmp_path, capsys):
    out = tmp_path / "out"
    args = ["cut", str(burst_video), "--out", str(out), "--top", "1", "--min-len", "4", "--max-len", "6"]
    assert main(args) == 0
    assert capsys.readouterr().out.splitlines() == [str(out / "clip_01.mp4")]
    entry = json.loads((out / "highlights.json").read_text())[0]
    assert entry["end"] - entry["start"] == pytest.approx(6, abs=0.01)


def test_cut_non_video_exits_nonzero(require_ffmpeg, tmp_path):
    bad = tmp_path / "bad.mp4"; bad.write_text("not a video")
    out = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "sportscut", "cut", str(bad), "--out", str(out)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith(f"sportscut: error: ffprobe failed for {bad}: ")
    assert "Traceback" not in result.stderr
    assert not (out / "highlights.json").exists()


def test_cut_requires_out(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["cut", "x.mp4"])
    assert exc.value.code == 2


def test_serve_defaults_call_uvicorn(monkeypatch):
    import uvicorn
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: calls.append((a, k)))
    assert main(["serve"]) == 0
    from sportscut.api import app
    assert calls == [((app,), {"host": "127.0.0.1", "port": 8000})]


def test_serve_custom_host_port(monkeypatch):
    import uvicorn
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: calls.append((a, k)))
    assert main(["serve", "--host", "0.0.0.0", "--port", "9001"]) == 0
    assert calls[0][1] == {"host": "0.0.0.0", "port": 9001}


def test_serve_without_api_extra_exits_1(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    assert main(["serve"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "sportscut: error: the API needs the [api] extra: "
        "pip install 'sportscut[api]'\n"
    )


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
