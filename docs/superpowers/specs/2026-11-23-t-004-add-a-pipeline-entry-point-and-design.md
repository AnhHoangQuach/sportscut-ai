# T-004: Add a pipeline entry point and the `sportscut cut` CLI

Request R-001. Plan: `docs/superpowers/plans/2026-11-23-t-004-add-a-pipeline-entry-point-and.md`.

## Product Owner request

Tạo API POST /highlights nhận video, trả về danh sách đoạn highlight và file đã cắt

## Goal

Add `sportscut/pipeline.py` with `run(video, out_dir, top, min_len, max_len) -> list[dict]`. It calls `require_ffmpeg`, `find_highlights` and `export_clips`, and returns the manifest entries. The API will reuse it. Wire up `sportscut cut VIDEO --out DIR --top N --min-len --max-len`. Raise a clear `PipelineError` for unreadable or invalid input (ffprobe failure, no audio stream) so the CLI exits non-zero with a message and the API can map it to HTTP 400. Tests: an end-to-end CLI run on the synthetic video produces clips plus a manifest; a non-video file exits non-zero with a readable error.

## Acceptance criteria

- AC1: `sportscut/pipeline.py` defines `class PipelineError(Exception)`, which is not a subclass of MediaError or ValueError. It also defines `run(video, out_dir, top=10, min_len=10, max_len=30, events=None) -> list[dict]`, which returns a list equal to `json.loads(<out_dir>/highlights.json)`. Each entry has exactly the keys start, end, score, reason, event, event_confidence, file. `pipeline.py` does not import subprocess. (updated by T-010) (updated by T-012)
- AC2: `run(burst_video, out)` returns 3 entries named clip_01.mp4..clip_03.mp4. All three files exist, and each has a probed duration of 12 s ± 0.5 s. With `top=1, min_len=4, max_len=6` it returns exactly 1 entry, of length 6 ± 0.01 s.
- AC3: `run` raises PipelineError and writes no highlights.json in these cases: a non-video text file (message matches `^ffprobe failed for <path>: .+`), a video with no audio stream (message exactly `no audio stream in <path>`), a missing file (message exactly `media file not found: <path>`), and `min_len=20, max_len=10` (message `min_len must be <= max_len`).
- AC4: With ffmpeg/ffprobe missing from PATH, `run` raises MediaError (`ffmpeg not found on PATH; install ffmpeg`), not PipelineError.
- AC5: `sportscut.media.has_audio(path)` returns True for the synthetic_video fixture and False for a video-only mp4. It raises MediaError `media file not found: <path>` for a missing file, and a MediaError matching `^ffprobe failed for <path>: .+` for a text file. `require_ffmpeg()` returns None when both tools are on PATH and raises MediaError when one is missing.
- AC6: `main(['cut', str(burst_video), '--out', str(out)])` returns 0. Stdout is exactly the 3 lines `str(out/'clip_0N.mp4')` (N=1..3), stderr is empty, the files exist, and highlights.json has 3 entries. `--top 1 --min-len 4 --max-len 6` gives 1 line and 1 entry of length ≈ 6 s.
- AC7: Running `python -m sportscut cut <text file> --out <dir>` as a subprocess exits with 1. Stdout is empty, stderr starts with `sportscut: error: ffprobe failed for <path>: ` and contains no `Traceback`, and `<dir>/highlights.json` does not exist. `sportscut cut x.mp4` without `--out` exits with 2.
- AC8: All existing tests pass unchanged. That includes every `detect` test and the no-args help test, which additionally asserts that `cut` appears in the help. `python -m pytest -q` reports 0 failures.
- AC9: The T-036 design spec ends with an `Updated by T-004` note about `require_ffmpeg` and `has_audio`. The diff touches only the files listed in `files`, stays under 400 changed lines, and changes nothing under agent-office/, pyproject.toml or tests/conftest.py.

## Out of scope

- The HTTP API (POST /highlights, upload handling, the 400/500 mapping, web framework dependency). That is a later task that reuses pipeline.run and PipelineError.
- Changes to detection logic, scoring, clip length or the export naming/manifest format
- Cleaning or emptying out_dir before export, job IDs, temp dirs, concurrency
- An encoder fallback when libx264 is missing
- A --json output mode for `cut`, progress output, logging
- Video-stream validation (an audio-only file is accepted if ffprobe can read it)
- Eval set / eval command (no detection change, so F1 is unaffected)

## Decisions

