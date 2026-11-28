# T-056: Decode the audio and the top-band frames once per pipeline run

Request R-010. Request design: `docs/superpowers/specs/2026-11-28-r-010-t-i-test-upload-video-b-design.md`. Plan: `docs/superpowers/plans/2026-11-28-t-056-decode-the-audio-and-the-top.md`.

## Product Owner request

Tôi đã test upload video bóng đá của chúng tôi lên trong source, hiện tại phần cắt các đoạn highlight vẫn không chính xác nhất là phần bàn thắng. Kiểm tra và fix bug nếu có

## Goal

pipeline.run currently decodes the whole video's audio 4 times (find_highlights, tag_goals, tag_incidents, tag_saves) and the top band 3 times (tag_goals, board_reverts, tag_saves). On a 4K/HEVC phone file, scaled to 90 min, that threatens the 10-minute budget. Add a one-entry cache in sportscut/media.py for extract_audio and sample_top_band, keyed by (resolved path, size, mtime_ns), that returns read-only arrays so a caller cannot change the cached data. Callers stay unchanged, and segments and highlights.json must be byte-identical. Acceptance: a subprocess.run spy over pipeline.run on a synthetic video sees exactly one audio decode and one top-band decode; changing the file (size or mtime) causes a re-decode; both eval sets print unchanged JSON. The Tech Lead quotes the before/after wall time of `sportscut cut` on the PO's local job input. Assumption: memory for one cached 90-min track (about 350 MB float32 audio plus 26 MB of frames) is acceptable on a laptop.

## Acceptance criteria

- AC1: In a `pipeline.run(video, out)` on the synthetic 'mixed' match from tests/fixtures/eval/build.py (encoded into tmp_path), a spy that wraps the real `subprocess.run` records exactly 1 audio decode of the source (args contain 'f32le' and the value after '-i' is str(video)) and exactly 1 top-band decode of the source (args contain 'fps=1,scale=160:90,format=gray,crop=160:30:0:0' and the '-i' value is str(video)). With the cache off (`media._cache_key` patched to `lambda p: object()`), the same run records at least 2 of each (4 and 3 expected), which proves the fixture reaches every caller.
- AC2: highlights.json from AC1's cached run is byte-identical to highlights.json from a cache-off run of the same video with the same options, and the returned entry lists are equal.
- AC3: Calling `media.extract_audio(p)` twice on an unchanged file runs ffmpeg once and returns the same object (`is`). After the file's size changes (bytes appended) or its mtime_ns changes (`os.utime` with ns), the next call runs ffmpeg again and returns the new data. `sample_top_band` behaves the same way.
- AC4: Arrays returned by `extract_audio` and `sample_top_band`, whether fresh or from the cache, have `flags.writeable == False`, and `arr[0] = 0` raises ValueError. dtype, shape and values are unchanged: float32 1-D, and uint8 (n, 30, 160).
- AC5: A failed decode (non-zero ffmpeg exit, so MediaError) is not cached, and the next call runs ffmpeg again. A missing file still raises `media file not found: <path>` even when that path was cached earlier and then deleted. A missing ffmpeg still raises `ffmpeg not found on PATH; install ffmpeg` for a path that is in the cache.
- AC6: Each cache holds one entry: decoding A, then B, then A runs ffmpeg 3 times. The audio and band caches are independent: audio(A), then band(A), then audio(A) runs the audio decode once. The same file given as a relative path and as an absolute path is one cache hit.
- AC7: The highlight eval (`python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json`) and the player eval (`python tests/fixtures/eval_player/build.py && python -m sportscut eval-player tests/fixtures/eval_player --json`) print JSON identical to the base branch, so `diff` is empty. The PR quotes both lines.
- AC8: The T-036 design spec contains the exact 'Updated by T-056: ...' paragraph from the spec, placed before the closing 'Updated by T-004:' paragraph, which is still the last paragraph. The full suite `python -m pytest -q` passes, and the only edit to an existing test is the writeable assertion in tests/test_media.py::test_extract_audio_is_mono_16k_float32.
- AC9: The diff touches only sportscut/media.py, tests/test_media.py, tests/test_media_cache.py, tests/test_t056_acceptance.py and the T-036 design spec (plus orchestrator-written docs/superpowers records), with fewer than 400 changed lines. No caller module (detect.py, events/*, pipeline.py, evaluate.py) changes. This is checked by `git diff --stat` in review.
- AC10 (review evidence, not pytest): the Tech Lead quotes the before/after wall time of `time sportscut cut <PO local job input> <out>` (base branch vs this branch, same options), and the before/after highlights.json from that input match byte for byte (`cmp`).

## Out of scope

- Any change to detection, goal, incident or save logic, thresholds, or accuracy (other R-007 tasks)
- Caching has_audio, probe_duration, probe_size, sample_frames, sample_window or clip decodes
- A multi-entry or disk cache, a public clear-cache API, an env var or CLI flag to turn caching off
- Passing decoded arrays through pipeline/evaluate signatures (callers stay unchanged)
- Decoding the audio and the band in one ffmpeg pass, hardware decoding, or downscaling tricks for 4K/HEVC
- Freeing cache memory after pipeline.run in the API process
- README or performance-doc changes

## Decisions

- T-056: the cache lives only in sportscut/media.py as two module globals, `_audio_cache` and `_band_cache`, each a (key, array) tuple or None, with one entry per function. Callers (detect, events/*, pipeline, evaluate) are not changed.
- T-056: the cache key is `_cache_key(p) = (str(p.resolve()), st_size, st_mtime_ns)`. `_cache_key` is the single test seam: patching it to `lambda p: object()` turns caching off.
- T-056: the order inside extract_audio and sample_top_band is: is_file check, then find_tool, then the cache lookup, then the decode. The 'media file not found' and 'ffmpeg not found' errors stay exactly as they were, whatever the cache state.
- T-056: only successful decodes are cached. A MediaError leaves the previous entry untouched.
- T-056: returned arrays are read-only (flags.writeable = False) and the cache returns the same object on a hit, with no defensive copy. This reverses T-036 AC5 ('writable'). The only edit to an existing test is the writeable assertion in tests/test_media.py::test_extract_audio_is_mono_16k_float32. The T-036 design spec records the change in an 'Updated by T-056:' paragraph placed before the final 'Updated by T-004:' paragraph, which must stay last (test_t004/t018/t021).
- T-056: there is no lock. A single global tuple assignment is atomic in CPython, so concurrent API requests can at worst cause one redundant decode.
- T-056: 'both eval sets' means the highlight eval (tests/fixtures/eval) and the player eval (tests/fixtures/eval_player). Both must print JSON byte-identical to the base branch. The before/after wall time on the PO's local job input is review evidence quoted by the Tech Lead, not a pytest check.
- T-056: the budget is < 400 changed lines outside docs/superpowers (Developer tests ≤ 130, Tester tests ≤ 170). Scope and size are checked with git commands in review, not by pytest git-diff tests (T-052 rule).

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`
- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`
