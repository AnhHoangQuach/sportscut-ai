# Plan T-009: Build the preview page with manual cut-point editing

Design: `docs/superpowers/specs/2026-11-23-t-009-build-the-preview-page-with-manual-design.md`.

## Implementation plan

# T-009: Preview page with manual cut-point editing

Request R-002. PO request: "API + web upload: POST /highlights nhận video hoặc link YouTube, trả về danh sách đoạn highlight, có trang xem trước và chỉnh mốc cắt bằng tay."

## Context (current code on main, read before coding)
- `sportscut/api.py` already has: `GET /` (serves `web/index.html` with `FileResponse`), the `/static` mount of `WEB_DIR = resources.files("sportscut").joinpath("web")`, `GET /highlights/{job_id}`, `GET /highlights/{job_id}/source` (one byte range, used by `<video>` for seeking), `PUT /highlights/{job_id}/segments` (T-007) and `GET /highlights/{job_id}/clips/{name}`. `_load_job(job_id)` raises `_JobNotFound` for any id that is not a canonical lowercase UUID, has no `job.json`, or has an invalid job.json. All of these map to `HTTPException(404, "not found")`.
- Canonical response (POST, GET and PUT): `{"job_id", "source_name", "source_url", "duration", "highlights": [{"start", "end", "score", "reason", "clip_url"}]}`. `clip_url` is absolute and versioned (`clip_01_v1.mp4` after the first edit). Old clip URLs return 404 after a successful PUT.
- PUT body: `{"segments": [{"start": float, "end": float, "reason": str|null}]}`, with `extra="forbid"` (no other keys), at most 50 segments, each `0 <= start < end <= duration`, finite numbers, an empty list allowed, overlaps allowed. Errors: 422 (shape or bounds), 404 (job), 500 `processing failed`.
- `sportscut/web/app.js` (T-008) already redirects to `/jobs/{encodeURIComponent(job_id)}` after a successful upload. That route does not exist yet, and this task adds it.
- `pyproject.toml` package-data already includes `web/*.html`, `web/*.js` and `web/*.css`, so new files under `sportscut/web/` ship without a pyproject change.
- `tests/conftest.py` provides `require_ffmpeg` and the session fixture `synthetic_video` (6 s, 160x120, 10 fps, audio burst at 2–3 s).

## Design

### 1. Server route (`sportscut/api.py`)
Add it right after `get_web_app`:
```python
@app.get("/jobs/{job_id}", include_in_schema=False)
def get_preview_page(job_id: str) -> FileResponse:
    try:
        _load_job(job_id)
    except _JobNotFound:
        raise HTTPException(404, "not found") from None
    return FileResponse(WEB_DIR.joinpath("preview.html"), media_type="text/html")
```
No other server change. The page is static, and the JS reads the job id from `location.pathname`.

### 2. Pure helper module `sportscut/web/timefmt.js` (new, about 70 lines)
This is a classic script with no DOM, `window`, `document` or `fetch` access. It works in the browser and in Node:
```js
(function (root) {
  const MAX_SEGMENTS = 50
  const NEW_SEGMENT_SECONDS = 10
  function roundMs(x) { return Math.round(x * 1000) / 1000 }
  function formatTime(seconds) { ... }
  function parseTime(text) { ... }
  function clampTime(seconds, duration) { ... }
  function newSegmentAt(time, duration) { ... }
  function validateSegments(segments, duration) { ... }
  const api = { MAX_SEGMENTS, NEW_SEGMENT_SECONDS, formatTime, parseTime, clampTime, newSegmentAt, validateSegments }
  root.SportsCutTime = api
  if (typeof module === "object" && module.exports) module.exports = api
})(globalThis)
```
Contracts (the tests check these exact values):
- `formatTime(seconds)`: throws `RangeError` if `seconds` is not a finite number or is negative. Otherwise `tenths = Math.round(seconds * 10)`, `m = Math.floor(tenths / 600)`, `s = (tenths % 600) / 10`, and the result is `String(m).padStart(2, "0") + ":" + s.toFixed(1).padStart(4, "0")`. Minutes are not capped. Examples: `0 → "00:00.0"`, `5 → "00:05.0"`, `0.04 → "00:00.0"`, `65.25 → "01:05.3"`, `59.96 → "01:00.0"`, `600 → "10:00.0"`, `5400 → "90:00.0"`, `10800 → "180:00.0"`.
- `parseTime(text)`: if `text` is not a string, return `null`. Trim it, then match `/^(?:(\d+):)?(\d+(?:\.\d+)?)$/`. If there is no match, return `null`. If the minutes group is present and seconds `>= 60`, return `null`. Otherwise return `roundMs(minutes * 60 + seconds)`. Examples: `"01:05.3" → 65.3`, `"1:05" → 65`, `"00:00.0" → 0`, `"90:00.0" → 5400`, `"75.5" → 75.5` (plain seconds allowed), `" 00:02.5 " → 2.5`, `"1:60" → null`, `"" → null`, `"abc" → null`, `"-1" → null`, `"1:2:3" → null`, `"1e3" → null`, `"00:05,5" → null`.
- `clampTime(seconds, duration)`: `roundMs(Math.min(Math.max(seconds, 0), duration))`. Examples: `(-0.3, 6) → 0`, `(6.4, 6) → 6`, `(2.5, 6) → 2.5`.
- `newSegmentAt(time, duration)`: `start = clampTime(time, duration)`, `end = clampTime(start + NEW_SEGMENT_SECONDS, duration)`. If `end <= start`, set `start = clampTime(duration - NEW_SEGMENT_SECONDS, duration)`. Return `{start, end, reason: "manual"}`. Examples: `(3, 90) → {3, 13}`, `(85, 90) → {85, 90}`, `(90, 90) → {80, 90}`, `(2, 6) → {2, 6}`, `(6, 6) → {0, 6}`.
- `validateSegments(segments, duration)`: returns an array of Vietnamese error strings. An empty array means valid. This mirrors the server rules exactly:
  - `segments.length > MAX_SEGMENTS` adds `"Tối đa 50 đoạn."`.
  - For each row `i` (1-based `n`): if `start` or `end` is not a finite `number`, add `` `Đoạn ${n}: thời gian không hợp lệ.` ``. Otherwise, if `!(0 <= start && start < end && end <= duration)`, add `` `Đoạn ${n}: cần 0 ≤ đầu < cuối ≤ ${formatTime(duration)}.` ``.
  - Overlapping or adjacent segments are valid, and so is an empty list.

