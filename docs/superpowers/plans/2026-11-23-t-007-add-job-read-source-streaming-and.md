# Plan T-007: Add job read, source streaming and manual segment edit endpoints

Design: `docs/superpowers/specs/2026-11-23-t-007-add-job-read-source-streaming-and-design.md`.

## Implementation plan

# T-007: Add job read, source streaming and manual segment edit endpoints

## Context and dependency gate

T-007 extends the T-005/T-006 FastAPI implementation. It must start only after both are present on the task base.

Run first:

```bash
test -f sportscut/api.py && grep -q '^def run(' sportscut/pipeline.py && grep -q '@app.post("/highlights")' sportscut/api.py && grep -q 'download_youtube' sportscut/api.py && grep -q 'source_url' sportscut/api.py && echo READY || echo BLOCKED
```

Proceed only when this prints `READY`. If it prints `BLOCKED`, stop and report the technical blocker. Do not recreate `api.py`, `export.py`, `pipeline.run`, or the T-006 source implementation.

## Goal

Persist enough metadata to reopen a completed job, expose the original video with byte-range seeking, and let a client replace all highlight marks and synchronously re-cut the clips. Upload and YouTube jobs use the same read/edit API.

## Persistent job format

Every successful POST writes `<data>/jobs/<canonical-lowercase-uuid>/job.json` as UTF-8 JSON with `indent=2` and a trailing newline:

```json
{
  "source_name": "match.mp4",
  "source_url": null,
  "duration": 90.0,
  "version": 0,
  "segments": [
    {
      "start": 14.0,
      "end": 26.0,
      "score": 5.2,
      "reason": "audio peak z=5.2",
      "file": "clip_01.mp4"
    }
  ]
}
```

For an upload, `source_name` is `UploadFile.filename` or `"upload"` when it is empty, and `source_url` is null. For a URL job, `source_name` is null and `source_url` is the accepted URL. `duration` is `media.probe_duration(<job>/input)`. `version` starts at 0 and increments after each successful PUT. `segments` equals `clips/highlights.json` after each successful POST or PUT.

The filename is metadata only. It is never resolved, joined to a filesystem path, or echoed into a response header.

## Canonical response

POST, GET and PUT return the same shape:

```json
{
  "job_id": "canonical-lowercase-uuid",
  "source_name": "match.mp4",
  "source_url": null,
  "duration": 90.0,
  "highlights": [
    {
      "start": 14.0,
      "end": 26.0,
      "score": 5.2,
      "reason": "audio peak z=5.2",
      "clip_url": "http://testserver/highlights/<job_id>/clips/clip_01.mp4"
    }
  ]
}
```

The keys are exactly `job_id`, `source_name`, `source_url`, `duration`, and `highlights`. Highlight keys remain exactly `start`, `end`, `score`, `reason`, and `clip_url`. This deliberately extends T-005/T-006's POST response with source metadata and duration; update their design specs and existing assertions accordingly.

Add private API helpers with these contracts:

```python
def _job_dir(job_id: str) -> Path: ...
def _load_job(job_id: str) -> tuple[Path, dict[str, object]]: ...
def _write_job(path: Path, job: dict[str, object]) -> None: ...
def _job_response(request: Request, job_id: str, job: dict[str, object]) -> dict[str, object]: ...
```

`_job_dir` accepts only `job_id` satisfying `str(uuid.UUID(job_id)) == job_id`; otherwise it raises the same internal not-found condition used for a missing job. `_load_job` reads only the fixed `<data>/jobs/<validated-id>/job.json`, validates the required top-level fields and segment fields sufficiently to avoid uncaught errors while building a response, and treats a missing, malformed, or inconsistent job as 404. No user-controlled string is joined to a path before canonical UUID validation.

## POST persistence changes

After `pipeline.run` succeeds, call `media.probe_duration(input_path)`, build the full job object above from the returned manifest entries, write it to `job.json`, and return `_job_response(...)`. Do not leave the old one-field T-006 job file. If probing or writing fails, preserve the existing cleanup/error behavior: the incomplete job directory is removed.

Call `media.probe_duration` through the `sportscut.media` module so tests can monkeypatch it. Detection, pipeline arguments and initial clip names remain unchanged.

## GET /highlights/{job_id}

Add:

```python
@app.get("/highlights/{job_id}")
def get_highlights(request: Request, job_id: str) -> dict[str, object]: ...
```

