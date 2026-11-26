# T-021: Overlay the live broadcast scoreboard and an event caption on vertical clips

Request R-004. Plan: `docs/superpowers/plans/2026-11-23-t-021-overlay-the-live-broadcast-scoreboard-and.md`.

## Product Owner request

Tự xuất video dọc 9:16 cho TikTok/Reels: tự bám theo bóng và cầu thủ để crop, có phụ đề và tỉ số.

## Goal

The 9:16 crop usually cuts off the broadcast scoreboard. Instead of OCR, reuse the static scoreboard box finder from R-003 (T-013, `sportscut/events/scoreboard.py`), or add a minimal version if T-013 is not merged. Crop that box from the source on every frame and overlay it scaled up in the top band of the vertical frame, so the scoreline stays correct and updates live after a goal. Add a short event caption from the segment's `event` and its match minute (for example `BÀN THẮNG · 34'`) using drawtext, with a font that supports Vietnamese diacritics resolved through fontconfig and a clear error if none is found. Add `--score-box x,y,w,h` as a manual override for broadcasts where detection fails. If no box is found, skip the overlay with a logged warning. Tests: on a synthetic clip with a known scoreboard box, the pixels in the vertical frame's top band match the scaled source box, and the caption text in the generated filtergraph matches the segment event.

## Acceptance criteria

- AC1: The Step 0 precondition prints READY on the base. Otherwise the Developer reports BLOCKED and changes nothing.
- AC2: `vertical.caption_text('goal', 2000, 2020) == "BÀN THẮNG · 34'"`, `caption_text('save', 0, 10) == "CỨU THUA · 1'"`, `caption_text('red_card', 60, 70) == "THẺ ĐỎ · 2'"`, `caption_text('controversy', 0, 10) == "TRANH CÃI · 1'"` and `caption_text('other', 0, 10) is None`. The separator is ' · ' (U+00B7) and the minute is floor((start+end)/2/60)+1.
- AC3: `vertical.band_box_to_source((10,4,40,10), 640, 360) == (36,12,168,48)`, `band_box_to_source((10,4,40,10), 160, 120) == (8,4,44,16)` and `band_box_to_source((0,0,5,3), 1920, 1080) == (0,0,72,48)`. `vertical.score_overlay_geometry((40,16,160,40)) == (640,160,220,40)` and `score_overlay_geometry((36,12,168,48)) == (560,160,260,40)`.
- AC4: `vertical.check_score_box` raises ValueError starting with `invalid score box: ` for a non-4-tuple, a bool or non-int member, negative x/y, w or h < 2, or a box that does not fit the frame. `check_score_box((0,0,200,10), 160, 120)` raises `invalid score box: 0,0,200,10 does not fit the 160x120 frame`. A valid box is returned as a tuple of ints.
- AC5: `vertical_filter([(0.0, 320.0)], 640, 360, score_box=(40,16,160,40), caption="BÀN THẮNG · 34'", fontfile='/fonts/DejaVuSans.ttf')` equals exactly the graph in the spec. That graph starts with `split=2[sc_main][sc_box];[sc_main]crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1[sc_v];[sc_box]crop=w=160:h=40:x=40:y=16,scale=640:160,setsar=1[sc_b];[sc_v][sc_b]overlay=x=220:y=40,drawtext=` and contains `:text=BÀN THẮNG · 34\\\':expansion=none:` (three backslashes before the apostrophe). With caption only, the result is the old crop string + ',' + drawtext_filter(...). With box only, it ends with `overlay=x=220:y=40`. With neither, it is byte-identical to the T-043 string. A caption without a fontfile raises ValueError `caption needs a fontfile`.
- AC6: `render_vertical(clip, path, out)` without new arguments makes exactly the T-043 calls (media.probe_size, then media.filter_video with the old filter) and never calls media.find_font. With `caption=...`, it calls probe_size, then find_font, then filter_video with the filter containing that caption's drawtext. With only `score_box=...`, it never calls find_font. An invalid crop path still raises before probe_size.
- AC7: `media.find_font()` behaves as follows:
- fc-list missing raises MediaError `fc-list not found on PATH; install fontconfig to draw captions`.
- fc-list listing no existing file raises MediaError starting `no font with Vietnamese support found`.
- It runs `fc-list --format %{file}\n :lang=vi` and `fc-match -s --format %{file}\n sans-serif:lang=vi`, and returns the first fc-match path that is also in the fc-list set.
- If none matches or fc-match fails, it returns the alphabetically first fc-list path.
- `vertical.py`, `pipeline.py` and `cli.py` still contain no `subprocess` string. The only `import subprocess` modules are media.py and events/incidents.py.
- AC8: On the synthetic 640x360 board clip (black board at 40,16,160,40 with a white 24x24 block at x=120 before t=2 and at x=160 from t=2), `vertical.find_score_box(clip)` returns a box that contains (40,16,160,40), with each edge within 12 px of it. On a black clip (burst_video recipe), it returns None.
- AC9: `render_vertical(board_clip, [(0.0, 320.0)], out, score_box=(40,16,160,40))` writes 1080x1920 h264. In the grey output frame at t=1.0, region rows 40..199 and columns 220..859 have a mean absolute difference ≤ 8 from the source frame at t=1.0 cropped to 160x40+40+16 and scaled to 640x160 by ffmpeg. The same holds at t=3.0 against the source at t=3.0, so the scoreline updates live. The t=3.0 output region differs from the t=1.0 expected region by ≥ 20, and a render without score_box differs from the expected region by ≥ 40, which shows the check can fail.
- AC10: With `vertical=True`, pipeline.run passes these keyword arguments to `vertical.render_vertical(clip, plan, dest, **kw)`:
- `score_box` is the manual box when one is given, and then `find_score_box` is never called. Otherwise it is the result of `vertical.find_score_box(clip)`.
- `caption` is `caption_text(entry['event'], entry['start'], entry['end'])`.
- A keyword is omitted when its value is None, so a clip with neither gets exactly three positional arguments.

