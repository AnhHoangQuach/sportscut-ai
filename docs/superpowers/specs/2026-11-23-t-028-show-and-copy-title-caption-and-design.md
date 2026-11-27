# T-028: Show and copy title, caption and hashtags on the web preview page

Request R-005. Plan: `docs/superpowers/plans/2026-11-23-t-028-show-and-copy-title-caption-and.md`.

## Product Owner request

Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt.

## Goal

On the R-002 preview page, show each clip's title, caption and hashtags in editable fields with a 'Sao chép' (copy) button, plus the reel-level metadata. A voice-over clip, when it exists, gets a player toggle between the original and the voice-over version. Edits are saved through a small `PUT /highlights/{job_id}/meta` endpoint that applies the same format validation as eval-meta (422 when invalid). Tests: TestClient serves the page with the metadata fields, and an invalid PUT returns 422 while a valid one persists. The copy and format logic lives in a small pure JS module. Assumption: this starts only after R-002's T-009 preview page is merged, otherwise report BLOCKED.

## Acceptance criteria

- AC1: The Step 0 command prints READY on the task's base branch. If it does not, the task reports BLOCKED and changes no file.
- AC2: `sportscut.commentary.eval_meta.format_problems(meta)` exists and returns [] for `generate_meta(ClipFacts(e))` for every e in EVENT_TYPES. It returns exactly: ['title length 4'] for title 'Ngắn'; ['title length 18'] for ' Bàn thắng đẹp mắt'; ['caption length 0'] for caption ''; ['caption length 301'] for 'a'*301; ['hashtag count 2'] for ('#A','#B'); ['hashtag count 9'] for 9 distinct valid tags; ['duplicate hashtag #bongda'] for ('#BongDa','#bongda','#X'); ['bad hashtag #Việt'] for ('#BongDa','#Việt','#X'). The other fields in each case are valid. Every existing test in tests/test_eval_meta.py, tests/test_commentary_meta.py and tests/test_t023_acceptance.py passes unchanged, and `sportscut eval-meta tests/fixtures/eval_meta --json` prints score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0.
- AC3: Setup: a hand-written job dir under SPORTSCUT_DATA_DIR (duration 6.0, version 0, source_name 'match.mp4', source_url null), with segments clip_01.mp4 (event 'goal') and clip_02.mp4 (no event key) and no meta.json. `GET /highlights/{id}/meta` returns 200 with exactly {"job_id": id, "reel": {"title": "Tổng hợp highlight trận đấu", "caption": "Tổng hợp những khoảnh khắc đáng chú ý trong trận đấu. Cùng xem lại nhé!", "hashtags": ["#BongDa", "#Highlight", "#TongHop"]}, "clips": [{"file": "clip_01.mp4", "title": "Bàn thắng trong trận đấu", "caption": "Bàn thắng trong trận đấu. Cùng xem lại khoảnh khắc này!", "hashtags": ["#BongDa", "#BanThang", "#Highlight"]}, {"file": "clip_02.mp4", "title": "Khoảnh khắc đáng chú ý trong trận đấu", "caption": "Khoảnh khắc đáng chú ý trong trận đấu. Cùng xem lại khoảnh khắc này!", "hashtags": ["#BongDa", "#KhoanhKhac", "#Highlight"]}]}. A segment whose event is a string outside EVENT_TYPES gets the 'other' defaults.
- AC4: These ids return 404 with {"detail": "not found"} for both `GET /highlights/{id}/meta` and `PUT /highlights/{id}/meta` (with a schema-valid body): a random unknown lowercase UUID, the uppercase form of an existing job's UUID, 'not-a-uuid', an existing UUID dir without job.json, and one with invalid job.json. No meta.json is created anywhere.
- AC5: On the AC3 job, PUT a body with reel {title 'Tổng hợp U23 Việt Nam', caption 'Những pha bóng hay nhất.', hashtags ['#BongDa','#U23','#VietNam']} and clips [{file 'clip_01.mp4', title 'Siêu phẩm phút cuối', caption 'Không thể tin nổi!', hashtags ['#BongDa','#BanThang','#Highlight']}, {file 'clip_02.mp4', title 'Khoảnh khắc đáng nhớ', caption 'Xem lại nào.', hashtags ['#BongDa','#KhoanhKhac','#Highlight','#VietNam']}]. It returns 200 with {job_id, reel, clips}: the same values, clip key order file, title, caption, hashtags. job_dir/meta.json now exists. A following GET returns the identical body, including the exact Vietnamese characters, and job.json's bytes are unchanged.
- AC6: Setup: after AC5's save, PUT a body with reel title 'Ngắn' and clip 2 hashtags ['#A','#B']. It returns 422 with detail exactly 'reel: title length 4; clip 2: hashtag count 2'. A body whose only problem is clip 1 hashtags ['#BongDa','#bongda','#X'] returns 422 'clip 1: duplicate hashtag #bongda'. In both cases meta.json's bytes are unchanged, and on a fresh job with no meta.json an invalid PUT creates none.
- AC7: A PUT whose clips' file list differs from the job's segment files in order returns 422 with detail "clips must match the job's clips". The tested cases are: a clip missing, an extra clip, the two clips swapped, and an unknown file name. meta.json is not written.
- AC8: These schema errors return 422 with a list `detail` (FastAPI validation): an extra top-level key, a missing `reel`, an extra key inside a clip, `hashtags` given as a string, and `title` given as a number. meta.json is not written.
- AC9: After a valid PUT, rewrite job.json so the segments' files are clip_01_v1.mp4 and clip_02_v1.mp4 (as PUT /segments does). GET then returns the saved reel and the default clip texts for the new files. If meta.json holds invalid JSON or a wrong shape, GET returns 200 with the AC3 defaults.
- AC10: `GET /jobs/{id}` returns 200 text/html whose body equals sportscut/web/preview.html. The HTML must contain:
- `section#meta` with `hidden`, holding an `h2` 'Tiêu đề, mô tả và hashtag', `ol#meta-list` and `button#save-meta[type=button][disabled]` 'Lưu tiêu đề và hashtag';
- `template#meta-row` with `li.meta-item` containing `h3.meta-name`, `input.meta-title[type=text]`, `textarea.meta-caption`, `input.meta-hashtags[type=text]` and `button.copy[type=button]` with text 'Sao chép';
- in `template#segment-row`, `button.voiceover[type=button][aria-pressed=false][hidden]` with text 'Lồng tiếng'.

