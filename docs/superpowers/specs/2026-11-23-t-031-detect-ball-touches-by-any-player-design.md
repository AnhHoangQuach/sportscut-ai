# T-031: Detect ball touches by any player from ball–player proximity and ball direction changes

Request R-006. Plan: `docs/superpowers/plans/2026-11-23-t-031-detect-ball-touches-by-any-player.md`.

## Product Owner request

Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó.

## Goal

Implement touch candidates in `sportscut/player.py`. Read frames at 5 fps, scaled to 320 px wide, through the ffmpeg rawvideo pipe. Reuse R-004's field mask and ball detector (`sportscut/reframe.py`, T-019/T-020), find player blobs as non-green connected regions inside the field mask, and mark a touch when the ball is within a size-relative distance of a player blob and its velocity changes direction or speed beyond a threshold, with non-maximum suppression at 0.4 s. `find_touches` still returns nothing for the query until tasks 4-5 land. This task raises `touch_f1_any` and exposes the candidates through `sportscut eval-player` debug output. Merge only if `touch_f1_any` ≥ 0.9 on the synthetic set, with the near-miss case not counted as a touch, and if 90 minutes of synthetic-rate frames still fit the 10-minute budget (put the measured seconds_per_min in the PR). Assumptions: this starts after R-004's T-020 is merged; if it is missing, report BLOCKED and do not duplicate the ball detector. Touches are only seen in wide shots: close-ups with no field mask produce no candidates.

## Acceptance criteria

- AC1: Step 0's script is run before any file change. On a base containing T-044, T-045 and T-020 with the listed reframe/media names it prints READY. Otherwise the Developer reports `BLOCKED: T-031 needs R-004 <capability>; do not duplicate it` with reframe.py's public and private names, and the diff is empty.
- AC2: `player.player_blobs(frame)` returns the 1-px-grown, frame-clipped (x, y, w, h) analysis-px bboxes of 8-connected components of `reframe.player_mask(frame)` with ≥ BLOB_MIN_AREA pixels, sorted by (y, x). It returns `[]` for a frame with no field mask. A red 8×16 rect at (100,60) on a 320×180 (40,140,60) field gives exactly [(100,60,8,16)], and a lone white radius-2 disc gives [].
- AC3: `player.find_kicks(hits, width)` returns [(i, strength)] with 0 < strength ≤ 1, only for samples where hits[i-KICK_SPAN], hits[i] and hits[i+KICK_SPAN] are all present. Constant velocity gives none. A 90° turn at index 7 gives index 7 as its strongest kick. Starting from rest gives a kick with strength 1.0. A ball coming to rest gives no kick. A 3° heading change with speed ratio 1.05 gives none.
- AC4: `player.suppress_touches` keeps touches greedily by confidence (ties: earlier t), drops any touch with |Δt| ≤ 0.4 s (+1e-9) from a kept one, and returns the result sorted by t. For example, {1.0:0.9, 1.4:0.5} gives [1.0], and {1.0, 1.6} keeps both.
- AC5: `player.detect_touches(video)` returns Touch objects sorted by t, with team None, number None, 0 < confidence ≤ 1, t a multiple of 0.2 s (rounded to 4 decimals), and bbox as 4 ints in source-video pixels. It reads frames only through `media.sample_frames(video, reframe.SAMPLE_HZ, aw, ah)` with aw = min(320, width), and finds the ball only through `reframe.ball_candidates` + `reframe.track_ball`. `grep -nE "subprocess|ffmpeg|green_mask|cumsum|def (sample_frames|field_mask|ball_candidates|track_ball)" sportscut/player.py` prints nothing.
- AC6: Close-ups with no field produce no candidates: `detect_touches` on the conftest `synthetic_video` (black/white, no grass) returns []. `detect_touches('missing-x.mp4')` raises `sportscut.media.MediaError`.
- AC7: Running `python tests/fixtures/eval_player/build.py && python -m sportscut eval-player tests/fixtures/eval_player --json` prints touch_f1_any ≥ 0.9, f1 == precision == recall == 0.0, and seconds_per_min ≤ 6.0 (so 90 minutes of 5 Hz frames take ≤ 540 s of the 600 s budget).
- AC8: The near-miss case is not counted as a touch. In the near_miss clip, every detect_touches result is within 0.5 s of a labelled touch (zero any-touch false positives). No result is within 0.5 s of any near-miss moment, where a near-miss moment is a 0.2 s grid time ≥ 1.0 s from every touch at which a listed player with no touch labels has a box-distance of 6–14 px from build.ball_pos.
- AC9: `sportscut eval-player DIR --debug` adds a final `candidates` key to every per_clip entry, equal to `[t.to_dict() for t in player.detect_touches(clip)]`. With `--json` the output is still one line. Without `--debug`, no per_clip entry has `candidates` and the top-level key set is unchanged.
- AC10: For every synthetic case and every labelled query, `player.find_touches(clip, query) == []`. find_touches and the Touch/PlayerQuery classes are unchanged.
- AC11: `python -m pytest -q` reports 0 failed. The only edits to pre-existing tests are the single `detect_touches('x.mp4')` line in tests/test_player.py (now expecting MediaError) and the two baseline asserts in tests/test_eval_player_fixtures.py::test_eval_player_cli_baseline_json (now f1 == 0.0, touch_f1_any ≥ 0.9, team_accuracy == id_accuracy == 0.0). `python -m sportscut eval tests/fixtures/eval --json` f1 equals the value measured on main in Step 0.
- AC12: `git diff main -- sportscut/reframe.py sportscut/media.py tests/conftest.py tests/fixtures/eval_player pyproject.toml` is empty. No .mp4 is tracked.
- AC13: README.md has a new section `## Phát hiện chạm bóng (T-031)` placed immediately before `## Highlight theo sự kiện: đo độ chính xác (eval)`. The section contains the --debug command, a ```text block with the final constant values, and `Kết quả đo trong T-031:` followed by a ```json block holding a one-line report with touch_f1_any ≥ 0.9 from a real run. README has 0 deleted lines vs main. The T-029 design spec has the appended T-031 bullet.
- AC14: Changed lines outside docs/superpowers total < 600, including the Tester file. The PR body quotes the measured eval-player JSON, seconds_per_min and the 90-minute projection.

