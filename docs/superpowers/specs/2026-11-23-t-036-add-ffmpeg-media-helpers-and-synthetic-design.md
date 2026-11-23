# T-036: Add ffmpeg media helpers and synthetic video fixtures

Request R-001. Plan: `docs/superpowers/plans/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic.md`.

## Product Owner request

Tạo API POST /highlights nhận video, trả về danh sách đoạn highlight và file đã cắt

## Goal

After foundation, create `sportscut/media.py`, `tests/conftest.py`, `tests/test_media.py`, and `tests/test_fixtures.py`. Implement exact ffmpeg discovery errors, duration probing, mono 16 kHz float32 extraction, clean media failures, session-scoped synthetic video generation, burst-level and scene-change checks, and clean skips without ffmpeg. Develop each interface test-first with recorded expected failures before implementation, then run the complete suite with and without ffmpeg and confirm no tracked/generated media. Add concise required task-specific persistent specs while keeping the slice under ~400 changed lines.

## Acceptance criteria

- AC1: `sportscut/media.py` exposes `SAMPLE_RATE == 16000`, `MediaError` (subclass of `RuntimeError`), `find_tool`, `probe_duration` and `extract_audio` with the signatures in the spec.
- AC2: With PATH set to an empty directory, `find_tool('ffmpeg')` and `find_tool('ffprobe')` raise `MediaError` whose message is exactly `ffmpeg not found on PATH; install ffmpeg` / `ffprobe not found on PATH; install ffmpeg`. For an existing file, `probe_duration` and `extract_audio` raise the matching exact ffprobe/ffmpeg message.
- AC3: For a non-existent path, both `probe_duration` and `extract_audio` raise `MediaError` with message exactly `media file not found: <path>`, even without ffmpeg installed.
- AC4: `probe_duration(synthetic_video)` returns a native `float` within 0.15 s of 6.0. When ffprobe exits 0 with output `N/A`, it raises `MediaError('ffprobe returned no duration for <path>')`.
- AC5: `extract_audio(synthetic_video)` (source: stereo 44.1 kHz) returns a 1-D, writable `np.float32` array whose length is within 1600 samples of 96000 and whose absolute values are <= 1.0.
- AC6: On a text file named `bad.mp4`, `probe_duration` raises `MediaError` matching `^ffprobe failed for <path>: .+` and `extract_audio` raises `MediaError` matching `^ffmpeg failed for <path>: .+`. No `CalledProcessError` or other exception type leaks out.
- AC7: The session-scoped `synthetic_video` fixture creates, outside the repository under pytest's temp directory, a 6 s 160x120 mpeg4/aac MP4 with one video stream and one stereo 44.1 kHz audio stream.
- AC8: In the synthetic clip, audio RMS over 2.2-2.8 s is at least 5x the RMS over 0.2-1.8 s and over 3.5-5.5 s. The 8x6 gray frame mean is < 64 at 0.5/1.5/2.5 s and > 192 at 3.5/4.5/5.5 s.
- AC9: `.venv/bin/python -m pytest -q` exits 0 with 0 failed, 0 errors and 0 skipped on a machine with ffmpeg.
- AC10: `PATH=/nonexistent .venv/bin/python -m pytest -q -rs` exits 0 with 0 failed and 0 errors. Every skipped test's reason is exactly `ffmpeg and ffprobe are required on PATH`.
- AC11: After the suite, `git ls-files '*.mp4' '*.mkv' '*.wav'` is empty and no `.mp4`/`.wav`/`.mkv` exists in the worktree outside `.venv`.
- AC12: The final report quotes a genuine red run before each implementation step: `No module named 'sportscut.media'`, `cannot import name 'probe_duration'`, `fixture 'synthetic_video' not found` and `cannot import name 'extract_audio'`. Each is followed by a green run.
- AC13: The diff touches only `sportscut/media.py`, `tests/conftest.py`, `tests/test_media.py`, `tests/test_fixtures.py` (plus orchestrator-written `docs/superpowers/` records), stays under 400 changed lines, and changes nothing under `agent-office/`, `pyproject.toml` or `.gitignore`.

## Out of scope

- POST /highlights, FastAPI, uploads, response schemas or any HTTP code
- Highlight detection: audio energy/z-score, whistle, scene detection algorithms, scoring or peak selection
- Clip cutting/export, concatenation, JSON manifests
- CLI subcommands (cut/detect/eval) and the eval command or tests/fixtures/eval/ labelled set
- Committed media files, real footage, or anything under data/
- Probing stream metadata beyond duration (fps, resolution, codecs) in product code
- Chunked/streaming audio decoding, subprocess timeouts, caching tool paths, configurable sample rate or channel count
- Video-without-audio special handling beyond the generic `ffmpeg failed for` error
- Changes to pyproject.toml, .gitignore, README/docs, agent-office/ or hand-written docs/superpowers records

## Decisions

- T-036 (R-001): `sportscut.media` is the only module that calls ffmpeg/ffprobe; every failure in it is raised as `MediaError(RuntimeError)` with a stable, human-readable message; `subprocess.CalledProcessError` never leaks to callers.
- T-036 (R-001): Tool lookup is `shutil.which` on every call (no caching); the missing-tool message is exactly `<name> not found on PATH; install ffmpeg`.
- T-036 (R-001): The input file existence check (`media file not found: <path>`) runs before tool lookup, so it works without ffmpeg.
- T-036 (R-001): Media inputs are always passed to ffmpeg/ffprobe with `-i` and never through a shell, so file names cannot be read as options or shell code.
- T-036 (R-001): The audio contract for all detectors is a 1-D native float32 numpy array, mono, at `SAMPLE_RATE = 16000`, decoded in one ffmpeg call to `f32le` on stdout.
- T-036 (R-001): Failure messages use the form `<tool> failed for <path>: <last non-empty stderr line>`, falling back to `exit code N`.
- T-036 (R-001): Tests needing ffmpeg depend on the session fixture `require_ffmpeg`, which skips with exactly `ffmpeg and ffprobe are required on PATH`; the rest of the suite must pass with PATH=/nonexistent.
- T-036 (R-001): The synthetic clip is generated once per session in pytest's temp dir with lavfi sources and the built-in mpeg4/aac encoders (no libx264). Its layout is a contract for later detector tests: 6 s, 160x120@10fps, black 0-3 s / white 3-6 s (one scene change at 3.0 s), stereo 44.1 kHz seeded white noise at 0.02 with a x20 burst at 2-3 s.
- T-036 (R-001): Fixture checks use windows away from edges (AAC smearing) and thresholds (RMS ratio >= 5, gray < 64 / > 192) instead of exact values, so they hold across ffmpeg versions.
- T-036 (R-001): No media file is ever committed; generated media lives only in pytest temp dirs, and the existing `.gitignore` media patterns are kept as they are.
- T-029: exception for the player-touch eval set — tests/fixtures/eval_player/build.py may write git-ignored clip.mp4 files inside tests/fixtures/eval_player/ for the eval command; pytest still builds only in temp dirs and no media is committed.

## Existing specs this task changes

- (none)
