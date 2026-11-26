# Plan T-021: Overlay the live broadcast scoreboard and an event caption on vertical clips

Design: `docs/superpowers/specs/2026-11-23-t-021-overlay-the-live-broadcast-scoreboard-and-design.md`.

## Implementation plan

# T-021: Overlay the live broadcast scoreboard and an event caption on vertical clips

Request R-004. PO request: "Tự xuất video dọc 9:16 cho TikTok/Reels: tự bám theo bóng và cầu thủ để crop, có phụ đề và tỉ số".

## Context (main @ 71cb0cc, 2026-11-26)

- T-043 is merged. `sportscut cut VIDEO --out OUT --vertical` calls `pipeline.run(..., vertical=True)`. For each manifest entry, run calls `reframe.plan_crop(clip)` and then `vertical_mod.render_vertical(clip, crop_path, OUT/'vertical'/<file>)` with **exactly three positional arguments**. The result is a 1080x1920 H.264 file with audio copied.
- The 9:16 crop takes the full height and is centred. On a 640x360 source it covers x 219..421, so a top-left broadcast scoreboard is cut off.
- T-013 is merged. `sportscut/events/scoreboard.py::find_box(frames)` takes the frames from `media.sample_top_band(path)`. Those frames are sampled at 1 fps, scaled to **160x90** grey and cropped to the top **160x30** band. find_box returns `(x, y, w, h)` of the largest static high-edge component, **in that 160x90 grid**, or None. This task reuses it unchanged; no new detector is added.
- `sportscut/media.py` is the only module that runs external tools. test_t018 ac2 asserts that the only `import subprocess` lines in sportscut/ are in `media.py` and `events/incidents.py`, and that the **string** `subprocess` does not appear anywhere in vertical.py, pipeline.py or cli.py, comments included.
- sportscut uses no logging yet.

### Existing tests that constrain this diff (all must stay green, unedited)

- tests/test_vertical.py and test_t018 ac7 check render_vertical when it gets no new arguments. It must call exactly `media.probe_size(clip)` and then `media.filter_video(clip, "crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1", out)`, and nothing else in media. `vertical_filter(path, W, H)` with no new arguments must return the old string byte-for-byte.
- These tests monkeypatch `sportscut.vertical.render_vertical` with fakes that take only `(clip, crop_path, dest)`:
  - test_t018 ac10 (`fake_render(clip, crop_path, dest)`, `boom(*args)`);
  - test_pipeline `test_run_vertical_forwards_plan_crop_result`.
  
  They run on `burst_video`, which is black (no scoreboard) and whose segments are event `other`. Therefore **the pipeline must pass no keyword arguments when a clip has neither a box nor a caption**.
- test_t018 ac12 runs `cut --vertical` on burst_video and asserts `stderr == ""`. The "no scoreboard" warning must therefore not reach stderr when logging is unconfigured.
- test_t018 ac9 and ac11 check that the manifest keys are exactly start, end, score, reason, event, event_confidence, file (and vertical_file last). **No new manifest keys.**
- test_t042_round2 and test_t042_tester ac3 require 0 deleted lines (`git diff --numstat $(git merge-base main HEAD)`) in:
  - sportscut/media.py, sportscut/cli.py;
  - tests/test_media.py, tests/test_cli.py;
  - README.md, DECISIONS.md, INDEX.md;
  - the T-036 design spec.
- test_t042 ac7 and test_t018 ac15: README must still end with the byte-identical `## Video dọc 9:16: đo khung cắt (eval-crop)` section.
- test_t004 and test_t018 ac13: the T-036 spec's last paragraph must remain the `Updated by T-004: sportscut.media also exposes require_ffmpeg() ...` paragraph.
- test_t018 ac13 splits README at `## Video dọc 9:16 cho TikTok/Reels (cut --vertical)` up to the next `\n## `. That section must keep its current text; new text is only added.

## Step 0: preconditions (run first, on the untouched base)

```
grep -q 'def render_vertical' sportscut/vertical.py && grep -q 'def find_box' sportscut/events/scoreboard.py && grep -q 'def sample_top_band' sportscut/media.py && echo READY || echo BLOCKED
```

The PM checked 71cb0cc and it prints READY. If it prints BLOCKED, stop, change nothing and report it. Then record:

1. The `python -m pytest -q` summary line. It must show 0 failed.
2. BASE_F1 from `python -m sportscut eval tests/fixtures/eval --json`.
3. BASE_CROP from `python tests/fixtures/eval_crop/build.py && python -m sportscut eval-crop tests/fixtures/eval_crop --json`.
4. The `event` values of `sportscut.pipeline.run(burst_video_path, tmp, top=2, min_len=4, max_len=6)`, using the conftest recipe. They are expected to be all `other`. If any is not `other`, report this to the Tech Lead before coding, because the existing real-ffmpeg vertical tests would then need a font.

## Design

### 1. `sportscut/media.py`: append `find_font()` (0 deleted lines)

```python
def find_font() -> Path:
    """Return a font file that covers Vietnamese, resolved through fontconfig."""
```

**Tool lookup.** For `fc-list` and then `fc-match`:
- `shutil.which(name)` returning None raises `MediaError(f"{name} not found on PATH; install fontconfig to draw captions")`.
- Do not use `find_tool`, because its message says "install ffmpeg".

**Step 1.** Run `[fc_list, "--format", "%{file}\n", ":lang=vi"]` with `capture_output=True, check=False, text=True`.
- A non-zero return code raises `MediaError(f"fc-list failed: {_failure_detail(result.stderr, result.returncode)}")`.
- `candidates` is the set of stripped, non-empty lines for which `Path(line).is_file()`.
- If `candidates` is empty, raise `MediaError("no font with Vietnamese support found; install one (for example DejaVu Sans or Noto Sans) and check with: fc-list :lang=vi")`.

**Step 2.** Run `[fc_match, "-s", "--format", "%{file}\n", "sans-serif:lang=vi"]`. This is fontconfig's preference order.
- Return `Path` of the first line that is in `candidates`.
- If no line is in `candidates`, or fc-match exits non-zero, return `Path(sorted(candidates)[0])`.

### 2. `sportscut/vertical.py`: new public names (existing functions keep their behaviour)

New imports: `import logging` is not needed here. Add `from sportscut.events import scoreboard` and keep `from sportscut import media, reframe`.

Constants:

```python
GRID_W, GRID_H = 160, 90          # sample_top_band scale grid
SCORE_MAX_W, SCORE_MAX_H = 1000, 160
SCORE_TOP = 40                    # y of the scoreboard overlay in the 1080x1920 frame
CAPTION_Y = 240
CAPTION_LABELS = {"goal": "BÀN THẮNG", "save": "CỨU THUA", "red_card": "THẺ ĐỎ", "controversy": "TRANH CÃI"}
```

**`caption_text(event: str, start: float, end: float) -> str | None`**
- Look up `label = CAPTION_LABELS.get(event)`. Return None for `other` or for an unknown event.
- `minute = math.floor((start + end) / 2 / 60) + 1`.
- Return `f"{label} · {minute}'"`. The separator is U+00B7 with one space on each side, and the minute is followed by an ASCII apostrophe.
- Examples:
  - `caption_text("goal", 2000, 2020) == "BÀN THẮNG · 34'"`
  - `caption_text("save", 0, 10) == "CỨU THUA · 1'"`
  - `caption_text("other", 0, 10) is None`

**`check_score_box(box, width: int, height: int) -> tuple[int, int, int, int]`**

Return the box as a tuple of ints, or raise ValueError:
- `invalid score box: expected four integers x,y,w,h` when it is not a 4-sequence of non-bool ints;
- `invalid score box: x,y must be >= 0 and w,h >= 2`;
- `invalid score box: {x},{y},{w},{h} does not fit the {width}x{height} frame` when `x+w > width` or `y+h > height`.

**`band_box_to_source(box, width: int, height: int) -> tuple[int, int, int, int]`**

Map a find_box result from the 160x90 grid to source pixels. Use integer arithmetic only:
- Pad by 1 grid pixel and clamp to the band:
  - `bx0 = max(0, x-1)`, `by0 = max(0, y-1)`
  - `bx1 = min(GRID_W, x+w+1)`, `by1 = min(media.BAND_H, y+h+1)`
- Scale to source pixels:
  - `sx0 = bx0*width // GRID_W`, `sy0 = by0*height // GRID_H`
  - `sx1 = min(width, -(-bx1*width // GRID_W))`, `sy1 = min(height, -(-by1*height // GRID_H))`
- Snap to even values:
  - `sx0 -= sx0 % 2`, `sy0 -= sy0 % 2`
  - `sx1 = min(width - width % 2, sx1 + sx1 % 2)`, and the same for y
