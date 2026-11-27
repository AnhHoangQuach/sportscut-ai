# Plan T-020: Detect the ball and let it drive the crop, with the player cluster as fallback

Design: `docs/superpowers/specs/2026-11-23-t-020-detect-the-ball-and-let-it-design.md`.

## Implementation plan

# T-020: Detect the ball and let it drive the crop, with the player cluster as fallback

Request R-004. Builds on T-045 (T-019b), which is merged on main as a3f277e.

## Context (current main)

- `sportscut/reframe.py` (T-045) does the following:
  - It samples frames at `SAMPLE_HZ = 5` through `media.sample_frames(video, 5, aw, ah)`, with `aw = min(320, width)`.
  - It builds `green_mask` and `player_mask`, the eroded non-green mass inside the field. `player_mask` returns None when green covers < 25% of the frame.
  - `target_x(frame, k)` returns the mass centroid of the heaviest crop-wide window (k analysis columns).
  - `smooth_path(targets, width, cw, dead_zone, ease, max_pan)` applies a dead zone, easing, a pan cap and clamping, and holds on None.
  - `plan_crop(video)` returns `[(t, x)]` on `sample_times(duration)`.
- The player-mode constants are `DEAD_ZONE = 0.06`, `EASE = 0.2` and `MAX_PAN = 0.1`. tests/test_t045_acceptance.py pins them to the README. Two tests require a step of at most 25.6 px when no ball is visible: tests/test_reframe.py:220 and tests/test_t045_acceptance.py:226. **These player constants therefore stay unchanged.**
- `sportscut/eval_crop.py` scores a plan as follows:
  - ball_in_crop: the share of labelled ball centres inside `[x - cw/2, x + cw/2]`.
  - players_in_crop: the same share for player box centres.
  - jitter: the mean |second difference| on the 5 Hz grid, divided by the width.
- The synthetic set is `tests/fixtures/eval_crop/build.py`: 4 clips at 640x360, 12 s each, with cw = 202. The ball is a white disk with r = 4, which is about 4.5 px wide at the 320-px analysis scale.
  - long_pass: the ball moves 100 -> 560 in 1 s.
  - occluded: the ball passes behind a blue player.
  - slow_dribble: the ball moves slowly with players around it.
  - white_distractor: there is a 2-px white line at x = 319..320 and a 14x30 white player.
- BEFORE is the T-045 camera, from the README `Sau (T-019)` line: `{"ball_in_crop": 0.5812, "players_in_crop": 0.5988, "jitter": 0.001658, ...}`.
  - Per clip: long_pass 0.6, occluded 0.7222, slow_dribble 1.0, white_distractor 0.0167.
- The T-045 decisions bind this task: jitter <= 0.002, and players_in_crop must not fall below the T-045 value.
- `data/eval_crop/` does not exist in this checkout.

## Design

Everything is added to `sportscut/reframe.py`. Use numpy only: no OpenCV, no new dependency and no subprocess. Frames are the same 5 Hz analysis frames that T-045 already decodes, so there is no second decode.

### 1. `field_mask(frame) -> np.ndarray | None` (refactor, behaviour-preserving)

- Return the bool (h, w) inside-field mask. This is the existing `inside` computation from `player_mask`: rows with >= FIELD_ROW_MIN green, between that row's first and last green pixel.
- Return None when `green.mean() < FIELD_MIN`.
- `player_mask` becomes `field_mask` & ~green, followed by the same 3x3 erosion. Its output is unchanged: the T-045 AC4 tests are the guard.

### 2. `ball_candidates(frame) -> list[tuple[float, float, float]]`

This is grid scoring with an integral image. Coordinates are in analysis pixels.

- If `field_mask(frame)` is None, return `[]`.
- `bright = (frame.min(axis=-1) >= BALL_LEVEL) & field`. This means white-ish pixels inside the field only.
- Build the integral image of `bright`. For each odd box size `s` in `BALL_BOXES = (3, 5)`, look at every pixel (r, c) whose outer box fits fully inside the frame:
  - The inner box is s x s, centred on (r, c).
  - The outer box is (s + 2*BALL_RING) x (s + 2*BALL_RING), with `BALL_RING = 2`, centred on (r, c).
  - `inner` is the bright count in the inner box. `ring` is the outer count minus the inner count.
  - The pixel is a hit when `ring == 0` (the blob is isolated, so lines, white kits and large blobs are rejected) and `inner >= BALL_FILL * s*s` (the blob is compact, about circular, and has a plausible size).
- For each hit:
  - `x = mean(cols of bright pixels in the inner box) + 0.5` and `y = mean(rows) + 0.5`.
  - `score = inner / (s*s)`.
