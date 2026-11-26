# Plan T-045: Follow the players with a smoothed virtual camera

Design: `docs/superpowers/specs/2026-11-25-t-045-follow-the-players-with-a-smoothed-design.md`.

## Implementation plan

# T-045: Follow the players with a smoothed virtual camera

Request R-004. This is T-019b: the reviewed T-019 design (round-2 spec, office/T-019 + `.agent-office` state), carried over unchanged. T-044 (T-019a) has already re-landed T-017 on main. The only changes from the T-019 text are for main as it is now. They are listed under **Deviations from the T-019 text** at the end. Ball detection is T-020. Rendering and `cut --vertical` are T-043.

## Context (grounded on main 9aa5a85)
- `sportscut/reframe.py` has `ASPECT = 9/16`, `SAMPLE_HZ = 5`, `crop_width(width, height, aspect)` (even, full height), `sample_times(duration)` (5 Hz grid over [0, duration), at least 1 entry) and `plan_crop(video, aspect=ASPECT)`. Today `plan_crop` calls `media.probe_size`, then `crop_width` (validation), then `media.probe_duration`, and returns `[(t, width/2) for t in sample_times(duration)]`. reframe.py imports `math`, `os`, `numbers.Real` and `from sportscut import media`.
- `sportscut/media.py` has `find_tool`, `require_ffmpeg`, `_failure_detail`, `MediaError`, `has_audio`, `probe_duration`, `probe_size`, `extract_audio`, `sample_top_band` (an ffmpeg rawvideo pipe; the pattern to copy), `cut_clip` and `concat_clips`. numpy is already imported.
- `sportscut/eval_crop.py` `evaluate_dir(root)` calls `reframe.plan_crop(path)` through the module. Report keys, in order: ball_in_crop, players_in_crop, jitter, seconds_per_min, per_clip.
- `tests/fixtures/eval_crop/build.py` `build_all(root)` builds 4 clips at 640x360, 25 fps, 12 s on a (40,140,60) field: long_pass, occluded, slow_dribble and white_distractor.
- The README's last section is `## Video dọc 9:16: đo khung cắt (eval-crop)`, with the centre baseline JSON (ball_in_crop 0.2821, players_in_crop 0.4024, jitter 0.0).
- These existing tests pin the centre-crop *values* and break on purpose once plan_crop follows players. Only the edits listed below may touch them: tests/test_eval_crop_fixtures.py, tests/test_t017_acceptance.py (AC15, AC17), tests/test_t042_round2_acceptance.py, tests/test_t042_tester_acceptance.py and tests/test_t044_acceptance.py.
- The conftest `synthetic_video` is 3 s black then 3 s white at 160x120 and 10 fps. `require_ffmpeg` is a session fixture.

## Step 0: precondition (run first; change nothing until it passes)
```bash
test -f sportscut/reframe.py && grep -q 'def plan_crop' sportscut/reframe.py && grep -q 'def sample_times' sportscut/reframe.py && grep -q 'def probe_size' sportscut/media.py && test -f sportscut/eval_crop.py && test -f tests/fixtures/eval_crop/build.py && grep -q 'eval-crop' sportscut/cli.py && test -f tests/test_t017_acceptance.py && echo READY
python -m pytest -q   # on the untouched base: must report 0 failed
```
- If READY is not printed, report `BLOCKED: T-045 needs T-044 (T-017 re-land) merged on the base branch`. List the missing paths and change nothing. Never recreate T-017.
- If the base suite fails, report BLOCKED with the failing test ids. Pre-existing failures belong to the Tech Lead.

## Step 1: measure the baseline (before any code)
```bash
python tests/fixtures/eval_crop/build.py
python -m sportscut eval-crop tests/fixtures/eval_crop --json   # save this line as BEFORE
python -m sportscut eval tests/fixtures/eval --json             # save f1 (expected 0.8421)
```

## Design
The camera moves only horizontally. The crop is always full height and `crop_width(width, height, aspect)` wide (T-017 contract).

