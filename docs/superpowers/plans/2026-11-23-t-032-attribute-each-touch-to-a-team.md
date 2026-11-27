# Plan T-032: Attribute each touch to a team by shirt-colour clustering

Design: `docs/superpowers/specs/2026-11-23-t-032-attribute-each-touch-to-a-team-design.md`.

## Implementation plan

# T-032: Attribute each touch to a team by shirt-colour clustering

Request R-006 (Theo dõi cầu thủ). Depends on T-031 (merged as 2ca350b, `sportscut/player.py` touch candidates).

## Context (read before coding)

- `sportscut/player.py` (T-031): `detect_touches(video)` reads 5 Hz frames, scaled to at most 320 px wide, with `media.sample_frames`. It finds kicks (`find_kicks`), matches each kick to the closest player blob (`player_blobs`, built on `reframe.player_mask`) and returns `Touch(t, team=None, number=None, confidence, bbox)` after NMS. `find_touches(video, query)` filters `detect_touches` on `team == query.team and number == query.number`, so it always returns [] today.
- `sportscut/eval_player.py` (T-029, **not changed here**): `team_accuracy` = share of matched any-touch pairs where `detect_touches(...).team == label.team`. Labels use the team names `red` and `blue`. `f1/precision/recall` score `find_touches(clip, query)` for every queried player.
- Synthetic set (`tests/fixtures/eval_player/build.py`, **not changed**): red shirts are RGB (200,30,30) and blue shirts are (30,60,200), 16×32 px at 640×360. Shirts carry white bitmap digits, the ball is a white disc, and the grass is (40,140,60)/(36,128,54). Every case has both teams on the pitch.
- Before (T-031 README run on main): `f1 0.0, touch_f1_any 0.9737, team_accuracy 0.0, id_accuracy 0.0, seconds_per_min 2.0195`. Per-clip touch_f1_any: dribble 1.0, near_miss 1.0, number_hidden 1.0, short_passes 0.9091.
- Error paths already exist and are reused unchanged: `sportscut player` prints `sportscut player: error: <msg>` and exits 2 on ValueError (cli.py), and `POST /players` maps ValueError to HTTP 422 (api.py).

## Design

All new code goes in `sportscut/player.py`. It uses numpy only, adds no dependency and does not change reframe/media.

1. **Colour feature.** `colour_features(rgb)` converts uint8 RGB (N,3) to float (N,3) `[s·cos(2πh), s·sin(2πh), v]`, with HSV h in [0,1) and s, v in [0,1]. This is a cone in which hue is circular and Euclidean distance makes sense. Saturation is `hypot(f[:,0], f[:,1])`.
2. **Shirt pixels.** `shirt_pixels(frame, box=None)` takes the pixels of `reframe.player_mask(frame)` (already eroded non-grass inside the field), restricts them to `box` (analysis px) when given, and keeps only pixels with saturation ≥ TEAM_MIN_SAT. That drops white digits, the white ball, lines, black shorts and shadows. It returns features (M,3), or an empty (0,3) array when there is no field.
3. **Match clusters.** `team_colours(frames)` pools `shirt_pixels` of every TEAM_EVERY-th frame (1 Hz). It returns None if fewer than TEAM_MIN_PIXELS pixels are found. Otherwise it keeps every ceil(n/TEAM_MAX_PIXELS)-th pixel, runs `kmeans(points, TEAM_K)`, and then:
   - drops clusters holding < TEAM_MIN_SHARE of the points (goalkeepers, referee, edge noise), the 'outliers by cluster size' rule;
   - visits the survivors by size, largest first (ties: lower index), and merges any cluster whose centroid is < TEAM_MERGE from an already kept centroid into it (size-weighted mean, sizes add), because one kit split in two is still one team;
   - re-sorts by size, largest first. Fewer than 2 clusters gives None; otherwise the two largest become the teams;
   - names them with `name_teams` and returns `TeamColours(centroids, names)`, larger team first.
