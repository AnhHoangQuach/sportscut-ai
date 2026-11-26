# T-017: Add a measurable 9:16 reframing eval with synthetic tracked clips and a center-crop baseline

Request R-004. Plan: `docs/superpowers/plans/2026-11-23-t-017-add-a-measurable-9-16-reframing.md`.

## Product Owner request

Tự xuất video dọc 9:16 cho TikTok/Reels: tự bám theo bóng và cầu thủ để crop, có phụ đề và tỉ số.

## Goal

Goal of R-004: `sportscut cut match.mp4 --vertical` also writes 1080x1920 (9:16) versions of every highlight clip. The crop window follows the ball and players, and each clip has burned-in subtitles and the live scoreline. We will know the crop is good when `sportscut eval-crop tests/fixtures/eval_crop --json` prints `{"ball_in_crop", "players_in_crop", "jitter", "seconds_per_min", "per_clip": [...]}` with ball_in_crop >= 0.95 and low jitter, and when the end-to-end CLI test produces playable vertical clips. Approaches considered: (a) cheap numpy heuristics on ffmpeg frames sampled at about 5 fps (green-field mask, player mass, bright ball blob) plus a smoothed virtual camera, (b) YOLO ball/person detection as an optional `[vision]` extra, (c) full multi-object tracking (ByteTrack and similar). We pick (a) because it needs no model and no extra install and fits the CPU budget, since only the exported clips (10 x 30 s at most) are analysed. (b) is a follow-up only if real-clip numbers fall short. This task: add `sportscut/reframe.py` with `plan_crop(video, aspect=9/16) -> list[(t, x_center)]`, which for now returns a static center crop (the baseline). Add `tests/fixtures/eval_crop/build.py`, which generates 4 idempotent synthetic clips with ffmpeg/numpy (640x360, 25 fps, about 12 s each, gitignored mp4): a green pitch, a white ball and coloured player rectangles on known trajectories, with these cases: slow dribble, fast long pass across the field, ball hidden behind a player for about 1 s, and a white-shirt or white-line distractor. Next to each clip, commit `labels.json` as `[{"t", "ball": [x,y] | null, "players": [[x,y,w,h], ...]}]` at 5 Hz. Sparse labels are allowed, so the PO can hand-label real clips in `data/eval_crop/`. Add the `sportscut eval-crop DIR --json` subcommand and record the center-crop baseline in the README. Assumptions: R-001's pipeline (T-001..T-004: media layer, export_clips, `sportscut cut`) is merged first. The existing F1 quality gate is unchanged; this metric is reported in the PRs of the R-004 tasks.

## Acceptance criteria

