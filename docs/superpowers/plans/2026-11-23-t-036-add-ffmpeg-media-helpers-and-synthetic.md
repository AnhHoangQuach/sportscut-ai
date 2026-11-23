# Plan T-036: Add ffmpeg media helpers and synthetic video fixtures

Design: `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`.

## Implementation plan

# T-036: ffmpeg media helpers and synthetic video fixtures

## Context

Request R-001 (PO: `POST /highlights` takes a video and returns highlight segments and cut files). T-001 was too big, so it was split. T-035 (merged on `main`, commit 30227a6) delivered `pyproject.toml` (numpy runtime dep, pytest via `dev` extra, `testpaths=['tests']`, `pythonpath=['.']`), `sportscut/__init__.py` (`__version__ = '0.1.0'`), `sportscut/cli.py`, `sportscut/models.py` (`Segment`), `tests/test_cli.py` and `tests/test_models.py`. This task, T-036, owns all ffmpeg media work. Its pipeline input is described in `docs/05-sportscut.md`: ffmpeg extracts mono 16 kHz audio, numpy processes it, and shot boundaries come from colour changes. Later detection, export and API tasks build on the helpers and the synthetic clip added here. Do not add detection, export or HTTP code.

`.gitignore` already ignores `*.mp4`, `*.mkv`, `*.wav`, `.venv/` and `data/`; do not change it. Do not touch `pyproject.toml`, `agent-office/` (protected) or `.gitattributes`. The orchestrator writes this task's design/plan/INDEX/DECISIONS records from this spec. Do not hand-write or edit anything under `docs/superpowers/`.

## Files

- create `sportscut/media.py`
- create `tests/conftest.py`
- create `tests/test_media.py`
- create `tests/test_fixtures.py`

Target: about 300 changed lines, hard limit 400. Do not create `tests/__init__.py`.

## Interfaces: `sportscut/media.py`

```python
import shutil, subprocess
from pathlib import Path
import numpy as np

SAMPLE_RATE = 16_000

class MediaError(RuntimeError):
    '''Any ffmpeg/ffprobe discovery, probing or decoding failure.'''

def find_tool(name: str) -> str: ...
def probe_duration(path: str | Path) -> float: ...
def extract_audio(path: str | Path) -> np.ndarray: ...
```

### `find_tool(name)`
Return `shutil.which(name)`. Look up PATH on every call; never cache it, because tests change PATH. If the result is `None`, raise `MediaError(f'{name} not found on PATH; install ffmpeg')`. With `name='ffprobe'` the message is exactly `ffprobe not found on PATH; install ffmpeg`.

### Common checks (in this order, for both `probe_duration` and `extract_audio`)
1. `p = Path(path)`. If `not p.is_file()`, raise `MediaError(f'media file not found: {path}')`. This check comes first, so it works without ffmpeg.
2. Resolve the tool with `find_tool('ffprobe')` or `find_tool('ffmpeg')`.
3. Run `subprocess.run(args, capture_output=True, check=False)`. Do not use `shell=True`. Always pass the input with `-i` so a file name that starts with `-` is never read as an option.
4. Failure detail = the last non-empty line of stderr, decoded as UTF-8 with `errors='replace'` and stripped. If stderr is empty, use `f'exit code {returncode}'`.

### `probe_duration(path)`
Args: `[ffprobe, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', '-i', str(p)]`, run with `text=True`.
- Non-zero exit: raise `MediaError(f'ffprobe failed for {path}: {detail}')`.
- If `float(stdout.strip())` raises `ValueError` (for example `N/A` or empty output), raise `MediaError(f'ffprobe returned no duration for {path}')`.
- Return a native `float` in seconds.

