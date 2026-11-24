# Plan T-014: Tag saves using whistle detection and roar shape

Design: `docs/superpowers/specs/2026-11-23-t-014-tag-saves-using-whistle-detection-and-design.md`.

## Implementation plan

# T-014: Tag saves using whistle detection and roar shape

Request R-003. Depends on T-013 (merged in #38). T-015 (red cards and controversy, the brief's 'task 6') reuses the whistle and stoppage features exported here.

## Goal

Add `sportscut/events/audio_cues.py`. It holds a whistle detector: the share of energy in the 2-4 kHz band against the whole band, per 0.1 s window, lasting at least 0.3 s. It also measures the roar shape of each candidate: rise time, time above baseline and decay. A save is a short, sharp roar (less than 4 s above baseline, rise of 0.5 s or less) with no whistle in the next 5 s and no scoreboard change near it. Only segments that are still `other` after `tag_goals` can become `save`. Everything else stays as it is. `pipeline.run` and `sportscut eval` call the new step right after `tag_goals`. Merge gate: save recall goes up from 0.0 (T-013 README block), goal precision/recall/F1 stay 1.0, overall F1 stays 0.8421, and the 90-minute pass stays under 600 s.

## Current code (read before starting)

- `sportscut/detect.py`: `find_highlights` (per-second RMS dB minus a 121 s rolling median, z >= 3 peaks, 12 s windows [peak-8, peak+4]). `loudness_residual` and `place_window` are public.
- `sportscut/events/scoreboard.py`: `tag_goals(video, segments, min_len, max_len)` loads `probe_duration`, `loudness_residual(extract_audio(video))`, `sample_top_band(video)`, `find_box`, `score_changes`, then calls the pure `match_goals`. Constants `ROAR_DB=6.0`, `MATCH_BEFORE=10.0`, `MATCH_AFTER=60.0`. A missing scoreboard means `changes is None`.
- `sportscut/pipeline.py`: `find_highlights(top=None)` -> `tag_goals(...)` -> `select_segments`, all inside `try/except (MediaError, ValueError) -> PipelineError`.
- `sportscut/evaluate.py:174`: `segments = scoreboard.tag_goals(video, detect.find_highlights(video))` (module attributes, so tests can stub them).
- `sportscut/media.py`: `SAMPLE_RATE = 16_000`. `extract_audio(path)` returns mono float32. It is the only module that runs ffmpeg (T-036), and that does not change.
- `tests/fixtures/eval/build.py` (T-011, do not change): save = +20 dB crowd (200-2000 Hz) roar, a 0.1 s ramp up, flat to t0+2, down by t0+2.5. Whistle = a 1 s 3 kHz tone at amplitude 0.3 at t0 of every red_card/controversy, then quiet crowd (0.005) until t0+12 (red) / t0+36 (controversy). Controversy adds 60-200 Hz booing at 0.08 over [t0+3, t0+33]. Distractors: swell (triangle, 2.5 s rise), chant (2 s fade-in, 2 Hz modulation). T-011 tests guarantee save rise <= 0.2 s and distractor rise >= 1.0 s (first 0.1 s window >= murmur+3 dB -> first window within 2 dB of the peak). Saves: cards 50; goals_saves 55, 140; mixed 15, 160. Scoreboard changes at t0+1 of goals: controversy 76; goals_saves 21, 101; mixed 71, 126.
- README 'Kết quả sau T-013' (the 'before' numbers): f1 0.8421, precision 0.7273, recall 1.0, precision_at_5 0.8889, goal p/r/f1 1.0, save precision null / recall 0.0.
- Tests that feed fake or label-derived segments through `evaluate_dir` stub `scoreboard.tag_goals` as identity (T-013 decision). They now also need `audio_cues.tag_saves` stubbed: tests/test_evaluate.py::test_evaluate_dir_validates_then_aggregates and ::test_evaluate_dir_ignores_hidden_video_metadata, tests/test_t010_acceptance.py::test_t010_ac9_sums_cases_in_sorted_order, tests/test_eval_fixtures_acceptance.py::test_acceptance_eval_oracles, tests/test_eval_fixtures.py::test_eval_all_other_baseline_shape.
- Real-pipeline tests on conftest `burst_video` (black video, 1 s white-noise bursts) assert every event is `other` (test_t010_ac2, test_t012_ac8). The design below keeps them green unchanged, because that video has no scoreboard.

## Design

### `sportscut/events/scoreboard.py` (small refactor, no behaviour change)

```python
def board_changes(video: str | Path) -> list[float] | None:
    """Scoreboard change times in seconds, or None when no scoreboard box is found."""
    frames = sample_top_band(video)
    box = find_box(frames)
    return None if box is None else score_changes(frames, box)
```
`tag_goals` calls `board_changes(video)` instead of its three inline lines. Its output stays byte-identical, and all T-013 tests pass unchanged.

### `sportscut/events/audio_cues.py` (new; numpy + stdlib only; imports `extract_audio`, `SAMPLE_RATE` from `sportscut.media`, `Segment` from `sportscut.models`, and `from sportscut.events import scoreboard`; no subprocess)

Constants (module level, names fixed):
```
WINDOW = SAMPLE_RATE // 10          # 1600 samples = 0.1 s; window i covers [i/10, (i+1)/10) s
CHUNK = 600                         # windows per FFT chunk (bounds memory on 90-min audio)
BASELINE_WINDOWS = 600              # baseline = median over windows [i-600, i+600]
WHISTLE_LOW, WHISTLE_HIGH = 2000.0, 4000.0
WHISTLE_SHARE = 0.5
WHISTLE_MIN_WINDOWS = 3             # 0.3 s
PLAY_LOW, PLAY_HIGH = 300.0, 2000.0 # play/crowd band; above booing, below whistle
QUIET_DB = 6.0
ABOVE_DB = 6.0                      # same value as scoreboard.ROAR_DB
RISE_DB = 3.0
NEAR_PEAK_DB = 2.0
RISE_LOOKBACK = 50                  # windows (5 s) before the peak
SAVE_MAX_SEC = 4.0                  # duration must be < 4.0
SAVE_MAX_RISE = 0.5                 # rise must be <= 0.5
WHISTLE_AFTER = 5.0
BOARD_BEFORE, BOARD_AFTER = 10.0, 30.0
CONF_SAVE = 0.6
```

Public interface:

1. `window_levels(samples: np.ndarray) -> np.ndarray`: n = len(samples) // WINDOW windows (trailing samples dropped). float64 `20*log10(rms + 1e-10)` per window. Empty input gives a float64 array of length 0.
2. `band_share(samples: np.ndarray, low: float, high: float) -> np.ndarray`: per window, apply a Hann window (`np.hanning(WINDOW)`) and take `|rfft|**2` with `rfftfreq(WINDOW, 1/SAMPLE_RATE)`. Return the power in bins with `low <= f <= high` divided by the total power. A window with zero total power gives 0.0. Compute in chunks of CHUNK windows. Length is n as above.
3. `find_whistles(samples: np.ndarray) -> list[tuple[float, float]]`: windows where `band_share(samples, WHISTLE_LOW, WHISTLE_HIGH) >= WHISTLE_SHARE`. Every maximal run of at least WHISTLE_MIN_WINDOWS consecutive windows [i, j) gives `(i / 10, j / 10)`, sorted by time.
4. `stoppage_after(samples: np.ndarray, at: float) -> float`: seconds of continuous low play-band activity starting at `at`. k0 = round(at*10). If k0 >= n, return 0.0. Play level of window k = `10*log10(P_k + 1e-20)`, where P_k is the Hann-windowed power in [PLAY_LOW, PLAY_HIGH], computed only for windows [max(0,k0-600), min(n,k0+601)). baseline = median of those levels. Count windows k = k0, k0+1, ... (< that range's end) while level[k] <= baseline - QUIET_DB, and return count / 10.
5. `class RoarShape(NamedTuple)` with fields `peak, start, end, duration, rise, decay` (all float seconds).
6. `roar_shape(levels: np.ndarray, start: float, end: float) -> RoarShape`:
   - a = max(0, floor(start*10 + 1e-6)), b = min(len(levels), ceil(end*10 - 1e-6)). If a >= b, return `RoarShape(start, start, start, 0.0, 0.0, 0.0)` (floats).
   - p = a + first argmax of levels[a:b]. base = median(levels[max(0,p-600) : p+601]).
   - If levels[p] < base + ABOVE_DB, return `RoarShape(p/10, p/10, p/10, 0.0, 0.0, 0.0)`.
   - [l, r) = maximal run of windows with level >= base + ABOVE_DB that contains p.
   - s0 = first k in [max(0, p-RISE_LOOKBACK), p] with level >= base + RISE_DB. The run need not be contiguous: like T-011, the first qualifying window counts, so a modulated chant still shows its slow fade-in.
   - q = first k in [s0, p] with level >= levels[p] - NEAR_PEAK_DB. q2 = last k in [p, r) with level >= levels[p] - NEAR_PEAK_DB.
   - Return `RoarShape(peak=p/10, start=l/10, end=r/10, duration=(r-l)/10, rise=(q-s0)/10, decay=(r-1-q2)/10)`.
7. `match_saves(segments: list[Segment], levels: np.ndarray, whistles: list[tuple[float, float]], changes: list[float] | None) -> list[Segment]` (pure):
   - If `changes is None` (no scoreboard), return `list(segments)` unchanged.
   - Otherwise each segment with `event == 'other'` gets `shape = roar_shape(levels, seg.start, seg.end)`. It becomes a save when all of these hold:
     - `0 < shape.duration < SAVE_MAX_SEC`
     - `shape.rise <= SAVE_MAX_RISE`
     - no whistle `(ws, we)` has `ws < shape.end + WHISTLE_AFTER and we > shape.start`
     - no change c has `shape.peak - BOARD_BEFORE <= c <= shape.peak + BOARD_AFTER`
   - A save is `dataclasses.replace(seg, event='save', event_confidence=CONF_SAVE, reason=f'{seg.reason}; sharp roar {shape.duration:.1f}s')`.
   - Same length and order as the input. The input is not mutated. Non-`other` segments are returned unchanged.
8. `tag_saves(video: str | Path, segments: list[Segment]) -> list[Segment]`: `changes = scoreboard.board_changes(video)`. If it is None, return `list(segments)` without decoding audio. Otherwise `samples = extract_audio(video)` and return `match_saves(list(segments), window_levels(samples), find_whistles(samples), changes)`.

### Wiring

- `sportscut/pipeline.py`: `from sportscut.events.audio_cues import tag_saves`. Right after the `tag_goals` call, inside the same try block: `candidates = tag_saves(video, candidates)`.
- `sportscut/evaluate.py`: `from sportscut.events import audio_cues, scoreboard`. The case line becomes `segments = audio_cues.tag_saves(video, scoreboard.tag_goals(video, detect.find_highlights(video)))`.
- The 5 tests listed above add exactly one line each, `monkeypatch.setattr(audio_cues, 'tag_saves', lambda video, segments, **kw: list(segments))` (plus the import). No other assertion changes.

### Docs

- README, eval section: after the T-013 paragraph, add the line `Kết quả sau T-014 (cứu thua = tiếng reo ngắn, bật lên nhanh, không có tiếng còi trong 5 giây sau và bảng tỷ số không đổi):`, then a ```json block holding the exact one-line output of `python -m sportscut eval tests/fixtures/eval --json` from this branch, then a paragraph: `Các ngưỡng của T-014 (còi 2–4 kHz kéo dài ≥ 0,3 giây, tiếng reo < 4 giây, thời gian bật ≤ 0,5 giây) chỉ được chỉnh trên bộ video tổng hợp. Muốn chỉnh cho trận thật cần bộ nhãn data/eval/ do PO gán. Khi video không có bảng tỷ số, SportsCut không gắn nhãn cứu thua.`
- `docs/superpowers/specs/2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md`: on the two decision lines about `pipeline.run` / `evaluate_dir` calling `tag_goals` and about eval tests stubbing `tag_goals`, append ` (updated by T-014: tag_saves runs right after tag_goals in pipeline.run and evaluate_dir; stubbed eval tests also stub audio_cues.tag_saves)`.

## Implementation steps (TDD: write each test, watch it fail for the right reason, then code)

1. Read T-011, T-013 designs, DECISIONS.md, `scoreboard.py`, `pipeline.py`, `evaluate.py`, `tests/fixtures/eval/build.py`.
2. tests/test_audio_cues.py: `window_levels` and `band_share` tests (AC1). Create audio_cues.py with the constants and both functions.
3. `find_whistles` test (AC2) -> code.
4. `stoppage_after` test (AC3) -> code.
5. `roar_shape` tests on the AC4 levels fixture -> code.
6. `match_saves` tests (AC5, AC6) -> code.
7. `board_changes` + `tag_saves` tests (AC7) -> extract `board_changes` in scoreboard.py, write `tag_saves`. Run `python -m pytest -q tests/test_scoreboard.py tests/test_t013_acceptance.py` (must stay green).
8. Pipeline spy test (AC8) -> wire pipeline.py.
9. Eval spy test (AC9) -> wire evaluate.py, add the 5 stub lines, run the full suite.
10. Built-set tests (AC10, AC11, AC12) using a module-scoped fixture that builds the set into tmp (copy the `built_eval_set` pattern from tests/test_scoreboard.py).
11. Opt-in budget test (AC13). Run it once with SPORTSCUT_PERF=1 and keep the printed line for the PR.
12. Build the fixtures, run the eval CLI, paste the line into README with the T-013 spec note, and add the README invariant test (AC14).
13. Final verification (AC15).

## Verify

```bash
python -m pytest -q
PATH=/nonexistent python -m pytest -q        # no new failures vs main; ffmpeg tests skip
python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json
# per_event.save.recall >= 0.8 and precision >= 0.8; goal precision/recall/f1 == 1.0;
# f1 == 0.8421, precision == 0.7273, recall == 1.0, precision_at_5 == 0.8889
SPORTSCUT_PERF=1 python -m pytest -q tests/test_audio_cues.py -k budget -s   # prints 'budget: <s>s for 5400s', < 600
```

PR body: per-event table before (README 'Kết quả sau T-013') and after (the new README block), plus the budget line.

## Assumptions

- Thresholds are tuned on the synthetic set only. Real-match tuning needs the PO's labelled `data/eval/` (README note).
- A save needs a visible scoreboard. Without one, 'no scoreboard change' cannot be checked, so nothing is tagged `save`. This is conservative, and it keeps the no-scoreboard `burst_video` outputs `other`.
- The scoreboard-change exclusion window is [peak-10 s, peak+30 s]. T-013's goal window (+60 s) would wrongly exclude two synthetic saves whose next goal's change comes 44-56 s later. 30 s still covers the usual broadcast score-graphic delay.
- Audio and frames are decoded again in `tag_saves` (simplicity over a shared cache, as in T-013). The opt-in budget test proves the cost.

## Test plan

- tests/test_audio_cues.py (Developer, pure numpy): test_window_levels_constant_zero_and_empty (AC1)
- tests/test_audio_cues.py: test_band_share_tone_offband_silence_and_white_noise (AC1)
- tests/test_audio_cues.py: test_find_whistles_keeps_runs_of_at_least_three_windows (AC2: [(2.0,3.0),(7.0,7.3)]; noise and zeros give [])
- tests/test_audio_cues.py: test_stoppage_after_counts_quiet_play_band_ignoring_low_booing (AC3)
- tests/test_audio_cues.py: test_roar_shape_save_like_swell_like_long_below_and_empty (AC4 fixture as a module-level helper `_levels()`)
- tests/test_audio_cues.py: test_roar_shape_rise_uses_first_window_in_five_second_lookback (AC4 levels[455] variant)
- tests/test_audio_cues.py: test_match_saves_tags_only_short_sharp_other_roars (AC5, including non-mutation, order and the None-changes case)
- tests/test_audio_cues.py: parametrized test_match_saves_whistle_and_board_exclusions (AC6, 8 cases)
- tests/test_audio_cues.py: test_tag_saves_without_board_skips_audio (AC7, monkeypatch scoreboard.board_changes -> None and audio_cues.extract_audio -> raise; plus real burst_video identity)
- tests/test_audio_cues.py: test_tag_saves_with_board_decodes_once (AC7, board_changes stubbed to [], spy extract_audio)
- tests/test_audio_cues.py: test_audio_cues_does_not_import_subprocess (AC7, ast walk like tests/test_pipeline.py)
- tests/test_audio_cues.py: test_pipeline_calls_tag_saves_after_tag_goals_and_wraps_media_error (AC8, spies on pipeline.find_highlights/tag_goals/tag_saves/select_segments, burst_video)
- tests/test_audio_cues.py: test_evaluate_dir_runs_tag_saves_on_tag_goals_output (AC9, fake case dir with an empty video.mp4, stub detect.find_highlights and scoreboard.tag_goals, spy audio_cues.tag_saves)
- tests/test_audio_cues.py (ffmpeg, module fixture `built_eval_set` = build_all(tmp) via importlib like tests/test_scoreboard.py): test_board_changes_matches_inline_detection (AC7), test_fixture_whistles_and_stoppages (AC10), test_tag_saves_labels_every_fixture_save_and_nothing_else_scored (AC11), test_eval_save_gate_and_unchanged_goal_and_overall_metrics (AC12, including the CLI subprocess comparison)
- tests/test_audio_cues.py: test_ninety_minute_budget (AC13, opt-in via SPORTSCUT_PERF=1)
- tests/test_audio_cues.py: test_readme_records_t014_invariants_and_t013_spec_note (AC14)
- Existing tests edited (one stub line + import each, AC9): tests/test_evaluate.py (2 tests), tests/test_t010_acceptance.py::test_t010_ac9_sums_cases_in_sorted_order, tests/test_eval_fixtures_acceptance.py::test_acceptance_eval_oracles, tests/test_eval_fixtures.py::test_eval_all_other_baseline_shape
- Tester (independent, from the ACs): tests/test_t014_acceptance.py covering AC1-AC15 with its own fixtures (its own tmp build of the eval set), and checks that each new unit test fails if its threshold is changed (e.g. SAVE_MAX_SEC 4.0 -> 4.1 makes AC5 L a save)
- Commands: `python -m pytest -q`; `PATH=/nonexistent python -m pytest -q`; `python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json` (save recall >= 0.8, save precision >= 0.8, goal p/r/f1 1.0, f1 0.8421); `SPORTSCUT_PERF=1 python -m pytest -q tests/test_audio_cues.py -k budget -s` (< 600 s)
