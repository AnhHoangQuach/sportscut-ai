# T-058: Cut each goal as one clip from the build-up to the celebration

Request R-010. Request design: `docs/superpowers/specs/2026-11-28-r-010-t-i-test-upload-video-b-design.md`. Plan: `docs/superpowers/plans/2026-11-28-t-058-cut-each-goal-as-one-clip.md`.

## Product Owner request

Tôi đã test upload video bóng đá của chúng tôi lên trong source, hiện tại phần cắt các đoạn highlight vẫn không chính xác nhất là phần bàn thắng. Kiểm tra và fix bug nếu có

## Goal

Goal clips today keep the generic 12 s window (8 s before the loudness peak, 4 s after), which often misses the build-up and shot, and a long cheer can give two overlapping goal clips. Add a pure step at the end of scoreboard.tag_goals, leaving match_goals unchanged, so the T-013 unit tests keep passing. For every goal with a sustained roar, the window is [roar onset - 12 s, roar onset + 10 s], clamped to [min_len, max_len] and keeping the 12:10 before/after ratio, and inside the media bounds. Overlapping goal segments merge into one, which keeps the highest score and confidence. A non-goal candidate that overlaps a goal is dropped. Board-only goals keep their window. This changes spec T-013 ('start/end unchanged, anchored on the audio peak'). Gate: eval_phone goal_coverage >= 0.9 and no two goal segments overlap; on the broadcast set f1/precision/recall stay the same or rise, per_event goal stays 1.0, and goal_coverage does not drop. The PR quotes both JSONs.

## Acceptance criteria

