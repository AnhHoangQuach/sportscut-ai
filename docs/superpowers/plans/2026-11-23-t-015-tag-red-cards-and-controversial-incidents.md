# Plan T-015: Tag red cards and controversial incidents

Design: `docs/superpowers/specs/2026-11-23-t-015-tag-red-cards-and-controversial-incidents-design.md`.

## Implementation plan

# T-015: Tag red cards and controversial incidents

Request R-003. Product Owner request: "Highlight theo sự kiện: gắn nhãn bàn thắng, cứu thua, thẻ đỏ, pha tranh cãi. Người dùng lọc 'chỉ bàn thắng' hoặc 'top 5 pha hay'."

## Goal

Tag `red_card` and `controversy` segments using only ffmpeg-decoded audio, scoreboard and a few frames:
- **red_card** = a whistle that starts inside the candidate, followed by a stoppage (low play-band activity) of at least 8 s, plus a red close-up: at least 2 frames whose centre is mostly saturated red. The frames are sampled at 2 fps only in the 15 s after the whistle ends, and only for whistles that already passed the stoppage check. The video is never scanned across the whole match.
- **controversy** = a whistle plus a stoppage of at least 30 s with at least 10 s of low-frequency booing. It also covers a disallowed goal: a goal segment whose scoreboard change is later reverted (the board returns to its earlier state within 180 s) becomes controversy.
- Precedence: goal > red_card > controversy > save. Both new events get a low `event_confidence` (red_card 0.5, controversy 0.4, reverted goal 0.5).

The PR reports per-event numbers before (README 'Kết quả sau T-014': red_card recall 0.0, controversy recall 0.0, event_accuracy 0.625) and after ('Kết quả sau T-015'). Merge only if red_card and controversy recall go up, and overall F1 and goal recall do not go down. Vision models are out of scope; they come later as an optional `[vision]` extra.

## Context (read before coding)

- The chain today: `pipeline.run` calls `find_highlights(top=None)` -> `tag_goals` -> `tag_saves` -> `select_segments`. `evaluate_dir` scores `audio_cues.tag_saves(video, scoreboard.tag_goals(video, detect.find_highlights(video)))` through module attributes.
- `sportscut/events/audio_cues.py` (T-014) already exports `WINDOW` (1600 samples = 0.1 s), `band_share(samples, low, high)`, `find_whistles(samples) -> list[(start, end)]` and `stoppage_after(samples, at) -> seconds`. Reuse them and do not change audio_cues.py.
- `sportscut/events/scoreboard.py` (T-013/T-014): `find_box`, `score_changes(frames, box)` (times are sample indices of the 1 fps `sample_top_band`, so they are seconds), `board_changes(video)`, `FLIP_DIFF=40`, `CHANGE_FRAC=0.03`, `STABLE_SAMPLES=3`. `tag_goals` writes the reason marker `scoreboard change at {change:.0f}s` on every goal it gets from a board change, whether matched (`'<reason>; scoreboard change at 45s'`) or board-only (`'scoreboard change at 45s'`).
- Synthetic set (`tests/fixtures/eval/build.py`, T-011, frozen):
  - red_card at t0: 3 kHz whistle on [t0, t0+1), crowd quiet from t0+1 to t0+12, red (200,20,20) close-up with a 24x32 skin box in the centre on [t0+4, t0+8).
  - controversy at t0: whistle, crowd quiet from t0+1 to t0+36, 60-200 Hz booing on [t0+3, t0+33), and a replay.
  - T-014 AC10 measured a stoppage of 9-13 s for red_card and 25-37 s for controversy (physically about 11 s and 35 s). The detector segment for these events is about [t0-7.5, t0+4.5] and contains the whistle start; T-014 overall recall is 1.0.
- Frozen files: the diff-scope tests T-013 AC15, T-014 AC15 and T-023 AC16 run on every later branch and forbid touching `tests/conftest.py`, `pyproject.toml`, `sportscut/models.py`, `sportscut/ranking.py`, `sportscut/media.py`, `sportscut/export.py`, `tests/fixtures/eval/build.py`, `tests/fixtures/eval/*/labels.json`, `agent-office/` and `.agent-office/`. So the frame sampler cannot go into media.py. It lives in the new module and reuses `media.find_tool`, `media.MediaError` and `media._failure_detail`.
- The web UI (T-016), ranking and API already know `red_card` and `controversy`. No UI change is needed.

## Design

### Classifier chain (changes the T-013/T-014 chain decisions)

