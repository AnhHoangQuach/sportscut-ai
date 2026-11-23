# Plan T-011: Build the synthetic event eval set and record the baseline

Design: `docs/superpowers/specs/2026-11-23-t-011-build-the-synthetic-event-eval-set-design.md`.

## Implementation plan

# T-011: Build the synthetic event eval set and record the baseline

Request R-003. Builds on T-010 (`sportscut/evaluate.py`, `sportscut eval DIR --json`) and copies the layout of the T-029 player eval set (`tests/fixtures/eval_player/build.py`).

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:test-driven-development for each step. Steps use checkbox (`- [ ]`) syntax.

## Goal
We need a small, deterministic, labelled synthetic set at `tests/fixtures/eval/`. Later R-003 classifier tasks will score themselves against it. Their targets are per-event recall >= 0.9 and goal recall >= 0.95, and they must not lower F1. This task builds the set, proves that every cue is really present in the generated media, and records the baseline of the current detector (every segment `event='other'`) in the README. **No production code under `sportscut/` changes.**

The eval command is:
```bash
python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json
```

## Repo facts this relies on (read, do not change)
- `sportscut/evaluate.py:evaluate_dir(root)` scans each subdirectory that has `labels.json`. The subdirectory must hold exactly one non-dot-prefixed `.mp4/.mkv/.mov`. Non-directories such as `build.py`, and subdirectories without labels such as `__pycache__/`, are ignored. It calls `detect.find_highlights(video)` with defaults (top=10, 12 s windows: 8 s before and 4 s after a 1 s RMS peak with z >= 3 against a 120 s median baseline). A label matches a segment when IoU >= 0.3 or the segment contains the label.
- `labels.json` is a JSON list of `{"start": float, "end": float, "type": str}` in seconds.
- `.gitignore` already ignores `*.mp4` and `*.wav`, so `video.mp4` is never committed.
- `tests/conftest.py` has the session fixture `require_ffmpeg` (skip message 'ffmpeg and ffprobe are required on PATH').
- `sportscut.media.extract_audio(path)` returns mono float32 at 16 kHz.

## Files
- Create `tests/fixtures/eval/build.py`, the generator (numpy + stdlib only; it must not import `sportscut`).
- Create `tests/fixtures/eval/<match>/labels.json` for the 4 matches below. These are committed and written by the generator.
- Create `tests/test_eval_fixtures.py`.
- Change `README.md`: add a new section; nothing else changes.

## Format
- Video: 160x90 rgb24 frames piped to ffmpeg at FPS = 10, encoded `-c:v mpeg4 -q:v 2 -pix_fmt yuv420p`.
- Audio: mono, AUDIO_RATE = 16000, written as 16-bit PCM WAV (stdlib `wave`) into a `tempfile.TemporaryDirectory()` and encoded `-c:a aac -b:a 64k -ar 16000 -ac 1`.
- Every match lasts exactly 180.0 s (`-t 180`).
- Output is `<match>/video.mp4`, written to `<match>/.video.tmp.mp4` first and then moved with `os.replace`. The dot prefix keeps a crashed build from producing a second 'video' that the eval would count.

## Picture (render_frame)
- **Pitch:** fill (40,140,60), with columns where `(x // 16) % 2 == 1` filled (36,128,54).
- **Ball:** a white (255,255,255) disk of radius 2 at the position given by the play clock `c`:
  - `x = 80 + 60*sin(0.37c) + 10*sin(1.3c)`
  - `y = 52 + 24*sin(0.23c + 1) + 8*sin(0.9c)`
  - both rounded. The ball always stays inside x 10..150, y 20..84, so it never touches the scoreboard.
- **Play clock:** `play_clock(name, t)` = t minus the frozen time before t. Frozen spans are red_card [t0, t0+12] and controversy [t0, t0+36]. During a frozen span the ball does not move.
- **Replay:** inside a replay window [r0, r1] that shows source [s0, s1], the base picture is the base picture at `s0 + (t - r0)`.
  - goal: r = [t0+13, t0+18), s = [t0-3, t0+2)
  - controversy: r = [t0+20, t0+26), s = [t0-6, t0)
- **Red close-up:** red_card only, for t in [t0+4, t0+8). The whole frame is filled (200,20,20) with a centred 24x32 (w x h) block of (230,190,160).
- **Scoreboard:** drawn last, on every frame.
  - The box covers x 2..31, y 2..15 (`SCOREBOARD = (2, 2, 30, 14)` as x, y, w, h) and is filled black.
  - Digits use the 3x5 FONT from eval_player/build.py, scaled x2 (6x10 px), white. The home digit's top-left is at (5,4) and the away digit's at (21,4). A dash fills x 14..17, y 8..9 in white.
  - The score is `score_at(name, t)`: (home, away), starting at (0,0). It increments for a goal of that team from t >= t0+1.0 onward, and is live during replays (it shows the new score).

## Sound (audio_track)
The generator uses `rng = np.random.default_rng(SEEDS[name])` with `SEEDS = {name: 1101 + index}`, where index is the match's position in MATCHES order.