- AC1 `scoreboard.shape_goals(segments, residual, duration, min_len=10, max_len=30)` exists. With residual = np.zeros(200), residual[40:48] = 10.0 and goal G = Segment(36, 48, 5.0, 'r', 'goal', 0.4), `shape_goals([G], residual, 200)` returns [Segment(28.0, 50.0, 5.0, 'r', 'goal', 0.4)]. The same holds for event_confidence 0.9.
- AC2 Clamp and ratio, same residual: max_len=11 gives (34.0, 45.0). min_len=30, max_len=30 gives start == approx(40 - 30*12/22) and end == approx(40 + 30*10/22), length 30. With defaults every reshaped goal is exactly 22.0 s long.
- AC3 Media bounds: onset 5 (residual[5:13] = 10, goal Segment(1, 13, 5, 'r', 'goal', 0.4), duration 200) gives (0.0, 22.0). Onset 52 (residual = np.zeros(60), residual[52:58] = 10, goal Segment(48, 58, 5, 'r', 'goal', 0.4), duration 60) gives (38.0, 60.0).
- AC4 Not reshaped: a board-only goal (event_confidence 0.6) keeps its start/end even when a >= 6 s roar lies under it. A goal whose run is < 6 s (e.g. residual all zeros, or a 5-second run) keeps its start/end. Non-goal segments are never reshaped.
- AC5 Merge: with residual[40:48] = 10 and residual[55:62] = 10, goals A = Segment(36, 48, 5, 'a', 'goal', 0.4) and B = Segment(51, 63, 7, 'b', 'goal', 0.9) give exactly one goal, Segment(28.0, 65.0, 7, 'b', 'goal', 0.9) (union span, highest score and its reason, highest confidence). A board-only goal overlapping a reshaped goal is merged the same way. Goals that only touch (end == start) are not merged.
- AC6 Drop: after reshaping G to [28, 50], an 'other' Segment(45, 57, 9, 'o') and a 'save' Segment(20, 30, 3, 's', 'save', 0.6) that overlap it are removed. An 'other' Segment(50, 62, 4, 'x') that only touches it and an 'other' Segment(70, 82, 4, 'y') are kept. Output is sorted by (start, end), and the input list and segments are unchanged.
- AC7 `roar` returns the same values as before (all existing test_scoreboard.py and test_t013_acceptance.py tests pass without edits), and `match_goals` is unchanged. `tag_goals` returns `shape_goals(match_goals(...), residual, duration, min_len, max_len)`, called once through the module global with the same residual, duration, min_len and max_len (spy test). On the burst video it still returns the candidates unchanged.
- AC8 Broadcast set (tests/fixtures/eval built): for each case, `tag_goals(video, detect.find_highlights(video, top=None))` returns exactly one goal per goal label. Each goal has event_confidence 0.9, length 22.0, and start <= label.start and label.end <= end. No two goal segments overlap. `evaluate_dir` gives f1/precision/recall/event_accuracy/per_event/precision_at_5 equal to the README 'Kết quả sau T-015' block (tests/test_eval_phone.py::test_broadcast_eval_unchanged passes), per_event.goal precision, recall and f1 are 1.0, and goal_coverage == 1.0.
- AC9 Phone set (tests/fixtures/eval_phone built, base includes T-057): `python -m sportscut eval <set> --json` has goal_coverage >= 0.9, and f1 == 0.7692, precision == 0.625, recall == 1.0, precision_at_5 == 0.8. For each case, no two segments with event 'goal' in `tag_goals(video, detect.find_highlights(video, top=None))` overlap.
- AC10 README has a line exactly 'Kết quả sau T-058:' followed by a blank line and a ```json block equal to the live phone eval line. It sits in the '### Kết quả đo video quay điện thoại (R-010)' section, after the earlier result blocks and before '## Theo dõi cầu thủ: xuất video tổng hợp (player)'; all earlier blocks are unchanged. DECISIONS.md has exactly one line containing 'T-058 (R-010): phone eval after T-058' that ends with the same JSON, and exactly one line containing 'T-058 (R-010): broadcast eval after T-058' that ends with the live broadcast JSON.
- AC11 The T-013 design spec has a line starting 'Updated by T-058:' directly before its final 'Updated by T-055:' line, which stays last.
- AC12 `python -m pytest -q` passes. The only edits to existing tests are the test_t055 README-block assertion (now reading 'Kết quả sau T-058:') and, only if test_t057_acceptance.py pins the live phone line to the T-057 block, that assertion becoming a T-057-block vs its DECISIONS-line check.

## Out of scope

- Changing match_goals, find_box, score_changes, plausible_board or any T-057 board logic
- Restricting roar-only goals to voice-band sound / removing the wind-gust false goal (T-059)
- Kickoff-whistle confirmation of goals
- Changing the generic window of non-goal candidates in detect.find_highlights (PRE_SEC/POST_SEC) or windows for save/red_card/controversy
- Re-ranking or capping merged goal length at max_len, or splitting a merged goal again
- Changes to pipeline.run, evaluate.py, ranking.py, export, the web/API layer or the vertical renderer
- Editing the eval fixtures, builders or committed labels.json
- Retuning GOAL_BEFORE/GOAL_AFTER or ROAR_DB on the PO's real video (no labels yet)
- Adding a new reason suffix to reshaped goals

## Decisions

- T-058 (R-010): T-058 starts from a base that contains T-057 (plausible_board). Without it the phone set has no goal at all and the goal_coverage gate cannot be met. T-057, T-058 and T-059 all change sportscut/events/scoreboard.py and run one after the other; whichever of T-058/T-059 lands second rebases and refreshes its README/DECISIONS phone block.
- T-058 (R-010): The goal window is added by a new pure step `scoreboard.shape_goals(segments, residual, duration, min_len=10, max_len=30)` called at the end of tag_goals as `shape_goals(match_goals(...), residual, duration, min_len, max_len)`. match_goals is unchanged, so the T-013 'start/end unchanged' match_goals tests stay valid. What changes is tag_goals' output geometry. This reverses T-013's 'goal segment anchored on the audio peak'.
- T-058 (R-010): Roar onset = float(left), the start of the first second of the maximal >= ROAR_DB run containing the goal segment's peak second. That is the same run match_goals used to qualify the goal, computed by a private `_roar_bounds(residual, start, end) -> (peak_time, left, right)` that `roar` now wraps, with identical outputs.
- T-058 (R-010): GOAL_BEFORE = 12.0 and GOAL_AFTER = 10.0. length = clamp(22, min_len, max_len), before = length*12/22, placed with detect.place_window(onset, length, duration, before), which shifts the window inside [0, duration] and keeps its length.
- T-058 (R-010): A goal is reshaped only if event == 'goal', event_confidence != CONF_BOARD_ONLY (0.6), and its roar run >= ROAR_SEC. Board-only goals and goals without a sustained run keep their window. Reshaping changes only start/end.
- T-058 (R-010): Overlap is strict (a.start < b.end and b.start < a.end), as in match_goals, so touching segments neither merge nor drop. Overlapping goals (including board-only ones) merge into the union span. Score and reason come from the highest-score member (None counts as -inf; a tie goes to the earliest (start, end)) and event_confidence is the members' max. The merged span may exceed max_len.
- T-058 (R-010): Any non-goal segment that overlaps a final goal segment is dropped from tag_goals' output. In the pipeline order every such segment is still 'other'.
- T-058 (R-010): Gates: broadcast f1/precision/recall/event_accuracy/per_event/precision_at_5 equal the 'Kết quả sau T-015' block, per_event goal is 1.0, and goal_coverage == 1.0 (from 0.0). Phone goal_coverage >= 0.9 with f1/precision/recall/precision_at_5 unchanged, and no two goal segments overlap on either set. If a gate fails, the Developer stops and reports to the Tech Lead with both JSONs instead of tuning thresholds or fixtures.
- T-058 (R-010): The phone result goes into README as 'Kết quả sau T-058:' after the earlier phone blocks, and into DECISIONS as 'phone eval after T-058'. The broadcast JSON goes into DECISIONS as 'broadcast eval after T-058'. The test pinning the live phone line moves to the T-058 block, and an older block pinned to the live line becomes a block-vs-DECISIONS check (the same rule T-057 applied to T-055). These edits follow the intended change and do not weaken tests.
- T-058 (R-010): The T-013 design spec gets an 'Updated by T-058:' line inserted directly before its final 'Updated by T-055:' line, which must stay last.
- T-058 (R-010): The Tech Lead's re-run of `sportscut cut` on the PO's job input (/tmp/r010-t058 vs /tmp/r010-t057: goal-clip count, start/end/length, any overlap, wall time) is review evidence logged in DECISIONS.md, never a pytest test.
- T-058 (R-010): Budget is < 300 changed lines outside docs/superpowers, Developer tests ≤ 130 lines and Tester tests ≤ 150. Scope is checked with git in review, with no git-diff pytest (T-052 rule).

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md`
- `docs/superpowers/specs/2026-11-28-t-055-add-a-phone-pitch-side-goal-design.md`
- `docs/superpowers/specs/2026-11-28-t-057-ignore-a-top-band-scoreboard-that-design.md`
- `docs/superpowers/specs/2026-11-23-t-014-tag-saves-using-whistle-detection-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-015-tag-red-cards-and-controversial-incidents-design.md`
- `docs/superpowers/specs/2026-11-28-t-056-decode-the-audio-and-the-top-design.md`
