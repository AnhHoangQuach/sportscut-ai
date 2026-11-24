import json
from collections.abc import Iterable
from pathlib import Path

from sportscut.detect import find_highlights
from sportscut.events.scoreboard import tag_goals
from sportscut.export import MANIFEST_NAME, export_clips
from sportscut.media import MediaError, has_audio, require_ffmpeg
from sportscut.ranking import select_segments


class PipelineError(Exception):
    """The input video or options are invalid."""


def run(
    video: str | Path,
    out_dir: str | Path,
    top: int = 10,
    min_len: float = 10,
    max_len: float = 30,
    events: Iterable[str] | None = None,
) -> list[dict]:
    if top < 1:
        raise PipelineError("top must be >= 1")
    require_ffmpeg()
    try:
        if not has_audio(video):
            raise PipelineError(f"no audio stream in {video}")
        candidates = find_highlights(
            video, top=None, min_len=min_len, max_len=max_len
        )
        candidates = tag_goals(
            video, candidates, min_len=min_len, max_len=max_len
        )
        segments = select_segments(candidates, top=top, events=events)
    except (MediaError, ValueError) as exc:
        raise PipelineError(str(exc)) from exc

    export_clips(video, segments, out_dir)
    manifest = Path(out_dir) / MANIFEST_NAME
    return json.loads(manifest.read_text(encoding="utf-8"))
