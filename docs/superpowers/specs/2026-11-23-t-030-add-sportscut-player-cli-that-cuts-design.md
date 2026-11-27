# T-030: Add `sportscut player` CLI that cuts and concatenates a reel around each touch

Request R-006. Plan: `docs/superpowers/plans/2026-11-23-t-030-add-sportscut-player-cli-that-cuts.md`.

## Product Owner request

Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó.

## Goal

Wire `sportscut player VIDEO --team T --number N --out DIR [--pre 3 --post 2 --merge-gap 4]`. It calls `find_touches`, pads each touch 3 s before and 2 s after, merges windows closer than the merge gap, clamps them to the video duration, cuts the clips with R-001's `export_clips`, and joins them in time order into `player_<team>_<number>.mp4` plus `player.json` (query, touches, clip windows, total duration). This lands early so the feature is usable from the start, and each later task only improves accuracy. Zero touches gives a clear message, a manifest with an empty list and no reel, with exit code 0. A bad `--team` or `--number` exits non-zero. Tests monkeypatch `find_touches` with known touches on the conftest synthetic video and check that merged windows match the reel duration within 0.5 s and that the manifest is correct. Assumptions: this starts after R-001's T-003/T-004 (`export_clips`, `require_ffmpeg`, CLI) are on main; if they are missing, report BLOCKED and do not re-create them. Concat uses the ffmpeg concat demuxer over clips that are already re-encoded.

## Acceptance criteria

