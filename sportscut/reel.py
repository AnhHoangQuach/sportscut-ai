import json
import math
import tempfile
from pathlib import Path

from sportscut import player
from sportscut.export import export_clips
from sportscut.media import concat_clips, probe_duration
from sportscut.models import Segment


MANIFEST_NAME = "player.json"


def reel_name(query: player.PlayerQuery) -> str:
    return f"player_{query.team.lstrip('#')}_{query.number}.mp4"


def plan_windows(
    times: list[float],
    duration: float,
    pre: float,
    post: float,
    merge_gap: float,
) -> list[tuple[float, float]]:
    windows: list[tuple[float, float]] = []
    for time in sorted(times):
        start = max(0.0, time - pre)
        end = min(duration, time + post)
        if end <= start:
            continue
        if windows and (start < windows[-1][1] or start - windows[-1][1] < merge_gap):
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
    return windows


def make_player_reel(
    video,
    query: player.PlayerQuery,
    out_dir,
    pre: float = 3.0,
    post: float = 2.0,
    merge_gap: float = 4.0,
) -> dict:
    if not math.isfinite(pre) or pre < 0:
        raise ValueError("--pre must be >= 0")
    if not math.isfinite(post) or post < 0:
        raise ValueError("--post must be >= 0")
    if pre + post == 0:
        raise ValueError("--pre and --post cannot both be 0")
    if not math.isfinite(merge_gap) or merge_gap < 0:
        raise ValueError("--merge-gap must be >= 0")

    duration = probe_duration(video)
    touches = sorted(player.find_touches(video, query), key=lambda touch: touch.t)
    windows = plan_windows([touch.t for touch in touches], duration, pre, post, merge_gap)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = reel_name(query) if windows else None
    if windows:
        with tempfile.TemporaryDirectory(prefix=".sportscut-cuts-", dir=out) as tmp:
            segments = [Segment(start, end, 0.0, "touch") for start, end in windows]
            clips = export_clips(video, segments, tmp)
            concat_clips(clips, out / name)

    manifest_touches = []
    for touch in touches:
        own_start = max(0.0, touch.t - pre)
        own_end = min(duration, touch.t + post)
        containing = next(
            ((start, end) for start, end in windows if start <= own_start and own_end <= end),
            None,
        ) if own_end > own_start else None
        entry = touch.to_dict()
        entry["t"] = round(entry["t"], 3)
        entry.update({
            "start": None if containing is None else round(containing[0], 3),
            "end": None if containing is None else round(containing[1], 3),
        })
        manifest_touches.append(entry)

    manifest = {
        "query": {"team": query.team, "number": query.number},
        "touches": manifest_touches,
        "clips": [
            {"start": round(start, 3), "end": round(end, 3)}
            for start, end in windows
        ],
        "total_duration": round(sum(end - start for start, end in windows), 3),
        "reel": name,
    }
    (out / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest
