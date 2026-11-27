# Plan T-031: Detect ball touches by any player from ball–player proximity and ball direction changes

Design: `docs/superpowers/specs/2026-11-23-t-031-detect-ball-touches-by-any-player-design.md`.

## Implementation plan

# T-031: Detect ball touches by any player (ball–player proximity + ball velocity change)

**Goal:** Replace the `detect_touches` stub in `sportscut/player.py` with real touch candidates by any player, so that `touch_f1_any` goes from 0.0 to ≥ 0.9 on the synthetic eval-player set. The candidates are also shown through `sportscut eval-player --debug`. `find_touches` still returns `[]` for every query, because no candidate has a team or number until T-032/T-033 land.

**Architecture:** Read the frames once with R-004's reader (`media.sample_frames` at `reframe.SAMPLE_HZ` = 5 Hz, scaled to `reframe.ANALYSIS_WIDTH` = 320 px wide). Find the ball with R-004's `reframe.ball_candidates` (per frame, field mask included) and follow it with `reframe.track_ball` (per sample, over the list of candidates). Keep only real detections (hits), never coasted positions. A sample is a **kick** when the ball's velocity over ±SPAN samples changes direction or speed beyond a threshold and the ball leaves at a minimum speed. A kick is a **touch candidate** when the ball is within REACH × blob height of a player blob. Player blobs are the 8-connected regions of `reframe.player_mask` (non-green pixels inside the field mask). Blobs are computed only at kick samples. Greedy non-maximum suppression with a 0.4 s radius gives the final touches.

**Tech stack:** Python 3.11, numpy, ffmpeg through `sportscut.media`. No new dependency.

## Context (read before coding)
- `sportscut/player.py`: `PlayerQuery`, `Touch(t, team, number, confidence, bbox)`, `detect_touches` (stub `[]`), `find_touches` (filters detect_touches by team/number). `find_touches` is **unchanged** in this task.
- `sportscut/reframe.py` (R-004: T-044 = T-017, T-045 = T-019, T-020): `SAMPLE_HZ`, `ANALYSIS_WIDTH`, `BALL_GATE`, `BALL_LOST`, `field_mask`, `player_mask` (3×3-eroded non-green inside the field, or `None` with no field), `ball_candidates(frame) -> [(x, y, score)]` (`[]` with no field), `track_ball(samples, gate, lost_after) -> [(x, y) | None]` (holds the last hit while coasting).
- `sportscut/media.py`: `probe_size`, `sample_frames(path, fps, width, height) -> uint8 (n, h, w, 3)`, `MediaError`.
- `sportscut/eval_player.py`: `evaluate_dir(path)` calls `player.detect_touches(clip)` once and `player.find_touches(clip, q)` per query. `seconds_per_min` = find_touches wall time / (duration × queries / 60). Because find_touches calls detect_touches, this number is the cost of one full detection per minute of video.
- `tests/fixtures/eval_player/build.py`: 640×360 at 25 fps, 16×32 shirts, ball radius 4 (white), ball 24 px below the shirt centre at touches, 4 cases / 39 touches on a 0.2 s grid, at least 1.2 s apart. near_miss has static defenders (blue 4, blue 2) passed by the ball at constant velocity, 6–14 px away. After the last touch the ball rolls to `ball_end` and stops next to the last toucher. That stop is **not** a label.
- Decisions of T-020 (ball detector, tracker), T-029 (eval, matching ±0.5 s, CLI output) and T-030 (find_touches through the module attribute) stay in force.

## Files
- Modify `sportscut/player.py`: constants and the functions `player_blobs`, `find_kicks`, `suppress_touches`, plus the real `detect_touches`. Imports `from sportscut import media, reframe`.
- Modify `sportscut/eval_player.py`: `evaluate_dir(path, debug: bool = False)`.
- Modify `sportscut/cli.py`: `eval-player --debug`.
- Create `tests/test_touches.py` (Developer tests).
- Modify `tests/test_player.py`: only the first line of `test_detect_touches_stub_and_find_filters` (see Step 4).
- Modify `tests/test_eval_player_fixtures.py`: only the two baseline asserts of `test_eval_player_cli_baseline_json` (see Step 7).
- Create `tests/test_t031_acceptance.py` (Tester).
- Modify `README.md`: insert-only new section.
- Modify `docs/superpowers/specs/2026-11-23-t-029-build-the-player-touch-eval-synthetic-design.md`: append one bullet.
- **Never modify:** `sportscut/reframe.py`, `sportscut/media.py`, `tests/conftest.py`, `tests/fixtures/eval_player/**`, `pyproject.toml`, any other existing test.

