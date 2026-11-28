# T-054: Update the README for the finished player reel: remove the stale stub notes and document POST /players and the 'Theo dõi

Request R-006. Plan: `docs/superpowers/plans/2026-11-28-t-054-update-the-readme-for-the-finished.md`.

## Product Owner request

Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó.

## Goal

Docs-only follow-up for R-006. No production code changes and no eval effect. Files: README.md, tests/test_readme_player_docs.py (new, at most 60 lines), plus docs/superpowers (spec, plan, INDEX row, DECISIONS entry). Steps: (1) In `## Phát hiện chạm bóng (T-031)`, change the bullet at README.md:200-201 ('Ứng viên chưa có đội và số áo ... vẫn chưa trả về gì cho tới khi T-032/T-033 xong'). It should now say that `detect_touches` fills in the team (T-032), and the number when the vote is confident (T-033), and that `find_touches` and `sportscut player` return the queried player's touches. Leave the historic T-031 JSON report as it is. (2) In `## Theo dõi cầu thủ: xuất video tổng hợp (player)`, replace the sentence 'Việc phát hiện pha chạm vẫn là stub cho đến khi T-031..T-033 hoàn thành.' with a pointer to the T-031/T-032/T-033 sections, `--min-confidence`, and a short description of the `player.json` fields (query, touches with t/start/end/confidence, clip windows, total duration). Take these fields from sportscut/reel.py exactly; do not invent them. (3) In `## API HTTP`, insert a player paragraph after the PUT /segments paragraph and before 'Hiện việc xử lý diễn ra đồng bộ'. It needs a bash block with `curl -F file=@match.mp4 -F team=red -F number=10 http://127.0.0.1:8000/players`, `curl -F job_id=JOB_ID -F team=red -F number=10 http://127.0.0.1:8000/players` and `curl -o reel.mp4 "<reel_url>"`. It also states the response shape `{"job_id","touches","reel_url"}` (reel_url null when there are no touches), that file and job_id are mutually exclusive (422), that a bad team or number gives 422, that an unknown job gives 404, and that the request runs synchronously like /highlights. Check every claim against sportscut/api.py create_player_reel and get_player_reel. (4) In `## Trang web: tải lên, xem trước và chỉnh mốc cắt`, add a numbered step 15 for the 'Theo dõi cầu thủ' section: choose a shirt colour or type a colour name, enter the number, then view the reel and the touch list. Clicking a touch seeks the source video. When there are no touches the page shows 'Không tìm thấy pha chạm bóng nào.' Take the labels from sportscut/web/index.html and app.js. Acceptance criteria: AC1: the README contains neither 'vẫn chưa trả về gì cho tới khi T-032/T-033 xong' nor 'vẫn là stub'. AC2: the README contains 'POST /players' in the `## API HTTP` section, plus `-F team=`, `-F number=`, `reel_url` and `job_id`. AC3: the web section contains 'Theo dõi cầu thủ' and 'Không tìm thấy pha chạm bóng nào.'. AC4: every README heading that exists on main still exists, in the same order. AC5: the Tester checks each documented status code and response field against api.py with the existing TestClient pattern, monkeypatching find_touches as tests/test_players_api.py does. AC6: `python -m pytest -q` reports 0 failed, and the eval and eval-player JSON are unchanged from main. Budget: under 150 changed lines outside docs/superpowers. Do not edit any existing test file.

## Acceptance criteria

