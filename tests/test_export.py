import ast
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from sportscut.export import export_clips
from sportscut.media import MediaError, probe_duration
from sportscut.models import Segment


def _gray_mean(video: Path, time: float) -> float:
    args = ["ffmpeg", "-v", "error", "-nostdin", "-ss", str(time), "-i",
            str(video), "-frames:v", "1", "-vf", "scale=8:6,format=gray",
            "-f", "rawvideo", "pipe:1"]
    output = subprocess.run(args, check=True, capture_output=True).stdout
    assert len(output) == 48
    return float(np.frombuffer(output, np.uint8).mean())


def test_export_clips_cuts_one_file_per_segment_in_time_order(
    synthetic_video, tmp_path
):
    segments = [
        Segment(3.5, 5.0, 2.0, "scene"),
        Segment(0.5, 2.0, 1.5, "audio"),
    ]
    original_order = list(segments)
    out = tmp_path / "job" / "out"
    expected = [out / "clip_01.mp4", out / "clip_02.mp4"]

    assert export_clips(synthetic_video, segments, out) == expected
    assert segments == original_order
    assert all(path.is_file() for path in expected)
    assert [probe_duration(path) for path in expected] == pytest.approx(
        [1.5, 1.5], abs=0.5
    )
    assert _gray_mean(expected[0], 0.05) < 64
    assert _gray_mean(expected[1], 0.05) > 192


def test_export_clips_writes_manifest(synthetic_video, tmp_path):
    segments = [
        Segment(3.5, 5.0, 2.0, "scene"),
        Segment(0.5, 2.0, 1.5, "audio"),
    ]
    out = tmp_path / "out"
    export_clips(synthetic_video, segments, out)
    ordered = sorted(segments, key=lambda segment: (segment.start, segment.end))
    expected = [
        {**segment.to_dict(), "file": f"clip_{index:02d}.mp4"}
        for index, segment in enumerate(ordered, 1)
    ]
    manifest = json.loads((out / "highlights.json").read_text(encoding="utf-8"))
    assert manifest == expected
    assert all((out / entry["file"]).is_file() for entry in manifest)


def test_export_clips_version_suffix(synthetic_video, tmp_path):
    out = tmp_path / "out"
    segment = Segment(0.5, 2.0, None, "manual")

    assert export_clips(
        synthetic_video, [segment], out, version_suffix="_v1"
    ) == [out / "clip_01_v1.mp4"]
    assert json.loads((out / "highlights.json").read_text()) == [
        {**segment.to_dict(), "file": "clip_01_v1.mp4"}
    ]


@pytest.mark.parametrize(
    "suffix", ["v1", "_v0", "_v01", "_v-1", "../_v1", None, 1]
)
def test_export_clips_rejects_invalid_version_suffix(tmp_path, suffix):
    out = tmp_path / "out"

    with pytest.raises(ValueError, match="^invalid version suffix$"):
        export_clips("missing.mp4", [], out, version_suffix=suffix)

    assert not out.exists()


def test_export_clips_empty_segments(synthetic_video, tmp_path):
    out = tmp_path / "out"
    assert export_clips(synthetic_video, [], out) == []
    assert json.loads((out / "highlights.json").read_text(encoding="utf-8")) == []
    assert list(out.glob("*.mp4")) == []


def test_export_clips_missing_video_writes_no_manifest(tmp_path):
    video = tmp_path / "missing.mp4"
    out = tmp_path / "out"
    with pytest.raises(MediaError) as exc:
        export_clips(video, [Segment(0, 1, 0, "x")], out)
    assert str(exc.value) == f"media file not found: {video}"
    assert not (out / "highlights.json").exists()


def test_export_module_does_not_import_subprocess():
    source = Path(__file__).parents[1] / "sportscut" / "export.py"
    imports = [
        node for node in ast.walk(ast.parse(source.read_text(encoding="utf-8")))
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert all(
        not (
            (isinstance(node, ast.Import) and any(alias.name == "subprocess" for alias in node.names))
            or (isinstance(node, ast.ImportFrom) and node.module == "subprocess")
        )
        for node in imports
    )
