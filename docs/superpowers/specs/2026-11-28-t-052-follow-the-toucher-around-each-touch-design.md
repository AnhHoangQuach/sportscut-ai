# T-052: Follow the toucher around each touch, vote its jersey number and keep only the chosen player, with --min-confidence

Request R-006. Plan: `docs/superpowers/plans/2026-11-28-t-052-follow-the-toucher-around-each-touch.md`.

## Product Owner request

Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó.

## Goal

Second slice of T-033 (R-006). Implement T-033 design spec §3, the §4 `player --min-confidence` part, the README section and the spec appendices, using jersey.get_reader() (digits only at this point). In player.py add NUMBER_SPAN, NUMBER_WIDTH, TRACK_GATE and MIN_CONFIDENCE, PlayerQuery.min_confidence with validation, _read_numbers (grid-aligned merged windows, seed/track with TRACK_GATE, max_reads subsampling), and detect_touches/find_touches number filtering. The T-031/T-032 code stays byte-identical. In cli.py add `player --min-confidence`. Make the nine pre-existing test edits listed in T-033 AC15, and no others. Add the insert-only README section `## Số áo cầu thủ (T-033)` immediately before `## Đội theo màu áo (T-032)`, containing the --min-confidence example, the góc rộng / data/eval_player/ limitation, a ```text block of the player and digit constants, and the `Trước T-033:`/`Sau T-033:` one-line eval-player JSON. The OCR/env/download text is added by the next slice. Append `## Updated by T-033` to the T-030, T-031 and T-032 design specs. Acceptance: T-033 AC8, AC9, AC10, AC11 (merge gate: f1 ≥ 0.85 overall and on number_hidden, id_accuracy ≥ 0.75, precision > 0.4205, team_accuracy ≥ 0.95, the touch_f1_any floors, seconds_per_min ≤ 6.0, eval f1 unchanged), AC12, AC13, AC15 and the README/spec parts of AC16/AC17 except the OCR strings. Tuning only within the T-033 ranges. Files: sportscut/player.py, sportscut/cli.py, README.md, tests/test_player_numbers.py, tests/test_t033b_acceptance.py, tests/test_player.py, tests/test_teams.py, tests/test_t032_acceptance.py, tests/test_t031_acceptance.py, tests/test_eval_player_fixtures.py, plus the T-030/T-031/T-032/T-033 design specs. Budget: <600 changed lines outside docs/superpowers.

## Acceptance criteria