### 1. Frame sampling: `sportscut/media.py` (insert after `sample_top_band`, 0 deleted lines)
```python
def sample_frames(path: str | Path, fps: float, width: int, height: int) -> np.ndarray:
    """RGB frames sampled at `fps`, scaled to width x height: uint8 array (n, height, width, 3)."""
```
- A missing file (`not Path(path).is_file()`) raises `MediaError(f"media file not found: {path}")` before ffmpeg runs.
- args: `[find_tool('ffmpeg'), '-v', 'error', '-nostdin', '-i', str(p), '-an', '-sn', '-vf', f'fps={fps},scale={width}:{height}:flags=area', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']`, run with `subprocess.run(args, capture_output=True, check=False)`.
- A non-zero exit raises `MediaError(f"ffmpeg failed for {path}: {_failure_detail(result.stderr, result.returncode)}")`. An audio-only file falls under this rule.
- `frame = width*height*3` and `n = len(stdout) // frame`. A trailing partial frame is dropped. Return `np.frombuffer(stdout, np.uint8)[: n*frame].reshape(n, height, width, 3)`. n can be 0.
- reframe.py never imports subprocess.

### 2. Analysis and camera: `sportscut/reframe.py`
Add `import numpy as np` and `from collections.abc import Sequence`. Add these module constants. Only the last three may be tuned, and only as described in step 7.
```python
ANALYSIS_WIDTH = 320      # analysis frame width in px (never upscaled)
GREEN_HUE = (60.0, 180.0) # HSV hue range of grass, degrees
GREEN_MIN_SAT = 0.20      # HSV saturation in [0, 1]
GREEN_MIN_VAL = 0.15      # HSV value in [0, 1]
FIELD_MIN = 0.25          # share of green pixels for 'field detected'
FIELD_ROW_MIN = 0.30      # share of green pixels for a row to count as field
MIN_MASS = 20             # eroded player pixels needed for a measurement
DEAD_ZONE = 0.03          # fraction of frame width
EASE = 0.5                # share of the error beyond the dead zone closed per sample
MAX_PAN = 0.2             # fraction of frame width per second
```

`green_mask(frame: np.ndarray) -> np.ndarray`
- Input is RGB uint8 (h, w, 3). Output is bool (h, w).
- HSV is computed in float numpy:
  - V = max/255.
  - S = (max-min)/max, or 0 when max = 0.
  - H is in degrees with the standard formula (0 when max == min): max==R gives 60*((G-B)/d mod 6), max==G gives 60*((B-R)/d + 2), max==B gives 60*((R-G)/d + 4).
- A pixel is green when GREEN_HUE[0] <= H <= GREEN_HUE[1], S >= GREEN_MIN_SAT and V >= GREEN_MIN_VAL.

`player_mask(frame: np.ndarray) -> np.ndarray | None`
- Returns None when `green.mean() < FIELD_MIN` (no field).
- A field row has a green share >= FIELD_ROW_MIN.
- A pixel is inside the field when it is in a field row and between that row's first and last green pixel (both inclusive).
- The candidates are the inside pixels that are not green.
- Apply a 3x3 binary erosion with numpy slicing. A pixel stays True only when all 9 pixels of its 3x3 neighbourhood are candidates. Frame-border pixels are False.
- Return the eroded bool mask.

`target_x(frame: np.ndarray, crop_cols: int) -> float | None`
Returns the mass centroid of the crop-wide window that holds the most player mass, in analysis-column units (column c has centre c + 0.5).
- Return None when player_mask is None or the total mass is < MIN_MASS.
- `col = mask.sum(axis=0)` and `k = min(crop_cols, w)`.
- Window sums `S[i] = col[i:i+k].sum()` for i in 0..w-k, computed with a cumsum. `i* = argmax` (the first maximum).
- Return `sum((c+0.5)*col[c]) / sum(col[c])` over c in [i*, i*+k).

`smooth_path(targets: Sequence[float | None], width: int, cw: int, dead_zone: float = DEAD_ZONE, ease: float = EASE, max_pan: float = MAX_PAN) -> list[float]`
- Set `lo, hi = cw/2, width - cw/2`, `dz = dead_zone*width` and `max_step = max_pan*width/SAMPLE_HZ`.
- Start: x0 = clamp(targets[0], lo, hi) when targets[0] is not None, else width/2.
- For each later target:
  - None: x is held.
  - Otherwise: `err = target - x`. step = 0 when |err| <= dz, else `ease*(err - sign(err)*dz)`. Then step = clamp(step, -max_step, max_step) and x = clamp(x + step, lo, hi).
- Returns one x per target, and [] for [].

