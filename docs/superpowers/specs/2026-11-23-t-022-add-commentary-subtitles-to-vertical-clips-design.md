# T-022: Add commentary subtitles to vertical clips via an optional speech-to-text extra

Request R-004. Plan: `docs/superpowers/plans/2026-11-23-t-022-add-commentary-subtitles-to-vertical-clips.md`.

## Product Owner request

Tự xuất video dọc 9:16 cho TikTok/Reels: tự bám theo bóng và cầu thủ để crop, có phụ đề và tỉ số.

## Goal

Add a `sportscut[asr]` extra (faster-whisper, `base` model downloaded on first use or by a separate `sportscut download-models` command, never committed). Add `sportscut/subtitles.py` with a `Transcriber` protocol, `transcribe(clip) -> list[(start, end, text)]` and `write_srt()`. Run it only on the exported clip audio, so 10 clips is at most 5 minutes of audio, which stays inside the 10-minute budget. Burn the subtitles into the lower third of the vertical clip (ffmpeg `subtitles` filter, or a drawtext fallback when ffmpeg lacks libass), wrapped to the 9:16 width, and also write `vertical/clip_NN.srt`. Language is auto-detected (Vietnamese and English commentary both work). Without the extra, the vertical clips still render with only the event caption and a one-line notice. Tests: a fake Transcriber gives exact SRT timings and text and burned-in frames that differ from the no-subtitle render. One real-model smoke test is skipped when the extra is not installed. Assumption: 'phụ đề' means a transcript of the original commentary. AI-written captions and voice-over belong to R-005.

## Acceptance criteria

- AC1: `pyproject.toml` `[project.optional-dependencies]` has `asr = ["faster-whisper>=1.0"]`. The `api`, `youtube` and `dev` lists are unchanged. No tracked file ends in .bin, .pt, .onnx, .safetensors or .mp4.
- AC2: `import sportscut.cli` and `import sportscut.subtitles` in a fresh interpreter (`python -c`) leave 'faster_whisper' out of `sys.modules`. `sportscut/subtitles.py` contains no `subprocess` string, and the only modules that import subprocess are still media.py and events/incidents.py.
- AC3: `subtitles.srt_time(0) == '00:00:00,000'`, `srt_time(4.8) == '00:00:04,800'`, `srt_time(3725.25) == '01:02:05,250'` and `srt_time(59.9996) == '00:01:00,000'`. `write_srt` creates missing parent directories and writes UTF-8 with LF newlines, with each cue as `i\nHH:MM:SS,mmm --> HH:MM:SS,mmm\ntext\n\n`. `write_srt([], p)` writes a 0-byte file, and the function returns `Path(p)`.
- AC4: `subtitles.layout([(1.0, 2.5, 'Vào rồi')]) == [(1.0, 2.5, 'Vào rồi')]`. `layout([(0.0, 5.7, 'aaaa bbbb cccc dddd eeee ffff gggg hhhh iiii jjjj kkkk llll')])` returns 2 cues: `(0.0, 4.8±1e-9, 'aaaa bbbb cccc dddd eeee\nffff gggg hhhh iiii jjjj')` and `(4.8±1e-9, 5.7, 'kkkk llll')`, the last ending exactly at 5.7. Writing that result with write_srt gives exactly `'1\n00:00:00,000 --> 00:00:04,800\naaaa bbbb cccc dddd eeee\nffff gggg hhhh iiii jjjj\n\n2\n00:00:04,800 --> 00:00:05,700\nkkkk llll\n\n'`. Every line produced by layout has at most 28 characters, and every cue has at most 2 lines.
- AC5: With `media.extract_audio` monkeypatched to return `np.zeros(96000, np.float32)` (6.0 s) and a fake Transcriber returning `[(2.0, 3.5, '  hai  '), (-0.2, 1.0, 'Vào rồi!'), (1.5, 1.5, 'x'), (4.0, 9.0, 'cuối'), (2.5, 3.0, '   ')]`, `subtitles.transcribe(clip, fake)` returns `[(0.0, 1.0, 'Vào rồi!'), (2.0, 3.5, 'hai'), (4.0, 6.0, 'cuối')]`. The fake is called exactly once with the very array extract_audio returned, and extract_audio is called with the clip. Decomposed Vietnamese text (NFD) comes back NFC-normalised. Empty audio returns [] without calling the transcriber. A transcriber raising RuntimeError('boom') raises `subtitles.TranscriptionError` with message `speech-to-text failed for clip_01.mp4: boom`.
- AC6: With a fake `faster_whisper` module in sys.modules:
- `WhisperTranscriber()` does not build a model.
- Two `transcribe(audio)` calls build `WhisperModel('base', device='cpu', compute_type='int8')` exactly once.
- Each model.transcribe call gets the same audio array with `language=None` and `vad_filter=True`, and segment objects come back as (start, end, text) tuples.
- `default_transcriber()` returns a WhisperTranscriber instance.
- `download_models()` calls `download_model('base')` and returns its result as a Path.

