# Plan T-016: Add event badges and 'Chỉ bàn thắng' / 'Top 5 pha hay' filters to the web preview

Design: `docs/superpowers/specs/2026-11-23-t-016-add-event-badges-and-ch-b-design.md`.

## Implementation plan

# T-016: Event badges and 'Chỉ bàn thắng' / 'Top 5 pha hay' filters on the web preview

Request R-003 (PO: "Highlight theo sự kiện ... Người dùng lọc 'chỉ bàn thắng' hoặc 'top 5 pha hay'"). Builds on R-002 T-008 (upload page), T-007 (job read/PUT), T-009 (preview page) and R-003 T-010/T-012 (event field, ranking, `events`/`top` on POST).

## Step 0: dependency gate

Run:
`test -f sportscut/web/preview.html && grep -q '@app.get("/jobs/{job_id}"' sportscut/api.py && grep -q 'def select_segments' sportscut/ranking.py && echo READY || echo BLOCKED`
If it prints BLOCKED, stop and report BLOCKED. Do not recreate T-009 or T-012 code. On main 032b298 it prints READY.

## Context (current code)

- `sportscut/api.py`: `POST /highlights` already takes `top` (default 10, >=1) and `events` (comma list, parsed by `ranking.parse_events`; blank = absent; bad value = 422). `GET /highlights/{job_id}` returns `{job_id, source_name, source_url, duration, highlights}` from job.json. Each highlight is `{start, end, score, reason, event, event_confidence, clip_url}`. `PUT /highlights/{job_id}/segments` takes `SegmentEdits{segments: list[SegmentEdit{start, end, reason?}]}` with `extra="forbid"`. It builds `Segment(start, end, None, reason or 'manual')`, so today every saved segment's event goes back to `'other'`.
- `sportscut/ranking.py`: `EVENT_PRIORITY = {goal:5, red_card:4, controversy:3, save:2, other:1}`. Rank key `(-(score*priority), -priority, start, end)`; filter first, then top N, then time order.
- `sportscut/web/preview.html` + `preview.js` (DOM/fetch) + `timefmt.js` (pure helpers, `globalThis.SportsCutTime` + `module.exports`). `preview.js` drops `event`/`score` in `acceptResponse` and saves `({ start, end, reason })`.
- `sportscut/web/index.html` + `app.js`: upload form with file/url/top/min_len/max_len. FormData is built by hand and only non-blank fields are appended.
- Node is used only in tests (skip with reason 'node is required on PATH' when absent). No npm, CDN or build step.

## Design

### 1. Pure filter module `sportscut/web/filters.js` (new)

A classic script in the same style as `timefmt.js`: an IIFE over `globalThis` that sets `root.SportsCutFilter = api` and, when `typeof module === 'object' && module.exports`, `module.exports = api` (the same object). It has no `document`, `window`, `fetch`, `localStorage` or `XMLHttpRequest`, and loading it prints nothing.

Exports (exact values):
- `EVENT_TYPES = ['goal','save','red_card','controversy','other']` (same order as `sportscut.models.EVENT_TYPES`)
- `EVENT_LABELS = {goal:'Bàn thắng', save:'Cứu thua', red_card:'Thẻ đỏ', controversy:'Tranh cãi', other:'Khác'}`
- `EVENT_PRIORITY = {goal:5, red_card:4, controversy:3, save:2, other:1}` (same as ranking.py)
- `PRESETS = {all:{events:[], top:null}, goals:{events:['goal'], top:null}, top5:{events:[], top:5}}`, deep-frozen (`Object.isFrozen` is true for each preset and its `events` array)
- `normalizeEvent(event) -> string`: returns `event` if it is one of EVENT_TYPES, else `'other'` (covers undefined/null/unknown strings from old manifests).
- `eventLabel(event) -> string`: `EVENT_LABELS[normalizeEvent(event)]`.
- `toggleEvent(selection, event) -> selection`: returns a NEW object `{events, top}`. `event` is added if absent and removed if present. `events` is kept in EVENT_TYPES order, and `top` is copied unchanged. The input is never mutated.
- `sameSelection(a, b) -> boolean`: true when both have the same set of events and the same `top`.
- `selectIndices(segments, selection) -> number[]`: the indices (into `segments`) that the selection keeps, in ascending index order.
  - `selection` null/undefined is treated as `PRESETS.all`.
  - Filter: if `selection.events` is non-empty, keep a segment only when `normalizeEvent(seg.event)` is in `events`. An empty array means no filter.
  - Top: `selection.top` null/undefined means no cap. Otherwise it must be an integer >= 1, or the function throws `RangeError('top must be a positive integer')` (0, -1, 2.5, '5', NaN). The top is applied AFTER the filter (T-012 order).
  - Rank key, the same as ranking.py: ascending by `(-(s*p), -p, start, end, index)`, where `p = EVENT_PRIORITY[normalizeEvent(seg.event)]`, `s = score` if it is a finite number else `0` (manual segments have `score: null`), and a non-finite `start`/`end` sorts as `Infinity`. Take the first `top` items, then return their indices sorted ascending.
  - It never mutates `segments` or `selection`.