- AC1 (Step 0) runs before any file change.
- It prints READY for `from sportscut.player import TeamColours, pick_team, _analyse, find_touches; from sportscut.jersey import get_reader, vote; from sportscut.media import sample_window`. Otherwise the Developer reports `BLOCKED: T-052 needs T-032 and T-051 on the base` and the diff is empty.
- It records the untouched base's one-line `python -m sportscut eval-player tests/fixtures/eval_player --json` and `python -m sportscut eval tests/fixtures/eval --json` in the Developer report.
- AC2 (T-033 AC10, query part) `PlayerQuery`:
- `PlayerQuery('red', 10) == PlayerQuery('red', 10, player.MIN_CONFIDENCE)` and both hash equal.
- `type(PlayerQuery('red', 10, 1).min_confidence) is float`.
- min_confidence values -0.1, 1.01, float('nan'), float('inf'), True and '0.5' each raise `ValueError('min confidence must be between 0 and 1')`; 0 and 1 are accepted.
- `player.NUMBER_SPAN == 2.0`, `player.NUMBER_WIDTH == 1280`, `0.5 <= player.TRACK_GATE <= 2.0`, `1.2 <= player.TRACK_MERGE <= 1.6` and `0.3 <= player.MIN_CONFIDENCE <= 0.8`.
- AC3 (T-033 AC8) `player._read_numbers(video, touches, reader)`. Setup: media.probe_size is patched to return (640, 360). media.sample_window is patched to grass (40,140,60) frames computed from the absolute time `start + k/fps`: a 16×32 (200,30,30) shirt with number 7 drawn by build._draw_number, moving 6 px per 0.2 s, with the number blanked for samples within ±1.0 s of the touch. The reader is a recording wrapper around jersey.DigitReader.
- One touch seeded with the shirt's source-px bbox returns `[(7, c)]` with `c >= player.MIN_CONFIDENCE`.
- A bbox farther than TRACK_GATE × its height from every blob, and a touch with `bbox=None`, each give `(None, 0.0)`.
- `[]` and `[Touch(..., bbox=None)]` call neither probe_size nor sample_window.
- If the shirt jumps 100 px at t+1.0 s, no crop taken after the jump is read: every recorded crop has a time ≤ t+0.8, recorded via the fake.
- A reader with `max_reads=2` is called exactly 2 times per tracked touch.
- Two touches 1.0 s apart cause exactly one sample_window call, whose start is ≥ 0 and a multiple of 0.2 within 1e-6. Touches 10 s apart cause two calls.
- Each touch's vote is equal whether it is read alone or together with its neighbour.
- A touch at t = 0.4 gives a first call with start 0.0.
- Clip end: with sample_window returning only the first half of the requested frames, the call still returns one vote per touch without raising.
- AC4 (crossing) Setup: red 7 moves +8 px per 0.2 s across a static red 9 on the same row, so their blobs merge for several samples and separate again inside the ±2 s span. A touch is seeded on red 7 before the crossing.
- `_read_numbers` returns `(7, c)` with `c >= MIN_CONFIDENCE`.
- No recorded read returns any number other than 7 or None.
- The Developer shows, in the report, that the same test fails with a plain nearest-centre tracker (no velocity, no TRACK_MERGE).
- AC5 (T-033 AC9) detect_touches and find_touches. Setup: `_analyse` is patched to return `([Touch(1.0,'red',None,.5,B), Touch(2.0,'blue',None,.5,B), Touch(3.0,'red',None,.5,B), Touch(4.0,None,None,.5,B)], C)` with C = red/blue TeamColours. `_read_numbers` is patched to record its touches and return `[VOTES[t.t] for t in touches]` with VOTES = {1.0: (10, .9), 2.0: (10, .9), 3.0: (7, .4)}.
- `find_touches(x, PlayerQuery('red', 10)) == [replace(red1, number=10)]`.
- `PlayerQuery('red', 7)` gives [] at the default threshold and `[replace(red3, number=7)]` with min_confidence 0.3.
- `PlayerQuery('#0000ff', 10)` gives `[replace(blue2, number=10)]`.
- `_analyse` is called exactly once per call.
- `_read_numbers` receives exactly the same-team touches in find_touches, and exactly the three team-labelled touches in detect_touches.
- `PlayerQuery('#ff00ff', 7)` raises 'equally close' before `_read_numbers` runs. colours None gives [] with no `_read_numbers` call.
- detect_touches returns 4 touches with numbers [10, 10, None, None], and t/team/confidence/bbox are unchanged.
- With `jersey.get_reader` patched to raise ValueError('x'), both functions raise it and `_analyse` is not called.
- AC6 (T-033 AC10, CLI)
- `python -m sportscut player CLIP --team blue --number 8 --min-confidence 1.5 --out D` exits 2. Its stderr contains `sportscut player: error: min confidence must be between 0 and 1`, and D is not created.
- With `sportscut.player.find_touches` patched to record its query, `--min-confidence 0.3` passes `PlayerQuery('blue', 8, 0.3)`, and no flag passes `PlayerQuery('blue', 8)`.
- `player --help` output contains `--min-confidence`.
- AC7 (T-033 AC11, merge gate) On the built synthetic set, `python -m sportscut eval-player tests/fixtures/eval_player --json` gives:
- f1 ≥ 0.85 and per_clip number_hidden f1 ≥ 0.85;
- id_accuracy ≥ 0.75 and precision > 0.4205;
- team_accuracy ≥ 0.95, touch_f1_any ≥ 0.9737, and per-clip touch_f1_any ≥ dribble 1.0, near_miss 1.0, number_hidden 1.0, short_passes 0.9091;
- 0 < seconds_per_min ≤ 6.0.
For every case and labelled query, every `find_touches(clip, q)` result is in `detect_touches(clip)` and has team == q.team and number == q.number.
`python -m sportscut player <built number_hidden clip> --team blue --number 8 --out D` exits 0. Every D/player.json touch has team 'blue' and number 8, and at least 3 of the labelled blue-8 times (4.0, 5.2, 9.0, 14.0) are within 0.5 s of a manifest touch.
`python -m sportscut eval tests/fixtures/eval --json` f1 equals the Step 0 value.
- AC8 (T-033 AC12, the gate can fail)
- With `jersey.get_reader` patched to a reader that always returns (None, 0.0), `evaluate_dir` on the built set gives f1 == 0.0 and id_accuracy == 0.0.
- With `player.NUMBER_SPAN` patched to 0.4, the number_hidden per-clip f1 is < 0.85.
- On number_hidden, the sets of find_touches results satisfy PlayerQuery('blue', 8, 0.0) ⊇ PlayerQuery('blue', 8) ⊇ PlayerQuery('blue', 8, 1.0).
- AC9 (T-033 AC13, sampling only around touches) During one `find_touches` call on each built clip:
- `media.sample_frames` is called exactly once.
- Every `media.sample_window(start, duration)` call has start ≥ 0 and start a multiple of 0.2 (within 1e-6).
- [start, start+duration] lies inside the union of [t-NUMBER_SPAN-0.2, t+NUMBER_SPAN+0.4] over the queried team's touches.
- On short_passes, `find_touches(clip, PlayerQuery('red', 7))` makes no sample_window call whose [start, start+duration] contains t = 12.0.
- AC10 (T-033 AC15, regression and scope; checked by commands and in review, not by pytest git-diff tests)
- `python -m pytest -q` reports 0 failed. No test is deleted, renamed, skipped or marked xfail.
- Pre-existing tests differ from main only inside the nine functions listed in spec §5, exactly as described there.
- The ast byte-identity command prints BYTE-IDENTICAL.
- The T-031 grep on sportscut/player.py prints nothing.
- `git diff main -- sportscut/jersey.py sportscut/media.py sportscut/eval_player.py sportscut/reel.py sportscut/api.py sportscut/reframe.py pyproject.toml tests/conftest.py tests/fixtures` is empty.
- `git ls-files '*.mp4' '*.pth'` is empty.
- Changed files are a subset of the task's file list plus orchestrator-written docs.
- AC11 (T-033 AC16 minus OCR) README.md:
- It is insert-only (0 deleted lines vs main).
- It has exactly one `## Số áo cầu thủ (T-033)` heading. The next `## ` heading is `## Đội theo màu áo (T-032)`, and the previous one is `## Theo dõi cầu thủ: xuất video tổng hợp (player)`.
- The section contains `--min-confidence`, `python -m sportscut player match.mp4 --team red --number 10 --min-confidence 0.3 --out reel`, `góc rộng` and `data/eval_player/`.
- It contains a ```text block whose NUMBER_SPAN, NUMBER_WIDTH, TRACK_GATE, TRACK_MERGE, MIN_CONFIDENCE values equal the sportscut.player constants, and whose VOTE_MIN_READS, INK_CONTRAST, INK_MIN_PIXELS, NUMBER_TOP, DIGIT_MIN_SCORE values equal the sportscut.jersey constants.
- It contains `Trước T-033:` and `Sau T-033:`, each followed by a one-line ```json eval-player report. 'Trước' has id_accuracy 0.0; 'Sau' has f1 ≥ 0.85 and id_accuracy ≥ 0.75.
- It does not contain `SPORTSCUT_NUMBER_READER`, `easyocr`, `[ocr]` or `download-models --ocr`.
- The T-027, T-031 and T-032 README tests still pass.
- AC12 (T-033 AC17 minus OCR) specs and size:
- The T-030, T-031 and T-032 design specs each end with a `## Updated by T-033` section (no `## ` after it) that names `--min-confidence`, the number vote and `find_touches` filtering by number. Their earlier text is unchanged, and the T-029/T-031 'Existing specs this task changes' lists keep their last bullet.
- The T-033 design spec still has `## Updated by T-051` as its last `## ` section and ends with a paragraph starting `Updated by T-052:` that mentions TRACK_MERGE and T-053.
- Changed lines outside docs/superpowers total < 600, new test files included.
- The Developer report quotes the before and after eval-player JSON (f1, precision, recall, id_accuracy, seconds_per_min), the eval f1 and the data/eval_player line.