With `sys.modules['faster_whisper'] = None`, `default_transcriber()` returns None and `download_models()` raises ImportError.
- AC7: `vertical.vertical_filter([(0.0, 320.0)], 640, 360, subtitles=[(1.0, 2.5, 'Vào rồi\nhay quá')], fontfile='/fonts/DejaVuSans.ttf')` equals exactly `crop=w=202:h=360:x='219.0000':y=0,scale=1080:1920,setsar=1,drawtext=fontfile=/fonts/DejaVuSans.ttf:text=Vào rồi:expansion=none:fontsize=56:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=12:x=(w-text_w)/2:y=1520:enable='between(t,1.000,2.500)',drawtext=fontfile=/fonts/DejaVuSans.ttf:text=hay quá:expansion=none:fontsize=56:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=12:x=(w-text_w)/2:y=1600:enable='between(t,1.000,2.500)'`. A one-line cue gets y=1600. Line text goes through `vertical._escape`, so `it's 1:0` appears as `text=` + `_escape("it's 1:0")`. With score_box and caption, the result is the T-021 graph + ',' + the subtitle filters, with the caption drawtext before the subtitles. `subtitles=None` or `[]` gives a byte-identical T-021 string for all four score_box/caption combinations. Non-empty subtitles without fontfile raise ValueError `subtitles need a fontfile`.
- AC8: Calls made by `render_vertical`:
- `render_vertical(clip, path, out, subtitles=[(0.5, 2.0, 'x')])` (media functions monkeypatched) calls probe_size, then find_font, then filter_video, with a filter containing `enable='between(t,0.500,2.000)'`.
- `render_vertical(clip, path, out)` never calls find_font and passes the T-043 filter.
- `render_vertical(clip, path, out, subtitles=[])` passes the T-043 filter too and never calls find_font.
- AC9: Real ffmpeg check, skipped when `media.find_font()` raises MediaError. On a 3 s black 640x360 clip with audio, render once with `subtitles=layout([(0.5, 2.0, 'Vào rồi! Một bàn thắng tuyệt đẹp của đội chủ nhà ở phút cuối')])` and once without subtitles, both with crop path `[(0.0, 320.0)]`. Both outputs are 1080x1920 h264. In grey frames:
- At t=1.0, rows 1280..1919 have ≥ 2000 pixels whose absolute difference between the two renders is > 100.
- At t=1.0, rows 0..1279 have ≤ 50 such pixels.
- At t=1.0, columns 0..39 and 1040..1079 of rows 1280..1919 of the subtitled frame have no pixel > 100 (the text stays inside the 9:16 width).
- At t=2.5 (after the cue), the whole frame has ≤ 50 such pixels.
- AC10: Pipeline with a fake transcriber returning [(0.5, 2.0, 'Vào rồi! Bàn thắng')], with `vertical.render_vertical` monkeypatched to record its calls, on `pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, vertical=True, transcriber=fake)`:
- `out/vertical/clip_01.srt` equals `'1\n00:00:00,500 --> 00:00:02,000\nVào rồi! Bàn thắng\n\n'`.
- render_vertical gets kw `{'caption': ..., 'subtitles': [(0.5, 2.0, 'Vào rồi! Bàn thắng')]}` when the segment is a 'goal' (monkeypatched select_segments as in T-021 AC10), or `{'subtitles': [...]}` for 'other'.
- The manifest keys and order are the same as without a transcriber (T-043 keys + vertical_file).