4. **K-means (deterministic).** `kmeans(points, k)` uses farthest-point initialisation: first the point nearest the mean, then each next centre is the point with the largest distance to its nearest chosen centre (ties: lowest index). Then at most TEAM_ITERS Lloyd iterations, stopping early when labels stop changing. An empty cluster keeps its previous centroid. It returns `(centroids (k,3) float64, labels (n,) int)`.
5. **Cluster names.** `name_teams(centroids)` picks the ordered pair of *distinct* names (a, b) from TEAM_NAMES that minimises d(c0, F(a)) + d(c1, F(b)), where F = colour_features of TEAM_RGB. It iterates a then b in TEAM_NAMES order and keeps the first strict minimum. `Touch.team` therefore stays a valid `normalize_team` value, and the eval compares it to label names directly.
6. **Label a touch.** In `_analyse`, after choosing the touching blob at kick sample i, `team_of(frames[i], blob, colours)` assigns each `shirt_pixels(frame, blob)` pixel to its nearest team centroid. The majority name wins (tie: `colours.names[0]`). It returns None when `colours` is None or the box has no saturated pixel.
7. **Map `--team`.** `pick_team(team, colours)`:
   - if `team` (already normalized) equals one of `colours.names`, return it;
   - otherwise F = colour_features of `TEAM_RGB[team]` or of the parsed `#rrggbb`. With d0, d1 the distances to the two centroids, raise `ValueError` when `abs(d0 - d1) <= TEAM_TIE * max(d0, d1)`. The message is `team colour '<team>' is equally close to both team shirts (<n0>, <n1>); use --team <n0>, --team <n1> or a closer #rrggbb`;
   - otherwise return the nearer cluster's name.
8. **One analysis pass.** A new private `_analyse(video) -> tuple[list[Touch], TeamColours | None]` holds the current body of `detect_touches`, plus `colours = team_colours(frames)` computed once and `team=` filled through `team_of`. `detect_touches(video)` returns `_analyse(video)[0]`. `find_touches(video, query)` calls `_analyse` once. If colours is None it returns []. Otherwise it returns `[t for t in touches if t.team == pick_team(query.team, colours)]`. **The number is ignored until T-033**, so the reel holds every touch by the queried team: a working but imprecise reel, as the task intends.

Kick detection, blob finding, NMS and all T-031 constants are unchanged, so touch times, confidences and bboxes are identical to T-031 and `touch_f1_any` cannot drop.

### Constants (in player.py, next to the T-031 ones)

```text
TEAM_RGB = {black (0,0,0), blue (0,0,255), green (0,128,0), orange (255,165,0), pink (255,105,180),
            purple (128,0,128), red (255,0,0), sky (135,206,235), white (255,255,255), yellow (255,255,0)}  # keys == TEAM_NAMES
TEAM_MIN_SAT = 0.25     # tunable 0.15..0.40
TEAM_K = 4              # tunable 3..5
TEAM_MIN_SHARE = 0.1    # tunable 0.05..0.20
TEAM_MERGE = 0.15       # tunable 0.05..0.30 (feature units)
TEAM_EVERY = 5          # fixed: every 5th 5 Hz sample = 1 Hz
TEAM_TIE = 0.05         # fixed: relative distance gap counted as 'equally far'
TEAM_MIN_PIXELS = 50    # fixed
TEAM_MAX_PIXELS = 20000 # fixed
TEAM_ITERS = 20         # fixed
```

### Interfaces (exact)

```python
@dataclass(frozen=True)
class TeamColours:
    centroids: tuple[tuple[float, float, float], tuple[float, float, float]]  # larger team first
    names: tuple[str, str]                                                    # distinct TEAM_NAMES

def colour_features(rgb: np.ndarray) -> np.ndarray            # (N,3) uint8 -> (N,3) float64
def shirt_pixels(frame: np.ndarray, box: tuple[int, int, int, int] | None = None) -> np.ndarray  # (M,3)
def kmeans(points: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]
def name_teams(centroids: np.ndarray) -> tuple[str, str]
def team_colours(frames: np.ndarray) -> TeamColours | None    # frames (n,h,w,3) uint8, n may be 0
def team_of(frame: np.ndarray, box: tuple[int, int, int, int], colours: TeamColours | None) -> str | None
def pick_team(team: str, colours: TeamColours) -> str
def _analyse(video) -> tuple[list[Touch], TeamColours | None]
def detect_touches(video) -> list[Touch]                      # == _analyse(video)[0]
def find_touches(video, query: PlayerQuery) -> list[Touch]
```

