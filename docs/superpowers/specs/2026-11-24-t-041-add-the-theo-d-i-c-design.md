# T-041: Add the 'Theo dõi cầu thủ' section to the web page

Request R-006. Plan: `docs/superpowers/plans/2026-11-24-t-041-add-the-theo-d-i-c.md`.

## Product Owner request

Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó.

## Goal

Scope: the web half of the original T-034 spec. Add the exact `#player-section` HTML block after `</form>` of `#highlights-form` in sportscut/web/index.html. Append the JS to the END of sportscut/web/app.js: POST /players with playerData, team name falling back to the colour picker, the reel or 'Không tìm thấy pha chạm bóng nào.', touch buttons that set #player-source currentTime = touch.t (built with textContent, no innerHTML), and source src `/highlights/${encodeURIComponent(data.job_id)}/source`. Update style.css: add #player-busy and #player-error to the existing rules, plus `video{width:100%}` and `#player-section{margin-top:2rem}`. Append the 'Updated by T-034' note to the T-008 design spec.

ACs carried over: original AC10, AC11 and AC12 (tests/test_web.py and tests/test_t008_acceptance.py unchanged and green: only /static/style.css and /static/app.js referenced, no http(s):// or content-type, first fetch( and finally are still the /highlights ones).

New size AC: changed lines outside docs/superpowers are under 380. Budgets: HTML/JS/CSS about 105 lines, Developer tests in tests/test_player_page.py at most 80 lines, Tester acceptance in tests/test_t034b_acceptance.py at most 130 lines.

Files: sportscut/web/index.html, sportscut/web/app.js, sportscut/web/style.css, tests/test_player_page.py, tests/test_t034b_acceptance.py, docs/superpowers/specs/2026-11-23-t-008-serve-a-web-upload-page-for-design.md, plus docs/superpowers (spec, plan, INDEX row).

Verify: `python -m pytest -q` shows 0 failed; the numstat stays under 380 non-doc lines. No eval effect.

## Acceptance criteria

- AC1 (markup): GET / returns 200 HTML. It contains exactly one <section id="player-section">, which comes after <form id="highlights-form"> and contains an <h2> with text 'Theo dõi cầu thủ', and exactly one <form id="player-form">. The player form has these inputs (id/name/type): player-file/file/file (accept="video/*"); player-job-id/job_id/text; player-team-color/team_color/color (value "#ff0000"); player-team-name/team_name/text; player-number/number/number (min="1" max="99" step="1"). Each has a <label for> with non-empty Vietnamese text. The page also has button#player-submit of type submit, #player-busy[role=status][hidden], #player-error[role=alert][aria-live=assertive][hidden], div#player-result[hidden], video#player-reel and video#player-source (both with controls and no src attribute), p#player-empty[hidden] with text 'Không tìm thấy pha chạm bóng nào.', and ol#player-touches. Each id appears exactly once.
- AC2 (T-008 and T-016 invariants): the href/src values in the HTML (from a parser and from the regex (?:href|src)="([^"]+)") are exactly ['/static/style.css', '/static/app.js']. Neither the HTML, app.js nor style.css matches https?:// (case-insensitive). app.js does not contain 'content-type' (case-insensitive) and does not contain 'innerHTML'. tests/test_web.py, tests/test_t008_acceptance.py, tests/test_web_filters.py and tests/test_t016_acceptance.py are unchanged (git diff --exit-code main...HEAD on them exits 0) and pass.
- AC3 (JS contract): app.js contains fetch("/players" with method "POST" and body: playerData. It reads #player-team-name .value.trim() with a fallback (||) to #player-team-color .value, appends "team" and "number", appends "file" when a file is chosen and "job_id" otherwise, and contains the template `/highlights/${encodeURIComponent(data.job_id)}/source`, `playerSource.currentTime = touch.t` inside a "click" listener, document.createElement("button"), .textContent, and data.reel_url. Ordering: source.index('fetch(') == source.index('fetch("/highlights"'); the first 'finally' comes before source.index('#player-form'); and source.index('#player-form') is greater than the index of the last line of the original highlights handler ('busy.hidden = true').
- AC4 (behaviour, node; the test skips if node is not on PATH): app.js runs under node against a minimal fake document and a stubbed fetch. On submit with no file, job id ' abc ', a blank team name, colour '#ff0000' and number '10', fetch is called once with '/players' and method 'POST', and the FormData has job_id='abc', team='#ff0000', number='10' and no 'file'. A 200 response of {job_id: 'j 1', touches: [{t: 1.5}, {t: 4}], reel_url: '/players/j%201/reel/player_ff0000_10.mp4'} sets #player-source.src to '/highlights/j%201/source' and #player-reel.src to the reel_url, shows #player-result and hides #player-empty. It renders 2 <li> items, each holding one button with type 'button' and textContent '1.5 s' and '4.0 s'. Calling the second button's click listener sets #player-source.currentTime to 4. Afterwards #player-submit.disabled is false and #player-busy.hidden is true. With team name ' blue ', the FormData team is 'blue'.
- AC5 (behaviour, node; skipped if node is missing): (a) reel_url null with touches [] hides #player-reel, shows #player-empty, shows #player-result and leaves #player-touches with 0 children. (b) A 422 response {detail: 'bad team'} sets #player-error.textContent to 'Lỗi 422: bad team', shows #player-error and keeps #player-result hidden. A 422 response whose detail is an array [{msg: 'x'}, {msg: 'y'}] gives 'Lỗi 422: x; y'. (c) Both a file and a job id, or neither, shows 'Hãy chọn một tệp video hoặc nhập mã công việc.' and fetch is not called. (d) fetch rejecting shows 'Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ.', and #player-submit.disabled is false afterwards.
- AC6 (CSS): style.css contains a selector list '#busy,\n#player-busy {' and a selector list '#error,\n#player-error {' (whitespace-normalised: '#busy, #player-busy {' and '#error, #player-error {'). It also contains a 'video {' rule with 'width: 100%' and a '#player-section {' rule with 'margin-top: 2rem'. The existing '#player {' and '.clip-player {' rules are still present.
- AC7 (spec note): docs/superpowers/specs/2026-11-23-t-008-serve-a-web-upload-page-for-design.md ends with a '## Updated by T-034' section that mentions 'Theo dõi cầu thủ', '#player-section' and '#highlights-form'.
- AC8: `python -m pytest -q` reports 0 failed and 0 errors.
- AC9 (scope): `git diff --exit-code main...HEAD -- sportscut/api.py sportscut/reel.py sportscut/player.py sportscut/pipeline.py sportscut/web/preview.html sportscut/web/preview.js sportscut/web/filters.js sportscut/web/timefmt.js pyproject.toml tests/conftest.py agent-office` exits 0. No existing test file is modified. The only non-doc files changed are sportscut/web/index.html, sportscut/web/app.js, sportscut/web/style.css, tests/test_player_page.py and tests/test_t034b_acceptance.py.
- AC10 (size): `git diff --numstat main...HEAD -- . ':(exclude)docs/superpowers'` totals (added + deleted) under 380 lines. tests/test_player_page.py has <= 80 lines and tests/test_t034b_acceptance.py has <= 130 lines. (updated by T-015: AC9's file list and allowlist and AC10's size cap applied to T-041's own diff only; on later branches test_ac9_ac10_scope_and_size checks only that pyproject.toml, tests/conftest.py and agent-office/ are unchanged against the merge base) (updated by T-025: pyproject.toml is no longer a frozen path; the llm extra is added by T-025)

## Out of scope

- Any API change (POST /players and GET reel are done in T-040), and any change to reel.py, player.py or pipeline.py.
- Real touch detection (T-031..T-033). Until then, real uploads usually show 'Không tìm thấy pha chạm bóng nào.'
- A YouTube URL as input to the player form.
- mm:ss time formatting, loading timefmt.js on the upload page, auto-play on seek, or highlighting the active touch.
- A download link for the reel, query history, or several reels per job.
- Progress reporting or async processing.
- README documentation for the player section.
- Editing existing tests, including the fragile two-dot git diff scope tests in test_t013/test_t023.

## Decisions

- T-041 (R-006): T-041 is T-034B, the web half of T-034. It reuses the T-034 checkpoint ccec97b web design (ids prefixed player-, section after #highlights-form, JS appended at the end of app.js) with small trims: a showPlayerError helper, no play() on seek, and the result hidden while a new request runs.
- T-041 (R-006): The HTML has no src/href attributes. Both videos get src from JS, so the T-008/T-016 'only /static/style.css and /static/app.js' checks hold. No new static asset files are added.
- T-041 (R-006): The player JS is appended after the highlights handler and uses only new top-level names (playerForm, playerSubmit, playerBusy, playerError, playerResult, playerReel, playerEmpty, playerTouches, playerSource, showPlayerError). The first fetch( and the first finally in app.js stay the /highlights ones.
- T-041 (R-006): team = the trimmed #player-team-name if non-blank, else the #player-team-color value (#rrggbb, accepted by PlayerQuery). The client checks only file XOR job id; the API stays authoritative for team and number (422 shown as 'Lỗi 422: <detail>').
- T-041 (R-006): The touch list is built with createElement/textContent only (no innerHTML). Each button shows `${t.toFixed(1)} s` and sets #player-source.currentTime = touch.t on click. The source src is `/highlights/${encodeURIComponent(data.job_id)}/source`.
- T-041 (R-006): A null reel_url hides #player-reel (src removed) and shows 'Không tìm thấy pha chạm bóng nào.'. Zero touches is a normal result, not an error.
- T-041 (R-006): CSS reuses the #busy/#error rules by adding #player-busy/#player-error to their selector lists, and adds video{width:100%} and #player-section{margin-top:2rem}.
- T-041 (R-006): JS behaviour is acceptance-tested in node with a minimal fake DOM, skipped when node is absent, matching the existing node-based web tests. Developer tests are static (HTML parse plus source markers).
- T-041 (R-006): Size guardrail: changed lines outside docs/superpowers < 380. Budgets are HTML/JS/CSS about 110, Developer tests <= 80, Tester acceptance <= 130. No eval/F1 gate, because accuracy is untouched.
- T-041 (R-006): The T-008 design spec gets an '## Updated by T-034' note: its 'no preview player' exclusion applies only to #highlights-form.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-008-serve-a-web-upload-page-for-design.md`
- `docs/superpowers/specs/2026-11-24-t-040-add-post-players-and-get-players-design.md`
- `docs/superpowers/specs/2026-11-23-t-016-add-event-badges-and-ch-b-design.md`

## Updated by T-028

Updated by T-028: the T-028 plan asked to pin test_ac9_ac10_scope_and_size to the T-041 commit 373a8438. T-015 (Tech Lead, round 1) had already rewritten that test to check only the project-wide frozen paths against the merge base, so it no longer fails on later branches. T-028 leaves the test unchanged (see the Deviations section of the T-028 plan).