Two unit-RMS band-noise streams cover the whole match: `crowd` (200-2000 Hz) and `boo` (60-200 Hz). Each is white noise from rng, passed through an FFT band mask, and normalised to RMS 1.

The mix is `crowd_env(t)*crowd + boo_env(t)*boo + whistle`, clipped to [-1, 1]. All levels are RMS:
- **murmur:** crowd_env = 0.02 by default.
- **goal:** a roar where crowd_env rises linearly from 0.02 to 0.2 over [t0, t0+0.5], holds, then falls back to 0.02 over [t0+9, t0+10].
- **save:** crowd_env rises to 0.2 over [t0, t0+0.1], holds until t0+2.0, then falls back to 0.02 by t0+2.5.
- **whistle:** red_card and controversy, at [t0, t0+1.0]. A 3000 Hz sine with peak 0.3 and 20 ms linear fade in and out.
- **quiet stoppage, red_card:** crowd_env = 0.005 on [t0+1, t0+12].
- **long stoppage, controversy:** crowd_env = 0.005 on [t0+1, t0+36]. boo_env = 0.08 on [t0+3, t0+33] (30 s) with 0.5 s linear ramps inside that span, and 0 elsewhere.
- **distractor swell:** crowd_env rises linearly from 0.02 to 0.08 over [t0, t0+2.5] and back over [t0+2.5, t0+5].
- **distractor chant:** crowd_env = 0.08*(0.6 + 0.4*sin(2*pi*2*(t-t0))) on [t0, t0+6].

Distractors have no whistle, no scoreboard change, no replay and no red close-up, and are not labelled.

## Labels per event (t0 = onset)
| type | start | end |
| --- | --- | --- |
| goal | t0-2 | t0+10 |
| save | t0-4 | t0+4 |
| red_card | t0-2 | t0+8 |
| controversy | t0-4 | t0+6 |

- `match_labels(name)` returns these as `[{"start": float, "end": float, "type": str}]`, sorted by start, with distractors excluded.
- labels.json content is `json.dumps(match_labels(name), indent=1) + "\n"`.
- **Footprints**, used only for the spacing test: goal [t0-3, t0+18], save [t0-4, t0+4], red_card [t0-2, t0+12], controversy [t0-6, t0+36], swell [t0, t0+5], chant [t0, t0+6].

## Matches (exact; MATCHES dict in this order)
Each event is (kind, t0) or, for goals, (kind, t0, team).
```python
MATCHES = {
  "cards":       {"duration": 180.0, "events": [("red_card", 20), ("save", 50), ("controversy", 75), ("swell", 130), ("red_card", 155)]},
  "controversy": {"duration": 180.0, "events": [("controversy", 20), ("goal", 75, "away"), ("chant", 110), ("controversy", 130)]},
  "goals_saves": {"duration": 180.0, "events": [("goal", 20, "home"), ("save", 55), ("swell", 75), ("goal", 100, "away"), ("save", 140), ("chant", 160)]},
  "mixed":       {"duration": 180.0, "events": [("save", 15), ("red_card", 40), ("goal", 70, "home"), ("swell", 105), ("goal", 125, "home"), ("save", 160)]},
}
```
Totals: 5 goals, 5 saves, 3 red cards, 3 controversies (16 labels) and 5 distractors.

## build.py interface
```python
HERE: Path; W, H, FPS = 160, 90, 10; AUDIO_RATE = 16000; SCOREBOARD = (2, 2, 30, 14)
MATCHES: dict; SEEDS: dict[str, int]; DISTRACTORS = ("swell", "chant")
def match_labels(name: str) -> list[dict]
def footprints(name: str) -> list[tuple[str, float, float]]   # (kind, start, end), sorted
def score_at(name: str, t: float) -> tuple[int, int]
def play_clock(name: str, t: float) -> float
def render_frame(name: str, t: float) -> np.ndarray            # (H, W, 3) uint8
def audio_track(name: str) -> np.ndarray                       # float32, len == duration*AUDIO_RATE
def build_all(out_dir=HERE, force=False) -> list[Path]         # the video paths, MATCHES order
if __name__ == "__main__": build_all(force="--force" in sys.argv)
```

Idempotent build:
- For each match, write labels.json only if it is missing or its content differs.
- Skip encoding when `video.mp4` exists, the labels did not change, and `force` is false.
- If ffmpeg fails, remove the temp file and raise `RuntimeError(stderr)`.

## Steps (test first)
- [ ] 1. Write `tests/test_eval_fixtures.py`. It loads build.py with `importlib.util.spec_from_file_location` (same pattern as tests/test_eval_player_fixtures.py) and starts with the pure tests: committed labels, coverage and spacing. Run them and watch them fail because build.py is missing. Then write the MATCHES, match_labels and footprints parts of build.py and generate the 4 labels.json files.
- [ ] 2. Add the picture tests (scoreboard, red close-up, replay, motion), watch them fail, then implement play_clock, score_at and render_frame.
- [ ] 3. Add the audio tests, watch them fail, then implement audio_track.
- [ ] 4. Add the ffmpeg tests (module-scope `eval_set` fixture that calls `build.build_all(tmp_dir)`, using `require_ffmpeg`): format, decoded cues, idempotency and force. Watch them fail, then implement build_all.
- [ ] 5. Add the eval tests: oracle, all-other oracle and CLI structure. These should pass without production changes; if they don't, the labels are wrong.
- [ ] 6. Run `python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json`, then paste the exact one-line output into the README. Add the README test first and watch it fail before pasting.
- [ ] 7. Run `python -m pytest -q` and `git status --short`. Confirm that no `.mp4` or `.wav` is staged and that only the files listed above changed.

