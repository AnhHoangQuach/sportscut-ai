# Plan T-052: Follow the toucher around each touch, vote its jersey number and keep only the chosen player, with --min-confidence

Design: `docs/superpowers/specs/2026-11-28-t-052-follow-the-toucher-around-each-touch-design.md`.

## Implementation plan

# T-052: Follow the toucher around each touch, vote its jersey number and keep only the chosen player (`--min-confidence`)

Request R-006 (Theo dõi cầu thủ). This is the second of three T-033 slices. T-051 already landed `media.sample_window` and `sportscut/jersey.py` (DigitReader, vote, get_reader). T-053 will add OCR, the env var and `download-models --ocr`. The design source is `docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md`. The T-033 plan file was never merged; its text is in commit 11413ad. This spec restates every part this slice needs, so there is no need to open it.

## Context (main @ 9275958)
- `player._analyse(video)` makes one pass at 5 Hz and 320 px and returns `(touches, TeamColours | None)`. `Touch.bbox` is the toucher's blob in **source px**. `detect_touches` returns `_analyse(video)[0]`. `find_touches` returns every touch of `pick_team(query.team, colours)` and ignores `query.number`.
- `jersey.get_reader()` always returns `DigitReader()` (`name 'digits'`, `max_reads None`). `jersey.vote(reads)` returns `(int | None, float)`. DigitReader drops ink that touches the crop edge, so a blob crop with a grass margin reads correctly.
- `media.sample_window(path, start, duration, fps, width, height)` returns uint8 `(n, height, width, 3)`, with frame k at `start + k/fps`.
- Synthetic set `tests/fixtures/eval_player/build.py`: 640×360, 16×32 shirts, the number drawn on shirt rows 6..15. Case `number_hidden` hides blue 8 during [t-1, t+1] around each of its touches. Non-author players move 30·k px beside the authors, so players cross each other.
- Base eval-player (README `Sau T-032`): f1 0.5827, precision 0.4205, recall 0.9487, touch_f1_any 0.9737, team_accuracy 1.0, id_accuracy 0.0, seconds_per_min 2.6874.
- `tests/test_t031_acceptance.py::test_ac5_no_own_reader_or_detector_in_player` forbids `subprocess|ffmpeg|green_mask|cumsum|def (sample_frames|field_mask|ball_candidates|track_ball)` on any line of player.py, comments and docstrings included.
- `tests/test_t033a_acceptance.py::test_ac9_t033_spec_appendix` requires `## Updated by T-051` to stay the LAST `## ` section of the T-033 design spec.
- `tests/test_t032_acceptance.py::test_ac13` pins two things: the heading after `## Đội theo màu áo (T-032)` is `## API HTTP`, and the last bullet of the T-029/T-031 'Existing specs this task changes' lists is fixed.

## Design

### 1. `sportscut/player.py`
Imports change to `from dataclasses import dataclass, replace` and `from sportscut import jersey, media, reframe`. Readers are always obtained through `jersey.get_reader()` as a module attribute, so tests can patch it. Add a new constant block directly after `TEAM_ITERS`, before `normalize_team`:
```python
NUMBER_SPAN = 2.0     # seconds read before and after each touch (fixed)
NUMBER_WIDTH = 1280   # max decode width of the number crops, never upscaled (fixed)
TRACK_GATE = 1.0      # max distance from the predicted centre per 5 Hz sample, times the previous box height (tunable 0.5..2.0)
TRACK_MERGE = 1.3     # a blob wider or taller than this times the seed box is two merged players (tunable 1.2..1.6)
MIN_CONFIDENCE = 0.5  # default min vote confidence (tunable 0.3..0.8)
```
Three existing top-level definitions change: `PlayerQuery`, `detect_touches` and `find_touches`. Every other existing definition stays byte-identical. That covers every T-031/T-032 constant, normalize_team, Touch, colour_features, kmeans, TeamColours, shirt_pixels, _TEAM_FEATS, name_teams, team_colours, team_of, pick_team, player_blobs, find_kicks, suppress_touches, _box_gap and `_analyse`.