The stylesheet/script resources are exactly ['/static/style.css', '/static/timefmt.js', '/static/filters.js', '/static/metafmt.js', '/static/preview.js'], all scripts are defer, the first `<a>` still has href '/', and there is no http:// or https://. `GET /static/metafmt.js` returns 200 with a javascript content type.
- AC11: Loaded with Node `require`, metafmt.js returns exactly:
- parseHashtags: '#BongDa  #Highlight,#KhoanhKhac\n' → ['#BongDa','#Highlight','#KhoanhKhac']; ' , ' → []; '' → []; null → []; 'BongDa #bongda' → ['BongDa','#bongda'].
- formatHashtags: ['#A','#B'] → '#A #B'; [] → ''.
- copyText({title:'Bàn thắng đẹp', caption:'Xem lại nhé!', hashtags:['#BongDa','#Highlight']}) → 'Bàn thắng đẹp\nXem lại nhé!\n#BongDa #Highlight'.
- clipSources: {clip_url:'/c/1.mp4'} → [{label:'Bản gốc',url:'/c/1.mp4'}]; adding voiceover_url '/c/1_vo.mp4' → [{label:'Bản gốc',url:'/c/1.mp4'},{label:'Lồng tiếng',url:'/c/1_vo.mp4'}]; voiceover_url '', null or 5 → only the original; clip_url null → []; undefined → [].

