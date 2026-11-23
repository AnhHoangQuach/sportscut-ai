# Plan T-005: Expose POST /highlights over HTTP with clip downloads

Design: `docs/superpowers/specs/2026-11-23-t-005-expose-post-highlights-over-http-with-design.md`.

## Implementation plan

# T-005: Expose POST /highlights over HTTP with clip downloads

Request R-001 (PO: "Tạo API POST /highlights nhận video, trả về danh sách đoạn highlight và file đã cắt").

## Context (current main, cd445e6)
- `sportscut.pipeline.run(video, out_dir, top=10, min_len=10, max_len=30) -> list[dict]` is the single entry point (T-004). It returns the manifest entries `{start, end, score, reason, file}`, sorted by start, with files `clip_01.mp4`, `clip_02.mp4` and so on. These are the contents of `<out_dir>/highlights.json` (`sportscut.export.MANIFEST_NAME`).
- `PipelineError` means bad caller input and maps to HTTP 400. `MediaError` (no ffmpeg on the server, or an encode failure) is a server fault and maps to 500 (T-004 decisions).
- `tests/conftest.py` has the session fixtures `require_ffmpeg` and `burst_video`. `burst_video` is 90 s with audio bursts at 20-21 s, 50-51 s and 75-76 s, and `pipeline.run` returns 3 clips of 12 s for it.
- `.agent-office/config.toml` `setup_cmd` installs `-e '.[dev]'` into `.venv`, so the test dependencies must be in the `dev` extra.

## Design

### Packaging (`pyproject.toml`)
- Add the extra `api = ["fastapi>=0.110", "uvicorn>=0.29", "python-multipart>=0.0.9"]`.
- `dev` becomes `["pytest>=8", "httpx>=0.27", "fastapi>=0.110", "uvicorn>=0.29", "python-multipart>=0.0.9"]`. The packages are listed explicitly (no self-referencing `sportscut[api]`), so the worktree setup works with any pip. `httpx` is needed by `fastapi.testclient`.
- Runtime `dependencies` stay `["numpy>=1.26"]`. The core CLI must not import fastapi.
- After editing pyproject, reinstall: `.venv/bin/python -m pip install -q -e '.[dev]'`.

### `sportscut/api.py` (new)
Module-level `app = FastAPI(title="SportsCut")`. It imports `from sportscut import pipeline` and always calls `pipeline.run(...)` through the module, so tests can monkeypatch `sportscut.pipeline.run`. It imports `PipelineError` from `sportscut.pipeline` and `MediaError` from `sportscut.media`. It does not import subprocess.

Settings are read from the environment on every request, so tests can use `monkeypatch.setenv`:
- `SPORTSCUT_DATA_DIR`: default `sportscut-data`, resolved relative to the process cwd at request time.
- `SPORTSCUT_MAX_UPLOAD_BYTES`: an int. The default is `DEFAULT_MAX_UPLOAD_BYTES = 2 * 1024**3` (2 GiB).

The module also defines the constants `CHUNK_BYTES = 1024 * 1024`, `INPUT_NAME = "input"` and `CLIPS_DIR = "clips"`.

**`POST /highlights`.** The endpoint is a plain `def create_highlights(request: Request, file: UploadFile = File(...), top: int = Form(10, ge=1), min_len: float = Form(10, gt=0, allow_inf_nan=False), max_len: float = Form(30, gt=0, allow_inf_nan=False)) -> dict`. It is NOT `async def`, so FastAPI runs it, and the blocking `pipeline.run` call, in its threadpool. Steps, in this order:
1. If `min_len > max_len`, raise `HTTPException(422, "min_len must be <= max_len")` before anything is written. FastAPI's own validation already returns 422 for a missing `file`, a non-numeric value, `top < 1`, `min_len/max_len <= 0`, `nan` or `inf`.
2. Set `job_id = str(uuid.uuid4())` and `job_dir = <data_dir>/jobs/<job_id>`, then `job_dir.mkdir(parents=True)`.
3. Stream the upload to `job_dir/input`: loop `chunk = file.file.read(CHUNK_BYTES)`, write each chunk and count the bytes. As soon as the total is greater than the limit (a file exactly at the limit is accepted), stop and raise `HTTPException(413, f"upload exceeds {limit} bytes")`.
4. Call `entries = pipeline.run(job_dir / "input", job_dir / "clips", top=top, min_len=min_len, max_len=max_len)`.
5. On `PipelineError` as exc, return 400 with `detail = str(exc).replace(str(job_dir / "input"), "upload")`, so the server path never leaks. For example: `no audio stream in upload`, or `ffprobe failed for upload: ...`.
6. On `MediaError`, return 500 with `detail = "processing failed"`.
7. On any 413/400/500 (in short, any failure after the mkdir), run `shutil.rmtree(job_dir, ignore_errors=True)` before raising. A failed request leaves no job dir. Wrap steps 3-6 in try/except and clean up there.
8. Return 200 with `{"job_id": job_id, "highlights": [{"start", "end", "score", "reason", "clip_url"}]}`, in manifest order. `clip_url` is `str(request.url_for("get_clip", job_id=job_id, name=entry["file"]))`, an absolute URL such as `http://127.0.0.1:8000/highlights/<id>/clips/clip_01.mp4`. The other fields are copied from the entry, and `file` is dropped.

