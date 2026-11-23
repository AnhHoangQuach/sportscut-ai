# T-004: Pipeline entry point and `sportscut cut` plan

Request R-001. Design: `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`.

## Goal

Add one reusable pipeline for validation, highlight detection, clip export, and manifest
loading. Expose it through `sportscut cut` while keeping input errors distinct from
environment/export failures and preserving `detect` behavior.

## Files

- `sportscut/media.py`: add `require_ffmpeg` and `has_audio`.
- `sportscut/pipeline.py`: add `PipelineError` and `run`.
- `sportscut/cli.py`: add and dispatch the `cut` subcommand.
- `tests/test_media.py`: cover tool checks and audio-stream probing.
- `tests/test_pipeline.py`: cover the pipeline contract, output, and errors.
- `tests/test_cli.py`: cover successful and failing `cut` invocations and help.
- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`:
  append the T-004 media-helper update.
- This plan and its paired design, plus append-only index/decision records.

Do not change `tests/conftest.py`, dependency metadata, or protected paths. Video-only
fixtures remain local to the test modules.

## TDD steps

1. Add media tests for audio/video-only/text/missing inputs and present/missing tools.
   Run `python -m pytest -q tests/test_media.py`; confirm the imports fail, implement
   `require_ffmpeg` and `has_audio`, then rerun green.
2. Add pipeline success tests for the default three 12-second clips and custom
   `top=1, min_len=4, max_len=6`. Confirm the missing module failure, then implement
   manifest-returning `run`.
3. Add pipeline error tests for text, video-only, missing input, invalid bounds, and
   missing tools, plus class-hierarchy and no-`subprocess` checks. Implement wrapping
   only for input/probe/option failures; keep setup and export `MediaError`s unchanged.
4. Add CLI tests for default/custom success, subprocess failure without traceback,
   required `--out`, and `cut` in help. Confirm parser failures, then add parsing and
   command-specific dispatch without changing `detect` output or error behavior.
5. Append the T-036 spec update. Run `python -m pytest -q`, then smoke-test a valid
   local video and a text file through `sportscut cut`.

## Assumptions and boundaries

- `PipelineError(Exception)` represents caller input errors for a future HTTP 400.
- `require_ffmpeg` runs first; missing tools and export/encoder failures stay
  `MediaError` for a future HTTP 500.
- Audio validation precedes detector option validation, so a no-audio input reports
  that issue first.
- Detection, scoring, manifest format, output cleanup, API work, JSON CLI output,
  encoder fallback, concurrency, and eval behavior are unchanged/out of scope.
- No eval run is needed because detection is unchanged and no eval command exists.

## Verification

- `python -m pytest -q tests/test_media.py tests/test_pipeline.py tests/test_cli.py`
- `python -m pytest -q tests/test_t004_acceptance.py`
- `python -m pytest -q`
- `sportscut cut <video> --out /tmp/sc_out --top 3`
- `sportscut cut /tmp/bad.mp4 --out /tmp/sc_bad` exits 1 with a readable ffprobe error.
- `git diff --check`; changed-line and changed-path inspection against the task base.
