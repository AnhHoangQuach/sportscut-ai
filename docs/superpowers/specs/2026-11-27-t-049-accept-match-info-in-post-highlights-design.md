# T-049: Accept match info in POST /highlights and serve the generated metadata to the preview page

Request R-005. Plan: `docs/superpowers/plans/2026-11-27-t-049-accept-match-info-in-post-highlights.md`.

## Product Owner request

Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt.

## Goal

Request R-005, API slice of T-024. POST /highlights accepts the optional form fields `meta` (bool), `home`, `away`, `competition`, `kickoff` and `meta_backend` (template|llm). When meta is true, the job runs publish.write_meta on its output directory after the cut. The response and GET /highlights/{job_id} then include each clip's title, caption and hashtags plus the reel metadata. GET /highlights/{job_id}/meta uses, in order: saved PUT edits (meta.json), then the metadata stored in highlights.json/reel.json, then the existing generic per-event default (_default_clip_meta). PUT validation is unchanged. Without the new fields, the API responses for existing requests are unchanged; the existing T-005/T-007/T-028 tests must pass untouched. Tests use TestClient with the existing synthetic-video job fixtures: a request with home/away returns metadata naming those teams and passing format_problems; GET meta returns the stored metadata instead of the generic default; a later PUT still overrides it. Files: sportscut/api.py, tests/test_api_meta_generate.py (new), docs/superpowers spec and INDEX. Do not change the web JS unless needed to send the fields; if the upload form gets team fields, keep it to sportscut/web/index.html and app.js with a TestClient check that they are served. Verify: pytest 0 failed; eval-meta score unchanged; diff < 400 lines outside docs/superpowers.

## Acceptance criteria

