# Plan T-049: Accept match info in POST /highlights and serve the generated metadata to the preview page

Design: `docs/superpowers/specs/2026-11-27-t-049-accept-match-info-in-post-highlights-design.md`.

## Implementation plan

# T-049: Accept match info in POST /highlights and serve the generated metadata to the preview page

Request R-005 (Bình luận AI: tiêu đề, caption, hashtag). This is the API slice of the dropped T-024. It builds on T-005/T-007 (POST/GET /highlights), T-028 (GET/PUT /highlights/{id}/meta and meta.json), T-047 (`publish.write_meta`) and T-048 (`cut --meta`, which is the CLI twin of this task).

## Context (current code on main)

- `sportscut/api.py` `create_highlights` takes the form fields file, url, top, min_len, max_len and events. It runs `pipeline.run(input, job_dir/'clips', top=, min_len=, max_len=, events=)` and writes `job.json` as {source_name, source_url, duration, version, segments}. It returns `_job_response(...)`.
- `_validate_job` accepts only the segment keys start, end, score, reason and file, plus the optional event and event_confidence. **So title/caption/hashtags must never go into job.json** (this is also a T-028 decision).
- `pipeline.run` writes `clips/highlights.json`, and its return value is the same list.
- `publish.write_meta(out_dir, match=None, backend='template', client=None)` reads `out_dir/highlights.json`. It rewrites that file with title/caption/hashtags added to each entry, and writes `captions.txt` and `reel.json` ({title, caption, hashtags}). It raises ValueError when highlights.json is an empty list.
- `GET /highlights/{id}/meta` currently returns meta.json (the PUT edits) when it is valid. Otherwise it returns `REEL_DEFAULT` plus `_default_clip_meta(entry)` for each segment.
- Existing tests pin the exact `pipeline.run` kwargs (tests/test_api.py:545 and tests/test_t005_acceptance.py:186: `{top, min_len, max_len, events}`). **So the API must not pass `match=` to pipeline.run.** The API has no voiceover, so match would have no effect there anyway (T-048 decision).

## Design

### POST /highlights: new optional form fields

```python
meta: bool = Form(False),
home: str | None = Form(None),
away: str | None = Form(None),
competition: str | None = Form(None),
kickoff: float | None = Form(None, allow_inf_nan=False),
meta_backend: Literal['template', 'llm'] | None = Form(None),
```

These are added after `events`, in this order. The existing validation order is kept, and the new checks run after the `events` parse and before `sources.check_youtube_url`. No job dir is created and pipeline.run is not called when they fail:

1. home, away and competition are stripped. A blank or whitespace-only value becomes None.
2. Build `match = {k: v for k, v in (('home', home), ('away', away), ('competition', competition), ('kickoff', kickoff)) if v is not None} or None`.
3. If `not meta` and (`match is not None` or `meta_backend is not None`): 422 with detail exactly `home, away, competition, kickoff and meta_backend need meta`.
4. If `match is not None`: call `facts_from_entry({'start': 0, 'end': 1, 'event': 'other'}, match)`. A ValueError becomes 422 with `detail = str(exc)`, for example `home must be a stripped string of 1 to 40 characters` or `kickoff must be non-negative`.

FastAPI handles schema errors (meta='maybe', kickoff='abc'/'nan'/'inf', meta_backend='gpt') as 422 with a list detail.

**Run.** After `pipeline.run(...)` returns `entries` (unchanged call) and before job.json is written: if `meta and entries`, call `publish.write_meta(job_dir / CLIPS_DIR, match, meta_backend or 'template')`. If `meta` is true and `entries == []`, write_meta is skipped (no reel.json), as `cut --meta` does with zero clips.

An exception from write_meta reaches the existing `except Exception: rmtree(job_dir); raise` branch, so the job dir is removed. job.json is written exactly as today, with `segments` = the pipeline entries and no meta keys.

### Stored metadata and the response shape

Add these helpers to api.py (names are fixed so the Tester can rely on them only through HTTP; they are not part of the public contract):