- Return `(sx0, sy0, sx1-sx0, sy1-sy0)`.
- Examples:
  - `band_box_to_source((10,4,40,10), 640, 360) == (36,12,168,48)`
  - `band_box_to_source((10,4,40,10), 160, 120) == (8,4,44,16)`
  - `band_box_to_source((0,0,5,3), 1920, 1080) == (0,0,72,48)`

**`find_score_box(clip) -> tuple[int, int, int, int] | None`**
1. `band = scoreboard.find_box(media.sample_top_band(clip))`.
2. If `band` is None, return None.
3. Otherwise compute `width, height = media.probe_size(clip)` and return `band_box_to_source(band, width, height)`.

Call these through module attributes so tests can monkeypatch them.

**`score_overlay_geometry(box) -> tuple[int, int, int, int]`** returns `(sw, sh, ox, oy)`:
- `f = min(SCORE_MAX_W / w, SCORE_MAX_H / h)`
- `sw = max(2, 2*round(w*f/2))`, `sh = max(2, 2*round(h*f/2))`
- `ox = (OUT_WIDTH - sw) // 2`, `oy = SCORE_TOP`
- Examples:
  - `(40,16,160,40)` → `(640,160,220,40)`
  - `(36,12,168,48)` → `(560,160,260,40)`

**`_escape(value: str) -> str` (private)**

This is ffmpeg's two-level filtergraph escaping. Replace in this order:
- Level 1: `\` → `\\`, `'` → `\'`, `:` → `\:`.
- Level 2, applied to the level-1 result: `\` → `\\`, `'` → `\'`, `[` → `\[`, `]` → `\]`, `,` → `\,`, `;` → `\;`.

The result for an apostrophe is `\\\'` (three backslashes then `'`), as in the ffmpeg-filters "Notes on filtergraph escaping" example.

**`drawtext_filter(caption: str, fontfile) -> str`** returns:

`f"drawtext=fontfile={_escape(str(fontfile))}:text={_escape(caption)}:expansion=none:fontsize=64:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=16:x=(w-text_w)/2:y={CAPTION_Y}"`

Example: `drawtext_filter("BÀN THẮNG · 34'", "/fonts/DejaVuSans.ttf")` gives

`drawtext=fontfile=/fonts/DejaVuSans.ttf:text=BÀN THẮNG · 34\\\':expansion=none:fontsize=64:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=16:x=(w-text_w)/2:y=240`

(in Python source, `"...34\\\\\\':expansion..."`).

**`vertical_filter(crop_path, width, height, score_box=None, caption=None, fontfile=None) -> str`**

Let `base = f"crop=w={cw}:h={height}:x='{expr}':y=0,scale=1080:1920,setsar=1"`, the existing string.
- Neither box nor caption: return `base`, unchanged.
- `caption` without `fontfile`: raise `ValueError("caption needs a fontfile")`.
- Box given: first `bx,by,bw,bh = check_score_box(score_box, width, height)` and `sw,sh,ox,oy = score_overlay_geometry(...)`. Then
  `graph = f"split=2[sc_main][sc_box];[sc_main]{base}[sc_v];[sc_box]crop=w={bw}:h={bh}:x={bx}:y={by},scale={sw}:{sh},setsar=1[sc_b];[sc_v][sc_b]overlay=x={ox}:y={oy}"`.
  Without a box, `graph = base`.
- Caption given: return `graph + "," + drawtext_filter(caption, fontfile)`. Otherwise return `graph`.

The box is cropped from the **source** on every frame, so a score change shows live.

Exact example: `vertical_filter([(0.0, 320.0)], 640, 360, score_box=(40,16,160,40), caption="BÀN THẮNG · 34'", fontfile="/fonts/DejaVuSans.ttf")` returns

`split=2[sc_main][sc_box];[sc_main]crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1[sc_v];[sc_box]crop=w=160:h=40:x=40:y=16,scale=640:160,setsar=1[sc_b];[sc_v][sc_b]overlay=x=220:y=40,drawtext=fontfile=/fonts/DejaVuSans.ttf:text=BÀN THẮNG · 34\\\':expansion=none:fontsize=64:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=16:x=(w-text_w)/2:y=240`

This graph has one unlabelled input and one unlabelled output, so it is still passed via `-vf` through the unchanged `media.filter_video`.

**`render_vertical(clip, crop_path, out, score_box=None, caption=None) -> Path`**