## Interfaces (all in `sportscut/player.py`)
```python
KICK_SPAN = 2         # samples before/after used for velocity (tunable 1..3)
TURN_DEG = 30.0       # min direction change, degrees (tunable 10..60)
SPEED_JUMP = 0.5      # min |s_out - s_in| / max(s_in, s_out) (tunable 0.2..0.8)
MIN_SPEED = 0.015     # min speed, fraction of analysis width per second (tunable 0.005..0.05)
REACH = 0.5           # max ball-to-blob gap, times blob bbox height (tunable 0.25..1.0)
BLOB_MIN_AREA = 20    # min eroded pixels of a player blob (tunable 10..40)
TOUCH_NMS = 0.4       # suppression radius in seconds (fixed)

def player_blobs(frame: np.ndarray) -> list[tuple[int, int, int, int]]
def find_kicks(hits: Sequence[tuple[float, float] | None], width: int) -> list[tuple[int, float]]
def suppress_touches(touches: Sequence[Touch]) -> list[Touch]
def detect_touches(video: str | os.PathLike[str]) -> list[Touch]
```
- `player_blobs(frame)`: `mask = reframe.player_mask(frame)`. Returns `[]` when the mask is `None`. Otherwise it labels the 8-connected components of `mask` (a plain Python BFS/scan over `np.argwhere(mask)`; no scipy, and called only at kick samples). It keeps components with ≥ BLOB_MIN_AREA pixels and returns each one's bbox `(x, y, w, h)` in analysis px, grown by 1 px on every side to undo the 3×3 erosion and clipped to the frame. The list is sorted by `(y, x)`.
- `find_kicks(hits, width)`: `hits[i]` is the ball position (analysis px) at sample i, or `None` when the ball was not really detected. For each i with `hits[i-S]`, `hits[i]` and `hits[i+S]` all present (S = KICK_SPAN, dt = S / reframe.SAMPLE_HZ): `v_in = (hits[i] - hits[i-S]) / dt` and `v_out = (hits[i+S] - hits[i]) / dt`, in px/s, with speeds `s_in` and `s_out`; `vmin = MIN_SPEED * width`. **No kick** when `s_out < vmin` (a ball coming to rest is not a touch). `jump = abs(s_out - s_in) / max(s_in, s_out)`. `turn` = the angle between v_in and v_out in degrees when `s_in >= vmin`, else 0. It is a kick when `turn >= TURN_DEG or jump >= SPEED_JUMP`, with `strength = min(1.0, max(turn / 180, jump))`. Returns `[(i, strength)]` in index order. Strength is always in (0, 1].
- `suppress_touches(touches)`: greedy by confidence descending (ties: earlier t first). A touch is dropped if `abs(t - kept.t) <= TOUCH_NMS + 1e-9` for any kept touch. Returns the kept touches sorted by t.
- `detect_touches(video)`:
  1. `width, height = media.probe_size(video)`; `aw = min(reframe.ANALYSIS_WIDTH, width)`; `ah = max(2, 2 * round(height * aw / width / 2))` (the same size rule as `reframe.plan_crop`); `frames = media.sample_frames(video, reframe.SAMPLE_HZ, aw, ah)`. Call these through the module attributes so tests can monkeypatch them.
  2. `cands = [reframe.ball_candidates(f) for f in frames]`; `track = reframe.track_ball(cands, reframe.BALL_GATE * aw, reframe.BALL_LOST)`.
  3. `hits[i] = track[i]` if `track[i]` equals `(c[0], c[1])` of some candidate in `cands[i]`, else `None` (this drops coasted positions).
  4. For each `(i, s)` in `find_kicks(hits, aw)`: `blobs = player_blobs(frames[i])`. Take the blob with the smallest gap from `hits[i]` to its bbox (Euclidean distance to the nearest bbox point, 0 when inside; ties go to the first blob). If `gap <= REACH * blob_h`, emit `Touch(t=round(i / reframe.SAMPLE_HZ, 4), team=None, number=None, confidence=round(s, 4), bbox=(round(x*k), round(y*k), round(w*k), round(h*k)))` with `k = width / aw` (source pixels).
  5. Return `suppress_touches(raw)`.
  - With no field (close-up), `ball_candidates` returns `[]`, so there are no hits and the result is `[]`. A missing file raises `MediaError` from `probe_size`.