**PlayerQuery.** Add a third field, `min_confidence: float = MIN_CONFIDENCE`. In `__post_init__`, after the number check, raise `ValueError("min confidence must be between 0 and 1")` when the value is any of:
- a bool;
- not an int/float instance;
- non-finite;
- outside [0, 1].

Otherwise store `float(value)` with `object.__setattr__`. So `PlayerQuery('red', 10) == PlayerQuery('red', 10, MIN_CONFIDENCE)`, and API and eval callers keep the default.

**`_read_numbers(video, touches: Sequence[Touch], reader: jersey.NumberReader) -> list[tuple[int | None, float]]`** returns one vote per input touch, in input order.
1. A touch with `bbox is None` gets `(None, 0.0)`. If no touch has a bbox (this includes `[]`), return at once without calling probe_size or sample_window.
2. Set the decode size and the tracking scale:
   - `width, height = media.probe_size(video)`;
   - `nw = min(width, NUMBER_WIDTH)` and `nh = max(2, 2 * round(height * nw / width / 2))`;
   - `s = max(1, nw // min(reframe.ANALYSIS_WIDTH, nw))`.
   Tracking runs on `frame[::s, ::s]` with the unchanged `player_blobs`. Source px map to tracking px with `f = nw / width / s`.
3. Windows use `HZ = reframe.SAMPLE_HZ` and are built only for touches with a bbox:
   - `lo = max(0, floor((t - NUMBER_SPAN) * HZ + 1e-6) / HZ)`;
   - `hi = ceil((t + NUMBER_SPAN) * HZ - 1e-6) / HZ`.
   Sort by lo and merge while `next.lo <= cur.hi + 1e-9`; the merged hi is the max. Each group is one call: `media.sample_window(video, round(lo, 4), round(hi - lo + 1 / HZ, 4), HZ, nw, nh)`. Frame k is at time `lo + k / HZ`. A short return near the clip end is not an error; missing frames are simply absent.
4. Each touch uses only the group frames with `abs(lo + k / HZ - t) <= NUMBER_SPAN + 1e-6`, so grouping never changes a vote. `player_blobs` results are cached per group frame.
   - **Seed.** The seed box is `bbox * f`, with size (sw, sh). The seed frame is the in-span frame nearest t. Pick the blob whose centre is nearest the seed-box centre, and accept it only within `TRACK_GATE * sh`. If none is accepted, the vote is `(None, 0.0)`.
   - **Walk.** Go forward and backward from the seed separately. Each direction starts with `v = (0, 0)`, `c` = the seed blob centre and `hp` = its h. In the next frame:
     - predict `p = c + v`; the candidates are blobs whose centre lies within `TRACK_GATE * hp` of p;
     - if there is no candidate, stop this direction;
     - otherwise take the candidate nearest p;
     - if it is **merged** (`w > TRACK_MERGE * sw or h > TRACK_MERGE * sh`), **coast**: set `c = p`, keep v and read no crop;
     - if it is not merged, set `v = centre - c`, `c = centre`, `hp = h`, and keep its crop.
     A merged seed blob also gives no crop, but the walk still runs from it.
   - **Crops.** Each kept blob `(x, y, w, h)` in tracking px is cut from the full nw×nh frame as `frame[y*s:(y+h)*s, x*s:(x+w)*s]`. Crops are kept in time order. If `reader.max_reads` is set and there are more than max_reads crops, read only the indices `sorted({int(round(float(v))) for v in np.linspace(0, n - 1, max_reads)})`.
   - The result is `jersey.vote([reader.read(c) for c in crops])`.

The T-033 design spec describes a plain nearest-centre tracker. The blocked T-033 attempt measured it at best number_hidden f1 0.7143 over the whole tuning grid, because blue 8 crosses another player and the track jumps to that player. This slice therefore replaces it with constant-velocity prediction and TRACK_MERGE coasting.

