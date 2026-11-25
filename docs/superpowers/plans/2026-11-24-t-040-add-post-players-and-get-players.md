# Plan T-040: Add POST /players and GET /players/{job_id}/reel/{name} to the API

Design: `docs/superpowers/specs/2026-11-24-t-040-add-post-players-and-get-players-design.md`.

## Implementation plan

# T-040: Add POST /players and GET /players/{job_id}/reel/{name} to the API

Request R-006 (PO: "Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó."). This is the API half (T-034A) of the T-034 split. The Tech Lead split T-034 on 2026-11-24 because the diff was 857 non-doc lines against a ~400 guardrail. The web section 'Theo dõi cầu thủ' is T-041 (T-034B) and depends on this task. The T-034 design was never committed to main, so this spec is self-contained. A reference implementation that passed AC1–AC9 is on checkpoint `6231ac9` (branch office/T-034-r2). The Developer MAY read it with `git show 6231ac9:sportscut/api.py`, but it MUST apply the two trims under Design §5. Nothing from that branch's web files or test files is copied.

## Context (checked on main 37f4067)
- `sportscut/api.py` (407 lines) has a module-level FastAPI `app` and these helpers:
  - `_data_dir()`, which reads `$SPORTSCUT_DATA_DIR` (default `sportscut-data`) and resolves it.
  - `_job_dir(job_id)`, which raises `_JobNotFound` unless job_id is a canonical lowercase UUID string.
  - `_load_job(job_id) -> (job_dir, job)`, which validates `job.json` and raises `_JobNotFound`.
  - `_write_job(path, job)`, an atomic write.
- api.py constants: `INPUT_NAME="input"`, `CLIPS_DIR="clips"`, `JOB_FILE="job.json"`, `CHUNK_BYTES`, `DEFAULT_MAX_UPLOAD_BYTES`.
- `POST /highlights` (`create_highlights`, lines 239-305) copies the upload inline at lines 265-273, with a chunked copy and a 413 limit from `$SPORTSCUT_MAX_UPLOAD_BYTES`.
- `GET /highlights/{job_id}/clips/{name}` (name `get_clip`) authorises the name against job.json before any path join. This task copies that pattern.
- `_validate_job` requires job.json keys to be exactly `{source_name, source_url, duration, version, segments}`. An empty `segments` list is valid.
- `sportscut/reel.py` (T-030):
  - `MANIFEST_NAME = "player.json"`.
  - `make_player_reel(video, query, out_dir, pre=3.0, post=2.0, merge_gap=4.0) -> dict` probes the video, then calls `player.find_touches(video, query)` through the module attribute, so it can be monkeypatched as `sportscut.player.find_touches`.
  - It writes `out_dir/player.json` and, if there are windows, `out_dir/player_<team>_<number>.mp4`.
  - It returns `{query, touches, clips, total_duration, reel}`, where `reel` is the mp4 file name or None.
- `sportscut/player.py`: `PlayerQuery(team, number)` normalises the team (case-insensitive named colour or `#rrggbb`) and requires an int from 1 to 99. Otherwise it raises ValueError. `Touch(t, team, number, confidence, bbox)`.
- Exception bases: `media.MediaError(RuntimeError)`. `media.require_ffmpeg()` raises MediaError when ffmpeg or ffprobe is missing.
- `tests/conftest.py` provides the session fixtures `require_ffmpeg` (skip reason 'ffmpeg and ffprobe are required on PATH') and `synthetic_video` (6 s mp4).

