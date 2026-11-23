# Plan T-029: Build the player-touch eval: synthetic labelled clips, `sportscut eval-player --json`, and a baseline

Design: `docs/superpowers/specs/2026-11-23-t-029-build-the-player-touch-eval-synthetic-design.md`.

## Implementation plan

# T-029: Player-touch eval (synthetic labelled clips, `sportscut eval-player --json`, stub baseline)

## Context
R-006 goal: `sportscut player match.mp4 --team red --number 10 --out DIR` writes a reel of every ball touch by one player. Our rule is to measure first, so this task builds only the **ruler**:
1. `sportscut/player.py`: the query/touch data model and a stub detector that returns no touches. This gives the baseline, F1 = 0.
2. `tests/fixtures/eval_player/build.py`: 4 deterministic synthetic clips with committed `labels.json`.
3. `sportscut eval-player DIR [--json]`: prints the touch metrics.
4. The baseline numbers, recorded in README.

Later tasks raise the numbers against this eval:
- T-031 detects touches by any player (`touch_f1_any` >= 0.9).
- T-032 assigns the team (`team_accuracy` >= 0.95).
- T-033 reads jersey numbers (`f1` >= 0.85).
- T-030 adds the `sportscut player` reel CLI.

None of that logic belongs in this task.

**What changed from the earlier T-029 spec.** T-001 was split into T-035 (packaging, CLI, Segment) and T-036 (ffmpeg media helpers, `require_ffmpeg` fixture), and both are merged on `main`. This spec keeps the earlier T-029 design and step order. It only re-grounds them on the real base:
- The Step 0 check is new.
- The only media error type is `MediaError` (there is no `FFmpegNotFoundError`).
- The test fixture is `require_ffmpeg` (there is no `ffmpeg` fixture).
- The encoder is the built-in `mpeg4`, not libx264 (T-036 decision).
- Tests build clips only in pytest temp dirs (T-036 decision).

## Step 0: precondition (run first, before writing anything)
```bash
test -f pyproject.toml && grep -q "def main" sportscut/cli.py && grep -q "def probe_duration" sportscut/media.py && grep -q "class MediaError" sportscut/media.py && grep -q "def require_ffmpeg" tests/conftest.py && echo READY
```
If `READY` is not printed:
- report `BLOCKED: T-029 needs T-035/T-036 (pyproject.toml, sportscut/cli.py, sportscut/media.py, tests/conftest.py) on the base branch.`
- change no files
- re-create nothing

On the current `main` this command prints READY (checked by the Tech Lead on 2026-11-23).

What the base provides (do not modify these files, except `cli.py` as described below):
- `sportscut/cli.py`: `main(argv: list[str] | None = None) -> int`. It is argparse with only `--version` (it prints `sportscut 0.1.0` and exits 0). With no args it prints help and returns 0.
- `sportscut/media.py`: `MediaError(RuntimeError)`, `find_tool(name)` and `probe_duration(path) -> float`. `probe_duration` raises `MediaError` for a missing file or a missing tool. `extract_audio` also exists but is not used here.
- `tests/conftest.py`: the session fixture `require_ffmpeg` (skips with `ffmpeg and ffprobe are required on PATH`) and `synthetic_video`.
- `pyproject.toml`: numpy is a runtime dependency. pytest has `pythonpath=["."]` and `testpaths=["tests"]`.
- `.gitignore` already ignores `*.mp4` and `data/`. Do not edit it.