`center_plan(video, aspect=ASPECT) -> list[tuple[float, float]]`
The T-017 baseline, copied verbatim from today's plan_crop body: probe_size, then crop_width(width, height, aspect), then probe_duration, then return `[(t, width/2) for t in sample_times(duration)]`. It decodes no frames.

`plan_crop(video, aspect=ASPECT) -> list[tuple[float, float]]` (replace the body and docstring)
1. `width, height = media.probe_size(video)`.
2. `cw = crop_width(width, height, aspect)`, so a bad aspect raises before probe_duration.
3. `times = sample_times(media.probe_duration(video))`.
4. `aw = min(ANALYSIS_WIDTH, width)`, `ah = max(2, 2*round(height*aw/width/2))` and `k = max(1, round(cw*aw/width))`.
5. `frames = media.sample_frames(video, SAMPLE_HZ, aw, ah)`, called through the `media` module so tests can monkeypatch it.
6. For i < len(times): when frame i exists and `tx = target_x(frames[i], k)` is not None, `targets[i] = tx*width/aw`, else None. Extra frames are ignored.
7. Return `list(zip(times, smooth_path(targets, width, cw)))`.

This keeps the T-017 plan contract: non-empty, t strictly increasing on the 5 Hz grid, and x in [cw/2, width-cw/2]. A clip with no field anywhere gives exactly width/2 everywhere. That covers synthetic_video, the black lavfi clip and close-ups.

### 3. Interpolation to the clip frame rate
The plan stays as 5 Hz keyframes. Per-frame positions come from the T-017 contract (np.interp, held at the ends), which the vertical renderer evaluates at every output frame. Per-frame keyframes would give the same positions and only bloat the render expression.

## Files to touch
| File | Change |
|---|---|
| `sportscut/media.py` | add `sample_frames` after `sample_top_band` (0 deleted lines) |
| `sportscut/reframe.py` | imports, constants, `green_mask`, `player_mask`, `target_x`, `smooth_path`, `center_plan`; replace the body and docstring of `plan_crop` |
| `tests/test_media.py` | append sample_frames tests |
| `tests/test_reframe.py` | append tests; existing tests stay unchanged and must pass |
| `tests/test_eval_crop_fixtures.py` | `test_center_crop_baseline_and_oracle`: add `monkeypatch.setattr(reframe, 'plan_crop', reframe.center_plan)` as its first line; nothing else changes |
| `tests/test_t017_acceptance.py` | AC15 and AC17 edits (below) |
| `tests/test_t042_round2_acceptance.py` | E1, E2, E3 |
| `tests/test_t042_tester_acceptance.py` | E2, E3 |
| `tests/test_t044_acceptance.py` | E4 |
| `tests/test_t045_acceptance.py` | **new**, written by the Tester |
| `README.md` | new Vietnamese section, inserted immediately before `## Video dọc 9:16: đo khung cắt (eval-crop)` |
| `docs/superpowers/specs/2026-11-23-t-017-add-a-measurable-9-16-reframing-design.md` | append `(updated by T-019)` bullets |
| `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md` | append one `(updated by T-019)` bullet about `media.sample_frames` |
| `docs/superpowers/specs/2026-11-24-t-042-land-the-t-017-9-16-design.md` | append one `Updated by T-045` note (E1-E3) |
| `docs/superpowers/specs/2026-11-25-t-044-re-land-the-reviewed-t-017-design.md` | append one `Updated by T-045` note (E4) |

