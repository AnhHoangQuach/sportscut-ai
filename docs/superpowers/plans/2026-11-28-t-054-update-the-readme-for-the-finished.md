# Plan T-054: Update the README for the finished player reel: remove the stale stub notes and document POST /players and the 'Theo dõi

Design: `docs/superpowers/specs/2026-11-28-t-054-update-the-readme-for-the-finished-design.md`.

## Implementation plan

# T-054: Update the README for the finished player reel

## Context
R-006 ("Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó") is finished: T-031 (touch detection), T-032 (team by shirt colour), T-033/T-051..T-053 (jersey number vote, `--min-confidence`, optional OCR), T-040 (`POST /players`, `GET /players/{job_id}/reel/{name}`) and T-041 (the 'Theo dõi cầu thủ' section of the upload page) are all merged. The README still has three out-of-date notes and does not document the player API or the player web section:

- README.md:200-201 (`## Phát hiện chạm bóng (T-031)`): "Ứng viên chưa có đội và số áo ... vẫn chưa trả về gì cho tới khi T-032/T-033 xong."
- README.md:285-286 (`## Theo dõi cầu thủ: xuất video tổng hợp (player)`): "Việc phát hiện pha chạm vẫn là stub cho đến khi T-031..T-033 hoàn thành."
- README.md:367 (`## Đội theo màu áo (T-032)`): "Chưa đọc số áo (T-033), nên video tổng hợp hiện chứa **mọi lần chạm bóng của cả đội đó**, chưa lọc theo số áo." This one is also out of date. It is in scope because the task is to remove the out-of-date notes (see Decisions).
- `## API HTTP` mentions `POST /players` only once, in the T-032 bullet (line 366). There is no curl example and no response shape.
- `## Trang web: ...` stops at step 14 and does not mention the 'Theo dõi cầu thủ' section.

This is a docs-only task. No file under `sportscut/` changes, no existing test file changes, and the eval cannot change.

## Ground truth (checked against main)

`sportscut/reel.py::make_player_reel` writes `player.json` (`MANIFEST_NAME`) with exactly these top-level keys:
- `query`: `{"team": query.team, "number": query.number}` (team normalised by `normalize_team`; `min_confidence` is **not** stored)
- `touches`: a list. Each item is `Touch.to_dict()` (`t`, `team`, `number`, `confidence`, `bbox`) plus `start` and `end`, the window that contains the touch. Both are `null` when no window contains it. `t`, `start` and `end` are rounded to 3 decimals.
- `clips`: a list of `{"start", "end"}` in time order
- `total_duration`: the sum of the clip lengths in seconds, rounded to 3 decimals
- `reel`: `player_<team without #>_<number>.mp4`, or `null` when there are no windows

`sportscut/api.py::create_player_reel` (`POST /players`, multipart form `file` | `job_id`, `team`, `number`):
- If both or neither of `file`/`job_id` are sent (an empty or whitespace `job_id` counts as absent), it returns 422 "send exactly one of file or job_id".
- A `PlayerQuery(team, number)` ValueError (unknown colour, number outside 1..99) returns 422. FastAPI form validation also returns 422 when `team`/`number` is missing or `number` is not an integer.
- An unknown `job_id`, or a job without `input`, returns 404 `{"detail":"not found"}`.
- An invalid uploaded video returns 400, an upload over `SPORTSCUT_MAX_UPLOAD_BYTES` returns 413, a ValueError from `make_player_reel` (for example the 'equally close' team tie) returns 422, and MediaError/OSError returns 500 "processing failed".
- A new upload creates a new job: `job.json` with `segments: []`. Its source plays through `GET /highlights/JOB_ID/source`.
- The response is exactly `{"job_id", "touches", "reel_url"}`. `touches` equals the manifest touches. `reel_url` is `null` when `manifest["reel"]` is null, otherwise the absolute URL of `GET /players/{job_id}/reel/{name}`.
- The API uses the default `MIN_CONFIDENCE` (0.5). There is no `min_confidence` form field.
- The request is synchronous (a plain `def` route, like `/highlights`).

`get_player_reel` returns 404 unless `name` equals `player.json`'s `reel` and the file exists. Otherwise it returns `video/mp4`.

