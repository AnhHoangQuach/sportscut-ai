# T-009: Build the preview page with manual cut-point editing

Request R-002. Plan: `docs/superpowers/plans/2026-11-23-t-009-build-the-preview-page-with-manual.md`.

## Product Owner request

API + web upload: POST /highlights nhận video hoặc link YouTube, trả về danh sách đoạn highlight, có trang xem trước và chỉnh mốc cắt bằng tay.

## Goal

Add `GET /jobs/{job_id}`, which serves `preview.html`; its JS loads `GET /highlights/{job_id}` and shows the source video player plus a segment list. Clicking a segment seeks and plays it. Each row has start/end inputs (mm:ss.s), 'set start/end = current time' buttons, ±0.5 s nudges and delete, with an 'add segment at current time' button and a Save button that calls `PUT /highlights/{job_id}/segments` and then refreshes the clip links/players. Client-side validation mirrors the server rules, but the server stays the source of truth. Tests: TestClient serves the page for an existing job and returns 404 for unknown ids; an end-to-end API test drives the same sequence the page uses (POST synthetic video → GET job → PUT edited marks → download a re-cut clip, check its duration); the JS time-format helpers are kept in a small pure module so they can be reviewed easily. Add a README section with `pip install -e '.[api,youtube]'`, `sportscut serve` and screenshots-free usage steps. Assumption: no timeline/waveform widget (YAGNI); inputs plus player controls are enough for manual adjustment.

## Acceptance criteria

- AC1: For a job directory with a valid job.json under SPORTSCUT_DATA_DIR, `GET /jobs/{job_id}` via TestClient returns 200 with Content-Type starting `text/html`, and the body is `sportscut/web/preview.html` (contains `<!doctype html>`, `id="player"`, `id="segments"`, `id="save"`, `id="add-segment"`).
- AC2: `GET /jobs/{id}` returns 404 with JSON `{"detail": "not found"}` for a random unknown lowercase UUID, the uppercase form of an existing job's UUID, `not-a-uuid`, and an existing UUID directory without job.json or with invalid job.json. The route is not in the OpenAPI schema (`/jobs/{job_id}` is absent from `app.openapi()["paths"]`).
- AC3: preview.html is `lang="vi"` and references, in order, `/static/style.css`, `/static/timefmt.js` (defer) and `/static/preview.js` (defer). It contains `#player` (video with controls), `#current-time`, `ol#segments`, `template#segment-row` with elements of classes `play`, `start`, `end`, `start-minus`, `start-plus`, `end-minus`, `end-plus`, `set-start`, `set-end`, `delete`, `clip`, `clip-player`, the buttons `#add-segment` and `#save`, initially hidden `#status[role=status]` and `#error[role=alert]`, and a link back to `/`. `GET /static/preview.js` and `GET /static/timefmt.js` return 200 with a JavaScript content type.
- AC4: The `timefmt.js` exports, loaded with Node `require`, return exactly the contract values in the spec: formatTime (`0→00:00.0`, `5→00:05.0`, `0.04→00:00.0`, `65.25→01:05.3`, `59.96→01:00.0`, `600→10:00.0`, `5400→90:00.0`, `10800→180:00.0`, and RangeError for -1, NaN and Infinity); parseTime (`01:05.3→65.3`, `1:05→65`, `90:00.0→5400`, `75.5→75.5`, `' 00:02.5 '→2.5`, and null for `1:60`, ``, `abc`, `-1`, `1:2:3`, `1e3`, `00:05,5` and a non-string); clampTime (`(-0.3,6)→0`, `(6.4,6)→6`, `(2.5,6)→2.5`); newSegmentAt (`(3,90)→3..13`, `(85,90)→85..90`, `(90,90)→80..90`, `(2,6)→2..6`, `(6,6)→0..6`, all with reason `manual`); and `MAX_SEGMENTS === 50`, `NEW_SEGMENT_SECONDS === 10`.
- AC5: `validateSegments` mirrors the server rules: `[]` for an empty list, for overlapping or adjacent valid segments, and for `end == duration`; `['Đoạn 1: cần 0 ≤ đầu < cuối ≤ 00:06.0.']` for `[{start:3,end:3}]` with duration 6 (and likewise for start<0, start>end and end>duration); `['Đoạn 2: thời gian không hợp lệ.']` when row 2 has a NaN or non-number start/end; and a result containing `Tối đa 50 đoạn.` for 51 valid segments, while exactly 50 valid segments returns `[]`.
- AC6: `timefmt.js` is pure: its source contains none of `document`, `window`, `fetch`, `localStorage` or `XMLHttpRequest`. It sets `globalThis.SportsCutTime` and `module.exports` to the same object, and loading it in Node prints no output and throws nothing.
- AC7: The `preview.js` source contains `/^\/jobs\/([^/]+)\/?$/`, ``fetch(`/highlights/${encodeURIComponent(jobId)}`)``, ``/highlights/${encodeURIComponent(jobId)}/source``, ``fetch(`/highlights/${encodeURIComponent(jobId)}/segments`, {``, `method: "PUT"`, `"Content-Type": "application/json"`, `({ start, end, reason })`, `T.validateSegments(segments, duration)`, `T.newSegmentAt(player.currentTime, duration)`, `T.clampTime(`, `T.parseTime(`, `T.formatTime(`, `player.play()`, `player.pause()`, `data?.detail`, ``Lỗi ${response.status}: ${message}``, `save.disabled = true`, `save.disabled = false`, `finally`, `Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ.`, `Đã lưu`, and no `http://` or `https://`. The Save handler returns before `fetch` when validation finds problems (the `T.validateSegments(` check comes textually before the PUT `fetch(` in the same handler).
- AC8: End-to-end with TestClient and `synthetic_video` (ffmpeg present), following the page's own sequence: POST /highlights (file, top=1, min_len=0.5, max_len=1.0) → 200; GET /jobs/{id} → 200 text/html; GET /highlights/{id} → 200 with the same highlights as the POST; GET /highlights/{id}/source with `Range: bytes=0-99` → 206; PUT /highlights/{id}/segments with `{"segments":[{"start":1.0,"end":3.5,"reason":<the first returned highlight's reason>},{"start":4.0,"end":5.5,"reason":"manual"}]}` → 200 with highlights (1.0,3.5) and (4.0,5.5) whose clip_urls end `clip_01_v1.mp4` and `clip_02_v1.mp4`; each clip_url download returns 200 and, written to a temp file, has `media.probe_duration` ≈ 2.5 and ≈ 1.5 (abs 0.5); the original POST clip_url now returns 404; GET /jobs/{id} still returns 200.
- AC9: README.md contains a section headed `## Trang web: tải lên, xem trước và chỉnh mốc cắt` that includes `pip install -e '.[api,youtube]'`, `sportscut serve`, `http://127.0.0.1:8000/`, `/jobs/JOB_ID`, `mm:ss.s` and `Lưu`, with no image links (`grep -n '!\[' README.md` finds nothing in the section).
- AC10: No change under `agent-office/`, `pyproject.toml`, `sportscut/web/index.html`, `sportscut/web/app.js`, or any existing test file (`git diff --name-only main...HEAD` lists only the files in `files` plus docs/superpowers). No new runtime dependency, CDN, npm or build step. `.venv/bin/python -m pytest -q tests/test_preview.py tests/test_t009_acceptance.py -rs` reports 0 failed and 0 skipped where node, ffmpeg and ffprobe are on PATH, and `.venv/bin/python -m pytest -q` reports 0 failed.