A fake returning [] writes a 0-byte clip_01.srt and leaves 'subtitles' out of the render kwargs.
- AC11: Only exported clip audio is transcribed. With a recording fake transcriber on `pipeline.run(burst_video, out, top=2, min_len=4, max_len=6, vertical=True, transcriber=fake)` (real extract_audio):
- The fake is called exactly once per manifest entry.
- Each call's audio length / 16000 is within 0.25 s of that entry's `end - start`.
- The total transcribed audio is ≤ 12.5 s of the 90 s source.

With `transcriber=None`, `sportscut.subtitles.transcribe` and `write_srt` are never called and no .srt file is created.
- AC12: Pipeline errors:
- `pipeline.run(burst_video, out, transcriber=fake)` without vertical raises PipelineError `transcriber needs vertical=True` before any file is written (`out/clip_01.mp4` does not exist), and the fake is not called.
- A transcriber raising RuntimeError('boom') makes run raise PipelineError `speech-to-text failed for clip_01.mp4: boom`.
- `sportscut cut ... --vertical --subtitles` with such a transcriber (`subtitles.default_transcriber` monkeypatched) exits 1 with stderr `sportscut: error: speech-to-text failed for clip_01.mp4: boom\n`.
- AC13: CLI `--subtitles` (with cli.run monkeypatched to record kwargs):
- `cut v.mp4 --out O --vertical --subtitles` forwards `transcriber` equal to the object returned by a monkeypatched `subtitles.default_transcriber`, with empty stderr.
- When default_transcriber returns None, transcriber=None is forwarded, stderr is exactly `sportscut: notice: subtitles need the [asr] extra: pip install 'sportscut[asr]'; vertical clips are rendered without subtitles\n`, stdout keeps the clip and vertical path lines, and the exit code is 0.
- Without `--subtitles`, default_transcriber is never called and `transcriber=None` is forwarded.
- `cut v.mp4 --out O --subtitles` without --vertical exits 2 with `--subtitles needs --vertical` on stderr and run is not called.
- The pre-existing `cut --vertical` tests (empty stderr, two stdout lines) pass unedited.
- AC14: `sportscut download-models`:
- With a fake faster_whisper whose `download_model('base')` returns '/cache/base', it exits 0 and prints `downloaded faster-whisper base model to /cache/base`.
- With `sys.modules['faster_whisper'] = None`, it exits 1 with stderr exactly `sportscut download-models: error: needs the [asr] extra: pip install 'sportscut[asr]'\n`.
- When download_model raises OSError('offline'), it exits 1 with stderr `sportscut download-models: error: offline\n`.
- AC15: `tests/test_subtitles_asr_smoke.py` is skipped (not failed) when faster_whisper is not importable (`pytest.importorskip`) or no TTS tool (`say`, `espeak-ng` or `espeak`) is on PATH. When it runs, it uses the real `WhisperTranscriber`:
- English: a synthesized clip saying 'What a goal! The home team scores in the final minute.' gives ≥ 1 cue with 0 ≤ start < end ≤ clip duration + 0.05, and the joined lower-case text contains 'goal'.
- Vietnamese: when a vi voice is available, a synthesized clip saying 'Vào rồi! Một bàn thắng tuyệt đẹp' gives ≥ 1 cue whose joined text contains at least one Vietnamese diacritic letter (for example à, ồ, ộ, ắ, ẹ, đ).
- AC16: Documentation:
- README's `## Video dọc 9:16 cho TikTok/Reels (cut --vertical)` section gains text containing `--subtitles`, `pip install 'sportscut[asr]'`, `sportscut download-models` and `vertical/clip_NN.srt`.
- README still ends with the byte-identical eval-crop section.
- The T-004, T-021 and T-043 design specs each end with an appended `## Updated by T-022` section mentioning `transcriber=None` (T-004), `subtitles=None` (T-021) and `--subtitles` (T-043).
- AC17: Whole suite and scope:
- `python -m pytest -q` reports 0 failed, and every pre-existing test file is unedited.
- `git diff --numstat $(git merge-base main HEAD)` shows 0 deleted lines for sportscut/cli.py, sportscut/pipeline.py, pyproject.toml, README.md and the T-004/T-021/T-043 specs. Any git-diff scope test is gated to branches starting with `office/T-022`.
- `python -m sportscut eval tests/fixtures/eval --json` f1 equals the base, and the eval-crop JSON equals the base except seconds_per_min.
- sportscut/media.py, sportscut/events/, sportscut/reframe.py, sportscut/export.py, tests/conftest.py and tests/fixtures/ are unchanged.