`normalize_team`, `PlayerQuery`, `Touch`, `player_blobs`, `find_kicks`, `suppress_touches` and `_box_gap` are unchanged. player.py must still match nothing for T-031's grep `subprocess|ffmpeg|green_mask|cumsum|def (sample_frames|field_mask|ball_candidates|track_ball)`: do not use np.cumsum and do not write the word ffmpeg.

## Files to touch

- `sportscut/player.py`: everything above.
- `tests/test_teams.py` (new, Developer): unit and integration tests for T-032.
- `tests/test_t032_acceptance.py` (new, Tester).
- Allowed edits to pre-existing tests. They pin the T-031 stub behaviour (find_touches == [], f1 == 0, team None on the real set, find_touches filtering a monkeypatched detect_touches), which this task intentionally replaces. Function names stay; nothing is deleted or skipped:
  - `tests/test_player.py::test_detect_touches_stub_and_find_filters`: only its last two statements. They are replaced by monkeypatching `sportscut.player._analyse` to return (values, TeamColours with names ('red','blue')) and asserting `find_touches('x.mp4', PlayerQuery('red', 10)) == [values[0], values[1]]` (team-only filter).
  - `tests/test_touches.py::test_eval_player_gate`: the `f1 == precision == recall == 0.0` line becomes `report['f1'] > 0.0`. The `find_touches(...) == []` loop becomes: every result is in `player.detect_touches(clip)` and has `team == entry['team']`.
  - `tests/test_eval_player_fixtures.py::test_eval_player_cli_baseline_json`: `report['f1'] == 0.0` → `report['f1'] > 0.0`, and `team_accuracy == id_accuracy == 0.0` → `report['team_accuracy'] >= 0.95 and report['id_accuracy'] == 0.0`. In `test_eval_player_indent_output`, `['f1'] == 0.0` → `['f1'] > 0.0`.
  - `tests/test_t031_acceptance.py`:
    - `test_ac5_real_set_touch_shape`: `t.team is None` → `t.team in {'red', 'blue'}`.
    - `test_ac7_eval_player_gate`: the f1 line → `report['f1'] > 0.0`.
    - `test_ac10_find_touches_empty`: body → for every case and query, every `find_touches` result is in `detections[name]` and has `team == q.team` (no detect_touches monkeypatch).
