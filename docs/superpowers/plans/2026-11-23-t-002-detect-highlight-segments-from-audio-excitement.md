# Plan T-002: Detect highlight segments from audio excitement

Design: `docs/superpowers/specs/2026-11-23-t-002-detect-highlight-segments-from-audio-excitement-design.md`.

## Implementation plan

# T-002: Detect highlight segments from audio excitement

Request R-001 (PO: "Tạo API POST /highlights nhận video, trả về danh sách đoạn highlight và file đã cắt"). This slice adds the detector the later API/cut tasks will call. It also adds the CLI `sportscut detect VIDEO --json` so the detector can be used on its own.

## Context (current code on main)
- `sportscut/models.py`: `Segment(start, end, score, reason)` is a frozen dataclass. It validates `start >= 0` and `end > start`, and `to_dict()` returns native floats/str.
- `sportscut/media.py`: `SAMPLE_RATE = 16000`, `MediaError(RuntimeError)`, `probe_duration(path) -> float`, `extract_audio(path) -> np.ndarray` (1-D float32 mono 16 kHz). Both check that the file exists before looking up ffmpeg, so the message `media file not found: <path>` works without ffmpeg.
- `sportscut/cli.py`: `main(argv=None) -> int`. It has an argparse parser with `--version`; with no arguments it prints help and returns 0 (T-035 contract, keep it).
- `tests/conftest.py`: `require_ffmpeg` (skips with `ffmpeg and ffprobe are required on PATH`) and the session fixture `synthetic_video`. That fixture is a 6 s clip with a x20 noise burst at 2-3 s; its layout is a T-036 contract and must NOT change.
- Defaults come from the MVP request (`agent-office/examples/sportscut/po_request.md`: top 10, clips 10-30 s) and from `docs/05-sportscut.md` §5.2/5.3: per-second RMS, a rolling-median baseline of a few minutes, local peaks, NMS, and padding of 8 s before and 4 s after.

## Design

### `sportscut/detect.py` (new)
```python
import numpy as np
from sportscut.media import SAMPLE_RATE, extract_audio, probe_duration
from sportscut.models import Segment

PRE_SEC = 8.0          # padding before the peak
POST_SEC = 4.0         # padding after the peak
BASELINE_SEC = 120     # centred rolling-median window (seconds)
MIN_Z = 3.0            # a peak must reach this z-score
MIN_SCALE_DB = 1.0     # floor of the z-score scale, in dB

def find_highlights(video, top: int = 10, min_len: float = 10, max_len: float = 30) -> list[Segment]:
```
The algorithm, in this exact order:
1. **Validate before touching media**, so these errors work without ffmpeg:
   - `top < 1` -> `ValueError("top must be >= 1")`
   - `min_len <= 0` -> `ValueError("min_len must be > 0")`
   - `min_len > max_len` -> `ValueError("min_len must be <= max_len")`
2. `duration = probe_duration(video)`, then `samples = extract_audio(video)`. A `MediaError` propagates unchanged.
3. `n = len(samples) // SAMPLE_RATE` (a trailing partial second is dropped). If `n == 0`, return `[]`.
4. **Per-second RMS** without big float64 temporaries: `frames = samples[: n * SAMPLE_RATE].reshape(n, SAMPLE_RATE)`, then `rms = np.sqrt(np.einsum("ij,ij->i", frames, frames, dtype=np.float64) / SAMPLE_RATE)`.
5. **Loudness in dB:** `db = 20 * np.log10(rms + 1e-10)`.
6. **Rolling-median baseline:** for each second `i`, `base[i] = np.median(db[max(0, i - 60): i + 61])`. The window is centred, `BASELINE_SEC // 2 = 60` on each side, and truncated at the edges.
7. **Robust z-score:**
   - `res = db - base`
   - `mad = np.median(np.abs(res - np.median(res)))`
   - `scale = max(1.4826 * mad, MIN_SCALE_DB)`
   - `z = res / scale`
   Pure silence gives `z == 0` everywhere, so there are no peaks. Steady noise cannot make peaks, because the scale is at least 1 dB.
