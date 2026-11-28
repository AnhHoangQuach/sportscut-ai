# T-057: Ignore a top-band 'scoreboard' that changes too often or never settles, and fall back to the roar rule

Request R-010. Request design: `docs/superpowers/specs/2026-11-28-r-010-t-i-test-upload-video-b-design.md`. Plan: `docs/superpowers/plans/2026-11-28-t-057-ignore-a-top-band-scoreboard-that.md`.

## Product Owner request

Tôi đã test upload video bóng đá của chúng tôi lên trong source, hiện tại phần cắt các đoạn highlight vẫn không chính xác nhất là phần bàn thắng. Kiểm tra và fix bug nếu có

## Goal

This is the main goal bug: a fence or roofline, or a running clock, is taken as the scoreboard, so camera pans become 0.9 goals and board-only goals with score 15 that crowd real highlights out of top-10. In sportscut/events/scoreboard.py, one shared check used by board_changes and board_reverts (so tag_goals, tag_incidents and tag_saves agree) treats the box as 'no scoreboard' (None or []) in two cases: more than max(4, duration_s/600) stable changes, or box flips (>= CHANGE_FRAC) in more than 25% of samples. Goals then come from the existing roar-only rule (confidence 0.4). This changes spec T-013 ('a found box is always trusted'). Gate: on eval_phone, no 'scoreboard change' goal and goal precision is higher than the task-1 baseline; the broadcast eval is identical (f1 >= 0.8421, every per_event value equal). The PR quotes both JSONs and the Tech Lead's re-run on the PO's video. Assumption: real matches have at most about 1 score change per 10 minutes; broadcasts with a clock lose the board and saves, and use the roar rule instead.

## Acceptance criteria

