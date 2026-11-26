# T-043: Render vertical 9:16 clips from a crop path and add `sportscut cut --vertical`

Request R-004. Plan: `docs/superpowers/plans/2026-11-24-t-043-render-vertical-9-16-clips-from.md`.

## Product Owner request

Tự xuất video dọc 9:16 cho TikTok/Reels: tự bám theo bóng và cầu thủ để crop, có phụ đề và tỉ số.

## Goal

Implement T-018 exactly as specified in docs/superpowers/specs/2026-11-23-t-018-render-vertical-9-16-clips-from-design.md and docs/superpowers/plans/2026-11-23-t-018-render-vertical-9-16-clips-from.md, with acceptance criteria AC1-AC14 unchanged. Add media.filter_video, sportscut/vertical.py (crop_x_expression as a flat clip-ramp expression, vertical_filter, render_vertical), pipeline.run(vertical=False), the CLI flag `cut --vertical` writing OUT/vertical/clip_NN.mp4 at 1080x1920 with a vertical_file manifest key, a README Vietnamese section, and appended 'Updated by T-018' notes in the T-004 and T-036 specs. Run the Step 0 precondition first. It must print READY now that T-018a is merged. If it prints BLOCKED, report it and do not recreate reframe.py or probe_size. Files: sportscut/vertical.py, sportscut/media.py, sportscut/pipeline.py, sportscut/cli.py, tests/test_vertical.py, tests/test_media.py, tests/test_pipeline.py, tests/test_cli.py (the last three append-only), tests/test_t018_acceptance.py, README.md, and the two spec files. Verify per the spec's Verify section, including eval f1 unchanged and eval-crop unchanged.

## Acceptance criteria

- AC1: The Step 0 precondition prints READY on the task's base (T-017 merged). Otherwise the Developer reports BLOCKED and changes nothing.
- AC2: `media.filter_video(path, video_filter, dest)` re-encodes with the given -vf filter (libx264, yuv420p) and returns Path(dest). `filter_video(synthetic_video, 'scale=32:24', o)` probes to (32, 24) with an aac audio stream. A missing input raises MediaError `media file not found: <path>`, and an invalid filter raises MediaError matching `^ffmpeg failed for <path>: .+`. No other module in sportscut/ imports subprocess.
- AC3: `vertical.crop_x_expression([(0.0, 101.0), (1.0, 201.0)], 640, 202) == '0.0000+100.000000*(clip(t,0.0000,1.0000)-0.0000)'` and `crop_x_expression([(0, 320), (1, 320)], 640, 202) == '219.0000'`. The expression contains no `if(` and is flat (no nesting other than the clip terms).
- AC4: For any valid crop path with t values of at most 4 decimals, evaluating the expression with clip(v,lo,hi)=min(max(v,lo),hi) equals np.interp(t, ts, clamped_left_edges) within 0.01 px at the keyframes, at midpoints, before the first and after the last keyframe. For [(0, -1000), (1, 5000)] on a width of 640 and crop 202, the values are 0 at t=0, 219 at t=0.5 and 438 at t>=1, and they never leave [0, width - crop_w].
- AC5: An empty crop path, an item that is not a pair of finite non-bool numbers, a first t < 0, or t not strictly increasing each raise ValueError whose message starts with `invalid crop path: `. render_vertical raises it before calling media.probe_size, even when the clip does not exist. An expression longer than 100000 characters raises ValueError `crop path too long: <n> keyframes`.
- AC6: `vertical.vertical_filter([(0.0, 320.0)], 640, 360) == "crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1"`.
- AC7: `render_vertical(clip, crop_path, out)` on a synthetic clip returns Path(out) and creates missing parent directories. ffprobe reports video codec h264 at exactly 1080x1920 and audio codec aac, and its duration is within 0.3 s of the input clip's.
- AC8: On a synthetic 640x360, 25 fps, 4 s clip with a 20x20 white marker whose centre moves as x = 120 + 100*t (y centred), render_vertical with the crop path [(k/5, 120 + 100*k/5) for k in range(20)] gives frames at t = 0.5, 1.5, 2.5 and 3.5 whose white pixels (gray > 200) exist and have a column centroid within 540 ± 108 px. With the static centre path [(0.0, 320.0)], the frames at t = 0.5 and 3.5 have no white marker pixels, which shows the check can fail.
- AC9: `pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True)` writes out/vertical/clip_01.mp4 (1080x1920). The returned entry has exactly the keys start, end, score, reason, event, event_confidence, file, vertical_file in that order, with vertical_file == 'vertical/clip_01.mp4', and the return value equals json.loads(out/highlights.json).
- AC10: With `vertical=True`, pipeline.run calls `reframe.plan_crop(out/<file>)` for each exported clip and passes its exact return value to `vertical.render_vertical(out/<file>, <that value>, out/'vertical'/<file>)`; this is verified with monkeypatched module attributes.
- AC11: Without vertical (the default), pipeline.run never calls plan_crop or render_vertical, creates no out/vertical directory, and the manifest entries have no vertical_file key. All pre-existing tests pass unchanged (test_media, test_pipeline and test_cli only gain appended tests).
- AC12: `sportscut cut VIDEO --out OUT --top 1 --min-len 4 --max-len 6 --vertical` exits 0 and prints exactly two lines, `OUT/clip_01.mp4` then `OUT/vertical/clip_01.mp4`, with empty stderr. The CLI forwards `vertical=True` with the flag and `vertical=False` without it. Without the flag, stdout is identical to before (one clip path per line).
- AC13: The T-004 design spec has an appended `## Updated by T-018` section and its existing AC lines are unedited (AC1 still contains `events=None`). The T-036 design spec has the appended `Updated by T-018` filter_video note, and README has the Vietnamese vertical section.
- AC14: `python -m pytest -q` reports 0 failed. `sportscut eval tests/fixtures/eval --json` gives the same f1 as on the base. No .mp4 is tracked by git.
- AC15 [T-043 r2]: Against `git merge-base main HEAD`, `git diff --numstat` shows 0 deleted lines for each of:
- sportscut/media.py, sportscut/cli.py, README.md;
- tests/test_media.py, tests/test_pipeline.py, tests/test_cli.py;
- the T-004 and T-036 design specs.

