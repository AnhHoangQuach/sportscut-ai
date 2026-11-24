# T-003: Export segments as mp4 clips plus a JSON manifest

Request R-001. Plan: `docs/superpowers/plans/2026-11-23-t-003-export-segments-as-mp4-clips-plus.md`.

## Product Owner request

Tạo API POST /highlights nhận video, trả về danh sách đoạn highlight và file đã cắt

## Goal

Add `sportscut/export.py` with `export_clips(video, segments, out_dir) -> list[Path]`. It cuts each segment with ffmpeg into `clip_01.mp4`, `clip_02.mp4`, ... in time order and writes `highlights.json` (a list of segment dicts plus a `file` name). Re-encode with `-preset ultrafast` instead of `-c copy` so cuts land on the requested time and not the nearest keyframe; short clips keep this cheap. Tests: the given Segments on the synthetic video produce one file per segment, ffprobe duration matches within 0.5 s, and the manifest matches the segments. Assumptions: no concatenated `highlights.mp4` reel, because R-001 asks only for the cut files (YAGNI); it is easy to add later.

## Acceptance criteria

- AC1: `sportscut.media.cut_clip(path, start, end, dest) -> Path` exists. For a non-existent `path` it raises `MediaError` with exactly `media file not found: <path>`, even with PATH=/nonexistent. For an existing file with no ffmpeg on PATH it raises exactly `ffmpeg not found on PATH; install ffmpeg`.
- AC2: `cut_clip` on a text file named `bad.mp4` raises `MediaError` matching `^ffmpeg failed for <path>: .+`. No `CalledProcessError` or other exception type leaks.
- AC3: `cut_clip(synthetic_video, 3.2, 5.2, tmp/'c.mp4')` returns `tmp/'c.mp4'`. The file has `probe_duration` within 0.5 s of 2.0, a video stream whose ffprobe `codec_name` is `h264`, and one audio stream with `codec_name` `aac`. Its first frame (8x6 gray mean at t=0.05 s) is > 192 (white), which proves the cut did not snap to the 2.4 s black keyframe.
- AC4: `sportscut.export.export_clips(video, segments, out_dir) -> list[Path]` with segments given out of order `[Segment(3.5, 5.0, 2.0, 'scene'), Segment(0.5, 2.0, 1.5, 'audio')]` and a not-yet-existing nested `out_dir` creates the directory. It returns `[out_dir/'clip_01.mp4', out_dir/'clip_02.mp4']`, both files exist, and their `probe_duration`s are within 0.5 s of 1.5 and 1.5 for the segments sorted by start (0.5-2.0 then 3.5-5.0).
- AC5: After AC4, `out_dir/'highlights.json'` parses as a JSON list equal to `[{**s.to_dict(), 'file': f'clip_{i:02d}.mp4'} for i, s in enumerate(sorted_segments, 1)]`. Each `file` is a bare name that exists in `out_dir`.
- AC6: `export_clips(video, [], out_dir)` returns `[]`, writes `highlights.json` containing `[]`, and creates no `.mp4`.
- AC7: `export_clips(missing_path, [Segment(0, 1, 0, 'x')], out_dir)` raises `MediaError('media file not found: <path>')` and leaves no `highlights.json` in `out_dir`.
- AC8: `sportscut/export.py` does not import `subprocess`. All ffmpeg calls go through `sportscut.media`.
- AC9: `.venv/bin/python -m pytest -q` exits 0 with 0 failed, 0 errors and 0 skipped on a machine with ffmpeg+libx264. `PATH=/nonexistent .venv/bin/python -m pytest -q -rs` exits 0 with 0 failed and 0 errors, and every skip reason is exactly `ffmpeg and ffprobe are required on PATH`.
- AC10: After the suite, `git ls-files '*.mp4' '*.mkv' '*.wav'` is empty and no `.mp4`/`.wav`/`.mkv` exists in the worktree outside `.venv`.
- AC11: The diff touches only `sportscut/media.py`, `sportscut/export.py`, `tests/test_media.py`, `tests/test_export.py` (plus orchestrator-written `docs/superpowers/` records) and stays under 400 changed lines. The report quotes the red runs `cannot import name 'cut_clip'` and `No module named 'sportscut.export'`, each followed by a green run.

## Out of scope

- POST /highlights, FastAPI, uploads, HTTP response schemas
- A concatenated `highlights.mp4` reel or any concat step
- Highlight detection, scoring, merging/padding of overlapping or adjacent segments
- CLI subcommands (`sportscut cut`/`detect`/`eval`) and the eval set
- Clamping segments to video duration, cleaning stale clips from out_dir, configurable codec/preset/quality/naming, an encoder fallback when libx264 is missing
- Thumbnails, per-clip metadata beyond the Segment fields plus `file`, absolute paths in the manifest
- Parallel cutting, subprocess timeouts, progress reporting
- Changes to tests/conftest.py, tests/test_fixtures.py, pyproject.toml, .gitignore, agent-office/, AGENTS.md, CLAUDE.md

## Decisions

- T-003 (R-001): Cutting lives in `sportscut.media.cut_clip(path, start, end, dest) -> Path`, keeping T-036's rule that `sportscut.media` is the only module calling ffmpeg. `sportscut.export` only orders, names and writes the manifest.
- T-003 (R-001): Clips are re-encoded, never stream-copied. The args are `-ss <start> -i <src> -t <end-start> -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac -movflags +faststart`, with input-side seek and times formatted to 3 decimals. Cuts are frame-accurate and the files play in browsers.
- T-003 (R-001): Product clips require an ffmpeg built with libx264. If it is missing, the user gets the generic `ffmpeg failed for <path>: ...` MediaError; there is no encoder fallback. The synthetic test fixture stays mpeg4 per T-036.
- T-003 (R-001): `export_clips` sorts segments by (start, end), names clips `clip_01.mp4`, `clip_02.mp4`, ... (`clip_{i:02d}.mp4`, 1-based) and returns only the clip paths, in that order.
- T-003 (R-001): The manifest is `<out_dir>/highlights.json` (`MANIFEST_NAME`). It is a JSON list (indent=2, trailing newline, UTF-8) of `Segment.to_dict()` plus `file`, a bare file name relative to out_dir. It is written only after every cut succeeds; an empty segment list writes `[]`.
- T-003 (R-001): Segments are cut exactly as given: no merging, padding or clamping. Same-named files in out_dir are overwritten, and out_dir is created with parents.
- T-003 (R-001): Cut accuracy is tested by content, not only duration. A cut starting at 3.2 s must begin on a white frame, which a keyframe-snapped `-c copy` cut (snapping to 2.4 s) would fail.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`

## Updated by T-007

- `export_clips` accepts a backward-compatible keyword-only `version_suffix`. The
  empty default preserves `clip_NN.mp4`; edits accept only `_vN` for positive `N`
  and produce `clip_NN_vN.mp4` names in both files and the manifest.
- `Segment.score` may be `null` for manually edited segments. Detector-produced
  segments and default export behavior remain unchanged.

## Updated by T-023

- Updated by T-023: A manifest entry may be passed to `commentary.facts_from_entry` to build facts
  for title, caption and hashtag generation. The manifest schema and export
  behavior are unchanged.