Object.keys sorted is ['clipSources','copyText','formatHashtags','parseHashtags'], and globalThis.SportsCutMeta === module.exports. The source contains none of document, window, fetch, localStorage, XMLHttpRequest or navigator, and loading it prints nothing and throws nothing.
- AC12: The preview.js source:
- contains `const M = globalThis.SportsCutMeta`, ``fetch(`/highlights/${encodeURIComponent(jobId)}/meta`)``, ``fetch(`/highlights/${encodeURIComponent(jobId)}/meta`, {``, `M.clipSources(seg)`, `M.formatHashtags(`, `M.parseHashtags(`, `M.copyText(`, `navigator.clipboard.writeText(`, `voiceover_url`, `aria-pressed`, 'Đã sao chép.', 'Không sao chép được. Hãy chọn chữ và sao chép thủ công.' and 'Đã lưu tiêu đề và hashtag.';
- has `saveMeta.disabled = true` before `async function loadJob()`;
- has a `loadMeta()` call after `acceptResponse(data)` inside loadJob, and one after the segments PUT fetch inside the `save.addEventListener("click"` handler;
- has no `innerHTML` and no http(s) URL.

All existing T-009/T-016 preview.js tests pass unchanged.
- AC13: Only two existing test files change. In tests/test_t016_acceptance.py, the preview resources list gains '/static/metafmt.js' and nothing else changes. In tests/test_t034b_acceptance.py::test_ac9_ac10_scope_and_size, the diff is pinned to commit 373a8438e6184d1048024bf48656139e158f2e2e as described in the spec. Both files pass, and the pinned test still asserts T-041's allowed files and its < 380 / ≤ 80 / ≤ 130 budgets.
- AC14: The README section '## Trang web: tải lên, xem trước và chỉnh mốc cắt' mentions 'Sao chép', 'Lưu tiêu đề và hashtag' and 'Lồng tiếng' and has no image link. Each of the T-009, T-016, T-023 and T-041 design specs ends with an '## Updated by T-028' note.
- AC15: `git diff --name-only $(git merge-base main HEAD)` plus untracked files lists only the task's `files` and docs/superpowers. Nothing under agent-office/, pyproject.toml, sportscut/export.py, sportscut/models.py, tests/conftest.py, index.html or app.js changes, and there is no new dependency, CDN, npm or build step. Changed lines outside docs/superpowers are < 430. `.venv/bin/python -m pytest -q tests/test_meta_page.py tests/test_t028_acceptance.py -rs` gives 0 failed and 0 skipped with node on PATH, and `.venv/bin/python -m pytest -q` gives 0 failed.

## Out of scope

- Generating metadata from match info (home/away/competition/kickoff), `sportscut cut --meta`, `sportscut meta`, captions.txt, POST /highlights meta fields and variants: the T-024 remainder.
- The LLM backend (T-025), commentary scripts (T-026) and voice-over generation or mixing (T-027). T-028 adds no `voiceover_url` to any API response.
- Client-side copy of the format rules, auto-adding '#', hashtag deduplication or normalisation (NFC/strip) on save.
- Autosave, unsaved-change warnings, undo, or a per-clip 'regenerate' button.
- Keeping clip texts across a segment re-cut (texts are keyed by clip file name).
- Any change to job.json's schema, `_validate_job`, PUT /segments, GET /highlights responses, the upload page (index.html/app.js) or pyproject.
- Browser automation tests, or a fake-DOM behavioural test of preview.js (pure module + static markers only).
- Fixing the other two-dot scope tests (test_t023 ac16); only the T-041 one that this task's files trigger is pinned.

## Decisions

- T-028 (R-005): T-028 does not wait for T-024. T-024 was dropped (diff_size) and is not on main. T-028 needs only T-009 (preview) and T-023 (template, format rules) and reports BLOCKED if the Step 0 command does not print READY. The board's depends_on T-024 is stale.
- T-028 (R-005): `job_dir/meta.json` is the single store of user-edited metadata. Its shape is the PUT body {reel:{title,caption,hashtags}, clips:[{file,title,caption,hashtags}]}, written atomically with `_write_job`. job.json, `_validate_job` and PUT /segments stay unchanged. A later T-024 API slice must seed or prefer meta.json and the GET defaults instead of adding title/caption/hashtags keys to job.json.
- T-028 (R-005): GET /highlights/{id}/meta defaults are `generate_meta(ClipFacts(event or 'other'))` per clip (unknown events become 'other'). The reel default is the constant 'Tổng hợp highlight trận đấu' / 'Tổng hợp những khoảnh khắc đáng chú ý trong trận đấu. Cùng xem lại nhé!' / ['#BongDa','#Highlight','#TongHop'], which matches T-024's planned generic reel. No names, minutes or scores are invented.
- T-028 (R-005): Clip metadata is keyed by clip file name. After PUT /segments re-cuts (new versioned names), clips fall back to defaults and the reel text stays. Saved entries for files that are gone are ignored.
- T-028 (R-005): PUT /highlights/{id}/meta validates in this order: schema (pydantic, extra=forbid, 422 list detail), job (404), clip files equal to the job's segment files in order (422 "clips must match the job's clips"), and format (422 '<where>: <problem>' joined by '; ', where is 'reel' or 'clip N', 1-based). Values are stored exactly as sent.
- T-028 (R-005): The format rules come from one place. `eval_meta.format_problems(ClipMeta)` is extracted from score_case unchanged, and both the eval and the API call it. Any rule change must keep the eval-meta score unchanged or higher.
- T-028 (R-005): Voice-over contract for T-027: a highlight in GET /highlights/{id} (and in the PUT /segments response) may carry `voiceover_url`, a non-empty string. The preview then shows `button.voiceover` ('Lồng tiếng', aria-pressed), which swaps the clip player between the original and the voice-over. T-028 itself never emits the field.
- T-028 (R-005): Pure JS logic lives in `sportscut/web/metafmt.js` (globalThis.SportsCutMeta + module.exports: parseHashtags, formatHashtags, copyText, clipSources). It loads between filters.js and preview.js. The T-016 exact resource-list test is updated to match; this amends the T-016 script-order decision.
- T-028 (R-005): The copy text is `title\ncaption\n` followed by the hashtags joined by single spaces, written with navigator.clipboard.writeText. A failure or a missing clipboard shows 'Không sao chép được. Hãy chọn chữ và sao chép thủ công.'. Status and errors reuse #status/#error, and user text is set only through value/textContent (no innerHTML).
- T-028 (R-005): One 'Lưu tiêu đề và hashtag' button saves the reel and all clip blocks together. It is disabled until GET /meta succeeds. There is no client-side validation; the server is the source of truth and its 422 detail is shown as 'Lỗi 422: <detail>'.
- T-028 (R-005): tests/test_t034b_acceptance.py::test_ac9_ac10_scope_and_size is pinned to commit 373a8438e6184d1048024bf48656139e158f2e2e (T-041 #43) instead of merge-base(main, HEAD). Otherwise it fails on every later branch that touches api.py or preview.*. It still checks T-041's files and budgets. This follows the T-013 precedent of editing a stale scope test.
- T-028 (R-005): New acceptance files must not put git-diff scope or size checks into the pytest suite. Scope and size are verified by the plan's commands and in review.
- T-028 (R-005): Size guardrail: < 430 changed lines outside docs/superpowers (production + README + the two edited old tests ≤ 225, Developer tests ≤ 80, Tester acceptance ≤ 120). There is no `sportscut eval` F1 gate because detection is untouched, and eval-meta must stay at the 1.0 baseline.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-009-build-the-preview-page-with-manual-design.md (Updated by T-028: the preview has a metadata section, a metafmt.js script and a voice-over toggle in the segment row; the segments save also reloads the metadata)`
- `docs/superpowers/specs/2026-11-23-t-016-add-event-badges-and-ch-b-design.md (Updated by T-028: the script order becomes timefmt.js, filters.js, metafmt.js, preview.js)`
- `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md (Updated by T-028: the format checks are exposed as eval_meta.format_problems and reused by PUT /highlights/{id}/meta)`
- `docs/superpowers/specs/2026-11-24-t-041-add-the-theo-d-i-c-design.md (Updated by T-028: the AC9/AC10 scope and size test is pinned to the T-041 commit 373a8438)`

Updated by T-050: the default clip meta from `generate_meta(ClipFacts(event))` now uses the hashed phrasing pick (see the T-023 spec's '## Updated by T-050'): the AC3 goal clip gives title 'Khoảnh khắc ghi bàn trong trận đấu' and caption 'Một bàn thắng đáng nhớ trong trận đấu. Hãy cùng xem lại nhé!', and the 'other' clip gives title 'Khoảnh khắc ấn tượng trong trận đấu' (caption unchanged); hashtags are unchanged.