## README section (Vietnamese, after the eval-player section)
Heading: `## Highlight theo sự kiện: đo độ chính xác (eval)`. It holds:
- the two commands;
- the layout `<thư-mục>/<trận>/{video.mp4,labels.json}` and the label format `[{"start":18.0,"end":30.0,"type":"goal"}]`;
- one line per cue (goal, save, red_card, controversy, distractor);
- the sentence `Baseline đo trong T-011 (mọi đoạn đều là \`other\`):`, directly followed by a ```json fenced block containing the exact one-line output;
- the line `Mục tiêu tiếp theo: recall mỗi sự kiện ≥ 0.9, recall bàn thắng ≥ 0.95, F1 không giảm.`

## Verify
```bash
python -m pytest -q tests/test_eval_fixtures.py
python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json
python tests/fixtures/eval/build.py   # second run: encodes nothing, finishes in < 2 s
python -m pytest -q
git status --short                    # no video.mp4 / wav listed
```
There is no minimum score; this task records the baseline. The README values must be exactly what the command printed on the Developer's machine.

## Assumptions
- The 4 matches x 180 s at 160x90/10 fps keep the build plus eval in CI well under a minute.
- Labels cover the moment a viewer wants to see, not the whole stoppage or replay. Replay and stoppage cues sit next to the label so a classifier can use them as evidence.
- The scoreboard is a single-digit `H-A` box. No goal takes a score above 9.
- If decoded AAC at 64k loses the whistle share asserted in the tests, the Developer may raise only the audio bitrate and record that in the README section. The test thresholds stay as they are.

## Test plan

- Unit, `tests/test_eval_fixtures.py::test_committed_labels_match_generator`: compare each committed labels.json byte for byte with match_labels and check the key set, type set and sorting (AC2).
- Unit, `test_set_coverage_and_spacing`: check the per-type label counts (5/5/3/3), 5 distractors, 180 s durations, footprints within [10, 170] and >= 12 s gaps (AC2, AC3).
- Unit, `test_untracked_video`: `git ls-files tests/fixtures/eval` lists only build.py and the 4 labels.json files; skip if git is unavailable (AC2).
- Unit, `test_scoreboard_changes_only_at_goals`: sample every 0.1 s, count SCOREBOARD crop changes and their times, and check score_at values (AC4).
- Unit, `test_red_closeup_only_for_red_cards`: compute the red share on 0.1 s samples inside and outside the windows (AC5).
- Unit, `test_replays_repeat_source_and_play_moves`: check replay equality outside the box, motion in play, and stillness during frozen spans (AC6).
- Unit, `test_audio_level_cues`: compute 0.1 s RMS dB from audio_track and check goal >= 8 s roar, save 2-3 s, red-card quiet, distractor peak and slow rise vs. sharp save (AC7).
- Unit, `test_audio_spectral_cues`: compute FFT band shares per whole second for the whistle 2.8-3.2 kHz and booing < 220 Hz, inside and outside their spans (AC8).
- Integration (ffmpeg; module-scope `eval_set` fixture = build.build_all(tmp_path_factory.mktemp('eval'))), `test_encoded_format_ffprobe`: check codecs, size, fps, audio channels and rate, duration, and that no temp file is left (AC9).
- Integration, `test_decoded_cues_survive_encoding`: decode frames with ffmpeg -ss for the scoreboard at goal t0+3 vs. t0-1 and red_card t0+6; read whistle share via sportscut.media.extract_audio (AC9).
- Integration, `test_build_is_idempotent` and `test_force_and_changed_labels_rebuild`: compare mtime_ns and bytes; in a separate tmp dir, delete one labels.json and check that it is rewritten and that match is re-encoded (AC10).
- Integration, `test_eval_oracle_matches_all_labels` and `test_eval_all_other_baseline_shape`: monkeypatch `sportscut.detect.find_highlights` and call evaluate_dir (AC11).
- Integration, `test_eval_cli_real_detector_json`: run main(['eval', dir, '--json']) with capsys, then check one line, the key set, per_match order and predictions > 0 (AC12).
- Unit, `test_readme_baseline`: extract the first ```json block after 'Baseline đo trong T-011' from README.md, parse it and check the AC13 invariants; also check the command string is present (AC13).
- Tester acceptance: run the Verify commands, time the second build run, diff the README JSON against a fresh eval run, run `PATH=/nonexistent python -m pytest -q tests/test_eval_fixtures.py` to confirm skips, and mutate one cue (e.g. change the goal roar to 5 s, or remove the scoreboard increment) to confirm the matching test fails (AC7, AC4, AC14).
