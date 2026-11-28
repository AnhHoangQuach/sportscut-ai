# Plan T-056: Decode the audio and the top-band frames once per pipeline run

Design: `docs/superpowers/specs/2026-11-28-t-056-decode-the-audio-and-the-top-design.md`.

## Implementation plan

# T-056: Decode the audio and the top-band frames once per pipeline run

Request: R-007 (the PO says goal highlights are still wrong on their real phone footage). This task does not change accuracy. It is a performance task, so that later accuracy fixes still fit the 90-minute budget (under 10 minutes on a laptop CPU).

## Context (current code on main, 94dbdfe)

`sportscut/pipeline.py::run` calls these in order: `find_highlights` (sportscut/detect.py:59 `extract_audio`), `tag_goals` (sportscut/events/scoreboard.py:265 `extract_audio` and, through `board_changes`, :126 `sample_top_band`), `tag_incidents` (sportscut/events/incidents.py:110 `scoreboard.board_reverts`, which calls `sample_top_band` at :154, then :135 `extract_audio`), and `tag_saves` (sportscut/events/audio_cues.py:228 `scoreboard.board_changes`, which calls `sample_top_band`, then :232 `extract_audio`). `sportscut/evaluate.py:174-177` runs the same chain. So one run decodes the whole source audio up to 4 times and the top band up to 3 times. Each decode is a full ffmpeg pass over the file, and on a 4K/HEVC phone file that pass is the main cost.

`sportscut/media.py`:
- `extract_audio(path)` returns `np.frombuffer(stdout, '<f4').astype(np.float32)`, a writable copy.
- `sample_top_band(path)` returns `np.frombuffer(stdout, np.uint8)[...].reshape(n, 30, 160)`, which is already read-only because it is a view of a bytes object.

No caller writes into either array in place. This was checked with a grep for `[...] =`, `+=`, `out=`, `as_strided` and `setflags` in `sportscut/`. The only `out=` (audio_cues.py:74) writes to a fresh `np.zeros` array.

## Design

All changes to production code are in `sportscut/media.py`. No caller changes.

```python
_audio_cache: tuple[object, np.ndarray] | None = None   # (key, read-only float32 array)
_band_cache: tuple[object, np.ndarray] | None = None    # (key, read-only uint8 (n,30,160) array)

def _cache_key(p: Path) -> tuple[str, int, int]:
    """Identity of a media file's current content: (resolved path, size, mtime_ns)."""
    st = p.stat()
    return (str(p.resolve()), st.st_size, st.st_mtime_ns)
```

New order inside `extract_audio(path)`. `sample_top_band(path)` gets the same change, using `_band_cache`.
1. `p = Path(path)`. If `not p.is_file()`, raise `MediaError(f"media file not found: {path}")`. This is unchanged and is still checked first.
2. `ffmpeg = find_tool("ffmpeg")`. This is unchanged and is still checked before the cache, so the error for a missing ffmpeg does not depend on cache state.
3. `key = _cache_key(p)` and `cached = _audio_cache`. If `cached is not None and cached[0] == key`, return `cached[1]`. This is the same object as before, with no copy.
4. Otherwise run the same ffmpeg command as today, with the same args and kwargs, and raise the same `MediaError` on a non-zero exit. A failure is never cached and leaves the old entry as it was.
5. Build the array exactly as today, then set `array.flags.writeable = False`. Store it with `global _audio_cache; _audio_cache = (key, array)` and return it.

The key is computed before the decode. If the file changes during a decode, the next call sees a new size or mtime and decodes again.

Each function has one entry. Decoding file B replaces file A's entry. The audio and band caches are independent, so a band decode never evicts the audio entry. Writing and reading a single module-global tuple is atomic in CPython, so concurrent API threads can at worst cause one extra decode and can never mix up two files. No lock is added.

No other media function is cached: `has_audio`, `probe_duration`, `probe_size`, `sample_frames`, `sample_window`, `cut_clip` and the rest stay as they are. No public API, CLI option, env var or clear function is added. Tests reset the cache with `monkeypatch.setattr(media, "_audio_cache", None)` and turn it off with `monkeypatch.setattr(media, "_cache_key", lambda p: object())`, because a fresh `object()` never equals the stored key, so every call decodes as on main.

## Behaviour change to an earlier spec

T-036 AC5 says `extract_audio` returns a writable array. From T-056 the array is read-only, and writing to it raises `ValueError: assignment destination is read-only`. `tests/test_media.py::test_extract_audio_is_mono_16k_float32` (line 200) changes `audio.flags.writeable` to `not audio.flags.writeable`. That is the only edit to an existing test. Every other assertion in that test stays.

The T-036 design spec gets one new paragraph, inserted before the closing `Updated by T-004: ...` paragraph, which must stay last because test_t004::test_documentation_acceptance, test_t018 and test_t021 check that. Exact text:

`Updated by T-056: extract_audio(path) and sample_top_band(path) keep a one-entry cache each, keyed by (resolved path, size, mtime_ns), and return read-only arrays (AC5's 'writable' no longer holds); a changed file or a failed decode is never served from the cache.`

It is separated from the paragraphs around it by blank lines. Nothing else in that file changes.