8. **Local peaks:** second `i` is a candidate when `z[i] >= MIN_Z`, `z[i] >= z[i-1]` and `z[i] > z[i+1]`. A missing neighbour at an edge counts as `-inf`. The peak time is `t = i + 0.5`.
9. **Window for each candidate:**
   - `L = min(max(PRE_SEC + POST_SEC, min_len), max_len)`
   - `start = t - L * PRE_SEC / (PRE_SEC + POST_SEC)`, `end = t + L * POST_SEC / (PRE_SEC + POST_SEC)`. This keeps the 2:1 ratio, and the peak always stays inside.
   - Clamp to the video by shifting, keeping the length when possible: if `start < 0`: `end -= start; start = 0`. Then if `end > duration`: `start -= end - duration; end = duration`. Then `start = max(start, 0.0)`.
   - The length is therefore `min(L, duration)`.
10. **Non-maximum suppression with a minimum gap of 0 s between clips:** go through the candidates by `z` descending (ties: earlier time first). Keep a candidate only if its window does not overlap any kept window. Two windows overlap when `a.start < b.end and b.start < a.end`; touching ends are allowed. Stop once `top` windows are kept.
11. Build `Segment(start=float(start), end=float(end), score=float(z_peak), reason=f"audio peak z={z_peak:.1f}")` and return the list **sorted by start**. Do not round start or end.

Performance: the audio is decoded once, the RMS is vectorised, and the median loop runs once per second (5400 iterations for 90 min). That fits the 10-minute budget.

### `sportscut/cli.py` (change)
- Add subparsers with `dest="command"`. With no command, keep the current behaviour (print help, return 0).
- The `detect` subcommand takes:
  - positional `video`
  - `--top` (int, default 10)
  - `--min-len` (float, default 10)
  - `--max-len` (float, default 30)
  - `--json` (store_true)
- It calls `find_highlights(args.video, top=args.top, min_len=args.min_len, max_len=args.max_len)`.
  - With `--json`: print `json.dumps([s.to_dict() for s in segments])` (a single line) and return 0.
  - Without `--json`: print one line per segment, `f"{s.start:.1f}\t{s.end:.1f}\t{s.score:.2f}\t{s.reason}"`, and return 0.
  - On `MediaError` or `ValueError`: print `sportscut: error: <message>` to stderr, print nothing to stdout, and return 1.

### `tests/conftest.py` (change: add one fixture, keep `synthetic_video` byte-for-byte)
Add the session fixture `burst_video(require_ffmpeg, tmp_path_factory) -> Path`. It generates `burst.mp4` under `tmp_path_factory.mktemp("media")` and has this layout:
- 90 s, video `color=c=black:s=160x120:r=5:d=90`
- audio `anoisesrc=d=90:c=white:r=44100:a=0.02:seed=7`
- filter chain `volume=volume=20:enable='between(t,20,21)',volume=volume=10:enable='between(t,50,51)',volume=volume=30:enable='between(t,75,76)',aformat=channel_layouts=stereo`
- encoders `-c:v mpeg4 -q:v 5 -pix_fmt yuv420p -c:a aac -b:a 96k -t 90`, run with `-v error -nostdin -y` and `subprocess.run(check=True, capture_output=True)`. Use the same style as `synthetic_video`.

The bursts, by strength, are **x30 at 75-76 s > x20 at 20-21 s > x10 at 50-51 s**. Update the module docstring to mention both clips.

Expected default output on `burst_video`: about `[12.5, 24.5]`, `[42.5, 54.5]` and `[67.5, 79.5]`. The quiet windows `[0, 10]`, `[28, 40]`, `[58, 65]` and `[82, 90]` must not be covered.

## Files
- `sportscut/detect.py` (new)
- `sportscut/cli.py` (change)
- `tests/conftest.py` (add `burst_video` only)
- `tests/test_detect.py` (new)
- `tests/test_cli.py` (add detect tests)

Nothing under `agent-office/`, `pyproject.toml`, `.gitignore` or `sportscut/media.py` changes. The target is under 400 changed lines.

