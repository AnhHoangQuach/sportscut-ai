# Plan T-030: Add `sportscut player` CLI that cuts and concatenates a reel around each touch

Design: `docs/superpowers/specs/2026-11-23-t-030-add-sportscut-player-cli-that-cuts-design.md`.

## Implementation plan

# T-030: `sportscut player` cuts and joins a reel around each touch

Request R-006 (Vietnamese, roughly: "track a player: pick one player and export a compilation video of every ball touch by that player"). Builds on T-029 (`sportscut/player.py`: `PlayerQuery`, `Touch`, `find_touches`) and on R-001's T-003 (`sportscut.export.export_clips`, `sportscut.media.cut_clip`), T-036 (`sportscut.media`, `tests/conftest.py::require_ffmpeg`, `synthetic_video`) and T-035/T-002 (`sportscut/cli.py` argparse subcommands). No task called T-004 exists on main. The CLI it would have added already exists (T-035 + T-002 `detect` + T-029 `eval-player`), so the dependency is checked by import (Step 0).

## Goal
`sportscut player VIDEO --team T --number N --out DIR [--pre 3 --post 2 --merge-gap 4]` writes `DIR/player_<team>_<number>.mp4`, a reel of every touch by the queried player in time order, and `DIR/player.json`. Detection accuracy is not part of this task: `find_touches` is still the T-029 stub, and T-031..T-033 improve it without changing this command.

## Design

### 1. `sportscut/media.py`: add `concat_clips` (the only new ffmpeg call)
```python
def concat_clips(clips: list[str | Path], dest: str | Path) -> Path
```
- `clips` empty: `ValueError("no clips to concatenate")`.
- Any clip that is not a file: `MediaError(f"media file not found: {clip}")`, checked before tool lookup (T-036 rule).
- `ffmpeg = find_tool("ffmpeg")`.
- Write a concat list file in `Path(dest).parent` with `tempfile.NamedTemporaryFile(mode="w", suffix=".txt", dir=..., delete=False, encoding="utf-8")`. It has one line per clip: `file '<abs path>'`, using `str(Path(clip).resolve())` with every `'` replaced by `'\''`. Delete the list file in a `finally` block.
- Args (no shell): `[ffmpeg, "-v", "error", "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", <list>, "-c", "copy", "-movflags", "+faststart", str(dest)]`. Stream copy is safe because every input comes from `cut_clip` and was re-encoded with the same H.264/AAC settings.
- A non-zero exit raises `MediaError(f"ffmpeg failed for {dest}: {_failure_detail(stderr, rc)}")`.
- Returns `Path(dest)`.

### 2. New `sportscut/reel.py` (no `subprocess` import)
```python
from sportscut import player            # call player.find_touches(...) through the module so tests can monkeypatch sportscut.player.find_touches
from sportscut.export import export_clips
from sportscut.media import concat_clips, probe_duration
from sportscut.models import Segment

MANIFEST_NAME = "player.json"

def reel_name(query: player.PlayerQuery) -> str:
    # f"player_{query.team.lstrip('#')}_{query.number}.mp4", e.g. player_red_10.mp4, player_ff0000_7.mp4

def plan_windows(times: list[float], duration: float, pre: float, post: float,
                 merge_gap: float) -> list[tuple[float, float]]:
    # for t in sorted(times): start = max(0.0, t - pre); end = min(duration, t + post)
    # drop the window if end <= start (touch at or beyond duration + pre)
    # merge into the previous window when start - prev_end < merge_gap (strict; overlaps always merge)
    #   merged = (prev_start, max(prev_end, end))
    # returns windows sorted by start, values not rounded

def make_player_reel(video, query: player.PlayerQuery, out_dir, pre: float = 3.0,
                     post: float = 2.0, merge_gap: float = 4.0) -> dict:
```
`make_player_reel` does these steps in order:
1. Validate the options. Each failure raises `ValueError`, before any I/O:
   - `pre < 0`: `"--pre must be >= 0"`
   - `post < 0`: `"--post must be >= 0"`
   - `pre + post == 0`: `"--pre and --post cannot both be 0"`
   - `merge_gap < 0`: `"--merge-gap must be >= 0"`
   - any value that is not finite: same messages.