### 2. Preview page (`preview.html`, `preview.js`, `style.css`)

`preview.html`:
- Script tags in this order: `/static/style.css`, `/static/timefmt.js` (defer), `/static/filters.js` (defer), `/static/preview.js` (defer).
- Between the `#current-time` paragraph and `<ol id="segments">`, add:
```html
<div id="filters" role="group" aria-label="Lọc theo sự kiện">
  <button type="button" id="filter-all" aria-pressed="true">Tất cả</button>
  <button type="button" class="chip" data-event="goal" aria-pressed="false">Bàn thắng</button>
  <button type="button" class="chip" data-event="save" aria-pressed="false">Cứu thua</button>
  <button type="button" class="chip" data-event="red_card" aria-pressed="false">Thẻ đỏ</button>
  <button type="button" class="chip" data-event="controversy" aria-pressed="false">Tranh cãi</button>
  <button type="button" class="chip" data-event="other" aria-pressed="false">Khác</button>
  <button type="button" id="preset-goals" aria-pressed="false">Chỉ bàn thắng</button>
  <button type="button" id="preset-top5" aria-pressed="false">Top 5 pha hay</button>
  <output id="filter-count"></output>
</div>
```
- In `template#segment-row`, add `<span class="event-badge"></span>` right after the `.play` button. Add no `<a>` element before the existing back link (`<a href="/">` must stay the first `<a>`). Keep every existing T-009 element.

`preview.js` (all DOM logic stays here):
- `const F = globalThis.SportsCutFilter` next to `const T = globalThis.SportsCutTime`. State `let selection = F.PRESETS.all`.
- `acceptResponse` keeps the event and score: `data.highlights.map(({ start, end, score, reason, event, clip_url }) => ({ start, end, score, reason, event: F.normalizeEvent(event), clip_url }))`.
- `render()` computes `const shown = new Set(F.selectIndices(segments, selection))`, loops over the FULL `segments` with `segments.forEach((seg, index) => { if (!shown.has(index)) return ... })`, so the labels `▶ Đoạn ${index + 1}`, the validation messages and `segments.splice(index, 1)` keep using the original index. Each row's `.event-badge` gets `textContent = F.eventLabel(seg.event)` and `dataset.event = seg.event`. `render()` also sets `aria-pressed` on each `.chip` (`selection.events.includes(chip.dataset.event)`), on `#filter-all` (`F.sameSelection(selection, F.PRESETS.all)`), on `#preset-goals` (`F.PRESETS.goals`) and on `#preset-top5` (`F.PRESETS.top5`). It sets `#filter-count` to `Đang hiện ${shown.size}/${segments.length} đoạn` when `shown.size > 0`, or `Không có đoạn nào khớp bộ lọc.` when `segments.length > 0 && shown.size === 0`, or `''` when there are no segments.
- Clicks: `.chip` -> `selection = F.toggleEvent(selection, chip.dataset.event)`; `#filter-all` -> `selection = F.PRESETS.all`; `#preset-goals` -> `selection = F.PRESETS.goals`; `#preset-top5` -> `selection = F.PRESETS.top5`. Each click then calls `render()`. A chip keeps the current top, so 'Top 5' + 'Bàn thắng' = the 5 best goals, the same as T-012 `events` + `top`.
- `#add-segment` pushes `{ ...T.newSegmentAt(player.currentTime, duration), event: "other", score: null, clip_url: null }`, sets `selection = F.PRESETS.all` (so the new row is visible) and calls `render()`.
- Save validates and sends ALL segments, including rows the filter hides: body `segments.map(({ start, end, reason, event }) => ({ start, end, reason, event }))`. It does not call `F.selectIndices` in the save handler. After a successful PUT, `acceptResponse(data)` + `render()` keep the current `selection`.
- Because the filter is view-only, the clip players and 'Tải clip' links (the existing `GET /highlights/{id}/clips/{name}` URLs) appear only for the selected rows. That is how the exported clip set follows the selection on this page.

