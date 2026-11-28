# Plan T-057: Ignore a top-band 'scoreboard' that changes too often or never settles, and fall back to the roar rule

Design: `docs/superpowers/specs/2026-11-28-t-057-ignore-a-top-band-scoreboard-that-design.md`.

## Implementation plan

# T-057: Ignore an implausible top-band 'scoreboard' and fall back to the roar rule

## Context (read from main @ fedde1c)

- `sportscut/events/scoreboard.py`: `find_box(frames)` returns the largest static high-edge component in the 160x30 top band (one grey frame per second from `media.sample_top_band`). `board_changes(video)` returns `None` when there is no box, otherwise `score_changes(frames, box)`. `board_reverts(video)` returns `[]` when there is no box, otherwise `find_reverts(frames, box, changes)`. Today a found box is always trusted (T-013).
- Three classifiers read the board, so they must agree. `tag_goals` uses `match_goals(..., changes)`: `None` → roar-only goals (`event_confidence` 0.4, reason `'; sustained roar <run>s'`); a list → roar+change goals at 0.9 and board-only goals at 0.6 (`reason 'scoreboard change at <c>s'`, score 3.0). `tag_incidents` calls `board_reverts`. `tag_saves` (in `audio_cues.py`, which this task does **not** edit) returns the segments unchanged when `board_changes` is `None`.
- Root cause (R-010 design): on phone or pitch-side footage, a fence, roofline or horizon line is taken as the board. Every camera pan then becomes a 'score change', and the fake goals crowd real highlights out of top-10. A running clock (a TV filmed with a phone) never settles. Because a box is found, the roar fallback is never used.
- **PM finding that widens the Tech Lead brief by one rule.** On `tests/fixtures/eval_phone`, the fence posts are present in each pixel for at most about 175 of 600 s, so the per-pixel median reference in `find_box` drops them. The only edge ≥ 40 that remains is the full-width sky/dark line at row 7 (luma ≈ 176 vs ≈ 42). So `find_box` returns a 160-px-wide, roughly 1-px-high box that never changes, and `board_changes` returns `[]`. That fits the T-055 baseline: no segment has event `goal` (goal precision null, recall 0.0), and the roar fallback is off. On that fixture the two briefed rules (too many changes, too many flips) would therefore never fire, and the phone gate could not move. Real scoreboards and TV bugs sit in a corner. The broadcast board is 30 px wide, and no real board spans more than half the frame. So the shared check also rejects a box wider than half the band (> 80 px). The two briefed rules stay as specified.

## Design

All code changes are in `sportscut/events/scoreboard.py`.

```python
MAX_BOARD_W = 80          # half of media.BAND_W (160): real boards sit in a corner
MAX_CHANGES = 4           # a board may change at most max(4, seconds/600) times
SECONDS_PER_CHANGE = 600  # assumption: <= ~1 real score change per 10 minutes
BUSY_FRAC = 0.25          # a board flipping in > 25% of samples is a clock/pan, not a score

def _flips(frames: np.ndarray, box: Box) -> np.ndarray:
    """Per-sample share of box pixels that changed by >= FLIP_DIFF; flips[0] == 0."""
    # exactly the computation score_changes does today; score_changes now calls it

def plausible_board(frames: np.ndarray, box: Box, changes: list[float]) -> bool:
    """False when the box is too wide, changes too often, or never settles."""
    if box[2] > MAX_BOARD_W:
        return False
    if len(changes) > max(MAX_CHANGES, len(frames) / SECONDS_PER_CHANGE):
        return False
    flips = _flips(frames, box)
    busy = float(np.mean(flips[1:] >= CHANGE_FRAC)) if len(flips) > 1 else 0.0
    return busy <= BUSY_FRAC

def _board(video) -> tuple[np.ndarray, Box, list[float]] | None:
    frames = sample_top_band(video)
    box = find_box(frames)
    if box is None:
        return None
    changes = score_changes(frames, box)
    if not plausible_board(frames, box, changes):
        return None
    return frames, box, changes

def board_changes(video) -> list[float] | None:
    board = _board(video)
    return None if board is None else board[2]

def board_reverts(video) -> list[tuple[float, float]]:
    board = _board(video)
    return [] if board is None else find_reverts(*board)
```