2. `duration = probe_duration(video)`. A missing file raises `MediaError` from media.
3. Call `touches = sorted(player.find_touches(video, query), key=lambda x: x.t)` exactly once. `video` is passed through as given.
4. Compute `windows = plan_windows([x.t for x in touches], duration, pre, post, merge_gap)`.
5. `out = Path(out_dir)`; `out.mkdir(parents=True, exist_ok=True)`.
6. If `windows` is not empty:
   - Inside `tempfile.TemporaryDirectory(prefix=".sportscut-cuts-", dir=out)` as `tmp`, call `clips = export_clips(video, [Segment(s, e, 0.0, "touch") for s, e in windows], tmp)`.
   - Then call `concat_clips(clips, out / reel_name(query))`.
   - The temp dir, the cut clips and the `highlights.json` that `export_clips` writes are all removed afterwards.
7. Build the manifest dict (below) and write it to `out / "player.json"` (`json.dumps(m, indent=2) + "\n"`, UTF-8). This happens only after the reel succeeds. Return the dict.

Manifest `player.json` (all times rounded with `round(x, 3)`):
```json
{
  "query": {"team": "red", "number": 10},
  "touches": [{"t": 1.0, "team": "red", "number": 10, "confidence": 0.9, "bbox": [1, 2, 3, 4], "start": 0.5, "end": 2.3}],
  "clips": [{"start": 0.5, "end": 2.3}, {"start": 4.0, "end": 5.0}],
  "total_duration": 2.8,
  "reel": "player_red_10.mp4"
}
```
- `touches`: every found touch, sorted by t. Each entry is `Touch.to_dict()` plus `start`/`end`: the bounds of the merged clip that contains the touch's own clamped window. Both are `null` when that window was dropped.
- `clips`: the merged windows in time order.
- `total_duration`: `round(sum(end - start), 3)`. It is `0.0` when there are no clips.
- `reel`: the bare file name, or `null` when there are no clips. In that case no mp4 is written.

### 3. `sportscut/cli.py`: add the `player` subparser
Arguments:
- `video`
- `--team` (required, str)
- `--number` (required, `type=int`)
- `--out` (required)
- `--pre` (float, default 3.0)
- `--post` (float, default 2.0)
- `--merge-gap` (float, default 4.0)

Handler:
```python
try:
    query = PlayerQuery(args.team, args.number)
    manifest = make_player_reel(args.video, query, args.out, args.pre, args.post, args.merge_gap)
except ValueError as exc:            # bad team/number/options
    print(f"sportscut player: error: {exc}", file=sys.stderr); return 2
except (MediaError, OSError) as exc: # missing video, ffmpeg failures
    print(f"sportscut player: error: {exc}", file=sys.stderr); return 1
```
On success it prints one line to stdout and returns 0:
- `manifest["reel"]` set: `wrote <out>/<reel>: <n> touches in <k> clips, <total_duration:.1f> s`
- otherwise: `no touches found for <team> <number>; wrote <out>/player.json`

The existing `detect`/`eval-player`/`--version`/no-args behaviour does not change. A non-integer `--number` (e.g. `abc`, `10.0`) or a missing required option is an argparse error (`SystemExit(2)`).

### 4. README.md
Add a short Vietnamese subsection `## Theo dõi cầu thủ: xuất video tổng hợp (player)` with the command example, the options and defaults, the output files and a note that touch detection is still a stub until T-031..T-033.

### 5. T-036 design spec
Append a line: `Updated by T-030: sportscut.media also owns joining clips with concat_clips (concat demuxer, stream copy of cut_clip outputs).`

## Files
- change `sportscut/media.py`: add `concat_clips` and `import tempfile`
- create `sportscut/reel.py`
- change `sportscut/cli.py`: add the `player` subparser and handler
- change `tests/test_media.py`: concat_clips tests
- create `tests/test_reel.py`: plan_windows, make_player_reel and CLI tests
- change `README.md`
- change `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md` (one appended line)

Not touched: `sportscut/player.py`, `sportscut/export.py`, `sportscut/models.py`, `sportscut/eval_player.py`, `tests/conftest.py`, `tests/test_cli.py`, `tests/test_player.py`, pyproject.toml, .gitignore, agent-office/, .github/.

## Steps (test-first; quote each red run, then the green run)
0. **Precondition.** Run `python -c "from sportscut.export import export_clips; from sportscut.media import cut_clip, probe_duration, MediaError; from sportscut.player import find_touches, PlayerQuery, Touch; from sportscut.cli import main; print('READY')" && grep -q 'def require_ffmpeg' tests/conftest.py`. It must print READY. Otherwise report `BLOCKED: T-030 needs export_clips/cut_clip/require_ffmpeg/cli from R-001 and player.py from T-029 on the base branch`, change nothing and do not re-create them.
1. **plan_windows.**
   - Red: write the plan_windows tests in `tests/test_reel.py` and run `python -m pytest -q tests/test_reel.py`. Expect `No module named 'sportscut.reel'`.
   - Green: create `reel.py` with `plan_windows` and `reel_name`.
