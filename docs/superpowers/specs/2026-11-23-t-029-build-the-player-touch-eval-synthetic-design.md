# T-029: Build the player-touch eval: synthetic labelled clips, `sportscut eval-player --json`, and a baseline

Request R-006. Plan: `docs/superpowers/plans/2026-11-23-t-029-build-the-player-touch-eval-synthetic.md`.

## Product Owner request

Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó.

## Goal

Goal of R-006: `sportscut player match.mp4 --team red --number 10 --out DIR` writes `player_red_10.mp4`, a reel of every ball touch by that player, plus `player.json` listing each touch (t, start, end, confidence). We know it works when `sportscut eval-player tests/fixtures/eval_player --json` prints `{"f1", "precision", "recall", "touch_f1_any", "team_accuracy", "id_accuracy", "seconds_per_min", "per_clip": [...]}` with F1 ≥ 0.85 for the queried player on the synthetic set. A predicted touch matches a label when it is within ±0.5 s, and each label matches at most one prediction. Approaches considered: (a) cheap numpy heuristics on sparse ffmpeg frames: ball blob near a player blob plus a change in ball direction or speed counts as a touch; shirt-colour clustering gives the team; the jersey number is read only on the toucher's crop around each touch, through a pluggable reader with an optional OCR extra; (b) a YOLO and ByteTrack tracker with re-ID across the whole match; (c) a user click on one frame, then appearance tracking. We pick (a) because it fits the CPU budget, needs no model for the base install, and reuses R-004's field mask and ball detector. (b) breaks the performance budget, and (c) cannot re-find the player after camera cuts, since teammates look alike. This task adds `sportscut/player.py` with `PlayerQuery(team: str, number: int)`, `Touch(t, team, number, confidence, bbox)` and a stub `find_touches(video, query) -> []`, so the baseline is F1 = 0 and is recorded in the README. It also adds `tests/fixtures/eval_player/build.py`, which generates 3-4 idempotent clips (gitignored mp4, 640x360, 25 fps, 20-40 s): a green pitch, two teams of coloured rectangles with bitmap-font numbers, and a ball passed along a known script. The cases are short passes, a dribble with repeated touches, a near-miss where the ball passes a player without a touch, and the number turned away during the touch. Each clip gets a committed `labels.json` (`{"touches": [{"t", "team", "number"}]}`) covering all players, so the eval can query several players per clip. Assumptions: a player is chosen by team shirt colour (a name like red/blue or a #hex) plus jersey number, because that is how a fan names a player and it survives camera cuts. The footage is a normal TV broadcast, as in the rest of the product. Replays may count a touch twice; dedup is out of scope. The PO can hand-label real matches in `data/eval_player/` in the same format.

## Acceptance criteria

- AC1: Step 0 prints READY on the base before any file is changed. If it does not, the developer reports the BLOCKED message and changes nothing. Files from T-035/T-036 (pyproject.toml, media.py, models.py, conftest.py) are not modified; cli.py only gains the subcommand.
- AC2: `PlayerQuery(' RED ', 10).team == 'red'` and `PlayerQuery('#FF0000', 7).team == '#ff0000'`. `PlayerQuery('maroon', 10)` raises ValueError whose message lists the valid names and '#rrggbb'. Numbers 0, 100, '10', 10.0 and True each raise ValueError. PlayerQuery is hashable.
- AC3: `Touch(t=1.5, team='Blue', number=4, confidence=0.8, bbox=(1,2,16,32)).to_dict()` returns exactly `{'t': 1.5, 'team': 'blue', 'number': 4, 'confidence': 0.8, 'bbox': [1, 2, 16, 32]}`. `json.dumps` works on it even when the fields are numpy scalars. A negative t or a confidence outside [0,1] raises ValueError. team, number and bbox may be None.
- AC4: `detect_touches(path)` returns [] (the baseline stub). `find_touches(path, query)` returns the detect_touches results whose team and number equal the query; checked by monkeypatching detect_touches.
- AC5: `load_labels` returns touches sorted by t and queries as the sorted union of `players` and touch authors. It raises ValueError naming the file (and the entry index where applicable) for: a non-object top level, missing or non-list touches, a non-list players, missing/non-numeric/bool/negative t, and an invalid team or number.
- AC6: `match_times` is a one-to-one maximum matching with an inclusive ±0.5 s tolerance:
- pred [1.0,2.0,5.0] vs truth [1.4,2.6,5.5] gives 2 pairs
- pred [3.0,3.2] vs [3.1] gives 1 pair
- pred [3.0] vs [2.6,3.4] gives 1 pair
- pred [1.0,1.6] vs [1.5,2.0] gives 2 pairs
- pred [5.0,1.0] vs [1.2] gives [(1,0)], i.e. pairs use the original indices of unsorted inputs

`prf(0,0,0) == (0.0, 0.0, 0.0)`, and `prf(2,1,1)` gives precision, recall and f1 all equal to 2/3.
- AC7: `score_clip` and `metrics` give hand-computed values:
- Queried-player tp/fp/fn are counted per query against that player's labels only. A touch found for A near B's label is an FP for A.
- touch_f1_any uses all labels.
- team_accuracy and id_accuracy are computed over matched any-touch pairs, and are None when there are none.
- Floats are rounded to 4 decimals.
- AC8: `build_all(dir)` creates `dir/{dribble,near_miss,number_hidden,short_passes}/{clip.mp4,labels.json}`.
- ffprobe reports mpeg4, 640x360, 25/1 fps, and a duration within 0.1 s of the case duration. Every duration is between 20 and 40 s.
- A second `build_all(dir)` changes no clip.mp4 mtime and no labels.json byte.
- `git ls-files '*.mp4'` is empty.
- AC9: Each committed `tests/fixtures/eval_player/<case>/labels.json` equals `build.case_labels(name)` (checked without ffmpeg).
- Across the set there are ≥ 35 touches, ≥ 17 queries, and touches by both teams.
- At least one case queries two players with the same number in different teams.
- In every case, touch times are multiples of 0.2 s, ≥ 1.2 s apart (> 2×tolerance + 0.1 s, so a +0.6 s shift cannot match the next touch), with the first ≥ 1.0 s and the last ≤ duration - 2 s.
- AC10: Ball physics in the generator:
- At every labelled touch, the ball centre is within 8 px of the toucher's box.
- The ball velocity changes at every touch: angle ≥ 25° or speed ratio ≥ 1.5, measured over 0.2 s before and after. A stationary-to-moving change counts.
- Sampled every 0.04 s, the ball centre is never inside any player box.
- AC11: The near_miss case has at least 2 moments, each ≥ 1.0 s from any touch, where a player with zero touch labels (listed in `players`) is 6–14 px from the ball centre (distance to the nearest box point), while the ball keeps a constant velocity (angle change < 5°, speed ratio within 1.1).
- AC12: In number_hidden, `render_frame` at each blue 8 touch time has no pixel ≥ 200 on all channels inside blue 8's box, excluding the ball disk. At a time ≥ 1.2 s from any blue 8 touch, the box has ≥ 10 such digit pixels.
- AC13: In the decoded clip frame at each touch time (ffmpeg -ss t -frames:v 1, rawvideo rgb24):
- the pixel at the rounded ball centre is ≥ 200 on all channels
- the pixel at (box centre x, box y + h - 4) is within 40 per channel of the toucher's team RGB
- AC14: `python -m sportscut eval-player <built set> --json` exits 0 and prints exactly one line of JSON.
- The top-level keys are exactly f1, precision, recall, touch_f1_any, team_accuracy, id_accuracy, seconds_per_min, per_clip.
- per_clip has 4 entries sorted by clip name, each with clip, duration, touches, queries and the 7 metrics.
- The baseline has f1 = precision = recall = touch_f1_any = 0.0 and team_accuracy = id_accuracy = null. seconds_per_min is a float ≥ 0.
- AC15: The eval discriminates. With `sportscut.player.detect_touches` and `find_touches` monkeypatched to an oracle built from each clip's labels.json:
- evaluate_dir gives f1 = touch_f1_any = team_accuracy = id_accuracy = 1.0
- with oracle times shifted by +0.5 s, f1 is still 1.0
- with a +0.6 s shift, f1 = 0.0 and touch_f1_any = 0.0
- AC16: `sportscut eval-player` returns 2 and prints `sportscut eval-player: error:` on stderr for a missing directory, a directory with no cases, and a case with labels.json but no clip.mp4 (that message mentions build.py). Without --json it prints indented multi-line JSON. `--version` and no-args help behave as before.
- AC17: README has the eval-player section: the commands, the label format, the data/eval_player layout, the ±0.5 s matching rule, the baseline JSON copied from a real run in this session, and the targets for T-031, T-032 and T-033. The T-036 design spec has the eval-player exception bullet.
- AC18: `python -m pytest -q` passes with every existing test still green, and the non-ffmpeg tests pass with PATH=/nonexistent (ffmpeg tests skip). Nothing under agent-office/ or .github/ changes, and no media is committed.

## Out of scope

- Any real touch detection, ball or player blob finding, field mask, team colour clustering or jersey number reading (T-031, T-032, T-033). The detect_touches stub stays [].
- The `sportscut player` command, reel cutting/concatenation, player.json output, and options such as --pre/--post/--min-confidence (T-030, T-033).
- An API endpoint or web form for player reels.
- An OCR or [ocr] extra, a NumberReader protocol, YOLO/ByteTrack, or any model download.
- Replay deduplication, camera cuts, close-ups and broadcast overlays in the synthetic clips.
- Making eval-player a merge-blocking gate in .agent-office/config.toml or a CI workflow.
- A labelling tool for the PO's real matches, or video names other than clip.mp4.
- Human-readable table output (JSON only, compact or indented).
- Changing pyproject.toml, media.py, models.py, conftest.py, .gitignore or anything under agent-office/.
- Committing any .mp4 or real footage.

## Decisions

- T-029 depends on T-035 + T-036 (the split of T-001), not on T-001. Step 0 checks pyproject.toml, cli.main, media.probe_duration, media.MediaError and conftest.require_ffmpeg, and it prints READY on the current main.
- A player is chosen by normalized team colour (one of TEAM_NAMES, or #rrggbb, stripped and lowercased) plus jersey number 1-99 (a real int). Team equality is plain string equality after normalization.
- sportscut.player exposes detect_touches(video) for all touches and find_touches(video, query) for the queried player. The eval calls both separately, so find_touches may later stop being a plain filter.
- Labels live in <DIR>/<case>/labels.json, next to a fixed clip.mp4. They hold required touches [{t, team, number}] and optional players [{team, number}]. Queries are the union of both. Real matches go in data/eval_player/ in the same format.
- Matching is a one-to-one maximum matching with |pred - label| <= 0.5 s inclusive (+1e-9), using a two-pointer pass on sorted times.
- Metrics are micro-averaged over all clips and queries. Zero denominators give 0.0. team_accuracy and id_accuracy are computed over matched any-touch pairs and are null when there are none. Floats are rounded to 4 decimals.
- seconds_per_min = total find_touches wall time / (duration x number of queries / 60), i.e. the cost of one player reel per minute of video.
- The eval-player CLI prints compact one-line JSON with --json and indent=2 JSON otherwise. User errors (ValueError, OSError, MediaError) print `sportscut eval-player: error: <msg>` and exit 2.
- build.py is standalone (it never imports sportscut), deterministic and data-driven. It encodes with the built-in mpeg4 encoder (-q:v 2, yuv420p, no audio), following T-036's no-libx264 rule.
- Exception to T-036's 'media only in pytest temp dirs': build.py may write git-ignored clip.mp4 files into tests/fixtures/eval_player/ for the eval command. pytest builds the set only in temp dirs, and no media is ever committed. The T-036 design spec gets a bullet saying this.
- The synthetic set is 4 cases (short_passes, dribble, near_miss, number_hidden) with 39 touches. Touch times are on 0.2 s frames and ≥ 1.2 s apart. In short_passes, receiver touches use 5.2/11.2/14.2/17.6; the dribble zig-zags because the dribbler's own keyframes alternate ±14 px at 1.2 s intervals.
- Synthetic feet use `cy + SHIRT_H/2 + BALL_R + 4`, giving the ball enough clearance from interpolating player boxes between touches while remaining within AC10's 8 px touch proximity.
- The baseline (stub) report is f1 = precision = recall = touch_f1_any = 0.0 and team_accuracy = id_accuracy = null, recorded in README from a real run.
- Tech Lead (dev_blocked): 2026-11-23 T-029: restart from the latest base after T-001 merges; the clean branch correctly stopped because its required scaffold exists only on office/T-001, not on T-029's base.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`
