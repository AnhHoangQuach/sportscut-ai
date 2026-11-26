# Plan T-022: Add commentary subtitles to vertical clips via an optional speech-to-text extra

Design: `docs/superpowers/specs/2026-11-23-t-022-add-commentary-subtitles-to-vertical-clips-design.md`.

## Implementation plan

# T-022: Add commentary subtitles to vertical clips via an optional speech-to-text extra

Request R-004. PO request: "Tự xuất video dọc 9:16 cho TikTok/Reels: tự bám theo bóng và cầu thủ để crop, có phụ đề và tỉ số."

## Context (current main, 189f3c1)

- `sportscut/vertical.py` (T-043, T-021) has `vertical_filter(crop_path, width, height, score_box=None, caption=None, fontfile=None)`, `drawtext_filter(caption, fontfile)`, `_escape(value)` (two-level ffmpeg escaping) and `render_vertical(clip, crop_path, out, score_box=None, caption=None)`. `render_vertical` calls `media.find_font()` only when a caption is drawn, then `media.filter_video(clip, vf, out)`. When `score_box` and `caption` are both None, the filter string is byte-identical to T-043.
- `sportscut/pipeline.py` `run(video, out_dir, top, min_len, max_len, events, vertical=False, score_box=None)` exports `out/clip_NN.mp4`. With `vertical=True` it renders each clip to `out/vertical/clip_NN.mp4` and passes `score_box`/`caption` as keyword arguments only when they are not None.
- `sportscut/media.py` already has `extract_audio(path) -> float32 mono 16 kHz ndarray` (`SAMPLE_RATE = 16_000`, the exact input format Whisper expects) and `find_font()`.
- Existing tests pin these behaviours, and they must stay valid without edits:
  - `cut --vertical` gives empty stderr and exactly two stdout lines (`tests/test_cli.py`, `test_t018_acceptance.py` AC12, `test_t021_acceptance.py` AC11).
  - Exactly one WARNING record on `sportscut.pipeline` per clip without a scoreboard (`test_t021_acceptance.py` AC11, `test_pipeline.py`).
  - The `dev` extra list in `pyproject.toml` is fixed (`test_t005_acceptance.py`).
  - Only `media.py` and `events/incidents.py` import subprocess, and `vertical.py`, `pipeline.py` and `cli.py` contain no `subprocess` string (T-021 AC7).

## Design

### Why subtitles are opt-in (`cut --vertical --subtitles`)
The task says that without the extra, the vertical clips render with only the event caption and a one-line notice. If subtitles were automatic, every `cut --vertical` run without the extra (CI) would print the notice to stderr. That breaks the three existing empty-stderr tests above, and they must not be edited. An automatic default would also run a real model inside the existing suite on any machine where the extra is installed, which makes the suite slow and nondeterministic. So subtitles are requested with `--subtitles` (which needs `--vertical`). Without the extra, `--subtitles` prints one notice line to stderr and the clips render without subtitles (exit 0). Without `--subtitles`, behaviour is byte-identical to T-021. Opting in also makes the extra CPU cost explicit.

### Packaging
`pyproject.toml` gains `asr = ["faster-whisper>=1.0"]` under `[project.optional-dependencies]`. `dev` is NOT changed, so CI never installs the model. The `base` model is downloaded by faster-whisper into the Hugging Face cache (`~/.cache/huggingface`, outside the repo) on first use, or ahead of time by `sportscut download-models`. Nothing model-related is committed.

### New module `sportscut/subtitles.py`
It has no subprocess and no top-level import of faster_whisper. It imports `textwrap`, `unicodedata`, `pathlib.Path`, `typing.Protocol/Iterable`, `numpy` and `from sportscut import media`. Always call `media.extract_audio` and `media.SAMPLE_RATE` through the module so that tests can monkeypatch them.