- AC1: README.md contains none of the strings 'vẫn chưa trả về gì cho tới khi T-032/T-033 xong', 'vẫn là stub' or 'chưa lọc theo số áo'.
- AC2: the `## API HTTP` section (from the heading up to the next '\n## ') contains 'POST /players', '-F team=', '-F number=', 'reel_url', 'job_id' and the three exact lines 'curl -F file=@match.mp4 -F team=red -F number=10 http://127.0.0.1:8000/players', 'curl -F job_id=JOB_ID -F team=red -F number=10 http://127.0.0.1:8000/players' and 'curl -o reel.mp4 "<reel_url>"' inside one ```bash block. In that section, the index of 'POST /players' is greater than the index of '/highlights/JOB_ID/segments' and smaller than the index of 'Hiện việc xử lý diễn ra đồng bộ'. The player paragraph (from 'POST /players' to 'Hiện việc xử lý') mentions '422', '404', 'null', '#rrggbb' and 'đồng bộ'.
- AC3: the `## Trang web: tải lên, xem trước và chỉnh mốc cắt` section contains a line starting with '15. ', and contains 'Theo dõi cầu thủ', 'Không tìm thấy pha chạm bóng nào.', 'Màu áo', 'Số áo', 'Tạo video cầu thủ', 'Video tổng hợp' and 'Các pha chạm bóng'. Each of these labels except 'Theo dõi cầu thủ' (which is the h2) also occurs in sportscut/web/index.html, and app.js contains 'currentTime = touch.t'.
- AC4: the ordered list of '## ' and '### ' heading lines in README.md is identical to main's. `diff <(git show main:README.md | grep -E '^#{2,3} ') <(grep -E '^#{2,3} ' README.md)` prints nothing.
- AC5: the `## Theo dõi cầu thủ: xuất video tổng hợp (player)` section names every top-level key of the manifest that reel.make_player_reel returns (query, touches, clips, total_duration, reel) and every key of a manifest touch (t, team, number, confidence, bbox, start, end), each as `key` in backticks, plus 'player.json' and '--min-confidence'. The `## Phát hiện chạm bóng (T-031)` section contains 'T-032', 'T-033', 'find_touches' and 'sportscut player', and its 'Kết quả đo trong T-031:' JSON still parses with touch_f1_any 0.9737.
- AC6: the Tester's TestClient tests, with player.find_touches monkeypatched, confirm each status code and response field in the README player paragraph: both or neither of file/job_id gives 422; team 'zzz' gives 422; number 0 and number 'abc' give 422; a find_touches ValueError (the 'equally close' tie) gives 422; an unknown job_id gives 404; an existing job with no touches gives 200 with keys exactly {job_id, touches, reel_url} and reel_url None; and each of these codes appears in the README player paragraph.
- AC7: `python -m pytest -q` reports 0 failed. No existing test file is modified, and no file under sportscut/, tests/fixtures/, conftest.py, tests/conftest.py or pyproject.toml changes. `sportscut eval tests/fixtures/eval --json` and `sportscut eval-player tests/fixtures/eval_player --json` match main on every key except seconds_per_min (eval-player f1 0.9474).
- AC8: changed lines outside docs/superpowers (README insertions plus deletions, plus the lines of the two new test files) total < 150. tests/test_readme_player_docs.py is ≤ 60 lines and tests/test_t054_acceptance.py is ≤ 45 lines.

## Out of scope

- Any change under sportscut/ (api.py, reel.py, player.py, web/), including adding a min_confidence form field to POST /players.
- Editing or deleting any existing test file, including the branch-gated T-031/T-032 README tests.
- Rewriting historic eval reports, 'Mục tiêu tiếp theo' lines, 'Trước/Sau T-0xx' JSON blocks or constants blocks.
- Adding, renaming or reordering README headings, or adding a new section for the player API.
- Documenting GET /players/{job_id}/reel/{name} error rules beyond reel_url and curl -o.
- Updating the T-030/T-040/T-041 specs. Their behaviour is unchanged, and the README is the only document that is out of date.
- English translation of the README, screenshots or images (existing tests forbid '![' in the web section).

## Decisions

- T-054 is docs-only: README.md plus two new test files (tests/test_readme_player_docs.py ≤ 60 lines, tests/test_t054_acceptance.py ≤ 45 lines). The budget is < 150 changed lines outside docs/superpowers. Scope, size, heading order and eval equality are checked by commands in review, not by pytest git-diff tests (T-028/T-049/T-051 rule).
- Besides the two notes named in the request, the out-of-date T-032 bullet 'Chưa đọc số áo (T-033) ... chưa lọc theo số áo' is replaced by 'Từ T-033, find_touches chỉ giữ ... số áo bỏ phiếu trùng --number'. The new line keeps the token 'T-033' that test_t032_acceptance::test_ac13 requires.
- No README heading is added, removed or renamed. The player API docs are a paragraph inside '## API HTTP', placed after the PUT /segments paragraph and before 'Hiện việc xử lý diễn ra đồng bộ'. The web docs are numbered step 15 inside the existing list.
- README sections refer to each other by quoted heading text, never as an inline '## ...', so existing '\n## ' section splitting is unaffected.
- The documented player.json fields are exactly what reel.make_player_reel writes: query{team,number}, touches[t,team,number,confidence,bbox,start,end], clips[{start,end}], total_duration and reel. The Developer test derives the keys by calling make_player_reel with find_touches, probe_duration, export_clips and concat_clips stubbed, so a later manifest change fails the doc test.
- The README states that POST /players uses the default min confidence 0.5 and has no confidence field. 422 covers both or neither of file/job_id, a bad team or number (including the equally-close tie) and FastAPI form errors. 404 covers an unknown job. 400 covers an invalid upload, 413 an oversize upload, and the request is synchronous like /highlights.
- Historic T-029/T-031/T-032/T-033 eval JSON reports in the README stay byte-identical.

## Existing specs this task changes

- (none)