**`detect_touches(video)`** (supersedes T-032 AC8, detect_touches == _analyse(video)[0]):
1. `reader = jersey.get_reader()` comes first, then `touches, _ = _analyse(video)` once.
2. `labelled = [t for t in touches if t.team is not None]`, then `votes = _read_numbers(video, labelled, reader)`.
3. A labelled touch with `n is not None and c >= MIN_CONFIDENCE` becomes `replace(t, number=n)`. Every other touch is returned unchanged, and the order stays the same.

**`find_touches(video, query)`** (supersedes the T-032 'number ignored' rule):
1. `reader = jersey.get_reader()`, then `touches, colours = _analyse(video)` once.
2. If colours is None, return `[]`. Otherwise `team = pick_team(query.team, colours)`; its tie ValueError propagates before any read.
3. `same = [t for t in touches if t.team == team]`, then `votes = _read_numbers(video, same, reader)`.
4. Return `[replace(t, number=n) for t, (n, c) in zip(same, votes) if n == query.number and c >= query.min_confidence]`.

Docstrings must not contain the word ffmpeg.

### 2. `sportscut/cli.py`
Change the import to `from sportscut.player import MIN_CONFIDENCE, PlayerQuery`. Then:
- Add the option: `player_parser.add_argument("--min-confidence", type=float, default=MIN_CONFIDENCE, help=f"minimum jersey-number vote confidence 0..1 (default {MIN_CONFIDENCE}); lower finds more touches, higher keeps fewer wrong ones")`.
- Build the query as `query = PlayerQuery(args.team, args.number, args.min_confidence)`.
- Bad values (1.5, -0.1, nan) go through the existing `except ValueError` path: exit 2 and `sportscut player: error: min confidence must be between 0 and 1`. This happens before make_player_reel, so --out is not created.

### 3. `README.md` (insert-only, 0 deleted lines)
Insert a new section `## Số áo cầu thủ (T-033)` directly before the line `## Đội theo màu áo (T-032)`, so it follows the `## Theo dõi cầu thủ: xuất video tổng hợp (player)` section. It is written in Vietnamese and contains:
- **How it works:** around each touch of the chosen team, ±2 s at 5 khung/giây; bám khối cầu thủ chạm bóng (bỏ qua khung hai cầu thủ dính nhau); đọc số trên từng khung bằng bộ đọc chữ số numpy; bỏ phiếu theo độ tin cậy; only touches whose number equals `--number` are kept.
- **Example:** a ```bash block with `python -m sportscut player match.mp4 --team red --number 10 --min-confidence 0.3 --out reel`, plus one sentence: a lower `--min-confidence` gives more touches, a higher one gives fewer wrong ones (default 0.5).
- **Limitation:** ở `góc rộng` số áo thường quá nhỏ để đọc. Real-match recall can only be measured once the PO supplies a labelled `data/eval_player/`. The reader has only been measured on the synthetic font.
- **Constants:** a ```text block with lines `NAME = value  # chú thích` whose values equal the module constants:
  - from player: NUMBER_SPAN, NUMBER_WIDTH, TRACK_GATE, TRACK_MERGE, MIN_CONFIDENCE;
  - from jersey: VOTE_MIN_READS, INK_CONTRAST, INK_MIN_PIXELS, NUMBER_TOP, DIGIT_MIN_SCORE.
- **Reports:** `Trước T-033:` followed by a one-line ```json block with the Step 0 eval-player report, and `Sau T-033:` followed by a one-line ```json block with the final report. Both are pasted from real runs, unedited.
- **Not included:** the section does NOT contain `SPORTSCUT_NUMBER_READER`, `easyocr`, `[ocr]` or `download-models --ocr` (T-053 adds them).