## Design (sportscut/api.py only)
1. **Imports and constant.** Change the package import to `from sportscut import export, media, pipeline, reel, sources` (a module import, so the reel stays monkeypatchable). Add `from sportscut.player import PlayerQuery` and `PLAYER_DIR = "player"`.
2. **DRY refactor, no behaviour change.** Add the helper below and replace the inline loop in `create_highlights` with `_save_upload(file, input_path)`:
```python
def _save_upload(file: UploadFile, path: Path) -> None:
    limit = int(os.environ.get("SPORTSCUT_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES))
    total = 0
    with path.open("wb") as destination:
        while chunk := file.file.read(CHUNK_BYTES):
            total += len(chunk)
            if total > limit:
                raise HTTPException(413, f"upload exceeds {limit} bytes")
            destination.write(chunk)
```
3. **`POST /players`**, a sync `def`:
```python
@app.post("/players")
def create_player_reel(
    request: Request,
    file: UploadFile | None = File(None),
    job_id: str | None = Form(None),
    team: str = Form(...),
    number: int = Form(...),
) -> dict[str, object]:
```
   FastAPI validation runs first: a missing team or number, or a non-int number, gives 422. Then the steps run in this order. Nothing is written and `find_touches` is not called before step d.
   a. `job_id = (job_id or "").strip() or None`. If `(file is None) == (job_id is None)`, raise `HTTPException(422, "send exactly one of file or job_id")`.
   b. `query = PlayerQuery(team, number)`. A ValueError gives `HTTPException(422, str(exc))`.
   c. **Existing job:** run `job_dir, _ = _load_job(job_id)` and set `input_path = job_dir / INPUT_NAME`. `_JobNotFound`, an OSError, or `input_path` not being a file gives `HTTPException(404, "not found")`.
   d. **New upload:** set `job_id = str(uuid.uuid4())`, `job_dir = _data_dir() / "jobs" / job_id`, run `job_dir.mkdir(parents=True)` and set `input_path = job_dir / INPUT_NAME`. Inside the try block below:
      - `_save_upload(file, input_path)`;
      - then `media.require_ffmpeg()`;
      - then `duration = media.probe_duration(input_path)`. A MediaError from the probe becomes `HTTPException(400, str(exc).replace(str(input_path), "upload"))`.
   e. `manifest = reel.make_player_reel(input_path, query, job_dir / PLAYER_DIR)`, with the T-030 defaults.
   f. New upload only, after e succeeds: `_write_job(job_dir / JOB_FILE, {"source_name": file.filename or "upload", "source_url": None, "duration": duration, "version": 0, "segments": []})`.
   g. Return:
```python
{"job_id": job_id, "touches": manifest["touches"],
 "reel_url": None if manifest["reel"] is None else str(request.url_for("get_player_reel", job_id=job_id, name=manifest["reel"]))}
```
   **Error mapping for d–f** (one `try/except Exception as exc` block):
   - for a NEW upload, first `shutil.rmtree(job_dir, ignore_errors=True)`;
   - then an `HTTPException` (413, or the 400 above) is re-raised;
   - `ValueError` gives 422 `str(exc)`;
   - `MediaError` or `OSError` gives 500 `"processing failed"`;
   - anything else is re-raised.
   For an EXISTING job, nothing outside `<job_dir>/player/` is ever written or deleted: not `input`, not `job.json`, not `clips/`.
4. **`GET /players/{job_id}/reel/{name}`**, with route `name="get_player_reel"`:
```python
@app.get("/players/{job_id}/reel/{name}", name="get_player_reel")
def get_player_reel(job_id: str, name: str) -> FileResponse:
```
   - Run `job_dir, _ = _load_job(job_id)`, then `m = json.loads((job_dir / PLAYER_DIR / reel.MANIFEST_NAME).read_text(encoding="utf-8"))`.
   - Require `isinstance(m, dict) and isinstance(m.get("reel"), str) and name == m["reel"]`. Only after that match is `path = job_dir / PLAYER_DIR / name` built, and it must be a file.
   - `_JobNotFound`, `OSError`, `json.JSONDecodeError`, `UnicodeError`, `TypeError` or a failed check gives `HTTPException(404, "not found")`.
   - Otherwise return `FileResponse(path, media_type="video/mp4")`.
