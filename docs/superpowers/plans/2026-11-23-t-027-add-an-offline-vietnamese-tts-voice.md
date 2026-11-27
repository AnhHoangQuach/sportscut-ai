# Plan T-027: Add an offline Vietnamese TTS voice-over mixed with ducking via `--voiceover`

Design: `docs/superpowers/specs/2026-11-23-t-027-add-an-offline-vietnamese-tts-voice-design.md`.

## Implementation plan

# T-027: Offline Vietnamese TTS voice-over mixed with ducking (`--voiceover`)

Request R-005 (Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt). T-026 already writes `OUT/clip_NN.script.json` (1-3 timed Vietnamese lines per clip) when `cut --voiceover` is given. This task turns that script into audio. It synthesizes each line offline with Piper, places it at its scripted time, and mixes it over the clip while the original audio is lowered by 12 dB during speech. The result is `OUT/clip_NN.vo.mp4`, plus `OUT/vertical/clip_NN.vo.mp4` with `--vertical`. The original clips are never modified.

## Read first
- `docs/superpowers/specs/2026-11-23-t-026-generate-a-timed-vietnamese-commentary-script-design.md` and its plan (`script.write_script`, `speech_seconds`, `pipeline._write_script`, manifest `script_file`).
- `docs/superpowers/specs/2026-11-23-t-022-add-commentary-subtitles-to-vertical-clips-design.md`. This task copies its patterns: the optional extra imported lazily, `default_transcriber()` returning None without the extra, `download-models`, the stderr notice and the real-model smoke test.
- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md` (pipeline.run and the manifest).
- `sportscut/pipeline.py`, `sportscut/cli.py`, `sportscut/media.py`, `sportscut/subtitles.py`, `sportscut/commentary/script.py`, `tests/conftest.py`.

**Step 0 (precondition).** `python -c "from sportscut.commentary import script; from sportscut.pipeline import run; import inspect; assert 'voiceover' in inspect.signature(run).parameters; print('READY')"` must print READY. Otherwise report BLOCKED.

## Constraints from existing tests (must keep passing unedited)
- `tests/test_t022_acceptance.py::test_ac2_no_subprocess_in_subtitles_and_only_two_importers` and `tests/test_media.py`: only `media.py` and `events/incidents.py` may import subprocess, and `cli.py`/`pipeline.py` must not contain the word `subprocess`. So **all ffmpeg calls go into `media.py`**, and `voiceover.py` must not contain the string `subprocess`.
- T-022 `download-models` tests pin the exact stdout/stderr of `sportscut download-models` with no arguments. So the voice download is opt-in with `--tts`, and the no-argument behaviour stays byte-identical.
- T-026 tests call `cli.main(['cut', ..., '--voiceover'])` with a fake `cli.run`, without the [tts] extra, and require exit 0 and exact stdout. They also call `pipeline.run(..., voiceover=True)` with no synthesizer and require `script_file` as the **last** manifest key. So without the extra, `--voiceover` prints an install hint on **stderr**, exits 0 and still writes the scripts. With no synthesizer, `run(voiceover=True)` behaves exactly as in T-026.
- Every fake `cli.run` in tests accepts `**kwargs`, so adding a `synthesizer=` keyword is safe.

## Design

### 1. `pyproject.toml`
Add `tts = ["piper-tts>=1.3"]` to `[project.optional-dependencies]` after `asr`. The other lists stay unchanged, and `dev` does not include piper.

### 2. `sportscut/commentary/voiceover.py` (new)
This file uses numpy and stdlib only (`os`, `shutil`, `tempfile`, `urllib.request`, `wave`, `pathlib`, `typing.Protocol`). It never imports `piper` at module level, and it never contains the word `subprocess`. Imports: `from sportscut import media`.

```python
VOICE = "vi_VN-vais1000-medium"
VOICE_URL = ("https://huggingface.co/rhasspy/piper-voices/resolve/main/"
             "vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium")   # + ".onnx" / ".onnx.json"
