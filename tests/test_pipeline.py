import ast
import json
import re
import subprocess
from pathlib import Path

import pytest

from sportscut.media import MediaError, probe_duration
from sportscut.pipeline import PipelineError, run


def _video_only(tmp_path: Path) -> Path:
    path = tmp_path / "video_only.mp4"
    subprocess.run([
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
        "color=c=black:s=160x120:r=5:d=3", "-c:v", "mpeg4", "-q:v", "5",
        "-pix_fmt", "yuv420p", str(path),
    ], check=True)
    return path


def test_run_returns_manifest_entries(burst_video, tmp_path):
    out = tmp_path / "out"
    entries = run(burst_video, out)
    assert isinstance(entries, list) and len(entries) == 3
    assert all(set(entry) == {"start", "end", "score", "reason", "event", "file"} for entry in entries)
    assert [entry["file"] for entry in entries] == [f"clip_{i:02d}.mp4" for i in range(1, 4)]
    assert all((out / entry["file"]).is_file() for entry in entries)
    assert entries == json.loads((out / "highlights.json").read_text(encoding="utf-8"))
    assert [probe_duration(out / entry["file"]) for entry in entries] == pytest.approx([12] * 3, abs=0.5)


def test_run_passes_options(burst_video, tmp_path):
    entries = run(burst_video, tmp_path / "out", top=1, min_len=4, max_len=6)
    assert len(entries) == 1
    assert entries[0]["end"] - entries[0]["start"] == pytest.approx(6, abs=0.01)


def test_run_non_video_raises_pipeline_error(require_ffmpeg, tmp_path):
    path = tmp_path / "bad.mp4"; path.write_text("not a video")
    out = tmp_path / "out"
    with pytest.raises(PipelineError, match="^" + re.escape(f"ffprobe failed for {path}: ") + ".+"):
        run(path, out)
    assert not (out / "highlights.json").exists()


def test_run_no_audio_raises_pipeline_error(require_ffmpeg, tmp_path):
    path = _video_only(tmp_path); out = tmp_path / "out"
    with pytest.raises(PipelineError) as exc:
        run(path, out)
    assert str(exc.value) == f"no audio stream in {path}"
    assert not (out / "highlights.json").exists()


def test_run_missing_file_raises_pipeline_error(require_ffmpeg, tmp_path):
    path = tmp_path / "missing.mp4"
    with pytest.raises(PipelineError) as exc:
        run(path, tmp_path / "out")
    assert str(exc.value) == f"media file not found: {path}"


def test_run_invalid_options_raises_pipeline_error(burst_video, tmp_path):
    with pytest.raises(PipelineError) as exc:
        run(burst_video, tmp_path / "out", min_len=20, max_len=10)
    assert str(exc.value) == "min_len must be <= max_len"


def test_run_without_ffmpeg_raises_media_error(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(MediaError) as exc:
        run(tmp_path / "missing.mp4", tmp_path / "out")
    assert str(exc.value) == "ffmpeg not found on PATH; install ffmpeg"
    assert not isinstance(exc.value, PipelineError)


def test_pipeline_error_is_plain_exception():
    assert issubclass(PipelineError, Exception)
    assert not issubclass(PipelineError, (MediaError, ValueError))


def test_pipeline_module_does_not_import_subprocess():
    source = Path(__file__).parents[1] / "sportscut" / "pipeline.py"
    imports = [node for node in ast.walk(ast.parse(source.read_text())) if isinstance(node, (ast.Import, ast.ImportFrom))]
    assert all(not ((isinstance(node, ast.Import) and any(alias.name == "subprocess" for alias in node.names)) or (isinstance(node, ast.ImportFrom) and node.module == "subprocess")) for node in imports)
