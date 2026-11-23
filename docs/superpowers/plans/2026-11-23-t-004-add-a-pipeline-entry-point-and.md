# Plan T-004: Add a pipeline entry point and the `sportscut cut` CLI

Design: `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`.

## Implementation plan

# T-004: Pipeline entry point and the `sportscut cut` CLI

## Context
The PO request (R-001) is an API `POST /highlights` that takes a video and returns the highlight segments plus the cut files. The pieces already exist on main:
- `sportscut.detect.find_highlights(video, top=10, min_len=10, max_len=30) -> list[Segment]` (T-002). It validates options first and raises `ValueError`, then probes and decodes through `sportscut.media`, which raises `MediaError`.
- `sportscut.export.export_clips(video, segments, out_dir) -> list[Path]` (T-003). It writes `clip_NN.mp4` files and `<out_dir>/highlights.json` (`MANIFEST_NAME`), a JSON list of `Segment.to_dict()` plus `file`.
- `sportscut.media` (T-036/T-003) is the only module that runs ffmpeg/ffprobe. It has `find_tool`, `probe_duration`, `extract_audio`, `cut_clip` and `MediaError(RuntimeError)`.
- `sportscut/cli.py` has only `detect`. It currently runs `find_highlights` for any subcommand that is not None.

This task adds one function that the CLI and the later API both call. It also adds the `cut` subcommand and a `PipelineError` that means "the caller's input is bad" (the API maps it to HTTP 400). Any other exception means a server or environment problem (the API maps it to 500).

## Design

### `sportscut/media.py` (add two functions; do not change existing ones)
```python
def require_ffmpeg() -> None:
    """Raise MediaError unless both ffmpeg and ffprobe are on PATH."""
    find_tool("ffmpeg")
    find_tool("ffprobe")

def has_audio(path: str | Path) -> bool:
    """True if the file has at least one audio stream."""
```
`has_audio` follows the same pattern as `probe_duration`:
1. If `Path(path).is_file()` is false, raise `MediaError(f"media file not found: {path}")`.
2. Get `ffprobe = find_tool("ffprobe")`.
3. Run `[ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", "-i", str(p)]` with `capture_output=True, check=False, text=True`.
4. A non-zero return code raises `MediaError(f"ffprobe failed for {path}: {_failure_detail(result.stderr, result.returncode)}")`.
5. Otherwise return `bool(result.stdout.strip())`.

### `sportscut/pipeline.py` (new)
```python
import json
from pathlib import Path

from sportscut.detect import find_highlights
from sportscut.export import MANIFEST_NAME, export_clips
from sportscut.media import MediaError, has_audio, require_ffmpeg


class PipelineError(Exception):
    """The input video or the options are invalid (the API maps this to HTTP 400)."""


def run(video: str | Path, out_dir: str | Path, top: int = 10,
        min_len: float = 10, max_len: float = 30) -> list[dict]:
    require_ffmpeg()                       # MediaError propagates (environment, not input)
    try:
        if not has_audio(video):
            raise PipelineError(f"no audio stream in {video}")
        segments = find_highlights(video, top=top, min_len=min_len, max_len=max_len)
    except (MediaError, ValueError) as exc:
        raise PipelineError(str(exc)) from exc
    export_clips(video, segments, out_dir)  # MediaError propagates (encoder/disk, not input)
    return json.loads((Path(out_dir) / MANIFEST_NAME).read_text(encoding="utf-8"))
```
Rules:
- `PipelineError` is a direct subclass of `Exception`. It is not a `MediaError` or a `ValueError`, so the `except` above never re-wraps it.
- The message of a wrapped error is exactly `str(exc)` of the original. Examples: `media file not found: <path>`, `ffprobe failed for <path>: <last stderr line>`, `min_len must be <= max_len`.
- A missing ffmpeg/ffprobe is not a PipelineError. `require_ffmpeg` raises `MediaError` (`ffmpeg not found on PATH; install ffmpeg`) before any input is touched.
- Export failures (for example an ffmpeg without libx264) stay `MediaError`.
- When a PipelineError is raised, export never ran, so no clip or manifest is written.
- The return value equals the manifest file contents: a list of dicts with keys `start, end, score, reason, file`, sorted by start.
- `pipeline.py` must not import `subprocess`. Media access stays in `sportscut.media`.

### `sportscut/cli.py`
Add a `cut` subparser next to `detect`:
```
sportscut cut VIDEO --out DIR [--top N] [--min-len S] [--max-len S]
```
- `--out` is required (`dest="out"`).
- `--top` is `type=int, default=10`. `--min-len` is `type=float, default=10`. `--max-len` is `type=float, default=30`. These are the same defaults as `detect`.
- Dispatch on `args.command`. The `detect` path stays byte-for-byte the same in behaviour. Its error handling is still `(MediaError, ValueError)`.
- The `cut` path calls `pipeline.run(args.video, args.out, top=..., min_len=..., max_len=...)`.
  - On success it prints one line per manifest entry: `str(Path(args.out) / entry["file"])`, in manifest order. It prints nothing else and returns 0. With 0 segments it prints nothing and returns 0, and the `[]` manifest is still written.
  - On `PipelineError` or `MediaError` it prints `sportscut: error: <msg>` on stderr, prints nothing on stdout, and returns 1. No traceback is shown.