## Out of scope

- Team colour clustering and jersey-number reading, i.e. filling Touch.team/number and making find_touches return results (T-032, T-033)
- Any change to sportscut/reframe.py, sportscut/media.py, the ball detector, tracker, field mask or frame reader, including a streaming/low-memory frame reader for full matches (R-004/media follow-up)
- Caching detect_touches between find_touches calls or between eval queries
- Treating a ball trapped dead at a player's feet as a touch
- A YOLO/vision ball or player detector extra
- Changing the eval-player metrics, matching rule, fixtures or labels
- Touch detection in close-ups or replays without a field mask
- Changes to the player reel, API or web page

## Decisions

- T-031 (R-006): Step 0 READY means reframe exposes SAMPLE_HZ, ANALYSIS_WIDTH, BALL_GATE, BALL_LOST, field_mask, player_mask, ball_candidates and track_ball, media exposes sample_frames, probe_size, probe_duration and MediaError, and git log contains T-044 (T-017), T-045 (T-019) and T-020. ball_candidates (per frame) + track_ball (per sample over candidate lists) count as the stepped ball capability.
- T-031 (R-006): player.py reuses R-004 only: frames come from media.sample_frames(video, reframe.SAMPLE_HZ, aw, ah) with aw = min(reframe.ANALYSIS_WIDTH, width) and ah = max(2, 2*round(height*aw/width/2)) (plan_crop's size rule); the ball comes from reframe.ball_candidates and reframe.track_ball(cands, BALL_GATE*aw, BALL_LOST); blobs come from reframe.player_mask. No reader, mask or detector code is written in player.py, and reframe.py/media.py are not modified.
- T-031 (R-006): Only real detections count. A tracker output is a hit only if it equals a candidate of that sample, so coasted (held) positions are None.
- T-031 (R-006): A kick at sample i uses v_in = (hit[i]-hit[i-S])/dt and v_out = (hit[i+S]-hit[i])/dt with S = KICK_SPAN, dt = S/5. It needs s_out ≥ MIN_SPEED*aw, and turn ≥ TURN_DEG (turn counts only when s_in ≥ vmin) or jump = |s_out-s_in|/max(s_in, s_out) ≥ SPEED_JUMP. strength = min(1, max(turn/180, jump)) becomes the Touch confidence.
- T-031 (R-006): A ball that comes to rest (s_out < vmin) is never a touch, so the synthetic ball_end stop next to the last toucher is not a false positive.
- T-031 (R-006): Player blobs are 8-connected components of reframe.player_mask with ≥ BLOB_MIN_AREA eroded pixels, bbox grown by 1 px and clipped to the frame. They are computed only at kick samples, for speed. A kick becomes a touch when the ball centre's distance to the nearest point of the closest blob bbox is ≤ REACH × that bbox's height. Touch.bbox is that blob in source pixels.
- T-031 (R-006): NMS is greedy by confidence (ties earlier t) and suppresses |Δt| ≤ 0.4 s (+1e-9). Touch t is sample_index/5 rounded to 4 decimals.
- T-031 (R-006): Tuning is allowed only within KICK_SPAN [1,3], TURN_DEG [10,60], SPEED_JUMP [0.2,0.8], MIN_SPEED [0.005,0.05] (fraction of analysis width per second), REACH [0.25,1.0] (× blob height), BLOB_MIN_AREA [10,40]. TOUCH_NMS = 0.4 is fixed. If no setting meets the gates, the Developer reports BLOCKED with the best JSON and the Tech Lead decides.
- T-031 (R-006): Merge gate on the synthetic eval-player set: touch_f1_any ≥ 0.9; f1 == precision == recall == 0.0 (find_touches unchanged and still empty); near_miss has zero any-touch false positives and no touch within 0.5 s of a near-miss moment; seconds_per_min ≤ 6.0 (90-min projection ≤ 540 s, reported in the PR); `sportscut eval` f1 unchanged.
- T-031 (R-006): Candidates are exposed by `sportscut eval-player --debug`, which adds per_clip[].candidates = Touch.to_dict() of the already computed detect_touches result. Output without --debug is unchanged; evaluate_dir(path, debug=False).
- T-031 (R-006): Allowed edits to pre-existing tests: the detect_touches('x.mp4') line in tests/test_player.py (now raises MediaError) and the two baseline asserts of tests/test_eval_player_fixtures.py::test_eval_player_cli_baseline_json. They change because the stub behaviour they pinned is intentionally replaced.
- T-031 (R-006): The README gets an insert-only section `## Phát hiện chạm bóng (T-031)` immediately before `## Highlight theo sự kiện: đo độ chính xác (eval)`. The T-029 eval-player section and its baseline stay byte-identical as history.
- T-031 (R-006): Size budget < 600 changed lines outside docs/superpowers including the Tester file (T-020/T-045 precedent for one gated algorithmic slice). No new dependency.
- Tech Lead (dev_blocked): 2026-11-23 T-031 (R-006): Tech Lead (dev_blocked): the Developer was right to stop. The root cause is task ordering, not code. T-031's spec and decision line 129 make R-004's T-017→T-019→T-020 a hard dependency, but the office started T-031 while all three were still todo. On base 3e30f75 there is no sportscut/reframe.py, media.py has no probe_video_size, and there is no T-020 commit, so Step 0 printed BLOCKED as AC1 requires. Decision: restart T-031 from the latest main with after [T-017, T-019, T-020]. The spec, ACs and files stay as they are. We will not copy the ball detector or field mask into player.py, because decision line 130 forbids that and it would duplicate R-004.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-029-build-the-player-touch-eval-synthetic-design.md`
- `docs/superpowers/specs/2026-11-23-t-020-detect-the-ball-and-let-it-design.md`
- `docs/superpowers/specs/2026-11-25-t-045-follow-the-players-with-a-smoothed-design.md`
- `docs/superpowers/specs/2026-11-23-t-030-add-sportscut-player-cli-that-cuts-design.md`
- T-032 (2026-11-27): detect_touches fills Touch.team from two shirt-colour clusters; find_touches returns every touch by the queried team (number ignored until T-033), superseding T-031 AC10 (find_touches == []).

## Updated by T-033

- Landed in T-052 (2026-11-28): find_touches now reads jersey numbers (the number vote) around each touch of the
  mapped team and keeps only touches whose voted number equals the query with confidence >= min_confidence.
- detect_touches fills Touch.number when the vote confidence >= MIN_CONFIDENCE; new `sportscut player --min-confidence`.
- This supersedes the T-032 'number ignored' rule and T-032 AC8 (detect_touches == _analyse(video)[0]).
- The OCR backend follows in T-053.