- AC1: Step 0 prints READY on the base before any file changes. If it does not, the developer reports the BLOCKED message, changes nothing and re-creates no R-001/T-029 code.
- AC2: `plan_windows` (no ffmpeg needed):
- `([12, 10, 30], 100, 3, 2, 4)` == `[(7, 14), (27, 32)]`
- `([10, 19], 100, 3, 2, 4)` == `[(7, 12), (16, 21)]` (a gap exactly equal to merge_gap is not merged)
- `([10, 18.9], 100, 3, 2, 4)` ≈ `[(7, 20.9)]`
- `([1.0], 6.0, 3, 2, 4)` == `[(0.0, 3.0)]`
- `([5.5], 6.0, 1, 2, 0)` == `[(4.5, 6.0)]`
- `([10], 6.0, 3, 2, 4)` == `[]`
- `([], 6.0, 3, 2, 4)` == `[]`
- `([1, 2], 10, 1, 1, 0)` == `[(0, 3)]` (overlap merges with gap 0)
- AC3: `reel_name(PlayerQuery('RED', 10)) == 'player_red_10.mp4'` and `reel_name(PlayerQuery('#FF0000', 7)) == 'player_ff0000_7.mp4'`.
- AC4: `concat_clips`:
- `[]` raises `ValueError`.
- A missing clip raises `MediaError` exactly `media file not found: <path>`, even with PATH=/nonexistent.
- A text file named `bad.mp4` raises `MediaError` matching `^ffmpeg failed for .+: .+`.
- Two `cut_clip` outputs of the synthetic video (0.5-1.5 s, then 4.0-5.0 s, the second named `it's.mp4`) concatenated into `dest` return `dest`, with `probe_duration(dest)` within 0.5 s of 2.0.
- Its 8x6 gray mean is < 64 at 0.3 s and > 192 at 1.5 s.
- After the call, `dest.parent` holds no leftover `.txt` file.
- AC5: With `sportscut.player.find_touches` monkeypatched to return red 10 touches at t = 4.5, 1.0, 1.8 (in that order; confidences 0.8, 0.9, 0.7; bbox (1,2,3,4) on the 1.0 touch, otherwise None), `main(['player', synthetic, '--team', 'RED', '--number', '10', '--out', out, '--pre', '0.5', '--post', '0.5', '--merge-gap', '0.5'])`:
- returns 0 and calls the fake exactly once, with `(synthetic, PlayerQuery('red', 10))`
- leaves `out` holding exactly `{'player_red_10.mp4', 'player.json'}`
- produces a reel whose `probe_duration` is within 0.5 s of 2.8 (= the merged windows 0.5-2.3 + 4.0-5.0)
- produces a reel whose gray mean is < 64 at 0.3 s and > 192 at 2.2 s (time order kept)
- prints a stdout line containing `player_red_10.mp4` and `3 touches in 2 clips`
- AC6: After AC5, `player.json` parses to exactly:
```json
{"query": {"team": "red", "number": 10},
 "touches": [
   {"t": 1.0, "team": "red", "number": 10, "confidence": 0.9, "bbox": [1, 2, 3, 4], "start": 0.5, "end": 2.3},
   {"t": 1.8, "team": "red", "number": 10, "confidence": 0.7, "bbox": null, "start": 0.5, "end": 2.3},
   {"t": 4.5, "team": "red", "number": 10, "confidence": 0.8, "bbox": null, "start": 4.0, "end": 5.0}],
 "clips": [{"start": 0.5, "end": 2.3}, {"start": 4.0, "end": 5.0}],
 "total_duration": 2.8,
 "reel": "player_red_10.mp4"}
```
- AC7: With the default options and fake touches at 1.0 and 5.5 on the 6 s synthetic video:
- the manifest has `clips == [{'start': 0.0, 'end': round(probe_duration(synthetic), 3)}]` (clamped and merged)
- the reel duration is within 0.5 s of `probe_duration(synthetic)`
- AC8: With find_touches faked to return `[]`:
- `main(['player', synthetic, '--team', 'red', '--number', '10', '--out', out])` returns 0.
- stdout contains `no touches found for red 10`.
- `player.json` == `{'query': {'team': 'red', 'number': 10}, 'touches': [], 'clips': [], 'total_duration': 0.0, 'reel': None}`.
- No `.mp4` exists in `out`.
- With one fake touch at t=10 on the 6 s video (pre 3), the manifest has that touch with `start`/`end` None, `clips == []`, `reel` None, and no mp4.
- AC9: Bad query or options (no ffmpeg needed):
- `--team maroon` returns 2, and stderr starts with `sportscut player: error: unknown team colour`.
- `--number 0` and `--number 100` return 2, and stderr contains `player number must be an integer from 1 to 99`.
- `--number abc` raises SystemExit with code 2.
- `--pre -1`, `--post -1`, `--merge-gap -1` and `--pre 0 --post 0` each return 2 with a `sportscut player: error:` message.
- In every case the fake find_touches is never called and `--out` is not created.
- AC10: A missing VIDEO returns 1 with stderr exactly `sportscut player: error: media file not found: <path>`, even with PATH=/nonexistent. `out` is not created and find_touches is not called.
- AC11: `main([])` help output lists `player`. The existing detect, eval-player and --version tests stay green unchanged.
- AC12: `sportscut/reel.py` does not import `subprocess` (AST check). All ffmpeg calls go through `sportscut.media`.
- AC13: Suite checks:
- `python -m pytest -q` exits 0 with 0 failed, 0 errors and 0 skipped on a machine with ffmpeg+libx264.
- `PATH=/nonexistent python -m pytest -q -rs` exits 0, and every skip reason is exactly `ffmpeg and ffprobe are required on PATH`.
- `git ls-files '*.mp4' '*.mkv' '*.wav'` is empty, and no media is left in the worktree outside `.venv`.
- AC14: The diff touches only the files listed in the spec (plus orchestrator-written docs/superpowers records), stays under 400 changed lines, and changes nothing under agent-office/, .github/, pyproject.toml, .gitignore, tests/conftest.py, sportscut/player.py or sportscut/export.py. README has the player subsection, and the T-036 design spec has the `Updated by T-030` line. The report quotes the red runs (`No module named 'sportscut.reel'`, `cannot import name 'concat_clips'`, `cannot import name 'make_player_reel'`, the CLI failure), each followed by a green run.

## Out of scope