README's new `## Video dọc 9:16 cho TikTok/Reels (cut --vertical)` section comes before `## Video dọc 9:16: đo khung cắt (eval-crop)`, which stays the last section, byte-identical. The T-036 `Updated by T-018` paragraph sits before that spec's final `Updated by T-004` paragraph, which is still the last text in the file, so test_t004_acceptance::test_documentation_acceptance passes. The eval-crop JSON on the same built set equals the base in every field except seconds_per_min. An existing test outside the append-only files may be edited only by the E1, E2 or E3 branch gates, each applied only when that test fails purely as a branch-diff scope check. Each gate is listed in the PR with its test id, the gated test reports skipped on the T-043 branch, and nothing else in its file changes.

## Out of scope

- Recreating, porting or changing reframe.py, sample_times, plan_crop, probe_size, eval_crop.py or the eval-crop CLI (T-044 owns them; on BLOCKED the task stops).
- Ball and player tracking, or smoothing of the crop path (T-019 and later R-004 tasks).
- Burned-in subtitles and the live scoreline overlay (later R-004 tasks).
- Output size, quality, CRF, preset or encoder options; letterboxing or padding for sources narrower than 9:16; vertical crop movement or zoom.
- sendcmd-based rendering and filter-script files.
- Vertical output in the HTTP API, the web upload/preview pages, the T-007 manual re-export, or the `sportscut player` reel.
- Cleaning stale files in OUT/vertical/; parallel rendering; progress output.
- Any change to detection, ranking, export naming, the eval/eval-crop/eval-player modules, tests/fixtures/ or tests/conftest.py.
- Reworking other scope tests beyond the conditional E1/E2/E3 branch gates, and gating the T-042 append-only or README-ends-with tests (T-043 must satisfy them).

## Decisions

- T-043 restarts from main @ 9aa5a85 (T-044 merged). Its dependency is T-044, not the dropped T-042. This spec replaces the blocked T-043 design/plan from wip commit e3d392c, which never reached main. AC1-AC14 are T-018's ACs verbatim; AC15 holds the base-specific checks.
- Step 0 was verified READY by the PM on 9aa5a85: reframe.plan_crop, reframe.crop_width and media.probe_size all exist.
- The ffmpeg call lives in `media.filter_video(path, video_filter, dest)`. It encodes with libx264 -preset veryfast and yuv420p, maps `-map 0:v:0 -map 0:a?`, copies audio with -c:a copy, and sets +faststart. It is appended to media.py, so media stays the only module that runs ffmpeg (T-036). vertical.py only validates the path and builds the filter.
- The time-varying crop is one flat ffmpeg expression: left_0 plus clipped linear ramps `±s*(clip(t,a,b)-a)`, with zero slopes dropped. It reproduces np.interp held at the ends (the T-017 contract).
- Nested if() is rejected because of the expression nesting limit, and sendcmd because it gives step changes.
- More than 100000 characters raises ValueError.
- Left edges and times are formatted .4f, slopes .6f.
- Crop geometry: w = reframe.crop_width(W, H), h = H, y = 0. Centres are clamped to [cw/2, W-cw/2], not rejected. The filter is `crop=w=CW:h=H:x='EXPR':y=0,scale=1080:1920,setsar=1`. The output is fixed at 1080x1920 H.264 with audio stream-copied.
- pipeline.run gains `vertical: bool = False` as its last parameter. When it is true, each exported clip goes through reframe.plan_crop and then vertical.render_vertical(clip, path, out_dir/'vertical'/<file>). The manifest is rewritten in export's format (indent=2 + newline), with `vertical_file` (POSIX `vertical/<file>`) as the last key.

