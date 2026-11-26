import json
from collections.abc import Iterable
from pathlib import Path

from sportscut import reframe
from sportscut import vertical as vertical_mod
from sportscut.detect import find_highlights
from sportscut.events.audio_cues import tag_saves
from sportscut.events.incidents import tag_incidents
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
    vertical: bool = False,
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
        candidates = tag_incidents(video, candidates)
        candidates = tag_saves(video, candidates)
        segments = select_segments(candidates, top=top, events=events)
    except (MediaError, ValueError) as exc:
        raise PipelineError(str(exc)) from exc

    export_clips(video, segments, out_dir)
    manifest = Path(out_dir) / MANIFEST_NAME
    entries = json.loads(manifest.read_text(encoding="utf-8"))
    if vertical:
        for entry in entries:
            clip = Path(out_dir) / entry["file"]
            rel = f"vertical/{entry['file']}"
            crop_path = reframe.plan_crop(clip)
            vertical_mod.render_vertical(clip, crop_path, Path(out_dir) / rel)
            entry["vertical_file"] = rel
        manifest.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return entries