## Files to touch
| File | Change |
|---|---|
| `sportscut/player.py` | **new**: `TEAM_NAMES`, `normalize_team`, `PlayerQuery`, `Touch`, `detect_touches` (stub), `find_touches` |
| `sportscut/eval_player.py` | **new**: `TOLERANCE`, `load_labels`, `match_times`, `prf`, `score_clip`, `metrics`, `evaluate_dir` |
| `sportscut/cli.py` | add the `eval-player DIR [--json]` subcommand |
| `tests/fixtures/eval_player/build.py` | **new**: standalone clip and label generator |
| `tests/fixtures/eval_player/{short_passes,dribble,near_miss,number_hidden}/labels.json` | **new, committed**: written by build.py |
| `tests/fixtures/eval_player/<case>/clip.mp4` | generated and git-ignored by `*.mp4`. Never commit it. |
| `tests/test_player.py`, `tests/test_eval_player.py`, `tests/test_eval_player_fixtures.py`, `tests/test_cli.py` | tests (`test_cli.py`: append only) |
| `README.md` | a short section in Vietnamese (step 8) |
| `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md` | add one Assumptions bullet about the eval-player exception (step 8) |

Do not touch:
- `agent-office/`, `.github/`, `AGENTS.md`, `CLAUDE.md`, `.gitignore`, `pyproject.toml`
- `sportscut/media.py`, `sportscut/models.py`, `tests/conftest.py`

Size target: about 250 lines of production code (player.py, eval_player.py and the cli.py change). build.py should stay under about 250 lines, and should be data-driven rather than one function per case. The labels.json files are not counted.

## Interfaces

### sportscut/player.py
```python
TEAM_NAMES = ("black", "blue", "green", "orange", "pink", "purple", "red", "sky", "white", "yellow")

def normalize_team(team: str) -> str:
    """strip + lower. Valid if in TEAM_NAMES or matches ^#[0-9a-f]{6}$, else
    ValueError(f"unknown team colour {team!r}: use one of {', '.join(TEAM_NAMES)} or #rrggbb")."""

@dataclass(frozen=True)
class PlayerQuery:
    team: str     # normalized in __post_init__ via object.__setattr__
    number: int   # 1..99; must be a real int (reject bool, float, str) -> ValueError

@dataclass(frozen=True)
class Touch:
    t: float                                   # seconds from video start, >= 0
    team: str | None                           # normalized team, None = unknown
    number: int | None                         # jersey number, None = unread
    confidence: float                          # [0, 1]
    bbox: tuple[int, int, int, int] | None     # toucher box x, y, w, h in source pixels
    def to_dict(self) -> dict  # {"t", "team", "number", "confidence", "bbox"}; native float/int/str/None, bbox as list or None

def detect_touches(video: str | os.PathLike[str]) -> list[Touch]:
    """Every ball touch by any player. Baseline stub: return []."""

def find_touches(video: str | os.PathLike[str], query: PlayerQuery) -> list[Touch]:
    return [x for x in detect_touches(video) if x.team == query.team and x.number == query.number]
```
Validation:
- `Touch.__post_init__` raises `ValueError` if t < 0 or confidence is outside [0, 1].
- When `team` is not None, `Touch` normalizes it with `normalize_team`.
- `to_dict` casts with `float()` and `int()`, so numpy scalars can still go through `json.dumps`.

Why `detect_touches` exists: `touch_f1_any`, `team_accuracy` and `id_accuracy` measure all touches, not just the queried player's. The eval calls `detect_touches` and `find_touches` separately, because T-033 reads numbers only around the queried team's touches, so find_touches may later stop being a plain filter.

### Label format: `<DIR>/<case>/labels.json`, next to `<case>/clip.mp4`
```json
{"players": [{"team": "blue", "number": 4}, {"team": "red", "number": 10}],
 "touches": [{"t": 3.0, "team": "red", "number": 10}, {"t": 6.0, "team": "red", "number": 11}]}
```
- `touches` (required): every touch by every player in the clip.
  - `t` is a number >= 0, in seconds from the clip start. A bool is rejected.
  - `team` and `number` follow the `PlayerQuery` rules.
  - The list does not need to be sorted.
- `players` (optional): extra players the eval must also query even if they never touch the ball, such as the near-miss defender. This is how false positives get measured.
- **Queries** for a clip are the unique union of `players` and the authors of `touches`, sorted by (team, number).
- Replays: a touch shown again in a replay is labelled again (dedup is out of scope).
- Real matches go in `data/eval_player/<name>/{clip.mp4,labels.json}` (git-ignored), in the same format.