## Out of scope

- OcrReader, ocr_dir, ocr_available, download_ocr_models, OCR_* constants, the SPORTSCUT_NUMBER_READER env handling, the [ocr] pyproject extra, `download-models --ocr`, the reader-forcing conftest fixture, the OCR timing test (T-033 AC4–AC6, AC14) and the OCR text in README (all T-053)
- Any change to sportscut/jersey.py (including tuning VOTE_MIN_READS, INK_CONTRAST or DIGIT_MIN_SCORE), sportscut/media.py, eval_player.py, reel.py, api.py, reframe.py, pyproject.toml, tests/conftest.py or tests/fixtures/
- Changing T-031 touch detection or T-032 team attribution (`_analyse` and all their constants/functions stay byte-identical)
- Exposing min_confidence in POST /players or on the web page; adding the vote confidence to player.json or Touch.to_dict (Touch keeps its five fields)
- Caching analysis or number reads between find_touches calls or eval queries
- Re-identifying players across camera cuts, handling close-ups or replays, or reading numbers outside ±NUMBER_SPAN of a touch
- Rewriting the stale T-030/T-032 README sentences (README is insert-only)
- Editing any pre-existing test other than the nine functions in spec §5, and adding pytest git-diff scope checks
- Labelling or committing real matches; data/eval_player/ stays git-ignored and PO-provided

## Decisions