- `eval_player.evaluate_dir(path, debug=False)`: when `debug` is true, each `per_clip` entry gets a last key `"candidates": [touch.to_dict() for touch in detected]`, reusing the `detected` list already computed. Without debug the output is byte-for-byte the same shape as today.
- `cli.py`: `eval_player_parser.add_argument("--debug", action="store_true", help="add each clip's touch candidates to the report")` and `evaluate_dir(args.directory, debug=args.debug)`. `--json` and the error handling are unchanged.

## Steps (test-first)
**Step 0 – precondition (run before any file change).**
```bash
python - <<'EOF'
import subprocess
try:
    from sportscut import reframe, media
except Exception as exc:
    print(f"BLOCKED: T-031 needs R-004 reframe ({exc}); do not duplicate it"); raise SystemExit(1)
need = {reframe: ("SAMPLE_HZ", "ANALYSIS_WIDTH", "BALL_GATE", "BALL_LOST", "field_mask", "player_mask", "ball_candidates", "track_ball"),
        media: ("sample_frames", "probe_size", "probe_duration", "MediaError")}
missing = [f"{m.__name__}.{n}" for m, names in need.items() for n in names if not hasattr(m, n)]
log = subprocess.run(["git", "log", "--format=%s"], capture_output=True, text=True).stdout
missing += [f"commit {t}" for t in ("T-044", "T-045", "T-020") if t not in log]  # T-017 landed as T-044, T-019 as T-045
print("BLOCKED: T-031 needs R-004 " + ", ".join(missing) + "; do not duplicate it" if missing else "READY")
EOF
```
If it prints BLOCKED, report it along with `python -c "import sportscut.reframe as r; print([n for n in dir(r) if not n.startswith('__')])"` and change nothing. If READY, also record the baselines: `python -m pytest -q` (quote the summary line; it must have 0 failed), `python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json` (BASE_F1), and `python -m sportscut eval-player tests/fixtures/eval_player --json` after `python tests/fixtures/eval_player/build.py` (all 0.0).

**Step 1 – blobs.** In `tests/test_touches.py`, write tests on numpy frames (320×180, filled (40,140,60)):
- one red (200,30,30) 8×16 rect at (100,60) gives `[(100,60,8,16)]`;
- a white radius-2 disc on its own gives `[]` (too small after erosion);
- two rects 10 px apart give 2 bboxes sorted by (y, x);
- an all-gray (128,128,128) frame gives `[]` (no field).

Run them and see them fail (ImportError). Implement `player_blobs`. Run them and see them pass.

**Step 2 – kicks.** Tests on hit lists (width 320, 5 Hz, S=2):
- a constant velocity of (4,0) px/sample for 15 samples gives `[]`;
- the same path turning 90° at index 7 gives a list whose highest-strength entry has index 7 and strength ≥ 0.5;
- a ball at rest for 6 samples then moving at 4 px/sample gives a kick at the first move index, with strength 1.0;
- a ball moving then at rest from index 7 gives no kick at index ≥ 6 (the rest rule);
- a 3° heading change with speed ratio 1.05 at index 7 (near miss) gives `[]`;
- `None` at index 5 means no kick at indices 3, 5 or 7.

Run, fail, implement `find_kicks`, pass.