- AC1 `scoreboard.plausible_board(frames, box, changes)` exists. With frames = np.zeros((600, 30, 160), uint8) and changes [], box (0, 0, 80, 5) returns True and box (0, 0, 81, 5) returns False.
- AC2 Count rule, box (2, 2, 30, 14), zero frames: with 600 samples, 4 changes → True and 5 → False; with 3600 samples, 6 changes → True and 7 → False.
- AC3 Busy rule, box (2, 2, 30, 14), 101 samples, changes []: when the box pixels toggle between 0 and 255 in exactly 25 of the 100 transitions → True, in 26 → False. Fewer than 2 samples → True.
- AC4 With sample_top_band/find_box/score_changes monkeypatched so plausible_board is False (e.g. box (0, 7, 160, 1)), `board_changes` returns None, `board_reverts` returns [] and find_reverts is never called, and score_changes is called exactly once per call. When the board is plausible, both functions return exactly what they return on main (same objects passed to find_reverts).
- AC5 `score_changes` output is unchanged: every existing score_changes/find_reverts/find_box test passes without edits.
- AC6 On each built eval_phone case (pitch_a, pitch_b): board_changes(video) is None, board_reverts(video) == [], and `scoreboard.tag_goals(video, detect.find_highlights(video, top=None))` contains at least one segment with event 'goal', every goal has event_confidence 0.4, and no reason contains 'scoreboard change'.
- AC7 `python -m sportscut eval <built eval_phone> --json`: per_event.goal.precision is not null and > 0, and per_event.goal.recall > 0.0 (T-055 baseline: null and 0.0). f1 == 0.7692, precision == 0.625, recall == 1.0 and precision_at_5 == 0.8 (unchanged).
- AC8 The broadcast eval (tests/fixtures/eval) has f1 >= 0.8421 and every per_event value equal to the README 'Kết quả sau T-015' block (the existing tests/test_eval_phone.py::test_broadcast_eval_unchanged passes).
- AC9 README phone section contains a line exactly 'Kết quả sau T-057:' followed by a blank line and a ```json block equal to the live phone eval line, placed after the T-055 baseline block and before '## Theo dõi cầu thủ'. All earlier README blocks are unchanged. DECISIONS.md has exactly one line containing 'T-057 (R-010): phone eval after T-057' that ends with the same JSON.
- AC10 The T-013 and T-015 design specs contain an 'Updated by T-057:' line directly before their final 'Updated by T-055:' line, which stays last. The T-014 design spec ends with an 'Updated by T-057:' line.
- AC11 `python -m pytest -q` passes. The only edits to existing tests are the two listed in the spec (test_t015 `frames = object()` and the test_t055 README-block assertion).

## Out of scope

- Goal-shaped windows that include the build-up, and one clip per goal (goal_coverage stays 0.0; a later R-010 task)
- Limiting roar-only goals to voice-band sound (the wind gust stays a false goal; a later R-010 task)
- Kickoff-whistle confirmation of goals
- Changing find_box itself, or the vertical/9:16 scoreboard overlay in sportscut/vertical.py (it keeps using find_box as is)
- Reading a running clock or the digits (OCR/vision)
- Any change to sportscut/events/audio_cues.py, incidents.py, match_goals or the eval fixtures/builders
- Retuning thresholds on the PO's real video (no labels yet)

## Decisions

- T-057 (R-010): A top-band box is trusted only if `scoreboard.plausible_board(frames, box, changes)` is True. Width <= MAX_BOARD_W = 80 px (half of the 160-px band), stable changes <= max(4, len(frames)/600), and the share of samples with flips >= CHANGE_FRAC <= 0.25. All bounds are inclusive. This reverses T-013's 'a found box is always trusted'.
- T-057 (R-010): The check lives in one helper `_board(video)` used by both board_changes and board_reverts, so tag_goals, tag_incidents and tag_saves always agree. An implausible box behaves exactly like no box: board_changes → None (roar-only goals at 0.4, tag_saves unchanged) and board_reverts → [].
- T-057 (R-010): The width rule was added by the PM beyond the Tech Lead's two rules. On eval_phone, find_box picks the full-width sky line (fence posts vanish in the per-pixel median), which has 0 changes, so the count and busy rules alone cannot change the phone eval. Real boards and TV bugs sit in a corner (broadcast fixture board is 30 px wide).
- T-057 (R-010): Duration is len(frames) seconds, because sample_top_band is 1 fps. No ffprobe call is added to board_changes/board_reverts.
- T-057 (R-010): `_flips(frames, box)` is the single flip computation, shared by score_changes and plausible_board. score_changes output is byte-for-byte the same as before.
- T-057 (R-010): Call contract kept. sample_top_band, find_box, score_changes and find_reverts are each called at most once per board call, in that order, through module globals, and find_reverts receives the same frames/box/changes objects.
- T-057 (R-010): Two existing-test edits follow the intended change and do not weaken tests. test_t015 `frames = object()` becomes `np.zeros((20, 30, 160), np.uint8)` (the check needs a real array). The test_t055 README assertion now compares the live phone line with the 'Kết quả sau T-057:' block, while the T-055 baseline block stays pinned by its DECISIONS line.
- T-057 (R-010): Phone gate: goal precision changes from null to a number > 0, goal recall changes from 0.0 to > 0, there is no 'scoreboard change' reason, and f1/precision/recall/precision_at_5 stay equal to the T-055 baseline. Broadcast gate: f1 >= 0.8421 and every per_event value equal to the 'Kết quả sau T-015' block.
- T-057 (R-010): The phone result goes into README under 'Kết quả sau T-057:' and DECISIONS as 'phone eval after T-057'. Spec notes are inserted before the final 'Updated by T-055:' line of the T-013/T-015 specs (it must stay last) and appended to the T-014 spec.
- T-057 (R-010): Assumption: a real match has at most about 1 score change per 10 minutes and a board at most half the frame wide. Broadcasts with a running clock lose board goals, saves and reverts and use the roar rule. Accepted until labelled real matches exist in data/eval/.
- T-057 (R-010): The Tech Lead logs the re-run of `sportscut cut` on the PO's job input (/tmp/r010-t057 vs /tmp/r010-before: goal-clip count, reasons, wall time) in DECISIONS.md as review evidence. It is never a pytest test.
- T-057 (R-010): Budget is < 300 changed lines outside docs/superpowers, with Developer tests ≤ 120 and Tester tests ≤ 150. Scope is checked with git in review, with no new git-diff pytest (T-052 rule).

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md`
- `docs/superpowers/specs/2026-11-23-t-014-tag-saves-using-whistle-detection-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-015-tag-red-cards-and-controversial-incidents-design.md`
- `docs/superpowers/specs/2026-11-28-t-055-add-a-phone-pitch-side-goal-design.md`
- `docs/superpowers/specs/2026-11-28-r-010-t-i-test-upload-video-b-design.md`