### `extract_audio(path)`
Args: `[ffmpeg, '-v', 'error', '-nostdin', '-i', str(p), '-vn', '-ac', '1', '-ar', str(SAMPLE_RATE), '-f', 'f32le', 'pipe:1']`, run in bytes mode.
- Non-zero exit (non-media input, or no audio stream): raise `MediaError(f'ffmpeg failed for {path}: {detail}')`.
- Return `np.frombuffer(result.stdout, dtype='<f4').astype(np.float32)`. The result is 1-D, native float32, a writable copy, mono, at 16 kHz.

Add nothing else: no timeouts, no caching, no extra parameters, no stream selection.

## Interfaces: `tests/conftest.py`

```python
@pytest.fixture(scope='session')
def require_ffmpeg() -> None:
    if shutil.which('ffmpeg') is None or shutil.which('ffprobe') is None:
        pytest.skip('ffmpeg and ffprobe are required on PATH')

@pytest.fixture(scope='session')
def synthetic_video(require_ffmpeg: None, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp('media') / 'synthetic.mp4'
    subprocess.run(ARGS, check=True, capture_output=True)
    return path
```

The module docstring documents the synthetic clip layout. This layout is the contract that later detector tests rely on:
- duration 6.0 s, 160x120 video at 10 fps, encoded `mpeg4` + `aac` (built-in encoders, no libx264 needed);
- video: solid black for 0-3 s, solid white for 3-6 s, so there is exactly one scene change at 3.0 s;
- audio: stereo, 44.1 kHz, seeded white noise at amplitude 0.02, raised x20 between 2.0 and 3.0 s (the crowd-noise burst).

`ARGS`. Pass this exact argument list; no shell is involved. The single quotes inside the filter are ffmpeg filter-graph quoting that protects the commas:
```
['ffmpeg', '-v', 'error', '-nostdin', '-y',
 '-f', 'lavfi', '-i', 'color=c=black:s=160x120:r=10:d=3',
 '-f', 'lavfi', '-i', 'color=c=white:s=160x120:r=10:d=3',
 '-f', 'lavfi', '-i', 'anoisesrc=d=6:c=white:r=44100:a=0.02:seed=42',
 '-filter_complex', "[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a]volume=volume=20:enable='between(t,2,3)',aformat=channel_layouts=stereo[a]",
 '-map', '[v]', '-map', '[a]',
 '-c:v', 'mpeg4', '-q:v', '5', '-pix_fmt', 'yuv420p',
 '-c:a', 'aac', '-b:a', '96k', '-t', '6', str(path)]
```
If the local ffmpeg rejects one option (for example `seed`), make the smallest change that keeps the documented layout, and report it in your summary. Generation failures must raise `CalledProcessError` (a test error); they must never become a skip. The clip always lives under pytest's temp directory and never in the repository.

## Tests: `tests/test_media.py`

These run everywhere, with or without ffmpeg:
- `test_find_tool_missing_raises_exact_message[ffmpeg|ffprobe]`: `monkeypatch.setenv('PATH', str(tmp_path))`; `pytest.raises(MediaError)`; `str(exc) == f'{name} not found on PATH; install ffmpeg'`.
- `test_probe_duration_without_ffprobe` / `test_extract_audio_without_ffmpeg`: write an existing empty `tmp_path/'clip.mp4'`, set PATH to the empty `tmp_path`, expect the exact `ffprobe ...` / `ffmpeg ...` not-found message.
- `test_missing_file_raises[probe_duration|extract_audio]`: `tmp_path/'missing.mp4'`; message is exactly `media file not found: {path}`.
- `test_probe_duration_without_duration_value`: create an existing file; monkeypatch `sportscut.media.find_tool` to return `'ffprobe'` and `sportscut.media.subprocess.run` to return `subprocess.CompletedProcess(args=[], returncode=0, stdout='N/A\n', stderr='')`; message is exactly `ffprobe returned no duration for {path}`.

