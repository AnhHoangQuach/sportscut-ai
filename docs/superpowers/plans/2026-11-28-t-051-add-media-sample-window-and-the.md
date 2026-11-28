# Plan T-051: Add media.sample_window and the jersey module with the number vote and the numpy digits reader

Design: `docs/superpowers/specs/2026-11-28-t-051-add-media-sample-window-and-the-design.md`.

## Implementation plan

# T-051: Add media.sample_window and the jersey module with the number vote and the numpy digits reader

Request R-006 (Theo dõi cầu thủ). This is the first of three slices of T-033, which the Tech Lead split on 2026-11-28 because the full task came to 1369 changed lines against an 800-line budget. This slice is a library only. It changes no CLI, player, API or eval behaviour. The next slice (player-number-filter) uses `jersey.get_reader()` and `media.sample_window` to read numbers around touches. The OCR slice adds OcrReader and the env var.

## Context (main @ 4ef309e)

- The T-033 design was never merged. Its committed design spec `docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md` exists only in commit `11413ad` (the blocked office/T-033 work), not on main. That commit also holds ported code: `git show 11413ad:sportscut/jersey.py`, `git show 11413ad:sportscut/media.py` and `git show 11413ad:tests/test_jersey.py`. The Developer may port from it and trim it to this slice (drop everything OCR/env related).
- `sportscut/media.py` is the only module that runs ffmpeg. `sample_frames(path, fps, width, height)` (line ~129) builds its args, runs `subprocess.run`, and reshapes stdout to `(n, height, width, 3)` uint8.
- **Pinned by existing tests that run on every branch:** `tests/test_t042_round2_acceptance.py::test_ac3_shared_files_are_append_only` and `tests/test_t042_tester_acceptance.py::test_ac3_shared_files_are_append_only_and_existing_commands_work` require `sportscut/media.py` and `tests/test_media.py` to have **0 deleted lines** against `merge-base main HEAD`. `probe_size` source must stay identical to 314d171. `tests/test_media.py::test_only_media_module_imports_subprocess` requires that only `media.py` and `events/incidents.py` import subprocess.
- `tests/fixtures/eval_player/build.py` (frozen) defines:
  - `FONT` (3×5 digit bitmaps '0'..'9') and `TEAM_RGB = {'red': (200,30,30), 'blue': (30,60,200)}`;
  - `_draw_number(frame, number, x, y)`, which writes 255 into 2×2 px cells at rows y+6.., with digits 6 px wide, a 2 px gap, centred in a 16 px shirt;
  - `build_all(out_dir)`, which builds the four cases. `number_hidden` is 640×360 at 25 fps.
  Tests load it with `importlib.util.spec_from_file_location` as tests/test_teams.py does.

## Design

### 1. `sportscut/media.py`: new `sample_window` (insert-only)

```python
def sample_window(path: str | Path, start: float, duration: float, fps: float, width: int, height: int) -> np.ndarray:
    """RGB frames of [start, start+duration) sampled at fps, scaled to width x height: uint8 (n, height, width, 3)."""
```
1. `p = Path(path)`. If `not p.is_file()`, raise `MediaError(f"media file not found: {path}")`.
2. If `not (math.isfinite(start) and math.isfinite(duration)) or start < 0 or duration <= 0`, raise `ValueError("window start must be >= 0 and duration > 0")`.
   Both checks run before `find_tool` and before `subprocess.run`.
3. args are exactly `[find_tool("ffmpeg"), "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(p), "-an", "-sn", "-vf", f"fps={fps},scale={width}:{height}:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]`.
4. Run and reshape exactly like sample_frames. A non-zero return code raises `MediaError(f"ffmpeg failed for {path}: {detail}")`.

**Zero-deletion refactor (required, because of the T-042 tests).** Add `import math` at the top. In `sample_frames`, insert `return _run_frames(args, path, width, height)` right after its args list. Then insert `sample_window` and a header `def _run_frames(args: list[str], path: str | Path, width: int, height: int) -> np.ndarray:` immediately above the existing `result = subprocess.run(args, ...)` line. The existing tail of sample_frames becomes the body of `_run_frames`. This is the exact shape of the 11413ad diff, and it gives 0 deleted lines. The sample_frames args are untouched.

### 2. New module `sportscut/jersey.py` (digits part only)

The module is named `jersey` so it does not shadow the stdlib `numbers` module. It is numpy-only: top-level imports are limited to `math`, `collections.abc`, `typing` and `numpy`. It does not import sportscut.player, sportscut.media, subprocess, os or easyocr.