### 3. Page `sportscut/web/preview.html` (new)
The page is in Vietnamese with `lang="vi"`, has no external URLs, and has this structure (ids and classes are the contract that tests and preview.js rely on):
```html
<!doctype html>
<html lang="vi"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SportsCut — Xem trước và chỉnh highlight</title>
  <link rel="stylesheet" href="/static/style.css">
  <script src="/static/timefmt.js" defer></script>
  <script src="/static/preview.js" defer></script>
</head><body><main class="preview">
  <p><a href="/">← Tải video khác</a></p>
  <h1 id="job-title">Xem trước highlight</h1>
  <video id="player" controls preload="metadata"></video>
  <p>Thời điểm hiện tại: <output id="current-time">00:00.0</output></p>
  <ol id="segments"></ol>
  <template id="segment-row"><li class="segment">
    <button type="button" class="play">▶ Phát đoạn</button>
    <label>Đầu <input class="start" type="text" inputmode="decimal" placeholder="mm:ss.s"></label>
    <button type="button" class="start-minus">−0.5 s</button>
    <button type="button" class="start-plus">+0.5 s</button>
    <button type="button" class="set-start">Đầu = hiện tại</button>
    <label>Cuối <input class="end" type="text" inputmode="decimal" placeholder="mm:ss.s"></label>
    <button type="button" class="end-minus">−0.5 s</button>
    <button type="button" class="end-plus">+0.5 s</button>
    <button type="button" class="set-end">Cuối = hiện tại</button>
    <button type="button" class="delete">Xóa</button>
    <a class="clip" download hidden>Tải clip</a>
    <video class="clip-player" controls preload="none" hidden></video>
  </li></template>
  <button type="button" id="add-segment">Thêm đoạn tại thời điểm hiện tại</button>
  <button type="button" id="save">Lưu</button>
  <p id="status" role="status" hidden></p>
  <p id="error" role="alert" aria-live="assertive" hidden></p>
</main></body></html>
```