- Sort hits by (-score, y, x). Then use greedy suppression: drop any hit within Euclidean distance `BALL_NMS = 3.0` of a hit already kept.
- Return the kept hits as float tuples `(x, y, score)`.

### 3. `track_ball(samples, gate, lost_after=BALL_LOST) -> list[tuple[float, float] | None]`

This is a pure function. `samples[i]` is the candidate list of sample i.

- The state is `pos` (None when not tracking), `vel = (0, 0)` and `misses = 0`.
- **When not tracking:**
  - If there are candidates, acquire the first candidate with the maximum score (list order breaks ties). Set `pos` to it, `vel = 0` and `misses = 0`, and output `pos`.
  - Otherwise output None.
- **When tracking:** compute `pred = pos + vel * (misses + 1)`. In-gate candidates are those with distance to `pred` <= `gate`.
  - **Hit:** take the nearest in-gate candidate (first on ties). Set `vel = (c - pos) / (misses + 1)`, `pos = c` and `misses = 0`, and output `c` as (x, y).
  - **Miss:** `misses += 1`. If `misses >= lost_after`, the ball is lost: set `pos = None`, `vel = 0` and `misses = 0`, and output None. Otherwise output the held `pos`, the last hit, while coasting.
- A non-None output means the ball is "confident".

### 4. `blend_weights(ball, step=BLEND_STEP) -> list[float]`

- Start with `w0 = 1.0` if `ball[0]` is not None, else `0.0`.
- For i >= 1: `w_i = min(1.0, w_{i-1} + step)` when `ball[i]` is not None, else `max(0.0, w_{i-1} - step)`.
- `[]` returns `[]`.

### 5. `framed_x(frame, crop_cols, ball_x, margin) -> float`

This is the ball-mode target in analysis pixels. It frames as many players as possible while the ball stays inside the crop.

- Allowed camera centres are `[ball_x - margin, ball_x + margin]`.
- Use `mask = player_mask(frame)`, `col = mask.sum(axis=0)`, `k = min(crop_cols, w)` and window starts `s` in `0..w-k`, each with centre `s + k/2`.
- Among starts whose centre is inside the allowed range, take the first argmax of the window mass.
- If `mask` is None, no start is allowed, or the best window mass is < MIN_MASS, return `float(ball_x)`.
- Otherwise return the mass centroid of that window (the same formula as `target_x`), clamped to `[ball_x - margin, ball_x + margin]`.

### 6. `smooth_path` gains per-sample gains (the same smoother, reused)

- `dead_zone`, `ease` and `max_pan` may each be a float, as before, or a sequence with `len == len(targets)`. A length mismatch raises `ValueError`.
- The step into sample i (i >= 1) uses the i-th values. Index 0 is never used.
- Called with floats, the output is identical to T-045.

### 7. `plan_crop(video, aspect)` wiring

The signature and return contract are unchanged.

- Probe the video, compute times and frames, and set `k`, `aw` and `scale = width / aw` exactly as T-045 does.
- `cands[i] = ball_candidates(frames[i])` when `i < len(frames)`, else `[]`.
- `ball = track_ball(cands, BALL_GATE * aw, BALL_LOST)`, then `w = blend_weights(ball, BLEND_STEP)`, then `margin = (0.5 - BALL_EDGE) * k`.
- For each i:
  - `p = target_x(frames[i], k)`, or None when the frame is missing.
  - Update `last_b = ball[i][0]` when `ball[i]` is not None.
  - If `last_b is None` or `w[i] == 0`, then `t = p`.
  - Otherwise `f = framed_x(frames[i], k, last_b, margin)`, or `last_b` when the frame is missing. Then `t = f` if `p is None` or `w[i] == 1`, else `w[i]*f + (1 - w[i])*p`.
  - The target is `None if t is None else t * scale`.
- Per-sample gains are linear interpolations: `dz_i = DEAD_ZONE + w_i*(BALL_DEAD_ZONE - DEAD_ZONE)`, and the same for `ease` with `BALL_EASE` and for `max_pan` with `BALL_MAX_PAN`.
- Return `list(zip(times, smooth_path(targets, width, cw, dz, ease, pan)))`.
- With no ball candidates anywhere, every `w` is 0, so the plan is exactly the T-045 plan. All T-045 tests keep passing unchanged.
- A ball-to-player switch is a target cross-fade over 1/BLEND_STEP samples and passes through the capped smoother, so no step can exceed `max(MAX_PAN, BALL_MAX_PAN) * width / SAMPLE_HZ`.

### New constants