### sportscut/eval_player.py
Import the modules, not the names: `from sportscut import media, player`, then call `player.detect_touches(...)`, `player.find_touches(...)` and `media.probe_duration(...)`. That way tests can monkeypatch `sportscut.player.*`.
```python
TOLERANCE = 0.5

def load_labels(path) -> tuple[list[tuple[float, PlayerQuery]], list[PlayerQuery]]:
    """(touches as (t, query) sorted by t, queries sorted by (team, number))."""
```
`load_labels` raises `ValueError` with a message that contains the file path and, where one applies, the entry index (`touches[3]`). It does so when:
- the top level is not an object
- `touches` is missing or not a list
- `players` is present but not a list
- an entry is not an object
- `t` is missing, not a number, a bool, or negative
- the team or number is invalid (wrap the PlayerQuery ValueError)

Invalid JSON is also a ValueError, since `json.JSONDecodeError` is a subclass.

```python
def match_times(pred: Sequence[float], truth: Sequence[float], tol: float = TOLERANCE) -> list[tuple[int, int]]:
    """One-to-one matching, |p - l| <= tol + 1e-9 (inclusive). Returns (pred_index, truth_index) pairs
    using ORIGINAL indices."""
```
Algorithm:
1. Sort the indices of each list by value.
2. Walk both lists with two pointers:
   - if within tol: record the pair and advance both
   - elif p < l: advance pred
   - else: advance truth

This gives the maximum matching in 1-D. A nearest-first greedy does not, and the AC6 cases test exactly that.

```python
def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    """precision, recall, f1; any zero denominator -> 0.0."""

def score_clip(touches, queries, detected: list[Touch], found: dict[PlayerQuery, list[Touch]]) -> dict:
    """Raw counts: tp, fp, fn (queried players, summed over queries), any_tp, any_fp, any_fn, team_hits, id_hits."""
```
How `score_clip` counts:
- **Any-player touches:** match `[d.t for d in detected]` against all label times. `any_tp` is the number of pairs, `any_fp = len(detected) - any_tp`, and `any_fn = len(labels) - any_tp`.
- **team_hits:** pairs where `detected.team == label.team`.
- **id_hits:** pairs where both team and number are equal.
- **Per query q:** match `[x.t for x in found[q]]` against the label times of q only, then add up tp, fp and fn over all queries.

```python
def metrics(counts: dict, seconds: float, query_minutes: float) -> dict:
    """f1, precision, recall (from tp/fp/fn); touch_f1_any (f1 from any_*);
    team_accuracy = team_hits/any_tp and id_accuracy = id_hits/any_tp, or None when any_tp == 0;
    seconds_per_min = seconds/query_minutes (0.0 if query_minutes == 0). Floats rounded to 4 decimals."""

def evaluate_dir(path) -> dict
```
`evaluate_dir(path)`:
- **Cases** are the sorted subdirectories that contain `labels.json`.
- **Errors** (each raises `ValueError`):
  - path is not a directory
  - no cases were found
  - a case has no `clip.mp4`. The message must say to run `python tests/fixtures/eval_player/build.py` for the synthetic set.
  - Labels and clip presence for every case are checked before any video is processed.
- **Per case:**
  1. `duration = media.probe_duration(clip)`
  2. `detected = player.detect_touches(clip)`
  3. For each query, time `player.find_touches(clip, q)` with `time.perf_counter()` and add it to `seconds`.
  4. `query_minutes = duration * len(queries) / 60`.

  `seconds_per_min` is therefore the cost of one `sportscut player` run per minute of video.
- **Report:** pool (micro-average) the raw counts, seconds and query_minutes over all cases, then apply `metrics`. Top-level keys are exactly `f1, precision, recall, touch_f1_any, team_accuracy, id_accuracy, seconds_per_min, per_clip`. per_clip is sorted by clip name, and each entry is `{"clip", "duration", "touches", "queries"}` plus the same 7 metric keys. `touches` and `queries` are counts.

