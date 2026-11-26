# T-045: Follow the players with a smoothed virtual camera

Request R-004. Plan: `docs/superpowers/plans/2026-11-25-t-045-follow-the-players-with-a-smoothed.md`.

## Product Owner request

Tự xuất video dọc 9:16 cho TikTok/Reels: tự bám theo bóng và cầu thủ để crop, có phụ đề và tỉ số.

## Goal

The T-019 spec, acceptance criteria and file list, unchanged (green-field HSV mask, player mass, best crop-wide window centroid, dead zone + easing + max pan, hold then centre fallback, center_plan baseline, eval-crop BEFORE/AFTER gate, jitter <= 0.002, 720p timing <= 6.0 s, and the documented edits E1-E3, AC15 and AC17). Starts from a main that contains T-019a. Step 0 must print READY.

## Acceptance criteria

- AC1: Step 0 prints READY and the untouched base suite reports 0 failed. Otherwise the Developer reports BLOCKED with the exact missing paths or the failing test ids, and changes nothing. `git diff --name-only $(git merge-base main HEAD)` lists none of: sportscut/eval_crop.py, sportscut/cli.py, sportscut/pipeline.py, sportscut/evaluate.py, sportscut/eval_player.py, sportscut/export.py, sportscut/events/, tests/fixtures/eval_crop/, tests/test_eval_crop.py, tests/conftest.py, docs/superpowers/plans/2026-11-23-t-017-add-a-measurable-9-16-reframing.md, pyproject.toml, .gitignore, agent-office/, any .mp4. `git ls-files '*.mp4'` is empty.
- AC2: `media.sample_frames(synthetic_video, 5, 80, 60)` returns a uint8 ndarray of shape (n, 60, 80, 3) with 29 <= n <= 31. Every frame at index < 14 has mean < 30, and every frame at index >= 16 has mean > 225. A missing file raises MediaError `media file not found: <path>`. An audio-only file (anullsrc .m4a) raises MediaError matching `^ffmpeg failed for `. `sportscut/reframe.py` contains no `import subprocess`.
- AC3: `reframe.green_mask` is True for RGB (40,140,60) and (36,128,54), and False for (200,30,30), (30,60,200), (255,255,255), (0,0,0) and (128,128,128).
- AC4: Start from a 180x320 frame filled with (40,140,60), with a red (200,30,30) rectangle at rows 40:56, cols 100:108. `player_mask` is True exactly at rows 41..54 x cols 101..106 (84 pixels). Each of these additions leaves the mask unchanged: a white 2-column line at cols 159:161 over the full height; grey (128,128,128) rows 0:30 with a red rectangle at rows 5:25, cols 200:210; grey cols 0:20 over all rows with a red rectangle at rows 100:120, cols 5:15. An all-grey frame and a frame with only 20% green pixels both return None.
- AC5: On the green 180x320 frame with red rectangles at [40:56, 100:108], [40:56, 116:124] and [100:116, 250:258], `target_x(frame, 101) == 112.0` (within 1e-9). It returns None for a single 4x4 red rectangle (mass < MIN_MASS) and for an all-grey frame.
- AC6: With width=640, cw=202, dead_zone=0.03, ease=0.5 and max_pan=0.2, `smooth_path` returns (all within 1e-9): [None, None, 400.0] -> [320.0, 320.0, 345.6]; [200.0, 230.0, 260.0] -> [200.0, 205.4, 223.1]; [300.0, 310.0, 280.9, None, 319.0] -> [300.0]*5; [10.0] -> [101.0]; [700.0] -> [539.0]; [] -> []. For [101.0] + [539.0]*80, the path never decreases, every step is <= 25.6 + 1e-9, no value exceeds 519.8 + 1e-9, and the last value is within 1e-3 of 519.8. With dead_zone=0 and max_pan=10, [320, 420, 420, 420] -> [320, 370, 395, 407.5]. For 200 targets from np.random.default_rng(0), uniform in [0, 640] with 20% None: every |x[i+1]-x[i]| is <= 25.6 + 1e-9, every x lies in [101, 539], and every x at a None equals the previous x.
- AC7: `reframe.center_plan(video)` equals `[(t, width / 2) for t in sample_times(duration)]` and never calls `media.sample_frames` (a test monkeypatches it to raise). `plan_crop(synthetic_video) == [(t, 80.0) for t in reframe.sample_times(6.0)]`. `plan_crop(missing)` raises MediaError. `plan_crop(video, aspect=0)` raises ValueError before `media.probe_duration` is called.
- AC8: Build a 4 s, 640x360, 25 fps clip in tmp_path from frames filled with (40,140,60), with static red rectangles at cols 96:112 and 128:144, rows 150:182. `plan_crop` returns exactly `len(sample_times(4.0))` pairs whose t values equal `sample_times(4.0)`, and every x is in [101, 140]. On an all-grey (128,128,128) clip of the same size and length, every x == 320.0.
- AC9: On a clip of 2 s all grey followed by 2 s of the AC8 field with rectangles, x == 320.0 for every t <= 1.8. After that, x never increases, each step is <= 25.6 + 1e-6, and the last x is < 320. On a clip of 2 s AC8 field followed by 2 s all grey, every x at t >= 2.0 equals the x at t = 1.8 (hold).
- AC10: Build the eval set with `build.build_all(tmp)`. AFTER is `eval_crop.evaluate_dir(tmp)`. BEFORE is the same call with `reframe.plan_crop` monkeypatched to `reframe.center_plan`. AFTER.ball_in_crop > BEFORE.ball_in_crop, AFTER.players_in_crop > BEFORE.players_in_crop, AFTER.jitter <= 0.002 and AFTER.seconds_per_min <= 6.0. BEFORE equals the README eval-crop baseline JSON in every field except seconds_per_min. Two plan_crop calls on the same clip return identical lists.
- AC11: `python -m sportscut eval-crop <built set> --json` exits 0 and prints one JSON line with the T-017 key order and 4 per_clip entries. Its jitter is <= 0.002. The PR description quotes the BEFORE and AFTER JSON and the 720p timing command output, which is <= 6.0 s for a 60 s 1280x720 clip.
- AC12: README contains `## Camera ảo bám cầu thủ (T-019)`, located before `## Video dọc 9:16: đo khung cắt (eval-crop)`. That section contains `Ngưỡng jitter: jitter ≤ 0.002`, `Trước (T-017, center crop):`, `Sau (T-019):`, `DEAD_ZONE`, `EASE` and `MAX_PAN`. The eval-crop section is still the last section, and the README diff against the merge base has 0 deleted lines. The T-017 design spec contains `(updated by T-019)` and `center_plan`. The T-036 design spec contains `(updated by T-019)` and `sample_frames`. The T-042 and T-044 design specs each contain `Updated by T-045`.
- AC13: `python -m pytest -q` reports 0 failed. Existing tests change only by the documented edits: the test_eval_crop_fixtures.py baseline monkeypatch, T-017 AC15 (baseline values moved to center_plan, CLI jitter <= 0.002), T-017 AC17 (jitter `<= 0.002`), E1-E3 in the two T-042 acceptance files, and E4 in tests/test_t044_acceptance.py. tests/test_media.py, tests/test_reframe.py and sportscut/media.py are append-only (0 deleted lines in `git diff --numstat $(git merge-base main HEAD)`). `python -m sportscut eval tests/fixtures/eval --json` prints the same f1 as the base (0.8421).