Each constant has a start value and a permitted tuning range. Tuning happens only on the synthetic eval. The final values are recorded in the README.

| Constant | Start value | Range | Meaning |
| --- | --- | --- | --- |
| `BALL_LEVEL` | 160 | [140, 200] | min RGB channel for a bright pixel |
| `BALL_FILL` | 0.4 | [0.3, 0.6] | minimum inner fill |
| `BALL_GATE` | 0.25 | [0.2, 0.4] | fraction of the analysis width |
| `BALL_LOST` | 5 | [3, 10] | samples |
| `BLEND_STEP` | 0.25 | [0.1, 0.5] | weight change per sample |
| `BALL_EDGE` | 0.15 | [0.05, 0.3] | fraction of the crop width kept between the ball and the crop edge |
| `BALL_DEAD_ZONE` | 0.02 | [0.01, 0.06] | |
| `BALL_EASE` | 0.6 | [0.3, 0.8] | |
| `BALL_MAX_PAN` | 0.5 | [0.2, 0.6] | |

These are fixed and not tunable: `BALL_BOXES = (3, 5)`, `BALL_RING = 2` and `BALL_NMS = 3.0`.

## Files to touch

- `sportscut/reframe.py`: add `field_mask`, `ball_candidates`, `track_ball`, `blend_weights`, `framed_x` and the constants. Extend `smooth_path`. Rewire `plan_crop`.
- `tests/test_reframe.py`: append-only (0 deleted lines). These are the Developer's unit and integration tests.
- `tests/test_t020_acceptance.py`: the Tester's file.
- `README.md`:
  - Insert the new section `## Camera bám bóng (T-020)` immediately before `## Video dọc 9:16: đo khung cắt (eval-crop)`.
  - The README is insert-only (0 deleted lines). The eval-crop section stays last and byte-identical.
  - The new section uses ```text fences, never ```json, and never contains the text `eval-crop)`.
  - It contains the brief algorithm, one `` `NAME = value` `` line per tunable constant, `Trước (T-045, chỉ cầu thủ):` + BEFORE JSON, `Sau (T-020):` + AFTER JSON, the 720p timing, and a real-clip line.
- `docs/superpowers/specs/2026-11-25-t-045-follow-the-players-with-a-smoothed-design.md`: append an `Updated by T-020` note covering three points:
  - `smooth_path` accepts per-sample gains.
  - `plan_crop` is ball-driven with player fallback.
  - The T-045 player constants are unchanged.

Do not touch: `sportscut/eval_crop.py`, `cli.py`, `media.py`, `vertical.py`, `pipeline.py`, `tests/fixtures/` (builder and labels), any other existing test, `pyproject.toml`, `.gitignore`, `agent-office/`, and any `.mp4`.

## Steps (test-first)

0. **Base check.**
   - On the untouched worktree, run `python -m pytest -q`; it must report 0 failed.
   - Run `python tests/fixtures/eval_crop/build.py && python -m sportscut eval-crop tests/fixtures/eval_crop --json > /tmp/t020_before.json`. This is the BEFORE JSON, kept outside the repo.
   - If the suite fails, report BLOCKED with the failing test ids and change nothing.
1. **field_mask.**
   - Write the field_mask test (AC2). Watch it fail with AttributeError.
   - Extract `field_mask` and make `player_mask` use it.
   - Run `python -m pytest -q tests/test_reframe.py tests/test_t045_acceptance.py`; it must be green.
2. **smooth_path per-sample gains.**
   - Write the tests (AC7). Watch them fail.
   - Add a helper `_at(param, i)` that returns `param` if it is a Real, else `param[i]`. Validate the lengths.
3. **ball_candidates.** Write the tests (AC3), watch them fail, then implement the integral-image scoring and the suppression.
4. **track_ball.** Write the tests (AC4), watch them fail, then implement.
5. **blend_weights.** Write the tests (AC5), watch them fail, then implement.
6. **framed_x.** Write the tests (AC6), watch them fail, then implement.
7. **plan_crop wiring.**
   - Write the integration tests (AC8-AC11) with ffmpeg-built clips in tmp_path. Use the T-045 `_clip` helper pattern: rawvideo rgb24 -> mpeg4 q:v 2, 640x360, 25 fps. Watch them fail.
   - Wire `plan_crop`.
8. **Tune.**
   - Run the AC12 test and `python -m sportscut eval-crop tests/fixtures/eval_crop --json`.
   - Tune only within the ranges until AC12 holds.
   - If no setting within the ranges meets every gate, stop and report BLOCKED with the best JSON. Do not widen a range on your own.