## Out of scope

- AI-written captions, translated subtitles and voice-over (R-005).
- A libass `subtitles`/`ass` filter path, ASS styling, karaoke or word-level highlighting, and configurable font, size, colour, position or wrap width.
- Making subtitles the default for `cut --vertical`, and changing behaviour when `--subtitles` is absent.
- Choosing or overriding the model size or language from the CLI, GPU support, and other ASR engines.
- Transcribing the full match, or using the transcript for highlight detection or event tagging.
- New manifest keys (for example subtitle_file), printing the .srt path to stdout, and subtitles in the HTTP API, the web pages, the T-007 re-export or the `sportscut player` reel.
- Adding faster-whisper to the dev extra or CI, committing model files, and bundling fonts.
- Changes to media.py, reframe.plan_crop, the scoreboard overlay, the event caption, detection or the eval sets.

## Decisions

- 2026-11-27 T-022 (R-004): Subtitles are opt-in with `sportscut cut --vertical --subtitles` (exit 2 without --vertical). An automatic default would print the missing-extra notice on every `cut --vertical`, which breaks the pinned empty-stderr/two-line tests (test_cli, T-018 AC12, T-021 AC11). It would also run a real model in the existing suite wherever the extra is installed. Without --subtitles, behaviour is byte-identical to T-021.
- 2026-11-27 T-022 (R-004): The speech-to-text extra is `sportscut[asr]` = `faster-whisper>=1.0`, and it is not part of `dev`. The model is faster-whisper `base` on CPU int8, loaded lazily on the first transcribe call and cached by faster-whisper in the Hugging Face cache outside the repo. `sportscut download-models` pre-fetches it. Model files are never committed.
- 2026-11-27 T-022 (R-004): `sportscut/subtitles.py` holds the `Transcriber` protocol (`transcribe(audio: float32 mono 16 kHz ndarray) -> Iterable[(start, end, text)]`), `WhisperTranscriber`, `default_transcriber()` (None without the extra), `download_models()`, `transcribe(clip, transcriber)`, `layout(cues)`, `srt_time` and `write_srt`. It gets audio only through `media.extract_audio` and never imports subprocess or faster_whisper at module level.
- 2026-11-27 T-022 (R-004): Language is auto-detected per clip (`language=None`), and `vad_filter=True` and `condition_on_previous_text=False` are set. Cues are normalised (whitespace collapsed, NFC), clamped to [0, clip audio length], cues that are empty or have end <= start are dropped, and the rest are sorted. Exceptions from the transcriber become `TranscriptionError` `speech-to-text failed for <clip name>: <exc>`, which the pipeline re-raises as PipelineError (CLI exit 1).
- 2026-11-27 T-022 (R-004): Wrapping is done in Python: at most 28 characters per line (textwrap, long words broken), at most 2 lines on screen. Longer cues are split into consecutive 2-line chunks, with time divided in proportion to character count and the last chunk ending at the cue end. The SRT holds exactly these burned cues.
- 2026-11-27 T-022 (R-004): Burn-in uses drawtext only, the fallback the task allows, not the libass `subtitles` filter. Drawtext is already required by the T-021 caption, renders the same on every ffmpeg build, and uses the same `media.find_font()` Vietnamese font. There is one drawtext per line: fontsize 56, white on black@0.6 (boxborderw 12), centred x, last line at y=1600 and 80 px line spacing (lower third), `enable='between(t,S,E)'` with 3 decimals, and text escaped by `vertical._escape`.
- 2026-11-27 T-022 (R-004): `vertical_filter` and `render_vertical` gain `subtitles=None` as their last parameter. None or [] keeps T-021 output byte-identical. Subtitle filters are appended after the overlay and caption, and `find_font()` is called when a caption or a non-empty subtitles list is drawn. This extends the T-021 decision on optional overlay arguments.
- 2026-11-27 T-022 (R-004): `pipeline.run(..., score_box=None, transcriber=None)`: transcriber is the new last parameter and needs vertical=True (PipelineError `transcriber needs vertical=True`, raised before any work). It runs only on each exported `out/clip_NN.mp4`, at most top × max_len of audio (5 min for 10 × 30 s), which keeps the 10-minute budget. It always writes `out/vertical/clip_NN.srt` (0 bytes when there is no speech) and passes `subtitles=` to render_vertical only when cues are non-empty. No manifest change.
- 2026-11-27 T-022 (R-004): Without the extra, `--subtitles` prints exactly one stderr line `sportscut: notice: subtitles need the [asr] extra: pip install 'sportscut[asr]'; vertical clips are rendered without subtitles`, renders with the event caption and score overlay only, and exits 0. No new logger records are added on `sportscut.pipeline`, so the T-021 one-warning-per-clip tests stay valid.
- 2026-11-27 T-022 (R-004): cli.py, pipeline.py, pyproject.toml, README.md and the T-004/T-021/T-043 specs are changed insert- or append-only (0 deleted lines). media.py, events/, reframe.py, export.py, tests/conftest.py and tests/fixtures/ are unchanged. Any git-diff scope test is gated to branches starting with `office/T-022`. No eval change is expected: f1 equals the base, and eval-crop equals the base except seconds_per_min.
- 2026-11-27 T-022 (R-004): The real-model smoke test is skipped when faster_whisper is not importable or no TTS tool (say/espeak-ng/espeak) is available. CI does not install the extra, so the real-model check is local only, and all CI coverage uses fake Transcribers and a fake faster_whisper module.
- Tech Lead (dev_blocked): 2026-11-27 T-022 (R-004) Tech Lead (dev_blocked, round 1): The T-022 code is not at fault; there are two separate root causes. (1) Stale base: the branch was cut from 6116b9b, and T-045 (a3f277e) then added a paragraph to the end of README's cut --vertical section. test_t021_acceptance::test_ac14_readme compares against the live main:README.md, so it fails on any branch that main has passed. Agents may not rebase, so T-022 restarts from current main and reuses its finished work from office/T-022 (82ebdf4). README.md is the only file both sides change. (2) Spec conflict: test_t021_acceptance::test_ac14_t004_spec and ::test_ac14_t043_spec require '## Updated by T-021' to be the last '## ' heading in the T-004 and T-043 specs, and they have no branch gate. Every later task that appends an 'Updated by' section breaks them, as T-022's AC16 must. Options (b) and (c) only move the problem to the next task, so (a) is chosen. AC17 is amended: tests/test_t021_acceptance.py may be edited only to put the two `headings[-1] == '## Updated by T-021'` assertions behind an own-branch gate (office/T-021, the decision-351 pattern). On other branches they become `'## Updated by T-021' in headings`. Every other assertion in that file stays byte-identical, including the T-018<T-021 order check and the needle checks. No other pre-existing test is edited.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-021-overlay-the-live-broadcast-scoreboard-and-design.md`
- `docs/superpowers/specs/2026-11-24-t-043-render-vertical-9-16-clips-from-design.md`
- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`
- `docs/superpowers/specs/2026-11-23-t-035-scaffold-sportscut-packaging-version-cli-and-design.md`