### 4. Spec notes (docs/superpowers)
- **T-030, T-031 and T-032 design specs.** Append at the end of each a blank line, then `## Updated by T-033`, then 2–5 lines. They state:
  - it landed in T-052;
  - find_touches now reads jersey numbers (the number vote) around each touch of the mapped team and keeps only touches whose voted number equals the query with confidence ≥ min_confidence;
  - detect_touches fills Touch.number when the vote confidence ≥ MIN_CONFIDENCE;
  - new `sportscut player --min-confidence`;
  - this supersedes the T-032 'number ignored' rule and T-032 AC8;
  - the OCR backend follows in T-053.
  Nothing else changes, and the T-029/T-031 'Existing specs this task changes' bullets keep their last line.
- **T-033 design spec.** Append a plain paragraph with NO `## ` heading, because test_t033a pins `## Updated by T-051` as the last section. It starts `Updated by T-052:` and says:
  - what landed: _read_numbers, PlayerQuery.min_confidence, number filtering in detect_touches/find_touches, `player --min-confidence` and the README section;
  - the tracker change: constant-velocity prediction and the TRACK_MERGE coast rule, with the reason;
  - that OcrReader, SPORTSCUT_NUMBER_READER and `download-models --ocr` are left for T-053.

### 5. The nine allowed edits to pre-existing tests (T-033 AC15). Only these functions change.
Do not change module-level imports in these files. Build expected touches inside the function, with literals or `dataclasses.replace` where `dataclasses` is already imported.
1. `tests/test_player.py::test_detect_touches_stub_and_find_filters`:
   - after the `_analyse` patch, add `monkeypatch.setattr("sportscut.player._read_numbers", lambda video, touches, reader: [(t.number, 1.0) for t in touches])`;
   - the expected value becomes `[values[0]]`.
2. `tests/test_teams.py::test_detect_touches_labels_team`:
   - before `player.detect_touches`, patch `player._read_numbers` with `lambda video, touches, reader: [(None, 0.0)] * len(touches)`;
   - `find_touches("clip.mp4", PlayerQuery("red", 99))` now `== []`.
3. `tests/test_teams.py::test_find_touches_team_only_single_pass`:
   - patch `player._read_numbers` with `lambda video, touches, reader: [{1: (10, .9), 2: (3, .9), 3: (7, .9)}[t.t] for t in touches]`;
   - red 10 now gives `[Touch(1, "red", 10, 1, None)]`;
   - `#0000ff` 3 now gives `[Touch(2, "blue", 3, 1, None)]`;
   - detect_touches now gives `[Touch(1, "red", 10, 1, None), Touch(2, "blue", 3, 1, None), values[2]]`;
   - the calls, tie and None-colours asserts stay.
4. `tests/test_teams.py::test_eval_player_team_gate`: `report["id_accuracy"] == 0.0` becomes `report["id_accuracy"] >= 0.75`.
5. `tests/test_t032_acceptance.py::test_ac8_detect_touches_team`: the first line patches `P._read_numbers` with `lambda v, xs, r: [(None, 0.0)] * len(xs)`.
6. `tests/test_t032_acceptance.py::test_ac9_find_touches_and_cli`:
   - patch `P._read_numbers` with `lambda v, xs, r: [(10, .9) if x.team == "red" else (99, .9) for x in xs]`;
   - `Q("red", 10)` gives `[dataclasses.replace(ts[0], number=10), dataclasses.replace(ts[2], number=10)]`;
   - `Q("sky", 99)` gives `[dataclasses.replace(ts[1], number=99)]`;
   - `Q("#ff1010", 1)` gives `[]`;
   - detect gives `[replace(ts[0], number=10), replace(ts[1], number=99), replace(ts[2], number=10), ts[3]]`;
   - the calls, tie, None and CLI lines stay.
7. `tests/test_t032_acceptance.py::test_ac10_eval_player_gate_and_queries`: `r["id_accuracy"] == 0` becomes `r["id_accuracy"] >= .75`.
8. `tests/test_t031_acceptance.py::test_ac5_real_set_touch_shape`: `t.number is None` becomes `(t.number is None or (type(t.number) is int and 1 <= t.number <= 99))`.
9. `tests/test_eval_player_fixtures.py::test_eval_player_cli_baseline_json`: `report["id_accuracy"] == 0.0` becomes `report["id_accuracy"] >= 0.75`.

