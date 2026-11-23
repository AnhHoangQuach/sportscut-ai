"""Independent acceptance tests for T-004's public pipeline and CLI."""

import ast
import json
from pathlib import Path
import subprocess
import sys

import pytest

from sportscut.cli import main
from sportscut.media import MediaError, has_audio, probe_duration, require_ffmpeg
from sportscut.pipeline import PipelineError, run


def _video_only(path: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi",
            "-i", "color=c=black:s=160x120:r=5:d=2", "-c:v", "mpeg4",
            "-q:v", "5", "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _flat_audio_video(path: Path) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi",
            "-i", "color=c=black:s=160x120:r=5:d=3", "-f", "lavfi",
            "-i", "sine=frequency=440:sample_rate=44100:duration=3", "-map",
            "0:v", "-map", "1:a", "-c:v", "mpeg4", "-q:v", "5",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "3", str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def test_pipeline_contract_and_success_acceptance(burst_video: Path, tmp_path: Path) -> None:
    import sportscut.pipeline as pipeline

    assert PipelineError.__bases__ == (Exception,)
    tree = ast.parse(Path(pipeline.__file__).read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "subprocess" not in imported

    out = tmp_path / "default"
    entries = run(burst_video, out)
    assert entries == json.loads((out / "highlights.json").read_text(encoding="utf-8"))
    assert [entry["file"] for entry in entries] == [
        "clip_01.mp4", "clip_02.mp4", "clip_03.mp4"
    ]
    assert all(set(entry) == {"start", "end", "score", "reason", "event", "file"} for entry in entries)
    assert all((out / entry["file"]).is_file() for entry in entries)
    assert all(probe_duration(out / entry["file"]) == pytest.approx(12, abs=0.5) for entry in entries)

    custom = run(burst_video, tmp_path / "custom", top=1, min_len=4, max_len=6)
    assert len(custom) == 1
    assert custom[0]["end"] - custom[0]["start"] == pytest.approx(6, abs=0.01)


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("missing", "media file not found: {path}"),
        ("text", "ffprobe failed for {path}: "),
        ("silent", "no audio stream in {path}"),
    ],
)
def test_bad_inputs_are_pipeline_errors_without_output_acceptance(
    kind: str, message: str, tmp_path: Path
) -> None:
    video = tmp_path / f"{kind}.mp4"
    if kind == "text":
        video.write_text("not media", encoding="utf-8")
    elif kind == "silent":
        _video_only(video)
    out = tmp_path / "out"

    with pytest.raises(PipelineError) as caught:
        run(video, out)

    expected = message.format(path=video)
    if kind == "text":
        assert str(caught.value).startswith(expected)
        assert len(str(caught.value)) > len(expected)
    else:
        assert str(caught.value) == expected
    assert not (out / "highlights.json").exists()


def test_invalid_options_and_missing_tools_have_distinct_errors_acceptance(
    burst_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "invalid"
    with pytest.raises(PipelineError, match="^min_len must be <= max_len$"):
        run(burst_video, out, min_len=20, max_len=10)
    assert not (out / "highlights.json").exists()

    monkeypatch.setenv("PATH", str(tmp_path / "empty-path"))
    with pytest.raises(MediaError, match="^ffmpeg not found on PATH; install ffmpeg$") as caught:
        run(burst_video, tmp_path / "tools")
    assert not isinstance(caught.value, PipelineError)


def test_media_helpers_acceptance(synthetic_video: Path, tmp_path: Path) -> None:
    assert require_ffmpeg() is None
    assert has_audio(synthetic_video) is True
    assert has_audio(_video_only(tmp_path / "video-only.mp4")) is False

    missing = tmp_path / "missing.mp4"
    with pytest.raises(MediaError, match=f"^media file not found: {missing}$"):
        has_audio(missing)
    text = tmp_path / "text.mp4"
    text.write_text("hello", encoding="utf-8")
    with pytest.raises(MediaError, match=f"^ffprobe failed for {text}: .+"):
        has_audio(text)


def test_cut_cli_success_options_and_zero_segments_acceptance(
    burst_video: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "cut"
    assert main(["cut", str(burst_video), "--out", str(out), "--top", "1",
                 "--min-len", "4", "--max-len", "6"]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.splitlines() == [str(out / "clip_01.mp4")]
    manifest = json.loads((out / "highlights.json").read_text(encoding="utf-8"))
    assert len(manifest) == 1
    assert manifest[0]["end"] - manifest[0]["start"] == pytest.approx(6, abs=0.01)

    empty_out = tmp_path / "empty"
    flat_video = _flat_audio_video(tmp_path / "flat.mp4")
    assert main(["cut", str(flat_video), "--out", str(empty_out)]) == 0
    assert capsys.readouterr().out == ""
    assert json.loads((empty_out / "highlights.json").read_text(encoding="utf-8")) == []


def test_cut_cli_failure_help_and_required_out_acceptance(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_text("bad", encoding="utf-8")
    out = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, "-m", "sportscut", "cut", str(bad), "--out", str(out)],
        cwd=Path(__file__).parents[1],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith(f"sportscut: error: ffprobe failed for {bad}: ")
    assert "Traceback" not in result.stderr
    assert not (out / "highlights.json").exists()

    missing_out = subprocess.run(
        [sys.executable, "-m", "sportscut", "cut", "x.mp4"],
        cwd=Path(__file__).parents[1], text=True, capture_output=True, check=False,
    )
    assert missing_out.returncode == 2
    help_result = subprocess.run(
        [sys.executable, "-m", "sportscut"],
        cwd=Path(__file__).parents[1], text=True, capture_output=True, check=False,
    )
    assert help_result.returncode == 0
    assert "detect" in help_result.stdout and "cut" in help_result.stdout


def test_documentation_acceptance() -> None:
    root = Path(__file__).parents[1]
    t036 = root / "docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md"
    assert t036.read_text(encoding="utf-8").rstrip().endswith(
        "Updated by T-004: sportscut.media also exposes require_ffmpeg() "
        "(both tools on PATH, else MediaError) and has_audio(path) -> bool "
        "(ffprobe audio-stream check; ffprobe failures raise MediaError)."
    )