**`GET /highlights/{job_id}/clips/{name}`.** Route name `get_clip`, plain `def get_clip(job_id: str, name: str) -> FileResponse`. It returns 404 (`detail = "not found"`) unless all of these hold:
- (a) `str(uuid.UUID(job_id)) == job_id`. The id must be canonical, lowercase and hyphenated, and a ValueError counts as not found.
- (b) `<data_dir>/jobs/<job_id>/clips/highlights.json` exists and parses.
- (c) `name` equals some entry's `file` in that manifest.
- (d) the file exists.

If all hold, it returns `FileResponse(clips_dir / name, media_type="video/mp4")`. The name is never joined to a path before it has matched the manifest, so `..`, `input`, `highlights.json` and encoded slashes all return 404.

### CLI (`sportscut/cli.py`)
Add the subcommand `serve` with `--host` (default `127.0.0.1`) and `--port` (int, default `8000`). When it runs, it imports inside the branch: `import uvicorn` and `from sportscut.api import app`.
- On `ImportError`, it prints `sportscut: error: the API needs the [api] extra: pip install 'sportscut[api]'` to stderr and returns 1.
- Otherwise it calls `uvicorn.run(app, host=args.host, port=args.port)` and returns 0.

The top-level CLI must not import fastapi or uvicorn, and the other subcommands are unchanged.

### Repo files
- `.gitignore`: add `sportscut-data/`.
- `README.md`: add a short Vietnamese section `## API HTTP (POST /highlights)`. It contains: install with `pip install -e '.[api]'`, `sportscut serve --host 127.0.0.1 --port 8000`, the request `curl -F file=@match.mp4 -F top=5 -F min_len=10 -F max_len=30 http://127.0.0.1:8000/highlights`, an example response JSON, a clip download with `curl -o clip_01.mp4 "<clip_url>"`, the env vars `SPORTSCUT_DATA_DIR` and `SPORTSCUT_MAX_UPLOAD_BYTES`, the status codes 400/404/413/422/500, and the limitations: synchronous, no auth, job dirs never deleted, binds to localhost by default.

## Files
- Create `sportscut/api.py` and `tests/test_api.py`.
- Modify `sportscut/cli.py`, `tests/test_cli.py`, `pyproject.toml`, `.gitignore` and `README.md`.
- Do not touch `tests/conftest.py`, `sportscut/pipeline.py`, `export.py`, `media.py` or `detect.py`.

## Steps (TDD; run every red step and quote its failure)
0. Edit pyproject (the extras above), then run `.venv/bin/python -m pip install -q -e '.[dev]'` and `python -c "import fastapi, uvicorn, multipart, httpx"`. It must exit 0.
1. **Red.** In `tests/test_api.py`, write the success tests (AC2, AC3, AC4). Expected failure: `ModuleNotFoundError: No module named 'sportscut.api'`.
   - Fixtures: a module-scoped `data_dir` (`tmp_path_factory.mktemp("api-data")`).
   - A module-scoped `job` fixture that uses `with pytest.MonkeyPatch.context() as mp: mp.setenv("SPORTSCUT_DATA_DIR", str(data_dir))` and POSTs `burst_video` once. It returns `(response_json, data_dir)`.
   - An autouse function-scoped fixture that sets `SPORTSCUT_DATA_DIR` to the same `data_dir` and deletes `SPORTSCUT_MAX_UPLOAD_BYTES`.
   - `client = TestClient(app)`.
   - Add `pytest.importorskip("fastapi")` at the top of the module. AC12 makes sure it does not actually skip in the venv.
2. **Green.** Implement the POST route and `get_clip` (the happy path).
3. **Red, then green.** The 400 tests (AC5), the 500 test (AC6) and the 422 tests (AC7).
4. **Red, then green.** The 413 tests, the boundary test and the default-data-dir test (AC8, AC9).
5. **Red, then green.** The 404/traversal tests (AC10). They should mostly pass once get_clip validates. Show that at least one fails against a naive `clips_dir / name` version, or explain in the report why it is green on the first run.
6. **Red, then green.** In `tests/test_cli.py`, the serve tests (AC11). Expected red: `invalid choice: 'serve'`. Then implement in cli.py.
7. Update the README and .gitignore. Run `python -m pytest -q` and `python -m pytest -q tests/test_api.py -rs`. Quote the summary lines.

