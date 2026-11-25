# T-016: Add event badges and 'Chỉ bàn thắng' / 'Top 5 pha hay' filters to the web preview

Request R-003. Plan: `docs/superpowers/plans/2026-11-23-t-016-add-event-badges-and-ch-b.md`.

## Product Owner request

Highlight theo sự kiện: gắn nhãn bàn thắng, cứu thua, thẻ đỏ, pha tranh cãi. Người dùng lọc "chỉ bàn thắng" hoặc "top 5 pha hay".

## Goal

On the R-002 preview page, show each segment's event as a Vietnamese badge (Bàn thắng, Cứu thua, Thẻ đỏ, Tranh cãi, Khác), add filter chips per event, and add two presets: 'Chỉ bàn thắng' (events=goal) and 'Top 5 pha hay' (top=5 by the task 3 ranking). The upload form gets the same optional event/top fields. Filtering is client-side over the job's segments, and the exported clip set follows the selection through the existing endpoints. Tests: TestClient serves the page with the filter controls; an API-level test runs POST with events=goal and checks that only goal clips come back; the filter logic lives in a small pure JS module so it is easy to review. Assumption: this starts only after R-002's T-009 preview page is merged; if it is missing, report BLOCKED.

## Acceptance criteria

- AC1: Step 0 prints READY on the task base. No T-009/T-012 module is recreated.
- AC2: `sportscut/web/filters.js` loaded with Node `require` returns the same object as `globalThis.SportsCutFilter`, prints nothing, and its source contains none of `document`, `window`, `fetch`, `localStorage`, `XMLHttpRequest`, `http://`, `https://`. It exports EVENT_TYPES ['goal','save','red_card','controversy','other'], EVENT_LABELS {goal:'Bàn thắng', save:'Cứu thua', red_card:'Thẻ đỏ', controversy:'Tranh cãi', other:'Khác'}, EVENT_PRIORITY {goal:5, red_card:4, controversy:3, save:2, other:1}, and PRESETS all={events:[],top:null}, goals={events:['goal'],top:null}, top5={events:[],top:5}, each preset and its events array frozen.
- AC3: normalizeEvent/eventLabel: 'goal'->'goal'/'Bàn thắng', 'red_card'->'Thẻ đỏ', 'controversy'->'Tranh cãi', 'save'->'Cứu thua'. undefined, null, '' and 'penalty' -> 'other'/'Khác'.
- AC4: selectIndices on the worked list W = [0:(0,10,2.0,other), 1:(15,25,1.0,save), 2:(30,40,2.0,goal), 3:(50,60,1.5,save), 4:(70,80,2.0,red_card), 5:(85,95,3.0,other), 6:(100,110,null,controversy)] (start,end,score,event) returns: PRESETS.top5 -> [1,2,3,4,5]; PRESETS.goals -> [2]; PRESETS.all, null and undefined -> [0,1,2,3,4,5,6]; {events:[],top:2} -> [2,4]; {events:[],top:3} -> [2,3,4]; {events:['save'],top:1} -> [3]; {events:['other'],top:1} -> [5]; {events:['controversy'],top:null} -> [6]; {events:['goal','save'],top:null} -> [1,2,3]; {events:['goal'],top:5} -> [2]. W is deep-equal to its copy afterwards.
- AC5: selectIndices tie and edge rules: two 'other' segments with score 1 at starts 30 (index 0) and 10 (index 1) with top 1 -> [1]; a segment with missing event or event 'penalty' is kept by {events:['other'],top:null}; a NaN start does not throw and ranks after finite starts on equal score/priority; [] -> []; top 0, -1, 2.5, '5' and NaN each throw RangeError 'top must be a positive integer'.
- AC6: toggleEvent({events:['save'],top:5}, 'goal') returns {events:['goal','save'],top:5} (EVENT_TYPES order) and leaves the input unchanged. Toggling 'save' off returns {events:[],top:5}. toggleEvent(PRESETS.all,'goal') does not throw on the frozen preset. sameSelection({events:['save','goal'],top:null}, {events:['goal','save'],top:null}) is true, and it is false when top differs (null vs 5) or the event sets differ.
- AC7: For a hand-written job, `GET /jobs/{job_id}` via TestClient returns 200 text/html containing `id="filters"`, `id="filter-all"`, five `class="chip"` buttons with data-event goal/save/red_card/controversy/other and labels Bàn thắng/Cứu thua/Thẻ đỏ/Tranh cãi/Khác, `id="preset-goals"` with text `Chỉ bàn thắng`, `id="preset-top5"` with text `Top 5 pha hay`, `id="filter-count"`, and `class="event-badge"` inside template#segment-row. preview.html references style.css < timefmt.js < filters.js < preview.js (the scripts deferred). `GET /static/filters.js` returns 200 with a JavaScript content type. The first `<a>` is still `href="/"`.
- AC8: preview.js contains `const F = globalThis.SportsCutFilter`, `F.selectIndices(segments, selection)`, `if (!shown.has(index)) return`, `F.eventLabel(`, `F.normalizeEvent(event)`, `F.toggleEvent(selection`, `F.PRESETS.goals`, `F.PRESETS.top5`, `F.sameSelection(`, `aria-pressed`, `Đang hiện`, `Không có đoạn nào khớp bộ lọc.`, `({ start, end, reason, event })`, and still `segments.splice(index, 1)`. The `addSegment` click handler sets `selection = F.PRESETS.all`. The save click handler (from `save.addEventListener("click"` to its PUT `fetch(`) contains `T.validateSegments(segments, duration)` and does not contain `selectIndices`. All other T-009 AC7 markers still hold.
- AC9: With synthetic_video and `sportscut.pipeline.find_highlights` stubbed to return Segments (0.5,1.5,2.0,'other'), (2.0,3.0,1.0,'goal'), (3.5,4.5,3.0,'save'), (4.6,5.6,1.5,'goal'), `POST /highlights` with file, `events=goal`, min_len=0.5, max_len=1.0 returns 200 whose highlights have events ['goal','goal'] and starts [2.0,4.6]. Each clip_url downloads 200 video/mp4 with probe_duration ≈ 1.0 (abs 0.5). job.json segments contain only goal entries. `GET /highlights/{id}` returns the same highlights.
- AC10: With the same stub and no events, `POST /highlights` with `top=2` returns starts [3.5,4.6] (events save, goal), because goal 1.5×5=7.5 and save 3.0×2=6 beat goal 1.0×5=5 and other 2.0×1=2.
- AC11: On a job made as in AC9 without events (4 segments), `PUT /highlights/{id}/segments` with `{"segments":[{"start":2.0,"end":3.0,"reason":"x","event":"goal"},{"start":0.5,"end":1.5},{"start":3.5,"end":4.5,"event":null}]}` returns 200 with highlights in time order, events ['other','goal','other'], every score null and event_confidence 0.0. job.json keeps the same events. `GET /highlights/{id}?event=goal` returns exactly the 2.0 segment.
- AC12: `PUT` with an item event 'penalty', 'Goal' or 1 returns 422, does not call `export.export_clips` (monkeypatched to fail) and leaves job.json bytes unchanged. An item with an unknown key (e.g. `extra`) still returns 422.
- AC13: `GET /` contains five checkboxes `name="events" type="checkbox"` with ids event-goal, event-save, event-red_card, event-controversy, event-other, values goal/save/red_card/controversy/other, each with a `<label for=...>` reading Bàn thắng/Cứu thua/Thẻ đỏ/Tranh cãi/Khác, none `checked`. index.html still references only /static/style.css and /static/app.js. app.js contains `document.querySelectorAll('input[name="events"]:checked')`, `.join(",")`, `if (events) formData.append("events", events)`, and the append comes before `fetch("/highlights"`. All T-008 tests pass unchanged.
- AC14: README section `## Trang web: tải lên, xem trước và chỉnh mốc cắt` contains `Chỉ bàn thắng`, `Top 5 pha hay`, `Tất cả`, `Bàn thắng`, `Lưu` and says hidden rows are still saved. All earlier README markers checked by test_preview.py still hold and the section has no `![`. The T-007 and T-009 design specs each contain `## Updated by T-016` mentioning `event`.
- AC15: `.venv/bin/python -m pytest -q` reports 0 failed. The targeted run in the spec's Verify section reports 0 failed and 0 skipped where node, ffmpeg and ffprobe are on PATH. The only edits to existing tests are the two `({ start, end, reason })` -> `({ start, end, reason, event })` marker changes. The diff touches no file under agent-office/, pyproject.toml, tests/conftest.py, sportscut/pipeline.py, sportscut/ranking.py, sportscut/detect.py or sportscut/models.py, and adds no dependency, npm or CDN.

