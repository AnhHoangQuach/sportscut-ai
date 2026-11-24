# T-005: Expose POST /highlights over HTTP with clip downloads

Request R-001. Plan: `docs/superpowers/plans/2026-11-23-t-005-expose-post-highlights-over-http-with.md`.

## Product Owner request

Tạo API POST /highlights nhận video, trả về danh sách đoạn highlight và file đã cắt

## Goal

Add `sportscut/api.py` (FastAPI, installed through the `[api]` extra: fastapi, uvicorn, python-multipart) and a `sportscut serve --host 127.0.0.1 --port 8000` command. `POST /highlights` takes a multipart `file` plus optional form fields `top`, `min_len` and `max_len`. It streams the upload to `$SPORTSCUT_DATA_DIR/jobs/<uuid>/input` (default `./sportscut-data`), with a configurable maximum size that returns 413, then runs `pipeline.run` synchronously in a threadpool. It returns 200 `{"job_id", "highlights": [{"start", "end", "score", "reason", "clip_url"}]}`, or 400 on `PipelineError` and 422 on a missing file or bad parameters. `GET /highlights/{job_id}/clips/{name}` serves the clip with FileResponse; it validates job_id as a UUID and name against the job's manifest to block path traversal, and returns 404 otherwise. Tests use FastAPI TestClient on the synthetic video: segments cover the injected bursts, every clip_url returns 200 video/mp4, and the 400, 404 and traversal cases are rejected. Assumptions: synchronous processing, no auth, no cleanup or retention of job dirs, local binding by default (all noted for the PO as follow-ups); add a short README section with a curl example.

## Acceptance criteria

- AC1: pyproject.toml has the extra `api = ["fastapi>=0.110", "uvicorn>=0.29", "python-multipart>=0.0.9"]`. `dev` contains pytest>=8, httpx>=0.27 and the same three api packages. `dependencies` is still exactly `["numpy>=1.26"]`. `sportscut/api.py` exposes a module-level FastAPI `app` and does not import subprocess (AST check). `python -c "import sportscut.cli"` does not import fastapi or uvicorn: after the import, `'fastapi' not in sys.modules` is checked in a subprocess.
- AC2: POSTing burst_video as multipart `file` (no other fields) with SPORTSCUT_DATA_DIR=<tmp> returns 200. The JSON keys are exactly {job_id, source_name, source_url, duration, highlights} (the T-007 canonical response), and job_id equals `str(uuid.UUID(job_id))`. `highlights` has 3 items, and each has exactly the keys {start, end, score, reason, event, event_confidence, clip_url}. Each burst interval (20,21), (50,51), (75,76) is covered by some highlight with start <= burst start and end >= burst end. The highlights, without clip_url, equal `<tmp>/jobs/<job_id>/clips/highlights.json` with `file` removed, in the same order. `<tmp>/jobs/<job_id>/input` exists and its bytes equal burst_video's bytes. (updated by T-012)
- AC3: For every highlight, `client.get(clip_url)` returns 200 with a content-type that starts with `video/mp4`, and the body is non-empty and equal to the bytes of `<tmp>/jobs/<job_id>/clips/clip_0N.mp4`. Each clip_url ends with `/highlights/<job_id>/clips/clip_0N.mp4` (N = 1..3 in order).
- AC4: POST with form fields top=1, min_len=4, max_len=6 on burst_video returns 200 with exactly 1 highlight whose end - start == 6 ± 0.01.
- AC5: A text-file upload returns 400 with a `detail` that starts with `ffprobe failed for upload: ` and does not contain the data dir path. An audio-less mpeg4 video upload returns 400 with `detail == "no audio stream in upload"`. After each 400, `<tmp>/jobs` contains no new job directory.
- AC6: When `sportscut.pipeline.run` is monkeypatched to raise `MediaError("ffmpeg not found on PATH; install ffmpeg")`, POST returns 500 with `detail == "processing failed"` and leaves no job directory.
- AC7: Each of these returns 422, does not call `pipeline.run` (spy) and creates no job directory: no `file` field; top=0; top=abc; min_len=0; max_len=-1; min_len=nan; max_len=inf; min_len=20 with max_len=10. The last one has `detail == "min_len must be <= max_len"`.
- AC8: With SPORTSCUT_MAX_UPLOAD_BYTES=10, an 11-byte upload returns 413 with `detail == "upload exceeds 10 bytes"`, does not call `pipeline.run` and leaves no job directory. A 10-byte upload with `pipeline.run` stubbed to return [] gets 200 with `highlights == []`.
- AC9: With SPORTSCUT_DATA_DIR unset, the cwd changed to a tmp dir (monkeypatch.chdir) and `pipeline.run` stubbed to return [], a POST returns 200, and `<cwd>/sportscut-data/jobs/<job_id>/input` exists. The stub received `video == <that path>` and `out_dir == <cwd>/sportscut-data/jobs/<job_id>/clips`.
- AC10: Using the real job from AC2, GET returns 404 for each of these, and no response body equals the input or manifest bytes: job_id `not-a-uuid`; the uppercase form of the real job_id; a fresh uuid4; name `clip_99.mp4`; name `highlights.json`; name `input`; raw paths `/highlights/<id>/clips/..%2Finput` and `/highlights/<id>/clips/%2e%2e%2finput`; and `/highlights/<id>/clips/..%2Fclips%2Fhighlights.json`.
- AC11: With `uvicorn.run` monkeypatched to a spy, `main(["serve"])` returns 0 and the spy was called once as `(sportscut.api.app, host="127.0.0.1", port=8000)`. `main(["serve", "--host", "0.0.0.0", "--port", "9001"])` passes host "0.0.0.0" and port 9001 (an int). With `sys.modules["uvicorn"] = None`, `main(["serve"])` returns 1 and stderr is exactly `sportscut: error: the API needs the [api] extra: pip install 'sportscut[api]'\n`. The no-argument help lists `serve`.
- AC12: `.venv/bin/python -m pytest -q tests/test_api.py -rs` reports 0 failed and 0 skipped when ffmpeg is on PATH. `python -m pytest -q` reports 0 failures, and every existing test passes unchanged.
- AC13: README.md has a section titled `API HTTP` that contains `pip install -e '.[api]'`, `sportscut serve`, a `curl -F file=@` POST to `/highlights` and a clip download curl. It also mentions SPORTSCUT_DATA_DIR and SPORTSCUT_MAX_UPLOAD_BYTES. `.gitignore` contains `sportscut-data/`. The diff touches only the files in `files`, stays under 400 changed lines, and changes nothing under agent-office/ or tests/conftest.py, or in pipeline.py, export.py, media.py or detect.py.