## Assumptions (for the PO as follow-ups)
- Processing is synchronous: the HTTP request stays open until all clips are cut. A 90-minute match can take minutes, and the client timeout must allow for that. A job queue with status polling is a follow-up.
- There is no authentication and no rate limiting. The server binds to 127.0.0.1 by default, and exposing it on a network needs a later auth task.
- Successful job dirs (input plus clips) are kept forever. There is no cleanup or retention yet. Failed requests do delete their job dir.
- The default maximum upload is 2 GiB. Starlette spools the multipart body to its own temp file before the handler runs, so "streaming" here means the handler copies in 1 MiB chunks and enforces the limit while copying. Rejecting a request before the body is read is a follow-up.
- `clip_url` is an absolute URL built from the request's Host. Behind a reverse proxy, uvicorn's proxy-header settings apply.
- Error messages are in English, like the CLI.

## Test plan

- tests/test_api.py (new). Add `pytest.importorskip("fastapi")` at the top. Fixtures: a module-scoped `data_dir`; a module-scoped `job` that sets SPORTSCUT_DATA_DIR with pytest.MonkeyPatch.context() and POSTs burst_video once; an autouse function-scoped env fixture (SPORTSCUT_DATA_DIR=data_dir, SPORTSCUT_MAX_UPLOAD_BYTES unset); `client = TestClient(app)`; and a `spy_run` helper fixture that monkeypatches `sportscut.pipeline.run` to record its calls and return [] or raise.
- test_post_returns_highlights_covering_bursts (AC2): uses burst_video and the real pipeline.
- test_clip_urls_serve_mp4_bytes (AC3): GET every clip_url, check the 200 status, the video/mp4 content type, and that the bytes equal the file on disk.
- test_post_passes_form_options (AC4): top=1, min_len=4, max_len=6 gives 1 highlight of about 6 s.
- test_post_non_video_returns_400_without_path and test_post_no_audio_returns_400 (AC5). The audio-less video is generated in the test module with ffmpeg (`color=c=black:s=160x120:r=5:d=3`, mpeg4, -q:v 5, yuv420p), the same way as tests/test_pipeline.py::_video_only. Both use the require_ffmpeg fixture and assert that no job dir remains.
- test_media_error_returns_500 (AC6): pipeline.run is stubbed to raise MediaError.
- test_bad_parameters_return_422 (AC7): parametrized over the missing file, top=0, top=abc, min_len=0, max_len=-1, min_len=nan, max_len=inf and min_len=20/max_len=10. It uses a tiny text upload, asserts the spy was not called and that the jobs dir is unchanged, and checks the min_len>max_len detail text.
- test_upload_over_limit_returns_413 and test_upload_at_limit_is_accepted (AC8): set SPORTSCUT_MAX_UPLOAD_BYTES=10 and send 11 bytes and 10 bytes, with the pipeline.run stub.
- test_default_data_dir_is_cwd_sportscut_data (AC9): monkeypatch.delenv SPORTSCUT_DATA_DIR, monkeypatch.chdir(tmp_path), and check the stub's arguments.
- test_get_clip_rejects (AC10): parametrized over the 9 bad job_id/name/raw-path cases against the real `job` fixture. Assert 404 and that the body differs from the input and manifest bytes. Send raw encoded paths as a string URL (`client.get(f"/highlights/{id}/clips/..%2Finput")`).
- test_api_module_does_not_import_subprocess and test_cli_import_does_not_load_fastapi (AC1). The second runs a subprocess: `python -c "import sys, sportscut.cli; assert 'fastapi' not in sys.modules and 'uvicorn' not in sys.modules"`. Also add test_create_highlights_is_sync: `not inspect.iscoroutinefunction(sportscut.api.create_highlights)`, so it runs in FastAPI's threadpool.
- tests/test_cli.py: test_serve_defaults_call_uvicorn, test_serve_custom_host_port, test_serve_without_api_extra_exits_1 (monkeypatch.setitem(sys.modules, 'uvicorn', None)), and assert that the no-argument help contains `serve` (AC11).
- Run commands: `.venv/bin/python -m pip install -q -e '.[dev]'`, `python -m pytest -q tests/test_api.py -rs` (0 skipped when ffmpeg is present) and `python -m pytest -q` (0 failed). Optional manual check: run `sportscut serve` and send the README curl with a synthetic video.
