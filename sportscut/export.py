import json
from pathlib import Path

from sportscut.media import cut_clip
from sportscut.models import Segment

MANIFEST_NAME = "highlights.json"


def export_clips(
    video: str | Path, segments: list[Segment], out_dir: str | Path
) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ordered = sorted(segments, key=lambda segment: (segment.start, segment.end))
    clips = []
    entries = []
    for index, segment in enumerate(ordered, 1):
        name = f"clip_{index:02d}.mp4"
        clips.append(cut_clip(video, segment.start, segment.end, out / name))
        entries.append({**segment.to_dict(), "file": name})
    (out / MANIFEST_NAME).write_text(
        json.dumps(entries, indent=2) + "\n", encoding="utf-8"
    )
    return clips
