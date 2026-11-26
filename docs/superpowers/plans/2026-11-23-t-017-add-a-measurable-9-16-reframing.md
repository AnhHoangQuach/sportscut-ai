# Plan T-017: Add a measurable 9:16 reframing eval with synthetic tracked clips and a center-crop baseline

Design: `docs/superpowers/specs/2026-11-23-t-017-add-a-measurable-9-16-reframing-design.md`.

## Implementation plan

# T-017: 9:16 reframing eval (synthetic tracked clips, `sportscut eval-crop --json`, center-crop baseline)

## Context
R-004 goal: `sportscut cut match.mp4 --vertical` also writes 1080x1920 versions of every highlight clip. The crop window follows the ball and players, and each clip has burned-in subtitles and the live scoreline. We measure first, so this task builds only the **ruler** and a baseline:
1. `sportscut/reframe.py`: the crop geometry and `plan_crop(video, aspect=9/16)`. For now it returns a static center crop (the baseline).
2. `media.probe_size(path)`: returns the video width and height. Both `plan_crop` and the eval need it.
3. `tests/fixtures/eval_crop/build.py`: 4 deterministic synthetic clips. Their `labels.json` files are committed and sampled at 5 Hz.
4. `sportscut eval-crop DIR [--json]`: prints `ball_in_crop`, `players_in_crop`, `jitter`, `seconds_per_min` and `per_clip`.
5. The center-crop baseline, recorded in README from a real run.

Later R-004 tasks raise the numbers. They add the numpy heuristics (green-field mask, player mass, bright ball blob) and a smoothed virtual camera, then rendering, `--vertical`, subtitles and the scoreline. None of that logic belongs in this task. It follows the T-029 eval-player pattern (`sportscut/eval_player.py`, `tests/fixtures/eval_player/build.py`). Copy its structure and conventions.