**Step 3 – NMS.** Test: touches at t = 1.0 (conf 0.6), 1.2 (0.9), 1.4 (0.5), 1.6 (0.9), 2.0 (0.7). `suppress_touches` keeps [1.2, 1.6, 2.0]? No: 1.6 lies within 0.4 of 1.2, so the result is [1.2, 2.0]. Add an exact-boundary test: 1.0 (0.9) and 1.4 (0.5) gives [1.0] (0.4 is suppressed), and 1.0 and 1.6 give both. Add an equal-confidence tie test: 1.0 (0.5) and 1.2 (0.5) give [1.0]. Run, fail, implement, pass.

**Step 4 – detect_touches on media.** Tests:
- `detect_touches(synthetic_video) == []`, using the conftest black/white clip, which has no field, i.e. a close-up;
- `detect_touches("missing-x.mp4")` raises `MediaError`;
- a monkeypatched unit test: patch `media.probe_size` → (640, 360), `media.sample_frames` → 15 synthetic 320×180 field frames with a red 8×16 player whose ball (white radius-2 disc) sits 4 px below the shirt and turns 90° at sample 7. Assert exactly one Touch, with t == 1.4, team and number None, 0 < confidence ≤ 1, and a bbox equal to the source-px (×2) blob bbox.

In `tests/test_player.py`, change only `assert detect_touches("x.mp4") == []` to `with pytest.raises(MediaError): detect_touches("x.mp4")` (import `MediaError` from `sportscut.media`). The rest of that test is unchanged. Run, fail, implement `detect_touches`, pass.

**Step 5 – eval integration test** (in `tests/test_touches.py`). This test uses `require_ffmpeg` and a module-scoped fixture that loads `tests/fixtures/eval_player/build.py` the same way `tests/test_eval_player_fixtures.py` does and calls `build.build_all(tmp_dir)`. It asserts:
- `evaluate_dir(tmp)['touch_f1_any'] >= 0.9`;
- `f1 == precision == recall == 0.0`;
- for every case and query, `find_touches(clip, q) == []`.

**Step 6 – --debug.** Tests:
- `main(['eval-player', d, '--json', '--debug'])` prints one line, and every per_clip entry has `candidates`, equal to `[t.to_dict() for t in player.detect_touches(clip)]`;
- without `--debug`, no per_clip entry has a `candidates` key.

Use monkeypatched `player.detect_touches` and `find_touches` with the built set or a tiny labelled dir. Run, fail, implement, pass.

**Step 7 – update the stale T-029 baseline asserts.** In `tests/test_eval_player_fixtures.py::test_eval_player_cli_baseline_json`, replace `assert report["f1"] == report["touch_f1_any"] == 0.0` with `assert report["f1"] == 0.0 and report["touch_f1_any"] >= 0.9`, and replace `assert report["team_accuracy"] is report["id_accuracy"] is None` with `assert report["team_accuracy"] == report["id_accuracy"] == 0.0`. Change nothing else in that file.

**Step 8 – measure and tune.** Run `python tests/fixtures/eval_player/build.py && python -m sportscut eval-player tests/fixtures/eval_player --json --debug`. Tune only the constants above, within their ranges. Gates:
- `touch_f1_any >= 0.9`;
- the near_miss clip has no candidate more than 0.5 s from every label, and none within 0.5 s of a near-miss moment (about 4.4 s and 9.6 s);
- `seconds_per_min <= 6.0` (90 min × 6.0 s = 540 s < 600 s budget).

If no in-range setting passes, report `BLOCKED` with the best JSON and the setting. Do not add new rules or change reframe.py; the Tech Lead decides.

**Step 9 – docs and final checks.**
- Insert into README.md a new section `## Phát hiện chạm bóng (T-031)` **immediately before** `## Highlight theo sự kiện: đo độ chính xác (eval)`. It is insert-only, and every other section stays byte-identical. It explains, in Vietnamese, that touches by any player are detected from the ball changing direction or speed next to a player blob, that close-ups with no field produce no candidates, and that `find_touches` still returns nothing until T-032/T-033. It also contains:
  - the command `python -m sportscut eval-player tests/fixtures/eval_player --json --debug`;
  - a ```text block listing the final constant values;
  - the line `Kết quả đo trong T-031:` followed by a ```json block with the one-line report (without --debug) from a real run in this session.