```python
def _saved_edits(job_dir: Path) -> MetaEdits | None
    # the current get_meta try/except body moved here: meta.json -> MetaEdits, or None on OSError/ValidationError

def _stored_meta(job_dir: Path) -> tuple[dict[str, dict], dict | None]:
    # clips: {file: {'title','caption','hashtags'}} for each entry of job_dir/clips/highlights.json
    #   that is a dict with a str 'file' and whose three META_KEYS validate as MetaText.
    #   Entries without them are skipped; an unreadable or invalid file gives {}.
    # reel: MetaText.model_validate_json(job_dir/clips/reel.json).model_dump(), or None on OSError/ValidationError

def _meta_body(job_id, job, edits, stored) -> dict  # stored = _stored_meta(job_dir)
```

`_meta_body` resolution: the reel is `edits.reel` if edits exist, else the stored reel, else `REEL_DEFAULT`. For each segment file, the clip meta is the edit for that file, else the stored meta for that file, else `_default_clip_meta(entry)`. The output shape and key order stay `{job_id, reel, clips:[{file,title,caption,hashtags}]}`.

`GET /highlights/{id}/meta` and `PUT /highlights/{id}/meta` both pass `_stored_meta(job_dir)`. PUT validation and the PUT write are unchanged.

`_job_response(request, job_id, job, entries=None, *, job_dir: Path)`: all three callers (create_highlights, get_job on the job.json path, put_segments) pass `job_dir`. The response is built exactly as today. Then, **only when the stored reel is not None** (that is, `clips/reel.json` is valid):

- `body = _meta_body(job_id, job, _saved_edits(job_dir), stored)`.
- Each highlight dict gets `title`, `caption` and `hashtags` appended after `clip_url`, taken from `body['clips']` by the entry's file.
- The response gets a top-level `reel` key (after `highlights`) equal to `body['reel']`.

Without a valid reel.json the response is byte-for-byte what it is today. This covers every job created without meta=true and every hand-written test job.

The manifest-only GET path (no job.json) is untouched.

### Upload page (optional fields, no kickoff)

`sportscut/web/index.html`: inside `#highlights-form`, after the `.options` div and before `button#submit`, add:

```html
<fieldset id="match-info">
  <legend>Thông tin trận đấu cho tiêu đề và hashtag (không bắt buộc)</legend>
  <label for="home">Đội nhà</label>
  <input id="home" name="home" type="text" maxlength="40">
  <label for="away">Đội khách</label>
  <input id="away" name="away" type="text" maxlength="40">
  <label for="competition">Giải đấu</label>
  <input id="competition" name="competition" type="text" maxlength="40">
</fieldset>
```

`sportscut/web/app.js`: directly after `if (events) formData.append("events", events)`, add:

```js
const match = ["home", "away", "competition"]
  .map((name) => [name, document.querySelector(`#${name}`).value.trim()])
  .filter(([, value]) => value)
if (match.length) {
  formData.append("meta", "true")
  for (const [name, value] of match) formData.append(name, value)
}
```

No other web file changes. preview.js already loads GET /meta, so the preview shows the generated texts with no change.

## Files to touch

- `sportscut/api.py`: the form fields, validation, the write_meta call, `_saved_edits`, `_stored_meta`, and the `_meta_body`/`_job_response` changes. Add `from sportscut.commentary import publish` and `from sportscut.commentary.facts import facts_from_entry`.
- `sportscut/web/index.html` and `sportscut/web/app.js`: as above.
- `tests/test_api_meta_generate.py` (new, Developer).
- `tests/test_t049_acceptance.py` (new, Tester).
- `docs/superpowers/specs/2026-11-23-t-005-expose-post-highlights-over-http-with-design.md`, `...t-007-add-job-read-source-streaming-and-design.md`, `...t-008-serve-a-web-upload-page-for-design.md` and `...t-028-show-and-copy-title-caption-and-design.md`: append an `## Updated by T-049` note to each.

The INDEX row and the T-049 design/plan files are committed by the orchestrator.

## Steps (TDD, in order)