For each one, first run it against the new code and watch it fail for the expected reason. Then edit it and watch it pass.

## Files
- **Modified:** sportscut/player.py (≈ +110), sportscut/cli.py (≈ +5), README.md (≈ +50, insert-only).
- **Test edits:** the five pre-existing test files, only the nine functions above (≈ 25 lines).
- **New tests:** tests/test_player_numbers.py (Developer, ≤ 190 lines) and tests/test_t033b_acceptance.py (Tester, ≤ 190 lines).
- **Docs:** the T-030, T-031, T-032 and T-033 design specs.
- **Not touched:** jersey.py, media.py, eval_player.py, reel.py, api.py, reframe.py, pyproject.toml, tests/conftest.py, tests/fixtures/ and agent-office/.

## Steps (test-first; run `python -m pytest -q <file>` after each)
0. **Step 0, before any edit.**
   - Check that `python -c 'from sportscut.player import TeamColours, pick_team, _analyse, find_touches; from sportscut.jersey import get_reader, vote; from sportscut.media import sample_window; print("READY")'` prints READY. If not, report `BLOCKED: T-052 needs T-032 and T-051 on the base` and leave the diff empty.
   - Run `python tests/fixtures/eval_player/build.py`, then `python -m sportscut eval-player tests/fixtures/eval_player --json` and `python -m sportscut eval tests/fixtures/eval --json`. Save both one-line JSONs; they are the `Trước T-033:` report and the eval f1 baseline.
   - If `data/eval_player/` exists, also run `python -m sportscut eval-player data/eval_player --json`.
1. Write `test_player_query_min_confidence` (AC2) and watch it fail. Then add MIN_CONFIDENCE and the PlayerQuery field.
2. Write the `_read_numbers` tests (AC3) on monkeypatched `media.probe_size` / `media.sample_window`. The fake frames must be a pure function of absolute time `start + k/fps`. Watch them fail, then implement the constants and `_read_numbers`. Prove the crossing test fails with a tracker without velocity or merge, then passes.
3. Write `test_detect_and_find_filter_by_number` (AC4) and watch it fail. Then change detect_touches/find_touches and make the nine test edits (§5).
4. Write `test_cli_min_confidence` (AC5) and watch it fail. Then change cli.py.
5. Write the ffmpeg-backed gate tests (AC6–AC8) and run the eval. Tune only TRACK_GATE [0.5, 2.0], TRACK_MERGE [1.2, 1.6] and MIN_CONFIDENCE [0.3, 0.8]. If no setting passes, report `BLOCKED` with the best JSON and the grid tried; jersey.py constants are not tuned in this slice.
6. Add the README section and the spec notes. Then run the full suite and every command below.

## Commands that prove it
- `python -m pytest -q` reports 0 failed.
- `python tests/fixtures/eval_player/build.py && python -m sportscut eval-player tests/fixtures/eval_player --json` must show:
  - f1 ≥ 0.85 and per_clip number_hidden f1 ≥ 0.85;
  - id_accuracy ≥ 0.75 and precision > 0.4205;
  - team_accuracy ≥ 0.95, touch_f1_any ≥ 0.9737, and per-clip touch_f1_any ≥ dribble 1.0, near_miss 1.0, number_hidden 1.0, short_passes 0.9091;
  - 0 < seconds_per_min ≤ 6.0.