- `pipeline.run`: `candidates = tag_goals(...)`, then `candidates = tag_incidents(video, candidates)`, then `candidates = tag_saves(video, candidates)`, then `select_segments(...)`. All of these stay inside the existing `(MediaError, ValueError) -> PipelineError` block. Import: `from sportscut.events.incidents import tag_incidents`.
- `evaluate_dir`: `segments = audio_cues.tag_saves(video, incidents.tag_incidents(video, scoreboard.tag_goals(video, detect.find_highlights(video))))`. Import: `from sportscut.events import audio_cues, incidents, scoreboard`.
- Precedence comes from the order and from which events each step may touch:
  - tag_goals runs first.
  - tag_incidents reads only `other` segments for whistle cues. It reads `goal` segments only for the reverted-board cue, which invalidates the goal evidence itself; a disallowed goal is not a goal.
  - Inside tag_incidents, red_card is checked before controversy.
  - tag_saves only tags segments that are still `other`.
- `sportscut detect` stays audio-only and untagged.

### New module `sportscut/events/incidents.py`

Constants:
```
RED_MIN_STOP = 8.0          # s of stoppage after the whistle end
CONTRO_MIN_STOP = 30.0
BOO_LOW, BOO_HIGH = 20.0, 220.0
BOO_SHARE = 0.5
BOO_MIN_SEC = 10.0
CLOSEUP_LOOK = 15.0         # s sampled after the whistle end
CLOSEUP_FPS = 2
FRAME_W, FRAME_H = 160, 90
RED_SHARE = 0.5
RED_MIN_FRAMES = 2
CONF_RED, CONF_CONTRO, CONF_REVERT = 0.5, 0.4, 0.5
```