These need ffmpeg (they use the `require_ffmpeg` or `synthetic_video` fixture):
- `test_find_tool_returns_path_from_path`: `find_tool('ffmpeg') == shutil.which('ffmpeg')`.
- `test_probe_duration_rejects_non_media` / `test_extract_audio_rejects_non_media`: `tmp_path/'bad.mp4'` contains the text `not a video`; `pytest.raises(MediaError, match='^' + re.escape(f'ffprobe failed for {path}: ') + '.+')`, and the same with `ffmpeg failed for`.
- `test_probe_duration_of_synthetic_video`: `type(d) is float` and `d == pytest.approx(6.0, abs=0.15)`.
- `test_extract_audio_is_mono_16k_float32`: `a.dtype == np.float32`, `a.ndim == 1`, `abs(a.size - 6 * SAMPLE_RATE) <= 1600`. The source is stereo 44.1 kHz, so this size proves downmix and resampling. Also `np.abs(a).max() <= 1.0` and `a.flags.writeable`.

## Tests: `tests/test_fixtures.py` (all use `synthetic_video`)

The file includes the helper `_gray_mean(video, t) -> float`. It runs `['ffmpeg', '-v', 'error', '-nostdin', '-ss', str(t), '-i', str(video), '-frames:v', '1', '-vf', 'scale=8:6,format=gray', '-f', 'rawvideo', 'pipe:1']` with `check=True`, asserts the output is 48 bytes, and returns `np.frombuffer(out, np.uint8).mean()`. The helper `_rms(a, s, e)` computes the RMS of `a[int(s*SAMPLE_RATE):int(e*SAMPLE_RATE)]`.
- `test_synthetic_video_is_temporary_and_six_seconds`: the path exists, it is not under the repository root (`Path(__file__).resolve().parents[1]`), and `probe_duration` returns approximately 6.0 (abs 0.15).
- `test_synthetic_video_streams`: `ffprobe -v error -show_entries stream=codec_type,width,height,channels,sample_rate -of json -i <video>` shows exactly one video stream at 160x120 and one audio stream with `channels == 2` and `sample_rate == '44100'`.
- `test_synthetic_video_has_audio_burst`: with `a = extract_audio(video)`, check `_rms(a, 2.2, 2.8) >= 5 * _rms(a, 0.2, 1.8)` and `>= 5 * _rms(a, 3.5, 5.5)`. The windows avoid AAC edge smearing.
- `test_synthetic_video_has_one_scene_change_at_3s`: `_gray_mean` at 0.5, 1.5 and 2.5 is `< 64`; at 3.5, 4.5 and 5.5 it is `> 192`.

## Steps (test-first; quote each red failure line in your final report)

1. Baseline: run `.venv/bin/python -m pytest -q` and confirm it is green. If `.venv` is missing, create it with `python3 -m venv .venv && .venv/bin/python -m pip install --no-build-isolation --no-index -e '.[dev]'`.
2. Write `tests/conftest.py` with only `require_ffmpeg`. Write the `find_tool` tests in `tests/test_media.py`. Run `.venv/bin/python -m pytest -q tests/test_media.py`. Expected red: `ModuleNotFoundError: No module named 'sportscut.media'`. Implement `MediaError`, `SAMPLE_RATE` and `find_tool`. Re-run: green.
3. Add the `probe_duration` tests that do not need the clip (no-tool, missing file, no duration, non-media) to the import line and the file. Expected red: `ImportError: cannot import name 'probe_duration'`. Implement the common checks and `probe_duration`. Re-run: green.
4. Write `tests/test_fixtures.py` with the duration, streams and scene-change tests, and add `test_probe_duration_of_synthetic_video`. Expected red: `fixture 'synthetic_video' not found`. Implement the `synthetic_video` fixture. Re-run: green.
5. Add the `extract_audio` tests (no-tool, missing file, non-media, mono/16k/float32, burst). Expected red: `ImportError: cannot import name 'extract_audio'`. Implement `extract_audio`. Re-run: green.
6. Run the verification commands below and quote their summary lines.

## Verification commands

