# Plan T-013: Tag goals from scoreboard-region changes plus sustained crowd roar

Design: `docs/superpowers/specs/2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md`.

## Implementation plan

# T-013: Tag goals from scoreboard-region changes plus sustained crowd roar

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A highlight becomes `event='goal'` when a sustained crowd roar (at least 6 s at 6 dB or more above the rolling baseline) comes before a change in the on-screen scoreboard. The change is found without OCR: we sample tiny gray frames at 1 fps, find the most static, high-edge box in the top band, and flag the moments where that box changes and then stays stable. `sportscut cut --events goal`, `POST /highlights events=goal` and `sportscut eval` all see the new labels.

**Architecture:** A new pure-numpy module `sportscut/events/scoreboard.py` does box finding, change detection and roar/scoreboard matching. One I/O wrapper, `tag_goals(video, segments, ...)`, feeds it data from `sportscut.media`, which stays the only module that runs ffmpeg (T-036). `pipeline.run` calls it between `find_highlights(top=None)` and `select_segments`, which is the classifier slot T-012 reserved. `evaluate_dir` calls it right after `detect.find_highlights(video)`, so the eval measures detector plus classifier.

**Tech stack:** Python 3.11, numpy (no new dependency), ffmpeg/ffprobe on PATH.

**Spec sources:** PO request R-003. Read these first: T-002, T-010, T-011, T-012 and T-036 designs, plus `DECISIONS.md`.

## Current code (read before starting)
- `sportscut/detect.py`: `find_highlights(video, top=10, min_len=10, max_len=30)`. Per-second RMS dB, minus a centred rolling median of 121 s, divided by `max(1.4826*MAD, 1.0)`. Peaks are local maxima with z >= 3. Each window has length L = clamp(12, min_len, max_len), split 8:4 around the peak and shifted inside [0, duration]. Then greedy non-overlap.
- `sportscut/pipeline.py`: `run()` has the comment `# event classifiers (later R-003 tasks) label candidates here`.
- `sportscut/evaluate.py:173`: `segments = detect.find_highlights(video)`.
- `tests/fixtures/eval/build.py`: 4 matches of 180 s at 160x90 and 10 fps. The scoreboard is a black box `SCOREBOARD=(2,2,30,14)` with white 3x5 digits drawn at 2x scale. The score changes at `t0+1` for each goal, and the goal roar is +20 dB for about 10 s from t0. Goals: controversy 75; goals_saves 20, 100; mixed 70, 125; cards has none. Booing during a controversy (+12 dB for 30 s) also counts as a sustained roar, so the roar alone is not enough.
- README baseline (T-011): `goal` precision null, recall 0.0; overall f1 0.8421, precision 0.7273, recall 1.0.

## Files
- Create `sportscut/events/__init__.py` (one-line docstring only).
- Create `sportscut/events/scoreboard.py`.
- Modify `sportscut/media.py`: add `sample_top_band`.
- Modify `sportscut/detect.py`: extract `loudness_residual` and `place_window`. No behaviour change.
- Modify `sportscut/pipeline.py`: call `tag_goals`.
- Modify `sportscut/evaluate.py`: call `scoreboard.tag_goals`.
- Create `tests/test_scoreboard.py`. Modify `tests/test_media.py`, `tests/test_pipeline.py`.
- Modify these to stub the new stage: `tests/test_evaluate.py`, `tests/test_t010_acceptance.py`, `tests/test_eval_fixtures_acceptance.py`. Modify `tests/test_t023_acceptance.py` (scope list).
- Modify `README.md` and the related specs (see the last step).
- Do NOT touch `tests/conftest.py`, `pyproject.toml`, `sportscut/export.py`, `sportscut/ranking.py`, `sportscut/models.py`, `tests/fixtures/eval/build.py` or `agent-office/`.

## Interfaces

### sportscut/media.py
```python
BAND_W, BAND_H = 160, 30   # top third of a 160x90 frame
def sample_top_band(path: str | Path) -> np.ndarray  # shape (n, 30, 160), dtype uint8
```
- Check order and error messages follow T-036: `media file not found: <path>` comes before tool lookup. Then `find_tool('ffmpeg')`. On a non-zero exit, raise MediaError `ffmpeg failed for <path>: <detail>`.
- Make one call: `[ffmpeg, '-v', 'error', '-nostdin', '-i', str(p), '-an', '-vf', 'fps=1,scale=160:90,format=gray,crop=160:30:0:0', '-f', 'rawvideo', '-pix_fmt', 'gray', 'pipe:1']`. Use `subprocess.run(capture_output=True, check=False)`.
- Return `np.frombuffer(stdout, np.uint8)[: k*4800].reshape(k, 30, 160)` with `k = len(stdout)//4800` (a trailing partial frame is dropped). Sample i is the frame at about i seconds.

