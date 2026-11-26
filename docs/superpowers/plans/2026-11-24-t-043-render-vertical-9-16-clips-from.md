# Plan T-043: Render vertical 9:16 clips from a crop path and add `sportscut cut --vertical`

Design: `docs/superpowers/specs/2026-11-24-t-043-render-vertical-9-16-clips-from-design.md`.

## Implementation plan

# T-043 (restart from main @ 9aa5a85): Render vertical 9:16 clips from a crop path and add `sportscut cut --vertical`

Request R-004. PO request: "Tự xuất video dọc 9:16 cho TikTok/Reels: tự bám theo bóng và cầu thủ để crop, có phụ đề và tỉ số".

This is T-018b, the second half of the T-018 split. Its dependency is now **T-044** (merged as 9aa5a85). T-044 re-landed T-017/T-042's `sportscut/reframe.py` (`crop_width`, `sample_times`, `plan_crop`), `media.probe_size` and `eval-crop`.

**Source of truth.** The T-018 design and plan files named in the brief were never committed. This document replaces the blocked T-043 spec and plan from the wip commit e3d392c (`docs/superpowers/specs/2026-11-24-t-043-...-design.md`, `plans/2026-11-24-t-043-....md`), which never reached main. The design and AC1-AC14 are T-018's, word for word. Items marked **[r2]** are base-specific changes the PM found by reading main @ 9aa5a85:

1. Step 0 now prints READY. The PM ran it on 9aa5a85.
2. E1 and E2 are probably no longer needed (see the scope-test section).
3. The T-036 note must be **inserted before** that spec's final `Updated by T-004` paragraph, not appended at the end, because `tests/test_t004_acceptance.py::test_documentation_acceptance` asserts the file ends with that paragraph.
4. Two T-042 tests apply to this task: the shared-file append-only tests and the README-ends-with-eval-crop tests.

## Context (main @ 9aa5a85, 2026-11-26)

- `sportscut cut VIDEO --out DIR [--top --min-len --max-len --events]` calls `run(args.video, args.out, top=..., min_len=..., max_len=..., events=args.events,)`. The call spans several lines and `events=args.events,` has its own line (cli.py ~165-169). The CLI then prints `Path(args.out) / entry["file"]` for each entry (cli.py ~173-174) and returns 0. `(PipelineError, MediaError)` → `sportscut: error: <msg>` on stderr, exit 1.
- `pipeline.run(video, out_dir, top=10, min_len=10, max_len=30, events=None)`:
  - It imports `from sportscut.media import MediaError, has_audio, require_ffmpeg`.
  - It runs find_highlights → tag_goals → tag_incidents → tag_saves → select_segments.
  - Then `export_clips(video, segments, out_dir)` writes `DIR/clip_NN.mp4` and `DIR/highlights.json` (`json.dumps(entries, indent=2) + "\n"`, keys start, end, score, reason, event, event_confidence, file).
  - It ends with `manifest = Path(out_dir) / MANIFEST_NAME` / `return json.loads(manifest.read_text(encoding="utf-8"))`.
- Reframe contract (T-017/T-042/T-044):
  - `reframe.plan_crop(video, aspect=9/16) -> list[(t, x_center)]`, with t in seconds from the clip start, strictly increasing, at 5 Hz.
  - `reframe.crop_width(W, H)` is even and covers the full height: 202 for 640x360, 66 for 160x120.
  - The centre is linearly interpolated and held at the ends (np.interp). Rendering must use the same interpolation.
  - `plan_crop` returns a static `W/2` today. T-019 tracking replaces it later, and this task picks that up automatically.
- T-036: `sportscut.media` is the only module in sportscut/ that runs ffmpeg/ffprobe (the only `import subprocess`). New helpers follow `cut_clip`'s pattern:
  1. `p.is_file()` check → `MediaError("media file not found: ...")`;
  2. `find_tool("ffmpeg")`;
  3. `subprocess.run(args, capture_output=True, check=False)`;
  4. on a non-zero return code, `MediaError(f"ffmpeg failed for {path}: {_failure_detail(result.stderr, result.returncode)}")`.