### Documented edits to existing tests
These follow an intended spec change (plan_crop is no longer the centre crop). They do not weaken any test: every baseline-value assertion is kept and runs against `reframe.center_plan`.
- **AC15** (`tests/test_t017_acceptance.py::test_ac15_cli_json_matches_independent_baseline`): keep the CLI run and its shape assertions (exit 0, one JSON line, key order, 4 per_clip). Add `report['jitter'] <= 0.002` to it. Add the `monkeypatch` parameter. Move `jitter == 0.0`, `ball_in_crop == _independent_center_crop_score(built_eval_dir)` and `ball_in_crop < 0.95` to an in-process `eval_crop.evaluate_dir(built_eval_dir)` run after `monkeypatch.setattr(reframe, 'plan_crop', reframe.center_plan)`.
- **AC17** (`test_ac17_cli_pretty_output_and_nonexistent_error`): `json.loads(pretty.stdout)['jitter'] == 0.0` becomes `<= 0.002`. Nothing else changes.
- **E1** (`test_t042_round2_acceptance.py::test_ac1_ac2_public_crop_contract_and_short_duration`): next to the existing probe_size/probe_duration patches, add `monkeypatch.setattr(reframe.media, 'sample_frames', lambda *a, **k: np.zeros((0, 2, 2, 3), np.uint8))` and `import numpy as np`. The expected `[(0.0, 320.0), (0.2, 320.0)]` stays.
- **E2** (`test_ac2_ported_files_and_probe_size_match_reviewed_t017` in round2 and `test_ac2_reviewed_files_and_probe_size_match_the_reviewed_commit` in tester): define a module tuple `CHANGED_BY_T019 = ('sportscut/reframe.py', 'tests/test_reframe.py', 'tests/test_eval_crop_fixtures.py', 'tests/test_t017_acceptance.py', 'docs/superpowers/specs/2026-11-23-t-017-add-a-measurable-9-16-reframing-design.md')`. Diff only `[p for p in PORTED_PATHS if p not in CHANGED_BY_T019]` against office/T-017-r2. The eval_crop.py, fixtures, test_eval_crop.py and T-017 plan paths stay, and so does the probe_size identity check.
- **E3** (`test_ac5_eval_crop_matches_readme_baseline` in round2, `test_ac5_eval_crop_cli_matches_the_readme_baseline` in tester): add the `monkeypatch` parameter and run `monkeypatch.setattr(eval_crop.reframe, 'plan_crop', reframe.center_plan)` before `evaluate_dir` / `cli.main`. Import `eval_crop` and `reframe` from sportscut inside the test. Every assertion stays.
- **E4** (`test_t044_acceptance.py::test_e_eval_crop_cli_on_built_fixtures_matches_readme`, new compared with T-019, the same intent as AC15): keep the build, the subprocess CLI run and its shape assertions (exit 0, one line, key order). Add `report['jitter'] <= 0.002`. Add the `monkeypatch` parameter. Move `ball_in_crop == 0.2821`, `players_in_crop == 0.4024`, `jitter == 0.0` and `_without_timings(report) == _without_timings(_readme_baseline())` to an in-process `eval_crop.evaluate_dir(tmp_path)` run with `reframe.plan_crop` patched to `reframe.center_plan`. Do not introduce a `"--name-only", "main"`-style two-dot diff (test_f).
- These need no edit: T-042 AC3 (append-only), AC7 (README ends with the eval-crop section), AC10 (protected paths), the T-044 `test_d_*` README checks, and T-017 AC5 (synthetic_video has no field, so plan_crop is still static there). Do not edit them. If any other existing test fails because of this task, stop and report it to the Tech Lead instead of editing it.

Do not change: `sportscut/eval_crop.py`, `sportscut/cli.py`, `sportscut/pipeline.py`, `sportscut/evaluate.py`, `sportscut/eval_player.py`, `sportscut/export.py`, `sportscut/events/**`, `tests/fixtures/eval_crop/**`, `tests/test_eval_crop.py`, `tests/conftest.py`, the T-017 plan, `pyproject.toml`, `.gitignore`, `agent-office/`. Commit no mp4. Never write the git index (no add, checkout -- path, mv, stash or commit).

## Steps (TDD: write each test, watch it fail for the right reason, then write the code)
1. Run Step 0, then Step 1. Record BEFORE and the f1.
2. `sample_frames`: append the tests to test_media.py, then implement.
3. `green_mask` / `player_mask`: write the numpy-only AC3/AC4 tests, then implement.
4. `target_x`: write the AC5 tests, then implement.
5. `smooth_path`: write the AC6 exact-number tests, then implement.
6. `center_plan` and the new `plan_crop`: write the AC7-AC9 tests. Clips are built in tmp_path from numpy frames piped into `ffmpeg -v error -y -f rawvideo -pix_fmt rgb24 -s 640x360 -r 25 -i pipe:0 -an -c:v mpeg4 -q:v 2 -pix_fmt yuv420p out.mp4` (subprocess.run with `input=frames.tobytes()`), behind `require_ffmpeg`. Then implement, apply AC15/AC17 and E1-E4, and run `python -m pytest -q`.
7. Measure AFTER with `python -m sportscut eval-crop tests/fixtures/eval_crop --json`.
   - Gate: AFTER.ball_in_crop > BEFORE.ball_in_crop, AFTER.players_in_crop > BEFORE.players_in_crop, AFTER.jitter <= 0.002 and AFTER.seconds_per_min <= 6.0.
   - If the gate fails, tune only DEAD_ZONE in [0.02, 0.08], EASE in [0.2, 0.6] and MAX_PAN in [0.1, 0.3], then re-measure.
   - If no combination passes, stop and report the numbers to the Tech Lead. Never weaken a test or the gate.
   - AC6 passes its parameters explicitly, so its numbers never change.
   - Time a 720p clip:
```bash
ffmpeg -v error -y -f lavfi -i testsrc2=s=1280x720:r=25:d=60 -c:v libx264 -preset ultrafast -pix_fmt yuv420p /tmp/t045_720p.mp4 || ffmpeg -v error -y -f lavfi -i testsrc2=s=1280x720:r=25:d=60 -c:v mpeg4 -q:v 2 -pix_fmt yuv420p /tmp/t045_720p.mp4
python -c "import time; from sportscut import reframe; s=time.perf_counter(); reframe.plan_crop('/tmp/t045_720p.mp4'); print(round(time.perf_counter()-s, 2))"
```
   It must print <= 6.0, which means 5 minutes of clips take <= 30 s.
8. Docs:
   - README: insert `## Camera ảo bám cầu thủ (T-019)` in Vietnamese immediately before the eval-crop section. It holds:
     - a short method description: green-field HSV mask, non-green mass inside the field, the crop-wide window with the most mass, dead zone + exponential easing + max pan speed, hold and then centre when there is no field
     - the final `DEAD_ZONE`, `EASE` and `MAX_PAN` values
     - the line `Ngưỡng jitter: jitter ≤ 0.002 (trung bình |sai phân bậc 2| trên lưới 5 Hz / chiều rộng khung)`
     - `Trước (T-017, center crop):` followed by the BEFORE JSON line, and `Sau (T-019):` followed by the AFTER JSON line, both copied from real runs. Put them in ```text fences, not ```json, and never repeat the eval-crop heading text inside this section, because other tests locate the baseline JSON by that heading.
     - the 720p timing
   - Leave the eval-crop section byte-identical and last.
   - T-017 design spec: append `(updated by T-019)` bullets. They say plan_crop now follows the players, the centre baseline lives on as `reframe.center_plan`, and baseline-value tests patch plan_crop to center_plan. AC5 still holds on synthetic_video because it has no field.
   - T-036 design spec: append one `(updated by T-019)` bullet describing `media.sample_frames`.
   - T-042 and T-044 design specs: append one `Updated by T-045:` line each, naming the E1-E3 / E4 edits.
9. The PR description reports BEFORE and AFTER (all 4 top-level numbers plus per-clip ball_in_crop and players_in_crop), the final constants, the 720p timing and the unchanged f1.

## Size budget
The target is < 600 changed lines outside docs/superpowers:
- reframe.py about 130
- media.py about 30
- Developer tests <= 200
- existing-test edits <= 55
- README <= 25
- Tester acceptance <= 160

It is one gated algorithmic slice. Splitting it would land a plan_crop change without its eval gate.

## Assumptions
- Grass is HSV hue 60-180 degrees with S >= 0.2 and V >= 0.15. The fixture field (40,140,60) has a hue of about 132 degrees and S of about 0.71.
- Players, the ball, referees and white shirts all count as player mass (YAGNI). Ball-specific logic is T-020.
- Painted lines (<= 2 px at analysis scale) and overlays outside each row's green span are not players.
- Only exported clips are analysed, so holding all sampled frames in memory (about 26 MB per 30 s at 320x180) is fine.
- With no measurement the camera holds its position. At the start of a clip with no measurement yet it sits at the centre and later eases from there without jumping.

## Deviations from the T-019 text (main changed after it was written)
- AC2 now checks only that `sportscut/reframe.py` does not import subprocess. The 'only media.py imports subprocess' wording is already false on main, because T-015's `sportscut/events/incidents.py` imports it, and T-045 must not touch events.
- E4 is added for `tests/test_t044_acceptance.py::test_e_*`, which landed after T-019 was written and pins the centre values through a subprocess CLI run. It gets the same treatment as T-017 AC15.
- The Tester file is `tests/test_t045_acceptance.py`. The README strings and the spec markers keep the T-019 names (`(T-019)`, `Sau (T-019):`, `(updated by T-019)`), because T-019 is the design ID that T-045 lands.