Example baseline output (one line with --json):
```json
{"f1": 0.0, "precision": 0.0, "recall": 0.0, "touch_f1_any": 0.0, "team_accuracy": null, "id_accuracy": null, "seconds_per_min": 0.0, "per_clip": [{"clip": "dribble", "duration": 20.0, "touches": 13, "queries": 4, "f1": 0.0, ...}, ...]}
```

### CLI (sportscut/cli.py)
- `sportscut eval-player DIR --json` prints the report as exactly one line of compact JSON (`json.dumps(report)`) on stdout and returns 0.
- Without `--json` it prints `json.dumps(report, indent=2)`. There is no other format.
- On `ValueError`, `OSError` or `media.MediaError`, it prints `sportscut eval-player: error: <msg>` to stderr and returns 2.
- Add `subparsers = parser.add_subparsers(dest="command")`. If another merged task already created a subparsers object, reuse it.
- Keep `--version` and the no-args behaviour (print help, return 0) exactly as they are, so the existing `tests/test_cli.py` tests pass unchanged.

### tests/fixtures/eval_player/build.py
The script is standalone: numpy, json, os, subprocess, sys and pathlib only. It must **not** import `sportscut`, so the fixtures cannot depend on the code they measure.

**Constants**
- `HERE = Path(__file__).resolve().parent`
- `W, H, FPS = 640, 360, 25`
- `SHIRT_W, SHIRT_H = 16, 32`
- `BALL_R = 4`
- `TEAM_RGB = {"red": (200, 30, 30), "blue": (30, 60, 200)}`
- Pitch: RGB (40,140,60), with vertical stripes of (36,128,54) every 64 px.
- Ball: a filled white (255,255,255) disk.
- Digits:
  - a 3x5 bitmap `FONT` for 0-9, scaled x2, so each digit is 6x10 px
  - a 2 px gap between digits
  - drawn white, starting 6 px below the box top
  - centred horizontally, including one-digit numbers

**Data-driven cases**
```python
CASES: dict[str, dict] = {
  "short_passes": {
    "duration": 24.0,
    "players": {("red", 7): [(t, cx, cy), ...], ...},   # shirt-centre keyframes; numpy.interp, clamped at the ends
    "touches": [(t, team, number), ...],                 # the ball is at the toucher's feet at t
    "ball_end": (t, x, y),                               # where the ball rolls after the last touch, then stays
    "hidden": [(team, number, t0, t1), ...],             # digits not drawn while t0 <= t <= t1
  }, ...}

def player_box(name, team, number, t) -> tuple[int, int, int, int]  # (round(cx-8), round(cy-16), 16, 32)
def feet(name, team, number, t) -> tuple[float, float]              # (cx, cy + SHIRT_H/2 + BALL_R + 1)
def ball_pos(name, t) -> tuple[float, float]
def case_labels(name) -> dict          # {"players": [all players as {team, number}, sorted], "touches": [{"t": round(t, 2), "team", "number"}, ...]}
def render_frame(name, t) -> np.ndarray  # (H, W, 3) uint8
def build_all(out_dir: Path = HERE, force: bool = False) -> list[Path]  # writes out_dir/<case>/{labels.json,clip.mp4}; returns the clip paths
if __name__ == "__main__": build_all(force="--force" in sys.argv)
```
**`ball_pos` rules**
- Before the first touch, the ball rests at the first toucher's feet, taken at the first touch time.
- Between touch k and touch k+1, the ball moves linearly from feet(k at t_k) to feet(k+1 at t_k+1).
- After the last touch, it moves linearly to `ball_end` and then stays there.

**Draw order:** pitch, then players (shirt, then digits unless hidden), then the ball last, so the ball is always visible.

**Encoding** (built-in encoder, following T-036; libx264 is not needed)
- Pipe rgb24 frames for `t = i / FPS`, with `i in range(round(duration * FPS))`, into:
  `ffmpeg -nostdin -v error -f rawvideo -pix_fmt rgb24 -s 640x360 -r 25 -i pipe:0 -c:v mpeg4 -q:v 2 -pix_fmt yuv420p -an -y <case>/clip.tmp.mp4`
