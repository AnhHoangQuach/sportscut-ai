import json
import logging
from collections.abc import Iterable
from pathlib import Path

from sportscut import media
from sportscut import reframe
from sportscut import subtitles
from sportscut import vertical as vertical_mod
from sportscut.commentary import script
from sportscut.commentary import voiceover as voiceover_mod
from sportscut.commentary.facts import facts_from_entry
from sportscut.detect import find_highlights
from sportscut.events.audio_cues import tag_saves
from sportscut.events.incidents import tag_incidents
from sportscut.events.scoreboard import tag_goals
from sportscut.export import MANIFEST_NAME, export_clips
from sportscut.media import MediaError, has_audio, require_ffmpeg
from sportscut.ranking import select_segments

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


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
    score_box=None,
    transcriber=None,
    voiceover: bool = False,
    synthesizer=None,
    match=None,
) -> list[dict]:
    if top < 1:
        raise PipelineError("top must be >= 1")
    if transcriber is not None and not vertical:
        raise PipelineError("transcriber needs vertical=True")
    if synthesizer is not None and not voiceover:
        raise PipelineError("synthesizer needs voiceover=True")
    if match is not None:
        try:
            facts_from_entry({"start": 0, "end": 1, "event": "other"}, match)
        except ValueError as exc:
            raise PipelineError(str(exc)) from exc
    require_ffmpeg()
    try:
        if not has_audio(video):
            raise PipelineError(f"no audio stream in {video}")
        if score_box is not None:
            if not vertical:
                raise PipelineError("score_box needs vertical=True")
            score_box = vertical_mod.check_score_box(score_box, *media.probe_size(video))
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
            box = score_box if score_box is not None else vertical_mod.find_score_box(clip)
            if box is None:
                logger.warning(
                    "no scoreboard found in %s; %s has no score overlay "
                    "(pass --score-box x,y,w,h to set it)",
                    entry["file"], rel,
                )
            caption = vertical_mod.caption_text(entry["event"], entry["start"], entry["end"])
            extra = {
                key: value
                for key, value in (("score_box", box), ("caption", caption))
                if value is not None
            }
            if transcriber is not None:
                try:
                    cues = subtitles.layout(subtitles.transcribe(clip, transcriber))
                except subtitles.TranscriptionError as exc:
                    raise PipelineError(str(exc)) from exc
                subtitles.write_srt(cues, (Path(out_dir) / rel).with_suffix(".srt"))
                if cues:
                    extra["subtitles"] = cues
            vertical_mod.render_vertical(clip, crop_path, Path(out_dir) / rel, **extra)
            entry["vertical_file"] = rel
    if voiceover:
        for entry in entries:
            lines = _write_script(Path(out_dir), entry, match)
            if synthesizer is not None:
                _write_voiceover(Path(out_dir), entry, lines, synthesizer)
    if vertical or voiceover:
        manifest.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return entries


def _write_voiceover(out_dir: Path, entry: dict, lines, synthesizer) -> None:
    stem = Path(entry["file"]).stem
    targets = [(out_dir / entry["file"], out_dir / f"{stem}.vo.mp4")]
    if "vertical_file" in entry:
        targets.append((out_dir / entry["vertical_file"], out_dir / "vertical" / f"{stem}.vo.mp4"))
    try:
        voiceover_mod.make_voiceover(lines, synthesizer, targets)
    except voiceover_mod.SynthesisError as exc:
        raise PipelineError(f"{entry['file']}: {exc}") from exc
    entry["voiceover_file"] = f"{stem}.vo.mp4"
    if "vertical_file" in entry:
        entry["vertical_voiceover_file"] = f"vertical/{stem}.vo.mp4"


def _write_script(out_dir: Path, entry: dict, match) -> list[tuple[float, str]]:
    clip = out_dir / entry["file"]
    clip_len = entry["end"] - entry["start"]
    peak = script.audio_peak(media.extract_audio(clip), clip_len)
    used = peak if peak is not None else script.default_peak(clip_len)
    lines = script.write_script(facts_from_entry(entry, match), clip_len, "template", peak=used)
    record = {
        "clip": entry["file"],
        "clip_len": clip_len,
        "peak": used,
        "backend": "template",
        "lines": [{"start": s, "end": s + script.speech_seconds(t), "text": t} for s, t in lines],
    }
    name = f"{Path(entry['file']).stem}.script.json"
    (out_dir / name).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    entry["script_file"] = name
    return lines
