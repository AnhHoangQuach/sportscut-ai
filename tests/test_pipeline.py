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


# T-043: vertical 9:16 rendering (appended)
import sportscut.reframe  # noqa: E402
import sportscut.vertical  # noqa: E402


def test_run_vertical_writes_9_16_clip_and_manifest_key(burst_video, tmp_path):
    out = tmp_path / "out"

    entries = run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True)

    assert len(entries) == 1
    assert list(entries[0]) == [
        "start", "end", "score", "reason", "event", "event_confidence",
        "file", "vertical_file",
    ]
    assert entries[0]["file"] == "clip_01.mp4"
    assert entries[0]["vertical_file"] == "vertical/clip_01.mp4"
    assert entries == json.loads((out / "highlights.json").read_text())
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=codec_name,width,height", "-of", "csv=p=0",
         str(out / "vertical" / "clip_01.mp4")],
        check=True, capture_output=True, text=True,
    )
    assert probe.stdout.strip() == "h264,1080,1920"


def test_run_vertical_forwards_plan_crop_result(burst_video, tmp_path, monkeypatch):
    out = tmp_path / "out"
    sentinel = object()
    planned = []
    rendered = []

    def fake_plan(clip):
        planned.append(clip)
        return sentinel

    def fake_render(clip, crop_path, dest):
        rendered.append((clip, crop_path, dest))
        return dest

    monkeypatch.setattr(sportscut.reframe, "plan_crop", fake_plan)
    monkeypatch.setattr(sportscut.vertical, "render_vertical", fake_render)

    entries = run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True)

    assert planned == [out / "clip_01.mp4"]
    assert rendered == [
        (out / "clip_01.mp4", sentinel, out / "vertical" / "clip_01.mp4")
    ]
    assert entries[0]["vertical_file"] == "vertical/clip_01.mp4"


def test_run_default_never_renders_vertical(burst_video, tmp_path, monkeypatch):
    out = tmp_path / "out"

    def fail(*args, **kwargs):
        pytest.fail("vertical stage must not run by default")

    monkeypatch.setattr(sportscut.reframe, "plan_crop", fail)
    monkeypatch.setattr(sportscut.vertical, "render_vertical", fail)

    entries = run(burst_video, out, top=1, min_len=4, max_len=6)

    assert not (out / "vertical").exists()
    assert entries and all("vertical_file" not in entry for entry in entries)
    assert entries == json.loads((out / "highlights.json").read_text())


# T-021: scoreboard overlay and caption in the vertical stage (appended)
import logging  # noqa: E402

import sportscut.media  # noqa: E402

GOAL = Segment(2.0, 8.0, 1.0, "r", "goal", 0.9)


def _one_goal(monkeypatch):
    monkeypatch.setattr(pipeline, "select_segments", lambda candidates, top, events: [GOAL])


def _record_render(monkeypatch):
    rendered = []

    def fake_render(clip, crop_path, dest, **kw):
        rendered.append((clip, crop_path, dest, kw))
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        return dest

    monkeypatch.setattr(sportscut.vertical, "render_vertical", fake_render)
    return rendered


def test_run_vertical_passes_caption_kwarg(burst_video, tmp_path, monkeypatch):
    _one_goal(monkeypatch)
    rendered = _record_render(monkeypatch)
    out = tmp_path / "out"

    entries = run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True)

    assert entries[0]["event"] == "goal"
    assert [r[3] for r in rendered] == [{"caption": "BÀN THẮNG · 1'"}]
    assert rendered[0][2] == out / "vertical" / "clip_01.mp4"


def test_run_vertical_manual_box_skips_detection(burst_video, tmp_path, monkeypatch):
    _one_goal(monkeypatch)
    rendered = _record_render(monkeypatch)
    monkeypatch.setattr(
        sportscut.vertical, "find_score_box",
        lambda clip: pytest.fail("detection must not run with a manual box"),
    )

    run(burst_video, tmp_path / "out", top=1, min_len=4, max_len=6,
        vertical=True, score_box=(8, 4, 44, 16))

    assert [r[3] for r in rendered] == [
        {"score_box": (8, 4, 44, 16), "caption": "BÀN THẮNG · 1'"}
    ]


def test_run_vertical_passes_detected_box(burst_video, tmp_path, monkeypatch):
    rendered = _record_render(monkeypatch)
    seen = []

    def fake_find(clip):
        seen.append(clip)
        return (2, 2, 20, 10)

    monkeypatch.setattr(sportscut.vertical, "find_score_box", fake_find)
    out = tmp_path / "out"

    run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True)

    assert seen == [out / "clip_01.mp4"]
    assert [r[3] for r in rendered] == [{"score_box": (2, 2, 20, 10)}]


def test_run_vertical_caption_reaches_filter(burst_video, tmp_path, monkeypatch):
    _one_goal(monkeypatch)
    filters = []

    def fake_filter(clip, video_filter, dest):
        filters.append(video_filter)
        return Path(dest)

    monkeypatch.setattr(sportscut.media, "find_font", lambda: Path("/fonts/DejaVuSans.ttf"))
    monkeypatch.setattr(sportscut.media, "filter_video", fake_filter)

    run(burst_video, tmp_path / "out", top=1, min_len=4, max_len=6, vertical=True)

    assert len(filters) == 1
    assert "text=BÀN THẮNG · 1\\\\\\'" in filters[0]


def test_run_vertical_warns_when_no_board(burst_video, tmp_path, monkeypatch, caplog):
    rendered = _record_render(monkeypatch)
    out = tmp_path / "out"

    with caplog.at_level(logging.WARNING, logger="sportscut.pipeline"):
        entries = run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True)

    records = [r for r in caplog.records if r.name == "sportscut.pipeline"]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    message = records[0].getMessage()
    assert "no scoreboard found in clip_01.mp4" in message
    assert "--score-box" in message
    assert [r[3] for r in rendered] == [{}]
    assert entries[0]["vertical_file"] == "vertical/clip_01.mp4"


def test_pipeline_logger_has_null_handler():
    handlers = logging.getLogger("sportscut.pipeline").handlers
    assert any(isinstance(h, logging.NullHandler) for h in handlers)


def test_run_out_of_frame_box_raises_before_export(burst_video, tmp_path):
    out = tmp_path / "out"
    with pytest.raises(PipelineError) as exc:
        run(burst_video, out, top=1, min_len=4, max_len=6,
            vertical=True, score_box=(0, 0, 200, 10))
    assert str(exc.value) == "invalid score box: 0,0,200,10 does not fit the 160x120 frame"
    assert not (out / "clip_01.mp4").exists()


def test_run_score_box_needs_vertical(burst_video, tmp_path):
    out = tmp_path / "out"
    with pytest.raises(PipelineError) as exc:
        run(burst_video, out, top=1, min_len=4, max_len=6, score_box=(0, 0, 20, 10))
    assert str(exc.value) == "score_box needs vertical=True"
    assert not (out / "clip_01.mp4").exists()
