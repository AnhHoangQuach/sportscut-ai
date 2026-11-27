# T-032: Attribute each touch to a team by shirt-colour clustering

Request R-006. Plan: `docs/superpowers/plans/2026-11-23-t-032-attribute-each-touch-to-a-team.md`.

## Product Owner request

Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó.

## Goal

Sample player-blob pixels across the match and cluster them into two team colours with a small numpy k-means in HSV. Exclude low-saturation pixels and goalkeeper or referee outliers by cluster size. Label each touch's player blob with the nearest team cluster, and map `--team` (a colour name or #hex) to the closest cluster, with a clear error if both clusters are equally far. `find_touches` now returns every touch by the queried team, which is a working but imprecise reel. Report `team_accuracy` and F1 before and after in the PR. Merge only if `team_accuracy` ≥ 0.95 and `touch_f1_any` does not drop. Assumption: the two teams wear clearly different shirt colours. Clashing kits are noted as a known limitation and are not solved.

## Acceptance criteria

- AC1: Step 0 runs before any file change. On a base containing T-031 it prints READY, and the eval-player and eval JSON of the untouched base are recorded. Otherwise the Developer reports `BLOCKED: T-032 needs T-031 touch candidates on the base` and the diff is empty.
- AC2: `player.colour_features(np.array([[255,0,0],[0,0,255],[255,255,255],[0,0,0],[200,30,30]], np.uint8))` equals [[1,0,1],[-0.5,-0.866025,1],[0,0,1],[0,0,0],[0.85,0,0.784314]] within 1e-5. `tuple(player.TEAM_RGB) == player.TEAM_NAMES`, with red (255,0,0), blue (0,0,255), sky (135,206,235), orange (255,165,0), pink (255,105,180), purple (128,0,128), green (0,128,0), yellow (255,255,0), white (255,255,255) and black (0,0,0).
- AC3: `player.kmeans(points, k)` is deterministic: two calls give identical centroids and labels. On two well-separated point groups with k=2 it labels each group as one cluster, with centroids within 0.05 of the group means. With k larger than the number of distinct points it does not raise and returns k centroids and len(points) labels.
- AC4: `player.team_colours(frames)` on numpy-built 320×180 field frames:
- 6 red (200,30,30) + 4 blue (30,60,200) + 1 orange (240,140,20) 8×16 shirts, with a white ball and white digit pixels, gives a TeamColours with names ('red','blue'), red first, and centroids[0] within 0.03 of colour_features (200,30,30). The single orange shirt is not a team.
- Red-only shirts, red (200,30,30) + (180,25,25) shirts, grey frames with no field, and a (0,180,320,3) array each give None.
- Equal inputs give equal results.
- AC5: `player.name_teams` returns two distinct TEAM_NAMES. Red/blue shirt centroids give ('red','blue'). Two centroids both nearest to red give a pair containing 'red' and another name.
- AC6: `player.team_of(frame, box, colours)` returns the majority team name of the saturated shirt pixels in box ('red' for a red shirt box). It returns None for a grass-only box and None when colours is None.
- AC7: With C = TeamColours((F(255,0,0), F(0,0,255)), ('red','blue')):
- pick_team('blue', C) == 'blue', pick_team('#ff0000', C) == 'red', pick_team('orange', C) == 'red' and pick_team('sky', C) == 'blue'.
- pick_team('#ff00ff', C) raises ValueError whose message contains 'equally close', 'red' and 'blue'.
- AC8: `detect_touches(video) == _analyse(video)[0]`.
- With monkeypatched media.probe_size/sample_frames (a turning ball next to a red shirt, with 3 blue and 2 more red shirts in every frame), the single touch has team 'red'. All T-031 single-colour unit tests still pass with team None.
- Touch t, confidence and bbox are unchanged from T-031: find_kicks, player_blobs, suppress_touches, _box_gap and every T-031 constant are byte-identical.
- AC9: `find_touches(video, query)` calls `_analyse` exactly once. It returns [] when colours is None. Otherwise it returns the touches whose team == pick_team(query.team, colours), ignoring query.number, and it lets the tie ValueError propagate. `python -m sportscut player <synthetic_video> --team '#ff00ff' --number 7 --out DIR`, with _analyse patched to return ([], C), exits 2 and prints `sportscut player: error:` and `equally close` on stderr.
- AC10: On the built synthetic set, `python -m sportscut eval-player tests/fixtures/eval_player --json` gives:
- team_accuracy ≥ 0.95, touch_f1_any ≥ 0.9737, and per-clip touch_f1_any ≥ dribble 1.0, near_miss 1.0, number_hidden 1.0, short_passes 0.9091;
- f1 > 0.0, id_accuracy == 0.0, seconds_per_min ≤ 6.0.