- `python -m sportscut eval tests/fixtures/eval --json`: f1 equals the Step 0 value.
- `python -m sportscut player tests/fixtures/eval_player/number_hidden/clip.mp4 --team blue --number 8 --out /tmp/t052_reel` exits 0 and prints `wrote /tmp/t052_reel/player_blue_8.mp4: ...`.
- `python -m sportscut player tests/fixtures/eval_player/number_hidden/clip.mp4 --team blue --number 8 --min-confidence 1.5 --out /tmp/t052_bad` exits 2 with the error line, and /tmp/t052_bad does not exist.
- `grep -nE 'subprocess|ffmpeg|green_mask|cumsum|def (sample_frames|field_mask|ball_candidates|track_ball)' sportscut/player.py` prints nothing.
- The byte-identity check prints `BYTE-IDENTICAL`:
```bash
python - <<'EOF'
import ast, subprocess
old = subprocess.run(['git', 'show', 'main:sportscut/player.py'], capture_output=True, text=True).stdout
new = open('sportscut/player.py').read()
def blocks(src):
    out = {}
    for node in ast.parse(src).body:
        names = [node.name] if hasattr(node, 'name') else [t.id for t in getattr(node, 'targets', []) if isinstance(t, ast.Name)]
        for name in names:
            out[name] = ast.get_source_segment(src, node)
    return out
o, n = blocks(old), blocks(new)
bad = [k for k in o if k not in ('PlayerQuery', 'detect_touches', 'find_touches') and o[k] != n.get(k)]
print('BYTE-IDENTICAL' if not bad else bad)
EOF
```
- `git diff main -- sportscut/jersey.py sportscut/media.py sportscut/eval_player.py sportscut/reel.py sportscut/api.py sportscut/reframe.py pyproject.toml tests/conftest.py tests/fixtures` is empty.
- `git diff --numstat main -- README.md` shows 0 deleted lines. `git ls-files '*.mp4' '*.pth'` is empty.
- Size: the `git diff --numstat main -- . ':!docs/superpowers'` sum plus the lines of untracked files under sportscut/ and tests/ is < 600.
- If `data/eval_player/` exists, run `python -m sportscut eval-player data/eval_player --json` and paste the output. Otherwise write the line `data/eval_player/ not available: real-match recall not measured`.

## Assumptions
- `number_hidden` is the 'number turned away' case; fixtures, labels and metrics are unchanged.
- Windows start on the 0.2 s grid, so with input seeking a given 5 Hz time decodes to the same frame whichever group decoded it. T-051 AC6 checked this on 25 fps clips.
- The number sits in the top 60 % of the toucher's blob crop, and the grass margin is removed by DigitReader's border-ink rule.
- The reader is DigitReader, because get_reader ignores the environment until T-053. Real-kit accuracy is unknown until data/eval_player/ exists.
- POST /players and the web page now get number filtering through find_touches at the default threshold, with no API code change.

## Review focus
1. **Touch near the clip end:** sample_window returns fewer frames than the window asks for. The touch still votes from the frames it has, without an IndexError.
2. **Touch near t = 0:** the window clamps to lo = 0, and the seed frame is still the one nearest t.
3. **Two players crossing or touching:** no crop of the other player, and no merged two-shirt crop, is ever read.
4. **Read alone or with neighbours:** the vote must not depend on which touches share a window. Otherwise a find_touches result would be missing from detect_touches.
5. **Long match:** only windows around the queried team's touches are decoded at crop resolution, so seconds_per_min stays ≤ 6.0.

Each of these has a test in the test plan.

## Test plan