TTS_HINT = "pip install 'sportscut[tts]'"
DUCK_DB = 12.0           # original audio is lowered by this much while speech plays
DUCK_PAD = 0.15          # s of ducking before and after each spoken interval
MIX_RATE = 48000

class SynthesisError(RuntimeError): ...

class Synthesizer(Protocol):
    sample_rate: int
    def synthesize(self, text: str) -> np.ndarray:
        """Mono float samples in [-1, 1] at self.sample_rate."""
```

Functions:
- `voice_dir() -> Path`: `Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'sportscut' / 'piper'`.
- `_fetch(url: str, dest: Path) -> None`: `urllib.request.urlopen(url, timeout=60)` piped to the file with `shutil.copyfileobj`. Tests monkeypatch this.
- `download_voice() -> Path`: creates `voice_dir()`. For each suffix in `('.onnx', '.onnx.json')`, in that order: if `voice_dir()/f'{VOICE}{suffix}'` is missing, it calls `_fetch(VOICE_URL + suffix, part)` where `part` is the same path with an extra `.part` suffix, then `part.replace(final)`. On any exception it unlinks `part` (missing_ok) and re-raises. Files that already exist are not fetched again. It returns the `.onnx` path.
- `class PiperSynthesizer`: `__init__` does nothing (no download, no import). A private `_load()` runs once: `path = download_voice()`, `from piper import PiperVoice`, `self._voice = PiperVoice.load(str(path))`. The `sample_rate` property calls `_load()` and returns `int(self._voice.config.sample_rate)`. `synthesize(text)` calls `_load()` and returns `np.concatenate([np.asarray(c.audio_float_array, np.float32) for c in self._voice.synthesize(text)])`, or a 0-length float32 array when there are no chunks. This is the piper-tts >= 1.3 API. If the installed version differs, only this class changes.
- `default_synthesizer() -> PiperSynthesizer | None`: `try: import piper` (noqa), `except ImportError: return None`, then `return PiperSynthesizer()`.
- `voice_track(lines, synthesizer, duration) -> tuple[np.ndarray, list[tuple[float, float]]]`. `lines` is `[(start, text), ...]` as returned by `script.write_script`. `sr = int(synthesizer.sample_rate)`. The track is `np.zeros(round(duration * sr), np.float32)`. For each line in order: `pos = max(round(start * sr), prev_end)`. If `pos >= len(track)`, skip the line without calling synthesize. Otherwise `audio = np.asarray(synthesizer.synthesize(text), np.float32).ravel()`. Any exception from `sample_rate` or `synthesize` is re-raised as `SynthesisError(f'text-to-speech failed: {exc}')`. Then `end = min(pos + len(audio), len(track))`, `track[pos:end] = audio[:end - pos]`, and `prev_end = end`. If `end > pos`, append `(pos / sr, end / sr)` to spoken. It returns `(np.clip(track, -1, 1), spoken)`. A line is never cut short to make room for the next one. Instead the next line is **delayed** so speech never overlaps, and audio past the clip end is dropped.
- `duck_intervals(spoken, duration) -> list[tuple[float, float]]`: each interval is padded by DUCK_PAD on both sides, clamped to `[0, duration]`, sorted, and merged where intervals overlap or touch.
- `mix_filter(duck) -> str`: the exact ffmpeg filter graph (gain = `10 ** (-DUCK_DB / 20)` formatted `:.6f`, which gives `0.251189`. Times are formatted `:.3f`):
  `[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=volume=0.251189:enable='between(t,1.850,3.007)+between(t,5.850,7.293)'[bg];[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[vo];[bg][vo]amix=inputs=2:duration=first:normalize=0[a]`
  With `duck == []`, the `,volume=...` part is omitted and nothing else changes.
- `_write_wav(samples, sr, path)`: stdlib `wave`, mono, 16-bit PCM, `np.round(samples * 32767).astype('<i2')`.
- `make_voiceover(lines, synthesizer, targets) -> list[Path]`. `targets` is `[(clip, dest), ...]` and must be non-empty. It calls `duration = media.probe_duration(targets[0][0])`, builds `voice_track` **once**, writes the WAV into a `tempfile.TemporaryDirectory()`, and calls `media.mix_audio(clip, wav, mix_filter(duck_intervals(spoken, duration)), dest)` for every target. It returns the dest paths. It only reads the clips.

### 3. `sportscut/media.py` (append one function, no other changes)
```python
def mix_audio(path, voice, audio_filter: str, dest) -> Path:
    """Copy the video of `path` and replace its audio with `audio_filter` applied to [0:a] and [1:a] (voice)."""
```
It raises `MediaError(f'media file not found: {x}')` when `path` or `voice` is not a file. Args, exactly: `[find_tool('ffmpeg'), '-v', 'error', '-nostdin', '-y', '-i', str(path), '-i', str(voice), '-filter_complex', audio_filter, '-map', '0:v:0', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '128k', '-movflags', '+faststart', str(dest)]` through `subprocess.run(args, capture_output=True, check=False)`. A non-zero exit raises `MediaError(f'ffmpeg failed for {path}: {detail}')` (same `_failure_detail` as the rest of media.py). It creates `Path(dest).parent` if missing and returns `Path(dest)`.

### 4. `sportscut/pipeline.py`
- Signature: `run(..., voiceover: bool = False, synthesizer=None)`, with `synthesizer` as the new last parameter.
- Next to the transcriber check, before any work: `if synthesizer is not None and not voiceover: raise PipelineError('synthesizer needs voiceover=True')`.
- `_write_script` additionally **returns** `lines` (the list of `(start, text)`), and its file output is unchanged.
- In the `if voiceover:` loop, after `_write_script` and only when `synthesizer is not None`: `stem = Path(entry['file']).stem`, targets are `[(out/entry['file'], out/f'{stem}.vo.mp4')]` plus `(out/entry['vertical_file'], out/'vertical'/f'{stem}.vo.mp4')` when `'vertical_file' in entry`. Call `voiceover.make_voiceover(lines, synthesizer, targets)`. `SynthesisError` becomes `PipelineError(f"{entry['file']}: {exc}")`. Then set `entry['voiceover_file'] = f'{stem}.vo.mp4'` and, for vertical, `entry['vertical_voiceover_file'] = f'vertical/{stem}.vo.mp4'`. The key order is `..., vertical_file?, script_file, voiceover_file, vertical_voiceover_file?`.
- With `synthesizer=None` the behaviour is byte-for-byte T-026.

### 5. `sportscut/cli.py`
- `from sportscut.commentary import voiceover`, plus `VO_NOTICE = "sportscut: notice: voice-over needs the [tts] extra: pip install 'sportscut[tts]'; only the commentary scripts are written"`.
- Change the `--voiceover` help to: `also write OUT/clip_NN.script.json and a Vietnamese voice-over copy OUT/clip_NN.vo.mp4 (and vertical/clip_NN.vo.mp4 with --vertical); audio needs the [tts] extra`.
- `download-models` gains `--tts` (store_true, help `download the Vietnamese Piper voice used by cut --voiceover instead`). With `--tts`: `path = voiceover.download_voice()`, print `downloaded Piper voice vi_VN-vais1000-medium to {path}`, return 0. Any exception prints `sportscut download-models: error: {exc}` to stderr and returns 1. Without `--tts`, the existing faster-whisper path stays byte-identical.
- `cut`: `synthesizer = None`. If `args.voiceover`: `synthesizer = voiceover.default_synthesizer()`, and when that is None, `print(VO_NOTICE, file=sys.stderr)`. Pass `synthesizer=synthesizer` to `run`. Without `--voiceover`, `default_synthesizer` is never called. After each entry's `script_file` line, print `out/voiceover_file` and then `out/vertical_voiceover_file` when present.

### 6. Docs
- README: insert a new subsection `### Lồng tiếng bình luận (--voiceover)` right after the `### Kịch bản bình luận có mốc thời gian ...` subsection, before `## Theo dõi cầu thủ: đo độ chính xác (eval-player)`. Write it in Vietnamese and include `pip install 'sportscut[tts]'`, `sportscut download-models --tts`, `sportscut cut match.mp4 --out out --voiceover --vertical`, `clip_NN.vo.mp4`, `vertical/clip_NN.vo.mp4`, `12 dB`, Piper offline on CPU, the voice cached in `~/.cache/sportscut/piper` and never committed, original clips unchanged, and a note that piper-tts is GPL-3.0 and installed by the user as an optional extra. It must contain no ```json block. The only deleted README text is the T-026 sentence `Âm thanh lồng tiếng sẽ có ở task sau.` (it spans 2 lines). It is replaced by `Âm thanh lồng tiếng: xem mục kế tiếp.` Everything else is insert-only, and the eval-crop section stays last and byte-identical.
- Append `## Updated by T-027` to the T-026, T-004 and T-022 design specs (see decisions).

## Files
Create: `sportscut/commentary/voiceover.py`, `tests/test_voiceover.py` (Developer), `tests/test_voiceover_piper_smoke.py` (Developer), `tests/test_t027_acceptance.py` (Tester).
Change: `pyproject.toml`, `sportscut/media.py` (append only), `sportscut/pipeline.py`, `sportscut/cli.py`, `README.md`, the three spec files above (append only).
Unchanged: `sportscut/commentary/script.py`, `facts.py`, `meta.py`, `llm.py`, `eval_meta.py`, `export.py`, `models.py`, `api.py`, `vertical.py`, `subtitles.py`, `reframe.py`, `sportscut/web/`, `tests/conftest.py`, `tests/fixtures/`, all pre-existing test files, `agent-office/`.

## Steps (test first)
1. Step 0 precondition.
2. Test `voice_track` placement, delay, truncation, skip and errors with a fake synthesizer (sr=1000), then implement `Synthesizer`, `SynthesisError` and `voice_track`.
3. Test `duck_intervals` (pad, clamp, merge) and the exact `mix_filter` strings, then implement them.
4. Test `media.mix_audio`: exact args with subprocess.run monkeypatched, missing input, and an ffmpeg failure. Then append it.
5. Real-ffmpeg test of `make_voiceover` with the tone fake on the synthetic 300 Hz clip (duration, tone at the scripted times, duck >= 8 dB, unchanged elsewhere, original bytes unchanged, one synthesis per line for two targets). Then implement `_write_wav` and `make_voiceover`.
6. Tests for `download_voice` (fetch order, cache reuse, .part cleanup), `PiperSynthesizer` and `default_synthesizer` with a fake `piper` module. Then implement them.
7. Pipeline tests (fake synthesizer, real ffmpeg, burst_video): vo files and manifest keys, the vertical variant, the synthesizer-without-voiceover error, the synthesis error message, and the unchanged T-026 behaviour with synthesizer=None. Then implement the pipeline changes.
8. CLI tests (fake run, monkeypatched default_synthesizer, download-models --tts). Then implement the CLI changes.
9. Add `pyproject` `tts` extra and the Piper smoke test (importorskip; skip when the voice download fails).
10. README subsection, spec appendices, full suite, eval check.

## Verify
```bash
python -m pytest -q
python -m pytest -q tests/test_voiceover.py tests/test_t027_acceptance.py
python -m sportscut eval tests/fixtures/eval --json      # f1 equals main
python -m sportscut eval-meta tests/fixtures/eval_meta --json --script   # unchanged headline
python -c "import sys, sportscut.cli, sportscut.pipeline, sportscut.commentary.voiceover; print('piper' in sys.modules, 'onnxruntime' in sys.modules)"   # False False
# with the extra (manual, reported in the PR):
pip install -e '.[tts]' && sportscut download-models --tts && sportscut cut match.mp4 --out out --voiceover --vertical
```
Size budget: < 600 changed lines outside docs/superpowers, including the Tester file (T-020 precedent).

## Assumptions
- One fixed voice, `vi_VN-vais1000-medium` (Piper, 22.05 kHz, medium quality), with no voice, speed or volume options (YAGNI).
- piper-tts >= 1.3 (`PiperVoice.load`, `synthesize(text)` yields chunks with `audio_float_array`, `config.sample_rate`) runs on CPU. About 30 short lines per 10-clip run takes seconds, well inside the 10-minute budget. The model is loaded once per process.
- ffmpeg >= 4.4 (amix `normalize` option).
- No limiter is applied. The broadcast audio is 12 dB down while speech plays, so clipping is rare. A limiter is out of scope.
- The vertical vo clip reuses the same voice track, because the vertical render copies the original audio unchanged.

## Test plan

- Developer tests (tests/test_voiceover.py):
- Unit tests for voice_track: placement, delay of the next line, truncation at the clip end, skipped lines with no synthesize call, empty lines, clipping, dtype, and the SynthesisError message (AC3).
- duck_intervals pad/clamp/merge cases (AC4).
- Exact mix_filter strings, with and without ducking (AC5).
- media.mix_audio unit tests with subprocess.run monkeypatched: exact args, missing clip, missing voice and ffmpeg failure (AC6). Developer and Tester.
- Real-ffmpeg integration test (skipped without ffmpeg). Build a 10 s clip in tmp_path: `color=c=black:s=160x120:r=10:d=10` plus `sine=frequency=300:sample_rate=44100:duration=10`, aac. Then:
- Run make_voiceover with the 22050 Hz / 2000 Hz tone fake.
- Check duration ±0.1 s, the stream count, 2000 Hz presence (≥30 dB above silence windows) and the 300 Hz duck (≥8 dB) in the spoken windows.
- Check the 300 Hz band is unchanged within 1 dB in [0.5,1.5], [4.0,5.0] and [8.0,9.5], and the source sha256 is unchanged.
The test helper band_rms(samples, 16000, f, t0, t1) zeroes rfft bins outside f±50 Hz and returns the RMS of irfft (AC7).
- make_voiceover with two targets: synthesize is called once per line, and both outputs are written with the right duration (AC8).
- download_voice with XDG_CACHE_HOME=tmp_path and _fetch monkeypatched: fetch order and URLs, cache reuse, and OSError cleanup of .part files (AC9).
- PiperSynthesizer and default_synthesizer with a fake `piper` module via monkeypatch.setitem(sys.modules, ...): lazy loading, load-once, chunk concatenation, sample_rate, and None when piper is missing (AC10).
- Pipeline integration on the burst_video fixture with the tone fake: vo file, duration and manifest key order; the vertical variant with render_vertical monkeypatched to shutil.copy the clip; synthesize call count; the synthesizer-without-voiceover error before any file is written; the 'clip_01.mp4: text-to-speech failed: boom' error; and synthesizer=None keeping T-026 behaviour (AC11, AC12).
- CLI tests with cli.run and voiceover.default_synthesizer monkeypatched:
- synthesizer forwarding, the exact VO_NOTICE on stderr with exit 0, default_synthesizer not called without the flag, the 5-line stdout order, and exit 1 on PipelineError (AC13).
- download-models --tts success and failure, and --help listing --tts (AC14).
- Fresh-interpreter subprocess test: piper and onnxruntime are not in sys.modules after importing cli, pipeline and voiceover. Plus a source scan for 'subprocess' and the importers list (AC2). pyproject tomllib check and a git ls-files check (AC1).
- tests/test_voiceover_piper_smoke.py: pytest.importorskip('piper'); skip on OSError from download_voice; real synthesis shape, duration and loudness; < 5 s for 3 template lines after warm-up; real make_voiceover duration (AC15).
- Tester acceptance tests/test_t027_acceptance.py, written from the ACs independently of the Developer's tests:
- Re-measure AC7 with its own signal generator and its own band measurement.
- Check the README and spec appendices (AC16).
- Check eval f1 and the eval-meta outputs equal main, and run the git-scope checks gated to office/T-027 branches (AC17).
- Confirm each new test fails when the duck gain is set to 1.0 or when the voice is placed 1 s late.