## Out of scope

- Event classifiers or any change to detection, ranking.py, pipeline.py or the eval (F1 unchanged).
- Editing an existing segment's event in the UI (no event dropdown per row); badges are read-only.
- A 'save only the filtered rows' / 'export selection' button, zip download or concatenated reel of the selection.
- Server-side filtering for the preview page (it does not call GET /highlights/{id}?event=); persisting the filter in the URL or localStorage.
- A free-form top-N input on the preview page beyond the 'Top 5 pha hay' preset; preset buttons on the upload form (the checkboxes + existing top field cover it).
- Sending score or event_confidence on PUT; restoring detector scores after a manual save.
- Browser automation (Playwright/Selenium), npm, bundlers or CDN assets.
- Changing the POST /highlights or GET /highlights/{id} contracts.

## Decisions

- T-016 (R-003): Filter logic lives in the pure classic script `sportscut/web/filters.js` (`globalThis.SportsCutFilter` and `module.exports`, same object), loaded on the preview page between timefmt.js and preview.js. preview.js keeps all DOM/fetch code.
- T-016 (R-003): Client ranking mirrors ranking.py exactly: priority goal 5, red_card 4, controversy 3, save 2, other 1; key (-(score*priority), -priority, start, end, index); filter by events first, then top N; shown in list order. A null/non-finite score counts as 0, a non-finite start/end sorts as Infinity, and a missing/unknown event counts as 'other' (label 'Khác').
- T-016 (R-003): Selection state is `{events: string[], top: number|null}`. Presets: Tất cả = {[],null}, 'Chỉ bàn thắng' = {['goal'],null}, 'Top 5 pha hay' = {[],5}. Event chips toggle events and keep top, so chips + Top 5 = the 5 best of those events (T-012 semantics).
- T-016 (R-003): The preview filter is view-only. It hides rows and their clip players/download links, but 'Lưu' always sends the full segment list, so filtering never deletes segments. The server-side way to export only some events is the upload form's event checkboxes (`events` on POST /highlights).
- T-016 (R-003): Adding a segment resets the filter to 'Tất cả' so the new 'other' row is visible. Row numbers ('Đoạn N'), validation messages and delete use the original index in the full list.
- T-016 (R-003): PUT /highlights/{id}/segments items accept an optional `event` (exactly one of goal, save, red_card, controversy, other; missing/null -> other; anything else 422 before export), and the preview sends `({ start, end, reason, event })`. This amends T-007 AC8/AC9 ('every PUT segment is manual': score stays null, event_confidence 0.0, but the event is now kept) and the T-009 decision 'Save sends only {start, end, reason}'. Updating the `({ start, end, reason })` marker in test_preview.py and test_t009_acceptance.py follows this intended spec change and does not weaken those tests.
- T-016 (R-003): The upload form adds five unchecked `events` checkboxes. app.js joins the checked values with ',' and appends `events` only when non-empty, so the default POST is unchanged. index.html still loads only style.css and app.js.
- T-016 (R-003): No accuracy change, so no eval gate beyond the existing T-012 F1 test staying green.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-007-add-job-read-source-streaming-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-009-build-the-preview-page-with-manual-design.md`
- `docs/superpowers/specs/2026-11-23-t-008-serve-a-web-upload-page-for-design.md`
- `docs/superpowers/specs/2026-11-23-t-012-let-users-filter-by-event-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-010-add-event-types-to-segments-and-design.md`

## Updated by T-028

Updated by T-028: the preview script order becomes `timefmt.js`, `filters.js`, `metafmt.js`, `preview.js` (all `defer`). The exact resource-list test in tests/test_t016_acceptance.py gains `/static/metafmt.js`; nothing else in the T-016 contract changes.