Same order as today:
1. `_validate(crop_path)`;
2. `media.probe_size(clip)`;
3. mkdir the parent;
4. **only if caption is not None**, `fontfile = media.find_font()`;
5. `media.filter_video(clip, vertical_filter(crop_path, width, height, score_box, caption, fontfile), out)`.

With both None, the calls are exactly as before.

### 3. `sportscut/pipeline.py`

New lines:
- `import logging`
- `from sportscut import media`
- `logger = logging.getLogger(__name__)`
- `logger.addHandler(logging.NullHandler())`

The signature gains a last parameter: `run(video, out_dir, top=10, min_len=10, max_len=30, events=None, vertical=False, score_box=None)`.

**Validation, inside the existing `try`, right after the has_audio check:**

```python
if score_box is not None:
    if not vertical:
        raise PipelineError("score_box needs vertical=True")
    score_box = vertical_mod.check_score_box(score_box, *media.probe_size(video))
```

The ValueError becomes a PipelineError with the same message, through the existing except. No clip is exported for a bad box.

**Vertical loop body:**

```python
clip = Path(out_dir) / entry["file"]
rel = f"vertical/{entry['file']}"
crop_path = reframe.plan_crop(clip)
box = score_box if score_box is not None else vertical_mod.find_score_box(clip)
if box is None:
    logger.warning("no scoreboard found in %s; %s has no score overlay (pass --score-box x,y,w,h to set it)", entry["file"], rel)
caption = vertical_mod.caption_text(entry["event"], entry["start"], entry["end"])
extra = {key: value for key, value in (("score_box", box), ("caption", caption)) if value is not None}
vertical_mod.render_vertical(clip, crop_path, Path(out_dir) / rel, **extra)
entry["vertical_file"] = rel
```

- When a manual box is given, find_score_box is never called.
- Errors from the vertical stage still propagate unwrapped (T-043).
- The manifest format and keys are unchanged.

### 4. `sportscut/cli.py` (additions only)

- Add a type function:

  ```python
  def _score_box_arg(text):
      if re.fullmatch(r"\d+,\d+,\d+,\d+", text.strip()) is None:
          raise argparse.ArgumentTypeError("expected x,y,w,h as four non-negative integers")
      return tuple(int(v) for v in text.split(","))
  ```

  `import re` goes on a new line.
- Add `cut_parser.add_argument("--score-box", type=_score_box_arg, default=None, metavar="X,Y,W,H", help="scoreboard box in source pixels for --vertical, when detection fails")`, placed after `--vertical`.
- After `args = parser.parse_args(argv)`, add: `if args.command == "cut" and args.score_box is not None and not args.vertical: cut_parser.error("--score-box needs --vertical")`. This exits 2.
- In the `run(` call, add a new line `score_box=args.score_box,` after `vertical=args.vertical,`.

A PipelineError such as an out-of-frame box prints `sportscut: error: invalid score box: ...` and exits 1, through the existing handler. A missing font raises MediaError, which prints `sportscut: error: no font with Vietnamese support found; ...` and exits 1.

### 5. Docs (insertions only)

**README.md.** Insert paragraphs at the end of the `## Video dọc 9:16 cho TikTok/Reels (cut --vertical)` section, immediately before `## Video dọc 9:16: đo khung cắt (eval-crop)`. Use no `## ` heading. They explain, in Vietnamese:
- The scoreboard is detected automatically, cut from the source and enlarged at the top of the vertical frame, so it updates live.
- Event clips get a caption such as `BÀN THẮNG · 34'`. The minute is counted from the start of the video. A font with Vietnamese support is needed (`fc-list :lang=vi`).
- If no scoreboard is found, the clip has no score overlay. Use `--score-box x,y,w,h` (source pixels) with the example `sportscut cut match.mp4 --out out --vertical --score-box 40,16,160,40`.

**T-036 design spec.** Insert the paragraph `Updated by T-021: sportscut.media also owns find_font(), which resolves a Vietnamese-capable font through fontconfig (fc-list :lang=vi, ordered by fc-match -s) and raises MediaError when none exists.` immediately **before** the final `Updated by T-004:` paragraph.

**T-004 design spec.** Append `## Updated by T-021` at the end, after `## Updated by T-018`. It says `run(...)` gains `score_box=None` (needs vertical=True; out-of-frame raises PipelineError) and that the CLI has `cut --score-box X,Y,W,H`.