5. **Trims compared with checkpoint 6231ac9** (YAGNI, and they fit the line budget):
   - (i) Do NOT add the extra `/players/{job_id}/reel/{name:path}` catch-all route. A name that contains `/` after decoding (e.g. `..%2Finput`) already fails to match `{name}` and gets Starlette's 404, the same as `get_clip` in T-005/T-007.
   - (ii) Do NOT add a `PipelineError` branch. `make_player_reel` never raises it.
   - Target: about 105–115 changed lines in api.py.

## Files to touch
- `sportscut/api.py`: `_save_upload`, `POST /players`, `GET /players/{job_id}/reel/{name}`. Budget is about 115 changed lines.
- `tests/test_players_api.py` (new, Developer): at most 110 lines.
- `tests/test_t034a_acceptance.py` (new, Tester): at most 150 lines.
- Docs: the orchestrator commits this spec and plan under `docs/superpowers/` plus the INDEX row.

Do NOT change:
- `sportscut/reel.py`, `sportscut/player.py`, `sportscut/pipeline.py`, `sportscut/evaluate.py`, `sportscut/eval_player.py`;
- `sportscut/web/*` (owned by T-041);
- `pyproject.toml`, `tests/conftest.py`, or any existing test file.

## Steps (TDD)
0. Precondition, which must print READY. Otherwise report BLOCKED with the missing item and change nothing:
   `test -f sportscut/api.py && grep -q '@app.post("/highlights")' sportscut/api.py && grep -q '"/highlights/{job_id}/source"' sportscut/api.py && grep -q 'def _load_job' sportscut/api.py && grep -q 'def make_player_reel' sportscut/reel.py && grep -q '^MANIFEST_NAME' sportscut/reel.py && echo READY || echo BLOCKED`
1. Baseline: run `python -m pytest -q` on the untouched tree and note the summary line.
2. Refactor `_save_upload` (Design §2). Run `python -m pytest -q tests/test_api.py tests/test_t005_acceptance.py tests/test_t006_acceptance.py tests/test_t007_acceptance.py`. It must stay green; no test is changed.
3. Write the failing test for the upload path: AC1 + AC2 + AC3 in one test, with `find_touches` monkeypatched. Watch it fail with 404 or 405. Then implement `POST /players` (new-upload path) and `get_player_reel`.
4. Write the failing parametrized AC8 test (reel 404 matrix), then fix until green.
5. Write the failing AC4 test (existing job created by POST /highlights with `pipeline.run` monkeypatched to return `[]`). Then implement the job_id path.
6. Write the AC5 test (zero touches).
7. Write the parametrized AC6 (422) and AC7 (404) tests and the AC9 error/cleanup tests, then fix until green.
8. Size and scope check (AC13, AC14). If over budget, compact the tests (parametrize, shared helpers). Never weaken an AC.
9. Run the full verification below and quote the summary lines.

## Verify
- `python -m pytest -q` reports 0 failed and 0 errors (quote the summary line).
- `python -m pytest -q tests/test_players_api.py tests/test_t034a_acceptance.py tests/test_api.py tests/test_t005_acceptance.py tests/test_t006_acceptance.py tests/test_t007_acceptance.py`
- `git diff --numstat main...HEAD -- . ':(exclude)docs/superpowers' | awk '{s+=$1+$2} END {print s}'` prints a number < 380.
- `git diff --name-only main...HEAD -- . ':(exclude)docs/superpowers'` lists only sportscut/api.py, tests/test_players_api.py and tests/test_t034a_acceptance.py.
- `git diff --exit-code main...HEAD -- sportscut/reel.py sportscut/player.py sportscut/pipeline.py sportscut/evaluate.py sportscut/eval_player.py sportscut/web pyproject.toml tests/conftest.py` exits 0.
- Eval: accuracy is not touched, so there is no F1 gate.

## Coordination
T-012 (ranking filters) also edits `sportscut/api.py`. If it merges first, rebase onto it and keep the `/players` code as separate new functions next to the existing routes. The orchestrator serialises the two tasks through the shared file.