## Out of scope

- Async/background jobs, a job status endpoint, progress reporting or websockets
- Authentication, API keys, CORS, rate limiting or HTTPS
- Cleaning up, retaining or expiring job directories, and any DELETE endpoint
- A GET endpoint for the full job/manifest or for the original upload
- Rejecting oversized uploads before Starlette parses the multipart body (Content-Length pre-check, custom streaming parser)
- Validating upload content type or file extension (ffprobe decides)
- Changes to detection, export naming, the manifest format, pipeline.run or PipelineError
- Docker images, deployment config, a uvicorn worker count, reload, or log configuration
- An OpenAPI customization beyond FastAPI's defaults
- Eval or F1 changes (detection is untouched, so F1 is unaffected)

## Decisions

- T-005 (R-001): The API lives in `sportscut/api.py` as a module-level FastAPI `app`. FastAPI, uvicorn and python-multipart are only in the new `[api]` extra and the `dev` extra (explicit lists, together with httpx for TestClient). Runtime dependencies stay numpy only, and importing `sportscut.cli` must not import fastapi or uvicorn.
- T-005 (R-001): `POST /highlights` is a sync `def` endpoint, so FastAPI runs it and `pipeline.run` in its threadpool. The API always calls `pipeline.run` through the `sportscut.pipeline` module (monkeypatchable) and adds no detection or export logic of its own.
- T-005 (R-001): Settings come from the environment and are read per request: `SPORTSCUT_DATA_DIR` (default `sportscut-data`, relative to cwd) and `SPORTSCUT_MAX_UPLOAD_BYTES` (default 2 GiB = 2147483648). An upload larger than the limit gives 413 `upload exceeds <limit> bytes`, and an upload exactly at the limit is accepted.
- T-005 (R-001): Job layout is `<data_dir>/jobs/<uuid4>/input` (the upload, no extension, copied in 1 MiB chunks) and `<data_dir>/jobs/<uuid4>/clips/` (pipeline output: clip_NN.mp4 and highlights.json).
- T-005 (R-001): Status mapping. 422: FastAPI validation (missing file; top >= 1; min_len and max_len > 0 and finite) plus `min_len must be <= max_len`, checked before anything is written. 413: oversized upload. 400: PipelineError, with the server input path replaced by `upload` in the detail. 500: MediaError with the fixed detail `processing failed`. Every failed POST deletes its job dir.
- T-005 (R-001): The 200 body is `{job_id, highlights: [{start, end, score, reason, clip_url}]}` in manifest order. `clip_url` is the absolute URL from `request.url_for("get_clip", ...)`.
- T-005 (R-001): `GET /highlights/{job_id}/clips/{name}` serves a file only if job_id is a canonical lowercase UUID string, the job's clips/highlights.json exists, and `name` equals a manifest `file` entry. Everything else returns 404 `not found`. The name is never joined to a path before it matches the manifest, which blocks traversal, `input` and `highlights.json`.
- T-005 (R-001): CLI `sportscut serve [--host 127.0.0.1] [--port 8000]` imports uvicorn and sportscut.api lazily and calls `uvicorn.run(app, host=..., port=...)`. Without the extra it prints `sportscut: error: the API needs the [api] extra: pip install 'sportscut[api]'` and exits 1.
- T-005 (R-001): Assumptions the PO should review as follow-ups: processing is synchronous, there is no auth, job dirs are never cleaned up, the server binds to localhost by default, and the size limit is enforced while copying, after Starlette has already spooled the body.
- T-005 (R-001): `sportscut-data/` is git-ignored. The API tests use the existing burst_video fixture and build the audio-less video locally, and tests/conftest.py is unchanged.

## Existing specs this task changes

- (none)

## Updated by T-006

- `file` is optional and `url` is the alternative input; exactly one is required (422 otherwise).
- A `SourceError` from URL validation or downloading maps to HTTP 400.
- Every successful job writes `job.json` containing its source URL or `null` for uploads.

## Updated by T-007

- Successful POST now persists an atomic full `job.json` containing source name or
  URL, duration, version, and manifest-equivalent segments. Its response adds
  `source_name`, `source_url`, and `duration` to the existing job/highlight shape.
- `GET /highlights/{job_id}` reopens that canonical response, while
  `GET /highlights/{job_id}/source` streams the fixed input with single-range byte
  seeking. `PUT /highlights/{job_id}/segments` replaces and synchronously re-cuts
  the full segment list.
- Clip authorization now uses only current `job.json` segment filenames, so stale
  versioned URLs and traversal-shaped names return 404.