### sportscut/detect.py (refactor only; all existing detect, T-002 and T-012 tests stay green)
```python
def loudness_residual(samples: np.ndarray) -> np.ndarray  # per-second dB minus the 121 s centred rolling median; len = len(samples)//SAMPLE_RATE (may be 0)
def place_window(anchor: float, length: float, duration: float, before: float) -> tuple[float, float]
```
- `place_window` returns `(anchor-before, anchor-before+length)`, shifted right if start < 0 and shifted left if end > duration (the existing rule), then `start = max(start, 0.0)`.
- `find_highlights` computes `residual = loudness_residual(samples)`, then `z = residual/scale`, and `place_window(peak, length, duration, length*PRE_SEC/(PRE_SEC+POST_SEC))`. Its output stays identical.

### sportscut/events/scoreboard.py
Constants (exact values):
`EDGE_MIN=40, MOTION_MAX=2, DILATE=2, MIN_BOARD_PIXELS=12, FLIP_DIFF=40, CHANGE_FRAC=0.03, STABLE_SAMPLES=3, ROAR_DB=6.0, ROAR_SEC=6, MATCH_BEFORE=10.0, MATCH_AFTER=60.0, LEAD_CENTER=45.0, LEAD_LEN=30.0, BOARD_ONLY_SCORE=3.0, CONF_BOARD=0.9, CONF_BOARD_ONLY=0.6, CONF_ROAR_ONLY=0.4`

```python
Box = tuple[int, int, int, int]  # (x, y, w, h) in band pixels
def find_box(frames: np.ndarray) -> Box | None
def score_changes(frames: np.ndarray, box: Box) -> list[float]
def roar(residual: np.ndarray, start: float, end: float) -> tuple[float, int]
def match_goals(segments: list[Segment], residual: np.ndarray, changes: list[float] | None, duration: float, min_len: float = 10, max_len: float = 30) -> list[Segment]
def tag_goals(video: str | Path, segments: list[Segment], min_len: float = 10, max_len: float = 30) -> list[Segment]
```

**find_box(frames)** (frames is (n,h,w) uint8):
1. If n < 2, return None.
2. `motion = median_t |F[t+1]-F[t]|`, computed in int16. `static = motion <= MOTION_MAX`.
3. `ref = median_t F`. `edge[y,x] = max(|ref[y,x+1]-ref[y,x]|, |ref[y+1,x]-ref[y,x]|)`, with missing neighbours counting as 0 difference. `mask = static & (edge >= EDGE_MIN)`.
4. Dilate `mask` with a (2*DILATE+1) square, then label 8-connected components of the dilated mask. Use plain numpy/Python, no scipy.
5. Pick the component holding the most original `mask` pixels. On a tie, take the one whose first pixel comes first in raster order. If that count is < MIN_BOARD_PIXELS, return None.
6. Return the bounding box of the original mask pixels in that component.

**score_changes(frames, box):**
1. Take `B = frames[:, y:y+h, x:x+w]` as int16. For t >= 1, `flip[t]` = the share of box pixels where `|B[t]-B[t-1]| >= FLIP_DIFF`.
2. Scan t from 1. When `flip[t] >= CHANGE_FRAC`, start a run s=t and extend e while `flip[e+1] >= CHANGE_FRAC`.
3. Report `float(s)` only if all of these hold:
   - `e+STABLE_SAMPLES < n`
   - `flip[e+1..e+STABLE_SAMPLES]` are all `< CHANGE_FRAC`
   - the share of pixels where `|B[e+STABLE_SAMPLES]-B[s-1]| >= FLIP_DIFF` is `>= CHANGE_FRAC`
4. Continue scanning at e+1. The returned list is ascending.

**roar(residual, start, end):**
1. Use seconds k in `range(floor(start), ceil(end))` that fall inside `[0, len(residual))`. If there are none, return `(float(start), 0)`.
2. `peak` = the first argmax of `residual[k]`.
3. `run` = length of the maximal run of consecutive seconds containing `peak` where `residual >= ROAR_DB`. It is 0 if `residual[peak] < ROAR_DB`.
4. Return `(peak + 0.5, run)`.