## Out of scope

- Ball detection, blob scoring and ball/player blending (T-020).
- Rendering 1080x1920 clips, `cut --vertical`, and pipeline/API/web wiring (T-043); subtitles and the scoreline overlay (later R-004 tasks).
- Vertical crop movement or zoom; any aspect other than the T-017 full-height crop.
- Emitting per-video-frame keyframes from plan_crop (interpolation stays the T-017 linear contract).
- Hysteresis or tracking across windows, Kalman filters, multi-object tracking, YOLO/OpenCV or any new dependency.
- CLI flags or config for the camera constants.
- Changing eval_crop metrics, the fixture builder or the labels, or making eval-crop a CI gate; any change to the `sportscut eval` F1 gate.
- Recreating or re-porting T-017 (T-044 did that).
- Removing subprocess from sportscut/events/incidents.py or touching any events module.
- Editing any existing test beyond AC15, AC17 and E1-E4, or fixing unrelated pre-existing failures.
- Hand-labelled real clips in data/eval_crop/ (report numbers only if they exist; not required).

## Decisions

- T-045 (R-004): T-045 is T-019b, the reviewed T-019 round-2 design landed unchanged on a main that contains T-044 (T-019a). Step 0 is the T-019 check that tests/test_t044_acceptance.py already proves prints READY, and the untouched base suite must report 0 failed. A missing T-017 is never recreated.
- T-045 (R-004): Frames are read only through the new `media.sample_frames(path, fps, width, height)`: an ffmpeg rawvideo rgb24 pipe with `fps=...,scale=W:H:flags=area`, -an -sn, the same pattern as sample_top_band, inserted after sample_top_band with 0 deleted lines. A missing file raises `media file not found`; an ffmpeg failure raises `ffmpeg failed for <path>: ...`. reframe.py never imports subprocess.
- T-045 (R-004): Analysis scale: width = min(320, source width), height = the even rounding of the source aspect. Frames are sampled at reframe.SAMPLE_HZ (5 Hz), and the plan's t values are exactly sample_times(duration). Missing trailing frames count as no measurement, and extra frames are ignored.
- T-045 (R-004): Field detection uses an HSV green mask (hue 60-180 deg, S >= 0.2, V >= 0.15). There is no field when green covers < 25% of the frame. A pixel is inside the field when its row has >= 30% green and it lies between that row's first and last green pixel. Player mass is the non-green pixels inside the field after a 3x3 erosion, which removes lines <= 2 px and speckle.
- T-045 (R-004): The robust target is the mass centroid inside the crop-wide window (crop width at analysis scale) with the most player mass, taking the first argmax. It replaces the brief's plain weighted median, which flips between player groups and can land on empty grass. A measurement needs >= 20 eroded pixels.
- T-045 (R-004): The virtual camera (smooth_path, 5 Hz) has a dead zone of 0.03 x width, exponential easing that closes 0.5 of the error beyond the dead zone per sample, a speed cap of 0.2 x width per second, and clamping to [cw/2, width - cw/2]. It starts at the first target, or at the centre when there is none. With no measurement it holds its position, so a clip with no field anywhere stays at width/2. Tuning is allowed only within DEAD_ZONE [0.02, 0.08], EASE [0.2, 0.6] and MAX_PAN [0.1, 0.3], and README records the final values.
- T-045 (R-004): Per-frame interpolation stays the T-017 contract: linear between the 5 Hz keyframes, held at the ends, evaluated per output frame by the vertical renderer. plan_crop emits no per-frame keyframes.
- T-045 (R-004): The T-017 centre baseline is kept as `reframe.center_plan(video, aspect)`. Tests that asserted centre values on the real plan_crop now patch plan_crop to center_plan: test_eval_crop_fixtures, T-017 AC15, T-042 AC5 in both T-042 files (E3) and T-044 test_e (E4). CLI-level checks keep the shape assertions and use jitter <= 0.002 (T-017 AC15/AC17, E4). Mocked-media plan_crop tests also patch media.sample_frames (E1). T-042's byte-equality diff against office/T-017-r2 excludes the CHANGED_BY_T019 paths (E2). These follow an intended spec change and do not weaken the tests.
- T-045 (R-004): E4 is new compared with T-019. tests/test_t044_acceptance.py::test_e_* landed after the T-019 spec and pins centre values through a subprocess CLI run, which a monkeypatch cannot reach. It gets the same treatment as T-017 AC15: the CLI shape plus jitter <= 0.002 in the subprocess, and the baseline values in-process with center_plan.
- T-045 (R-004): T-019's AC2 clause 'no sportscut module other than media.py imports subprocess' is narrowed to 'reframe.py does not import subprocess'. It is already false on main because of T-015's sportscut/events/incidents.py, which is out of scope here.
- T-045 (R-004): The merge gate on the synthetic eval-crop set is: ball_in_crop and players_in_crop both strictly above the center_plan baseline (0.2821 / 0.4024), jitter <= 0.002 and seconds_per_min <= 6.0. A 60 s 1280x720 clip must plan in <= 6.0 s, reported in the PR. jitter is eval-crop's mean |second difference| on the 5 Hz grid divided by the frame width, which is the stricter reading of '0.2% of the frame width per frame'.
- T-045 (R-004): jitter <= 0.002 is the R-004 'low jitter' bound. Later R-004 tasks (T-020) must keep jitter <= 0.002 and must not lower players_in_crop below the T-045 value.
- T-045 (R-004): The README section `## Camera ảo bám cầu thủ (T-019)` is inserted immediately before the eval-crop section. Its JSON lines use ```text fences and it never repeats the eval-crop heading text, so the T-042/T-044 README readers still find the T-017 baseline. The eval-crop section stays last and byte-identical, and README stays append-only.
- T-045 (R-004): README strings and spec markers keep the T-019 design name (`(T-019)`, `Sau (T-019):`, `(updated by T-019)`). The Tester file is tests/test_t045_acceptance.py. The T-042 and T-044 specs get an `Updated by T-045` note for E1-E4.
- T-045 (R-004): The size budget is < 600 changed lines outside docs/superpowers, above the usual ~400. This is one gated algorithmic slice plus the documented test edits; splitting it would land a plan_crop change without its eval gate.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-017-add-a-measurable-9-16-reframing-design.md`
- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`
- `docs/superpowers/specs/2026-11-24-t-042-land-the-t-017-9-16-design.md`
- `docs/superpowers/specs/2026-11-25-t-044-re-land-the-reviewed-t-017-design.md`

## Updated by T-020

- Updated by T-020: `smooth_path` accepts per-sample gains. `dead_zone`, `ease` and `max_pan` may each be a scalar (unchanged T-045 behaviour) or a sequence with one value per target; a length mismatch raises ValueError.
- Updated by T-020: `plan_crop` is ball-driven with player fallback. A tracked white ball drives the camera (the heaviest player window near the ball), cross-faded with the T-045 player target by a ball-confidence weight. With no ball candidates the plan is exactly the T-045 plan.
- Updated by T-020: the T-045 player constants are unchanged (`DEAD_ZONE = 0.06`, `EASE = 0.2`, `MAX_PAN = 0.1`); ball mode uses its own `BALL_DEAD_ZONE`, `BALL_EASE` and `BALL_MAX_PAN`, interpolated by the weight. See `docs/superpowers/specs/2026-11-23-t-020-detect-the-ball-and-let-it-design.md`.