Check this with a monkeypatched `select_segments` returning one 'goal' Segment (2.0, 8.0) on burst_video: kw == {'caption': "BÀN THẮNG · 1'"} without a box, and kw == {'score_box': (8,4,44,16), 'caption': "BÀN THẮNG · 1'"} with score_box=(8,4,44,16). End to end, with media.find_font and media.filter_video monkeypatched and a real render_vertical, the filter string passed to filter_video contains `text=BÀN THẮNG · 1\\\'`.
- AC11: When no box is found, pipeline.run still writes the vertical clip without an overlay. It emits exactly one WARNING record on logger `sportscut.pipeline` per such clip, containing `no scoreboard found in clip_01.mp4` and `--score-box`, which caplog can check. Logger `sportscut.pipeline` has a logging.NullHandler, and `sportscut cut BURST --out OUT --top 1 --min-len 4 --max-len 6 --vertical` still exits 0 with empty stderr and the same two stdout lines as T-043.
- AC12: Bad `score_box` calls to pipeline.run raise PipelineError before any clip is written:
- `pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True, score_box=(0,0,200,10))` raises `invalid score box: 0,0,200,10 does not fit the 160x120 frame`, and `out/clip_01.mp4` is not created.
- `score_box` with `vertical=False` raises PipelineError `score_box needs vertical=True`.
- Without score_box, the manifest keys and bytes are unchanged from T-043.
- AC13: CLI checks for `--score-box`:
- `sportscut cut V --out O --vertical --score-box 40,16,160,40` forwards `score_box=(40,16,160,40)` and `vertical=True` to run.
- Without the flag it forwards `score_box=None`.
- `--score-box 1,2,3` and `--score-box a,b,c,d` exit 2 with `expected x,y,w,h as four non-negative integers` on stderr.
- `--score-box 1,2,3,4` without `--vertical` exits 2 with `--score-box needs --vertical`.
- A MediaError such as a missing font prints `sportscut: error: <msg>` and exits 1.
- AC14: Documentation:
- README's `## Video dọc 9:16 cho TikTok/Reels (cut --vertical)` section gains text containing `--score-box`, `BÀN THẮNG · 34'` and `fc-list :lang=vi`, and README still ends with the byte-identical eval-crop section.
- The T-036 spec contains the `Updated by T-021: sportscut.media also owns find_font()` paragraph before its final `Updated by T-004:` paragraph, which is still last.
- The T-004 spec ends with a `## Updated by T-021` section mentioning `score_box=None` and `--score-box`.
- The T-043 spec has an appended `## Updated by T-021` section.
- AC15: `python -m pytest -q` reports 0 failed, with every pre-existing test unedited. `git diff --numstat $(git merge-base main HEAD)` shows 0 deleted lines for:
- sportscut/media.py, sportscut/cli.py;
- tests/test_media.py, tests/test_cli.py, tests/test_pipeline.py;
- README.md and the T-004, T-036 and T-043 design specs.

`sportscut eval tests/fixtures/eval --json` f1 equals the base. The eval-crop JSON equals the base except seconds_per_min. sportscut/events/, sportscut/reframe.py, sportscut/export.py, tests/conftest.py and tests/fixtures/ are unchanged, and no .mp4 is tracked.

## Out of scope

- OCR of the scoreline or the match clock, and parsing team names or scores into text.
- Changing sportscut/events/scoreboard.py, find_box thresholds or the 160x90 band. Detecting boards outside the top third of the frame.
- Burned-in commentary subtitles or speech-to-text; only the one-line event caption is in scope.
- Captions for `other` segments, configurable caption text, colours, font, size or position, and animation or fade of the overlays.
- Detecting the box once on the full match instead of per clip, and tracking a box that moves.
- A visible CLI warning, a --verbose/--quiet flag or logging configuration in the CLI.
- New manifest keys (for example whether an overlay was applied).
- Vertical overlays in the HTTP API, the web pages, the T-007 re-export or the `sportscut player` reel.
- Ball and player tracking for the crop (T-045 and later), and any change to reframe.plan_crop, eval-crop or detection.
- Bundling a font file in the repo, and Windows-specific font lookup without fontconfig.