```python
MODEL_NAME = "base"
WRAP_CHARS = 28          # max characters per subtitle line (fits 1080 px at fontsize 56)
MAX_LINES = 2            # lines shown at once
ASR_HINT = "pip install 'sportscut[asr]'"
Cue = tuple[float, float, str]   # (start s, end s, text), times relative to the clip

class TranscriptionError(RuntimeError): ...

class Transcriber(Protocol):
    def transcribe(self, audio: np.ndarray) -> Iterable[tuple[float, float, str]]:
        """audio: float32 mono at media.SAMPLE_RATE (16 kHz). Returns (start, end, text) in seconds."""

class WhisperTranscriber:
    def __init__(self): self._model = None
    def transcribe(self, audio):
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
        segments, _info = self._model.transcribe(audio, language=None, vad_filter=True,
                                                 condition_on_previous_text=False)
        return [(s.start, s.end, s.text) for s in segments]

def default_transcriber() -> WhisperTranscriber | None:
    # try: import faster_whisper  (ImportError -> return None); else return WhisperTranscriber()

def download_models() -> Path:
    from faster_whisper import download_model   # ImportError propagates to the CLI
    return Path(download_model(MODEL_NAME))

def transcribe(clip, transcriber: Transcriber) -> list[Cue]: ...
def layout(cues) -> list[Cue]: ...
def srt_time(t: float) -> str: ...
def write_srt(cues, path) -> Path: ...
```

`language=None` makes faster-whisper detect the language for each clip, so Vietnamese and English commentary both work. `vad_filter=True` skips crowd noise without speech.

`transcribe(clip, transcriber)`:
1. `audio = media.extract_audio(clip)`. A MediaError propagates.
2. If `audio.size == 0`, return `[]` without calling the transcriber.
3. Call `transcriber.transcribe(audio)` once. Any `Exception` it raises is re-raised as `TranscriptionError(f"speech-to-text failed for {Path(clip).name}: {exc}")`.
4. Normalise each item:
   - `text = unicodedata.normalize("NFC", " ".join(str(text).split()))`
   - `start = max(0.0, float(start))`
   - `end = min(float(end), audio.size / media.SAMPLE_RATE)`
   - Drop the item if the text is empty or `end <= start`.
5. Return the items sorted by `(start, end)`.

`layout(cues)` makes each cue fit the 9:16 frame:
- `lines = textwrap.wrap(text, WRAP_CHARS, break_long_words=True, break_on_hyphens=False)`.
- The lines are grouped into chunks of `MAX_LINES` consecutive lines.
- The cue's time is split between chunks in proportion to `sum(len(line) for line in chunk)`. Chunk k ends at `start + (end-start) * cum_k / total`, and the last chunk ends exactly at `end`.
- Each output cue's text is the chunk's lines joined with `"\n"`.
- A cue that fits in 1 or 2 lines keeps its original times.

`srt_time(t)`: `ms = round(t * 1000)`, then `HH:MM:SS,mmm` (`ms // 3_600_000`, ...), zero-padded.

`write_srt(cues, path)`:
- It creates the parent directories.
- It writes UTF-8 with `"\n"` newlines (`newline="\n"`). Each cue i (1-based) is the block `f"{i}\n{srt_time(s)} --> {srt_time(e)}\n{text}\n\n"`.
- Zero cues give an empty (0-byte) file. The function returns `Path(path)`.

Example. `layout([(0.0, 5.7, "aaaa bbbb cccc dddd eeee ffff gggg hhhh iiii jjjj kkkk llll")])` gives two cues: `(0.0, ≈4.8, "aaaa bbbb cccc dddd eeee\nffff gggg hhhh iiii jjjj")` and `(≈4.8, 5.7, "kkkk llll")`. `write_srt` writes them as:

```
1
00:00:00,000 --> 00:00:04,800
aaaa bbbb cccc dddd eeee
ffff gggg hhhh iiii jjjj

2
00:00:04,800 --> 00:00:05,700
kkkk llll

```

### Burn-in: `sportscut/vertical.py` (drawtext, lower third)
New constants: `SUB_FONTSIZE = 56`, `SUB_LAST_Y = 1600` (top y of the last line), `SUB_LINE_H = 80`.

```python
def subtitle_filters(cues, fontfile) -> str:
    # for each cue (start, end, text), lines = text.split("\n"), n = len(lines);
    # line j gets y = SUB_LAST_Y - (n - 1 - j) * SUB_LINE_H and the filter
    # f"drawtext=fontfile={_escape(str(fontfile))}:text={_escape(line)}:expansion=none:"
    # f"fontsize=56:fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=12:"
    # f"x=(w-text_w)/2:y={y}:enable='between(t,{start:.3f},{end:.3f})'"
    # all filters joined with "," in cue order, then line order
```