- The no-argument help behaviour from T-035 is kept. The help text now lists both `detect` and `cut`.

## Files to touch
- `sportscut/pipeline.py` (new)
- `sportscut/media.py` (add `require_ffmpeg`, `has_audio`)
- `sportscut/cli.py` (add the `cut` subcommand and dispatch by command)
- `tests/test_pipeline.py` (new)
- `tests/test_media.py` (tests for the two new helpers)
- `tests/test_cli.py` (tests for `cut`, and help lists `cut`)
- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md` (append an "Updated by T-004" note)

Do not change `tests/conftest.py`. The video-only fixture is local to the test modules that need it.

## Steps (TDD: write each test, see it fail for the right reason, then write the code)
1. **media helpers.** In `tests/test_media.py`, add a local helper `_video_only(tmp_path)`. It runs `ffmpeg -v error -nostdin -y -f lavfi -i color=c=black:s=160x120:r=5:d=3 -c:v mpeg4 -q:v 5 -pix_fmt yuv420p <tmp>/video_only.mp4` with `check=True`. Write these tests:
   - `test_has_audio_true_for_synthetic_video`
   - `test_has_audio_false_for_video_only` (needs `require_ffmpeg`)
   - `test_has_audio_missing_file_raises` (exact `media file not found: <path>`)
   - `test_has_audio_rejects_non_media` (match `^ffprobe failed for <path>: .+`)
   - `test_require_ffmpeg_missing_tool`: with PATH set to an empty tmp dir it raises MediaError `ffmpeg not found on PATH; install ffmpeg`
   - `test_require_ffmpeg_ok`: with tools present it returns None

   Run `python -m pytest -q tests/test_media.py` and see ImportError or failures. Implement both helpers. Run again and see them pass.
2. **pipeline success.** In `tests/test_pipeline.py`, write `test_run_returns_manifest_entries(burst_video, tmp_path)`. It calls `run(burst_video, tmp_path/"out")` and checks:
   - the result is a list of 3 dicts,
   - each has keys `{start, end, score, reason, file}`,
   - the files are `clip_01.mp4..clip_03.mp4` and exist,
   - the result `== json.loads(highlights.json)`,
   - each clip's `probe_duration` is approximately 12 s (abs 0.5).

   Also write `test_run_passes_options(burst_video, tmp_path)`: with `top=1, min_len=4, max_len=6` there is 1 entry and `end - start ≈ 6` (abs 0.01). Implement `run`.
3. **pipeline errors.** Write these tests in `tests/test_pipeline.py`:
   - `test_run_non_video_raises_pipeline_error`: a text file `bad.mp4` raises PipelineError whose message matches `^ffprobe failed for <path>: .+`, and `out/highlights.json` does not exist.
   - `test_run_no_audio_raises_pipeline_error`: a local video-only fixture raises with the message exactly `no audio stream in <path>`, and there is no manifest.
   - `test_run_missing_file_raises_pipeline_error`: the message is exactly `media file not found: <path>`.
   - `test_run_invalid_options_raises_pipeline_error(burst_video)`: `min_len=20, max_len=10` gives the message `min_len must be <= max_len`.
   - `test_run_without_ffmpeg_raises_media_error`: with PATH set to an empty tmp dir, it raises `MediaError`, and the error `isinstance` check against PipelineError is false.
   - `test_pipeline_error_is_plain_exception`: `issubclass(PipelineError, Exception)`, but it is not a subclass of MediaError or ValueError.
   - `test_pipeline_module_does_not_import_subprocess`: an AST check like the one in `tests/test_export.py`.

   Make them pass.
4. **CLI cut.** Write these tests in `tests/test_cli.py`:
   - `test_cut_end_to_end(burst_video, tmp_path, capsys)`: `main(["cut", str(burst_video), "--out", str(out)]) == 0`. Stdout lines are `[str(out/"clip_01.mp4"), str(out/"clip_02.mp4"), str(out/"clip_03.mp4")]`, stderr is `""`, every listed file exists, and `highlights.json` has 3 entries whose `file` values match.
   - `test_cut_passes_options(burst_video, tmp_path, capsys)`: `--top 1 --min-len 4 --max-len 6` gives exactly 1 stdout line and a manifest entry with length ≈ 6.
   - `test_cut_non_video_exits_nonzero(tmp_path)`: run `[sys.executable, "-m", "sportscut", "cut", str(bad), "--out", str(out)]` as a subprocess with `cwd` = repo root, on a text file. Check: returncode == 1, stdout == "", stderr starts with `sportscut: error: ffprobe failed for <bad>: `, `"Traceback" not in stderr`, and `not (out/"highlights.json").exists()`. Use the `require_ffmpeg` fixture.
   - `test_cut_requires_out(capsys)`: `main(["cut", "x.mp4"])` raises SystemExit with code 2 (argparse).
   - Extend `test_no_args_prints_help_and_returns_zero` with `assert "cut" in captured.out`.

   Implement the subcommand and the dispatch. All existing `detect` tests must still pass unchanged.
5. **Docs.** Append this to the end of the T-036 design spec: `Updated by T-004: sportscut.media also exposes require_ffmpeg() (both tools on PATH, else MediaError) and has_audio(path) -> bool (ffprobe audio-stream check; ffprobe failures raise MediaError).`
6. **Verify.** Run `python -m pytest -q` and confirm everything passes (quote the summary line). Then run a manual smoke test on any local video: `sportscut cut <video> --out /tmp/sc_out --top 3`. It prints the clip paths and `/tmp/sc_out/highlights.json` exists. Finally, `echo hi > /tmp/bad.mp4; sportscut cut /tmp/bad.mp4 --out /tmp/sc_bad; echo $?` prints `sportscut: error: ffprobe failed for /tmp/bad.mp4: ...` and `1`.

## Assumptions
- The task text says `require_ffmpeg`, but on main that name exists only as a pytest fixture. This task adds a product function with that name to `sportscut.media`.
- Invalid options (`ValueError` from `find_highlights`) count as invalid input, so they become a PipelineError. The API can then map one exception type to 400.
- The audio check runs before `find_highlights`. If a no-audio video also has invalid options, the user sees the no-audio error. This is acceptable.
- No eval exists yet and detection logic is unchanged, so F1 cannot move. No eval command is needed.
- The end-to-end tests re-encode with libx264, which the T-003 export tests already require.

## Test plan

- tests/test_media.py::test_has_audio_true_for_synthetic_video: has_audio(synthetic_video) is True
- tests/test_media.py::test_has_audio_false_for_video_only: a local video-only mp4 (lavfi color, mpeg4, no audio) gives False
- tests/test_media.py::test_has_audio_missing_file_raises: exact `media file not found: <path>`
- tests/test_media.py::test_has_audio_rejects_non_media: a text file raises MediaError matching `^ffprobe failed for <path>: .+`
- tests/test_media.py::test_require_ffmpeg_missing_tool: PATH set to an empty tmp dir raises MediaError `ffmpeg not found on PATH; install ffmpeg`
- tests/test_media.py::test_require_ffmpeg_ok: returns None when ffmpeg/ffprobe are present
- tests/test_pipeline.py::test_run_returns_manifest_entries (burst_video): 3 entries, keys {start,end,score,reason,file}, equal to the manifest file, files exist, durations ≈ 12 s
- tests/test_pipeline.py::test_run_passes_options (burst_video): top=1, min_len=4, max_len=6 gives 1 entry of length ≈ 6
- tests/test_pipeline.py::test_run_non_video_raises_pipeline_error: ffprobe failure message, no manifest
- tests/test_pipeline.py::test_run_no_audio_raises_pipeline_error: exact `no audio stream in <path>`, no manifest
- tests/test_pipeline.py::test_run_missing_file_raises_pipeline_error: exact `media file not found: <path>`
- tests/test_pipeline.py::test_run_invalid_options_raises_pipeline_error (burst_video): `min_len must be <= max_len`
- tests/test_pipeline.py::test_run_without_ffmpeg_raises_media_error: empty PATH gives MediaError, not PipelineError
- tests/test_pipeline.py::test_pipeline_error_is_plain_exception: class hierarchy check
- tests/test_pipeline.py::test_pipeline_module_does_not_import_subprocess: AST import check
- tests/test_cli.py::test_cut_end_to_end (burst_video): exit 0, stdout lists 3 clip paths, empty stderr, manifest has 3 entries
- tests/test_cli.py::test_cut_passes_options (burst_video): --top 1 --min-len 4 --max-len 6 gives 1 line, length ≈ 6
- tests/test_cli.py::test_cut_non_video_exits_nonzero: subprocess `python -m sportscut cut bad.mp4 --out dir` gives returncode 1, a readable `sportscut: error: ffprobe failed for ...`, no Traceback, no manifest
- tests/test_cli.py::test_cut_requires_out: missing --out gives SystemExit 2
- tests/test_cli.py::test_no_args_prints_help_and_returns_zero: also asserts 'cut' in the help output
- Fixtures: the existing session fixtures burst_video, synthetic_video and require_ffmpeg from tests/conftest.py. A video-only mp4 is generated per test module in tmp_path; conftest.py is not changed.