- AC1: POST /highlights accepts optional form fields meta (bool, default false), home, away, competition (strings, stripped; blank means absent), kickoff (finite float) and meta_backend ('template' or 'llm'). Any of home/away/competition/kickoff/meta_backend given without meta=true returns 422 with detail exactly 'home, away, competition, kickoff and meta_backend need meta'. meta=true with a 41-character home returns 422 'home must be a stripped string of 1 to 40 characters'; kickoff=-5 returns 422 'kickoff must be non-negative'; kickoff=nan, meta=maybe and meta_backend=gpt return 422 with a list detail. In every 422 case pipeline.run is not called and no job dir is created. home='   ' without meta returns 200 as a normal request.
- AC2: With pipeline.run faked to write and return two entries (goal clip_01.mp4 and other clip_02.mp4) and media.probe_duration faked to 60.0, a POST with meta=true, home='Hà Nội' and away='Viettel' returns 200. Top-level keys are exactly job_id, source_name, source_url, duration, highlights, reel in that order. Each highlight's keys are exactly start, end, score, reason, event, event_confidence, clip_url, title, caption, hashtags. Every clip title contains 'Hà Nội vs Viettel', every caption contains 'trong trận Hà Nội gặp Viettel', every hashtag list contains '#HaNoi' and '#Viettel', reel.title == 'Tổng hợp highlight: Hà Nội vs Viettel', and format_problems(ClipMeta(...)) == [] for every clip and the reel.
- AC3: After the AC2 POST, job_dir/clips/highlights.json, captions.txt and reel.json are byte-identical to the files produced by running publish.write_meta(tmp_copy, {'home': 'Hà Nội', 'away': 'Viettel'}, 'template') on a temporary copy of the fake pipeline's original highlights.json. The response's per-clip title/caption/hashtags and reel equal the contents of those files. job.json is exactly {source_name, source_url, duration, version: 0, segments} where segments equals the fake pipeline's returned entries (no title/caption/hashtags keys).
- AC4: On the AC2 job, GET /highlights/{id} returns a body equal to the POST response. GET /highlights/{id}?event=goal returns only the goal highlight, still carrying its title/caption/hashtags, plus the same reel. GET /highlights/{id}/meta returns {job_id, reel, clips} where reel equals reel.json and each clip equals {file, title, caption, hashtags} from highlights.json. It does not equal REEL_DEFAULT or _default_clip_meta for those clips.
- AC5: On the AC2 job, a valid PUT /highlights/{id}/meta (format-valid texts for both clips, in job order) returns 200. Afterwards GET /highlights/{id}/meta returns exactly the PUT values, and GET /highlights/{id} shows the PUT clip texts on its highlights and the PUT reel as `reel`. PUT validation errors (clip mismatch, format problems, schema errors) are unchanged and leave meta.json untouched.
- AC6: A POST without any new field (real burst_video fixture and faked pipeline) returns exactly today's keys (no `reel`, highlight keys end at clip_url), writes no clips/reel.json or clips/captions.txt, and pipeline.run is called with exactly {top, min_len, max_len, events} kwargs. POST with meta=true whose pipeline returns [] returns 200 with no `reel` key and writes no reel.json. GET /highlights/{id}/meta on a job without reel.json and without stored clip meta returns the T-028 defaults unchanged.
- AC7: meta_backend defaults to 'template'. With ANTHROPIC_API_KEY unset and meta_backend='llm', the POST returns 200, and a spy wrapping publish.write_meta records backend 'llm' and match {'home': 'Hà Nội', 'away': 'Viettel'}. No network is used.
- AC8: Integration on the real synthetic video: posting tests/conftest.py's burst_video with meta=true, home='Hà Nội' and away='Viettel' returns 200 with 3 highlights. Each has a title containing 'Hà Nội vs Viettel' and format_problems == [], and GET /highlights/{id}/meta returns the same texts.
- AC9: GET / serves index.html containing fieldset#match-info with a Vietnamese legend, and inputs #home, #away and #competition (name equal to id, type text, maxlength 40), each with a non-empty Vietnamese <label for>. They sit inside #highlights-form, before button#submit. GET /static/app.js returns 200 and contains 'formData.append("meta", "true")' and the three field names, placed after 'if (events) formData.append("events", events)' and before 'fetch("/highlights"'. All existing upload-page tests (test_web.py, test_t008, test_t016 and test_t034b acceptance) pass unchanged.
- AC10: Each of the T-005, T-007, T-008 and T-028 design specs ends with a '## Updated by T-049' note that describes the new fields, the conditional response keys, the GET meta source order (meta.json, then highlights.json/reel.json, then defaults) and the upload-page fields.
- AC11: `.venv/bin/python -m pytest -q` reports 0 failed, and no existing test file is modified. `.venv/bin/python -m sportscut eval-meta tests/fixtures/eval_meta --json` prints the same score as main (1.0), and `sportscut eval tests/fixtures/eval --json` F1 is unchanged. Changed lines outside docs/superpowers are < 400, and only the files in `files` change. sportscut/pipeline.py, export.py, models.py, cli.py, commentary/*, tests/conftest.py, pyproject.toml and agent-office/ are untouched. These scope/size checks are done by command and in review, not by pytest.

## Out of scope

- Passing match into pipeline.run from the API (no voiceover in the API; existing tests pin the run kwargs).
- Voice-over, vertical clips or subtitles via the API.
- A `score` form field, a kickoff field on the upload page, or any kickoff UI.
- Adding meta to the manifest-only GET /highlights/{id} path (no job.json).
- Regenerating metadata after PUT /segments, removing stale captions.txt/reel.json, or a 'regenerate' button.
- Changes to preview.html, preview.js, metafmt.js, style.css or any other web file besides index.html and app.js.
- Changes to job.json schema, _validate_job, PUT /segments, PUT /meta validation, publish.py, meta.py, facts.py, llm.py, cli.py, pipeline.py.
- README changes, async/background jobs, LLM calls in tests.

## Decisions

- T-049 (R-005): The API reuses publish.write_meta unchanged on job_dir/clips after pipeline.run and before job.json is written. The metadata lives only in clips/highlights.json, clips/captions.txt and clips/reel.json, never in job.json (keeps the T-028 rule and _validate_job).
- T-049 (R-005): pipeline.run is called by the API exactly as before (no match kwarg). Match info only feeds write_meta, because the API has no voiceover and the existing tests pin the run kwargs.
- T-049 (R-005): New POST fields are meta (bool, default false), home, away, competition (stripped; blank means absent), kickoff (finite float) and meta_backend (template|llm, default template). Match fields or meta_backend without meta=true give 422 'home, away, competition, kickoff and meta_backend need meta' (mirrors T-048's argparse rule). Match values are validated with facts_from_entry({'start':0,'end':1,'event':'other'}, match), and a ValueError becomes 422 with str(exc). All of this runs before the job dir is created.
- T-049 (R-005): meta=true with zero clips skips write_meta and returns the normal response without metadata (mirrors T-048).
- T-049 (R-005): A job 'has generated metadata' exactly when clips/reel.json is a valid {title, caption, hashtags} object. Only then do the POST, GET /highlights/{id} and PUT /segments responses append title, caption and hashtags to each highlight (after clip_url) and a top-level `reel` (after highlights). Otherwise the responses are unchanged.
- T-049 (R-005): The metadata source order for GET /highlights/{id}/meta and for the response fields is: meta.json PUT edits (whole reel and per-file clips), then stored per-file clip meta from clips/highlights.json and the reel from clips/reel.json, then _default_clip_meta / REEL_DEFAULT. Clip texts are keyed by file name, so after PUT /segments the new files fall back to defaults and the stored reel stays. This supersedes T-028's 'GET meta defaults' for jobs with stored metadata.
- T-049 (R-005): The upload page gets fieldset#match-info with #home, #away and #competition (text, maxlength 40) and no kickoff. app.js sends meta=true plus the non-blank fields only when at least one is filled. This amends T-028's 'no upload page change' out-of-scope note.
- T-049 (R-005): Size budget is < 400 changed lines outside docs/superpowers (api.py ≈ 60, index.html + app.js ≈ 20, Developer tests ≤ 150, Tester acceptance ≤ 150). No existing test file is edited. Scope/size are checked by commands and in review, not by pytest git-diff tests (T-028 rule). eval-meta stays 1.0 and eval F1 is unchanged.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-005-expose-post-highlights-over-http-with-design.md`
- `docs/superpowers/specs/2026-11-23-t-007-add-job-read-source-streaming-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-008-serve-a-web-upload-page-for-design.md`
- `docs/superpowers/specs/2026-11-23-t-028-show-and-copy-title-caption-and-design.md`
- `docs/superpowers/specs/2026-11-27-t-047-add-sportscut-meta-out-dir-writing-design.md`
- `docs/superpowers/specs/2026-11-27-t-048-add-sportscut-cut-meta-with-the-design.md`
- `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md`