- `README.md`: insert-only new section `## Đội theo màu áo (T-032)` placed immediately before `## API HTTP` (not next to the T-031 section: `test_t031_acceptance.py::test_ac13` pins the heading that follows T-031's).
- `docs/superpowers/specs/2026-11-23-t-031-detect-ball-touches-by-any-player-design.md` and `docs/superpowers/specs/2026-11-23-t-029-build-the-player-touch-eval-synthetic-design.md`: append one bullet each under `## Existing specs this task changes`, exactly: `- T-032 (2026-11-27): detect_touches fills Touch.team from two shirt-colour clusters; find_touches returns every touch by the queried team (number ignored until T-033), superseding T-031 AC10 (find_touches == []).`

Not changed: reframe.py, media.py, eval_player.py, cli.py, reel.py, api.py, tests/conftest.py, tests/fixtures/eval_player/**, pyproject.toml, agent-office/.

## Plan (test first)

**Step 0: READY check and the before measurement.** On the untouched branch, run:

```bash
python -c "from sportscut import player, reframe; [getattr(player, n) for n in ('player_blobs','find_kicks','suppress_touches','detect_touches','find_touches')]; reframe.player_mask; assert '## Phát hiện chạm bóng (T-031)' in open('README.md').read(); print('READY')"
python tests/fixtures/eval_player/build.py && python -m sportscut eval-player tests/fixtures/eval_player --json > /tmp/t032_before.json && cat /tmp/t032_before.json
python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json
```

If the first command does not print READY, report `BLOCKED: T-032 needs T-031 touch candidates on the base` and change nothing. Keep both JSON outputs for the report.

**Step 1: colour_features + TEAM_RGB.**
- Test first. `colour_features(np.array([[255,0,0],[0,0,255],[255,255,255],[0,0,0],[200,30,30]], np.uint8))` ≈ `[[1,0,1],[-0.5,-0.866025,1],[0,0,1],[0,0,0],[0.85,0,0.784314]]` (atol 1e-5), and `tuple(TEAM_RGB) == TEAM_NAMES` with the values above.
- Watch it fail, then implement.

**Step 2: kmeans.**
- Test first:
  - 30 points near (1,0,1) and 20 near (-0.5,-0.87,1) (fixed offsets, no RNG), k=2: labels split exactly by group and centroids are within 0.05 of the group means;
  - two calls give identical arrays;
  - k=3 on only 2 distinct values (repeated) does not raise and returns 3 centroids and n labels.
- Implement.

**Step 3: shirt_pixels, name_teams, team_colours.** Test first, on frames built with numpy (320×180 field of (40,140,60), shirts 8×16, white radius-2 ball, white 2×2 'digit' squares on shirts, 6 frames stacked):
- 6 red (200,30,30) + 4 blue (30,60,200) + 1 orange (240,140,20) shirts give names == ('red','blue'), red first, centroids[0] within 0.03 of colour_features (200,30,30). Orange (1 of 11 shirts, < 0.1) is not a team;
- removing the white ball/digits gives the same result;
- red-only shirts give None, red (200,30,30) + dark red (180,25,25) gives None (merged), all-grey frames (no field) give None, `np.zeros((0,180,320,3), np.uint8)` gives None;
- two calls on the same frames are equal;
- `shirt_pixels` on a frame with no field has shape (0,3), and with a box it only returns pixels inside the box;
- `name_teams` of red/blue features gives ('red','blue'), and two centroids that are both closest to red give two distinct names, one of them 'red'.

Implement.

**Step 4: team_of and pick_team.**
- Test first:
  - `team_of` on a frame with a red shirt box gives 'red'; a box covering grass only gives None; colours None gives None;
  - with `C = TeamColours((tuple(F(255,0,0)), tuple(F(0,0,255))), ('red','blue'))`: `pick_team('blue', C) == 'blue'`, `pick_team('#ff0000', C) == 'red'`, `pick_team('orange', C) == 'red'`, `pick_team('sky', C) == 'blue'`;
  - `pick_team('#ff00ff', C)` raises ValueError whose message contains 'equally close', 'red' and 'blue'.
- Implement.

**Step 5: _analyse, detect_touches, find_touches.** Test first:
- reuse T-031's monkeypatched `media.probe_size`/`media.sample_frames` pattern (turning ball next to a red shirt at analysis (150,60), plus 3 blue shirts and 2 more red shirts elsewhere in every frame): the single touch has team 'red'. The T-031 single-colour unit tests keep team None (only one cluster);
- monkeypatch `player._analyse` to count calls: `find_touches` calls it once, filters on team only (number ignored), returns [] when colours is None, and propagates the pick_team ValueError;
- `main(['player', str(synthetic_video), '--team', '#ff00ff', '--number', '7', '--out', tmp])` with `_analyse` patched to return ([], C) returns 2, and stderr contains `sportscut player: error:` and `equally close`.

Implement, then make the listed edits to the pre-existing tests.

**Step 6: integration gate.**
- Write the gate test in tests/test_teams.py. It uses the built eval set in a tmp dir via `build.build_all` with require_ffmpeg, the same as test_touches.py. `evaluate_dir`:
  - team_accuracy ≥ 0.95, touch_f1_any ≥ 0.9737, per-clip touch_f1_any ≥ {dribble 1.0, near_miss 1.0, number_hidden 1.0, short_passes 0.9091}, f1 > 0.0, id_accuracy == 0.0, seconds_per_min ≤ 6.0;
  - on short_passes, `find_touches(clip, PlayerQuery('#c81e1e', 7)) == find_touches(clip, PlayerQuery('red', 7))` and `PlayerQuery('sky', 4)` gives the same result as `PlayerQuery('blue', 4)`.
- Run it. If it fails, tune only the tunable TEAM_* constants within their ranges. If no setting passes, report `BLOCKED` with the best JSON. The Tech Lead decides.

**Step 7: README and specs.**
- Add the README section, in Vietnamese, like the T-031 section. It contains:
  - how teams are found (two clusters of saturated shirt colour, small clusters such as goalkeeper/referee dropped);
  - how `--team` (name or #hex) maps to the closest cluster, and the 'equally close' error;
  - that the reel now holds **every touch of that team** until T-033 reads numbers;
  - the known limitations: clashing kits (trùng màu áo), white/black/grey kits (low saturation, not clustered: find_touches returns []), and only one team visible (returns []);
  - a ```text block with the final TEAM_* values;
  - `Trước T-032:` and `Sau T-032:`, each followed by a ```json block holding one line of real eval-player output from this session.
- Append the spec bullets.

**Step 8: verify.**

```bash
python -m pytest -q
python tests/fixtures/eval_player/build.py && python -m sportscut eval-player tests/fixtures/eval_player --json
python -m sportscut eval tests/fixtures/eval --json   # f1 equals Step 0
git diff --stat main -- sportscut/reframe.py sportscut/media.py sportscut/eval_player.py sportscut/cli.py sportscut/reel.py sportscut/api.py tests/conftest.py tests/fixtures/eval_player pyproject.toml   # empty
git diff --numstat main -- . ':!docs/superpowers'   # total < 600 incl. new files
```

The Developer's report (and the PR body) quotes the before and after eval-player JSON, team_accuracy, touch_f1_any and seconds_per_min.

## Assumptions

- The two teams wear clearly different, saturated shirt colours. Clashing kits are a known limitation and are not solved.
- White, black and grey kits are not clustered, because the task excludes low-saturation pixels. Such matches give fewer than two clusters, so touches keep team None and find_touches returns [] (no error). This is documented as a limitation and left for a follow-up.
- Clusters are computed per video (a new match means new colours). A short clip that shows mostly a goalkeeper could make the goalkeeper a 'team'. This is accepted.
- 'Equally far' means the two distances are within 5 % of each other (TEAM_TIE), because exact float equality never happens in practice.
- Until T-033, `find_touches` ignores the number, so `player_red_10.mp4` contains all red touches. This is the intended interim behaviour.

## Test plan

- tests/test_teams.py::test_colour_features_values: the five RGB rows from AC2, plus TEAM_RGB keys/values.
- tests/test_teams.py::test_kmeans_separates_and_is_deterministic: two fixed point groups, k=2. Repeat the call and compare with np.array_equal. Also k=3 on 2 distinct repeated points.
- tests/test_teams.py::test_team_colours_two_teams_drop_keeper: the 6 red + 4 blue + 1 orange shirt frames with ball/digits. Assert names, order and centroid; repeat with no ball/digits.
- tests/test_teams.py::test_team_colours_none_cases: red-only, two red shades, grey no-field and empty frames each give None.
- tests/test_teams.py::test_shirt_pixels_mask_box_and_saturation: no field gives shape (0,3); box restriction; white pixels are excluded.
- tests/test_teams.py::test_name_teams_distinct: red/blue gives ('red','blue'); two red-ish centroids give distinct names including 'red'.
- tests/test_teams.py::test_team_of_majority_and_none: red box gives 'red'; grass box gives None; colours None gives None.
- tests/test_teams.py::test_pick_team_mapping_and_tie: exact name, #ff0000, orange, sky; '#ff00ff' raises with 'equally close', 'red' and 'blue'.
- tests/test_teams.py::test_detect_touches_labels_team: monkeypatched probe_size/sample_frames with a turning ball at a red shirt among red and blue shirts gives one touch with team 'red'.
- tests/test_teams.py::test_find_touches_team_only_single_pass: monkeypatched _analyse call counter; filter ignores number; None colours gives []; ValueError propagates.
- tests/test_teams.py::test_player_cli_tie_error (require_ffmpeg, conftest synthetic_video): exit 2, `sportscut player: error:` and `equally close` on stderr.
- tests/test_teams.py::test_eval_player_team_gate (require_ffmpeg, build.build_all into a tmp dir): the AC10 metric thresholds, the subset/team check for every query, and the hex/sky equivalence on short_passes.
- Edit the listed pre-existing tests exactly as the spec says (AC11), then run `python -m pytest -q` with 0 failed.
- Tester: tests/test_t032_acceptance.py, written independently from AC2-AC13, covering:
- the tie error through the CLI;
- team_accuracy/touch_f1_any gates on a freshly built set;
- a mutation check that the gate can fail: with _analyse patched to swap the two names, team_accuracy < 0.95;
- README section placement, constants and JSON;
- the spec bullets;
- the protected-files diff, gated to branches starting with office/T-032 (Tech Lead pattern from T-031 round 2) so later branches are not frozen.