**match_goals(...):** pure. Returns a new list sorted by (start, end) and never mutates its input.
- A segment *qualifies* when `event == 'other'` and its roar run is `>= ROAR_SEC`. Its peak time p comes from `roar()`. Non-`other` segments are never relabelled.
- If `changes is None` (no scoreboard), every qualifying segment becomes `replace(seg, event='goal', event_confidence=CONF_ROAR_ONLY, reason=f'{seg.reason}; sustained roar {run}s')`. No segment is added.
- Otherwise:
  1. A pair (segment i, change c) is eligible when `p_i - MATCH_BEFORE <= c <= p_i + MATCH_AFTER`.
  2. Assign pairs greedily by `(|c - p_i|, c, i)`. Each segment and each change is used at most once.
  3. A matched segment becomes `replace(seg, event='goal', event_confidence=CONF_BOARD, reason=f'{seg.reason}; scoreboard change at {c:.0f}s')`.
  4. For each unmatched change c, in ascending order: set `L = min(max(LEAD_LEN, min_len), max_len)` and `(s, e) = place_window(c - LEAD_CENTER, L, duration, L/2)`. Add `Segment(s, e, BOARD_ONLY_SCORE, f'scoreboard change at {c:.0f}s', 'goal', CONF_BOARD_ONLY)`, but only if `e > s` and it overlaps no segment already in the result. Touching counts as no overlap, as in T-002.

**tag_goals(video, segments, min_len, max_len):**
1. `duration = probe_duration(video)`, `residual = loudness_residual(extract_audio(video))`, `frames = sample_top_band(video)`, `box = find_box(frames)`.
2. `changes = None if box is None else score_changes(frames, box)`.
3. Return `match_goals(list(segments), residual, changes, duration, min_len, max_len)`.
4. MediaError propagates.

### Wiring
- `pipeline.py`: add `from sportscut.events.scoreboard import tag_goals`. Inside the existing try block: `candidates = tag_goals(video, candidates, min_len=min_len, max_len=max_len)` before `select_segments`. Replace the placeholder comment.
- `evaluate.py`: add `from sportscut.events import scoreboard`, then `segments = scoreboard.tag_goals(video, detect.find_highlights(video))`, called through the module attribute so tests can stub it. Validation order is unchanged.