0. Baseline: run `.venv/bin/python -m pytest -q` and `.venv/bin/python -m sportscut eval-meta tests/fixtures/eval_meta --json`, and note the summary line and the score (1.0).
1. **Test: validation.** Monkeypatch `pipeline.run` to record its calls. Check:
   - `home` without meta → 422 with the exact 'need meta' detail. The same for `meta_backend=template` alone.
   - A 41-character home with meta=true → 422 'home must be a stripped string of 1 to 40 characters'.
   - `kickoff=-5` → 422 'kickoff must be non-negative'.
   - `kickoff=nan` and `meta_backend=gpt` → 422 with a list detail.
   - In every case, no pipeline call and no new job dir.
   - Blank `home='  '` without meta is accepted (200).

   Watch it fail, then implement the fields and checks.
2. **Test: generate.** Use a fake `pipeline.run(video, out_dir, **kw)` that writes two entries (goal clip_01.mp4 0-10 s, other clip_02.mp4 20-30 s) to `out_dir/highlights.json` with `json.dumps(..., indent=2)` and returns them, and monkeypatch `media.probe_duration` to return 60.0. POST with meta=true, home 'Hà Nội' and away 'Viettel'. Then assert:
   - The response has a `reel` key.
   - Each highlight's keys end with title, caption, hashtags. The titles contain 'Hà Nội vs Viettel', the hashtags contain '#HaNoi' and '#Viettel', and `format_problems` is [] for every clip and the reel.
   - The values equal `clips/highlights.json`/`reel.json`.
   - job.json is unchanged in shape: segments are the fake entries, with no meta keys.
   - Byte identity: the three files equal `publish.write_meta` run on a tmp copy of the original highlights.json with the same match.

   Implement the write_meta call, `_stored_meta` and `_job_response`.
3. **Test: GET.** On the step-2 job:
   - `GET /highlights/{id}` equals the POST body.
   - `GET /highlights/{id}?event=goal` keeps the meta on the one goal highlight and keeps `reel`.
   - `GET /highlights/{id}/meta` returns the stored reel and clip texts, not `REEL_DEFAULT`/`_default_clip_meta`.
   - A valid PUT /meta then overrides it: GET /meta and GET /highlights both show the PUT values.

   Implement `_saved_edits` and the `_meta_body` resolution.
4. **Test: no-meta and zero clips.**
   - A POST without the new fields gives exactly the old key sets and no reel.json/captions.txt.
   - meta=true with a fake pipeline that writes `[]` gives 200, no `reel` key and no reel.json.
   - meta_backend=llm with ANTHROPIC_API_KEY unset → 200. A spy on `publish.write_meta` saw backend 'llm', and the default backend is 'template'.
5. **Test: web.** `GET /` contains the fieldset, the three inputs with their labels and maxlength 40. `GET /static/app.js` contains `formData.append("meta", "true")` before `fetch("/highlights"`. Then edit index.html and app.js.
6. Append the `## Updated by T-049` notes to the T-005, T-007, T-008 and T-028 design specs.
7. Verify with the commands below.

## Verify commands

- `.venv/bin/python -m pytest -q tests/test_api_meta_generate.py tests/test_t049_acceptance.py -rs` → 0 failed.
- `.venv/bin/python -m pytest -q` → 0 failed. tests/test_api.py, test_t005/t007/t008/t016/t028/t034b_acceptance.py, test_meta_page.py and test_web.py pass with no edits.
- `.venv/bin/python -m sportscut eval-meta tests/fixtures/eval_meta --json` → the same score as the baseline (1.0).
- `.venv/bin/python -m sportscut eval tests/fixtures/eval --json` → F1 unchanged (detection is untouched).
- `git diff --numstat $(git merge-base main HEAD) -- . ':(exclude)docs/superpowers'` plus untracked files: the sum is < 400 lines.
- `git diff --name-only $(git merge-base main HEAD)` lists only the files above.

## Assumptions

- The web form offers home/away/competition only. Kickoff is seconds into the uploaded video, which is not a user-friendly concept, so it is API-only. `score` is not a form field: it is not in the task, and the CLI only takes it through `--match-info`.
- The web form sends meta=true only when at least one team or competition field is filled. Otherwise the request is the same as today.
- After PUT /segments re-cuts a meta job, export_clips rewrites highlights.json without meta keys, so the new clip files get the default texts. reel.json stays and keeps serving the reel, consistent with the T-028 rule 'clips fall back to defaults and the reel text stays'. A stale captions.txt is left on disk.
- Stored metadata is not re-checked with format_problems on read. write_meta output passes by construction, and eval-meta covers it.

