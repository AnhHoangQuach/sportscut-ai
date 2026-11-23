# Plan T-006: Accept a YouTube link as POST /highlights input

Design: `docs/superpowers/specs/2026-11-23-t-006-accept-a-youtube-link-as-post-design.md`.

## Implementation plan

# T-006: Accept a YouTube link as POST /highlights input

Request R-002. Builds on T-005 (`sportscut/api.py`, merged at 3e30f75) and T-004 (`pipeline.run`). Read `docs/superpowers/specs/2026-11-23-t-005-expose-post-highlights-over-http-with-design.md` and the T-005 lines in `DECISIONS.md` first. Every T-005 decision still holds unless this spec says otherwise.

## Step 0: precondition (run first, from the worktree root)

```bash
test -f sportscut/api.py && grep -q '^def run(' sportscut/pipeline.py && grep -q '@app.post("/highlights")' sportscut/api.py && echo READY || echo BLOCKED
```

If it prints `BLOCKED`, stop and report BLOCKED. Do not create `api.py` or `pipeline.run` yourself (Tech Lead decision).

## Context

Today `POST /highlights` takes only a multipart `file`. It copies the file to `<data_dir>/jobs/<uuid>/input`, runs `pipeline.run(input, job/clips, top=, min_len=, max_len=)` and returns `{job_id, highlights:[{start,end,score,reason,clip_url}]}`. This task adds a second input: the form field `url` with a YouTube link. A new module `sportscut/sources.py` downloads the link with yt-dlp (Python API) and saves it as `<job>/input`, and the rest of the pipeline runs unchanged. Detection, export, `pipeline.run`, the manifest and `GET /highlights/{job_id}/clips/{name}` do not change.

## Design

### `sportscut/sources.py` (new, about 80 lines; no yt_dlp import at module level)

```python
ALLOWED_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
MAX_URL_LENGTH = 2048
MAX_DURATION_SECONDS = 3 * 3600          # 10800
MAX_DOWNLOAD_BYTES = 2 * 1024**3          # same as the T-005 default upload limit
FORMAT = "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]"
OUTPUT_NAME = "source.mp4"
URL_ERROR = "url must be an http(s) link to youtube.com or youtu.be"
EXTRA_ERROR = "YouTube links need the [youtube] extra: pip install 'sportscut[youtube]'"

class SourceError(Exception):
    """The video source (link or download) is invalid or failed."""

def check_youtube_url(url: str) -> None: ...
def download_youtube(url: str, dest_dir: str | Path) -> Path: ...
```

**`check_youtube_url(url)`** returns None, or raises `SourceError(URL_ERROR)` (always this exact message) when any of these is true:
- `url` is not a `str`, is empty, or is longer than `MAX_URL_LENGTH`;
- it contains any character with code point <= 0x20, 0x7f, or a backslash `\\` (this covers leading/trailing spaces and newlines);
- `urllib.parse.urlsplit(url)`, or reading `.port`, raises `ValueError`;
- `parts.scheme.lower()` is not in `{"http", "https"}`;
- `parts.username` or `parts.password` is not None (userinfo);
- `parts.port` is not None (any explicit port);
- `parts.hostname` (already lowercased by urllib) is not in `ALLOWED_HOSTS`. This is an exact match, so subdomains such as music.youtube.com and look-alikes such as youtube.com.evil.com are rejected.

**`download_youtube(url, dest_dir)`**, in this order:
1. `check_youtube_url(url)`. Validation runs before yt_dlp is imported.
2. `import yt_dlp` inside the function. On `ImportError`, raise `SourceError(EXTRA_ERROR)`.
3. `dest = Path(dest_dir)`; `dest.mkdir(parents=True, exist_ok=True)`.
4. Build the options with the module globals read at call time, so tests can monkeypatch them:
```python
opts = {"format": FORMAT, "merge_output_format": "mp4", "noplaylist": True,
        "max_filesize": MAX_DOWNLOAD_BYTES, "outtmpl": str(dest / "source.%(ext)s"),
        "quiet": True, "no_warnings": True, "noprogress": True, "cachedir": False}
```
5. Inside `try:` with `with yt_dlp.YoutubeDL(opts) as ydl:`:
   - `info = ydl.extract_info(url, download=False, process=False)`
   - if `info.get("_type", "video") != "video"` or `info.get("extractor_key") != "Youtube"`, raise `SourceError("link must point to a single YouTube video")` (this covers playlists, channels and url redirects);
   - if `info.get("is_live")` or `info.get("live_status") in {"is_live", "is_upcoming"}`, raise `SourceError("live streams are not supported")`;
   - `duration = info.get("duration")`: if None, raise `SourceError("video length is unknown")`; if `duration > MAX_DURATION_SECONDS`, raise `SourceError("video is longer than 3 hours")`. Exactly 10800 is accepted;
   - `ydl.process_ie_result(info, download=True)`.
   - Catch `yt_dlp.utils.YoutubeDLError as exc` and raise `SourceError("could not download video: " + str(exc).replace(str(dest), "download")) from exc`. Do not catch SourceError itself, and let other exception types propagate.