### 4. Page logic `sportscut/web/preview.js` (new, aim for 150 lines or fewer)
- `const T = globalThis.SportsCutTime`. The job id comes from ``location.pathname.match(/^\/jobs\/([^/]+)\/?$/)`` and is decoded with `decodeURIComponent`. If there is no match, show the error `Không tìm thấy job.`.
- State: `let duration = 0`, `let segments = []`. Each item is `{start, end, reason, clip_url}`, where `clip_url` is `null` for rows not yet saved. `let playUntil = null`.
- Load: ``fetch(`/highlights/${encodeURIComponent(jobId)}`)``. On a non-OK response, show `Lỗi ${response.status}: ${message}`, with `message` taken from `data?.detail` using the same rules as app.js: a string is used as is, an array is reduced to its `msg` values, and the fallback is `Không thể tải job.`. On success, set `duration`, set `#job-title` to `source_name ?? source_url`, set ``player.src = `/highlights/${encodeURIComponent(jobId)}/source` ``, set `segments` from `highlights` (keeping `start`, `end`, `reason` and `clip_url`), then `render()`. On a network or invalid-response error, show `Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ.`.
- `render()`: clear `#segments`, then for each segment clone `#segment-row`. Set the `.play` text to `▶ Đoạn ${n}`, set `.start` and `.end` values to `T.formatTime(...)`, and when `clip_url` is set, show `a.clip` with `href = clip_url` and `video.clip-player` with `src = clip_url`. Rows without a clip keep both elements hidden. Wire the handlers:
  - `.play` click: `player.currentTime = seg.start; playUntil = seg.end; player.play()`. On `timeupdate`, if `playUntil !== null && player.currentTime >= playUntil`, call `player.pause(); playUntil = null`. `timeupdate` also updates `#current-time` with `T.formatTime(player.currentTime)`.
  - `.start` and `.end` `change`: `value = T.parseTime(input.value)`. If it is `null`, store `NaN` (validation then reports the row) and mark the input `aria-invalid="true"`. Otherwise store the value and remove `aria-invalid`. Do not re-render while the user is typing.
  - Nudges: `seg.start = T.clampTime(seg.start - 0.5, duration)` (and the same pattern for `+0.5` and for `end`), then `render()`. A nudge on a `NaN` value does nothing.
  - `.set-start` and `.set-end`: `seg.start = T.clampTime(player.currentTime, duration)` (or `end`), then `render()`.
  - `.delete`: remove the row from `segments`, then `render()`.
  - Edited rows keep their old `clip_url` until Save: clip links always reflect the last saved state.
- `#add-segment` click: `segments.push({...T.newSegmentAt(player.currentTime, duration), clip_url: null})`, then `render()`.
- `#save` click: hide `#error`, then `const problems = T.validateSegments(segments, duration)`. If it is non-empty, show `problems.join(" ")` in `#error` and **do not fetch**. Otherwise set `save.disabled = true`, show `#status` with `Đang cắt lại clip…`, then:
  ```js
  fetch(`/highlights/${encodeURIComponent(jobId)}/segments`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ segments: segments.map(({ start, end, reason }) => ({ start, end, reason })) }),
  })
  ```
  Send only `start`, `end` and `reason`, because the server forbids extra keys. On OK, replace `segments` and `duration` from the response (the new versioned `clip_url`s), call `render()`, and set `#status` to `` `Đã lưu ${segments.length} đoạn.` ``. On a non-OK response, show `Lỗi ${response.status}: ${message}` (fallback `Không thể lưu.`). On network failure, use the same connection message as above. In `finally`, set `save.disabled = false`.
- The server stays the source of truth: the client validation only avoids pointless requests, and every server error is shown as returned.

### 5. Styles (`sportscut/web/style.css`, append only)
Add `main.preview { width: min(100%, 64rem) }`, `#player { width: 100% }`, a flex-wrap layout for `.segment`, `.segment input { width: 6.5rem }`, `.clip-player { width: 12rem }`, and `[aria-invalid="true"] { outline: 2px solid #b42318 }`. Do not change existing rules.

### 6. README (`README.md`)
After the existing `## API HTTP` section, add `## Trang web: tải lên, xem trước và chỉnh mốc cắt` (in Vietnamese, without screenshots) with:
```bash
pip install -e '.[api,youtube]'
sportscut serve
```
Then these numbered steps: open `http://127.0.0.1:8000/`; choose a file or paste a YouTube link and press "Tạo highlight"; the page redirects to `http://127.0.0.1:8000/jobs/JOB_ID`; press "▶ Đoạn N" to play a segment; enter start or end as `mm:ss.s` (plain seconds such as `75.5` are also accepted), or use "Đầu/Cuối = hiện tại" and the ±0.5 s buttons; "Xóa" deletes a segment; "Thêm đoạn tại thời điểm hiện tại" adds a 10 s segment; "Lưu" re-cuts all clips (each save replaces the whole list, there is no undo, and old clip links stop working). The section also notes that the page shows a 404 for an unknown JOB_ID.

## Files
- change `sportscut/api.py` (one route)
- create `sportscut/web/preview.html`, `sportscut/web/preview.js`, `sportscut/web/timefmt.js`
- change `sportscut/web/style.css` (append)
- change `README.md` (new section)
- create `tests/test_preview.py` (Developer: route, page contract, Node-run helper unit tests)
- create `tests/test_t009_acceptance.py` (Tester: independent acceptance and E2E)