**T-043 design spec.** Append `## Updated by T-021`. It says:
- render_vertical and vertical_filter take optional score_box and caption;
- vertical.py now also finds the score box (via media and scoreboard, still no external tool calls);
- the pipeline passes those keyword arguments only when they are not None;
- a missing board is logged at WARNING on `sportscut.pipeline`, which has a NullHandler.

## Ordered steps (TDD)

1. Step 0.
2. **media.find_font.** Append failing tests to tests/test_media.py, monkeypatching `media.shutil.which` and `media.subprocess.run`: tool missing, empty list, preference order, fc-match failure fallback. Implement and run `python -m pytest -q tests/test_media.py`.
3. **caption_text, check_score_box, band_box_to_source, score_overlay_geometry, drawtext_filter and the extended vertical_filter.** Write failing tests in the new tests/test_vertical_overlay.py with the exact strings above, then implement.
4. **render_vertical keyword path.** Write monkeypatched wiring tests:
   - with caption, the calls are probe_size, find_font, filter_video with the expected graph;
   - with only a box, find_font is not called;
   - with neither, the calls are unchanged.
   Then implement.
5. **Synthetic board clip fixture**, module-local in test_vertical_overlay.py; do not touch conftest. It is a 640x360, 25 fps, 4 s libx264 yuv420p clip, built from `color=c=0x2E8B57:s=640x360:r=25:d=4` with:
   - `drawbox=x=40:y=16:w=160:h=40:color=black:t=fill`
   - `drawbox=x=120:y=24:w=24:h=24:color=white:t=fill:enable='lt(t,2)'`
   - `drawbox=x=160:y=24:w=24:h=24:color=white:t=fill:enable='gte(t,2)'`
   
   Add audio with `anoisesrc` → aac.
6. **Pixel tests (real ffmpeg).** Write the find_score_box detection test and the band pixel tests. Implement find_score_box.
7. **Pipeline.** Append failing tests to tests/test_pipeline.py: kwargs forwarding, the manual box skipping detection, the warning, the bad box, and score_box without vertical. Implement.
8. **CLI.** Append failing tests to tests/test_cli.py, then implement.
9. **Docs**, then the Verify section.

## Verify

- `python -m pytest -q` reports 0 failed. Quote the summary line.
- `python -m sportscut eval tests/fixtures/eval --json` reports f1 == BASE_F1.
- The eval-crop JSON equals BASE_CROP except seconds_per_min.
- `git diff --numstat $(git merge-base main HEAD) -- sportscut/media.py sportscut/cli.py tests/test_media.py tests/test_cli.py README.md docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md` shows 0 in the deleted column on every line.
- `git ls-files '*.mp4'` is empty.
- Manual: build the board clip into /tmp and run `python -m sportscut cut /tmp/board.mp4 --out /tmp/o --top 1 --min-len 2 --max-len 4 --vertical --score-box 40,16,160,40`. It exits 0.

## Assumptions

- The match minute comes from video time, `floor(midpoint/60)+1`. There is no OCR of the match clock, so pre-match footage or half-time shifts it.
- Detection runs per exported clip, not on the full match. It is cheap (1 fps band), reuses find_box unchanged and needs at least 2 sampled seconds.
- A detected box is padded by 1 grid pixel and snapped to even pixels. A manual box is used exactly as given.
- Segments with event `other` get no caption.
- The overlay sits at y=40, at most 1000x160, centred. The caption sits at y=240, white text in a 60% black box, size 64.
- The caption keeps the ASCII apostrophe from the PO example, so the filtergraph escaping is done exactly as specified.

## Test plan