- Any real touch detection, team clustering or number reading (T-031..T-033); find_touches stays the T-029 stub
- --min-confidence, confidence filtering, replay dedup, or slow-motion/transition effects between clips
- Overlays, captions, a title card, or audio crossfades in the reel
- Keeping per-touch clip files or highlights.json in --out
- Deleting stale reels from earlier runs in --out
- An encoder fallback when libx264 is missing; configurable codec/quality
- Re-encoding during concat (the concat demuxer with -c copy only)
- Changes to export_clips, cut_clip, PlayerQuery/Touch, the eval-player command or the eval set
- An HTTP API or web form for player reels
- Progress output, parallel cutting, subprocess timeouts
- Changing pyproject.toml, .gitignore, tests/conftest.py, agent-office/ or .github/

## Decisions

- T-030 (R-006): the 'T-003/T-004 on main' precondition is checked by importing export_clips, cut_clip, probe_duration, MediaError, find_touches and cli.main, and by finding require_ffmpeg in conftest; no T-004 task exists, and the CLI it would add is already on main (T-035/T-002/T-029)
- T-030 (R-006): reel logic lives in a new module sportscut/reel.py (plan_windows, reel_name, make_player_reel), not in sportscut/player.py, so T-031..T-033 detection work does not conflict with it
- T-030 (R-006): reel.py calls player.find_touches through the module attribute, so tests and the eval monkeypatch sportscut.player.find_touches, matching T-029's pattern
- T-030 (R-006): touch windows are [max(0, t - pre), min(duration, t + post)] with duration from probe_duration. Windows are built from touches sorted by t; a window with end <= start is dropped; a window merges into the previous one when start - prev_end < merge_gap (strict), so overlaps always merge. Defaults are pre 3, post 2, merge_gap 4
- T-030 (R-006): option rules are pre >= 0, post >= 0, pre + post > 0, merge_gap >= 0, all finite. They are checked before any I/O and raise ValueError
- T-030 (R-006): concatenation is sportscut.media.concat_clips(clips, dest). It uses the ffmpeg concat demuxer (-f concat -safe 0, a temp list file of absolute single-quote-escaped paths next to dest, deleted afterwards) with -c copy -movflags +faststart over cut_clip outputs. sportscut.media stays the only module that calls ffmpeg
- T-030 (R-006): clips are cut with the unchanged export_clips into a hidden TemporaryDirectory inside --out (same disk), which is removed afterwards. --out keeps only player_<team>_<number>.mp4 and player.json. Segments passed to export_clips use score 0.0 and reason 'touch'
- T-030 (R-006): the reel name is player_<team without leading '#'>_<number>.mp4, e.g. player_red_10.mp4 or player_ff0000_7.mp4
- T-030 (R-006): player.json is {query:{team,number}, touches:[Touch.to_dict() + start/end of the containing merged clip, or null if dropped], clips:[{start,end}], total_duration, reel: file name or null}. Times are rounded to 3 decimals; the file is indent=2 JSON with a trailing newline, UTF-8. It is written last, only after the reel succeeds
- T-030 (R-006): when there are no clip windows (zero touches, or all outside the video), no mp4 is written, the manifest has reel null and total_duration 0.0, stdout says `no touches found for <team> <number>; wrote <out>/player.json`, and the exit code is 0
- T-030 (R-006): CLI exit codes: ValueError (bad team, number or options) prints `sportscut player: error: <msg>` and exits 2; MediaError/OSError (missing video, ffmpeg failure) prints the same prefix and exits 1; argparse errors (non-int --number, missing required option) exit 2. The query and options are validated before the video is probed or find_touches is called, and --out is created only after validation and probing succeed

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`

## Updated by T-040

- `POST /players` now wraps `make_player_reel` for either a new upload or an
  existing API job, and the manifest-authorized reel route serves its current
  mp4. The earlier HTTP-API exclusion applied to T-030's CLI scope only.

## Updated by T-032

- Updated by T-032 (2026-11-27): find_touches is no longer the T-029 stub. It returns every touch by the
  queried team (`--team` name or #rrggbb mapped to the nearest shirt-colour cluster; number ignored until
  T-033), so `sportscut player` now writes a non-empty reel. A team colour equally close to both clusters
  raises ValueError, which reuses this spec's exit-2 / HTTP 422 path. The CLI contract above is unchanged.