```python
VOTE_MIN_READS = 3       # reads of the winning number for full vote confidence (tunable 1..5)
INK_CONTRAST = 80        # min |luma - crop median luma| of a number pixel (tunable 40..120)
INK_MIN_PIXELS = 6       # fewer ink pixels = unreadable (fixed)
NUMBER_TOP = 0.6         # only the top 60 % of crop rows is searched (fixed)
DIGIT_MIN_SCORE = 0.6    # min template correlation to accept a read (tunable 0.4..0.9)
DIGIT_FONT = {...}       # literal copy of tests/fixtures/eval_player/build.py FONT ('0'..'9'); not imported from tests

class NumberReader(Protocol):
    name: str
    max_reads: int | None          # None = read every tracked crop
    def read(self, crop: np.ndarray) -> tuple[int | None, float]: ...   # (1..99 or None, confidence 0..1)

class DigitReader:               # name = "digits"; max_reads = None (class attributes)
    def read(self, crop: np.ndarray) -> tuple[int | None, float]: ...

def vote(reads: Sequence[tuple[int | None, float]]) -> tuple[int | None, float]: ...
def get_reader() -> NumberReader: ...   # returns DigitReader(); ignores the environment in this slice
```

**`DigitReader.read(crop)`** takes an (h, w, 3) uint8 RGB crop. It is deterministic and works for either polarity.
1. If the crop is not 3-D, or has 0 rows or 0 columns, return `(None, 0.0)`. Otherwise keep the top `math.ceil(NUMBER_TOP * rows)` rows, as float64.
2. `luma = 0.299R + 0.587G + 0.114B`; `ink = |luma - median(luma)| >= INK_CONTRAST`.
3. **Drop border ink:** remove every ink pixel that is 8-connected through ink to the crop's outer edge. Use an iterative numpy flood fill seeded with the ink on the first and last row and column; scipy is not allowed. This addition to the T-033 §2 algorithm is required: without it the (40,140,60) grass border counts as ink against a light shirt, and AC3's dark-on-light case reads [7, 7, None, None, None] (measured on office/T-033).
4. If fewer than INK_MIN_PIXELS ink pixels are left, return `(None, 0.0)`.
5. Crop to the bounding box of the remaining ink. For each n in 1..99, build the template from DIGIT_FONT: 5 rows, 3 columns per digit, and 1 empty column between two digits. That gives 5×3 for 1..9 and 5×7 for 10..99. Templates may be precomputed at import.
6. Resample the ink box to the template's grid as the ink fraction per cell. Cell edges are `np.round(np.linspace(0, size, k+1)).astype(int)`, and an empty cell counts as 0.0.
7. The score is the Pearson correlation of the flattened grids, or 0.0 when either grid is constant.
8. Take the best n; ties go to the smaller n. If `best < DIGIT_MIN_SCORE`, return `(None, 0.0)`. Otherwise return `(int(n), round(float(best), 4))`.

**`vote(reads)`**:
- Only reads with `number is not None and conf > 0` count. With none, it returns `(None, 0.0)`.
- `W[n]` is the sum of the confs for n, and `count[n]` the number of reads of n.
- The winner has the largest W; ties go to the smaller n.
- `confidence = round(W[win] / sum(W) * min(1, count[win] / VOTE_MIN_READS), 4)`.
- The winner is returned as a Python `int` and the confidence as a Python `float`, even for numpy-typed inputs.

**`get_reader()`** returns a new `DigitReader()` and never reads os.environ. The OCR slice replaces its body with the `SPORTSCUT_NUMBER_READER` handling from T-033 §2.

## Files
- `sportscut/media.py`: insert-only change (≈ +20 lines).
- `sportscut/jersey.py`: new (≈ 95 lines).
- `tests/test_jersey.py`: new, Developer unit tests (≤ 170 lines).
- `tests/test_t033a_acceptance.py`: new, Tester acceptance tests (≤ 200 lines).
- `docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md`: restored and appended.

No other file changes. In particular: player.py, cli.py, pyproject.toml, README.md, the conftest.py files, tests/test_media.py, tests/fixtures/ and every other existing test file stay as they are.

## Steps (test-first; run `python -m pytest -q tests/test_jersey.py` after each)
0. Before any edit, record the base JSON lines:
   - `python tests/fixtures/eval_player/build.py && python -m sportscut eval-player tests/fixtures/eval_player --json`;
   - `python -m sportscut eval tests/fixtures/eval --json`.
1. Write the `vote` tests (AC1) and watch them fail with ImportError/AttributeError. Then implement the constants and `vote`.
2. Write the DigitReader tests (AC2, AC3). Crops are built by the helper `shirt_crop(n, shirt_rgb, ink=None, k=1)`:
   - a 36×20 crop of (40,140,60) with `crop[2:34, 2:18] = shirt_rgb`;
   - `build._draw_number(crop, n, 2, 2)`;
   - when `ink` is given, pixels equal to (255,255,255) are recoloured to `ink`;
   - `np.repeat(np.repeat(crop, k, 0), k, 1)`.
   Then implement DIGIT_FONT, the templates, border-ink removal and DigitReader.