2. **concat_clips.**
   - Red: write the concat_clips tests in `tests/test_media.py`. Expect `cannot import name 'concat_clips'`.
   - Green: implement `concat_clips`.
3. **make_player_reel.**
   - Red: write the make_player_reel tests (monkeypatched `sportscut.player.find_touches`). Expect `cannot import name 'make_player_reel'`.
   - Green: implement it.
4. **CLI.**
   - Red: write the CLI tests. Expect `invalid choice: 'player'` or SystemExit 2.
   - Green: add the subparser and handler.
5. README section and the T-036 spec line.
6. **Verify.**
   - `python -m pytest -q` passes with 0 failed, errors or skips.
   - `PATH=/nonexistent python -m pytest -q -rs` passes, and every skip reason is `ffmpeg and ffprobe are required on PATH`.
   - `git ls-files '*.mp4'` is empty.
   - `git diff --stat main...HEAD` is under 400 lines.
   - Manual smoke run, which must exit 0 and print `no touches found for red 10`: `ffmpeg -v error -f lavfi -i color=c=green:s=160x120:r=10:d=8 -f lavfi -i anoisesrc=d=8 -shortest -c:v mpeg4 -c:a aac /tmp/m.mp4 && python -m sportscut player /tmp/m.mp4 --team red --number 10 --out /tmp/reel`.

## Assumptions
- A merge happens when the gap is strictly less than `--merge-gap`. Overlapping windows always merge, even with gap 0.
- Touch windows are clamped to `[0, probe_duration(video)]` before merging. A window that becomes empty is dropped, and its touch is still listed with `start`/`end` = null.
- Intermediate cuts live in a hidden temp dir inside `--out`, on the same disk, and are deleted afterwards. `--out` ends up with only the reel and `player.json` (plus whatever was there before).
- Stale reels from earlier runs are not deleted. A zero-touch run writes `reel: null` and leaves other files alone.
- Product reels need an ffmpeg built with libx264, as T-003 decided for clips.

## Test plan

- tests/test_reel.py::test_plan_windows_* (no ffmpeg): parametrized cases from AC2, including the strict gap boundary, clamping at 0 and at duration, a dropped window, unsorted input and the overlap-with-gap-0 case; use pytest.approx for the 18.9 case
- tests/test_reel.py::test_reel_name: AC3
- tests/test_media.py::test_concat_clips_empty_raises_value_error, ::test_concat_clips_missing_clip (monkeypatch PATH to an empty tmp dir), ::test_concat_clips_bad_file (text file bad.mp4, needs require_ffmpeg)
- tests/test_media.py::test_concat_clips_joins_in_order (synthetic_video): cut 0.5-1.5 to a.mp4 and 4.0-5.0 to "it's.mp4" with cut_clip, concat into dest; assert duration ≈ 2.0 ±0.5, gray mean < 64 at 0.3 s and > 192 at 1.5 s (reuse a local _gray_mean helper like tests/test_export.py), and no *.txt in dest.parent
- tests/test_reel.py::test_player_cli_cuts_merges_and_joins (synthetic_video, monkeypatch sportscut.player.find_touches with a recording fake): AC5 + AC6 exact manifest dict, out dir contents, reel duration and frame checks, single call with the normalized query
- tests/test_reel.py::test_player_cli_default_options_clamp_and_merge (synthetic_video): AC7
- tests/test_reel.py::test_player_cli_zero_touches and ::test_player_touch_beyond_video_is_dropped (synthetic_video): AC8
- tests/test_reel.py::test_player_cli_rejects_bad_query_and_options (no ffmpeg, parametrized; the fake find_touches asserts it is never called; video path may be nonexistent): AC9
- tests/test_reel.py::test_player_cli_number_not_int_is_usage_error: pytest.raises(SystemExit) with code 2
- tests/test_reel.py::test_player_cli_missing_video (no ffmpeg): AC10
- tests/test_reel.py::test_help_lists_player: AC11
- tests/test_reel.py::test_reel_module_does_not_import_subprocess: AC12 (AST walk, same pattern as tests/test_export.py)
- Fixtures: only the existing session fixtures `synthetic_video` and `require_ffmpeg` from tests/conftest.py (unchanged). No new media fixture, nothing written outside tmp_path.