- `vertical_filter(..., fontfile=None, subtitles=None)` gains `subtitles` as its new last parameter.
  - When `subtitles` is None or empty, the result is byte-identical to today for every combination of `score_box` and `caption`.
  - Otherwise, non-empty `subtitles` without `fontfile` raises `ValueError("subtitles need a fontfile")`. The result is the current graph (base, overlay and/or caption) + `","` + `subtitle_filters(subtitles, fontfile)`.
  - The early `return base` must also check that subtitles is falsy.
- `render_vertical(clip, crop_path, out, score_box=None, caption=None, subtitles=None)` calls `media.find_font()` when `caption is not None or subtitles`, and passes `subtitles` through.

Why one drawtext per line: drawtext centres each line by itself (`x=(w-text_w)/2`), no newline enters the filtergraph, and each line has its own `enable` window. Lines sit at y 1520..1668 for 2 lines, inside the lower third (y ≥ 1280) and above the bottom TikTok UI. Wrapping is done in Python (`layout`) so the SRT and the burned frames match.

### Pipeline `sportscut/pipeline.py`
- `run(..., score_box=None, transcriber=None)`: `transcriber` is the new last parameter.
- Next to the `top < 1` check (before `require_ffmpeg`), `transcriber is not None and not vertical` raises `PipelineError("transcriber needs vertical=True")`.
- In the vertical loop, when `transcriber is not None`, do this before `render_vertical`:
  ```python
  try:
      cues = subtitles.layout(subtitles.transcribe(clip, transcriber))
  except subtitles.TranscriptionError as exc:
      raise PipelineError(str(exc)) from exc
  subtitles.write_srt(cues, (Path(out_dir) / rel).with_suffix(".srt"))   # out/vertical/clip_NN.srt
  if cues:
      extra["subtitles"] = cues
  ```
- Transcription runs on the exported `out/clip_NN.mp4` (≤ top × max_len seconds, 10 × 30 s = 5 min at most), never on the full match. Whisper `base` int8 on a laptop CPU handles 5 min of audio in about 1 min, which fits the 10-minute budget.
- When `transcriber` is None, nothing in `subtitles` is called and all calls are unchanged.
- No manifest change.

### CLI `sportscut/cli.py` (insert-only)
- `from sportscut import subtitles`.
- `cut` gains `--subtitles` (`store_true`, help `burn commentary subtitles into --vertical clips (needs the [asr] extra)`). `--subtitles` without `--vertical` gives `cut_parser.error("--subtitles needs --vertical")` (exit 2), checked next to the `--score-box` check.
- In the `cut` branch:
  - `transcriber = None`.
  - If `args.subtitles`: `transcriber = subtitles.default_transcriber()`. If that is None, print `NOTICE` to stderr once, where `NOTICE = "sportscut: notice: subtitles need the [asr] extra: pip install 'sportscut[asr]'; vertical clips are rendered without subtitles"`.
  - Always pass `transcriber=transcriber` to `run`. Stdout is unchanged (the clip path, then the vertical path).
  - `subtitles.default_transcriber` is never called without `--subtitles`.
- New subcommand `download-models` (help `download the speech-to-text model used by cut --subtitles`, no arguments):
  - It calls `subtitles.download_models()`.
  - On success it prints `downloaded faster-whisper base model to <path>` and exits 0.
  - On `ImportError` it prints to stderr `sportscut download-models: error: needs the [asr] extra: pip install 'sportscut[asr]'` and exits 1.
  - On any other `Exception` it prints `sportscut download-models: error: <exc>` and exits 1.

### Docs
- README: insert a paragraph and an example in `## Video dọc 9:16 cho TikTok/Reels (cut --vertical)`, before `## Video dọc 9:16: đo khung cắt (eval-crop)`. It covers `pip install 'sportscut[asr]'`, `sportscut download-models`, `sportscut cut match.mp4 --out out --vertical --subtitles`, `out/vertical/clip_NN.srt`, automatic language detection (Vietnamese and English), and the notice when the extra is missing.
- Append `## Updated by T-022` sections to the T-004, T-021 and T-043 design specs.

## Files
Create:
- `sportscut/subtitles.py`
- `tests/test_subtitles.py`
- `tests/test_subtitles_asr_smoke.py`
- `tests/test_t022_acceptance.py` (Tester)