- `.venv/bin/python -m pytest -q`: 0 failed, 0 errors, 0 skipped (ffmpeg is installed on the dev machine).
- `PATH=/nonexistent .venv/bin/python -m pytest -q -rs`: 0 failed, 0 errors; every skip reason is `ffmpeg and ffprobe are required on PATH`; the always-run tests above pass.
- `git ls-files '*.mp4' '*.mkv' '*.wav'` prints nothing.
- `git status --porcelain --untracked-files=all` lists only the four files above (plus the orchestrator's `docs/superpowers/` records).
- `find . -path ./.venv -prune -o \( -name '*.mp4' -o -name '*.wav' -o -name '*.mkv' \) -print` prints nothing after the suite.
- `git diff --stat main` total is under 400 changed lines; nothing under `agent-office/` is listed.

## Assumptions

- The dev machine has ffmpeg/ffprobe (Homebrew); CI or other machines may not, so ffmpeg-dependent tests must skip cleanly.
- The worktree-local `.venv` comes from the existing setup command (T-035 decision).

## Test plan

- unit (always runs) tests/test_media.py::test_find_tool_missing_raises_exact_message[ffmpeg|ffprobe]: monkeypatch PATH to an empty tmp_path; check the exact message
- unit (always runs) tests/test_media.py::test_probe_duration_without_ffprobe and ::test_extract_audio_without_ffmpeg: existing empty file + empty PATH; check the exact not-found message
- unit (always runs) tests/test_media.py::test_missing_file_raises[probe_duration|extract_audio]: message exactly `media file not found: <path>`
- unit (always runs) tests/test_media.py::test_probe_duration_without_duration_value: monkeypatch sportscut.media.find_tool and sportscut.media.subprocess.run to return stdout 'N/A\n'; check the exact message
- integration (require_ffmpeg) tests/test_media.py::test_find_tool_returns_path_from_path: equals shutil.which('ffmpeg')
- integration (require_ffmpeg) tests/test_media.py::test_probe_duration_rejects_non_media and ::test_extract_audio_rejects_non_media: text file -> MediaError matching '^ffprobe failed for <path>: .+' / '^ffmpeg failed for <path>: .+'
- integration (synthetic_video) tests/test_media.py::test_probe_duration_of_synthetic_video: float, approx 6.0 abs 0.15
- integration (synthetic_video) tests/test_media.py::test_extract_audio_is_mono_16k_float32: float32, ndim 1, |size-96000| <= 1600, max |x| <= 1, writable
- integration (synthetic_video) tests/test_fixtures.py::test_synthetic_video_is_temporary_and_six_seconds: exists, not under repo root, duration approx 6.0
- integration (synthetic_video) tests/test_fixtures.py::test_synthetic_video_streams: ffprobe JSON shows one 160x120 video stream and one 2-channel 44100 Hz audio stream
- integration (synthetic_video) tests/test_fixtures.py::test_synthetic_video_has_audio_burst: RMS(2.2-2.8) >= 5x RMS(0.2-1.8) and >= 5x RMS(3.5-5.5)
- integration (synthetic_video) tests/test_fixtures.py::test_synthetic_video_has_one_scene_change_at_3s: gray mean < 64 at 0.5/1.5/2.5 s and > 192 at 3.5/4.5/5.5 s
- fixture tests/conftest.py: session-scoped `require_ffmpeg` (skips with 'ffmpeg and ffprobe are required on PATH') and session-scoped `synthetic_video` (generated once in tmp_path_factory via lavfi color/anoisesrc; nothing committed)
- suite run with ffmpeg: `.venv/bin/python -m pytest -q` -> 0 failed/0 errors/0 skipped
- suite run without ffmpeg: `PATH=/nonexistent .venv/bin/python -m pytest -q -rs` -> 0 failed/0 errors, only the ffmpeg skip reason
- hygiene: `git ls-files '*.mp4' '*.mkv' '*.wav'` empty; `find` finds no media outside .venv; `git diff --stat main` < 400 lines
