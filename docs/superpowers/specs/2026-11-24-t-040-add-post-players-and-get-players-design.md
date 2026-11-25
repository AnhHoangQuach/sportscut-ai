# T-040: Add POST /players and GET /players/{job_id}/reel/{name} to the API

Request R-006. Plan: `docs/superpowers/plans/2026-11-24-t-040-add-post-players-and-get-players.md`.

## Product Owner request

Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó.

## Goal

Scope: the API half of the original T-034 spec, design steps 1–4. The steps are: the `_save_upload(file, path)` DRY refactor of create_highlights; the sync `POST /players` (multipart file OR form job_id, plus team and number; order a–g, error mapping and new-upload cleanup exactly as specified); and `GET /players/{job_id}/reel/{name}` (name='get_player_reel', manifest-authorised before any path join).

ACs carried over: original AC0 (precondition prints READY), AC1–AC9, AC12 (all existing tests pass unchanged) and AC13's protected-file rule.

New size AC: changed lines outside docs/superpowers are under 380. Budgets: sportscut/api.py about 115 lines, Developer tests in tests/test_players_api.py at most 110 lines, Tester acceptance in tests/test_t034a_acceptance.py at most 150 lines. Use parametrize for the AC6 422 cases, the AC7 404 cases and the AC8 404 cases.

Files: sportscut/api.py, tests/test_players_api.py, tests/test_t034a_acceptance.py, plus docs/superpowers (spec, plan, INDEX row).

Verify: `python -m pytest -q` shows 0 failed; `git diff --numstat main...HEAD` stays under 380 non-doc lines. No eval effect.

## Acceptance criteria

- AC0: The Step 0 precondition command prints READY on the task base. Otherwise the task reports BLOCKED and changes no file.
- AC1: The request is POST /players with multipart file=('match.mp4', synthetic 6 s video bytes), team='RED', number=10, and `sportscut.player.find_touches` monkeypatched to return [Touch(1.0,'red',10,0.9,None), Touch(4.5,'red',10,0.8,None)]. It returns 200, and: the body keys are exactly {job_id, touches, reel_url}; job_id is a canonical lowercase uuid4 string; find_touches was called exactly once with (<data_dir>/jobs/<job_id>/input, PlayerQuery('red', 10)); <data_dir>/jobs/<job_id>/input has the same bytes as the upload; <data_dir>/jobs/<job_id>/player/ contains exactly {player_red_10.mp4, player.json}; body.touches equals player.json['touches']; and reel_url ends with `/players/<job_id>/reel/player_red_10.mp4`.
- AC2: For the AC1 job, job.json parses to exactly the keys {source_name, source_url, duration, version, segments}, with source_name 'match.mp4', source_url null, |duration - 6| <= 0.2, version 0 and segments []. GET /highlights/<job_id> returns 200 with highlights == [], and GET /highlights/<job_id>/source returns 200 with content-type video/mp4.
- AC3: GET reel_url returns 200 with content-type video/mp4, and the body bytes equal player/player_red_10.mp4 on disk. `sportscut.media.probe_duration` of that file is > 0.
- AC4: The existing job is created by POST /highlights with the synthetic video and `sportscut.pipeline.run` monkeypatched to return []. A sentinel file is written into its clips/ dir and job.json bytes are snapshotted. POST /players with form job_id=<that id>, team='blue', number=7 then returns 200, and: body.job_id equals that id; find_touches received <that job dir>/input; job.json bytes and every file under clips/ are unchanged; the number of directories under <data_dir>/jobs is unchanged; and <that job dir>/player/ exists.
- AC5: When find_touches returns [] on a new upload, the response is 200 with touches == [] and reel_url null. player/player.json has reel null, and player/ contains no .mp4 file.
- AC6 (one parametrized test): each of these returns 422: team='plaid'; number=0; number=100; number='abc'; missing team; missing number; both file and job_id; neither file nor job_id; job_id='   ' with no file. In every case find_touches (a fake that calls pytest.fail) is not called and <data_dir>/jobs has no new entry.
- AC7 (one parametrized test): POST /players with a valid team and number and form job_id set to a fresh uuid4, to an existing job's id in uppercase, or to '../etc' returns 404 with JSON exactly {"detail": "not found"}, and find_touches is not called.
- AC8 (one parametrized test): GET /players/{job_id}/reel/{name} returns 404 for each of: a fresh uuid4 job; a valid job with no player/ dir; name 'player.json'; name 'input'; name 'player_blue_7.mp4' when the current reel is player_red_10.mp4; and the encoded traversal name '..%2Finput'. All cases except '..%2Finput' return JSON exactly {"detail": "not found"}. In every case the response body is not the bytes of input or player.json.
- AC9: Error mapping and cleanup. (a) An upload of b'not a video' (real ffmpeg, find_touches not called) gives 400; the detail does not contain str(<data_dir>), and <data_dir>/jobs has no entries afterwards. (b) A fake find_touches raising MediaError('boom') on a new upload gives 500 {"detail": "processing failed"}, and the new job dir is removed. (c) The same on an existing job_id gives 500, and that job dir, its input bytes and its job.json bytes are unchanged. (d) A fake find_touches raising ValueError('bad') gives 422. (e) With SPORTSCUT_MAX_UPLOAD_BYTES=10 and a larger upload, the response is 413 and <data_dir>/jobs has no entries afterwards.
- AC12: All existing tests pass without changes, including tests/test_api.py and the tests/test_t005, t006 and t007 acceptance files, which cover the `_save_upload` refactor. `python -m pytest -q` reports 0 failed and 0 errors.
- AC13: `git diff --exit-code main...HEAD -- sportscut/reel.py sportscut/player.py sportscut/pipeline.py sportscut/evaluate.py sportscut/eval_player.py sportscut/web pyproject.toml tests/conftest.py` exits 0, and no existing test file is changed.
- AC14 (size): `git diff --numstat main...HEAD -- . ':(exclude)docs/superpowers'` totals (added + deleted) under 380 lines. The only files are sportscut/api.py (about 115), tests/test_players_api.py (<= 110 lines) and tests/test_t034a_acceptance.py (<= 150 lines).

