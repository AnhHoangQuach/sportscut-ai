import json
from pathlib import Path

from sportscut.detect import find_highlights
from sportscut.export import MANIFEST_NAME, export_clips
from sportscut.media import MediaError, has_audio, require_ffmpeg


class PipelineError(Exception):
    """The input video or options are invalid."""


def run(
    video: str | Path,
    out_dir: str | Path,
    top: int = 10,
    min_len: float = 10,
    max_len: float = 30,
) -> list[dict]:
    require_ffmpeg()
    try:
        if not has_audio(video):
            raise PipelineError(f"no audio stream in {video}")
        segments = find_highlights(
            video, top=top, min_len=min_len, max_len=max_len
        )
    except (MediaError, ValueError) as exc:
        raise PipelineError(str(exc)) from exc

    export_clips(video, segments, out_dir)
    manifest = Path(out_dir) / MANIFEST_NAME
    return json.loads(manifest.read_text(encoding="utf-8"))