- Fixtures in `tests/conftest.py` (do not change): `require_ffmpeg`, `synthetic_video` (160x120, 6 s, aac audio) and `burst_video` (160x120, 90 s, aac audio, bursts at 20/50/75 s).
- Tests already on main that constrain this diff (all must stay green):
  - `tests/test_t042_round2_acceptance.py::test_ac3_shared_files_are_append_only` and `tests/test_t042_tester_acceptance.py::test_ac3_shared_files_are_append_only_and_existing_commands_work`: 0 deleted lines against `git merge-base main HEAD` for sportscut/media.py, sportscut/cli.py, tests/test_media.py, tests/test_cli.py, README.md, docs/superpowers/DECISIONS.md, docs/superpowers/INDEX.md and the T-036 design spec.
  - `test_t042_round2_acceptance::test_ac7_*` and `test_t042_tester_acceptance::test_ac7_documentation_is_the_reviewed_trailing_section`: README must still **end with** the reviewed `## Video dọc 9:16: đo khung cắt (eval-crop)` section.
  - `test_t004_acceptance::test_documentation_acceptance`: the T-036 spec, after rstrip, must end with the `Updated by T-004: sportscut.media also exposes require_ffmpeg() ...` paragraph.
  - `test_t012_acceptance`: the T-004 spec's AC1 line must still contain `events=None`.
  - `test_t015_acceptance::test_ac15_*`: README has 0 removed lines.
  - `test_t042_*::test_ac10_*`: no change to evaluate.py, eval_player.py, export.py, pyproject.toml, tests/conftest.py, agent-office/, .gitignore or AGENTS.md, and no tracked .mp4.

## Step 0: preconditions (run first, on the untouched base)

```
grep -q 'def plan_crop' sportscut/reframe.py && grep -q 'def crop_width' sportscut/reframe.py && grep -q 'def probe_size' sportscut/media.py && echo READY || echo BLOCKED
```

- [r2] The PM ran this on main @ 9aa5a85 and it printed **READY**.
- If it prints BLOCKED on your base, stop and change nothing. Report BLOCKED and quote `grep -n 'def ' sportscut/reframe.py` and `grep -n 'def probe_size' sportscut/media.py`. Never recreate reframe.py or probe_size.
- 0b. Record these on the untouched base:
  - the `python -m pytest -q` summary line. It must say 0 failed; otherwise report BLOCKED with the failing ids.
  - BASE_F1 = the `f1` from `python -m sportscut eval tests/fixtures/eval --json`.
  - BASE_CROP = the output of the two commands in README's `## Video dọc 9:16: đo khung cắt (eval-crop)` section: `python tests/fixtures/eval_crop/build.py`, then `python -m sportscut eval-crop tests/fixtures/eval_crop --json`. If that README section is missing, report BLOCKED.

## Design

### `sportscut/media.py` (append only, 0 deleted lines)

```python
def filter_video(path: str | Path, video_filter: str, dest: str | Path) -> Path:
```

- If `path` is not a file, raise `MediaError(f"media file not found: {path}")` before any tool lookup.
- Run ffmpeg with no shell. The args are exactly:
  `[ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(p), "-map", "0:v:0", "-map", "0:a?", "-vf", video_filter, "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", str(dest)]`
- On a non-zero return code, raise `MediaError(f"ffmpeg failed for {path}: {_failure_detail(result.stderr, result.returncode)}")`. Otherwise return `Path(dest)`.
- It does not create the parent directory.

### `sportscut/vertical.py` (new)

```python
from sportscut import media, reframe
OUT_WIDTH = 1080
OUT_HEIGHT = 1920
MAX_EXPRESSION = 100_000
def crop_x_expression(crop_path, width: int, crop_w: int) -> str
def vertical_filter(crop_path, width: int, height: int) -> str
def render_vertical(clip, crop_path, out) -> Path
```

**`_validate(crop_path) -> list[tuple[float, float]]` (private).** It raises a ValueError whose message starts with `invalid crop path: ` when:
- the path is empty (`invalid crop path: empty`);
- an item is not a 2-item sequence of real, finite, non-bool numbers;
- the first t is < 0;
- t is not strictly increasing.

It returns floats. An out-of-frame x is not an error; it is clamped.

**`crop_x_expression(crop_path, width, crop_w)`.** Validate first. Then for each keyframe:
- clamp the centre: `xc = min(max(x, crop_w/2), width - crop_w/2)`;
- take the left edge: `left = xc - crop_w/2`, which is in `[0, width - crop_w]`.

The result is a **flat** ffmpeg expression in `t`:
- It starts with `f"{left_0:.4f}"`.
- For each consecutive pair i→i+1, `slope = (left_{i+1} - left_i) / (t_{i+1} - t_i)`. Skip the pair if `abs(slope) < 1e-9`. Otherwise append `f"{sign}{abs(slope):.6f}*(clip(t,{t_i:.4f},{t_{i+1}:.4f})-{t_i:.4f})"`, with sign `+` for a positive slope and `-` for a negative one.
- The result equals np.interp over the clamped left edges, held before the first keyframe and after the last.
- If `len(expr) > MAX_EXPRESSION`, raise `ValueError(f"crop path too long: {n} keyframes")`.

Exact examples:
- `crop_x_expression([(0.0, 101.0), (1.0, 201.0)], 640, 202) == "0.0000+100.000000*(clip(t,0.0000,1.0000)-0.0000)"`
- `crop_x_expression([(0, 320), (1, 320)], 640, 202) == "219.0000"`

**`vertical_filter(crop_path, width, height)`.**
- `cw = reframe.crop_width(width, height)`.
- It returns `f"crop=w={cw}:h={height}:x='{expr}':y=0,scale={OUT_WIDTH}:{OUT_HEIGHT},setsar=1"`.
- Example: `vertical_filter([(0.0, 320.0)], 640, 360) == "crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1"`.
- The single quotes protect the commas inside `clip(...)` from the filtergraph parser. The crop filter re-evaluates `x` on every frame.

**`render_vertical(clip, crop_path, out) -> Path`.**
1. Validate crop_path first, so a bad path raises ValueError even when the clip is missing.
2. `width, height = media.probe_size(clip)`.
3. `Path(out).parent.mkdir(parents=True, exist_ok=True)`.
4. `return media.filter_video(clip, vertical_filter(crop_path, width, height), out)`.

Always call through module attributes (`media.probe_size`, `media.filter_video`, `reframe.crop_width`) so tests can monkeypatch them.

### `sportscut/pipeline.py`

Add `from sportscut import reframe` and `from sportscut import vertical as vertical_mod`. The alias is needed because the parameter `vertical` shadows the module name. Keep the existing imports.

The signature becomes `run(video, out_dir, top=10, min_len=10, max_len=30, events=None, vertical: bool = False) -> list[dict]`. Everything up to and including `export_clips(...)` and the `manifest = ...` line is unchanged. Replace only the final `return json.loads(...)` with:

```python
entries = json.loads(manifest.read_text(encoding="utf-8"))
if vertical:
    for entry in entries:
        clip = Path(out_dir) / entry["file"]
        rel = f"vertical/{entry['file']}"
        crop_path = reframe.plan_crop(clip)
        vertical_mod.render_vertical(clip, crop_path, Path(out_dir) / rel)
        entry["vertical_file"] = rel
    manifest.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
return entries
```

- `vertical_file` is the last key. It is a POSIX relative path, `vertical/<file>`.
- MediaError and ValueError from the vertical stage propagate unwrapped. If a render fails, highlights.json keeps its pre-vertical content.
- When `vertical=False`, plan_crop and render_vertical are never called, `DIR/vertical/` is never created, and the manifest is byte-identical to today's.
- When nothing is selected (`[]`), nothing is rendered.
- The CLI already prints MediaError as `sportscut: error: ...` with exit 1. A ValueError from a bad plan is a programming error and is not caught.

### `sportscut/cli.py` (additions only, 0 deleted lines)

- Add `cut_parser.add_argument("--vertical", action="store_true", help="also write 1080x1920 (9:16) clips to OUT/vertical/")` after the existing cut arguments.
- In the `run(...)` call, add a new line `vertical=args.vertical,` right after the existing `events=args.events,` line. Leave existing lines untouched.
- After the existing `print(Path(args.out) / entry["file"])`, add, inside the same loop:
  ```python
  if "vertical_file" in entry:
      print(Path(args.out) / entry["vertical_file"])
  ```