Web (`sportscut/web/index.html`, `app.js`):
- Section `#player-section` with h2 "Theo dõi cầu thủ".
- Labels: "Tệp video", "Mã công việc có sẵn", "Màu áo" (colour picker), "Hoặc tên màu áo (ví dụ: red, blue)", "Số áo".
- Button "Tạo video cầu thủ".
- Results: h3 "Video tổng hợp", `#player-empty` "Không tìm thấy pha chạm bóng nào.", h3 "Các pha chạm bóng".
- Each touch is a button labelled `${t.toFixed(1)} s` that sets `playerSource.currentTime = touch.t`. `playerSource` is `/highlights/JOB_ID/source`.
- A typed colour name wins over the picker. Sending both or neither of file/job_id shows "Hãy chọn một tệp video hoặc nhập mã công việc."

## Design: exact README edits (Vietnamese text, use as written)
Add no `## ` or `### ` heading. Do not touch any JSON report, constants block or other section.

### Edit 1: `## Phát hiện chạm bóng (T-031)`
Replace the two lines 200-201:
~~~
- Ứng viên chưa có đội và số áo (`team`/`number` là `null`), nên `find_touches` và lệnh `sportscut player`
  vẫn chưa trả về gì cho tới khi T-032/T-033 xong.
~~~
with:
~~~
- `detect_touches` điền đội cho mỗi ứng viên (T-032, xem mục "Đội theo màu áo (T-032)") và số áo khi phiếu đủ
  tin cậy (T-033, xem mục "Số áo cầu thủ (T-033)"); `find_touches` và lệnh `sportscut player` trả về các pha
  chạm của đúng cầu thủ được hỏi (`--team`, `--number`).
~~~
Leave the debug bash block, the constants block and "Kết quả đo trong T-031:" with its JSON byte-identical.

### Edit 2: `## Đội theo màu áo (T-032)`
Replace line 367:
~~~
- Chưa đọc số áo (T-033), nên video tổng hợp hiện chứa **mọi lần chạm bóng của cả đội đó**, chưa lọc theo số áo.
~~~
with:
~~~
- Từ T-033, `find_touches` chỉ giữ các pha chạm của đội đó có số áo bỏ phiếu trùng `--number` (xem mục "Số áo cầu thủ (T-033)").
~~~
The line must keep the token `T-033`, because tests/test_t032_acceptance.py::test_ac13 requires `T-033` in this section.

### Edit 3: `## Theo dõi cầu thủ: xuất video tổng hợp (player)`
Replace lines 285-286:
~~~
không có pha chạm thì chỉ có manifest. Việc phát hiện pha chạm vẫn là stub cho
đến khi T-031..T-033 hoàn thành.
~~~
with:
~~~
không có pha chạm thì chỉ có manifest. Cách tìm pha chạm được mô tả trong các mục
"Phát hiện chạm bóng (T-031)", "Đội theo màu áo (T-032)" và "Số áo cầu thủ (T-033)";
`--min-confidence` (mặc định 0.5) đặt độ tin cậy tối thiểu của phiếu số áo.

`player.json` chứa:

- `query`: `{"team": ..., "number": ...}`, màu đội đã chuẩn hoá và số áo được hỏi;
- `touches`: mỗi pha chạm có `t` (giây), `team`, `number`, `confidence`, `bbox`, cùng `start`/`end`
  của đoạn clip chứa pha đó (`null` nếu không đoạn nào chứa nó);
- `clips`: các đoạn `{"start", "end"}` đã ghép vào video, theo thứ tự thời gian;
- `total_duration`: tổng độ dài các đoạn, tính bằng giây;
- `reel`: tên tệp video, `null` khi không có pha chạm.
~~~
The existing `cut ... --events goal --top 5` paragraph and its bash block stay after this text, unchanged.

### Edit 4: `## API HTTP`
Insert after the paragraph that ends "...trình duyệt không phát lại bản đã cache." (README.md:456-458) and before "Hiện việc xử lý diễn ra đồng bộ, ..." (line 460). Keep one blank line on each side:
~~~
Tạo video tổng hợp các pha chạm bóng của một cầu thủ (`POST /players`) từ một tệp mới hoặc từ video của
một job có sẵn, rồi tải video về:

```bash
curl -F file=@match.mp4 -F team=red -F number=10 http://127.0.0.1:8000/players
curl -F job_id=JOB_ID -F team=red -F number=10 http://127.0.0.1:8000/players
curl -o reel.mp4 "<reel_url>"
```

Phản hồi có dạng `{"job_id":"...","touches":[...],"reel_url":"http://127.0.0.1:8000/players/JOB_ID/reel/player_red_10.mp4"}`.
`touches` giống khoá `touches` của `player.json`, còn `reel_url` là `null` khi không có pha chạm nào. `team`
nhận tên màu hoặc `#rrggbb`, `number` là số nguyên 1–99, và API dùng độ tin cậy mặc định 0.5. `file` và `job_id`
loại trừ lẫn nhau: gửi cả hai hoặc không gửi cái nào đều trả 422. Màu đội hoặc số áo sai (kể cả màu cách đều hai
đội) trả 422, `job_id` không tồn tại trả 404, video tải lên không hợp lệ trả 400 và upload quá lớn trả 413. Khi
gửi tệp, API tạo một job mới; video gốc của job đó phát được qua `GET /highlights/JOB_ID/source`. Yêu cầu chạy
đồng bộ như `/highlights`.
~~~

### Edit 5: `## Trang web: tải lên, xem trước và chỉnh mốc cắt`
Insert after step 14 (line 490-491) and before "Trang trả về lỗi 404 nếu `JOB_ID` không tồn tại.":
~~~
15. Mục "Theo dõi cầu thủ" trên trang `http://127.0.0.1:8000/` tạo video tổng hợp cho một cầu thủ. Chọn
    "Tệp video" hoặc nhập "Mã công việc có sẵn" (chỉ một trong hai). Chọn "Màu áo" hoặc gõ tên màu vào ô
    "Hoặc tên màu áo (ví dụ: red, blue)" (tên màu được ưu tiên), nhập "Số áo" rồi nhấn "Tạo video cầu thủ".
    Trang hiện "Video tổng hợp" và danh sách "Các pha chạm bóng"; nhấn một pha (ví dụ "3.0 s") để tua video
    gốc tới lúc đó. Khi không có pha chạm nào, trang hiện "Không tìm thấy pha chạm bóng nào."
~~~

## Files
- `README.md`: edits 1-5 only. About 45 changed lines (insertions plus deletions).
- `tests/test_readme_player_docs.py`: new Developer test, at most 60 lines.
- `tests/test_t054_acceptance.py`: new Tester acceptance test, at most 45 lines.
- The orchestrator commits the spec and plan in `docs/superpowers/` and appends the INDEX row and DECISIONS entries.

## Interfaces
No code interface changes. The tests read `README.md`, `sportscut/web/index.html` and `sportscut/web/app.js`, and call `sportscut.reel.make_player_reel` and `sportscut.api.app` through `fastapi.testclient.TestClient`.

Section helper used by both test files: `sec(h) = text.split(h + "\n", 1)[1].split("\n## ", 1)[0]`. This is the existing pattern in tests/test_preview.py:297.

## Steps (test first)
1. Write `tests/test_readme_player_docs.py` (below) and run `python -m pytest -q tests/test_readme_player_docs.py`. It must fail on the absence and order assertions, for example `vẫn là stub` is still present and `POST /players` is missing from the API paragraph.
2. Apply README edits 1-5 exactly as written above.
3. Re-run `python -m pytest -q tests/test_readme_player_docs.py`. Expect all passed.
4. Run the full suite: `python -m pytest -q`. Expect 0 failed. Existing README tests that must stay green: test_t031_acceptance::test_ac13, test_t032_acceptance::test_ac13, test_t033b::test_ac11, test_t033c::test_ac8, test_preview, test_t009, test_t016, test_web_filters, test_t005, test_t006, test_t042_round2.
5. Heading check (AC4): `diff <(git show main:README.md | grep -E '^#{2,3} ') <(grep -E '^#{2,3} ' README.md)` prints nothing.
6. Scope and size check: `git diff --stat main -- . ':!docs/superpowers'` lists only README.md, and the two new test files appear as untracked or added. `git diff --numstat main -- README.md` plus the line counts of the two new tests total < 150. `git diff main -- sportscut tests/fixtures conftest.py tests/conftest.py pyproject.toml` is empty.
7. Eval check (AC6):
   - `python tests/fixtures/eval/build.py && python -m sportscut eval tests/fixtures/eval --json`
   - `python tests/fixtures/eval_player/build.py && python -m sportscut eval-player tests/fixtures/eval_player --json`

   Compare with the same commands on main. Every key must be equal except `seconds_per_min` (timing). Expected eval-player: f1 0.9474, precision 0.973, recall 0.9231, id_accuracy 0.973, touch_f1_any 0.9737.