Rules that existing tests rely on, which the code must keep:
- `sample_top_band`, `find_box`, `score_changes` and `find_reverts` are each called at most once per `board_changes`/`board_reverts` call, in that order, through module globals so monkeypatching still works. `find_reverts` gets the very same `frames`, `box` and `changes` objects (identity checks in test_incidents/test_t015).
- `len(frames)` is the duration in seconds (the band is sampled at 1 fps). Thresholds are strict: exactly `max(4, n/600)` changes is allowed, and exactly 25% busy samples is allowed.
- `find_box`, `score_changes` (output unchanged; it only reuses `_flips`), `find_reverts`, `match_goals`, `tag_goals` and `sportscut/vertical.py` keep their behaviour. The roar rule is the existing `changes is None` branch of `match_goals`, and it is not changed.

## Edits to existing tests (intended change, not a weakening; recorded in decisions)
1. `tests/test_t015_acceptance.py::test_ac2_board_reverts_composes_helpers_in_order`: change `frames = object()` to `frames = np.zeros((20, 30, 160), np.uint8)`. The new check needs a real array. All order and identity asserts stay.
2. `tests/test_t055_acceptance.py::test_ac9_ac10_ac11_phone_eval_matches_readme_and_decisions`: the line `assert (block := section.split("Baseline đo trong T-055:\n\n```json\n", 1)[1].split("\n```", 1)[0]) == line` becomes two lines:
   `block = section.split("Baseline đo trong T-055:\n\n```json\n", 1)[1].split("\n```", 1)[0]`
   `assert section.split("Kết quả sau T-057:\n\n```json\n", 1)[1].split("\n```", 1)[0] == line`
   The historic baseline is still pinned by the DECISIONS `endswith(block)` assert. The live phone output is now pinned to the T-057 block.
No other existing test may be edited. If any other test fails, stop and report it to the Tech Lead.