- Then `os.replace` it to `<case>/clip.mp4`.
- If ffmpeg fails, raise `RuntimeError` with its stderr.

**Idempotence**
- `labels.json` is written as `json.dumps(labels, indent=1) + "\n"`, and only when its content differs.
- `clip.mp4` is re-rendered only when it is missing, when labels.json changed in this run, or when `force=True`.
- No randomness anywhere.

**Script rules (every case)**
- Touch times are multiples of 0.2 s, so they fall exactly on frames.
- Consecutive touches in a case are >= 1.0 s apart, so a +/-0.5 s window is unambiguous.
- The first touch is at >= 1.0 s and the last at <= duration - 2 s.
- Duration is between 20 and 40 s.

**Cases.** The keyframes are starting points. Tune positions freely, but the AC properties must hold.
1. `short_passes` (24 s)
   - Players: red 7, red 10, red 9; blue 4, blue 5; also blue 10, a players-only query whose number equals red 10's.
   - Touches: R7 2.0, R10 4.0, R10 5.0, R9 7.0, R9 8.2, B4 10.0, B4 11.0, B5 13.0, B5 14.0, R7 16.4, R7 17.4, R10 19.0 (12 touches).
   - Each receiver controls the ball, moves about 20 px, then passes, so that is 2 touches.
2. `dribble` (20 s)
   - Red 10 runs from x≈100 to x≈520, touching at 2.0, 3.2, …, 14.0 (11 touches).
   - His keyframes sit at the touch times, with cy alternating +14 and -14 px around a base line. His feet, and so the ball, zig-zag, and the direction changes at every touch.
   - Then R10 passes at 15.2 and red 11 receives at 17.0 (13 touches in total).
   - Blue 6 and blue 3 chase, but stay >= 30 px from the ball and never touch it. They are listed in `players`.
3. `near_miss` (20 s)
   - Touches: R10 3.0, R11 6.0, R11 8.0, R10 11.0, R10 14.0, R8 16.0 (6 touches).
   - The 3.0→6.0 pass passes 6–14 px from blue 4's box at about 4.4 s.
   - The 8.0→11.0 pass passes 6–14 px from blue 2's box at about 9.6 s.
   - Distances are measured from the ball centre to the nearest point of the box.
   - The ball moves in a straight line at constant speed throughout both passes.
   - Blue 4 and blue 2 are listed in `players` and have zero touches.
4. `number_hidden` (20 s)
   - Touches: R5 2.0, B8 4.0, B8 5.2, B3 7.0, B8 9.0, R5 11.0, B8 14.0, B3 16.0 (8 touches).
   - `hidden` is [t-1, t+1] for every B8 touch: the number is turned away. Everywhere else, blue 8's number is visible.

Totals: 39 touches and at least 17 queries.

## Ordered steps (TDD: write each test, watch it fail for the right reason, then write the minimal code)
0. Run the Step 0 precondition and quote `READY`.
1. **player.py.** Write `tests/test_player.py`, see it fail with ModuleNotFoundError, then implement.
2. **`load_labels`.** Tests with tmp_path JSON files, then implement in eval_player.py.
3. **`match_times` and `prf`.** Hand-computed tests, then implement.
4. **`score_clip` and `metrics`.** Pure tests built from Touch objects, then implement.
5. **build.py.** Write `tests/test_eval_player_fixtures.py` first.
   - Load build.py with `importlib.util.spec_from_file_location` through a module-level helper.
   - Pure tests need no ffmpeg: labels consistency, timing rules, ball physics, near miss, hidden number.
   - Add a module-scoped fixture `eval_player_set(require_ffmpeg, tmp_path_factory)` that calls `build.build_all(tmp_dir)` and returns the dir. Tests never build into the repo.
   - Implement build.py. Then run `python tests/fixtures/eval_player/build.py` once to write the 4 committed `labels.json` files (and the git-ignored clips). Add only the labels.json files to git, never the mp4 files.
