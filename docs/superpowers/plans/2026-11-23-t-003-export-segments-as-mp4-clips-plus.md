# Plan T-003: Export segments as mp4 clips plus a JSON manifest

Design: `docs/superpowers/specs/2026-11-23-t-003-export-segments-as-mp4-clips-plus-design.md`.

## Implementation plan

# T-003: Export segments as mp4 clips plus a JSON manifest

Request R-001 (POST /highlights returns highlight segments and the cut files). This slice gives the future API and CLI one call that turns a video plus `Segment`s into cut files and a manifest. Depends on T-035 (`sportscut/models.py::Segment`) and T-036 (`sportscut/media.py`, `tests/conftest.py::synthetic_video`), both already on main.

## Current code (read before starting)
- `sportscut/models.py`: `Segment(start, end, score, reason)` is a frozen dataclass. It validates `0 <= start < end`. `to_dict()` returns `{"start", "end", "score", "reason"}` as native float/str.
- `sportscut/media.py`: `MediaError(RuntimeError)`, `find_tool(name)`, `_failure_detail(stderr, returncode)`, `probe_duration(path)`, `extract_audio(path)`. Every public function first checks `Path(path).is_file()` (`media file not found: <path>`), then calls `find_tool`, then runs `subprocess.run(..., capture_output=True, check=False)`. On a non-zero exit it raises `MediaError(f"<tool> failed for {path}: {detail}")`.
- `tests/conftest.py`: session fixtures `require_ffmpeg` (skips with exactly `ffmpeg and ffprobe are required on PATH`) and `synthetic_video`. The clip is 6 s, 160x120@10fps mpeg4, black 0-3 s and white 3-6 s, with stereo aac audio. mpeg4 uses its default GOP of 12 frames, so the source has keyframes at 0, 1.2, 2.4, 3.6 and 4.8 s. A `-c copy` cut starting at 3.2 s would start on the black keyframe at 2.4 s. A re-encoded cut starts white.

## Design
T-036 decided that `sportscut.media` is the only module that calls ffmpeg. So the actual cut is a new media helper, `cut_clip`. `sportscut/export.py` only orders segments, names files and writes the manifest. It never imports `subprocess`.

### `sportscut/media.py`: add
```python
def cut_clip(path: str | Path, start: float, end: float, dest: str | Path) -> Path:
```
1. `p = Path(path)`. If it is not a file, raise `MediaError(f"media file not found: {path}")`. This check runs before tool lookup.
2. `ffmpeg = find_tool("ffmpeg")`.
3. Run exactly these args, with no shell:
   `[ffmpeg, "-v", "error", "-nostdin", "-y", "-ss", f"{start:.3f}", "-i", str(p), "-t", f"{end - start:.3f}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(dest)]`
   with `subprocess.run(args, capture_output=True, check=False)`.
4. If the return code is non-zero, raise `MediaError(f"ffmpeg failed for {path}: {_failure_detail(result.stderr, result.returncode)}")`.
5. Return `Path(dest)`.

Notes: `-ss` goes before `-i` (fast input seek). Because the clip is re-encoded, the output still starts at the requested time, not at a keyframe. Output timestamps start at 0. The function does not validate `start`/`end`; callers pass validated `Segment` values.

### `sportscut/export.py`: new
```python
import json
from pathlib import Path
from sportscut.media import cut_clip
from sportscut.models import Segment

MANIFEST_NAME = "highlights.json"

def export_clips(video: str | Path, segments: list[Segment], out_dir: str | Path) -> list[Path]:
```
Behaviour:
1. `out = Path(out_dir)`, then `out.mkdir(parents=True, exist_ok=True)`.
2. `ordered = sorted(segments, key=lambda s: (s.start, s.end))`. The caller's list is not mutated.
3. For `i, seg in enumerate(ordered, 1)`: set `name = f"clip_{i:02d}.mp4"`, call `cut_clip(video, seg.start, seg.end, out / name)`, collect the path, and collect the entry `{**seg.to_dict(), "file": name}`.
4. Only after all cuts succeed, write `out / MANIFEST_NAME` as `json.dumps(entries, indent=2) + "\n"` (UTF-8). If a cut fails, its `MediaError` propagates and no manifest is written.
5. Return the clip paths in time order. The manifest path is not in the list.

Manifest example:
```json
[
  {"start": 0.5, "end": 2.0, "score": 1.5, "reason": "audio", "file": "clip_01.mp4"}
]
```
`file` is a bare file name relative to `out_dir`, so the folder can be moved or served as is. An empty `segments` list cuts nothing, writes `[]` to the manifest and returns `[]`.

## Files
- change `sportscut/media.py` (add `cut_clip`, about 15 lines)
- create `sportscut/export.py` (about 25 lines)
- change `tests/test_media.py` (add `cut_clip` tests)
- create `tests/test_export.py`

Do not change `tests/conftest.py`, `tests/test_fixtures.py`, `pyproject.toml`, `.gitignore`, `agent-office/`, `AGENTS.md` or `CLAUDE.md`.