- Step 0 (Developer, before any edit): print READY, then record the base eval-player and eval JSON (AC1).
- tests/test_player_numbers.py (Developer, ≤ 190 lines). It loads build.py via importlib like test_teams.py. Fake frames come from a helper computing grass frames from the absolute time `start + k/fps`, with shirts drawn by build._draw_number.
- test_player_query_min_confidence: default equality and hash, float storage, the six invalid values and the 0/1 boundaries, and the constant ranges (AC2).
- test_read_numbers_reads_hidden_number_from_neighbour_frames: the number is blank within ±1 s of the touch and the vote is (7, c ≥ MIN_CONFIDENCE) (AC3).
- test_read_numbers_gate_and_missing_bbox: a far bbox and bbox=None give (None, 0.0); [] and an all-None-bbox list make no probe_size/sample_window call (AC3).
- test_read_numbers_stops_after_jump: with a 100 px jump at t+1 s, no crop after the jump is read, recorded by crop time (AC3).
- test_read_numbers_max_reads_subsamples: a recording reader with max_reads=2 is called exactly 2 times (AC3).
- test_read_numbers_merges_grid_aligned_windows: 1.0 s apart gives 1 call, 10 s apart gives 2 calls; starts are ≥ 0 and on the 0.2 grid; t = 0.4 gives start 0.0 (AC3).
- test_read_numbers_vote_independent_of_grouping_and_short_clip: a vote alone equals the vote with a neighbour; a truncated sample_window return still gives one vote per touch (AC3, Review focus 1/2/4).
- test_read_numbers_keeps_identity_through_a_crossing: red 7 crosses a static red 9. The vote is (7, c) and no recorded read is 9 or another number. Write it first against a plain nearest-centre tracker to see it fail (AC4, Review focus 3).
- test_detect_and_find_filter_by_number: patched _analyse/_read_numbers with VOTES keyed by t; covers every AC5 assert, including the get_reader ValueError raised before _analyse (AC5).
- test_cli_min_confidence: exit 2, the error text and no --out dir for 1.5; the PlayerQuery passed with and without the flag; --help (AC6).
- ffmpeg tests (require_ffmpeg, module-scoped built set in tmp_path_factory) in tests/test_player_numbers.py: test_eval_player_number_gate (AC7 numbers plus the find ⊆ detect check); test_number_gate_can_fail (always-None reader, NUMBER_SPAN=0.4, min_confidence monotonicity) (AC8); test_frames_sampled_only_around_touches (sample_frames once, sample_window spans, short_passes t=12.0) (AC9, Review focus 5).
- Edits to the nine pre-existing test functions exactly as in spec §5. Each is first run against the new code to see it fail for the expected reason, then edited and passing.
- tests/test_t033b_acceptance.py (Tester, ≤ 190 lines, written from the acceptance criteria, not from the Developer's tests). It covers AC2–AC9 with its own fakes and its own built set, and the content checks for AC11 (README headings order, required and forbidden strings, constants equal to the modules, one-line Trước/Sau JSON with id_accuracy 0.0 / ≥ 0.75) and AC12 (spec endings). It has no git-diff assertions (T-028/T-049/T-051 rule). The Tester also confirms that the gate tests fail with an always-None reader and with NUMBER_SPAN=0.4, and that the crossing test fails with a plain tracker.
- Full run: `python -m pytest -q` (0 failed), then every command in the spec's 'Commands that prove it', with outputs quoted in the report.

## Deviations

- Test grouping only (no behaviour change): to keep tests/test_player_numbers.py within its 190-line cap, the
  seven planned `_read_numbers` tests are written as two functions:
  `test_read_numbers_reads_hidden_number_and_keeps_identity_through_a_crossing` (parametrized `hidden` /
  `crossing`) and `test_read_numbers_gates_jump_max_reads_missing_bbox_and_windows` (the 100 px jump, max_reads=2,
  far bbox, bbox=None, no decode for [] / all-None, 1 vs 2 sample_window calls on the 0.2 s grid, t=0.4 gives
  start 0.0, grouping independence, truncated window). Every planned assert is still there.
- No tuning was needed: the defaults TRACK_GATE 1.0, TRACK_MERGE 1.3 and MIN_CONFIDENCE 0.5 pass the gate on the first run.
- Review round 1 (Tech Lead): §1 step 3 said 'each group is one call' with no limit on its length. Touches less
  than about 4.2 s apart chained into one sample_window call covering a whole possession (≈ 13.8 MB per second at
  1280×720), which runs out of memory on real matches. Added `NUMBER_GROUP_MAX = 20.0` (fixed): a touch merges into
  the current group only when `lo <= cur_hi + 1e-9 and hi - cur_lo <= NUMBER_GROUP_MAX + 1e-9`. Each touch's window
  stays inside its own group on the 0.2 s grid, so votes and AC9 are unchanged. The README constants block lists it.