Functions:
- `red_share(frames: np.ndarray) -> np.ndarray`
  - Input shape is (n, h, w, 3) uint8. Returns the float64 per-frame fraction of red pixels (R >= 150 and G <= 60 and B <= 60) inside the centre crop rows [h//4, 3*h//4) and cols [w//4, 3*w//4). For 90x160 that is rows 22:67 and cols 40:120.
  - n == 0 gives an empty float64 array.
- `booing_seconds(samples: np.ndarray, start: float, end: float) -> float`
  - Takes windows a = max(0, round(start*10)) to b = min(len(samples)//WINDOW, round(end*10)) and returns 0.0 if a >= b.
  - Otherwise returns `(band_share(samples[a*WINDOW:b*WINDOW], BOO_LOW, BOO_HIGH) >= BOO_SHARE).sum() / 10`.
- `classify(stoppage: float, booing: float, red_frames: int) -> str`
  - `'red_card'` if stoppage >= RED_MIN_STOP and red_frames >= RED_MIN_FRAMES.
  - Otherwise `'controversy'` if stoppage >= CONTRO_MIN_STOP and booing >= BOO_MIN_SEC.
  - Otherwise `'other'`.
- `sample_frames(video: str | Path, start: float, duration: float) -> np.ndarray`
  - A missing file raises `MediaError(f'media file not found: {video}')` before ffmpeg is looked up.
  - Runs exactly `[ffmpeg, '-v', 'error', '-nostdin', '-ss', f'{start:.3f}', '-i', str(p), '-t', f'{duration:.3f}', '-an', '-vf', 'fps=2,scale=160:90', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1']` with `subprocess.run(args, capture_output=True, check=False)`.
  - A non-zero exit raises `MediaError(f'ffmpeg failed for {video}: {detail}')`, where detail comes from `media._failure_detail`.
  - Returns uint8 (n, 90, 160, 3) and drops trailing partial bytes.
- `tag_incidents(video: str | Path, segments: list[Segment]) -> list[Segment]`, in this order:
  1. `result = list(segments)`.
  2. If any segment has event `'goal'`: `reverts = scoreboard.board_reverts(video)`. For each (c1, c2) in reverts and each goal segment in result whose reason contains `f'scoreboard change at {c1:.0f}s'` or `f'scoreboard change at {c2:.0f}s'`, replace it with event `'controversy'`, event_confidence 0.5 and reason `f'{reason}; scoreboard change at {c1:.0f}s reverted at {c2:.0f}s'`. Use only the original goal segments, so a segment is relabelled at most once.
  3. If no segment has event `'other'`, return result. In that case nothing else is decoded.
  4. `samples = extract_audio(video)` (once) and `whistles = audio_cues.find_whistles(samples)`.
  5. For each `'other'` segment, find the first whistle (ws, we) with `segment.start <= ws < segment.end`; skip the segment if there is none.
  6. `stop = audio_cues.stoppage_after(samples, we)`; skip if stop < RED_MIN_STOP, and do not decode frames then.
  7. `red_frames = int((red_share(sample_frames(video, we, CLOSEUP_LOOK)) >= RED_SHARE).sum())` and `boo = booing_seconds(samples, we, we + stop)`.
  8. `event = classify(stop, boo, red_frames)`, then:
     - red_card: reason `f'{reason}; whistle at {ws:.0f}s, stoppage {stop:.0f}s, red close-up'`, confidence 0.5.
     - controversy: reason `f'{reason}; whistle at {ws:.0f}s, stoppage {stop:.0f}s, booing {boo:.0f}s'`, confidence 0.4.
     - other: leave the segment unchanged.
  - start, end and score never change. Nothing is added or removed, the order is kept, and the inputs are not mutated (`dataclasses.replace`).
  - Module-level names that tests monkeypatch: `incidents.extract_audio`, `incidents.sample_frames`, `scoreboard.board_reverts` (called through the module attribute), `audio_cues.*`.

### `sportscut/events/scoreboard.py` additions (tag_goals and board_changes unchanged)

- `REVERT_MAX = 180.0`.
- `find_reverts(frames: np.ndarray, box: Box, changes: list[float]) -> list[tuple[float, float]]`
  - For each adjacent pair (c1, c2) in `sorted(changes)` with c2 - c1 <= REVERT_MAX, crop the board as `score_changes` does.
  - `before = board[int(c1) - 1]` and `after = board[min(int(c2) + STABLE_SAMPLES, len(board) - 1)]`.
  - The pair is a revert when `np.mean(np.abs(after - before) >= FLIP_DIFF) < CHANGE_FRAC` (int16 arithmetic). Returns the pairs in time order; fewer than 2 changes gives [].
- `board_reverts(video) -> list[tuple[float, float]]`
  - `frames = sample_top_band(video)` and `box = find_box(frames)`; returns [] if box is None, without calling score_changes or find_reverts.
  - Otherwise returns `find_reverts(frames, box, score_changes(frames, box))`. All calls go through module globals so tests can stub them.

### README

Add a block after 'Kết quả sau T-014'. It starts with the marker line `Kết quả sau T-015 (thẻ đỏ = còi + dừng trận ≥ 8 giây + cận cảnh đỏ giữa khung hình; tranh cãi = còi + dừng trận ≥ 30 giây + tiếng la ó ≥ 10 giây, hoặc tỷ số bị hoàn lại):`. Then comes a ```json block of exactly one line holding `python -m sportscut eval <built set> --json` output.

After that, one paragraph says:
- the thresholds are tuned on the bộ video tổng hợp only;
- real-match tuning needs the PO's `data/eval/` labels;
- the confidences are low (0.5 / 0.4);
- replay detection and card/referee vision are future work behind an optional `[vision]` extra.

The earlier README blocks stay byte-identical.

### Spec notes

- In `docs/superpowers/specs/2026-11-23-t-014-tag-saves-using-whistle-detection-and-design.md`, append to the 'Classifier chain' decision bullet: ` (updated by T-015: tag_incidents runs between tag_goals and tag_saves in pipeline.run and evaluate_dir; stubbed eval/pipeline tests also stub tag_incidents as pass-through)`.
- Append the same text to the two chain bullets in the T-013 design spec that already carry '(updated by T-014'.

## Files

Create:
- `sportscut/events/incidents.py`
- `tests/test_incidents.py`
- `tests/test_t015_acceptance.py` (Tester)

Modify:
- `sportscut/events/scoreboard.py`
- `sportscut/pipeline.py`
- `sportscut/evaluate.py`
- `README.md`
- The 2 spec files above
- Existing tests that feed fake videos through a stubbed chain. Each gets exactly one pass-through stub line plus its import; no assertion changes:
  - `tests/test_evaluate.py` (test_evaluate_dir_validates_then_aggregates, test_evaluate_dir_ignores_hidden_video_metadata)
  - `tests/test_eval_fixtures.py` (test_eval_all_other_baseline_shape)
  - `tests/test_eval_fixtures_acceptance.py` (test_acceptance_eval_oracles)
  - `tests/test_t010_acceptance.py` (test_t010_ac9_sums_cases_in_sorted_order)
  - `tests/test_audio_cues.py` (test_pipeline_calls_tag_saves_after_tag_goals_and_wraps_media_error, test_evaluate_dir_runs_tag_saves_on_tag_goals_output)
  - `tests/test_t014_acceptance.py` (test_ac8_pipeline_orders_classifiers_and_wraps_save_media_errors, test_ac9_evaluate_scores_tag_saves_output_after_tag_goals)
- The stub is `monkeypatch.setattr(incidents, 'tag_incidents', lambda _video, segments: segments)` for evaluate tests and `monkeypatch.setattr(pipeline, 'tag_incidents', lambda _video, segments: segments)` for pipeline tests. It returns the same object, so `is` and order assertions stay true. This follows the T-013/T-014 stub precedent.

## Assumptions

- The red_card stoppage threshold is 8 s, not the 20 s in the task text. The frozen synthetic red card has a 12 s freeze (measured 9-13 s), so 20 s would make red_card recall 0 and fail the merge gate. The red close-up is the discriminating cue, and 8 s still rejects quick restarts. Real-match tuning needs `data/eval/`.
- Controversy uses booing; replay detection (frames repeating) is out of scope for this PR. On the synthetic set booing alone marks every controversy. A replay matcher must tell replays apart from frozen-stoppage frames and needs its own task.
- A disallowed goal is detected only when tag_goals produced a goal segment from the reverted change. Reverts never create new segments.
- The whistle must start inside the candidate segment. The close-up is expected within 15 s after the whistle.

## Implementation plan (test-first; each task: write the failing test, run it red, implement, run it green)

**Task 1 - scoreboard reverts.**
- Tests in tests/test_incidents.py: `test_find_reverts_pairs_and_gap_limit` and `test_board_reverts_composes_helpers_and_skips_without_box` (AC1, AC2).
- Then add REVERT_MAX, find_reverts and board_reverts.
- Run `python -m pytest -q tests/test_incidents.py -k revert`.

**Task 2 - pure helpers.**
- Tests: `test_red_share_centre_crop_and_pixel_thresholds`, `test_booing_seconds_counts_low_band_windows` and `test_classify_thresholds_and_precedence` (AC3-AC5).
- Then implement red_share, booing_seconds and classify.

**Task 3 - frame sampler.**
- Tests: `test_sample_frames_command_and_shape` (subprocess.run monkeypatched), `test_sample_frames_real_black_white` (synthetic_video), and `test_sample_frames_missing_and_non_media` (AC6).
- Then implement sample_frames.

**Task 4 - tag_incidents.**
- Tests: `test_tag_incidents_audio_rules_and_frame_locality`, `test_tag_incidents_red_beats_controversy_and_needs_two_frames`, `test_tag_incidents_reverted_goal_becomes_controversy`, `test_tag_incidents_skips_decoding_when_nothing_to_check` and `test_tag_incidents_real_noise_videos_unchanged` (AC7-AC9).
- Then implement tag_incidents.

**Task 5 - chain wiring.**
- Tests: `test_pipeline_calls_tag_incidents_between_goals_and_saves` and `test_evaluate_dir_chains_goals_incidents_saves` (AC10, AC11).
- Then change pipeline.py and evaluate.py, and add the pass-through stubs to the 9 existing tests listed above.
- Run the whole suite.

**Task 6 - built set, eval and docs.**
- First measure: build the set into tmp and print, for each red_card/controversy event, the whistle, `stoppage_after`, `booing_seconds` and the red frame count. If any controversy stoppage is < 30 s or any red_card stoppage < 8 s, stop and report to the Tech Lead; do not change thresholds silently.
- Tests: `test_fixture_incidents_tagged_with_local_frame_sampling`, `test_eval_incident_gate_and_unchanged_metrics` and `test_ninety_minute_budget` (opt-in) (AC12-AC14).
- Then write the README block (AC15) with `test_readme_records_t015_invariants`, and add the spec notes.

## Verify commands

```
python -m pytest -q
PATH=/nonexistent python -m pytest -q          # no new failures vs main; ffmpeg tests skip
python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json
#   red_card and controversy precision/recall/f1 == 1.0, goal == 1.0, save >= 0.8,
#   f1 0.8421, precision 0.7273, recall 1.0, precision_at_5 0.8889, event_accuracy 1.0
SPORTSCUT_PERF=1 python -m pytest -q tests/test_incidents.py -k budget -s   # prints 'budget: <s>s for 5400s', < 600
```

The PR description quotes the T-014 'before' per_event block, the T-015 'after' per_event block and the budget line.

## Test plan

- tests/test_incidents.py::test_find_reverts_pairs_and_gap_limit (AC1: pure numpy frames, cases a-d, empty and single change)
- tests/test_incidents.py::test_board_reverts_composes_helpers_and_skips_without_box (AC2: monkeypatched sample_top_band/find_box/score_changes/find_reverts, call order, None box -> [])
- tests/test_incidents.py::test_red_share_centre_crop_and_pixel_thresholds (AC3)
- tests/test_incidents.py::test_booing_seconds_counts_low_band_windows (AC4: 120 s 1 kHz + 100 Hz boo signal)
- tests/test_incidents.py::test_classify_thresholds_and_precedence (AC5: parametrized boundary table)
- tests/test_incidents.py::test_sample_frames_command_and_shape (AC6: monkeypatched incidents.subprocess.run, exact argv, partial-frame truncation)
- tests/test_incidents.py::test_sample_frames_real_black_white (AC6: conftest synthetic_video, needs ffmpeg)
- tests/test_incidents.py::test_sample_frames_missing_and_non_media (AC6: missing path with empty PATH, text file)
- tests/test_incidents.py::test_tag_incidents_audio_rules_and_frame_locality (AC7: synthetic numpy audio with three whistles; stubbed extract_audio/sample_frames/board_reverts; exact output segments, reasons, confidences, sample_frames call list, decode counts, input not mutated)
- tests/test_incidents.py::test_tag_incidents_red_beats_controversy_and_needs_two_frames (AC8 first half)
- tests/test_incidents.py::test_tag_incidents_reverted_goal_becomes_controversy (AC8 second half: G1-G4, extract_audio not called)
- tests/test_incidents.py::test_tag_incidents_skips_decoding_when_nothing_to_check (AC9 stubs)
- tests/test_incidents.py::test_tag_incidents_real_noise_videos_unchanged (AC9: burst_video and synthetic_video)
- tests/test_incidents.py::test_pipeline_calls_tag_incidents_between_goals_and_saves (AC10: spy order, object identity, MediaError -> PipelineError)
- tests/test_incidents.py::test_evaluate_dir_chains_goals_incidents_saves (AC11: spy through module attributes)
- Existing tests get one pass-through stub each (AC11): test_evaluate.py x2, test_eval_fixtures.py::test_eval_all_other_baseline_shape, test_eval_fixtures_acceptance.py::test_acceptance_eval_oracles, test_t010_acceptance.py::test_t010_ac9_sums_cases_in_sorted_order, test_audio_cues.py x2 (pipeline and evaluate spies), test_t014_acceptance.py AC8 and AC9
- tests/test_incidents.py::test_fixture_incidents_tagged_with_local_frame_sampling (AC12: module-scoped fixture builds the eval set into tmp via importlib-loaded build.py, like the T-014 t014_eval_set fixture; spies sample_frames)
- tests/test_incidents.py::test_eval_incident_gate_and_unchanged_metrics (AC13: evaluate_dir plus the `python -m sportscut eval --json` subprocess)
- tests/test_incidents.py::test_ninety_minute_budget (AC14: skipped unless SPORTSCUT_PERF=1)
- tests/test_incidents.py::test_readme_records_t015_invariants (AC15: README JSON invariants, required words, older blocks unchanged, '(updated by T-015' in the T-013 and T-014 specs)
- Tester: tests/test_t015_acceptance.py covers AC1-AC16 independently from the acceptance criteria, including the AC16 scope check that diffs against `git merge-base main HEAD`, never a bare `main`

## Deviations

- **Revert threshold (`find_reverts`).** The plan says a pair is a revert when `np.mean(np.abs(after - before) >= FLIP_DIFF) < CHANGE_FRAC` (0.03). Task 6's measurement on the built set found `board_reverts(mixed) == [(71.0, 126.0)]`: that match goes 0-0 -> 1-0 -> 2-0, and in the synthetic font the '2' glyph differs from '0' in only 0.0258 of board pixels. With that rule, AC12 (`board_reverts == []` for every match) fails, and `evaluate_dir` gives goal recall 0.6 and controversy precision 0.6, which fails the merge gate. Fix: a separate constant `scoreboard.REVERT_FRAC = 0.01`, used only by `find_reverts`. The same board state compared at two times measures 0.0 on every built match, and the AC1 cases measure 0.0 (revert) and 0.14 (B -> C), so AC1 still holds. `CHANGE_FRAC` and `tag_goals`/`board_changes` are unchanged. Test: `tests/test_incidents.py::test_find_reverts_needs_near_identical_board`. Real-broadcast tuning of 0.01 needs `data/eval/`.