- Without `--vertical`, stdout is unchanged. Error handling is unchanged.

### README.md (insert only)

Insert a Vietnamese section, `## Video dọc 9:16 cho TikTok/Reels (cut --vertical)`, **immediately before** the heading `## Video dọc 9:16: đo khung cắt (eval-crop)`. If a T-019 section already sits before eval-crop, put the new section after it and still before eval-crop. The eval-crop section stays last and byte-identical, and README gets 0 deleted lines. The section shows:
- `sportscut cut match.mp4 --out out --vertical`;
- the output `out/vertical/clip_NN.mp4` (1080x1920, H.264, audio copied);
- the `vertical_file` key in highlights.json;
- a note that the crop follows `plan_crop`, which is a static centre crop until the ball/player tracking tasks land.

### Spec updates (insert/append only, 0 deleted lines)

- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`: append a `## Updated by T-018` section at the end of the file (after `## Updated by T-039`). It says:
  - `run` gains `vertical=False`;
  - with `vertical=True`, each entry also has `vertical_file` (the last key) and `<out_dir>/vertical/clip_NN.mp4` is written;
  - `cut --vertical` prints the vertical path after each clip path;
  - AC1/AC6 hold unchanged when vertical is off.
  
  Do NOT edit the existing AC lines (test_t012 checks that AC1 still contains `events=None`).
- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md` [r2]: insert this paragraph, followed by a blank line, **immediately before** the final paragraph that starts with `Updated by T-004: sportscut.media also exposes require_ffmpeg()`. That paragraph must stay the last text in the file. The `Updated by T-017` paragraph already set this precedent.
  > Updated by T-018: sportscut.media also owns filter_video(path, video_filter, dest), which re-encodes video through an ffmpeg -vf filter (libx264 veryfast, yuv420p) and stream-copies audio, so vertical.py never calls ffmpeg directly.

### Cross-task scope-test gates (E1, E2, E3; apply only when needed)

[r2] The PM read main @ 9aa5a85:
- `test_t014_acceptance::test_ac15_*` no longer forbids sportscut/media.py, because T-044 removed it.
- `test_t034b_acceptance::test_ac9_ac10_scope_and_size` now checks only pyproject.toml, tests/conftest.py and agent-office (T-015 round 1).
- `test_t013` ac15, `test_t015` ac16 and `test_t023` ac16 forbid none of T-043's files.

So none of these is expected to fail. Run the full suite after the code is in (Step 7):
- **E1**: only if `test_t014_acceptance.py::test_ac15_task_diff_uses_merge_base_and_touches_no_forbidden_path` fails purely because of this branch's diff. Add as its first lines: `branch = subprocess.run(["/usr/bin/git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()` and `if not branch.startswith("office/T-014"): pytest.skip("T-014 scope check runs only on its own office/T-014 branch")`.
- **E2**: only if `test_t034b_acceptance.py::test_ac9_ac10_scope_and_size` fails for the same reason. Right after its existing main-branch skip, add: `if not git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip().startswith(("office/T-041", "office/T-034")): pytest.skip("T-041 scope check runs only on its own branch")`.
- **E3** (pre-approved by the Tech Lead): only if a test added by T-044/T-042/T-017 fails solely because it asserts that the current branch's diff against merge-base stays inside that task's own files. Add as the first lines of that test function: `if not <branch>.startswith(("office/T-044", "office/T-042", "office/T-017")): pytest.skip("<task> scope check runs only on its own branch")`. Get the branch via `git rev-parse --abbrev-ref HEAD`, using the file's existing git helper or subprocess as in E1. Change nothing else in that file.
- The T-042 append-only tests (`test_ac3_shared_files_are_append_only*`) and README-ends-with tests (`test_ac7_*`) are **not** E3 candidates. They pass when this spec's insert-only rules are followed. If they fail, fix the T-043 change.
- Any other failing test means stop and report BLOCKED with the test ids. List every gate you applied (E1/E2/E3 and the test id) in the PR.

## Files

- Create: `sportscut/vertical.py`, `tests/test_vertical.py` (Developer), `tests/test_t018_acceptance.py` (Tester).
- Change:
  - `sportscut/media.py` (append only);
  - `sportscut/pipeline.py`;
  - `sportscut/cli.py` (additions only);
  - `tests/test_media.py`, `tests/test_pipeline.py`, `tests/test_cli.py` (append only);
  - `README.md` (insert only);
  - the T-004 spec (append) and the T-036 spec (insert before the final T-004 note).
- Only if needed: `tests/test_t014_acceptance.py` (E1), `tests/test_t034b_acceptance.py` (E2), or one T-017/T-042/T-044 acceptance file (E3).
- Do not change: `tests/conftest.py`, `sportscut/reframe.py`, `sportscut/eval_crop.py`, `sportscut/export.py`, `sportscut/api.py`, `sportscut/evaluate.py`, `sportscut/eval_player.py`, detection/events modules, `tests/fixtures/`, `pyproject.toml`, `.gitignore`, `agent-office/`, `AGENTS.md`, `CLAUDE.md`.
- Never run git commands that write the index (checkout -- path, add, mv, stash, commit). The orchestrator commits.

## Steps (TDD: write the test, watch it fail for the right reason, then write the code)

0. Run Step 0 and 0b. Stop if BLOCKED.
1. **media.filter_video.** Append to tests/test_media.py:
   - a missing input → `media file not found: <path>`;
   - (require_ffmpeg) `filter_video(synthetic_video, "scale=32:24", tmp_path/"o.mp4")` returns the dest, `media.probe_size(dest) == (32, 24)`, and ffprobe shows an aac audio stream;
   - `"nosuchfilter"` → MediaError matching `^ffmpeg failed for `.
   
   Red: `cannot import name 'filter_video'`. Then implement.
2. **Validation + crop_x_expression** (tests/test_vertical.py):
   - the two exact examples;
   - each of `[]`, `[(0, float('nan'))]`, `[(1, 5), (1, 6)]`, `[(-1, 5)]`, `[(0, True)]` raises ValueError starting with `invalid crop path: `;
   - clamping: `[(0, -1000), (1, 5000)]` at 640/202 evaluates to 0 at t=0, 219 at t=0.5, and 438 at t=1, 2 and 5;
   - 25 000 keyframes → `crop path too long`.
   
   Evaluate expressions with `eval(expr, {"__builtins__": {}}, {"t": t, "clip": lambda v, lo, hi: min(max(v, lo), hi)})`. Red: `No module named 'sportscut.vertical'`. Then implement.
3. **vertical_filter.** Test the exact example string. Then implement.
4. **render_vertical.**
   - With `media.probe_size`/`media.filter_video` monkeypatched, check the argument passing and the parent mkdir.
   - An invalid path raises before probe_size is called, even for a missing clip.
   - (require_ffmpeg) `synthetic_video` with `[(0.0, 80.0)]` gives (1080, 1920) and a duration within 0.3 s.
   
   Then implement.
5. **Pipeline** (append to tests/test_pipeline.py):
   - (a) `run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True)` writes out/vertical/clip_01.mp4 at 1080x1920. The entry's keys are in order with `vertical_file` last, and the return value equals `json.loads(out/'highlights.json')`.
   - (b) A sentinel returned by a monkeypatched `reframe.plan_crop` reaches a fake `vertical.render_vertical` as `(out/'clip_01.mp4', sentinel, out/'vertical'/'clip_01.mp4')`. Patch via `monkeypatch.setattr(sportscut.reframe, 'plan_crop', ...)` and `monkeypatch.setattr(sportscut.vertical, 'render_vertical', ...)`.
   - (c) The default `run` with plan_crop/render patched to `pytest.fail` creates no vertical dir and no key.
   
   Then implement.
6. **CLI** (append to tests/test_cli.py):
   - `main(["cut", str(burst_video), "--out", str(out), "--top", "1", "--min-len", "4", "--max-len", "6", "--vertical"])` returns 0 and prints exactly the lines `[str(out/'clip_01.mp4'), str(out/'vertical'/'clip_01.mp4')]`;
   - a fake `cli.run` records `vertical=True` with the flag and `vertical=False` without it.
   
   Then implement.
7. Run `python -m pytest -q`. If it fails, apply only the E1/E2/E3 rules above, then re-run. Any other failure: stop, report BLOCKED with the ids.
8. Update README and the two spec files as described above.
9. Run Verify and quote each summary line.

## Verify

- `python -m pytest -q`: 0 failed (quote the summary line).
- Build a sample video with audio, then cut it:
  ```
  mkdir -p /tmp/t043src && ffmpeg -v error -nostdin -y -f lavfi -i color=c=black:s=160x120:r=5:d=90 -f lavfi -i anoisesrc=d=90:c=white:r=44100:a=0.02:seed=7 -filter_complex "[1:a]volume=volume=30:enable='between(t,75,76)',aformat=channel_layouts=stereo[a]" -map 0:v -map "[a]" -c:v mpeg4 -q:v 5 -pix_fmt yuv420p -c:a aac -b:a 96k -t 90 /tmp/t043src/burst.mp4
  python -m sportscut cut /tmp/t043src/burst.mp4 --out /tmp/t043 --top 1 --min-len 4 --max-len 6 --vertical
  ```
  The cut prints two lines. Then `ffprobe -v error -select_streams v:0 -show_entries stream=codec_name,width,height -of csv=p=0 /tmp/t043/vertical/clip_01.mp4` prints `h264,1080,1920`.
- `python -m sportscut eval tests/fixtures/eval --json`: f1 == BASE_F1.
- `python -m sportscut eval-crop tests/fixtures/eval_crop --json` equals BASE_CROP in every field except `seconds_per_min` (top level and per_clip). Quote both in the PR (R-004 requires it).
- `git ls-files '*.mp4'` is empty.
- `git diff --numstat $(git merge-base main HEAD) -- sportscut/media.py sportscut/cli.py README.md tests/test_media.py tests/test_pipeline.py tests/test_cli.py docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md` shows 0 deleted lines for every file.

## Assumptions

- The output is fixed at 1080x1920 H.264 (libx264), with no size or quality option. The ffmpeg on PATH has libx264, which standard Homebrew/apt builds include. If it does not, the require_ffmpeg tests fail with the ffmpeg error, and the Developer reports that as an environment BLOCKED rather than switching encoders.
- The crop is always full height; only x moves, clamped to the frame edges. A source narrower than 9:16 uses the full width and is scaled without letterboxing.
- The aspect distortion from 202x360 or 66x120 → 1080x1920 is below 0.3% and is accepted (setsar=1).
- Audio is stream-copied from the exported clip, which export always encodes as AAC. `-map 0:a?` tolerates a clip with no audio.
- Rendering is one ffmpeg pass per clip with no per-frame Python. `--vertical` is opt-in, so the 90-minute default budget is unaffected.
- Stale files in DIR/vertical/ are not cleaned (consistent with T-004).
- Subtitles, the scoreline overlay and real ball/player tracking are later R-004 tasks. This PR delivers the 9:16 export path that they plug into.

## Test plan

- Step 0 (Developer, before any edit): run the grep precondition. It is expected to print READY on 9aa5a85; on BLOCKED, report it and stop. Record the base `pytest -q` summary (0 failed required), BASE_F1 and the BASE_CROP eval-crop JSON.
- Developer, unit tests in tests/test_vertical.py:
- the exact crop_x_expression strings, plus the absence of `if(` (AC3);
- expression evaluation versus np.interp at keyframes, midpoints, before the first and after the last keyframe, including clamping (AC4);
- the parametrized invalid paths with the `invalid crop path: ` prefix, and the 25 000-keyframe `crop path too long` (AC5);
- the exact vertical_filter string (AC6);
- render_vertical with monkeypatched media.probe_size/filter_video: argument passing, parent mkdir, and probe not called for an invalid path even with a missing clip.
- Developer, integration test in tests/test_vertical.py (require_ffmpeg): render_vertical(synthetic_video, [(0.0, 80.0)], tmp_path/'v'/'o.mp4') gives 1080x1920 h264 and a duration within 0.3 s (AC7).
- Developer, tests appended to tests/test_media.py (AC2):
- filter_video with a missing file;
- scale=32:24 succeeds with an aac stream;
- `nosuchfilter` raises MediaError `^ffmpeg failed for `;
- a source scan shows that only sportscut/media.py imports subprocess.
- Developer, tests appended to tests/test_pipeline.py:
- vertical=True end to end on burst_video with top=1/min_len=4/max_len=6: key order and manifest equality (AC9);
- a monkeypatched plan_crop sentinel is forwarded to a fake render_vertical (AC10);
- a default run with plan_crop/render patched to pytest.fail creates no vertical dir and no key (AC11).
- Developer, tests appended to tests/test_cli.py: cut --vertical stdout lines on burst_video, and a fake cli.run records vertical=True/False (AC12).
- Developer: run the full suite after the code is in. Apply E1/E2/E3 only for a pure branch-diff scope failure, exactly as specified, and re-run. Any other failure, including the T-042 append-only or README-ends-with tests, is either fixed in the T-043 change or reported as BLOCKED with its ids.
- Tester, tests/test_t018_acceptance.py, written independently from the ACs. A module-local fixture builds the AC8 clip in tmp_path with ffmpeg lavfi:
- base `color=c=0x1e7a32:s=640x360:r=25:d=4`;
- marker `color=c=white:s=20x20`, overlaid with `x='110+100*t':y=170`;
- `anoisesrc` audio;
- encoded with mpeg4 -q:v 2 + aac.

Never commit it or add it to conftest.
- Tester: decode single frames with `ffmpeg -v error -ss T -i out -frames:v 1 -f rawvideo -pix_fmt gray pipe:1` and reshape to (1920, 1080).
- AC8 moving path: the marker centroid is within 540±108 at t=0.5/1.5/2.5/3.5.
- Static centre path: no marker at t=0.5 and 3.5.
- Tester:
- ffprobe codec/size/duration checks for AC7;
- the AC9 key order and manifest equality;
- AC12 via subprocess `python -m sportscut cut ... --vertical` (exit 0, exactly two lines, empty stderr), and a run without the flag (one line, no OUT/vertical);
- AC13 text checks on both spec files and README.
- Tester, AC15 checks:
- numstat shows 0 deleted lines for the listed files;
- the README new section index is below the eval-crop heading index, and README ends with the eval-crop section;
- the T-036 spec still ends with the `Updated by T-004:` paragraph and contains `Updated by T-018: sportscut.media also owns filter_video`;
- any E1/E2/E3 gate is the only change in its file.

Every git-based scope check the Tester adds must itself start with a skip unless `git rev-parse --abbrev-ref HEAD` starts with `office/T-043`.
- Tester: show that the tests can fail. In a scratch copy, temporarily invert the slope sign (or feed the static path to the moving clip), watch the AC8 assertion fail, then restore. Report the red and green output. Never edit production code.
- Tester: run and quote the summary lines of:
- `python -m pytest -q` (0 failed);
- `python -m sportscut eval tests/fixtures/eval --json` (f1 == BASE_F1);
- `python tests/fixtures/eval_crop/build.py && python -m sportscut eval-crop tests/fixtures/eval_crop --json` (equal to BASE_CROP apart from seconds_per_min);
- the Verify cut + ffprobe (`h264,1080,1920`);
- `git ls-files '*.mp4'` (empty).

## Deviations

- AC2's "No other module in sportscut/ imports subprocess" is already false on main @ 9aa5a85: `sportscut/events/incidents.py` imports subprocess for `sample_frames`, by the T-015 decision recorded in DECISIONS.md (media.py was frozen then). That file is out of T-043's scope. So the appended `tests/test_media.py::test_only_media_module_imports_subprocess` asserts the importers are exactly `events/incidents.py` and `media.py`. That means T-043 adds no new importer, and vertical.py and pipeline.py call ffmpeg only through `sportscut.media`.
- No E1/E2/E3 gate was needed. The full suite passed with no scope-test edits, and none of the merge-base scope tests (t013, t014, t015, t023, t034b, t042*, t044) forbids a T-043 file.