3. Write the tests for get_reader, the Protocol and import hygiene (AC4, AC5), then implement get_reader.
4. Write the sample_window tests (AC6, AC7):
   - real decode on `build.build_all(tmp)` in a module-scoped fixture that uses the `require_ffmpeg` fixture;
   - args captured by monkeypatching `media.subprocess.run` to record args and return `subprocess.CompletedProcess(args, 0, b"", b"")`;
   - validation, with `media.subprocess.run` and `media.find_tool` patched to raise AssertionError.
   Then implement sample_window with the zero-deletion refactor.
5. Restore the T-033 design spec if it is missing: `git show 11413ad:docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md > docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md` (read-only git, no branch switch). If 11413ad is unreachable, create the file with the title `# T-033: Read jersey numbers around each touch with a pluggable reader and keep only the chosen player` and a one-line note that the full text lives in the T-051 plan. Then append the `## Updated by T-051` section (AC9).
6. Run the full suite and every command below, and quote the summary lines in the report.

## Commands that prove it
- `python -m pytest -q` reports 0 failed.
- `python -m pytest -q tests/test_jersey.py tests/test_t033a_acceptance.py` reports 0 failed.
- `python tests/fixtures/eval_player/build.py && python -m sportscut eval-player tests/fixtures/eval_player --json`: every key except `seconds_per_min` (overall and per clip) equals Step 0, and `seconds_per_min ≤ 6.0`.
- `python -m sportscut eval tests/fixtures/eval --json` equals Step 0.
- `git diff --numstat $(git merge-base main HEAD) -- sportscut/media.py` shows 0 deleted lines.
- `git diff --name-only $(git merge-base main HEAD)` plus `git status --porcelain` list only the five files above. Ignore docs/superpowers INDEX/DECISIONS and the T-051 spec/plan, which the orchestrator writes.
- `git diff --numstat $(git merge-base main HEAD) -- . ':!docs/superpowers'` plus `wc -l` of the untracked new files total < 600. Quote the total.
- `python -c "import sys, sportscut.jersey; print(sorted(m for m in ('sportscut.player','sportscut.media','easyocr','subprocess') if m in sys.modules))"` prints `[]`. (If the interpreter preloads subprocess, the AC5 test checks the jersey source imports instead.)

## Assumptions
- DIGIT_FONT is a literal copy, so the product never imports from tests/. Equality with build.FONT is a test, not an import.
- ffmpeg input seeking (`-ss` before `-i`) lands on the 5 Hz grid frame for these mpeg4 25 fps clips. AC6 allows a mean absolute difference ≤ 2 and 4..6 frames for codec rounding.
- Real-kit accuracy of the digits reader is unknown until `data/eval_player/` exists; this slice measures only the synthetic font.
- The new module has no caller yet, so eval and eval-player output are unchanged by construction. The commands above prove it.

## Test plan

- Step 0 (Developer, before any edit): record the base `sportscut eval-player tests/fixtures/eval_player --json` (after build.py) and `sportscut eval tests/fixtures/eval --json` lines for AC8.
- tests/test_jersey.py (Developer, unit): `test_vote_examples` covers the AC1 cases, including numpy-typed input returning a Python int/float.
- tests/test_jersey.py: `shirt_crop(n, shirt, ink=None, k=1)` helper using build._draw_number. `test_digit_reader_reads_every_number` is parametrized over team in (red, blue) and k in (1, 2, 3) and loops n in 1..99 (AC2). `test_digit_reader_dark_on_light_blank_and_deterministic` covers AC3.
- tests/test_jersey.py: `test_get_reader_ignores_env` (monkeypatch.setenv/delenv for unset/'ocr'/'tesseract'), `test_constants_and_protocol`, and `test_jersey_imports_numpy_only` (an ast walk of the top-level imports plus a subprocess sys.modules check) (AC4, AC5).
- tests/test_jersey.py: `test_sample_window_matches_sample_frames` (require_ffmpeg, module-scoped `build.build_all(tmp_path_factory.mktemp(...))`) (AC6); `test_sample_window_validation_before_ffmpeg` (find_tool/subprocess.run patched to raise AssertionError; parametrized bad windows; missing file) and `test_sample_window_and_sample_frames_args` (captured args, the non-zero return-code MediaError) (AC7).
- Each Developer test is first watched failing for the right reason (missing attribute or wrong value) before the code is written. The Developer also confirms the AC3 dark-on-light test fails when the border-ink step is removed.
- tests/test_t033a_acceptance.py (Tester, ≤ 200 lines, written from AC1-AC7 and AC9, not copied from tests/test_jersey.py): independent crops and arg checks, the T-033 spec appendix check (file exists and ends with `## Updated by T-051` naming sample_window/DigitReader/vote/get_reader), and the get_reader env cases. No git-diff or line-count tests (T-028/T-049 rule). The Tester confirms the tests can fail by temporarily mutating DIGIT_MIN_SCORE to 0.99, swapping the vote tie rule, and moving `-ss` after `-i`, then reverts.
- Full run: `python -m pytest -q` (0 failed). Then the AC8 commands (eval and eval-player JSON vs Step 0, media.py numstat 0 deletions, changed-file list, < 600-line total), quoted in the report.