6. `path = dest / OUTPUT_NAME`. If it is not a file, raise `SourceError("download produced no video file")`. If `path.stat().st_size > MAX_DOWNLOAD_BYTES`, raise `SourceError(f"video exceeds {MAX_DOWNLOAD_BYTES} bytes")`. Return `path`.

The caller owns `dest_dir`: `download_youtube` does not delete partial files.

### `sportscut/api.py` changes (about 30 lines)

- Add the imports `from sportscut import pipeline, sources` and `from sportscut.sources import SourceError`. Always call `sources.check_youtube_url` and `sources.download_youtube` through the module, so tests can monkeypatch them. Add the constants `DOWNLOAD_DIR = "download"` and `JOB_FILE = "job.json"`.
- Signature: `file: UploadFile | None = File(None)` and `url: str | None = Form(None)`. `top`, `min_len` and `max_len` stay unchanged. The endpoint stays a sync `def`.
- Order of checks, all before any directory is created:
  1. FastAPI validation (unchanged).
  2. `if url is not None and not url.strip(): url = None` (a blank url counts as absent, as an HTML form sends it).
  3. `if (file is None) == (url is None): raise HTTPException(422, "send exactly one of file or url")`.
  4. The existing `min_len must be <= max_len` 422.
  5. If `url` is set: `sources.check_youtube_url(url)`. On `SourceError`, raise `HTTPException(400, str(exc))`; no job directory is created and the downloader is not called.
- Inside the existing `try` after `job_dir.mkdir(...)`:
  - upload: copy in chunks exactly as now (413 logic unchanged);
  - url: `downloaded = sources.download_youtube(url, job_dir / DOWNLOAD_DIR)`; `os.replace(downloaded, input_path)`; `shutil.rmtree(job_dir / DOWNLOAD_DIR, ignore_errors=True)`;
  - then `(job_dir / JOB_FILE).write_text(json.dumps({"source_url": url}) + "\n", encoding="utf-8")`. `url` is None for uploads, which gives `{"source_url": null}`;
  - then `pipeline.run(...)` with exactly the same arguments as today.
- Add `except SourceError as exc: shutil.rmtree(job_dir, ignore_errors=True); raise HTTPException(400, str(exc)) from exc` next to the existing handlers. PipelineError, MediaError, HTTPException and other exceptions behave as before. The PipelineError detail still replaces the input path with `upload` for both sources.
- The response body does not change: still exactly `{job_id, highlights}`. The T-005 tests assert those keys.

### Job layout (extends T-005)

`<data_dir>/jobs/<uuid>/input` (an upload or the downloaded mp4), `job.json` (`{"source_url": <str|null>}`, indent none, trailing newline) and `clips/`. `download/` exists only while a link is downloading. `job.json` and `input` are never served, because `get_clip` only serves manifest names.

### Packaging and docs

- `pyproject.toml`: add `youtube = ["yt-dlp>=2024.8.6"]` under `[project.optional-dependencies]`. Do **not** change `dependencies`, `api` or `dev`: T-005's acceptance test pins `dev` exactly, and the tests use a fake `yt_dlp`.
- `README.md`, inside the existing `## API HTTP` section (keep every existing line): add `pip install -e '.[api,youtube]'`, the example `curl -F url=https://www.youtube.com/watch?v=VIDEO_ID http://127.0.0.1:8000/highlights`, and one sentence on the limits: only youtube.com/www/m.youtube.com/youtu.be links, a single video, at most 3 hours, downloaded at <=720p mp4, at most 2 GiB, `file` and `url` are mutually exclusive, 400 when the link is invalid or the download fails. Add one more sentence: the person submitting a link is responsible for having the rights to that video.
- `docs/superpowers/specs/2026-11-23-t-005-expose-post-highlights-over-http-with-design.md`: append a section `## Updated by T-006` that lists these points: `file` is optional, `url` is the alternative, exactly one of the two (422), SourceError maps to 400, and every job writes `job.json`.

## Files

- create `sportscut/sources.py`, `tests/test_sources.py`, `tests/test_t006_acceptance.py` (Tester)
- change `sportscut/api.py`, `tests/test_api.py` (add tests only; do not edit existing tests), `pyproject.toml`, `README.md`, `docs/superpowers/specs/2026-11-23-t-005-expose-post-highlights-over-http-with-design.md`
- do not touch: `pipeline.py`, `detect.py`, `export.py`, `media.py`, `cli.py`, `tests/conftest.py`, `tests/test_t005_acceptance.py`, `agent-office/`

## TDD steps