## Steps (test first)
- [ ] **0.** Write down the 'before' numbers: `python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json`. Save the output for the PR. Goal must be precision null, recall 0.0; f1 0.8421.
- [ ] **1.** In `tests/test_media.py`, write the failing tests for `sample_top_band` (AC1). Run `python -m pytest -q tests/test_media.py` and see them fail with ImportError/AttributeError. Implement, then see them pass.
- [ ] **2.** In `tests/test_scoreboard.py`, write the failing tests for `place_window` and `loudness_residual` (AC2). Refactor `detect.py`. Run `python -m pytest -q tests/test_detect.py tests/test_scoreboard.py tests/test_t012_acceptance.py`; all must be green.
- [ ] **3.** Write the failing synthetic-array tests for `find_box` and `score_changes` (AC3, AC4). Implement them.
- [ ] **4.** Write the failing tests for `roar` and `match_goals`, covering the worked examples, scoreboard-only placement and the fallback (AC5–AC8). Implement them.
- [ ] **5.** Write the failing integration tests on the built eval set and burst_video (AC9, AC10). Implement `tag_goals`.
- [ ] **6.** Write the failing pipeline wiring tests (AC11). Wire `pipeline.run`.
- [ ] **7.** Write the failing eval test (AC12). Wire `evaluate.py`. Stub `scoreboard.tag_goals` (identity: `lambda video, segments, **kw: list(segments)`) in the four fake-video tests listed in AC13. Remove `'sportscut/evaluate.py'` from the protected list in `tests/test_t023_acceptance.py::test_ac16_protected_implementation_files_are_unchanged_from_main`.
- [ ] **8.** Add the env-gated budget test (AC14). Run it once with `SPORTSCUT_PERF=1` and note the seconds.
- [ ] **9.** README: after the line `Mục tiêu tiếp theo: recall mỗi sự kiện ≥ 0.9, recall bàn thắng ≥ 0.95, F1 không giảm.` add the line `Kết quả sau T-013 (bàn thắng = bảng tỷ số đổi + tiếng reo kéo dài):` followed by a ```json block holding the exact one-line eval output. Also add one Vietnamese sentence on the rule and the fallback. Update the related specs with `(updated by T-013)`: T-010 design decision line on `detect.find_highlights` and AC9 (the eval now runs `scoreboard.tag_goals` after detection); T-012 design pipeline-order decision (the classifier slot is filled by `tag_goals`); T-023 design AC16 (evaluate.py is no longer protected after T-023); T-036 design AC1 (media also exposes `sample_top_band`). Keep existing markers.
- [ ] **10.** Run `python -m pytest -q`, `PATH=/nonexistent python -m pytest -q` and the eval command. Quote the summary lines and the before/after goal precision/recall in the PR.

## Assumptions
- Frames are scaled to a fixed 160x90 rather than `160:-1`, so every raw frame is exactly 4800 bytes after the top-third crop and no ffprobe call is needed. Non-16:9 video is stretched, which does not matter for change detection.
- Sample i is treated as time i s (ffmpeg fps filter). Change times can be off by up to 1 s, which the 60 s / 10 s matching window absorbs.
- If no scoreboard is found, the system falls back to roar-only goals with confidence 0.4. In that mode, sustained booing can be mislabelled as a goal; this is accepted because the fallback is documented as low confidence.
- Running clocks inside a real scoreboard are not handled specially beyond the static-pixel mask. The synthetic set has no clock. Real-match tuning is a later task.
- Audio is decoded a second time by `tag_goals` (simplicity over a shared cache). The 90-minute budget test proves this is affordable.

## Test plan

- tests/test_media.py: test_sample_top_band_shape_and_values (synthetic_video), test_sample_top_band_single_ffmpeg_call_with_filter (spy on media.subprocess.run, returning 2*4800 zero bytes and asserting shape (2,30,160)), test_sample_top_band_missing_file_without_ffmpeg (PATH=/nonexistent), test_sample_top_band_non_media_file_raises
- tests/test_scoreboard.py (pure numpy, no ffmpeg): test_place_window_examples, test_loudness_residual_lengths, test_find_box_locates_static_box, test_find_box_none_for_noise_black_and_single_frame, test_score_changes_single_change, test_score_changes_ignores_flash, test_score_changes_needs_stable_tail, test_score_changes_two_sample_transition, test_roar_runs, test_match_goals_with_board, test_match_goals_nearest_peak_wins, test_match_goals_keeps_non_other_events, test_match_goals_board_only_placement_and_overlap, test_match_goals_fallback_roar_only, test_match_goals_does_not_mutate_and_sorts
- tests/test_scoreboard.py (ffmpeg, module-scoped fixture `built_eval_set` that loads tests/fixtures/eval/build.py via importlib and calls build_all(tmp_path_factory.mktemp(...)); depends on require_ffmpeg): test_fixture_scoreboard_changes_at_goals, test_tag_goals_labels_each_fixture_goal, test_tag_goals_leaves_burst_video_unchanged, test_eval_goal_recall_and_f1_gate (evaluate_dir on built set), test_readme_t013_result_invariants
- tests/test_pipeline.py: test_run_calls_tag_goals_between_detect_and_select (monkeypatch pipeline.find_highlights / pipeline.tag_goals spies with burst_video), test_run_wraps_tag_goals_media_error, test_run_goals_only_on_fixture (built goals_saves video, events=['goal'] -> 2 goal entries)
- tests/test_scoreboard.py: test_ninety_minute_budget (skipped unless SPORTSCUT_PERF=1; builds a 5400 s lavfi video in tmp, times detection + tag_goals < 600 s)
- Existing test edits: add identity stub `monkeypatch.setattr(scoreboard, 'tag_goals', lambda video, segments, **kw: list(segments))` to the 4 fake-video eval tests listed in AC13; drop 'sportscut/evaluate.py' from the T-023 AC16 protected list
- Commands: `python -m pytest -q`; `PATH=/nonexistent python -m pytest -q`; `python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json` (goal recall >= 0.95, f1 >= 0.8421); `SPORTSCUT_PERF=1 python -m pytest -q tests/test_scoreboard.py -k budget -s`

## Deviations

- The earlier implementation deviated from AC6 by letting `match_goals()` substitute a later tied maximum when `roar()`'s first argmax was not sustained. Tester feedback removed that exception: qualification now uses only the peak and run returned by `roar()`, matching the persistent first-argmax decision.
- `tests/test_eval_fixtures.py::test_eval_all_other_baseline_shape` also stubs `tag_goals` as identity. Although AC13 lists four fake-video tests, this existing real-video oracle likewise asserts the detector-only all-`other` baseline and would otherwise exercise the newly added classifier instead of the behavior it is intended to isolate.