9. **Timing.** Run the AC14 command.
10. **Real clips.** If `data/eval_crop/` exists, run eval-crop on it on the base and after the change, and put both JSON lines in the PR.
11. **Docs.** Write the README section and the T-045 spec note (AC15).
12. **Final checks.** Run `python -m pytest -q` (0 failed) and `python -m sportscut eval tests/fixtures/eval --json`, which must give the base f1, 0.8421.

## Commands that prove done

```bash
python -m pytest -q
python tests/fixtures/eval_crop/build.py
python -m sportscut eval-crop tests/fixtures/eval_crop --json   # ball_in_crop >= 0.95, jitter <= 0.002, players_in_crop >= BEFORE
python -m sportscut eval tests/fixtures/eval --json             # f1 unchanged (0.8421)
ffmpeg -v error -y -stream_loop 4 -i tests/fixtures/eval_crop/white_distractor/clip.mp4 -vf scale=1280:720 -t 60 -c:v mpeg4 -q:v 2 -an /tmp/t020_720p.mp4
python -c "import time; from sportscut import reframe; s=time.perf_counter(); reframe.plan_crop('/tmp/t020_720p.mp4'); print(round(time.perf_counter()-s, 2))"   # <= 6.0
```

## Assumptions

- "No jitter regression" means the R-004 bound recorded by T-045: aggregate jitter <= 0.002. "No drop in players_in_crop" means AFTER >= the T-045 camera, measured in the same run with ball detection disabled. The recorded reference value is 0.5988.
- "ball_in_crop >= 0.95 on the synthetic set" is the aggregate value. The two named hard clips must each reach >= 0.9, so that the aggregate cannot hide a broken occlusion or distractor case.
- The ball is white-ish. Coloured winter balls are out of scope, and the real-clip numbers decide on a YOLO follow-up.
- PR notes must include the following:
  - BEFORE/AFTER JSON for the synthetic set.
  - The 720p timing.
  - Real-clip BEFORE/AFTER, or the line "no data/eval_crop clips available".
  - When real-clip ball_in_crop is < 0.8, a one-line proposal for a separate `[vision]` YOLO request (not implemented here).

## Test plan

- tests/test_reframe.py (Developer, append-only): test_field_mask_inside_region_and_none (AC2).
- tests/test_reframe.py: test_smooth_path_per_sample_gains_exact, test_smooth_path_sequence_length_mismatch_raises and test_smooth_path_scalar_equals_constant_sequences (AC7).
- tests/test_reframe.py: test_ball_candidates_single_3x3, test_ball_candidates_two_blobs_order, test_ball_candidates_4x4_score and a parametrised test_ball_candidates_rejects for the line, the 7x15 white, the 8x8 white, red, grey, outside-field and all-grey cases (AC3).
- tests/test_reframe.py: test_track_ball_* with one test per AC4 sequence: steady, constant-velocity distractor, gated miss holds, lost then reacquire, velocity across the gap, highest-score acquisition, and empty.
- tests/test_reframe.py: test_blend_weights_ramp_and_edges (AC5) and test_framed_x_clamp_window_and_fallbacks (AC6).
- tests/test_reframe.py (integration, require_ffmpeg): build clips in tmp_path with a `_ball_clip(path, frames)` helper using the T-045 rawvideo->mpeg4 command. Tests: test_plan_crop_no_ball_equals_t045_plan (AC8, monkeypatch ball_candidates), test_plan_crop_follows_moving_ball (AC9), test_plan_crop_pass_catches_up (AC10) and test_plan_crop_ball_lost_falls_back_smoothly (AC11).
- tests/test_t020_acceptance.py (Tester, written from the ACs, not from the Developer's tests): the scope test gated to `office/T-020*` branches (AC1). It re-derives the AC3-AC7 exact cases independently. It runs the AC8-AC11 clips, the module-scoped eval set built with build.build_all(tmp) for the AC12 BEFORE/AFTER gate (BEFORE via monkeypatched ball_candidates), the AC13 CLI subprocess check, and the AC15 README/spec checks.
- Tester mutation checks (show that the tests can fail): (1) monkeypatch track_ball to ignore velocity (pred = pos) and assert the AC4 constant-velocity case fails; (2) monkeypatch blend_weights to return hard 0/1 switches and assert the AC11 step-cap check fails; (3) patch ball_candidates to drop the ring test (ring==0) and assert the AC3 line case fails; (4) patch plan_crop to center_plan and assert the AC12 gate fails.
- Fixtures: no new committed fixtures. All clips are built in tmp_path with ffmpeg, and the eval set comes from tests/fixtures/eval_crop/build.py into tmp. No .mp4 is committed.