## Files to touch
- `sportscut/media.py`: two cache globals, `_cache_key`, and the changes to `extract_audio` and `sample_top_band` (about 25 lines).
- `tests/test_media.py`: the single line 200 edit above.
- `tests/test_media_cache.py` (new, Developer, 130 lines or fewer): unit tests with a fake `subprocess.run`.
- `tests/test_t056_acceptance.py` (new, Tester, 170 lines or fewer): pipeline-level acceptance.
- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`: insert the one paragraph.

## Steps (test first)
1. Before changing anything, on the base branch run `python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json > /tmp/t056_eval_before.json` and `python tests/fixtures/eval_player/build.py && python -m sportscut eval-player tests/fixtures/eval_player --json > /tmp/t056_player_before.json`.
2. Write `tests/test_media_cache.py` (see the test plan). Run `python -m pytest -q tests/test_media_cache.py` and check that it fails because the call counts are 2 instead of 1 and the arrays are writable.
3. Make the one-line change in `tests/test_media.py`. Run `python -m pytest -q tests/test_media.py -k mono_16k` and check that it fails on `not audio.flags.writeable`.
4. Implement the design in `sportscut/media.py`. Rerun steps 2 and 3 and check that they pass.
5. Insert the T-036 spec paragraph. Run `python -m pytest -q tests/test_t004_acceptance.py tests/test_t018_acceptance.py tests/test_t021_acceptance.py tests/test_t013_acceptance.py tests/test_t017_acceptance.py tests/test_t045_acceptance.py` and check that it passes.
6. Run the full suite with `python -m pytest -q`. It must pass.
7. Rerun both eval commands into `/tmp/t056_*_after.json`, then run `diff /tmp/t056_eval_before.json /tmp/t056_eval_after.json` and `diff /tmp/t056_player_before.json /tmp/t056_player_after.json`. Both diffs must be empty. Quote both JSON lines in the PR.

## Assumptions
- Holding one cached 90-minute track in memory is acceptable on a laptop. That is about 345 MB of float32 audio at 16 kHz and about 26 MB of top-band frames. In the long-running API process, the last video's arrays stay in memory until the next decode replaces them.
- (resolved path, size, mtime_ns) identifies file content well enough. Replacing a file at the same path with the same size and the same nanosecond mtime is not a real-world case.
- A read-only array passed to a third-party transcriber (`subtitles.transcribe` on exported clips) is fine. NumPy and torch at most warn and copy when converting it, and that path decodes clips, not the source video.

## Test plan

- Developer, tests/test_media_cache.py (fake ffmpeg: `monkeypatch.setattr(media, 'find_tool', lambda n: '/tools/ffmpeg')`, a counting fake `media.subprocess.run` returning CompletedProcess(returncode=0, stdout=<bytes>), and an autouse fixture that sets `media._audio_cache` and `media._band_cache` to None):
- test_hit_returns_same_readonly_object[extract_audio|sample_top_band]: two calls give 1 ffmpeg call, the result `is` the same object, writeable is False, and assignment raises ValueError (AC3, AC4)
- test_size_change_redecodes[...]: append a byte, then the call count is 2 and the new stdout is reflected (AC3)
- test_mtime_change_redecodes[...]: os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9)), then the call count is 2 (AC3)
- test_failure_not_cached[...]: first fake returncode=1 raises MediaError, the second call succeeds, and the call count is 2 (AC5)
- test_deleted_cached_file_raises_not_found and test_missing_tool_beats_cache: exact messages (AC5)
- test_one_entry_lru: A, B, A gives 3 calls; test_caches_independent: audio(A), band(A), audio(A) gives 1 audio call; test_relative_and_absolute_share_entry via monkeypatch.chdir (AC6)
- Developer, tests/test_media.py::test_extract_audio_is_mono_16k_float32: assertion changed to `not audio.flags.writeable` (real ffmpeg, synthetic_video) (AC4)
- Tester, tests/test_t056_acceptance.py, written from the ACs: a module-scoped fixture loads tests/fixtures/eval/build.py with importlib (as tests/test_pipeline.py::pipeline_eval_set does), makes tmp/'mixed', calls `build._encode_match('mixed', dir/'video.mp4')` and needs require_ffmpeg
- test_ac1_single_decode_per_run: reset both caches, wrap the real subprocess.run with a recorder through monkeypatch.setattr(media.subprocess, 'run', spy), run pipeline.run(video, out), and assert audio == 1 and band == 1. Then turn the cache off with `_cache_key` patched to `lambda p: object()`, run into out2, and assert audio >= 2 and band >= 2. This also proves the test fails on main's behaviour.
- test_ac2_byte_identical_manifest: (out/'highlights.json').read_bytes() == (out2/'highlights.json').read_bytes() and the entry lists are equal
- test_ac3_changed_file_redecodes_in_pipeline: after a cached run, os.utime the video with a new mtime_ns, run pipeline.run again, and assert exactly 1 more audio decode and 1 more band decode
- test_ac4_readonly_on_real_video: extract_audio and sample_top_band on the mixed video return non-writeable arrays with dtype float32 and uint8 and band shape[1:] == (30, 160)
- test_ac8_t036_note: the spec contains the exact T-056 paragraph and the last paragraph starts with 'Updated by T-004:'
- Commands: `python -m pytest -q` (full suite green), the two eval commands with an empty diff (AC7), `git diff --stat main...` (AC9), and the Tech Lead's `time sportscut cut` before/after (AC10)

## Deviations

- AC7 / step 7, player eval: `diff /tmp/t056_player_before.json /tmp/t056_player_after.json` cannot be empty on any two runs, because `seconds_per_min` (sportscut/eval_player.py:69) is wall time from `time.perf_counter()`. With every `seconds_per_min` key dropped, before and after JSON are equal (checked with a small json compare). The highlight eval diff is empty byte for byte.
- tests/test_media_cache.py::test_missing_tool_beats_cache uses the real `find_tool` with an empty PATH instead of a fake raiser, so the exact message comes from production code.
