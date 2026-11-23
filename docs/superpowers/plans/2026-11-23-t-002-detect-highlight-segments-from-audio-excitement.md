# Plan T-002: Detect highlight segments from audio excitement

Design: `docs/superpowers/specs/2026-11-23-t-002-detect-highlight-segments-from-audio-excitement-design.md`.

## Scope and files

Implement the audio-only detector and standalone CLI described by the design. Touch only:

- `sportscut/detect.py`
- `sportscut/cli.py`
- `tests/conftest.py` (add `burst_video`; preserve `synthetic_video`)
- `tests/test_detect.py`
- `tests/test_cli.py`
- the T-002 records under `docs/superpowers/`

No API, cutting, scene detection, ML, eval, real media, or dependency changes.

## Test-first sequence

1. Add invalid-option tests, observe the missing detector import, then implement validation before media access.
2. Add silence and sub-second tests, observe the incomplete result, then implement RMS, rolling baseline, robust z-score, and local peaks.
3. Add burst coverage and the `burst_video` fixture, then implement windowing and non-maximum suppression.
4. Add separate tests for `top`, minimum/maximum length, overlap suppression, and short-video clamping.
5. Add JSON, text, option forwarding, error, and no-argument CLI tests; then implement `detect`.

Record each red error and focused green result in `.office/DEV_NOTES.md`.

## Verification

- `.venv/bin/python -m pytest -q`
- `PATH=/nonexistent .venv/bin/python -m pytest -q -rs`
- Generate the specified `/tmp/sc_burst.mp4`, run `.venv/bin/sportscut detect /tmp/sc_burst.mp4 --json`, then remove it.
- `git diff --check main`
- `git ls-files '*.mp4' '*.mkv' '*.wav'`
- `git diff --stat main` (allowed files only; fewer than 400 changed lines)