## Steps (test-first; record each red run's error line, then the green run)
1. **Red:** in `tests/test_media.py`, import `cut_clip` and add `test_cut_clip_missing_file_raises` and `test_cut_clip_without_tool`. Run `.venv/bin/python -m pytest -q tests/test_media.py` and expect `cannot import name 'cut_clip'`. **Green:** add `cut_clip` steps 1-2, then the subprocess call, error handling and return.
2. **Red:** add `test_cut_clip_rejects_non_media` and `test_cut_clip_is_accurate_h264`. These pass right away if step 1 was implemented in full. If so, note it, then temporarily replace the codec args with `-c copy` and confirm `test_cut_clip_is_accurate_h264` fails on the white-first-frame or codec assertion. Revert, and it is green.
3. **Red:** create `tests/test_export.py` with `test_export_clips_cuts_one_file_per_segment_in_time_order`. Expect `No module named 'sportscut.export'`. **Green:** implement `export_clips` steps 1-3 and 5.
4. **Red:** add `test_export_clips_writes_manifest` and `test_export_clips_empty_segments`. Expect a missing `highlights.json` (FileNotFoundError). **Green:** implement step 4.
5. **Red:** add `test_export_clips_missing_video_writes_no_manifest`. It should pass right away, because the existence check is in `cut_clip` and the manifest is written last. Record that.
6. Run the full verification below. Keep the diff under 400 changed lines. Confirm no media is tracked or left in the worktree.

## Verification commands
- `.venv/bin/python -m pytest -q` exits 0 with 0 failed, 0 errors and 0 skipped on a machine with ffmpeg built with libx264.
- `PATH=/nonexistent .venv/bin/python -m pytest -q -rs` exits 0 with 0 failed and 0 errors. Every skip reason is exactly `ffmpeg and ffprobe are required on PATH`.
- `git ls-files '*.mp4' '*.mkv' '*.wav'` prints nothing. `find . -path ./.venv -prune -o \( -name '*.mp4' -o -name '*.wav' -o -name '*.mkv' \) -print` prints nothing.
- No eval exists yet, so there is no F1 gate. This task does not touch detection.

## Assumptions
- R-001 asks for the cut files only. There is no concatenated `highlights.mp4` reel (YAGNI).
- Segments are cut as given. Overlapping or adjacent segments are not merged; merging belongs to the detector/selection step.
- A segment whose `end` is past the video's end gives a shorter clip, as ffmpeg stops at end of input. No clamping or error.
- Files already in `out_dir` with the same names are overwritten (`-y`). Stale clips from an earlier run with more segments are not removed; the caller gives a fresh directory per job.
- The clip codec is H.264 (libx264, `ultrafast`, yuv420p) plus AAC in MP4 with faststart, so the API's files play in browsers. mpeg4 part 2 does not. The ffmpeg used by the product and the tests must include libx264 (Homebrew, Ubuntu apt and the common static builds do). If it is missing, the user gets `MediaError('ffmpeg failed for <video>: ... libx264 ...')`.

## Test plan

- unit tests/test_media.py::test_cut_clip_missing_file_raises: `cut_clip(tmp_path/'missing.mp4', 0, 1, tmp_path/'o.mp4')` raises exact `media file not found: <path>`. Needs no ffmpeg.
- unit tests/test_media.py::test_cut_clip_without_tool: create an empty file, monkeypatch PATH to tmp_path, and expect exact `ffmpeg not found on PATH; install ffmpeg`.
- integration tests/test_media.py::test_cut_clip_rejects_non_media (require_ffmpeg): a text `bad.mp4` raises MediaError matching `^ffmpeg failed for <path>: .+`.
- integration tests/test_media.py::test_cut_clip_is_accurate_h264 (synthetic_video): cut 3.2-5.2. Assert the return value equals dest, `probe_duration` approx 2.0 within 0.5, ffprobe JSON (`-show_entries stream=codec_type,codec_name -of json`) has video codec `h264` and one aac audio stream, and the 8x6 gray mean of the frame at 0.05 s is > 192. Use a small local `_gray_mean` helper with the same ffmpeg args as tests/test_fixtures.py; do not modify test_fixtures.py.
- integration tests/test_export.py::test_export_clips_cuts_one_file_per_segment_in_time_order (synthetic_video): segments out of order, out_dir = tmp_path/'job'/'out' (not existing). Assert the returned list equals [out/'clip_01.mp4', out/'clip_02.mp4'], files exist, and durations are approx 1.5 within 0.5 each. Also check that clip_01's first frame is black (< 64) and clip_02's is white (> 192), which proves time order.
- integration tests/test_export.py::test_export_clips_writes_manifest (synthetic_video): `json.loads(highlights.json)` equals the expected list built from sorted segments' `to_dict()` plus `file`, and each file exists in out_dir.
- integration tests/test_export.py::test_export_clips_empty_segments (synthetic_video): returns [], the manifest content parses to [], and `list(out.glob('*.mp4')) == []`.
- unit tests/test_export.py::test_export_clips_missing_video_writes_no_manifest: no ffmpeg needed. A missing video raises exact `media file not found: <path>` and `not (out/'highlights.json').exists()`.
- suite: run `.venv/bin/python -m pytest -q` (0 skipped) and `PATH=/nonexistent .venv/bin/python -m pytest -q -rs` (only the require_ffmpeg skip reason), then check that no media is tracked or left in the worktree.
