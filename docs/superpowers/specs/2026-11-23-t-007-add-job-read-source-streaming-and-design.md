# T-007: Add job read, source streaming and manual segment edit endpoints

Request R-002. Plan: `docs/superpowers/plans/2026-11-23-t-007-add-job-read-source-streaming-and.md`.

## Product Owner request

API + web upload: POST /highlights nhận video hoặc link YouTube, trả về danh sách đoạn highlight, có trang xem trước và chỉnh mốc cắt bằng tay.

## Goal

Persist each job as `jobs/<uuid>/job.json` (source name or URL, duration, segments with clip names). Add `GET /highlights/{job_id}`, which returns that job, and `GET /highlights/{job_id}/source`, which serves the input video with HTTP Range support so a browser `<video>` can seek. Add `PUT /highlights/{job_id}/segments`, which takes the full edited list of `{start, end}` (plus optional `reason`), validates 0 ≤ start < end ≤ duration and at most 50 segments (400/422 otherwise), re-cuts the clips with `export_clips`, rewrites the manifest and returns the same shape as POST. New clip files get a version suffix so browsers do not show stale cached clips. Tests on the synthetic video: an edit changes clip durations to match the new marks within 0.5 s; invalid ranges, unknown or non-UUID job ids and path traversal are rejected; a Range request returns 206. Assumptions: manual edits overwrite the previous version (no undo history), and edited segments keep score null and reason 'manual' when added by the user; feeding edits back as eval labels is out of scope. Like task 1, it requires R-001's T-005 on main.

## Acceptance criteria

- AC1: Step 0 prints `READY` on the task base, proving both T-005 and T-006 prerequisites are present; no prerequisite module is recreated.
- AC2: A successful upload POST persists job.json with exactly source_name, source_url, duration, version and segments; source_name is the submitted filename (or `upload` when empty), source_url is null, duration equals probe_duration(input), version is 0, and segments equals clips/highlights.json. A URL POST stores source_name null and the submitted source_url.
- AC3: Successful POST returns exactly {job_id, source_name, source_url, duration, highlights}; each highlight has exactly {start,end,score,reason,clip_url}. Existing upload and URL detection, error, cleanup and clip-download tests remain green after their expected response/job schema assertions are updated.
- AC4: GET /highlights/{job_id} for a completed upload or URL job returns 200 and exactly the same canonical response as POST, including absolute current clip URLs. A canonical unknown UUID, non-UUID, uppercase UUID, missing/malformed job.json or malformed persisted segment returns 404 with detail `not found`.
- AC5: GET /highlights/{job_id}/source without Range returns 200 video/mp4, Accept-Ranges `bytes`, exact Content-Length and bytes equal to the stored input.
- AC6: Source requests `bytes=2-5`, `bytes=2-`, and `bytes=-4` return 206 with the exact requested bytes, correct Content-Range and Content-Length. An end beyond EOF is clamped. Malformed units, multiple ranges, zero suffix and starts at/after EOF return 416 with `Content-Range: bytes */<total>`.
- AC7: Source requests with non-UUID, uppercase UUID, unknown UUID, missing input, encoded traversal in job_id, or extra path components return 404 and never return input, job.json or manifest contents.
- AC8: PUT accepts exactly `{"segments":[{"start":float,"end":float,"reason":optional-string},...]}`. More than 50 items, non-finite/type-invalid values, extra fields, or any violation of `0 <= start < end <= duration` returns 422 before export and leaves job.json, manifest and clip bytes unchanged.
- AC9: A PUT replacing segments on synthetic_video returns 200 in the canonical POST shape. Persisted and returned items are sorted by `(start,end)`, have score null, use a supplied non-empty reason or `manual`, and their clip durations match `end-start` within 0.5 seconds.
- AC10: The first successful edit increments version 0 to 1 and creates names `clip_01_v1.mp4`, etc.; a second edit increments to 2 and uses `_v2`. After success, the manifest and job segments agree, old clip URLs return 404, and current clip URLs return 200 video/mp4.
- AC11: PUT with an empty segments list succeeds, increments the version, writes empty segments and `[]` manifest, returns empty highlights, and makes every previous clip URL return 404.
- AC12: A non-UUID, uppercase UUID, unknown UUID, encoded traversal attempt or missing/malformed job returns 404 from PUT without calling export or changing any filesystem content.
- AC13: If re-cutting raises MediaError, PUT returns 500 `processing failed`; any partial next-version files are removed and the old GET response, job.json, manifest and clip URLs still work. An unexpected exception likewise preserves the previous job and propagates under TestClient.
- AC14: `export_clips(..., version_suffix="_v3")` creates and manifests versioned names while an omitted suffix preserves exact T-003 names. Invalid suffixes raise `ValueError("invalid version suffix")` before output creation. `Segment.score=None` serializes as JSON null while numeric score behavior is unchanged.
- AC15: README documents job GET, ranged source playback and full-list PUT replacement. T-003, T-005 and T-006 design specs contain `Updated by T-007` sections reflecting the changed contracts.
- AC16: `.venv/bin/python -m pytest -q tests/test_models.py tests/test_export.py tests/test_api.py tests/test_t007_acceptance.py -rs` and `.venv/bin/python -m pytest -q` both report 0 failed; the acceptance run has 0 skipped when ffmpeg/ffprobe are on PATH.