`style.css`: add `#filters { display: flex; flex-wrap: wrap; gap: 0.5rem; }`, `#filters button { width: auto; }`, `#filters button[aria-pressed="true"] { background: #1d4ed8; color: #fff; }` and `.event-badge { padding: 0.1rem 0.5rem; border-radius: 999px; background: #e5e7eb; }`. Keep all existing rules.

### 3. PUT keeps the event (`sportscut/api.py`)

`SegmentEdit` gets an optional `event: Literal["goal", "save", "red_card", "controversy", "other"] | None = None` (the values must equal `models.EVENT_TYPES`; matching is exact and lower-case). `put_segments` builds `Segment(item.start, item.end, None, item.reason or "manual", event=item.event or "other")`. Score stays null and event_confidence stays 0.0 (manual edit). Any other value (e.g. `penalty`, `Goal`) gives the normal FastAPI 422 before export, and job.json, the manifest and clips stay unchanged. Every other key is still forbidden.

### 4. Upload form (`index.html`, `app.js`)

`index.html`: inside `.options` (after the `top` field), add `<fieldset id="events"><legend>Chỉ lấy sự kiện (không bắt buộc)</legend>` with five checkboxes, one per event in EVENT_TYPES order, each as `<input id="event-goal" name="events" type="checkbox" value="goal"> <label for="event-goal">Bàn thắng</label>` (ids `event-goal`, `event-save`, `event-red_card`, `event-controversy`, `event-other`; labels as in EVENT_LABELS). Nothing is checked by default. No new script or stylesheet: index.html keeps referencing only `/static/style.css` and `/static/app.js` (T-008 acceptance).
`app.js`, after the top/min_len/max_len lines:
```js
const events = Array.from(document.querySelectorAll('input[name="events"]:checked'), (input) => input.value).join(",")
if (events) formData.append("events", events)
```
Together with the existing `top` field this gives 'Chỉ bàn thắng' (tick Bàn thắng) and 'Top 5 pha hay' (top=5) at upload time, through the existing `POST /highlights`. Keep every existing app.js line.

### 5. Docs

- README section `## Trang web: tải lên, xem trước và chỉnh mốc cắt`: add numbered steps (no new `## ` heading inside the section, no images). They cover the event checkboxes on the upload form; the badges; the chips; `Tất cả`; `Chỉ bàn thắng`; `Top 5 pha hay`; that the filter only hides rows and `Lưu` still saves every segment; and that clip links show only for the rows shown. Keep every existing line of the section.
- `docs/superpowers/specs/2026-11-23-t-007-add-job-read-source-streaming-and-design.md`: append `## Updated by T-016`. PUT items accept an optional `event` (one of goal, save, red_card, controversy, other; missing/null -> other; anything else 422); this amends AC8/AC9 and the 'every PUT segment is manual' decision (score stays null).
- `docs/superpowers/specs/2026-11-23-t-009-build-the-preview-page-with-manual-design.md`: append `## Updated by T-016`. Save sends `{start, end, reason, event}` (amends AC7 and the 'Save sends only {start, end, reason}' decision); `filters.js` is loaded between timefmt.js and preview.js (AC3 order still holds); and the event filter chips/presets exist.

## Interfaces summary

- JS: `globalThis.SportsCutFilter = { EVENT_TYPES, EVENT_LABELS, EVENT_PRIORITY, PRESETS, normalizeEvent, eventLabel, toggleEvent, sameSelection, selectIndices }`. Selection shape `{ events: string[], top: number|null }`.
- HTTP: `PUT /highlights/{id}/segments` body items `{start, end, reason?, event?}`. Response shape unchanged.
- Form: `POST /highlights` gets `events=goal,save` from the checkboxes (the field is unchanged from T-012).

## Ordered steps (TDD)

1. Step 0 gate (above).
2. Write `tests/test_web_filters.py::test_filters_*` (node, `_node_eval` pattern from test_preview.py that requires `sportscut/web/filters.js`). Run it and see it FAIL (module missing). Create `filters.js`. Run it and see it pass.
3. Write `test_put_keeps_event_*` (API). FAIL. Add `SegmentEdit.event` + the `put_segments` change. Pass.
4. Write `test_post_events_goal_returns_only_goal_clips` and `test_post_top_ranks_by_event_priority` (ffmpeg). They should pass already (T-012), which proves the existing endpoint works for this page. If they fail, stop and report, do not change the pipeline.
5. Write `test_preview_page_serves_filter_controls` and `test_preview_js_filter_contract`. FAIL. Edit preview.html, preview.js and style.css. Pass. Update the two T-009 markers `({ start, end, reason })` -> `({ start, end, reason, event })` in `tests/test_preview.py::test_preview_js_contract` and `tests/test_t009_acceptance.py::test_preview_javascript_acceptance_contract` (intended spec change, see decisions; change nothing else in those tests).
6. Write `test_upload_form_has_event_checkboxes` and `test_app_js_sends_checked_events`. FAIL. Edit index.html and app.js. Pass.
7. Write `test_readme_documents_event_filters`. FAIL. Update the README and the two spec files. Pass.
8. Run the full verification commands.