- AC1: The Step 0 precondition command prints READY on the task's base. Otherwise the Developer reports BLOCKED and changes nothing.
- AC2: `media.probe_size(path)` returns `(width, height)` as ints: `(160, 120)` for the conftest synthetic_video. It raises MediaError `media file not found: <path>` for a missing file and `no video stream in <path>` for an audio-only file.
- AC3: `reframe.crop_width(640, 360) == 202`, `crop_width(1920, 1080) == 606` and `crop_width(720, 1920) == 720`. A non-positive or bool width/height, or an aspect that is <= 0, non-finite or bool, raises ValueError.
- AC4: `reframe.sample_times(12.0)` returns 60 times from 0.0 to 11.8 in 0.2 s steps, and `sample_times(0.1) == [0.0]`. A duration <= 0 or nan raises ValueError.
- AC5: `reframe.plan_crop(video)` returns `[(t, width / 2) for t in sample_times(duration)]`, which equals `[(t, 80.0) ...]` with 30 items for synthetic_video. A missing file raises MediaError, and `aspect=0` raises ValueError.
- AC6: `tests/fixtures/eval_crop/build.py` never imports sportscut. `build_all(dir)` creates exactly the cases slow_dribble, long_pass, occluded and white_distractor. Each has a clip.mp4 that probes to 640x360 with duration 12.0 ± 0.05 s, plus a labels.json.
- AC7: A second `build_all` without force leaves every clip.mp4 `st_mtime_ns` unchanged, and `force=True` re-encodes it. No .mp4 under tests/fixtures/eval_crop is tracked or unignored by git.
- AC8: The committed `tests/fixtures/eval_crop/<case>/labels.json` text equals `labels_text(case)` for all 4 cases. Each has 60 entries `{t, ball, players}` at t = 0.0..11.8 (5 Hz), with integer pixel coordinates inside the 640x360 frame.
- AC9: Only the occluded case has `ball: null` labels, as one consecutive run of 4–8 labels inside t ∈ [4.6, 6.4]. render_frame at a hidden time contains no pure-white pixel, and at a visible time it contains ≥ 20.
- AC10: long_pass has a ball speed ≥ 300 px/s between some consecutive labels, and slow_dribble never exceeds 60 px/s. white_distractor renders ≥ 200 pure-white pixels outside the ball, and its ball x is > 421 at every label.
- AC11: `eval_crop.load_labels` accepts sparse, unsorted labels, `ball: null` and a missing `players` key. For each malformed input listed in the spec (non-list, empty, bad t, bad ball, bad players, invalid JSON) it raises ValueError prefixed with the file path.
- AC12: For each case, `eval_crop.evaluate_dir` validates that clip.mp4 exists and that its labels parse before calling plan_crop at all. A missing clip gives ValueError containing `run python tests/fixtures/eval_crop/build.py`. A non-directory or a directory with no cases raises ValueError.
- AC13: A plan that breaks the contract raises ValueError `plan_crop returned an invalid plan for <case>: ...`. That covers an empty plan, t not strictly increasing, a non-finite value, or x outside [cw/2, width - cw/2].
- AC14: Scoring is as specified. The window is inclusive and the plan is interpolated with np.interp. Ball and player hits are micro-averaged across clips, and a metric is null when it has no labels. jitter is the mean |second difference| of the 5 Hz-resampled centre divided by width, rounded to 6 decimals. Other floats are rounded to 4. The top-level key order is ball_in_crop, players_in_crop, jitter, seconds_per_min, per_clip, and per_clip entries are `{clip, duration, labels, ball_labels, player_boxes, ball_in_crop, players_in_crop, jitter, seconds_per_min}` sorted by clip name.
- AC15: Running `python -m sportscut eval-crop tests/fixtures/eval_crop --json` after building prints exactly one line of JSON with those keys and 4 per_clip entries. The baseline has jitter == 0.0 and ball_in_crop < 0.95, equal to the value computed independently from the committed labels with the window [219, 421]. Exit code 0.
- AC16: An oracle plan that follows the labelled ball (clipped to [101, 539]) scores ball_in_crop == 1.0 on the synthetic set, which proves the 0.95 target is reachable and the eval discriminates.
- AC17: `sportscut eval-crop` without --json prints indented JSON. ValueError/OSError/MediaError print `sportscut eval-crop: error: <msg>` to stderr and exit 2.
- AC18: README has the Vietnamese eval-crop section with the build and eval commands, the label format, the metric definitions and the baseline JSON copied from a real run in this task. The T-036 design spec has the T-017 exception bullet.
- AC19: `python -m pytest -q` passes, and every pre-existing test is unchanged except the append-only test_media.py and test_cli.py. `sportscut/evaluate.py` and `sportscut/eval_player.py` are unchanged, so the `sportscut eval` F1 gate behaves exactly as before.

## Out of scope

- Any real ball/player detection or smoothed virtual camera (green-field mask, blobs, Kalman/EMA): later R-004 tasks.
- Rendering 1080x1920 clips, the `cut --vertical` flag, burned-in subtitles and the live scoreline.
- The YOLO `[vision]` extra and multi-object tracking (ByteTrack).
- Vertical crop movement or zoom (the crop is always full height); frame-accurate rendering at 25 fps.
- Making eval-crop a CI gate or setting a numeric jitter threshold; any change to the `sportscut eval` F1 gate, evaluate.py or eval_player.py.
- Hand-labelling real clips in data/eval_crop/ (the PO does that later); a labelling tool.
- Editing .gitignore or committing any mp4.

## Decisions

