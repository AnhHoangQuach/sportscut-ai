# T-002: Detect highlight segments from audio excitement

Request R-001. Plan: `docs/superpowers/plans/2026-11-23-t-002-detect-highlight-segments-from-audio-excitement.md`.

## Product Owner request

Tạo API POST /highlights nhận video, trả về danh sách đoạn highlight và file đã cắt

## Goal

Add `sportscut/detect.py` with `find_highlights(video, top=10, min_len=10, max_len=30) -> list[Segment]`. It computes per-second RMS from `extract_audio`, z-scores it against a rolling median baseline, picks local peaks, applies non-maximum suppression with a minimum gap, pads each peak 8 s before and 4 s after, clamps the length to [min_len, max_len] and to the video duration, keeps the top N by score, and returns them sorted by time with reason such as `"audio peak z=3.2"`. Expose it as `sportscut detect VIDEO --json` so the slice is usable on its own. Tests: on the conftest synthetic video, every injected burst is covered by exactly one segment and none of the quiet parts are; the options are respected. Assumptions: audio only, no scene detection or ML (YAGNI for this request; accuracy work belongs to the later F1-gated request), defaults taken from the MVP spec.

## Acceptance criteria

- AC1: `sportscut/detect.py` exposes `find_highlights(video, top=10, min_len=10, max_len=30) -> list[Segment]` and the constants PRE_SEC=8.0, POST_SEC=4.0, BASELINE_SEC=120, MIN_Z=3.0, MIN_SCALE_DB=1.0. It imports `extract_audio`/`probe_duration` from `sportscut.media` as module-level names.
- AC2: `top < 1`, `min_len <= 0` and `min_len > max_len` raise ValueError with exactly `top must be >= 1`, `min_len must be > 0` and `min_len must be <= max_len`. The check runs before any media access, so it works with PATH=/nonexistent and a non-existent file.
- AC3: When `extract_audio` returns 60 s of zeros or under 1 s of audio (monkeypatched), `find_highlights` returns `[]`.
- AC4: On `burst_video` with defaults: exactly 3 segments sorted by start. Each burst [20,21], [50,51] and [75,76] lies fully inside exactly one segment, and no segment intersects [0,10], [28,40], [58,65] or [82,90]. Each length is 12±0.01, each reason matches `^audio peak z=\d+\.\d$`, and each score is a native float >= 3.0 that agrees with the reason to 0.05.
- AC5: On `burst_video`, `top=2` gives the segments containing the 20 s and 75 s bursts (in time order), and `top=1` gives only the 75 s burst.
- AC6: On `burst_video`, `min_len=20,max_len=30` gives 3 segments of 20±0.01 s and `min_len=4,max_len=6` gives 3 segments of 6±0.01 s. Each one contains its burst.
- AC7: On `burst_video`, `min_len=max_len=60` gives exactly one segment of about [30.0, 90.0] (end equal to probe_duration ±0.01) containing [75,76]. Overlapping windows are suppressed and kept segments never overlap.
- AC8: On the unchanged `synthetic_video` (6 s) with defaults, there is exactly one segment with start == 0.0 and end == probe_duration(synthetic_video).
- AC9: `sportscut detect VIDEO --json` exits 0 and prints one line of a JSON list of objects with exactly the keys start, end, score, reason. `--top`, `--min-len` and `--max-len` are passed through. Without `--json` it prints one tab-separated line per segment.
- AC10: `sportscut detect <missing>` returns 1 with empty stdout and stderr exactly `sportscut: error: media file not found: <path>\n`. Invalid options return 1 with stderr containing the ValueError message. `sportscut` with no arguments still prints help (now listing `detect`) and returns 0.
- AC11: `.venv/bin/python -m pytest -q` exits 0 with 0 failed and 0 skipped when ffmpeg is present. `PATH=/nonexistent .venv/bin/python -m pytest -q -rs` exits 0 with 0 failed, and every skip reason is exactly `ffmpeg and ffprobe are required on PATH`.
- AC12: The diff touches only sportscut/detect.py, sportscut/cli.py, tests/conftest.py (with the `synthetic_video` fixture unchanged), tests/test_detect.py and tests/test_cli.py, plus orchestrator-written docs/superpowers records. It stays under 400 changed lines, and `git ls-files '*.mp4' '*.mkv' '*.wav'` is empty.
- AC13: The report quotes a real red run before each implementation step (`No module named 'sportscut.detect'`, `fixture 'burst_video' not found`, argparse `invalid choice: 'detect'`), each followed by a green run.

## Out of scope

- POST /highlights, FastAPI, uploads, or any HTTP code
- Clip cutting/export, highlights.mp4 concatenation, highlights.json writing, `sportscut cut`, `--out DIR`
- Scene/shot-boundary detection and snapping clip edges to scene changes, replay, OCR, whistle, spectral flux, ML/YOLO
- `sportscut eval`, tests/fixtures/eval/ labelled set, F1 metrics, learned weights
- Tuning thresholds on real footage; anything under data/
- Configurable pad/threshold/baseline options beyond --top/--min-len/--max-len
- Streaming/chunked audio decoding or changes to sportscut/media.py
- Changing the existing `synthetic_video` fixture, pyproject.toml, .gitignore, docs/05, agent-office/

## Decisions

- T-002 (R-001): `sportscut.detect.find_highlights(video, top=10, min_len=10, max_len=30) -> list[Segment]` is the only detector entry point for later cut/API tasks. It is audio only, uses no ML, and calls media only through `sportscut.media`.
- T-002 (R-001): Option validation (`top must be >= 1`, `min_len must be > 0`, `min_len must be <= max_len`, all ValueError) runs before any media access.
- T-002 (R-001): Loudness is per-second RMS in dB (frames of SAMPLE_RATE samples, trailing partial second dropped). The baseline is a centred rolling median of 121 s (BASELINE_SEC=120, truncated at edges). z = residual / max(1.4826*MAD(residual), 1.0 dB), so silence and steady noise produce no peaks.
- T-002 (R-001): A peak is a local maximum (>= left, > right, edges count as -inf) with z >= 3.0, timed at the centre of its second.
- T-002 (R-001): The clip length is L = clamp(12, min_len, max_len), split 2:1 around the peak (generalising 8 s before / 4 s after). It is then shifted inside [0, duration], so the length is min(L, duration); the video bounds win over min_len.
- T-002 (R-001): Non-maximum suppression is greedy by z (ties: earlier first) and rejects any window that overlaps a kept one (minimum gap 0 s; touching allowed). Returned segments never overlap, are at most `top`, and are sorted by start.
- T-002 (R-001): Segment.score is the raw robust z of the peak, and reason is exactly `audio peak z=<z:.1f>`. Start and end are not rounded.
- T-002 (R-001): CLI `sportscut detect VIDEO [--top N] [--min-len S] [--max-len S] [--json]`. `--json` prints one line of a JSON list of Segment.to_dict(); otherwise it prints one tab-separated line per segment. MediaError/ValueError give `sportscut: error: <msg>` on stderr and exit 1. No-argument help behaviour from T-035 is kept.
- T-002 (R-001): Detector tests use a new session fixture `burst_video` (90 s, seeded noise 0.02, x20@20-21 s, x10@50-51 s, x30@75-76 s). Its layout is a contract for later detector tests. The T-036 `synthetic_video` contract is unchanged and is used for the duration-clamp test.

## Existing specs this task changes

- (none)
