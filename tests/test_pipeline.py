import ast
import importlib.util
import json
import re
import subprocess
from pathlib import Path

import pytest

from sportscut import pipeline
from sportscut.media import MediaError, probe_duration
from sportscut.models import Segment
from sportscut.pipeline import PipelineError, run


@pytest.fixture(scope="module")
def pipeline_eval_set(tmp_path_factory, require_ffmpeg):
    build_path = Path(__file__).parent / "fixtures" / "eval" / "build.py"
    spec = importlib.util.spec_from_file_location("t013_pipeline_eval_build", build_path)
    assert spec is not None and spec.loader is not None
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    root = tmp_path_factory.mktemp("t013_pipeline_eval")
    build.build_all(root)
    return root


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
    assert all(set(entry) == {"start", "end", "score", "reason", "event", "event_confidence", "file"} for entry in entries)
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


def test_run_calls_tag_goals_between_detect_and_select(
    burst_video, tmp_path, monkeypatch
):
    calls = []
    candidate = Segment(0, 1, 3, "x")

    def fake_find(video, **kwargs):
        calls.append(("find", video, kwargs))
        return [candidate]

    def fake_tag(video, candidates, **kwargs):
        calls.append(("tag", video, candidates, kwargs))
        return list(candidates)

    def fake_select(candidates, **kwargs):
        calls.append(("select", candidates, kwargs))
        return list(candidates)

    monkeypatch.setattr(pipeline, "find_highlights", fake_find)
    monkeypatch.setattr(pipeline, "tag_goals", fake_tag)
    monkeypatch.setattr(pipeline, "select_segments", fake_select)

    run(burst_video, tmp_path / "out", top=2, min_len=4, max_len=6)

    assert [call[0] for call in calls] == ["find", "tag", "select"]
    assert calls[0][2] == {"top": None, "min_len": 4, "max_len": 6}
    assert calls[1] == (
        "tag",
        burst_video,
        [candidate],
        {"min_len": 4, "max_len": 6},
    )
    assert calls[2][2] == {"top": 2, "events": None}


def test_run_wraps_tag_goals_media_error(burst_video, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "find_highlights", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        pipeline,
        "tag_goals",
        lambda *args, **kwargs: (_ for _ in ()).throw(MediaError("tag failed")),
    )

    with pytest.raises(PipelineError, match="^tag failed$"):
        run(burst_video, tmp_path / "out")


def test_run_goals_only_on_fixture(pipeline_eval_set, tmp_path):
    out = tmp_path / "goals"

    entries = run(
        pipeline_eval_set / "goals_saves" / "video.mp4",
        out,
        events=["goal"],
    )

    assert len(entries) == 2
    assert all(entry["event"] == "goal" for entry in entries)
    assert all(entry["event_confidence"] == 0.9 for entry in entries)
    assert entries == json.loads((out / "highlights.json").read_text())