## Out of scope

- The upload/preview/edit web page; this task supplies the HTTP primitives it will consume.
- Undo history, edit history, optimistic concurrency, ETags or conflict detection.
- Feeding manual edits into eval labels or changing highlight detection/ranking/F1.
- Partial/PATCH-style edits, stable segment IDs, preserving detector scores by matching edited timestamps, or reordering without replacement.
- Multiple HTTP byte ranges, multipart/byteranges responses, transcoding the source, content-type sniffing or non-MP4 source normalization.
- Async/background re-cutting, job status/progress, cancellation or queues.
- Authentication, authorization, CORS, rate limiting, retention/cleanup jobs or DELETE endpoints.
- Changing YouTube validation/download limits, pipeline.run, detector behavior, codecs or ffmpeg performance settings.

## Decisions

- T-007 depends on both T-005 and T-006 and must restart from their merged base. Step 0 must print READY; otherwise the task stops without recreating prerequisite code.
- job.json becomes the durable full job manifest with source_name/source_url, duration, version and manifest-equivalent segments; this replaces T-006's one-field job.json.
- POST, GET job and PUT edit use one canonical response shape, extending T-005/T-006 POST responses with source_name, source_url and duration.
- All UUID path parameters must be canonical lowercase UUID strings. Invalid, unknown, malformed and traversal-shaped jobs are indistinguishable 404 `not found` responses.
- Upload filenames are stored only as inert metadata and are never used to derive filesystem paths.
- Source Range support is implemented explicitly with bounded streaming so behavior does not depend on the Starlette version. Only one byte range is supported.
- All request-shape and edit-bound failures return 422; missing/invalid jobs return 404; re-cut MediaError returns the existing fixed 500 `processing failed`.
- PUT replaces the entire segment list. Empty replacement is valid; at most 50 segments are accepted; overlaps and adjacency are allowed.
- Every submitted PUT segment is manual because the request has no stable IDs: score is null, a missing/empty reason becomes `manual`, and a non-empty supplied reason is retained.
- export_clips gains only a backward-compatible keyword-only version_suffix. Default output remains T-003-compatible; edit output uses `_vN` to avoid stale browser caches.
- A successful edit increments a persisted integer version. Failed validation or export does not increment it or alter the active job.
- The previous job remains readable throughout re-cutting. New version names prevent partial cuts from overwriting active clips; job JSON is written atomically and partial new-version files are cleaned on failure.
- After a successful replacement, authorization against current job segments makes old clip URLs return 404. Old physical files are removed after the new job/manifest is active; no undo history is retained.
- Segment.score is widened to float|null solely to represent manual edits; detector-generated segments continue using numeric scores.
- This task does not touch accuracy, so no eval/F1 gate is added.
- Tech Lead (dev_blocked): T-007 is correctly blocked by missing prerequisite code; restart it from the latest base only after T-005 and T-006 merge, because T-006 also changes POST /highlights and should precede T-007 to avoid conflict.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-003-export-segments-as-mp4-clips-plus-design.md`
- `docs/superpowers/specs/2026-11-23-t-005-expose-post-highlights-over-http-with-design.md`
- `docs/superpowers/specs/2026-11-23-t-006-accept-a-youtube-link-as-post-design.md`