For every case and every labelled query, each find_touches result is in detect_touches(clip) and has team == query.team. On short_passes, PlayerQuery('#c81e1e', 7) gives the same list as PlayerQuery('red', 7), and PlayerQuery('sky', 4) gives the same list as PlayerQuery('blue', 4). `python -m sportscut eval tests/fixtures/eval --json` f1 equals the Step 0 value.
- AC11: `python -m pytest -q` reports 0 failed. Pre-existing tests change only in the places listed in the spec:
- tests/test_player.py::test_detect_touches_stub_and_find_filters (its last two statements);
- tests/test_touches.py::test_eval_player_gate;
- tests/test_eval_player_fixtures.py::test_eval_player_cli_baseline_json and ::test_eval_player_indent_output (the f1/team/id asserts);
- tests/test_t031_acceptance.py::test_ac5_real_set_touch_shape, ::test_ac7_eval_player_gate and ::test_ac10_find_touches_empty.

No test is deleted, skipped or marked xfail.
- AC12: `git diff main -- sportscut/reframe.py sportscut/media.py sportscut/eval_player.py sportscut/cli.py sportscut/reel.py sportscut/api.py tests/conftest.py tests/fixtures/eval_player pyproject.toml` is empty. No .mp4 is tracked and no dependency is added. T-031's grep `subprocess|ffmpeg|green_mask|cumsum|def (sample_frames|field_mask|ball_candidates|track_ball)` on sportscut/player.py prints nothing.
- AC13: README.md has a new section `## Đội theo màu áo (T-032)` immediately before `## API HTTP`, with 0 deleted README lines vs main. The section contains:
- the --team name/#hex mapping and the 'equally close' error;
- the note that the reel holds every touch of the team until T-033;
- the known limitations (clashing kits, white/black/grey kits, one team visible);
- a ```text block whose TEAM_* values equal the module constants;
- `Trước T-032:` and `Sau T-032:`, each followed by a one-line ```json eval-player report from a real run, with the 'Sau' report having team_accuracy ≥ 0.95.

The T-031 and T-029 design specs each end their `## Existing specs this task changes` list with the exact T-032 bullet.
- AC14: Changed lines outside docs/superpowers total < 600, including new test files. The Developer report and PR body quote the before and after eval-player JSON, team_accuracy, touch_f1_any and seconds_per_min.

## Out of scope

- Jersey-number reading and filtering find_touches by number (T-033)
- Solving clashing kits, white/black/grey kits or shorts/socks colours
- Goalkeeper/referee identification beyond dropping small clusters; goalkeepers as their own team
- Caching _analyse between find_touches calls or eval queries
- Any change to eval_player.py metrics, labels, build.py or the synthetic clips
- Any change to reframe.py, media.py, the ball detector, field/player mask or kick detection constants
- CLI/API/web changes (the existing ValueError paths are reused), e.g. listing detected team colours to the user
- Tracking players across frames or across camera cuts
- New dependencies (scikit-learn, OpenCV) or vision models

## Decisions

- T-032 (R-006): Team attribution lives in sportscut/player.py and uses numpy only. reframe.py, media.py, eval_player.py, cli.py, reel.py and api.py are not changed.
- T-032 (R-006): The colour feature is the HSV cone [s·cos 2πh, s·sin 2πh, v] with Euclidean distance. Pixels are reframe.player_mask pixels with saturation ≥ TEAM_MIN_SAT, sampled at 1 Hz (every TEAM_EVERY=5th 5 Hz sample) and capped at TEAM_MAX_PIXELS by an even stride.
- T-032 (R-006): K-means is deterministic: farthest-point initialisation starting from the point nearest the mean (ties: lowest index), at most TEAM_ITERS=20 Lloyd iterations, and empty clusters keep their centroid. TEAM_K=4.
- T-032 (R-006): Outliers are removed by cluster size: clusters with < TEAM_MIN_SHARE of points are dropped. Survivors closer than TEAM_MERGE are merged (one kit split in two), largest first. The two largest remaining clusters are the teams. Fewer than two clusters, or fewer than TEAM_MIN_PIXELS pixels, means no teams (None).
- T-032 (R-006): Clusters are named with distinct TEAM_NAMES by minimising the summed distance to the TEAM_RGB palette, so Touch.team is always a normalized colour name and eval compares it to label names directly. TEAM_RGB values are fixed in the spec.
- T-032 (R-006): A touch's team is the majority vote of its blob's saturated shirt pixels over the two centroids (tie: the larger team). It is None when there are no teams or no saturated pixel.
- T-032 (R-006): --team mapping: an exact cluster name wins; otherwise the nearest centroid to the name's TEAM_RGB colour or the #hex colour. If |d0-d1| ≤ TEAM_TIE(0.05)·max(d0,d1), a ValueError containing 'equally close' and both names is raised; this surfaces as CLI exit 2 and API 422 through existing handlers.
- T-032 (R-006): A private _analyse(video) returns (touches, TeamColours|None) in one frame pass. detect_touches returns its touches. find_touches calls it once and returns every touch of the mapped team, ignoring the number until T-033. With no teams it returns [] rather than an error.
- T-032 (R-006): Tuning is allowed only for TEAM_MIN_SAT [0.15,0.40], TEAM_K [3,5], TEAM_MIN_SHARE [0.05,0.20] and TEAM_MERGE [0.05,0.30]. T-031 detection constants are frozen. If no setting meets the gate, the Developer reports BLOCKED with the best JSON.
- T-032 (R-006): Merge gate on the synthetic eval-player set:
- team_accuracy ≥ 0.95;
- touch_f1_any ≥ 0.9737 overall and per clip ≥ the T-031 README values;
- f1 > 0.0, id_accuracy == 0.0, seconds_per_min ≤ 6.0;
- `sportscut eval` f1 unchanged.