## Steps (test-first; record each red run's error line, then the green run)
Setup: use the worktree `.venv` (`.venv/bin/python -m pytest ...`).

1. **Validation, red/green.** In `tests/test_detect.py`, write `test_rejects_invalid_options`, parametrised over `(top=0)`, `(min_len=0)`, `(min_len=20, max_len=10)`. It uses a non-existent path and expects `ValueError` with the exact messages. Run it and expect `No module named 'sportscut.detect'`. Create `detect.py` with the constants and steps 1-2 only, and make the test pass.
2. **Silence/short audio, red/green.** Write `test_silence_and_sub_second_audio_give_no_segments`. It monkeypatches `sportscut.detect.extract_audio` to return `np.zeros(60*SAMPLE_RATE, np.float32)` (and, in a second case, `np.zeros(SAMPLE_RATE//2, np.float32)`), and `sportscut.detect.probe_duration` to return `60.0`. It asserts `find_highlights('x.mp4') == []` (the files are never touched). It is red because the function returns None or raises. Implement steps 3-8 and 11, enough for this to pass.
3. **Burst coverage, red/green.** Write `test_every_burst_covered_once_and_quiet_parts_untouched(burst_video)` with defaults:
   - exactly 3 segments, sorted by start
   - each burst `[b, b+1]` for b in (20, 50, 75) lies fully inside exactly one segment
   - no segment intersects any quiet window
   - every length is `12 ± 0.01`
   - every reason matches `^audio peak z=\d+\.\d$`
   - the score equals the z in the reason to 0.05
   - every score is a native `float` >= 3.0
   First run: `fixture 'burst_video' not found`. Add the fixture. Then implement or fix steps 9-10 until it passes.
4. **Options (each a separate test on `burst_video`; write the test, see it fail if the behaviour is missing, fix):**
   - `test_top_keeps_highest_scores_sorted_by_time`: with `top=2` the segments contain the 20 s and 75 s bursts, in that order. With `top=1` there is one segment, and it contains 75-76.
   - `test_min_len_extends_segments`: `min_len=20, max_len=30` gives 3 segments, each `20 ± 0.01` long and containing its burst.
   - `test_max_len_shortens_segments`: `min_len=4, max_len=6` gives 3 segments, each `6 ± 0.01` long and containing its burst.
   - `test_overlapping_windows_are_suppressed`: `min_len=60, max_len=60` gives exactly 1 segment, equal to `[30.0, 90.0]` (±0.2, and `end == probe_duration` ±0.01), containing 75-76.
   - `test_short_clip_is_clamped_to_duration(synthetic_video)`: with defaults there is exactly one segment, `start == 0.0` and `end == probe_duration(synthetic_video)`.
5. **CLI, red/green.** In `tests/test_cli.py`:
   - `test_detect_json(burst_video, capsys)`: `main(['detect', str(burst_video), '--json']) == 0`. stdout is one line; `json.loads` gives a list of 3 dicts with exactly the keys `start,end,score,reason`, and stderr is `''`.
   - `test_detect_passes_options(burst_video, capsys)`: `--top 1 --min-len 4 --max-len 6 --json` gives 1 item with `end - start == 6 ± 0.01`.
   - `test_detect_text_output(burst_video, capsys)`: without `--json` there are 3 lines, each with 4 tab-separated fields.
   - `test_detect_missing_file(tmp_path, capsys)`: returns 1, stdout is `''`, and stderr is exactly `sportscut: error: media file not found: <path>\n`. No ffmpeg is needed.
   - `test_detect_invalid_options(tmp_path, capsys)`: `--min-len 20 --max-len 10` returns 1 and stderr contains `min_len must be <= max_len`.
   - Extend `test_no_args_prints_help_and_returns_zero` to also assert that `'detect'` is in the help output.
   Red: argparse exits 2 with `invalid choice: 'detect'` / `unrecognized arguments`. Implement the subcommand.