## Step 0: precondition (run first, before writing anything)
```bash
test -f pyproject.toml && grep -q "def main" sportscut/cli.py && grep -q '"cut"' sportscut/cli.py && grep -q '"eval"' sportscut/cli.py && grep -q "def probe_duration" sportscut/media.py && grep -q "class MediaError" sportscut/media.py && grep -q "def evaluate_dir" sportscut/evaluate.py && grep -q "def require_ffmpeg" tests/conftest.py && echo READY
```
The PM checked this on main on 2026-11-23, and it prints READY because T-004 (#19) and T-010 (#27) are merged. If it does not print READY on your base:
- report `BLOCKED: T-017 needs T-004 and T-010 on the base branch`
- change no files
- do not recreate or cherry-pick the missing foundation (Tech Lead decision)

What the base provides:
- `sportscut/media.py`: `MediaError`, `find_tool`, `_failure_detail` and `probe_duration`. All of them raise `MediaError` with `media file not found: <path>` for a missing file.
- `sportscut/cli.py`: argparse with subcommands `detect`, `cut`, `eval-player`, `eval`, `player` and `serve`.
- `tests/conftest.py`: the session fixtures `require_ffmpeg` and `synthetic_video` (6 s, 160x120 @ 10 fps).
- `.gitignore`: already ignores `*.mp4` and `data/`. Do not edit it.

Do not modify `sportscut/evaluate.py`, `sportscut/eval_player.py` or any existing test except the append-only files listed below.

## Files to touch
| File | Change |
|---|---|
| `sportscut/media.py` | add `probe_size(path) -> tuple[int, int]` |
| `sportscut/reframe.py` | **new**: `ASPECT`, `SAMPLE_HZ`, `crop_width`, `sample_times`, `plan_crop` |
| `sportscut/eval_crop.py` | **new**: `Label`, `load_labels`, `validate_plan`, `score_clip`, `metrics`, `evaluate_dir` |
| `sportscut/cli.py` | add the `eval-crop DIRECTORY [--json]` subcommand |
| `tests/fixtures/eval_crop/build.py` | **new**: standalone generator for clips and labels |
| `tests/fixtures/eval_crop/{slow_dribble,long_pass,occluded,white_distractor}/labels.json` | **new, committed**, written by build.py |
| `tests/fixtures/eval_crop/<case>/clip.mp4` | generated and git-ignored. Never commit it. |
| `tests/test_reframe.py`, `tests/test_eval_crop.py`, `tests/test_eval_crop_fixtures.py` | **new** tests |
| `tests/test_media.py`, `tests/test_cli.py` | append-only tests |
| `tests/test_t017_acceptance.py` | **new**, written by the Tester |
| `README.md` | new Vietnamese section (step 9) |
| `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md` | append one Assumptions bullet (step 9) |

## Interfaces

### `sportscut/media.py`
```python
def probe_size(path: str | Path) -> tuple[int, int]:
    """(width, height) of the first video stream."""
```
- If the file is missing, raise `MediaError(f"media file not found: {path}")` before calling ffprobe.
- Run `ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0:s=x -i <path>`.
- A non-zero exit raises `MediaError(f"ffprobe failed for {path}: {detail}")`, using `_failure_detail`.
- Empty output (no video stream) raises `MediaError(f"no video stream in {path}")`.
- Otherwise, parse the first line `WxH` into ints.

### `sportscut/reframe.py`
```python
ASPECT = 9 / 16          # width / height of the output frame
SAMPLE_HZ = 5

def crop_width(width: int, height: int, aspect: float = ASPECT) -> int
def sample_times(duration: float) -> list[float]
def plan_crop(video: str | os.PathLike[str], aspect: float = ASPECT) -> list[tuple[float, float]]
```
- `crop_width`: the crop is always full source height. It returns `min(width, max(2, 2 * math.floor(height * aspect / 2)))`, which is even so libx264/yuv420p can use it later.
  - It raises `ValueError` unless width and height are positive ints (not bool).
  - It raises `ValueError` unless aspect is a finite real number > 0 (not bool).
  - Examples: (640, 360) → 202, (1920, 1080) → 606, (720, 1920) → 720.
- `sample_times`: duration must be finite and > 0, otherwise `ValueError`.
  - `n = max(1, math.floor(duration * SAMPLE_HZ + 1e-9))`. It returns `[round(i / SAMPLE_HZ, 4) for i in range(n)]`.
  - So 12.0 gives 60 times, 0.0 to 11.8, and 0.1 gives [0.0].
- `plan_crop`:
  - `width, height = media.probe_size(video)`.
  - Call `crop_width(width, height, aspect)` to validate aspect. A bad aspect raises `ValueError` before `probe_duration` is called.
  - `duration = media.probe_duration(video)`.
  - Return `[(t, width / 2) for t in sample_times(duration)]`.
  - Baseline only: no frames are decoded. Call `media` through the module (`from sportscut import media`) so tests can monkeypatch it.
- **Plan contract** (checked by the eval and used by later tasks):
  - the plan is non-empty
  - every item is `(t, x_center)`, both finite numbers
  - t is strictly increasing
  - `cw/2 - 1e-6 <= x_center <= width - cw/2 + 1e-6`, where `cw = crop_width(width, height)`
  - Between samples the center is linearly interpolated (`np.interp`, held constant outside the plan's range). The crop window at time t is `[x - cw/2, x + cw/2]`.

### Label format (`<DIR>/<case>/labels.json`)
A JSON list of entries `{"t": seconds, "ball": [x, y] | null, "players": [[x, y, w, h], ...]}` in source-frame pixels. Player boxes use their top-left corner.
- `ball: null` means the ball is not visible (occluded or off-frame). Such an entry is excluded from `ball_in_crop`.
- `players` is optional. Missing means "not labelled"; an empty list means "no players visible".
- Labels may be sparse and at any times, so the PO can hand-label real clips in `data/eval_crop/<name>/{clip.mp4,labels.json}` using the same layout.

### `sportscut/eval_crop.py`
```python
class Label(NamedTuple):
    t: float
    ball: tuple[float, float] | None
    players: tuple[tuple[float, float, float, float], ...]

def load_labels(path) -> list[Label]                 # sorted by t
def validate_plan(plan, width: int, cw: int, where: str) -> None
def score_clip(labels, plan, width: int, cw: int, duration: float) -> dict
def metrics(counts: dict, seconds: float, minutes: float) -> dict
def evaluate_dir(path) -> dict
```
**`load_labels`** raises `ValueError` with the label path as a prefix (`f"{path}: ..."`):
- OSError or JSONDecodeError → `f"{path}: {exc}"`
- top level is not a list → `top level must be a list`
- empty list → `no labels`
- `[i]` is not an object → `[i] must be an object`
- t missing, bool, non-number, non-finite or < 0 → `[i].t must be a non-negative number`
- `ball` key missing, or not null and not a list of 2 finite numbers (not bool) → `[i].ball must be null or [x, y]`
- `players` present but not a list of 4-number lists (finite, not bool) with w > 0 and h > 0 → `[i].players must be a list of [x, y, w, h] with w, h > 0`

**`validate_plan`**: raise `ValueError(f"plan_crop returned an invalid plan for {where}: <reason>")` when the plan contract is broken. The reasons are `empty`, `not (t, x) pairs`, `t not strictly increasing` and `x outside the frame`.

**`score_clip`** returns `{"ball_hits", "ball_total", "player_hits", "player_total", "jerk_sum", "jerk_n"}`. With `ts, xs = zip(*plan)`:
- **Ball:** for each label with a ball, `xc = np.interp(label.t, ts, xs)`. It is a hit when `xc - cw/2 - 1e-9 <= ball_x <= xc + cw/2 + 1e-9`. Only x matters because the crop is full height.
- **Players:** for each player box in each label, the same test is applied to the box centre `x + w/2`.
- **Jitter:** `grid = reframe.sample_times(duration)` and `g = np.interp(grid, ts, xs)`.
  - `d2 = np.abs(np.diff(g, 2)) / width`, i.e. the second difference at 5 Hz as a fraction of frame width.
  - `jerk_sum = float(d2.sum())` and `jerk_n = len(d2)`, which is 0 when the grid has fewer than 3 points.

**`metrics`** (micro-averaged when it is given summed counts):
- `ball_in_crop = round(ball_hits/ball_total, 4)`, or `None` if ball_total is 0
- `players_in_crop = round(player_hits/player_total, 4)`, or `None` if player_total is 0
- `jitter = round(jerk_sum/jerk_n, 6)`, or `0.0` if jerk_n is 0
- `seconds_per_min = round(seconds/minutes, 4)`, or `0.0` if minutes is 0
- The returned key order is exactly ball_in_crop, players_in_crop, jitter, seconds_per_min.

**`evaluate_dir`**:
1. `root` must be a directory, otherwise `ValueError(f"not a directory: {root}")`.
2. Cases are the subdirectories that contain `labels.json`, sorted by name. If there are none, raise `ValueError(f"no eval-crop cases found in {root}")`.
3. Validate every case before any `plan_crop` call. Each case needs `clip.mp4`, otherwise `ValueError(f"missing {clip}; run python tests/fixtures/eval_crop/build.py for the synthetic set")`. Then run `load_labels`.
4. For each case:
   - `width, height = media.probe_size(clip)`, `duration = media.probe_duration(clip)` and `cw = reframe.crop_width(width, height)`.
   - Time `reframe.plan_crop(clip)` with `time.perf_counter()`, calling it through the module so it can be monkeypatched.
   - Run `validate_plan(plan, width, cw, case_name)` and then `score_clip`.
5. The per_clip entry, in this key order:
```
{"clip": name, "duration": round(duration, 4), "labels": len(labels), "ball_labels": n_with_ball, "player_boxes": n_boxes, **metrics(counts, seconds, duration/60)}
```
6. Return `{**metrics(summed counts, summed seconds, summed minutes), "per_clip": [...]}`.

### CLI
- Register `eval-crop` (help `evaluate 9:16 crop framing`) with a positional `directory` (metavar `DIRECTORY`) and `--json`.
- Import it as `from sportscut import eval_crop` and call `eval_crop.evaluate_dir(args.directory)`.
- With `--json`, print compact one-line JSON (`json.dumps(report)`); otherwise print `indent=2`. Return 0.
- `ValueError`, `OSError` and `MediaError` print `sportscut eval-crop: error: <msg>` to stderr and return 2.
- Mirror the eval-player branch. Existing branches stay unchanged.

## Synthetic set: `tests/fixtures/eval_crop/build.py`
The builder is standalone. It never imports `sportscut` and uses only numpy, json, subprocess and the ffmpeg binary.

**Constants and encoding**
- `W, H, FPS = 640, 360, 25`, `DURATION = 12.0` (300 frames), `LABEL_HZ = 5`, `BALL_R = 4`, `PLAYER_W, PLAYER_H = 14, 30`.
- Colours: pitch `(40,140,60)` with darker stripes `(36,128,54)` like eval_player; `TEAM_RGB = {"red": (200,30,30), "blue": (30,60,200), "white": (255,255,255)}`; ball `(255,255,255)`.
- Encode like eval_player: rawvideo rgb24 piped to `ffmpeg -c:v mpeg4 -q:v 2 -pix_fmt yuv420p -an`. Write to `clip.tmp.mp4`, then `os.replace` it to `clip.mp4`.

**Trajectories.** A trajectory is a keyframe list `[(t, x, y), ...]` of centres. It is linearly interpolated with `np.interp` and held constant outside its range, so a single keyframe means a static object.

```python
CASES = {
  "slow_dribble": {"ball": [(0,120,200),(12,520,200)], "line": False, "players": [
      ("red",  [(0,110,178),(12,510,178)]),   # dribbler, follows ball
      ("blue", [(0,160,180),(12,560,180)]),   # defender
      ("red",  [(0,200,120)]), ("blue", [(0,450,280)])]},
  "long_pass": {"ball": [(0,100,180),(4,100,180),(5,560,180),(12,580,190)], "line": False, "players": [
      ("red",  [(0,90,155)]), ("red", [(0,575,160),(12,590,165)]),
      ("blue", [(0,330,120),(12,330,140)]), ("blue", [(0,500,240)])]},
  "occluded": {"ball": [(0,150,220),(5,320,220),(6,320,220),(12,480,220)], "line": False, "players": [
      ("blue", [(0,320,220)]),                 # blocker: covers the ball ~5-6 s
      ("red",  [(0,140,190),(12,470,190)]), ("red", [(0,420,120)])]},
  "white_distractor": {"ball": [(0,480,250),(6,560,120),(12,450,300)], "line": True, "players": [
      ("white", [(0,200,150)]),                # white-shirt distractor
      ("red",  [(0,470,228),(6,550,98),(12,440,278)]), ("blue", [(0,300,200)])]},
}
```

**Functions**
- `label_times()`: returns `[round(i / LABEL_HZ, 1) for i in range(int(DURATION * LABEL_HZ))]`, i.e. 60 times from 0.0 to 11.8.
- `ball_pos(name, t) -> (x, y)` as floats.
- `player_boxes(name, t) -> list[[x, y, w, h]]`: for each player, `[round(cx - PLAYER_W/2), round(cy - PLAYER_H/2), PLAYER_W, PLAYER_H]`, in CASES order.
- `ball_hidden(name, t) -> bool`: with `bx, by` the rounded ball centre, it is True when some player box satisfies `x <= bx-R`, `bx+R <= x+w-1`, `y <= by-R` and `by+R <= y+h-1`.
- `case_labels(name)`: for each t in `label_times()`, an entry `{"t": t, "ball": None if ball_hidden else [round(x), round(y)], "players": player_boxes}`.
- `labels_text(name)`: `"[\n" + ",\n".join(json.dumps(e) for e in labels) + "\n]\n"`, one entry per line so diffs stay readable.
- `render_frame(name, t) -> np.ndarray (H, W, 3) uint8`, drawn in this order:
  1. pitch and stripes
  2. if `line`, the white halfway line at columns 319-320 over the full height
  3. the ball disk of radius BALL_R
  4. players, drawn last so they cover the ball
- `build_all(out_dir=HERE, force=False) -> list[Path]`: idempotent, exactly like eval_player. It rewrites `labels.json` only when the content differs, and re-encodes `clip.mp4` only if it is missing, the labels changed or `force` is set.
- `__main__`: `build_all(force="--force" in sys.argv)`.

**Expected set properties** (the fixture tests check them):
- Each case has 60 labels.
- Only `occluded` has null balls: one consecutive run of 4–8 labels around t=5.0–6.0. The PM derivation gives 6 (5.0..6.0).
- `long_pass` reaches ≥ 300 px/s between consecutive labels; `slow_dribble` stays ≤ 60 px/s.
- In `white_distractor`, the ball is always right of x=421, so it is outside the center crop.
- The PM derivation gives a center-crop ball_in_crop of about 65/234 ≈ 0.28. The authoritative value is the one computed from the committed labels.

## Steps (TDD; for each step write the failing test, run it and see it fail for the right reason, then write the code)
1. Step 0 precondition.
2. `tests/test_media.py` (append):
   - `probe_size(synthetic_video) == (160, 120)`
   - a missing file raises `MediaError` matching `media file not found`
   - an audio-only wav made with lavfi `anoisesrc` in tmp_path raises `MediaError` matching `no video stream`
   - then implement `probe_size`
3. `tests/test_reframe.py`:
   - the `crop_width` examples and its ValueErrors (aspect 0, -1, nan, inf, True; width 0; height -1)
   - `sample_times(12.0)` has 60 items, first 0.0 and last 11.8; `sample_times(0.1) == [0.0]`; 0, -1 and nan raise ValueError
   - `plan_crop(synthetic_video)` equals `[(t, 80.0) for t in sample_times(6.0)]`
   - `plan_crop(missing)` raises MediaError; `plan_crop(synthetic_video, aspect=0)` raises ValueError
   - then implement `reframe.py`
4. `tests/test_eval_crop.py` (no ffmpeg; uses tmp_path JSON files and monkeypatched `media.probe_size`, `media.probe_duration` and `reframe.plan_crop`):
   - **load_labels:** each error message from the list; sorting by t; optional players; a null ball
   - **score_clip, with W=640 and cw=202:**
     - a ball at x 219 and at x 421 under a static 320 plan counts as a hit (inclusive edges); x 218.9 is a miss
     - a player box `[410, 0, 20, 30]` (centre 420) is a hit
     - interpolation: plan `[(0,101),(2,539)]` puts the window centre at 320 at t=1
     - jitter of a constant plan is 0.0
     - jitter of plan `[(0,320),(0.2,340),(0.4,320),(0.6,340)]` over duration 0.8 is `round(40/640, 6)` (grid 0, 0.2, 0.4, 0.6 → |d2| = 40, 40)
   - **metrics:** None when there are no ball or player labels; seconds_per_min; key order
   - **validate_plan:** each invalid case
   - **evaluate_dir:**
     - not a directory; no cases
     - a missing clip in the second case means plan_crop is never called
     - a bad plan raises ValueError
     - micro-averaging over two fake cases (hits 1/2 and 3/3 give 0.8, not the macro 0.75)
     - per_clip key order and sorting by name
   - then implement `eval_crop.py`
5. `tests/test_cli.py` (append), with `eval_crop.evaluate_dir` monkeypatched:
   - `--json` prints exactly one line whose JSON equals the fake report
   - without `--json` the output is indented
   - a ValueError gives exit 2 and stderr starting `sportscut eval-crop: error:`
   - then add the subcommand
6. `tests/test_eval_crop_fixtures.py` (load build.py with `importlib.util.spec_from_file_location`, as in `test_eval_player_fixtures.py`):
   - Committed files: for each case, the committed `labels.json` text equals `labels_text(name)`, and the case names are exactly the 4 above.
   - Static properties (no ffmpeg):
     - every label time is on the 0.2 s grid, with 60 labels
     - balls and boxes lie fully inside 640x360
     - the null-ball run and speed rules hold
     - in `white_distractor`, ball x > 421 at every label
   - Rendering:
     - `render_frame('occluded', hidden_t)` has 0 pixels equal to (255,255,255), and a visible t has ≥ 20
     - `render_frame('white_distractor', 0)` has ≥ 200 pure-white pixels outside the ball's 9x9 square
   - `require_ffmpeg`, module-scoped build into a tmp dir:
     - 4 clips, each probing to `(640, 360)` with duration 12.0 ± 0.05
     - a second `build_all` leaves `clip.mp4` `st_mtime_ns` unchanged
     - `force=True` re-encodes
   - End to end on the tmp set:
     - the `evaluate_dir` keys are exactly the 5 required
     - the baseline has jitter 0.0, ball_in_crop equal to `round(hits/total, 4)` computed independently from the labels with window [219, 421], and < 0.95
     - an **oracle** that monkeypatches `reframe.plan_crop` to follow the labelled ball (interp over non-null labels, clipped to [101, 539]) gives ball_in_crop == 1.0
   - then write build.py and run it to generate the committed labels.
7. Run `python tests/fixtures/eval_crop/build.py`, then `git status --porcelain tests/fixtures/eval_crop`. Only `build.py` and the 4 `labels.json` may appear, and `git check-ignore tests/fixtures/eval_crop/occluded/clip.mp4` must print the path.
8. Run `python -m sportscut eval-crop tests/fixtures/eval_crop --json` and keep the printed line for the README.
9. Docs:
   - **README:** append a Vietnamese section `## Video dọc 9:16: đo khung cắt (eval-crop)`. It covers the build and eval commands, the label format with a one-line example, the real-data location `data/eval_crop/<name>/{clip.mp4,labels.json}`, and the metric definitions: ball centre inside the crop window, player box centre inside, jitter = mean abs second difference of the crop centre at 5 Hz as a fraction of frame width, and seconds_per_min. Then put the baseline JSON from step 8 verbatim under `Baseline đo trong T-017 (center crop):`, and the target line `Mục tiêu: ball_in_crop ≥ 0.95 với jitter thấp (các task R-004 sau)`.
   - **T-036 design spec:** append to Assumptions: `- T-017: same exception for the reframing eval set — tests/fixtures/eval_crop/build.py may write git-ignored clip.mp4 files inside tests/fixtures/eval_crop/; pytest builds only in temp dirs and no media is committed.`
10. Verify by running everything below in this session and quoting the summary lines.

## Verify
```bash
python -m pytest -q                                            # all pass, incl. pre-existing eval/eval-player tests
python tests/fixtures/eval_crop/build.py && python tests/fixtures/eval_crop/build.py   # second run is a no-op
python -m sportscut eval-crop tests/fixtures/eval_crop --json  # 1 line, jitter 0.0, ball_in_crop < 0.95, 4 per_clip
python -m sportscut eval-crop /nonexistent --json; echo $?     # prints 'sportscut eval-crop: error: not a directory: ...', 2
git status --porcelain | grep -c '\.mp4' || true             # 0
git diff --stat main -- sportscut/evaluate.py sportscut/eval_player.py   # empty
```

## Assumptions
- The crop is full source height with a 9:16 width. Later tasks scale it to 1080x1920 when rendering, so the eval scores only horizontal placement.
- "In crop" means the centre point is inside the window. Ball radius and partial player visibility are ignored. Real clips can be judged on the same rule.
- The baseline does not decode frames, so its seconds_per_min is near 0 and machine-dependent. Tests assert only that it is a float ≥ 0.
- This eval is reported in R-004 PRs, but it is not yet a CI gate. The F1 gate is unchanged.

## Test plan

- tests/test_media.py (append): probe_size on synthetic_video == (160, 120); a missing file raises MediaError 'media file not found'; an audio-only wav from lavfi anoisesrc in tmp_path raises MediaError 'no video stream'.
- tests/test_reframe.py: crop_width examples (640x360→202, 1920x1080→606, 720x1920→720) and the ValueError cases (aspect 0, -1, nan, inf, True; width 0; height -1).
- tests/test_reframe.py: sample_times(12.0) has length 60 with endpoints 0.0 and 11.8; sample_times(0.1) == [0.0]; sample_times(0), (-1) and (nan) raise.
- tests/test_reframe.py: plan_crop(synthetic_video) == [(t, 80.0) for t in sample_times(6.0)]; plan_crop(missing) raises MediaError; plan_crop(synthetic_video, aspect=0) raises ValueError.
- tests/test_eval_crop.py: load_labels sorts by t and accepts null ball and missing players; each malformed case raises ValueError starting with the path (non-list, empty, bad t incl. bool/negative/nan, bad ball incl. 3 items/bool, bad players incl. w=0, invalid JSON).
- tests/test_eval_crop.py: score_clip with W=640 and cw=202. Under a static 320 plan, ball x 219 and 421 are hits and 218.9 is a miss. A player box centre at 420 is a hit. Plan [(0,101),(2,539)] gives centre 320 at t=1. Jitter is 0 for a constant plan, and 40/640 for the zig-zag 320/340 plan over duration 0.8.
- tests/test_eval_crop.py: metrics gives None when ball_total or player_total is 0, jitter 0.0 when jerk_n is 0, the seconds_per_min arithmetic, and the exact key order.
- tests/test_eval_crop.py: validate_plan raises on an empty plan, non-pairs, non-increasing t, nan, and x outside [cw/2, W - cw/2].
- tests/test_eval_crop.py (monkeypatched media.probe_size, media.probe_duration and reframe.plan_crop; fake clip.mp4 files are empty files): not a dir, no cases, a missing clip in the 2nd case (plan_crop call count 0), micro-average 0.8 over two cases (1/2 and 3/3), per_clip sorted by name with exact keys.
- tests/test_cli.py (append, monkeypatched eval_crop.evaluate_dir): --json prints one line equal to the report; without --json the output is indented; a ValueError gives exit 2 and stderr prefix 'sportscut eval-crop: error:'.
- tests/test_eval_crop_fixtures.py: for all 4 cases, the committed labels.json text == build.labels_text(name), and the case names are exact.
- tests/test_eval_crop_fixtures.py (static): 60 labels on the 0.2 s grid; ball and boxes inside the frame; the null-ball run only in occluded (4–8 labels in [4.6, 6.4]); long_pass max speed ≥ 300 px/s and slow_dribble ≤ 60 px/s; white_distractor ball x > 421.
- tests/test_eval_crop_fixtures.py (render): occluded at a hidden t has 0 pure-white pixels and ≥ 20 at a visible t; white_distractor at t=0 has ≥ 200 white pixels outside the ball square.
- tests/test_eval_crop_fixtures.py (require_ffmpeg, module-scoped tmp build): 4 clips probing to (640, 360) with duration 12.0 ± 0.05; idempotent rebuild (mtime_ns unchanged); force re-encodes.
- tests/test_eval_crop_fixtures.py (end to end): the baseline evaluate_dir has the 5 exact keys, jitter 0.0, and ball_in_crop equal to an independent computation from the labels with window [219, 421] and < 0.95. An oracle plan_crop monkeypatch gives ball_in_crop 1.0.
- tests/test_t017_acceptance.py (Tester, written from the ACs, not from the dev tests): a subprocess run of `python -m sportscut eval-crop <tmp built set> --json` gives one JSON line, exit 0 and the AC15 properties; a nonexistent dir gives exit 2; git check-ignore on the clip paths; hand-written sparse labels in a tmp case (3 labels, one null ball, no players key) are scored without error.