- T-052 (R-006): T-052 is the second T-033 slice. It implements T-033 §3 (player tracking, vote and filtering) and §4's `player --min-confidence` using jersey.get_reader() (DigitReader only), the README section without OCR text, and the `## Updated by T-033` notes. T-053 adds OCR, SPORTSCUT_NUMBER_READER, `download-models --ocr` and the OCR README text.
- T-052 (R-006): This changes the T-033 design decision 'the toucher is followed by nearest-centre blob matching'. The walk predicts `p = c + v` (constant velocity, v starting at 0 in each direction) and takes the blob nearest p within TRACK_GATE × the previous box height. A blob wider or taller than TRACK_MERGE × the seed box counts as two merged players: the track coasts (c = p, v kept) and that crop is never read. New constant TRACK_MERGE = 1.3, tunable 1.2..1.6. Reason: the blocked T-033 attempt measured the plain tracker at best number_hidden f1 0.7143 over the whole tuning grid, because tracks jumped to crossing players.
- T-052 (R-006): New player constants NUMBER_SPAN=2.0 (fixed), NUMBER_WIDTH=1280 (fixed), TRACK_GATE=1.0 (0.5..2.0), TRACK_MERGE=1.3 (1.2..1.6) and MIN_CONFIDENCE=0.5 (0.3..0.8) sit in a block after TEAM_ITERS, before PlayerQuery. jersey.py constants are not tuned in this slice. If the gate cannot be met within these ranges, the Developer reports BLOCKED with the best JSON and the Tech Lead decides.
- T-052 (R-006): _read_numbers decodes crops with media.sample_window at min(width, 1280) px in grid-aligned ±NUMBER_SPAN windows, merging overlapping windows into one call. Tracking runs on frame[::s, ::s] at about 320 px with the unchanged player_blobs. Each touch uses only frames inside its own ±NUMBER_SPAN, so votes do not depend on grouping and every find_touches result is in detect_touches. Touches without a bbox vote (None, 0.0), and if no touch has a bbox no media call is made. A short sample_window return at the clip end is not an error.
- T-052 (R-006): detect_touches and find_touches call jersey.get_reader() through the module attribute before _analyse, so a reader error fails fast and tests can patch it. find_touches reads only same-team touches and keeps n == query.number with conf ≥ query.min_confidence. detect_touches reads every team-labelled touch and sets number only when conf ≥ MIN_CONFIDENCE. t, team, confidence and bbox never change.
- T-052 (R-006): T-033 AC9 as written is inconsistent: blue's (10, .9) vote would make detect_touches number blue 10, not None. T-052's AC5 therefore keys the fake votes by touch time {1.0: (10, .9), 2.0: (10, .9), 3.0: (7, .4)} and expects detect numbers [10, 10, None, None]. The rule is unchanged; only the example is corrected.
- T-052 (R-006): PlayerQuery.min_confidence defaults to MIN_CONFIDENCE and is stored as float. A bool, non-number, non-finite or out-of-[0, 1] value raises ValueError('min confidence must be between 0 and 1'). The CLI `player --min-confidence` (type=float) passes it, and bad values exit 2 through the existing ValueError path before --out is created. POST /players and eval labels use the default, so the API now filters by number without any API code change.
- T-052 (R-006): The nine pre-existing test edits are exactly those in T-033 AC15. The expected values are specified in the T-052 spec §5. Edits stay inside those functions (no module-level import changes), building expected touches with literals or the already-imported dataclasses.replace.
- T-052 (R-006): The README section `## Số áo cầu thủ (T-033)` is insert-only and goes directly before `## Đội theo màu áo (T-032)`. Its ```text block lists the player constants NUMBER_SPAN, NUMBER_WIDTH, TRACK_GATE, TRACK_MERGE, MIN_CONFIDENCE and the jersey constants VOTE_MIN_READS, INK_CONTRAST, INK_MIN_PIXELS, NUMBER_TOP, DIGIT_MIN_SCORE. It contains no OCR, env or download text until T-053.
- T-052 (R-006): The T-030, T-031 and T-032 design specs each get an appended `## Updated by T-033` section. The T-033 design spec gets only a trailing plain paragraph `Updated by T-052: ...` with no `## ` heading, because tests/test_t033a_acceptance.py::test_ac9_t033_spec_appendix requires `## Updated by T-051` to be its last section. T-053 must follow the same rule or edit that test through a Tech Lead decision.
- T-052 (R-006): The budget is < 600 changed lines outside docs/superpowers, new test files included: player.py ≈ 110, cli.py ≈ 5, README ≈ 50, the nine edits ≈ 25, Developer tests ≤ 190 and Tester tests ≤ 190. Size, changed-file scope, byte-identity of T-031/T-032 code and the README 0-deletion rule are checked by commands and in review, not by pytest git-diff tests (T-028/T-049/T-051 rule).

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md`
- `docs/superpowers/specs/2026-11-23-t-032-attribute-each-touch-to-a-team-design.md`
- `docs/superpowers/specs/2026-11-23-t-031-detect-ball-touches-by-any-player-design.md`
- `docs/superpowers/specs/2026-11-23-t-030-add-sportscut-player-cli-that-cuts-design.md`
- `docs/superpowers/specs/2026-11-28-t-051-add-media-sample-window-and-the-design.md`