- Append to the T-029 design spec the bullet: `- T-031 (2026-11-27): detect_touches now returns touch candidates by any player (team/number None); find_touches still returns [] until T-032/T-033. The T-029 README baseline is kept as history.`
- Run `python -m pytest -q` (0 failed), the eval-player command, and `python -m sportscut eval tests/fixtures/eval --json` (f1 == BASE_F1).
- Run `grep -nE "subprocess|ffmpeg|green_mask|cumsum|def (sample_frames|field_mask|ball_candidates|track_ball)" sportscut/player.py`, which must print nothing.
- Run `git diff --stat main -- sportscut/reframe.py sportscut/media.py tests/conftest.py tests/fixtures/eval_player pyproject.toml`, which must be empty.
- Check that `git diff --numstat main -- . ':!docs/superpowers'` totals < 600 lines.
- Put the measured JSON, seconds_per_min and the 90-min projection (seconds_per_min × 90) in the PR.

## Global constraints
- Never write a frame reader, field mask or ball detector/tracker in player.py; reuse R-004's.
- No new dependency; numpy only.
- `Touch` and `PlayerQuery` are unchanged; `find_touches` is unchanged.
- eval-player output without `--debug` is unchanged in shape; the `sportscut eval` F1 must not drop.
- Diff < 600 changed lines outside docs/superpowers (T-020/T-045 precedent for one gated algorithmic slice).

## Review focus
1. A coasted (held) tracker position used as a hit would create a fake stop and then a fake kick. Step 3 of detect_touches must compare against the real candidates.
2. The ball rolling to rest next to the last toucher (`ball_end` in every case) must not become a touch; the s_out ≥ vmin rule covers it.
3. A video narrower than 320 px: `aw = width` (never upscaled), and the bbox scale k = 1.
4. Fewer frames than 2·SPAN+1, or an empty `frames` array, must give `[]` without IndexError.
5. Each per-query `find_touches` call reruns detection; seconds_per_min must still be ≤ 6.0.