Change:
- `pyproject.toml`
- `sportscut/vertical.py`
- `sportscut/pipeline.py`
- `sportscut/cli.py`
- `README.md`
- the T-004, T-021 and T-043 design specs

## Steps (TDD: write each test, watch it fail, then write the code)
1. Write tests for `srt_time`/`write_srt` (exact text, empty file), then implement them.
2. Write tests for `layout` (short cue unchanged, the 12-word example, Vietnamese example), then implement it.
3. Write tests for `transcribe` with a fake Transcriber and a monkeypatched `media.extract_audio` (normalise, clamp, sort, NFC, empty audio, error wrapping), then implement it.
4. Write tests for `WhisperTranscriber`, `default_transcriber` and `download_models` with a fake `faster_whisper` module in `sys.modules`, plus a subprocess import test, then implement them.
5. Write tests for `subtitle_filters`/`vertical_filter` exact strings and the byte-identical T-021 strings, then implement them. Add the `render_vertical` call-order test.
6. Write the real-ffmpeg burned-frame test, then make it pass.
7. Write pipeline wiring tests (SRT written, kwargs, empty transcript, only clip audio, errors, needs vertical), then implement them.
8. Write CLI tests (`--subtitles` forwarding, notice, needs `--vertical`, `download-models`), then implement them.
9. Add the `asr` extra, the smoke test, the README text and the spec sections.
10. Verify:
    - `python -m pytest -q`
    - `python -m sportscut eval tests/fixtures/eval --json` (f1 equal to the base)
    - `python -m sportscut eval-crop tests/fixtures/eval_crop --json` (equal to the base except seconds_per_min)
    - `python -m sportscut cut <video> --out /tmp/o --vertical --subtitles` without the extra prints the notice and exits 0

## Assumptions
- 'phụ đề' means a transcript of the original commentary (from the task). AI-written captions and voice-over belong to R-005.
- Subtitles are opt-in through `--subtitles`. See "Why subtitles are opt-in" above: an automatic default would break pinned empty-stderr tests and make the suite depend on whether the extra is installed.
- Burn-in uses drawtext only, the fallback the task names. Drawtext is already required by the T-021 caption, renders the same on every ffmpeg build with or without libass, uses the same Vietnamese font from `find_font()`, and leaves one code path to test. A libass `subtitles` filter path is not built.
- The SRT contains exactly the cues that are burned in (wrapped and split into 2-line chunks), timed from the start of the clip.

## Test plan