## Decisions

- 2026-11-26 T-021 (R-004): The score overlay reuses T-013's `scoreboard.find_box` unchanged on `media.sample_top_band(clip)`, run per exported clip. The 160x90-grid box is mapped to source pixels by `vertical.band_box_to_source`: pad 1 grid pixel, integer floor/ceil scaling, snap outwards to even pixels. No OCR.
- 2026-11-26 T-021 (R-004): The overlay crops the box from the source on every frame inside one -vf graph: `split=2[sc_main][sc_box];[sc_main]<T-043 crop>[sc_v];[sc_box]crop=...,scale=SW:SH,setsar=1[sc_b];[sc_v][sc_b]overlay=x=OX:y=40`.
- The scale fits within 1000x160 with even sizes and is centred horizontally.
- media.filter_video is reused unchanged, and the score updates live with no second encode.
- 2026-11-26 T-021 (R-004): The caption is `<LABEL> · <minute>'`, with labels BÀN THẮNG, CỨU THUA, THẺ ĐỎ and TRANH CÃI, and no caption for `other`. The minute is floor(midpoint/60)+1 of video time.
- drawtext uses expansion=none, fontsize 64, white text on a black@0.6 box (borderw 16), centred at y=240, below the score band.
- Option values go through two-level ffmpeg escaping (level 1 `\\ ' :`, level 2 `\\ ' [ ] , ;`), so an apostrophe becomes `\\\'`.
- 2026-11-26 T-021 (R-004): The font is resolved by `media.find_font()` through fontconfig: `fc-list :lang=vi` gives the coverage set and `fc-match -s sans-serif:lang=vi` gives the preference order, with sorted-first as the fallback. Missing tools or no Vietnamese font raise MediaError with an install hint. It lives in media.py so media stays the only module running external tools (T-036), and it is called only when a caption is drawn.
- 2026-11-26 T-021 (R-004): render_vertical and vertical_filter gain optional score_box and caption (render_vertical resolves fontfile itself). With both None, calls and the filter string are byte-identical to T-043. The pipeline passes these keyword arguments only when they are not None, which keeps T-043's three-positional-argument fakes and wiring tests valid. This extends the T-043 decision that vertical.py only validates the path and builds the filter: vertical.py now also finds the score box via media and scoreboard.
- 2026-11-26 T-021 (R-004): A missing scoreboard is not an error. The clip is rendered without the overlay, and a WARNING is logged on `sportscut.pipeline`. That logger carries a logging.NullHandler, so stderr stays empty for an unconfigured CLI, as the T-043 AC12 test requires. This is the project's first logger.
- 2026-11-26 T-021 (R-004): The manual override is `pipeline.run(..., score_box=None)`, the new last parameter, and `cut --score-box X,Y,W,H` in source pixels. It is validated against probe_size(video) inside the try, so a bad box raises PipelineError before export, and it needs vertical (PipelineError in run, exit 2 in the CLI). A manual box skips detection and is used exactly as given.
- 2026-11-26 T-021 (R-004): No manifest change. Keys stay as in T-043, with vertical_file last.
- 2026-11-26 T-021 (R-004): media.py, cli.py, test_media.py, test_cli.py, test_pipeline.py, README.md and the T-004/T-036/T-043 specs are changed append- or insert-only (0 deleted lines). The T-036 note goes before its final T-004 paragraph. The README text is inserted inside the cut --vertical section, before the trailing eval-crop section. Any git-diff scope test added for T-021 is gated to branches starting with `office/T-021`.
- 2026-11-26 T-021 (R-004): No eval change is expected. f1 must equal the base, and eval-crop must equal the base except seconds_per_min.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-24-t-043-render-vertical-9-16-clips-from-design.md`
- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`
- `docs/superpowers/specs/2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md`
- `docs/superpowers/specs/2026-11-25-t-044-re-land-the-reviewed-t-017-design.md`

## Updated by T-022

Updated by T-022: `vertical_filter(..., fontfile=None, subtitles=None)` and `render_vertical(..., caption=None, subtitles=None)` gain `subtitles`, a list of layout cues `(start, end, text)` drawn as one drawtext per line in the lower third (last line at y=1600, 80 px per line, fontsize 56), each shown only during its cue. The subtitle filters come after the scoreboard overlay and the event caption. With `subtitles=None` or `[]`, every score_box/caption combination gives the byte-identical T-021 filter, and render_vertical calls `media.find_font()` only when a caption or subtitles are drawn. Non-empty subtitles without a fontfile raise ValueError `subtitles need a fontfile`.