1. Step 0 precondition: it must print READY.
2. `tests/test_sources.py`: write the URL accept/reject table and watch it fail (ImportError). Add `SourceError`, the constants and `check_youtube_url`, and watch it pass.
3. Add the fake `yt_dlp` fixture (see the test plan) and the download tests: options, call order, return path, dest created, guards, error wrapping, size, missing output, missing extra. Watch them fail, implement `download_youtube`, and watch them pass.
4. `tests/test_api.py` (append): exactly-one 422 cases, the blank url case, invalid url 400 without calling the downloader, download SourceError 400 with cleanup, job.json for uploads. Watch them fail, change `api.py`, and watch them pass.
5. `tests/test_api.py` (append): URL→segments with the real pipeline on `burst_video` through the monkeypatched downloader, with the highlights equal to the upload result. Watch it pass.
6. Import-guard test (subprocess): `import sportscut.api` does not load `yt_dlp`.
7. pyproject `youtube` extra, README, and the T-005 spec note.
8. Run the full verify commands below.

## Verify

```bash
.venv/bin/python -m pytest -q tests/test_sources.py tests/test_api.py tests/test_t006_acceptance.py -rs   # 0 failed, 0 skipped (ffmpeg on PATH)
.venv/bin/python -m pytest -q   # 0 failed; every existing test unchanged and passing
```

There is no eval or F1 gate: detection is untouched. The URL→segments test checks that the output is the same as for an upload of the same bytes.

## Assumptions

- The PO is responsible for the rights to linked videos; the README says so.
- Processing stays synchronous, as in T-005. A 3 h download can make the request very slow, which is acceptable until real use shows timeouts (async jobs are a later task).
- The download size cap is the constant 2 GiB (`MAX_DOWNLOAD_BYTES`), independent of `SPORTSCUT_MAX_UPLOAD_BYTES`, because the task fixes the signature `download_youtube(url, dest_dir)`.
- The PipelineError detail keeps saying `upload` for URL jobs too (no new wording).
- Diff budget: the implementation diff (everything except the Tester's `tests/test_t006_acceptance.py` and the orchestrator-written docs/superpowers files) stays under 400 changed lines, following the T-005 precedent. Target about 130 lines for production code plus docs and about 220 for the Developer's tests.

## Test plan

- Fixture `fake_ytdlp` (tests/test_sources.py, and its own copy in the Tester's file): builds types.ModuleType('yt_dlp') with `utils` = SimpleNamespace(YoutubeDLError=E, DownloadError=subclass of E) and a `YoutubeDL` class. The class records the opts and calls on a shared list, works as a context manager, returns a configurable info dict from extract_info (default {'extractor_key': 'Youtube', 'duration': 60}), and on process_ie_result writes configurable bytes (default b'mp4') to Path(opts['outtmpl'].replace('%(ext)s', 'mp4')) unless told to write nothing or to raise. Installed with monkeypatch.setitem(sys.modules, 'yt_dlp', fake). It never touches the network.
- unit tests/test_sources.py: test_check_accepts_youtube_hosts (parametrized, AC2); test_check_rejects (parametrized over every AC3 input, plus None) asserting the exact message.
- unit tests/test_sources.py: test_download_options_and_call_order (AC4: opts dict, calls order, return path, dest created); test_download_rejects_non_video_live_unknown_long (parametrized, AC5, asserts process_ie_result not called) and test_duration_at_limit_ok.
- unit tests/test_sources.py: test_download_error_wrapped_and_path_hidden for both extract_info and process_ie_result (AC6); test_missing_output (AC7); test_size_cap with MAX_DOWNLOAD_BYTES monkeypatched to 5 for 6 bytes (error) and 5 bytes (ok), also checking opts max_filesize == 5 (AC7).
- unit tests/test_sources.py: test_missing_extra (sys.modules['yt_dlp']=None; valid URL gives the extra message, invalid URL gives the url message) (AC8); test_api_import_does_not_load_ytdlp via subprocess `import sys, sportscut.api; assert 'yt_dlp' not in sys.modules` and the same for sportscut.cli with fastapi/uvicorn/yt_dlp (AC8).
- integration tests/test_api.py (append only): test_url_job_matches_upload_result (AC9). Uses the real pipeline on burst_video through a monkeypatched sources.download_youtube that shutil.copy's burst_video to dest_dir/'source.mp4' (dest_dir.mkdir(parents=True, exist_ok=True) first) and returns it. Compares with an upload of the same file, then checks download args, input bytes, the absence of the download dir, job.json, and the clip GETs.
- integration tests/test_api.py: test_upload_writes_job_json_with_null_source and the 404 for clips/job.json (AC10); test_exactly_one_of_file_or_url (parametrized both/neither, AC11); test_blank_url_with_file_is_upload (url '' and '   ', AC11).
- integration tests/test_api.py: test_invalid_url_returns_400_without_download (parametrized over evil.com and 169.254.169.254, AC12); test_download_failure_returns_400_and_cleans (AC13); test_download_unexpected_error_removes_job with pytest.raises(RuntimeError) (AC13).
- Tester: tests/test_t006_acceptance.py independently covers AC2-AC14 from the acceptance criteria, with its own fake yt_dlp and its own monkeypatched downloader. It confirms that at least one test fails when check_youtube_url accepts every host (mutation check, then revert), and it reads no git history (per the T-005 Tech Lead ruling).
- Regression: run the full suite (AC15). tests/test_t005_acceptance.py and the existing tests/test_api.py tests must pass without edits.