- T-004 (R-001): `sportscut.pipeline.run(video, out_dir, top=10, min_len=10, max_len=30) -> list[dict]` is the single entry point for the CLI `cut` and the future API. It returns the manifest entries, equal to the contents of `<out_dir>/highlights.json`.
- T-004 (R-001): `PipelineError(Exception)` means bad caller input (the API maps it to HTTP 400). It wraps `MediaError` and `ValueError` raised by `has_audio` and `find_highlights` and keeps the original message (`str(exc)`). The original exception is chained with `from`.
- T-004 (R-001): Environment and server failures are not PipelineError. A missing ffmpeg/ffprobe (`require_ffmpeg`) and any export/encode failure stay `MediaError` (the API maps them to 500).
- T-004 (R-001): A video without an audio stream is rejected before detection with the exact message `no audio stream in <path>`. The detector is audio-only and could not find anything.
- T-004 (R-001): `sportscut.media` gains `require_ffmpeg()` (both ffmpeg and ffprobe via find_tool) and `has_audio(path) -> bool` (ffprobe `-select_streams a -show_entries stream=index -of csv=p=0`; non-empty stdout means True). Media access stays only in sportscut.media, and pipeline.py does not import subprocess.
- T-004 (R-001): The PipelineError path never calls export, so no clips or manifest are written for invalid input.
- T-004 (R-001): CLI `sportscut cut VIDEO --out DIR [--top N] [--min-len S] [--max-len S]` has `--out` required and the same defaults as detect (10/10/30). On success it prints one clip path (`out_dir/file`) per line in manifest order. On PipelineError or MediaError it prints `sportscut: error: <msg>` on stderr and exits 1. The `detect` behaviour and the no-argument help are unchanged.
- T-004 (R-001): The end-to-end cut tests use the existing burst_video fixture (3 clips of 12 s). The no-audio test video is generated locally in the test module; tests/conftest.py is not changed.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`

## Updated by T-039

AC3 and AC7 (PipelineError and CLI messages for missing, non-video and silent inputs) hold when ffmpeg and ffprobe are on PATH. Without them, AC4 applies first: `run` calls `require_ffmpeg()` before any input check and raises MediaError. The tests for AC3 and AC7 therefore request the conftest `require_ffmpeg` fixture and skip with `ffmpeg and ffprobe are required on PATH`, while the AC4 tests keep running.

## Updated by T-018

Updated by T-018 (implemented in T-043): `run(video, out_dir, top=10, min_len=10, max_len=30, events=None, vertical=False)` gains `vertical=False`. With `vertical=True`, each exported clip is reframed with `reframe.plan_crop` and rendered by `vertical.render_vertical` to `<out_dir>/vertical/clip_NN.mp4` (1080x1920, H.264, audio copied), and each manifest entry gains `vertical_file` (`vertical/clip_NN.mp4`) as its last key; highlights.json is rewritten with it. `sportscut cut ... --vertical` prints the vertical path after each clip path. With vertical off (the default) nothing is rendered, no `vertical/` directory is created, and AC1/AC6 hold unchanged.

## Updated by T-021

Updated by T-021: `run(...)` gains a last parameter `score_box=None`, a scoreboard box `(x, y, w, h)` in source pixels for the vertical overlay. It needs `vertical=True` (otherwise PipelineError `score_box needs vertical=True`) and is checked against the source size before any clip is exported; an out-of-frame or malformed box raises PipelineError `invalid score box: ...`. The CLI exposes it as `sportscut cut ... --vertical --score-box X,Y,W,H` (a bad format or a missing `--vertical` exits 2). Without score_box the manifest keys and bytes are unchanged.

## Updated by T-022

Updated by T-022: `run(...)` gains a last parameter `transcriber=None` (a `sportscut.subtitles.Transcriber`). It needs `vertical=True` (otherwise PipelineError `transcriber needs vertical=True`, raised before anything is exported). With a transcriber, each exported clip's audio (never the full match) is transcribed, laid out with `subtitles.layout`, written to `<out_dir>/vertical/clip_NN.srt` and, when non-empty, passed to `render_vertical` as `subtitles=`; a transcriber failure becomes PipelineError `speech-to-text failed for clip_NN.mp4: ...`. The CLI exposes it as `sportscut cut ... --vertical --subtitles`. With `transcriber=None` (the default) nothing in `subtitles` is called, no .srt is written, and the manifest is unchanged.

## Updated by T-026

Updated by T-026: `run(...)` gains a last parameter `voiceover=False` (after `transcriber`). With `voiceover=True`, after export and the vertical block, each clip gets `<out_dir>/clip_NN.script.json` (`{clip, clip_len, peak, backend: "template", lines: [{start, end, text}]}`, UTF-8) built by `sportscut.commentary.script.write_script` around the clip's audio peak, and its manifest entry gains `script_file` as the last key; the manifest is rewritten once when vertical or voiceover is set. A MediaError from reading the clip audio propagates. The CLI exposes it as `sportscut cut ... --voiceover` and prints each script path after its clip (and vertical) path. With `voiceover=False` (the default) nothing is written and the manifest is unchanged.