It loads `job.json` and returns `_job_response`. A non-canonical UUID, unknown UUID, missing job file, malformed job JSON, or malformed persisted segment returns 404 with `{"detail":"not found"}`.

## GET /highlights/{job_id}/source

Add:

```python
@app.get("/highlights/{job_id}/source")
def get_source(request: Request, job_id: str): ...
```

It validates and loads the job before opening the fixed `<job>/input`. Missing or invalid jobs and missing inputs return 404 `not found`.

Serve `video/mp4` with `Accept-Ranges: bytes`. Without a Range header return 200, the complete bytes, and the exact `Content-Length`. Support one RFC-style byte range in each of these forms: `bytes=START-END`, `bytes=START-`, and `bytes=-SUFFIX_LENGTH`. A satisfiable range returns 206 with the selected bytes, `Content-Range: bytes START-END/TOTAL`, and the selected `Content-Length`. End values beyond EOF are clamped. Reject malformed units, multiple ranges, empty/negative values, zero suffix length, and unsatisfiable starts with 416 plus `Content-Range: bytes */TOTAL`. Stream in bounded chunks; do not read the whole source into memory. Do not rely on the installed Starlette version to implement Range behavior.

## PUT /highlights/{job_id}/segments

Define request models in `sportscut/api.py`:

```python
class SegmentEdit(BaseModel):
    start: float
    end: float
    reason: str | None = None

class SegmentEdits(BaseModel):
    segments: list[SegmentEdit]
```

Use finite-float validation. The JSON body is exactly an object with `segments`; configure both models to reject extra fields. FastAPI/Pydantic structural/type failures return 422. The endpoint also returns 422 when there are more than 50 segments or any item violates `0 <= start < end <= job.duration`. Empty lists are valid and replace the current list with no highlights. Overlap, adjacency and input order are allowed; `export_clips` retains its established sort by `(start, end)`.

For every submitted segment create `Segment(start, end, score=None, reason=reason or "manual")`. An empty string reason is treated as absent and becomes `manual`; a non-empty supplied reason is retained. Because edits contain no stable segment identity, every submitted item is considered manually supplied; previous detector score/reason values are not inferred by matching times.

Call:

```python
export.export_clips(input_path, edited_segments, clips_dir, version_suffix=f"_v{next_version}")
```

through the `sportscut.export` module. `next_version = job["version"] + 1`. A first edit therefore produces `clip_01_v1.mp4`, a second `clip_01_v2.mp4`, and so on. On successful export, read the rewritten `clips/highlights.json`, update `job.json` with the new version and segments, remove clip files referenced only by the previous manifest, and return `_job_response`. Old clip URLs must return 404 immediately after success because clip access is authorized against the current manifest/job segments.

Validation completes before invoking ffmpeg or modifying any manifest. Versioned output means an export failure cannot overwrite the currently served clip files. `export_clips` writes its manifest only after every cut succeeds; if it raises `MediaError`, remove any new-version files, leave the previous manifest/job/clip set usable, and return 500 `processing failed`. Unexpected exceptions similarly remove only new-version artifacts, preserve the old job, and propagate under TestClient as existing unexpected failures do. Write the new job file atomically using a sibling temporary file plus `os.replace`; never expose partial JSON.

## export_clips extension

Change the signature compatibly:

```python
def export_clips(
    video: str | Path,
    segments: list[Segment],
    out_dir: str | Path,
    *,
    version_suffix: str = "",
) -> list[Path]: ...
```

The suffix must either be empty or match `^_v[1-9][0-9]*$`; otherwise raise `ValueError("invalid version suffix")` before creating output. Names become `clip_{index:02d}{version_suffix}.mp4`. Existing callers that omit the keyword keep the exact T-003 behavior and names.

## Segment model extension

Change `Segment.score` to `float | None`. `to_dict()` emits JSON null for `None`, otherwise the existing native float. Existing detector/export behavior remains unchanged because detected segments still supply floats.

## Clip authorization

Update `GET /highlights/{job_id}/clips/{name}` to validate the canonical job and authorize `name` only when it exactly equals a current `job.json` segment `file`. Only after that comparison may it join `clips_dir / name`. This preserves T-005 traversal protection and makes old-version URLs return 404. `input`, `job.json`, `highlights.json`, encoded slashes and arbitrary filenames remain inaccessible.

## Documentation

Update README's API HTTP section with GET job, ranged source playback and the PUT JSON example. State that PUT replaces the complete segment list, supports at most 50 items, and has no undo history.