## Out of scope

- Timeline, waveform, thumbnails, drag handles or keyboard shortcuts for scrubbing.
- Undo/redo, edit history, unsaved-change warnings, or autosave.
- Editing `reason`/`event` labels or scores in the UI (reasons are passed through unchanged; new rows use 'manual').
- Any change to the PUT/GET/POST/source/clip API behaviour, validation rules or response shape.
- Async jobs, progress polling during upload or re-cut, cancellation.
- Concatenated reel export or download of all clips as a zip.
- Auth, multi-user locking, CORS, deployment.
- Browser automation tests (Playwright/Selenium) or adding Node/npm as a product or CI dependency.
- Changing index.html/app.js (the upload page) or pyproject packaging.
- Job listing page or job deletion.

## Decisions

- T-009 (R-002): `GET /jobs/{job_id}` serves the static `sportscut/web/preview.html` via FileResponse after `_load_job` succeeds. Unknown, invalid or non-canonical ids return the same 404 `not found` as the T-007 endpoints. The route is excluded from the OpenAPI schema like `GET /`.
- T-009 (R-002): The preview page is static (no templating). Its JS takes the job id from `location.pathname` and loads data only through the existing public API (GET /highlights/{id}, /source, PUT /segments, clip URLs).
- T-009 (R-002): Time helpers live in the pure, DOM-free classic script `sportscut/web/timefmt.js`, exposed as `globalThis.SportsCutTime` and `module.exports`. preview.js holds all DOM/fetch logic.
- T-009 (R-002): The display format is `mm:ss.s`: minutes at least 2 digits and uncapped, rounded to the nearest tenth (59.96 → 01:00.0). Input also accepts `m:ss[.f]` and plain seconds. Parsed values are rounded to milliseconds.
- T-009 (R-002): Client state keeps exact second values. Inputs only display them rounded to tenths, and only a typed value is re-parsed, so untouched segments are sent back exactly as the server returned them.
- T-009 (R-002): Client validation mirrors the server (≤50 segments, finite numbers, 0 ≤ start < end ≤ duration, overlaps allowed, empty allowed) only to skip pointless requests. The server stays the source of truth and its errors are shown as `Lỗi <status>: <message>`.
- T-009 (R-002): Save sends only `{start, end, reason}` per segment, because the server forbids extra keys. Existing reasons are passed through, new rows use reason `manual`, and the list is re-rendered from the PUT response so clip links/players show the new versioned URLs.
- T-009 (R-002): 'Add segment at current time' creates a 10 s segment clamped to the video, shifted to end at the video's end when the current time is at the end. Nudges are ±0.5 s clamped to [0, duration].
- T-009 (R-002): Clicking a segment seeks to its start, plays, and pauses at its end (timeupdate check).
- T-009 (R-002): Node runs only in the tests, to execute timefmt.js. These tests skip with reason 'node is required on PATH' when node is absent, and the product needs no Node, npm or build step (T-008 AC10 still holds).
- T-009 (R-002): No pyproject change is needed, because the existing `web/*.html`/`web/*.js`/`web/*.css` package-data globs already ship the new files.
- T-009 (R-002): The task does not touch detection accuracy, so no eval/F1 gate applies.

## Existing specs this task changes

- (none)