## Verify

- `.venv/bin/python -m pytest -q tests/test_web_filters.py tests/test_t016_acceptance.py tests/test_preview.py tests/test_t009_acceptance.py tests/test_web.py tests/test_t008_acceptance.py tests/test_api.py tests/test_t007_acceptance.py tests/test_t012_acceptance.py -rs` -> 0 failed, 0 skipped when node, ffmpeg and ffprobe are on PATH.
- `.venv/bin/python -m pytest -q` -> 0 failed.
- `node -e "const F=require('./sportscut/web/filters.js'); console.log(JSON.stringify(F.selectIndices([{start:0,end:1,score:1,event:'other'},{start:2,end:3,score:1,event:'goal'}], F.PRESETS.goals)))"` prints `[1]`.
- Manual: `sportscut serve`, upload with 'Bàn thắng' ticked, open `/jobs/JOB_ID`, click the chips and presets.
- No detection/ranking code changes, so the `sportscut eval` F1 is unchanged (T-012 AC15 test still passes).

## Assumptions

- The preview filter is a view: it hides rows and their clip links, and never deletes segments. `Lưu` always saves the full list, so filtering cannot lose work. To keep only goals in the job, the user ticks 'Bàn thắng' on upload (server-side `events`) or deletes rows.
- Until event classifiers land (later R-003 tasks), real detections are all `other`, so 'Chỉ bàn thắng' on a real job shows `Không có đoạn nào khớp bộ lọc.`. Tests use stubbed detections with events.
- After a manual save every score is null, so 'Top 5 pha hay' then ranks by event priority and then time, which is the same rule as the server with score 0.
- 'Top 5' counts the segments in the current list, including manually added ones (event other, score 0).

## Test plan

- tests/test_web_filters.py (Developer, node via a `_node_eval`-style helper that requires sportscut/web/filters.js; skips 'node is required on PATH'): test_filters_module_is_pure_and_exports_constants (AC2), test_filters_normalize_and_label (AC3), test_filters_select_indices_worked_list (AC4, the W list and all listed selections plus no mutation), test_filters_select_indices_ties_and_errors (AC5), test_filters_toggle_and_same_selection (AC6).
- tests/test_web_filters.py API (TestClient, SPORTSCUT_DATA_DIR=tmp_path, `synthetic_video` fixture from conftest, `monkeypatch.setattr(pipeline, 'find_highlights', stub)` returning the 4 Segments of AC9): test_post_events_goal_returns_only_goal_clips (AC9, including clip download + media.probe_duration), test_post_top_ranks_by_event_priority (AC10), test_put_keeps_event (AC11), test_put_rejects_bad_event_without_export (AC12; monkeypatch `sportscut.api.export.export_clips` to pytest.fail and compare job.json bytes).
- tests/test_web_filters.py page contracts: test_preview_page_serves_filter_controls (AC7, a GET /jobs/{id} on a hand-written job.json like test_preview._write_job), test_preview_js_filter_contract (AC8, text slices of preview.js), test_upload_form_has_event_checkboxes and test_app_js_sends_checked_events (AC13), test_readme_documents_event_filters_and_specs_updated (AC14).
- Existing tests: in tests/test_preview.py::test_preview_js_contract and tests/test_t009_acceptance.py::test_preview_javascript_acceptance_contract, change only the marker `({ start, end, reason })` to `({ start, end, reason, event })`. Every other existing test passes unchanged (test_web.py, test_t008_acceptance.py, test_api.py, test_t007_acceptance.py, test_t012_acceptance.py).
- tests/test_t016_acceptance.py (Tester, written independently from the ACs): node-driven checks of selectIndices/toggleEvent/sameSelection on its own lists (including a null score, an unknown event, and top applied after the filter), the AC9/AC10/AC11/AC12 HTTP flows on synthetic_video with a stubbed detector, the AC7/AC13 HTML structure parsed with html.parser, and confirming the tests fail against main (e.g. filters.js missing, PUT rejecting `event`).
- Fixtures: reuse `synthetic_video` (6 s) and `require_ffmpeg` from tests/conftest.py. No new media files, nothing under data/.