When it is false, behaviour and bytes are identical to before. Both modules are called through module attributes (`from sportscut import reframe`, `from sportscut import vertical as vertical_mod`), and errors are not wrapped.
- The CLI change only adds lines:
- `--vertical` (store_true);
- a new `vertical=args.vertical,` line after `events=args.events,`;
- a guarded second print after the existing print.

This keeps cli.py append-only for the T-042 shared-file tests.
- README gets an inserted section, `## Video dọc 9:16 cho TikTok/Reels (cut --vertical)`, placed immediately before the eval-crop section. The eval-crop section stays last and byte-identical, as the test_t042 ac7 tests require, and README has 0 deleted lines.
- [r2] The T-036 `Updated by T-018` note is inserted immediately before that spec's final `Updated by T-004` paragraph, not at the end of the file. This is required because test_t004_acceptance::test_documentation_acceptance asserts the file ends with the T-004 paragraph. The `Updated by T-017` note set this precedent. The rule for later tasks: new notes in the T-036 spec go before the final T-004 paragraph.
- The T-004 spec gets an appended `## Updated by T-018` section after `## Updated by T-039`. Its AC lines stay unedited because test_t012 checks their text.
- [r2] On 9aa5a85, test_t014 ac15 no longer forbids media.py (T-044), and test_t034b ac9_ac10 checks only frozen paths (T-015), so E1/E2 are expected to be unnecessary. E1, E2 and the Tech Lead's pre-approved E3 are applied only when such a test fails purely as a branch-diff scope check, and each one used is listed in the PR. The T-042 append-only and README-ends-with tests are never gated: T-043 must satisfy them.
- Any git-diff scope test the Tester adds for T-043 starts with an own-branch gate (skip unless the branch starts with `office/T-043`), following decision 351.
- No eval change is expected, because detection and plan_crop are untouched: f1 must equal BASE_F1, and eval-crop must equal BASE_CROP in every field except seconds_per_min.
- Tech Lead (dev_blocked): 2026-11-26 T-043 (R-004) Tech Lead (dev_blocked, round 1): Restart T-043 from main after T-044 merges. The block is real and is not a fault in T-043. Main 0b89c5a has no sportscut/reframe.py and no media.probe_size, because T-042 (T-018a) was dropped on protected_paths. The cause was the stale base_ref guardrail problem recorded for T-015, not anything T-042 changed. T-044 is now re-landing the reviewed T-017/T-042 code (reframe.plan_crop/crop_width/sample_times, media.probe_size, eval-crop) and supplies what T-043 needs, so the dependency is T-044 and no longer the dropped T-042. Rejected options: rebasing onto office/T-042 would carry an unreviewed diff tainted by agent-office/ changes into T-043 and trip protected_paths again. Re-scoping T-043 to rebuild T-017 code is ruled out by the spec and by decision 343, and it would push the diff past the size limit. Spec and AC1-AC15 stay as they are. One pre-approved addition: if T-044 lands a git-diff scope test with no branch gate (test_t042_*/test_t044_*/test_t017_acceptance), the Developer may add an E3 own-branch gate, using the same pattern as E1/E2 (decision 351).

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`
- `docs/superpowers/specs/2026-11-25-t-044-re-land-the-reviewed-t-017-design.md`
- `docs/superpowers/specs/2026-11-23-t-017-add-a-measurable-9-16-reframing-design.md`
- `docs/superpowers/specs/2026-11-24-t-042-land-the-t-017-9-16-design.md`
- `docs/superpowers/specs/2026-11-23-t-014-tag-saves-using-whistle-detection-and-design.md`
- `docs/superpowers/specs/2026-11-24-t-041-add-the-theo-d-i-c-design.md`

## Updated by T-021

Updated by T-021:
- `render_vertical(clip, crop_path, out, score_box=None, caption=None)` and `vertical_filter(crop_path, width, height, score_box=None, caption=None, fontfile=None)` take an optional scoreboard box (cropped from the source on every frame and overlaid scaled up in the top band) and an optional event caption (drawn with drawtext; render_vertical then resolves the font with `media.find_font()`). With neither, the calls and the filter string are byte-identical to T-043.
- vertical.py now also finds the score box (`find_score_box`, via `media.sample_top_band`, `scoreboard.find_box` and `media.probe_size`), still with no external tool calls of its own.
- The pipeline passes `score_box` and `caption` keyword arguments to render_vertical only when they are not None, so a clip with neither still gets exactly three positional arguments.
- A clip with no detected board is logged at WARNING on `sportscut.pipeline`, which has a NullHandler, so nothing reaches stderr unless logging is configured.