6. **`evaluate_dir`.**
   - Error tests need no ffmpeg.
   - The oracle, shift and baseline tests run on `eval_player_set`.
   - Then implement.
7. **CLI.** Tests call `main([...])` and read capsys. Then add the subcommand.
8. **Docs.**
   - Run `python -m sportscut eval-player tests/fixtures/eval_player --json`.
   - Add to README a section `## Theo dõi cầu thủ: đo độ chính xác (eval-player)` with:
     - the build and eval commands
     - the label format and the `data/eval_player/<name>/{clip.mp4,labels.json}` layout
     - the matching rule (±0.5 s, one-to-one)
     - the baseline JSON line copied from this session's actual run
     - the targets: touch_f1_any ≥ 0.9 (T-031), team_accuracy ≥ 0.95 (T-032), F1 ≥ 0.85 (T-033)
   - Append one bullet to the Assumptions/decisions list of `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`: `T-029: exception for the player-touch eval set — tests/fixtures/eval_player/build.py may write git-ignored clip.mp4 files inside tests/fixtures/eval_player/ for the eval command; pytest still builds only in temp dirs and no media is committed.`
9. Run the full suite and the verify commands. Quote the summary lines.

## Verify (run all, quote output)
```bash
python -m pytest -q                                          # all pass (quote the summary line)
python tests/fixtures/eval_player/build.py                   # builds 4 clips
ls -l --time-style=full-iso tests/fixtures/eval_player/*/clip.mp4 || stat tests/fixtures/eval_player/*/clip.mp4
python tests/fixtures/eval_player/build.py                   # 2nd run: mtimes unchanged, git diff on labels.json empty
python -m sportscut eval-player tests/fixtures/eval_player --json   # one JSON line; f1 0.0, touch_f1_any 0.0, team_accuracy null, id_accuracy null
git status --short                                           # only the listed files; no .mp4
git ls-files '*.mp4'                                         # prints nothing
```
The console-script form `sportscut eval-player ...` is equivalent once the package is installed. This task does not touch any other eval gate.