- Unit tests/test_subtitles.py::test_srt_time_values and ::test_write_srt_exact_and_empty: the AC3 values, the AC4 SRT text, a 0-byte file for [], and parent directories created under tmp_path.
- Unit tests/test_subtitles.py::test_layout_short_cue_unchanged, ::test_layout_splits_into_two_line_chunks (the 12-word example with pytest.approx boundaries) and ::test_layout_vietnamese_lines_within_28 (all lines ≤ 28 chars, ≤ 2 lines per cue, chunk times contiguous from start to end).
- Unit tests/test_subtitles.py::test_transcribe_normalises_clamps_sorts (monkeypatch sportscut.media.extract_audio to np.zeros(96000); fake Transcriber class that records calls; identity check on the array), ::test_transcribe_nfc, ::test_transcribe_empty_audio_skips and ::test_transcribe_wraps_errors.
- Unit tests/test_subtitles.py::test_whisper_transcriber_lazy_and_auto_language: build a fake `faster_whisper` module with types.ModuleType whose WhisperModel records init args and transcribe kwargs and returns ([SimpleNamespace(start=..., end=..., text=...)], info). Put it in sys.modules with monkeypatch.setitem. Also ::test_default_transcriber_with_and_without_extra (sys.modules['faster_whisper']=None for the missing case) and ::test_download_models_uses_base.
- Unit tests/test_subtitles.py::test_import_does_not_load_faster_whisper: subprocess `[sys.executable, '-c', 'import sys, sportscut.cli, sportscut.subtitles; print("faster_whisper" in sys.modules)']` prints False. Plus a grep check that subtitles.py has no 'subprocess'.
- Unit tests/test_subtitles.py::test_vertical_filter_with_subtitles_exact (the AC7 string), ::test_vertical_filter_without_subtitles_byte_identical (None and [] against the current outputs for the four score_box/caption combinations), ::test_subtitles_need_fontfile, ::test_subtitle_line_text_is_escaped and ::test_render_vertical_subtitles_call_order (monkeypatch media.probe_size/find_font/filter_video to record the order).
- Integration tests/test_subtitles.py::test_burned_subtitles_lower_third_only: build a 3 s black 640x360 libx264 clip with anoisesrc audio in tmp_path using ffmpeg. Render with and without subtitles and extract grey frames at t=1.0 and t=2.5 with `ffmpeg -ss T -i out.mp4 -frames:v 1 -f rawvideo -pix_fmt gray pipe:1`, reshaped to (1920,1080). Check the AC9 pixel-count thresholds and the column margins. Skip if media.find_font() raises MediaError.
- Integration tests/test_subtitles.py::test_pipeline_writes_srt_and_passes_subtitles, ::test_pipeline_empty_transcript_writes_empty_srt, ::test_pipeline_transcribes_only_clip_audio (top=2 on burst_video with real extract_audio and a recording fake), ::test_pipeline_transcriber_needs_vertical and ::test_pipeline_transcription_error. Monkeypatch vertical.render_vertical with a `(clip, crop_path, dest, **kw)` recorder where pixels do not matter, and monkeypatch select_segments for the goal/other cases as in the T-021 AC10 tests.
- Unit tests/test_subtitles.py::test_cli_subtitles_forwards_transcriber, ::test_cli_subtitles_notice_without_extra (capsys, exact stderr, exit 0), ::test_cli_without_subtitles_never_checks_extra (default_transcriber monkeypatched to pytest.fail), ::test_cli_subtitles_needs_vertical (SystemExit 2), ::test_cli_transcription_error_exit_1 and ::test_cli_download_models_{ok,missing_extra,failure}.
- Smoke tests/test_subtitles_asr_smoke.py::test_real_model_english and ::test_real_model_vietnamese. Use pytest.importorskip('faster_whisper'). Synthesize speech with `say -o x.aiff` (vi: `say -v Linh` when `say -v '?'` lists vi_VN) or `espeak-ng -w x.wav` (vi: `-v vi`), and skip when no tool or voice is available. Build a 160x120 black mp4 with that audio via ffmpeg in tmp_path, then run subtitles.transcribe(clip, WhisperTranscriber()) and check the AC15 assertions. Not run in CI because the dev extra does not include faster-whisper.
- Tester acceptance tests/test_t022_acceptance.py: write independent tests for AC1–AC17 from the acceptance criteria, including the pyproject TOML parse, the git-diff scope check gated to office/T-022 branches, and the eval/eval-crop comparison against the base. Show the burned-frame check can fail by asserting that the no-subtitle render compared to itself gives < 2000 differing pixels.
- Commands: `python -m pytest -q` (quote the summary line); `python -m sportscut eval tests/fixtures/eval --json` (f1 equal to the base); `python -m sportscut eval-crop tests/fixtures/eval_crop --json`; `python -m sportscut download-models` without the extra exits 1 with the hint.

## Deviations

- Restart (Tech Lead dev_blocked decision, 2026-11-27, round 1, in DECISIONS.md): the branch was restarted from main a3f277e and the finished T-022 work from office/T-022 (82ebdf4) was brought across unchanged with `git diff 6116b9b 82ebdf4 -- <files> | git apply`. The code was not rewritten.
- README: the T-022 subsection now sits at the end of `## Video dọc 9:16 cho TikTok/Reels (cut --vertical)`, after T-045's `Cập nhật (T-045): ...` paragraph and right before `## Video dọc 9:16: đo khung cắt (eval-crop)`. The diff against main has 0 deleted lines, and the eval-crop tail is byte-identical to main.
- AC17 amendment (same Tech Lead decision): `tests/test_t021_acceptance.py` is the one pre-existing test that was edited. A `_on_t021_branch()` helper was added (`git rev-parse --abbrev-ref HEAD` starts with `office/T-021`). In `test_ac14_t004_spec` and `test_ac14_t043_spec`, only the `assert headings[-1] == "## Updated by T-021"` line changed: it now applies on T-021's own branch, and on other branches the check is `"## Updated by T-021" in headings`. No other line in that file changed.