## Assumptions
- R-004's `track_ball` works over a list of per-frame candidate lists, and `ball_candidates` works one frame at a time. This satisfies the 'stepped per frame' capability the Tech Lead requires, so Step 0 prints READY on main 473b97e.
- A ball that stops at a player's feet without being played away is not counted as a touch. The receiver's next touch (dribble or pass) is counted instead. This matches the T-029 labels, which do not label the `ball_end` stop.
- Holding all 5 Hz frames in memory (R-004's `sample_frames`) is accepted here. A streaming reader belongs in media.py/R-004 and is out of scope.

## Test plan

- tests/test_touches.py::test_player_blobs_single_rect: a 320x180 field frame with a red 8x16 rect at (100,60) gives [(100,60,8,16)]
- tests/test_touches.py::test_player_blobs_ignores_ball_and_no_field: a lone white r=2 disc gives []; an all-gray frame gives []; two rects give 2 bboxes sorted by (y,x)
- tests/test_touches.py::test_find_kicks_straight_none / _turn_peaks_at_turn / _start_from_rest / _rest_is_not_a_kick / _near_miss_wobble_none / _gaps_skip: the hit-list cases of AC3
- tests/test_touches.py::test_suppress_touches_radius_and_ties: {1.0:.6,1.2:.9,1.4:.5,1.6:.9,2.0:.7} gives [1.2,2.0]; the 0.4 boundary is suppressed; 0.6 apart keeps both; an equal-confidence tie keeps the earlier
- tests/test_touches.py::test_detect_touches_monkeypatched_frames: patched probe_size (640,360) and sample_frames (15 synthetic frames, 90° ball turn at sample 7 below a red blob) give one Touch at t=1.4 with team/number None and the bbox scaled ×2
- tests/test_touches.py::test_detect_touches_no_field_and_missing (require_ffmpeg for synthetic_video): [] for the no-grass clip; MediaError for a missing file
- tests/test_touches.py::test_eval_player_gate (require_ffmpeg, module fixture builds the set in tmp): touch_f1_any ≥ 0.9, f1 == precision == recall == 0.0, find_touches == [] for every case/query
- tests/test_touches.py::test_cli_debug_candidates: --json --debug prints one line with per_clip candidates == detect_touches dicts; no candidates key without --debug
- tests/test_player.py::test_detect_touches_stub_and_find_filters: first line now `with pytest.raises(MediaError): detect_touches('x.mp4')`; the filter part is unchanged
- tests/test_eval_player_fixtures.py::test_eval_player_cli_baseline_json: asserts updated to f1 == 0.0, touch_f1_any ≥ 0.9, team_accuracy == id_accuracy == 0.0
- tests/test_t031_acceptance.py (Tester, written from the ACs): builds the synthetic set in tmp with build.build_all; checks AC7's gate including seconds_per_min ≤ 6.0; AC8's near-miss check, computing the moments independently from build.ball_pos/player_box/case labels; AC5/AC10 Touch shape and find_touches == []; AC6 with a lavfi gray clip and the conftest synthetic_video; AC9's --debug contract; AC12's grep of player.py and empty diff of the protected files; AC13's README placement/insert-only/JSON block. It confirms the tests can fail by checking that a monkeypatched detect_touches returning one touch per near-miss moment fails the AC8 check.
- Verify commands: `python -m pytest -q`; `python tests/fixtures/eval_player/build.py && python -m sportscut eval-player tests/fixtures/eval_player --json` (touch_f1_any ≥ 0.9, seconds_per_min ≤ 6.0); `python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json` (f1 == main's)

## Deviations

- Step 2 tests: the plan wrote the hit-list cases for S = 2 (for example "None at index 5 means no kick at 3, 5 or 7"). The tuned KICK_SPAN is 1, so the tests now run under a `span` fixture parametrized over KICK_SPAN 1 and 2. The gap case checks the AC3 rule `{5 - S, 5, 5 + S}`, and the short-list case uses `2 * S` hits. The plan's S = 2 cases are all still covered.
- Step 8 tuning (only in-range constants, no new rules): KICK_SPAN 2→1, TURN_DEG 30→20, SPEED_JUMP 0.5→0.75, REACH 0.5→0.75; MIN_SPEED 0.015 and BLOB_MIN_AREA 20 are unchanged. Defaults gave touch_f1_any 0.961, but near_miss had 1 FP at 17.8 s: the ±0.4 s window straddled the `ball_end` stop at 18.0 s, giving s_out 9.9 px/s > vmin and jump 0.70. With KICK_SPAN 1 the stop falls exactly on s_out = 0. An offline sweep of the full in-range grid (16,380 settings, over cached hits/blobs) found 27 settings at F1 1.0, but every one needs SPEED_JUMP 0.3 with MIN_SPEED 0.04, which sit on measured knife edges (8.2 s jump 0.31; 16.4 s s_out 13.5 vs 12.8 px/s). The chosen setting gives 0.9737 (0 FP, 2 FN: short_passes 8.2 s and 16.4 s, speed-only changes of 0.42/0.56 that are below SPEED_JUMP), and all 11 of its one-step grid neighbours also pass the gate.
- Open conflict, not resolved here: tests/test_t042_round2_acceptance.py::test_ac10_protected_paths_untouched_and_no_tracked_mp4 and tests/test_t042_tester_acceptance.py::test_ac10_protected_paths_are_untouched_and_no_mp4_is_tracked list `sportscut/eval_player.py` as protected against `git merge-base main HEAD`, with no own-branch gate. This task's spec requires changing that file (Files, AC9), and AC11 forbids editing other existing tests. Escalated to the Tech Lead; those tests are not edited.
- T-042 AC10 own-branch gate (Tech Lead round 2, decision-351/E3 pattern), resolving the conflict above: AC11 is amended. In those two tests, only the protected-files `git diff` call and its two asserts now run when the branch starts with `office/T-042`. The tracked-mp4 check stays unconditional, and no other line of either file changed. Any git-diff scope test in tests/test_t031_acceptance.py must likewise start with an own-branch gate (skip unless the branch starts with `office/T-031`).