## Out of scope

- The 'Theo dõi cầu thủ' web section (index.html, app.js, style.css) and the T-008 spec note: that is T-041 (T-034B).
- Real touch detection (shirt colour or number recognition): T-031..T-033. The real detect_touches still returns [].
- A YouTube URL as input to POST /players.
- Exposing pre/post/merge_gap over HTTP.
- Several reels per job, query history, cleanup of old reels or job dirs.
- Async or background processing, progress reporting, auth.
- A catch-all route that rewrites Starlette's default 404 body for names containing '/'.
- Any change to reel.py, player.py, pipeline.py, the eval commands, pyproject dependencies, conftest.py or existing tests.

## Decisions

- T-040 (R-006): T-040 is T-034A, the API half of the T-034 split. T-041 (web section) depends on it. The T-034 technical design carries over unchanged except for the two trims below.
- T-040 (R-006): POST /players is a sync def endpoint taking multipart `file` OR form `job_id` (a blank job_id counts as absent; exactly one, else 422 'send exactly one of file or job_id'), plus the required form fields `team: str` and `number: int`. Check order: FastAPI validation, then exactly-one, then PlayerQuery (ValueError gives 422 str(exc)), then job lookup or upload. Nothing is written and find_touches is not called before the query and job are valid.
- T-040 (R-006): The upload copy loop moves into `_save_upload(file, path)` (same 413 limit from SPORTSCUT_MAX_UPLOAD_BYTES). create_highlights calls it as a pure refactor, and the POST /highlights behaviour and tests are unchanged.
- T-040 (R-006): A new upload becomes a full T-007 job. job.json is {source_name: filename or 'upload', source_url: null, duration, version: 0, segments: []}, written only after the reel succeeds. Highlight detection is not run.
- T-040 (R-006): An existing job_id is resolved with `_load_job`. Unknown, malformed or non-canonical ids and a missing `input` give 404 'not found'. Only `<job_dir>/player/` is written; job.json, input and clips/ are never modified or deleted, even on failure.
- T-040 (R-006): The reel is built by `reel.make_player_reel(input_path, query, job_dir / 'player')` with the T-030 defaults. The API adds no detection or cutting logic.
- T-040 (R-006): Status mapping for POST /players: 422 for the request shape, team, number or a ValueError from the reel; 404 for unknown jobs; 400 when a new upload fails media.probe_duration (detail with the server input path replaced by 'upload'); 500 'processing failed' for missing ffmpeg (require_ffmpeg runs before the probe), MediaError or OSError; 413 for oversized uploads. Every failure of a new upload removes its job dir.
- T-040 (R-006): No PipelineError branch in POST /players, because make_player_reel never raises it. This replaces the T-034 Tech Lead note 'PipelineError → 400' for this endpoint; the 400 case is the failed upload probe.
- T-040 (R-006): The response is {job_id, touches, reel_url}. touches is the manifest's touches list. reel_url is the absolute `request.url_for('get_player_reel', ...)`, or null when the manifest reel is null. Zero touches is 200.
- T-040 (R-006): GET /players/{job_id}/reel/{name} (route name get_player_reel) serves FileResponse video/mp4 only when the job loads, player/player.json parses to a dict whose 'reel' is a string, and name equals it. The name is never joined to a path before that match. Anything else gives 404 {'detail': 'not found'}. Only the latest query's reel per job is downloadable.
- T-040 (R-006): No catch-all `{name:path}` route. A decoded name containing '/' (e.g. '..%2Finput') gets Starlette's default 404, consistent with get_clip in T-005/T-007. AC8 requires only status 404 and no leaked bytes for that case.
- T-040 (R-006): Size guardrail: changed lines outside docs/superpowers < 380, Tester tests included. Budgets are api.py about 115, Developer tests <= 110, Tester acceptance <= 150. The 6231ac9 checkpoint is reference only for api.py.
- T-040 (R-006): No new dependencies. reel.py, player.py, pipeline.py, evaluate.py, eval_player.py, sportscut/web, pyproject.toml and conftest.py are unchanged. There is no eval/F1 gate because accuracy is not touched.
- Tech Lead (dev_blocked): 2026-11-24 T-040 (R-006) Tech Lead (dev_blocked, round 1): The only full-suite failure (test_t023_acceptance::test_ac16) came from a stale base, not from T-040. The branch was cut from 888573b. T-013 (4442265, now on main) changed sportscut/evaluate.py and, as already recorded in DECISIONS, removed evaluate.py from test_ac16. The worktree still has the old test running `git diff main`, so it compares the old base against the new main. A dev_blocked retry does not merge the base, and agents may not rebase, so the task restarts on a fresh branch from current main. The finished work on office/T-040 (6026c39) is reused, not redone: sportscut/api.py is unchanged on main since 888573b, so the diff applies cleanly. Spec, ACs and budgets are unchanged.
- Tech Lead (dev_blocked): 2026-11-24 T-040 (R-006) Tech Lead (dev_blocked, round 2): The T-040 code is not at fault. Main moved again after the round-1 restart: dcc9770 (agent-office upstream retry) and 08190a8 (DEFAULT_MAX_UPLOAD_BYTES set to 20 GiB in api.py and test_api.py) landed on top of base 4442265. tests/test_t013_acceptance.py::test_ac15 runs a two-dot `git diff --name-only main`, so on a stale branch it sees main's newer agent-office/ files. The task's three-dot diff is clean (only api.py, test_players_api.py and test_t034a_acceptance.py; 370 lines; AC13 exits 0). Agents may not rebase, so the task restarts from current main (08190a8) and reuses the finished commits db2052e (feat) and 93b34a1 (tests) from office/T-040-r2. The api.py hunks (lines 16-24, 30-36, 170+, 337+, 379+) do not overlap 08190a8's line-27 constant change, so the commits should apply cleanly. Spec, ACs and budgets are unchanged, and no existing test is edited. Known fragility: per-task scope tests that use a two-dot `git diff main` (test_t013 ac15, test_t023 ac16) fail on any branch that main has passed. Any change to those tests needs its own task and is out of T-040's scope.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-005-expose-post-highlights-over-http-with-design.md`
- `docs/superpowers/specs/2026-11-23-t-007-add-job-read-source-streaming-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-030-add-sportscut-player-cli-that-cuts-design.md`