6. **Verify:**
   - `.venv/bin/python -m pytest -q` exits 0, with 0 failed and 0 skipped (ffmpeg present).
   - `PATH=/nonexistent .venv/bin/python -m pytest -q -rs` exits 0. Every skip reason is exactly `ffmpeg and ffprobe are required on PATH`, and the validation, silence, missing-file and invalid-option tests run and pass.
   - Manual check:
     - `ffmpeg -v error -y -f lavfi -i color=c=black:s=160x120:r=5:d=90 -f lavfi -i anoisesrc=d=90:c=white:r=44100:a=0.02:seed=7 -filter_complex "[1:a]volume=volume=20:enable='between(t,20,21)'[a]" -map 0:v -map "[a]" -c:v mpeg4 -c:a aac -t 90 /tmp/sc_burst.mp4`
     - then `.venv/bin/sportscut detect /tmp/sc_burst.mp4 --json` prints one segment of about `[12.5, 24.5]` with reason `audio peak z=...`
     - then `rm /tmp/sc_burst.mp4`
   - `git ls-files '*.mp4' '*.mkv' '*.wav'` is empty.
   - `git diff --stat main` shows only the listed files and fewer than 400 lines.

There is no eval command yet, so there is no F1 gate. Accuracy work belongs to the later F1-gated request.

## Assumptions
- Audio only. No scene snapping, whistle, spectral flux or ML; `docs/05` describes those as later signals.
- The video duration used for clamping comes from `probe_duration` (container duration), not from the number of audio samples.
- The score is the raw robust z of the peak second. It has no upper bound (allowed by the T-035 `Segment` decision).
- Segments never overlap. Fewer than `top` segments are returned when there are fewer qualifying peaks; nothing is padded with quiet clips.
- `min_len`/`max_len` are floats in seconds. When the video is shorter than `L`, a segment is shorter than `min_len`; the video bounds win.

## Test plan

- unit tests/test_detect.py::test_rejects_invalid_options: parametrised over top=0, min_len=0, min_len>max_len, with a non-existent path. Checks the exact ValueError messages. No ffmpeg needed.
- unit tests/test_detect.py::test_silence_and_sub_second_audio_give_no_segments: monkeypatch sportscut.detect.extract_audio (60 s zeros / 0.5 s zeros) and probe_duration (60.0). Expects []. No ffmpeg needed.
- integration tests/test_detect.py::test_every_burst_covered_once_and_quiet_parts_untouched(burst_video): checks the count, coverage, quiet windows, lengths, reason regex and score type.
- integration tests/test_detect.py::test_top_keeps_highest_scores_sorted_by_time(burst_video): top=2 gives the 20 s and 75 s bursts; top=1 gives the 75 s burst.
- integration tests/test_detect.py::test_min_len_extends_segments(burst_video): min_len=20,max_len=30 gives lengths of 20.
- integration tests/test_detect.py::test_max_len_shortens_segments(burst_video): min_len=4,max_len=6 gives lengths of 6, each containing its burst.
- integration tests/test_detect.py::test_overlapping_windows_are_suppressed(burst_video): min_len=max_len=60 gives a single segment of about [30, 90].
- integration tests/test_detect.py::test_short_clip_is_clamped_to_duration(synthetic_video): one segment [0, probe_duration].
- integration tests/test_cli.py::test_detect_json, test_detect_passes_options, test_detect_text_output (burst_video): exit code, stdout format, empty stderr.
- unit tests/test_cli.py::test_detect_missing_file and test_detect_invalid_options: exit 1, exact stderr, empty stdout. No ffmpeg needed.
- unit tests/test_cli.py::test_no_args_prints_help_and_returns_zero: extended to assert 'detect' is in the help.
- fixture tests/conftest.py::burst_video: session-scoped 90 s 160x120@5fps mpeg4/aac clip in the pytest temp dir, seeded noise 0.02 with x20@20-21 s, x10@50-51 s and x30@75-76 s, depending on require_ffmpeg.
- suite: `.venv/bin/python -m pytest -q` (0 skipped) and `PATH=/nonexistent .venv/bin/python -m pytest -q -rs` (only the ffmpeg skip reason).