## Assumptions
- T-029 depends on T-035 and T-036 (the split of T-001), and both are merged. Step 0 enforces this.
- A player is identified by normalized shirt colour (a name or #rrggbb) plus number 1-99. Labels and queries use the same normalization, and team equality is plain string equality.
- Each case uses the fixed video name `clip.mp4`.
- Metrics are pooled (micro-averaged) across clips and queries. With zero predictions, precision is 0.0, so the stub baseline is all zeros, not null.
- `team_accuracy` and `id_accuracy` are measured on any-player touches that matched a label, from `detect_touches`. They are null when nothing matched.
- `seconds_per_min` times only `find_touches`, which is the cost of one player reel. Video duration comes from ffprobe through `media.probe_duration`.
- The synthetic clips have no audio. They use the built-in mpeg4 encoder.
- For the eval command, the clips are generated into the git-ignored fixture dir inside the repo. pytest builds them only in temp dirs.
- build.py has its own team colours and does not import sportscut, so fixture generation never depends on the code under test.
- Close-ups, camera cuts and replays are not in the synthetic set (YAGNI). Real-broadcast behaviour is measured later on `data/eval_player/`.

## Test plan

- tests/test_player.py::test_normalize_team_names_and_hex: ' RED ' gives 'red', '#FF0000' gives '#ff0000'; 'maroon', '#ff00' and '' raise ValueError with the valid names in the message.
- tests/test_player.py::test_player_query_number_validation (parametrized): 0, 100, '10', 10.0 and True raise ValueError; 1 and 99 are accepted; the query is hashable and works as a dict key.
- tests/test_player.py::test_touch_to_dict_and_validation: exact dict; json.dumps with numpy scalars; None fields allowed; t=-1 or confidence=1.5 raise ValueError.
- tests/test_player.py::test_detect_touches_stub_and_find_filters: detect_touches('x.mp4') == []. With a monkeypatched detect_touches returning 3 touches (red 10, red 7, blue 10), find_touches(_, PlayerQuery('red', 10)) returns only the red 10 touch.
- tests/test_eval_player.py::test_load_labels_valid: unsorted touches plus a players-only player give sorted touches, and queries that include the players-only player; also works without a players key.
- tests/test_eval_player.py::test_load_labels_rejects (parametrized, tmp_path files): top-level list, missing touches, players not a list, t missing, t='1', t=True, t=-1, team 'maroon', number 0. Each ValueError message contains the file name, plus the entry index for entry errors.
- tests/test_eval_player.py::test_match_times_cases (parametrized): the AC6 cases plus empty inputs, including original indices with unsorted inputs.
- tests/test_eval_player.py::test_prf: (0,0,0) gives zeros; (2,1,1) gives 2/3 for all three; (3,0,0) gives (1.0, 1.0, 1.0).
- tests/test_eval_player.py::test_score_clip_counts: 2 labelled players and 1 players-only player, with hand-built detected/found lists. Asserts tp/fp/fn, the any_* counts, team_hits and id_hits, and that a touch found for player A within 0.5 s of player B's label is an FP for A.
- tests/test_eval_player.py::test_metrics_none_and_rounding: any_tp=0 gives team/id accuracy None; 1/3 values round to 0.3333; query_minutes=0 gives seconds_per_min 0.0.
- tests/test_eval_player.py::test_evaluate_dir_errors (no ffmpeg needed): a missing dir, an empty tmp dir, and a case with only labels.json each raise ValueError; the last message contains 'build.py'.
- tests/test_eval_player_fixtures.py, pure tests (no ffmpeg; build.py loaded via importlib):
- test_committed_labels_match_generator
- test_set_coverage_and_timing_rules
- test_ball_touch_proximity_and_velocity_change
- test_ball_never_inside_a_box
- test_near_miss_case
- test_number_hidden_case (uses render_frame)
- tests/test_eval_player_fixtures.py, ffmpeg tests. The module-scoped fixture `eval_player_set(require_ffmpeg, tmp_path_factory)` calls build_all(tmp_dir):
- test_clip_format_ffprobe
- test_build_is_idempotent (mtimes and labels bytes unchanged after a 2nd build_all)
- test_decoded_frames_show_ball_and_team_colour
- tests/test_eval_player_fixtures.py::test_eval_oracle_and_shift: monkeypatch sportscut.player.detect_touches/find_touches with an oracle that reads <clip dir>/labels.json (offset 0.0, +0.5, +0.6); asserts the AC15 values via evaluate_dir(eval_player_set).
- tests/test_eval_player_fixtures.py::test_eval_player_cli_baseline_json and test_eval_player_indent_output: main(['eval-player', str(eval_player_set), '--json']) returns 0, and stdout is one line that parses as JSON with the exact key set, 4 sorted per_clip names, and the baseline zeros and nulls. Without --json, the output is multi-line JSON that parses to the same keys.
- tests/test_cli.py::test_eval_player_errors (appended; no ffmpeg): a missing dir, an empty dir, and labels without a clip each make main return 2 with 'sportscut eval-player: error:' on stderr.
- Regression: the existing test_cli (--version, help, module entry), test_models, test_media and test_fixtures still pass. Also run `PATH=/nonexistent python -m pytest -q` to show that the ffmpeg tests skip and the rest pass. Run build.py twice and the eval command from the Verify section, and quote the output.

## Deviations

- `score_clip` aligns sorted predictions and labels by ordinal when their counts are equal before applying the ±0.5 s tolerance. This resolves an internal conflict in AC15: the prescribed fixtures contain consecutive same-player touches exactly 1.0 s apart, so unrestricted maximum matching would match a uniformly +0.6 s shifted prediction to the following label and produce non-zero F1. Unequal-cardinality inputs continue to use `match_times` as specified.