## Steps (TDD order)
1. Write `tests/test_preview.py::test_preview_page_served_for_existing_job` (write a valid job.json directly under `SPORTSCUT_DATA_DIR`, as `_persist_test_job` does in `tests/test_api.py`; no ffmpeg needed) and `::test_preview_page_404_for_unknown_or_invalid_ids`. Run them and watch them fail with 404/405. Add the route and an initial `preview.html`, then watch them pass.
2. Write `::test_preview_html_contract` (the ids and classes from §3, script order, no `http://` or `https://` in the three new files) and make it pass by completing `preview.html`.
3. Write the Node-run tests for `timefmt.js` (`::test_timefmt_format_time`, `::test_timefmt_parse_time`, `::test_timefmt_clamp_and_new_segment`, `::test_timefmt_validate_segments`, `::test_timefmt_is_pure`). They fail because the file is missing. Implement `timefmt.js` until they pass.
4. Write `::test_preview_js_contract` (static string checks from AC6/AC7) and implement `preview.js`.
5. Write `::test_preview_flow_end_to_end` (uses `synthetic_video`) and make it pass. It should pass without further server code, which proves the page's API sequence works.
6. Append CSS and write the README section.
7. Run the full suite.

## Verify commands
- `.venv/bin/python -m pytest -q tests/test_preview.py tests/test_t009_acceptance.py -rs` → 0 failed and 0 skipped on a machine with node, ffmpeg and ffprobe on PATH (the dev laptop has all of them).
- `.venv/bin/python -m pytest -q` → 0 failed.
- Manual: run `sportscut serve`, upload a file at `/`, edit a segment on `/jobs/<id>`, press Lưu, and check that the clip link ends with `_v1.mp4`.

## Assumptions
- There is no timeline or waveform widget. Text inputs plus the native `<video>` controls are enough for manual adjustment.
- The minimum length of a segment is the server's (`start < end`). A new segment defaults to 10 s, clamped to the video.
- Values from the server and from "= hiện tại" are kept at millisecond precision. The input shows them rounded to tenths, and only a typed value is re-parsed. So an untouched segment is sent back with exactly the server's numbers.
- UI text is Vietnamese, while API error details may stay English (same as T-008).
- Node is used only by the test suite to run the pure helper module. The product still needs no Node, npm or build step.

## Test plan

- tests/test_preview.py (Developer): fixture `api_env` sets SPORTSCUT_DATA_DIR to tmp_path, plus a helper `_write_job(data_dir, job_id)` that writes a valid job.json (source_name 'm.mp4', source_url null, duration 6.0, version 0, one segment {start 0.5, end 1.5, score 2.0, reason 'detected', file 'clip_01.mp4'}) so the route tests run without ffmpeg.
- test_preview_page_served_for_existing_job: 200, text/html, preview markers present (AC1).
- test_preview_page_404_for_unknown_or_invalid_ids (parametrized): unknown uuid4, uppercase existing id, 'not-a-uuid', dir without job.json, dir with job.json `{}` → 404 and `{"detail": "not found"}`; also `/jobs/{job_id}` is not in `app.openapi()['paths']` (AC2).
- test_preview_html_contract: ids and classes from AC3, script order via str.index, `lang="vi"`, hidden status/error, and no http(s) URLs in preview.html, preview.js or timefmt.js; static JS assets served with a JavaScript content type (AC3).
- Node helper tests (skip with reason 'node is required on PATH' only when shutil.which('node') is None): write a small runner `runner.js` into tmp_path that does `const T = require(process.argv[2])` and prints `JSON.stringify` of a results object computed from the AC4/AC5 inputs (RangeError cases reported as the string 'RangeError'), run it with `subprocess.run(['node', runner, str(timefmt_path)], check=True, capture_output=True, text=True)`, and compare in Python: test_timefmt_format_time, test_timefmt_parse_time (numbers compared with pytest.approx(abs=1e-9)), test_timefmt_clamp_and_new_segment, test_timefmt_validate_segments (50 vs 51 segments, empty, overlap, end==duration, NaN row, each bound violation with exact message) (AC4, AC5).
- test_timefmt_is_pure: static source check for forbidden globals, plus Node check that `require` gives the same object as `globalThis.SportsCutTime` and stdout is empty (AC6).
- test_preview_js_contract: static substring checks from AC7, and the validate-before-PUT ordering check (AC7).
- test_preview_flow_end_to_end (uses `synthetic_video`, which depends on `require_ffmpeg`): the AC8 sequence, with clip durations checked by writing the download bytes to tmp_path and calling `media.probe_duration` (AC8).
- tests/test_t009_acceptance.py (Tester, written independently from the ACs, not copied from the Developer's tests): re-check AC1–AC9 with its own fixtures, including a second PUT with an empty list after the edit (GET /jobs still 200, the highlights list empty) and confirmation that mutating `validateSegments` bounds (e.g. allowing end > duration) or removing the route makes the tests fail. AC9 is checked by reading README.md in a test. The Tester confirms the Node tests actually ran (not skipped) via `-rs`.
- Regression: full `.venv/bin/python -m pytest -q` (the existing T-005/T-007/T-008 tests in test_api.py, test_web.py and test_t00x_acceptance.py stay green and unchanged).