## Assumptions
- A new upload through POST /players becomes a full T-007 job with `segments: []` and version 0. Highlight detection is NOT run, but the job works with the T-007 routes (`GET /highlights/{id}`, `/source`).
- POST /players accepts only a file or a job_id; a YouTube URL is not accepted. Users create a job via POST /highlights with the URL first, then reuse its job_id.
- Each POST /players on a job overwrites `player/player.json`. Only the latest query's reel is downloadable, and older reel files are not cleaned up.
- pre/post/merge_gap are not exposed; the T-030 defaults (3/2/4) apply.
- The real `detect_touches` still returns []. Until T-031..T-033 land, real requests give 200 with zero touches and `reel_url: null`.

## Test plan

- Shared setup in each new module: `pytest.importorskip("fastapi")`, a module-level `client = TestClient(app)`, and an autouse fixture that runs `monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))` and `monkeypatch.delenv("SPORTSCUT_MAX_UPLOAD_BYTES", raising=False)`. The data dir is per test, so job-dir counts are exact. Tests that need real media request the conftest `synthetic_video` fixture (which skips cleanly without ffmpeg, per T-039). Monkeypatch `"sportscut.player.find_touches"` with a fake that records (Path(video), query) calls. Use one small `_post(...)` helper and one `_jobs(root)` helper to stay inside the line budget.
- tests/test_players_api.py::test_upload_builds_reel_job_and_download covers AC1 + AC2 + AC3 in one flow: POST, then job.json, then GET /highlights/<id> and /source, then GET reel_url (pass the absolute URL to TestClient) with bytes and probe_duration > 0.
- tests/test_players_api.py::test_existing_job_is_reused covers AC4: create the job via POST /highlights with `monkeypatch.setattr(pipeline, "run", lambda *a, **k: [])`, write a sentinel into clips/, snapshot, POST /players with job_id, and assert nothing changed.
- tests/test_players_api.py::test_zero_touches covers AC5.
- tests/test_players_api.py::test_rejects_bad_request covers AC6 with @pytest.mark.parametrize over the 9 cases (data dict + whether a file is sent). The fake find_touches calls pytest.fail.
- tests/test_players_api.py::test_unknown_job_is_404 covers AC7 with @pytest.mark.parametrize (fresh uuid4, uppercase existing id, '../etc'). For the uppercase case, create a job.json directly on disk under <data_dir>/jobs/<id>/ instead of running ffmpeg.
- tests/test_players_api.py::test_reel_route_rejects covers AC8 with @pytest.mark.parametrize over the 6 cases. Build the fixture job on disk (valid job.json, an input file, player/player.json with reel 'player_red_10.mp4' and that file with dummy bytes), so this test needs no ffmpeg.
- tests/test_players_api.py::test_errors_and_cleanup covers AC9 (a)–(e). It may be split into 2–3 small tests. (a) needs `synthetic_video` only for the ffmpeg skip; (c) builds the existing job on disk.
- Tester: tests/test_t034a_acceptance.py, at most 150 lines, written independently from the ACs (not copied from the Developer file or from 6231ac9:tests/test_t034_acceptance.py). It covers AC1–AC9 with parametrize for the AC6, AC7 and AC8 matrices and one shared module-level fixture for the synthetic upload with a monkeypatched find_touches. It does not re-test POST /highlights behaviour that the T-005/T-007 suites already cover. The Tester confirms that at least one test fails under a mutation (e.g. reel_url forced to None, or get_player_reel joining the name before the manifest check) and restores the code afterwards.
- Regression and guardrails: `python -m pytest -q` (whole suite, 0 failed), the numstat total < 380 (AC14) and the protected-file `git diff --exit-code` (AC13). The Tester runs the numstat before reporting; going over its 150-line budget is a Tester fix (compact), not a Developer blocker.