## Assumptions
- The README is written in Vietnamese like the rest of it. Code identifiers, form field names and labels are copied verbatim from the code.
- Sections are cross-referenced in prose by their heading text in quotes, not as `## ` inline code. This keeps `"\n## "` section splitting in existing tests unaffected.
- `bbox` is listed without a format because its meaning belongs to player.py, not to this doc.
- `GET /players/{job_id}/reel/{name}` is documented only through `reel_url` and `curl -o`. Its 404 rules are already tested by T-040.


## Test plan

- Developer, tests/test_readme_player_docs.py (≤ 60 lines, no ffmpeg, no git): a module-level `README = (ROOT/'README.md').read_text(encoding='utf-8')` and a `sec(heading)` helper using split(heading+'\n',1)[1].split('\n## ',1)[0].
- test_stale_notes_removed (AC1): assert none of the three stale strings is in README.
- test_t031_and_t032_bullets (AC5 part, Edit 2): the T-031 section contains 'T-032', 'T-033', 'find_touches' and 'sportscut player'. json.loads of the block after 'Kết quả đo trong T-031:' has touch_f1_any == 0.9737. The T-032 section still contains 'T-033'.
- test_player_section_lists_manifest_fields (AC5): monkeypatch reel.probe_duration → 10.0, player.find_touches → [Touch(5.0,'red',10,0.9,None)], reel.export_clips → lambda *a: [] and reel.concat_clips → lambda *a: None. Call reel.make_player_reel('v.mp4', PlayerQuery('red',10), tmp_path). For every key in the returned manifest and in manifest['touches'][0], assert f'`{key}`' is in the player section. Also assert 'player.json' and '--min-confidence' are in it.
- test_api_player_paragraph (AC2): the three curl lines are inside one ```bash block of the API section. Order: '/highlights/JOB_ID/segments' < 'POST /players' < 'Hiện việc xử lý diễn ra đồng bộ'. The paragraph between 'POST /players' and 'Hiện việc xử lý' contains '-F team=', '-F number=', 'reel_url', 'job_id', '422', '404', 'null', '#rrggbb' and 'đồng bộ'.
- test_web_step_15 (AC3): the web section has a line starting with '15. ' and contains the labels. Each label except 'Theo dõi cầu thủ' is in sportscut/web/index.html, and 'currentTime = touch.t' is in sportscut/web/app.js.
- Tester, tests/test_t054_acceptance.py (≤ 45 lines, written from the ACs, not copied from the Developer test): importorskip('fastapi'), TestClient(app), and an autouse fixture setting SPORTSCUT_DATA_DIR=tmp_path, as in tests/test_players_api.py. A parametrized test posts each bad request and asserts status 422: file and job_id together, neither, team='zzz', number=0, number='abc', and find_touches raising ValueError('equally close'). An unknown uuid job_id gives 404.
- Tester: test_existing_job_no_touches builds jobs/<uuid>/{input,job.json}, with input a copy of the synthetic_video fixture so probe_duration works, and monkeypatches player.find_touches → []. POST with job_id gives 200, set(body) == {'job_id','touches','reel_url'}, touches == [] and reel_url is None.
- Tester: test_readme_states_checked_codes asserts that every code exercised above ('422', '404') plus 'reel_url', 'null' and 'job_id' appears in the README player paragraph between 'POST /players' and 'Hiện việc xử lý', and that the paragraph does not claim an async/background job.
- Tester: confirm the tests can fail by temporarily restoring the old README line 285 ('vẫn là stub') in a scratch copy, or by asserting against `git show main:README.md`. In that run, test_stale_notes_removed and the API test fail. Restore afterwards and report.
- Commands: `python -m pytest -q` (quote the summary line); the AC4 heading diff; the scope/size commands; and the eval and eval-player JSON on this branch and on main, compared key by key except seconds_per_min.