The before and after JSON goes in the README and the PR.
- T-032 (R-006): Allowed edits to pre-existing tests are only the T-031/T-029 asserts that pinned find_touches == [], f1 == 0, team None on the real set and the detect_touches-monkeypatch filter (exact list in the spec). No test is deleted or skipped.
- T-032 (R-006): The README section `## Đội theo màu áo (T-032)` is insert-only and placed immediately before `## API HTTP`, because test_t031_acceptance::test_ac13 pins the heading after the T-031 section.
- T-032 (R-006): Known limitations, documented and not solved: clashing kits, white/black/grey (low-saturation) kits, clips where only one team is visible (all give no teams or wrong teams), and a goalkeeper-dominated short clip.
- T-032 (R-006): The size budget is < 600 changed lines outside docs/superpowers including the Tester file (the T-031 precedent for one gated algorithmic slice). No new dependency. The Tester's diff-scope asserts run only on office/T-032* branches.
- Tech Lead (dev_blocked): 2026-11-27 T-032 (R-006) Tech Lead (dev_blocked, round 1): The T-032 code is fine. The 4 failing tests in tests/test_t050_acceptance.py (ac4, ac10, ac11, ac12) are the known defect where T-050's scope checks compare against main without checking the branch. T-047 (9859233, merged to main) already fixed it by adding the _own_branch() gate. office/T-032 fails only because its last merge with main is b517c32, which is older than 9859233. Decision: the office merges current main (9859233 or later) into office/T-032, then the Developer re-verifies. Neither option the developer offered is used: (a) would duplicate T-047's edit on this branch and cause a merge conflict; (b) has already been done on main. T-032 does not edit tests/test_t050_acceptance.py, and its file list and scope test stay as they are. tests/test_t020_acceptance.py::test_ac12_eval_gate (11.0 s against a 6.0 s budget) failed only when run in parallel with other pytest processes; it passed on its own and is not a T-032 issue.
- Tech Lead (dev_blocked): 2026-11-27 T-032 (R-006) Tech Lead (dev_blocked, round 2): The T-032 code is still fine. The real cause is the office, not the branch. A Tech Lead 'retry' on dev_blocked never merges the base into the worktree. agent_office/pipeline.py only calls wt.start_merge when task.merge_conflict is set, which happens for a merge_conflict retry or when _pr runs update_from_base, and _pr only runs after tests pass. So round 1's 'the office merges main first' could never happen, and the Developer correctly stopped again. office/T-032 is still based on b517c32 and lacks 9859233 (T-047's _own_branch() gate), so tests/test_t050_acceptance.py ac4/ac10/ac11/ac12 fail there and only there. Asking again would loop forever. Decision: restart. The office cuts office/T-032-r2 from current main, which contains 9859233, and keeps the old office/T-032 branch for reference. The Developer restores the reviewed work from 17be5da without re-deriving it: path checkout for the files main has not touched since b517c32, and a 3-way apply of the T-032-only README hunk. The office regenerates the design, plan, INDEX and DECISIONS rows. Agents still do not commit, merge or switch branches. tests/test_t050_acceptance.py is still not edited. The test_web wheel failure was a one-off: it passed on its own (1 passed) and is not a T-032 issue.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-031-detect-ball-touches-by-any-player-design.md`
- `docs/superpowers/specs/2026-11-23-t-029-build-the-player-touch-eval-synthetic-design.md`
- `docs/superpowers/specs/2026-11-23-t-030-add-sportscut-player-cli-that-cuts-design.md`