Append `Updated by T-007` sections to the T-003, T-005 and T-006 design specs describing the compatible export suffix, expanded job manifest/response, read/source/edit endpoints, and replacement of T-006's one-field job JSON.

## Ordered TDD implementation plan

1. Run Step 0 and proceed only on `READY`.
2. Add model tests proving `Segment(..., score=None, ...).to_dict()` emits null; run them red, then minimally update `sportscut/models.py`.
3. Add export tests for `_v1` names/manifest and invalid suffix; run red, then extend `export_clips` without changing default behavior.
4. Add POST persistence/response tests with `pipeline.run` and `media.probe_duration` stubbed; run red, then add atomic job writing and canonical response helpers.
5. Add GET job tests for upload and URL jobs plus invalid UUID, unknown UUID and malformed job data; run red, then implement the endpoint and validated loader.
6. Add source tests for full 200, the three valid Range forms, clamping and 416 cases, plus UUID/traversal rejection; run red, then implement bounded streaming.
7. Add PUT validation tests first: schema/type/non-finite/extra-field errors, bounds, duration limit, 51 items, unknown IDs, traversal and no-export assertions. Implement request models and pre-export validation.
8. Add PUT success tests on `synthetic_video`: replacement response/manifest/job JSON, null scores, manual/custom reasons, version names, old URL rejection, second edit version increment, empty replacement and clip durations. Run red, then implement re-cut and persistence.
9. Add failure-atomicity tests by making `export_clips`/media cutting fail after creating a new-version artifact; implement cleanup so the prior GET response and clips remain available.
10. Update README and the three related design specs. Update existing T-005/T-006 API assertions only where the intentional response/job schema changed; do not weaken their security or source behavior assertions.
11. Run all verification commands and inspect their summaries.

## Verification

```bash
.venv/bin/python -m pytest -q tests/test_models.py tests/test_export.py tests/test_api.py tests/test_t007_acceptance.py -rs
.venv/bin/python -m pytest -q
```

Both commands must report 0 failed. The task does not alter detection or ranking, so no eval/F1 command is required. The integration test must use `media.probe_duration` to prove each edited clip duration differs from its requested `end-start` by at most 0.5 seconds.

## Test plan

- Unit tests in tests/test_models.py: add `test_segment_allows_null_score` and retain numeric serialization/temporal validation tests.
- Integration/unit tests in tests/test_export.py: add `test_export_clips_version_suffix`, `test_export_clips_rejects_invalid_version_suffix`, and verify the default naming/manifest tests remain unchanged.
- Integration tests in tests/test_api.py: update the shared real-job fixture assertions for the expanded response and full job.json, then add `test_get_highlights_returns_persisted_job` and URL-source coverage.
- Integration tests in tests/test_api.py: add parametrized GET rejection tests for invalid/uppercase/unknown UUID, malformed or missing job.json, malformed segment data and path traversal.
- Integration tests in tests/test_api.py: add `test_source_full_response`, parametrized valid Range tests for closed/open/suffix/clamped ranges, parametrized 416 tests, and missing/invalid/traversal tests. Use a small known byte input for exact header/body assertions.
- Integration tests in tests/test_api.py: add parametrized PUT schema and semantic validation tests covering missing segments, extra fields, wrong types, NaN/infinity, negative/equal/reversed/out-of-duration bounds, 51 items and valid 50 items; spy on export and compare pre/post files.
- Integration tests in tests/test_api.py: add `test_put_segments_recuts_synthetic_video` using synthetic_video and probe_duration, asserting requested durations within 0.5 seconds, sorted output, null scores, default/custom reasons, versioned names, canonical response and persisted manifest/job equality.
- Integration tests in tests/test_api.py: add `test_put_segments_second_version_and_old_urls_404` and `test_put_empty_segments_replaces_all`.
- Integration tests in tests/test_api.py: add failure-atomicity tests for MediaError and unexpected exceptions, including a fake partial `_vN` artifact and assertions that previous files and GET responses remain usable.
- Independent Tester file tests/test_t007_acceptance.py: create its own jobs through POST, independently cover AC2-AC14 from public HTTP behavior, and include a mutation check proving at least one Range/edit acceptance test fails when Range handling or duration-bound validation is deliberately disabled, then restore the implementation.
- Regression: run the complete suite and confirm T-005/T-006 source validation, URL downloads, upload limits, clip traversal protection, CLI imports and pipeline tests remain green.