- T-017 depends on T-004 and T-010. Both are merged (#19, #27), and the Step 0 grep check prints READY on main as of 2026-11-23. A missing foundation is never recreated inside T-017.
- Crop geometry: the crop is always full source height with width `min(width, max(2, 2*floor(height*aspect/2)))`, which is even. It is 202 px for 640x360 and 606 px for 1920x1080. Only the horizontal centre moves.
- Plan contract: `plan_crop(video, aspect=9/16) -> list[(t, x_center)]`, non-empty, finite, t strictly increasing, x within [cw/2, width - cw/2]. Between samples the centre is linearly interpolated (np.interp, held at the ends). Rendering tasks must use the same interpolation. The baseline samples at 5 Hz (`reframe.sample_times`) with x = width/2 and decodes no frames.
- `media.probe_size(path) -> (width, height)` is the single place that probes frame size (ffprobe v:0 stream=width,height). Missing file → `media file not found`; no video stream → `no video stream in <path>`.
- Label format: `<DIR>/<case>/{clip.mp4, labels.json}`, where labels.json is a list of `{t, ball: [x,y] | null, players?: [[x,y,w,h], ...]}` in source pixels with top-left boxes. ball is required (null = not visible, excluded from ball_in_crop). players is optional (missing = not labelled). Sparse and unsorted labels are allowed. Real clips go in data/eval_crop/ in the same layout.
- Metric definitions:
- ball_in_crop: the share of non-null ball labels whose centre x lies inside the interpolated crop window, edges inclusive with 1e-9 tolerance.
- players_in_crop: the same test applied to the player box centre x.
- Both are micro-averaged over all clips and are null when there are no labels.
- jitter: the mean |second difference| of the crop centre resampled on the 5 Hz grid over [0, duration), divided by frame width, rounded to 6 decimals (0.0 for a static camera).
- seconds_per_min: total plan_crop wall time / total clip minutes.
- Other floats are rounded to 4 decimals.
- Report shape: the top-level key order is ball_in_crop, players_in_crop, jitter, seconds_per_min, per_clip. per_clip entries are `{clip, duration, labels, ball_labels, player_boxes, ball_in_crop, players_in_crop, jitter, seconds_per_min}`, sorted by directory name.
- The eval validates every case (clip exists, labels parse) before calling plan_crop, and calls `reframe.plan_crop`, `media.probe_size` and `media.probe_duration` through their modules so tests and later experiments can monkeypatch them (matches T-029/T-030).
- The CLI command `eval-crop DIRECTORY [--json]` prints compact JSON with --json and indent=2 JSON otherwise. ValueError/OSError/MediaError print `sportscut eval-crop: error: <msg>` and exit 2, mirroring eval-player and eval.
- Synthetic set:
- 4 cases (slow_dribble, long_pass, occluded, white_distractor), each 640x360, 25 fps and 12.0 s.
- Keyframe trajectories are fixed in build.py; labels are at 5 Hz, 60 per clip, with integer pixels.
- Players are drawn on top of the ball. The ball is labelled null exactly when its 9x9 square is fully inside a player box.
- white_distractor adds a white-shirt player and a white halfway line, and its ball never enters the center crop.
- build.py is standalone (it never imports sportscut), deterministic and idempotent. It encodes with the built-in mpeg4 encoder (-q:v 2, yuv420p, no audio) per T-036, and writes labels one entry per line. It may write git-ignored clip.mp4 files into tests/fixtures/eval_crop/ (the same exception as T-029, recorded in the T-036 design spec). pytest builds only in temp dirs.
- The center-crop baseline is recorded in README from a real run. It must have jitter 0.0 and ball_in_crop < 0.95 (about 0.28 by PM derivation). An oracle that follows the labelled ball must reach 1.0, which proves the target is reachable.
- The R-004 target is ball_in_crop >= 0.95 on the synthetic set with low jitter. eval-crop is reported in R-004 PRs but is not a CI gate, and the existing F1 gate is unchanged.
- Tech Lead (dev_blocked): 2026-11-23 Tech Lead (T-017): restart from the latest base only after T-004 and T-010 merge; the blocker is missing prerequisite scheduling, not an implementation failure, and waiting also prevents overlapping CLI/eval work.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`
- `docs/superpowers/specs/2026-11-23-t-029-build-the-player-touch-eval-synthetic-design.md`
- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-010-add-event-types-to-segments-and-design.md`