## Test plan

- tests/test_media.py (append): test_sample_frames_shape_and_content on synthetic_video (fps 5, 80x60; shape, dtype uint8, dark frames before index 14, bright from index 16); test_sample_frames_missing_file; test_sample_frames_audio_only_raises (anullsrc .m4a built in tmp_path, require_ffmpeg).
- tests/test_reframe.py (append, numpy-only frames): test_green_mask_colours; test_player_mask_eroded_rectangle_exact; test_player_mask_ignores_thin_line_crowd_rows_and_side_band; test_player_mask_no_field_returns_none (all grey, and 20% green).
- tests/test_reframe.py: test_target_x_centroid_of_heaviest_window (== 112.0); test_target_x_low_mass_or_no_field_none.
- tests/test_reframe.py: test_smooth_path_exact_values (every AC6 list); test_smooth_path_converges_to_dead_zone_edge; test_smooth_path_pure_easing; test_smooth_path_random_bounds_speed_and_hold (np.random.default_rng(0)).
- tests/test_reframe.py: test_center_plan_is_t017_baseline (monkeypatch media.sample_frames to raise); test_plan_crop_follows_static_players; test_plan_crop_no_field_is_centre; test_plan_crop_starts_centre_then_eases; test_plan_crop_holds_when_field_lost. The last four use a helper that pipes numpy RGB frames into ffmpeg (rawvideo rgb24 640x360 at 25 fps -> mpeg4 -q:v 2) in tmp_path and need require_ffmpeg.
- Existing-test edits, each to be shown in the diff:
  - tests/test_eval_crop_fixtures.py: one added center_plan monkeypatch line.
  - tests/test_t017_acceptance.py AC15: CLI shape plus jitter <= 0.002, and the baseline values checked in-process with center_plan.
  - tests/test_t017_acceptance.py AC17: jitter <= 0.002.
  - tests/test_t042_round2_acceptance.py: E1, E2, E3.
  - tests/test_t042_tester_acceptance.py: E2, E3.
  - tests/test_t044_acceptance.py: E4.
  Before the code change, each edited baseline test must still pass against center_plan, which proves the edit kept its assertion.
- tests/test_t045_acceptance.py (Tester, written from the ACs, not from the Developer tests): AC1-AC13.
  - AC10 runs the before/after gate on `build.build_all(tmp_path)`, importing build.py with importlib like the T-017 tests, and compares BEFORE to the README baseline JSON without seconds_per_min.
  - AC11 runs the CLI in a subprocess.
  - AC12 checks the README section order and the strings in the README and the 4 specs.
  - AC13 checks append-only numstat against `git merge-base main HEAD` and skips when git or main is unavailable. Use no two-dot `main` diffs.
  - It proves AC6 can fail: a smoother without the speed cap breaks the step bound.
  - It proves AC9's hold check can fail: a smoother that returns to centre on None breaks it.
- Commands, with the summary lines quoted in the report: the Step 0 block; `python -m pytest -q`; `python tests/fixtures/eval_crop/build.py && python -m sportscut eval-crop tests/fixtures/eval_crop --json` before and after; `python -m sportscut eval tests/fixtures/eval --json` (f1 0.8421 unchanged); the 720p timing command from step 7 (<= 6.0).

## Deviations

- (Developer, T-045) The T-036 design spec bullet about `media.sample_frames` is inserted right after the existing `Updated by T-030` media line, not at the very end of the file. `tests/test_t004_acceptance.py::test_documentation_acceptance` requires that spec to end with the `Updated by T-004` line, and that test is not one of the documented edits. The file still has 0 deleted lines.
- (Developer, T-045) Step 7 tuning was needed: with the starting constants (0.03, 0.5, 0.2) AFTER jitter was 0.005855 (> 0.002). A grid over DEAD_ZONE 0.02-0.08 (step 0.01), EASE 0.2-0.6 (step 0.05) and MAX_PAN 0.1-0.3 (step 0.025) found 66 of 567 combinations passing the gate. Chosen: DEAD_ZONE = 0.06, EASE = 0.2, MAX_PAN = 0.1 (jitter 0.001658, more margin than the highest-coverage pass 0.05/0.2/0.1 at jitter 0.001912).