## Test plan

- tests/test_api_meta_generate.py (Developer, ≤ 150 lines). Fixture `env(tmp_path, monkeypatch)` sets SPORTSCUT_DATA_DIR=tmp_path, delenvs ANTHROPIC_API_KEY and returns TestClient(api.app). Helper `fake_run(entries)` returns a function that writes entries to out_dir/highlights.json (json.dumps indent=2 + newline) and returns a copy; media.probe_duration is monkeypatched to 60.0.
- test_meta_fields_need_meta_and_valid_match: parametrized over {home only, meta_backend only, 41-char home, kickoff -5, kickoff nan, meta_backend gpt}. Checks the 422 detail (exact string or list), no pipeline call and an unchanged jobs dir set. Also checks that a blank home without meta returns 200.
- test_post_meta_generates_and_returns_metadata: AC2 + AC3. Checks key order, team names, format_problems, response == files, byte identity against publish.write_meta on a tmp copy, and the job.json shape.
- test_get_job_and_meta_use_stored_metadata: AC4. Checks GET /highlights/{id} == POST body, the ?event=goal filter, and that GET /meta returns the stored texts and not the defaults.
- test_put_meta_overrides_stored: AC5. A valid PUT body built from texts that pass format_problems; then GET /meta and GET /highlights reflect it.
- test_no_meta_unchanged_and_zero_clips: AC6. Checks the old key sets, no reel.json/captions.txt, the exact pipeline.run kwargs, and that meta=true with [] gives no reel.
- test_llm_backend_passed_through: AC7. A spy wraps publish.write_meta (monkeypatch api.publish.write_meta) and records (match, backend).
- test_upload_form_sends_match_fields: AC9. Static checks on GET / and GET /static/app.js, including the order of markers in app.js.
- tests/test_t049_acceptance.py (Tester, ≤ 150 lines). Acceptance tests written independently from the ACs: AC1 to AC7 with its own fake pipeline (different team names, e.g. 'Công An Hà Nội' and 'Nam Định', plus competition 'V.League 1' and kickoff 0, checking 'phút' appears in titles), and AC8 using the session `burst_video` fixture (skips without ffmpeg).
- Tester: AC9 HTML is parsed with html.parser (the ids are inside the form and before the submit button; labels and maxlength). Optionally, when node is on PATH, run app.js in a minimal fake DOM (as the tests/test_t034b_acceptance.py harness does), submit the highlights form with home 'A' and blank away, and assert the FormData contains ('meta','true') and ('home','A') and no 'away'.
- Tester confirms the tests can fail: stash the api.py change (or run against a git-archive export of main under PYTHONPATH, with no branch switch) and show that the AC2/AC4 tests fail for the right reason. Then run the full suite, eval-meta and the scope/size commands from the spec, and quote the summary lines.

## Deviations

- Step 6 / AC10: in the T-007 and T-008 design specs the note is a `### Updated by T-049` subsection at the end of the file, not a new `## ` section. Existing tests that must pass unedited pin those files' last `## ` section: tests/test_t012_acceptance.py:401 requires the last `## ` heading of the T-007 spec to be `## Updated by T-012`, and tests/test_player_page.py:79 requires the T-008 `## Updated by T-034` section to contain no later `\n## `. The `###` heading still contains the text `## Updated by T-049` and ends the file. The T-005 and T-028 specs use a plain `## Updated by T-049` section.
- sportscut/api.py is about 87 changed lines (the plan estimated about 60). The extra lines come from moving the meta.json read into `_saved_edits`, two small `_read_json`/`_meta_text` helpers used by `_stored_meta`, and passing `job_dir=` at the three `_job_response` call sites.
- tests/test_t048_acceptance.py: gate-only edit of the INDEX last-row assert behind an office/T-048 branch check, per the T-049 Tech Lead round-1 decision; excluded from the size budget.