- tests/test_media.py (append): find_font with media.shutil.which and media.subprocess.run monkeypatched.
- fc-list missing gives the exact message, and fc-match missing behaves the same way.
- fc-list returns only non-existent paths: 'no font with Vietnamese support found'.
- fc-list returns tmp files A and B, and fc-match -s returns [other, B, A]: the result is B.
- fc-match returns a non-zero code: the result is sorted first.
- Assert the exact argv of both calls.
- An optional real test is skipped when fc-list is not on PATH or find_font raises: the result is_file().
- tests/test_vertical_overlay.py (new, Developer): unit tests for caption_text (all 5 events, minute rounding at 59.9/60.0 s midpoints), check_score_box (each error message), band_box_to_source (the 3 exact examples plus clamping at the band edges), score_overlay_geometry (2 examples, very wide box limited by width), drawtext_filter exact string, and escaping of ':' ',' '[' ';' and '\\' in a fontfile path.
- tests/test_vertical_overlay.py: vertical_filter exact strings for box+caption, caption-only and box-only, the old string unchanged when neither is given, ValueError for a caption without a fontfile, and ValueError for an out-of-frame box.
- tests/test_vertical_overlay.py: render_vertical wiring with monkeypatched media.probe_size, find_font and filter_video. Check the call order for caption, box-only and none, and that find_font is never called without a caption.
- tests/test_vertical_overlay.py (real ffmpeg, uses the require_ffmpeg fixture): a module-scoped board_clip fixture built in tmp_path_factory with the lavfi recipe from the spec.
- find_score_box(board_clip) contains (40,16,160,40) within 12 px.
- find_score_box on a black 160x120 clip is None.
- Helper `_gray_frame(path, t, vf)` runs ffmpeg -ss t -i path -frames:v 1 -vf '<vf>,format=gray' -f rawvideo - and returns a numpy array.
- AC9 band checks at t=1.0 and t=3.0 against the source crop+scale, and the two can-fail controls (cross-time ≥ 20, no-overlay ≥ 40).
- tests/test_vertical_overlay.py (real ffmpeg, skipped if `drawtext` is not in `ffmpeg -hide_banner -filters` or media.find_font raises MediaError): render with score_box and caption "BÀN THẮNG · 34'" succeeds at 1080x1920, and the band region still matches (MAD ≤ 8), which proves the escaped graph parses.
- tests/test_pipeline.py (append), on burst_video:
- With select_segments monkeypatched to one goal Segment(2.0, 8.0, 1.0, 'r', 'goal', 0.9) and vertical.render_vertical replaced by a fake recording kwargs, kw == {'caption': "BÀN THẮNG · 1'"}.
- With score_box=(8,4,44,16), find_score_box is monkeypatched to fail and kw includes the box.
- With media.find_font and media.filter_video monkeypatched and a real render_vertical, the captured filter contains `text=BÀN THẮNG · 1\\\'`.
- caplog WARNING on sportscut.pipeline for the default black clip, and the vertical file is still written (fake render).
- An out-of-frame box raises PipelineError with no clip_01.mp4.
- score_box with vertical=False raises PipelineError.
- `logging.NullHandler` is in `logging.getLogger('sportscut.pipeline').handlers`.
- tests/test_cli.py (append):
- --score-box parsing and forwarding with cli.run monkeypatched: tuple, None by default.
- The format errors and --score-box without --vertical exit 2 (pytest.raises(SystemExit) code 2, with the message in capsys err).
- A subprocess `python -m sportscut cut burst --vertical --score-box 0,0,200,10` exits 1 with stderr `sportscut: error: invalid score box: 0,0,200,10 does not fit the 160x120 frame`.
- tests/test_t021_acceptance.py (new, Tester): independent tests for AC2-AC15 written from the acceptance criteria.
- Include the AC9 pixel test with its own board clip and the AC11 empty-stderr CLI run.
- Any git-diff scope check starts with an own-branch gate: skip unless the branch starts with `office/T-021`.
- Regression: the full `python -m pytest -q`, especially test_vertical.py, test_t018_acceptance.py, test_pipeline.py, test_t042_*_acceptance.py and test_t004_acceptance.py, stays green unedited. Run the eval and eval-crop commands from Verify.

## Deviations

- Step order: `find_score_box` was implemented together with the other vertical.py helpers in step 3, with its own monkeypatched unit tests (band mapped through `band_box_to_source`; None skips `probe_size`). So the step 6 real-ffmpeg pixel tests passed on their first run. Their ability to fail was shown separately: with `find_score_box` stubbed to return a wrong box, the detection test fails. The AC9 controls measured cross-time MAD 45.9 (≥ 20) and no-overlay MAD 108.2 (≥ 40), against MAD 0.05 and 0.06 for the real matches.
- Manual verify: the 4 s board clip in the Verify section has steady noise and gives no highlight (`highlights.json` is `[]`). `cut ... --vertical --score-box 40,16,160,40` exits 0 but renders nothing. An extra 30 s board clip with an audio burst at 14-16 s was used to exercise the render. It printed both clip paths and exited 0, and `find_score_box` returned (32,8,172,52) on its exported clip.
- `find_font` looks up both fc-list and fc-match with `shutil.which` before running fc-list, so a missing fc-match is reported even when fc-list would succeed.