## Docs
- README.md, in the section `### Kết quả đo video quay điện thoại (R-010)`: after the paragraph starting `Precision và độ phủ bàn thắng thấp là dự kiến` and before `## Theo dõi cầu thủ`, add one Vietnamese paragraph about the rule. It says a top-band box is ignored when it is wider than half the frame, changes more than max(4, thời lượng/600 s) times, or flips in more than 25% of samples; goals then use the roar rule (confidence 0,4), saves and score reverts are turned off for that video, and a broadcast with a running clock loses the board and saves for the same reason. Then add a line that is exactly `Kết quả sau T-057:`, a blank line, and a ```json block holding the exact one-line output of the phone eval command. Do not edit any existing README text or block.
- `docs/superpowers/DECISIONS.md` (append-only): append `- 2026-11-28 T-057 (R-010): phone eval after T-057 (tests/fixtures/eval_phone): <same JSON line>`. The line must not contain the text `phone eval baseline`.
- Spec notes, one line each: `Updated by T-057: a found box is trusted only if scoreboard.plausible_board passes (width <= 80 px, at most max(4, seconds/600) stable changes, flips in <= 25% of samples); otherwise board_changes is None (roar-only goals at 0.4, no saves) and board_reverts is []. This replaces 'a found box is always trusted'.` In `2026-11-23-t-013-...-design.md` and `2026-11-23-t-015-...-design.md`, insert it **directly before** the final `Updated by T-055:` line, which must stay last (test_t055). In `2026-11-23-t-014-...-design.md`, append it as the last line.

## Steps (TDD)
0. Diagnose, no code. Build the phone set into a temp dir and print `find_box(sample_top_band(v))` and `len(score_changes(...))` for pitch_a and pitch_b. Expected: a box about 160 px wide with 0 changes. Quote it in the PR. If the box is `None`, stop and report to the Tech Lead.
1. Write the `plausible_board` tests in tests/test_scoreboard.py (width, count, busy boundaries). Watch them fail with ImportError/AttributeError. Add the constants, `_flips` (make `score_changes` use it) and `plausible_board`. Run the tests and see them pass, and also see the existing `score_changes` tests pass.
2. Write the `board_changes`/`board_reverts` rejection tests with monkeypatched `sample_top_band`/`find_box`/`score_changes`. Watch them fail. Add `_board` and rewire both functions.
3. Make the two existing-test edits above. Run `python -m pytest -q`.
4. Run both eval commands. Add the README block, the DECISIONS line and the three spec notes. Run `python -m pytest -q` again.

## Verify
```bash
python -m pytest -q
python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json
python tests/fixtures/eval_phone/build.py && python -m sportscut eval tests/fixtures/eval_phone --json
```
- Broadcast: f1 >= 0.8421, and every per_event value is equal to the README 'Kết quả sau T-015' block (byte-identical JSON to main is expected).
- Phone: compared with the T-055 baseline, `per_event.goal.precision` changes from null to a number > 0 and `per_event.goal.recall` changes from 0.0 to > 0. Expected about 0.6667 and 1.0: each case gets 2 cheer goals plus 1 wind-gust false positive, all at 0.4. f1 0.7692, precision 0.625, recall 1.0 and precision_at_5 0.8 stay unchanged, because only event labels change and not segment times or scores. goal_coverage stays 0.0; goal windows are a later R-010 task.
- The PR quotes both JSON lines and the step 0 diagnosis. The Tech Lead runs `sportscut cut` on the PO's local job input (`sportscut-data/jobs/370c35dc-.../input`) into /tmp/r010-t057 and logs in DECISIONS.md the goal-clip count, their reasons and the wall time, compared with /tmp/r010-before. This is review evidence, not a pytest test, and no media is committed.

## Budget
Under 300 changed lines outside docs/superpowers. Developer tests ≤ 120 lines, Tester tests ≤ 150 lines. Scope and size are checked with git commands in review, with no new git-diff pytest (T-052 rule). Do not touch `sportscut/events/audio_cues.py`, `tests/conftest.py`, `tests/fixtures/eval/build.py`, `tests/fixtures/eval_phone/build.py`, models/ranking/export or `agent-office/`.

## Assumptions
- A real match has at most about 1 score change per 10 minutes, and never more than 4 in a short clip.
- A real scoreboard or TV bug is at most half the frame wide.
- A broadcast with a running clock (or a board that flips in > 25% of seconds) loses board goals, saves and reverts, and uses the roar rule instead. That is accepted for now (R-010 targets phone footage).

## Test plan

- Developer, tests/test_scoreboard.py: test_plausible_board_width_limit (AC1: boxes 80 vs 81 wide on np.zeros((600,30,160)))
- Developer, tests/test_scoreboard.py: test_plausible_board_change_count (AC2: 600 samples 4/5 changes, 3600 samples 6/7)
- Developer, tests/test_scoreboard.py: test_plausible_board_busy_fraction (AC3: 101 samples, box region toggled 0/255 for the first 25 vs 26 transitions, then constant; also a 1-sample array → True)
- Developer, tests/test_scoreboard.py: test_board_changes_and_reverts_reject_implausible_box (AC4: monkeypatch sample_top_band → zeros(600,30,160), find_box → (0,7,160,1), score_changes → []; board_changes is None, board_reverts == [], find_reverts stub raises if called; then a clock case: box (2,2,30,14) whose pixels alternate every sample with score_changes → [] gives None)
- Developer: run the existing suite; the old composition tests (test_audio_cues, test_t014, test_incidents, test_t015 after the one-line edit) pin call order and identity (AC4/AC5)
- Tester, tests/test_t057_acceptance.py: own boundary tests for AC1–AC3, written from the ACs with fresh arrays (do not copy the Developer's)
- Tester: mutation check that the tests can fail. Temporarily change `>` to `>=` in each rule and confirm a boundary test fails, then revert (report it, do not commit)
- Tester, tests/test_t057_acceptance.py (require_ffmpeg): build eval_phone into tmp_path with build_all(tmp_path). For both cases assert AC6. Then run evaluate_dir(tmp_path) and assert AC7 values
- Tester: assert AC9/AC10 by reading README.md, DECISIONS.md and the three spec files (README block == live `python -m sportscut eval <tmp phone> --json` line)
- Tester: run the broadcast eval command and the full `python -m pytest -q`, and quote the summary line and both JSON lines in the report (AC8, AC11)
