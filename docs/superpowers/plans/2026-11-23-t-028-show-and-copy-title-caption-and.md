# Plan T-028: Show and copy title, caption and hashtags on the web preview page

Design: `docs/superpowers/specs/2026-11-23-t-028-show-and-copy-title-caption-and-design.md`.

## Implementation plan

# T-028: Show and copy title, caption and hashtags on the web preview page

Request R-005. Read these first: the T-009 design (preview page), the T-016 design (filters and script order), the T-023 design and its DECISIONS lines (format rules), and the T-041 design (its scope test).

## Goal

The preview page `/jobs/{job_id}` gets a 'Tiêu đề, mô tả và hashtag' section. It shows one block for the whole reel and one block per clip. Each block has an editable title, caption and hashtags and a 'Sao chép' button that copies `title\ncaption\n#a #b` to the clipboard. One 'Lưu tiêu đề và hashtag' button saves every block through a new `PUT /highlights/{job_id}/meta`. That endpoint applies exactly the eval-meta format rules and returns 422 when they fail. A new `GET /highlights/{job_id}/meta` returns the saved values, or template defaults when nothing is saved yet. If a highlight carries a `voiceover_url`, its clip player gets a 'Lồng tiếng' toggle that switches between the original and the voice-over. The copy, format and source-choice logic lives in a pure JS module, `sportscut/web/metafmt.js`.

## Step 0: precondition (otherwise report BLOCKED)

T-009 (preview page) and T-023 (template metadata) must be on the base branch. Run:

```bash
.venv/bin/python -c "from pathlib import Path; from sportscut import api; from sportscut.commentary.eval_meta import score_case; from sportscut.commentary.meta import ClipMeta, generate_meta; p={r.path for r in api.app.routes}; assert '/jobs/{job_id}' in p and '/highlights/{job_id}/segments' in p; assert Path('sportscut/web/preview.js').is_file() and Path('sportscut/web/filters.js').is_file(); print('READY')"
```

If it does not print READY, report BLOCKED and change nothing.

## What exists today (main 0c613ee)

- `sportscut/api.py`:
  - `_load_job(job_id)` returns `(job_dir, job)` or raises `_JobNotFound`. `_validate_job` requires exactly 5 job.json keys.
  - `_write_job(path, obj)` writes JSON atomically.
  - `put_segments` re-cuts clips under new versioned names (`clip_01_v1.mp4`, ...) and rewrites `job['segments']`.
- `sportscut/commentary/meta.py`: `ClipMeta(title, caption, hashtags)` with `.to_dict()`, and `generate_meta(ClipFacts)`, the deterministic Vietnamese template.
- `sportscut/commentary/eval_meta.py`: the format checks are written inline at the top of `score_case`.
- `sportscut/web/preview.html` + `preview.js` (T-009/T-016), `timefmt.js`, `filters.js`.
- **T-024 (metadata in `cut --meta` / POST, reel generator) was dropped for diff size and is not merged.** Jobs carry no metadata today. **T-027 (voice-over) is not built**, so no highlight has a `voiceover_url` yet. T-028 does not depend on either (see decisions).

## Design

### 1. `sportscut/commentary/eval_meta.py`: extract `format_problems` (pure refactor)

Move the format block at the top of `score_case` (title, caption, hashtag count, then the per-tag bad/duplicate loop) unchanged into:

```python
def format_problems(meta: ClipMeta) -> list[str]:
    ...  # exactly the existing checks and message strings, in the same order
    return problems
```

`score_case` then starts with `problems = format_problems(meta)` and `format_ok = not problems`. Its output is byte-for-byte the same as before. The messages are `title length N`, `caption length N`, `hashtag count N`, `bad hashtag X` and `duplicate hashtag X`.

### 2. `sportscut/api.py`: metadata storage and two routes

Storage is `job_dir/meta.json`, written only by the PUT through `_write_job`. It holds the validated PUT body (`MetaEdits.model_dump()`). job.json, `_validate_job` and `put_segments` are **not changed**.

```python
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sportscut.commentary.eval_meta import format_problems
from sportscut.commentary.facts import ClipFacts
from sportscut.commentary.meta import ClipMeta, generate_meta
from sportscut.models import EVENT_TYPES, Segment

META_FILE = "meta.json"
REEL_DEFAULT = ClipMeta(
    "Tổng hợp highlight trận đấu",
    "Tổng hợp những khoảnh khắc đáng chú ý trong trận đấu. Cùng xem lại nhé!",
    ("#BongDa", "#Highlight", "#TongHop"),
)

class MetaText(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    caption: str
    hashtags: list[str]

class ClipMetaText(MetaText):
    file: str

class MetaEdits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reel: MetaText
    clips: list[ClipMetaText] = Field(max_length=50)
```

Helpers:
- `_meta_problems(where, item)` returns `[f"{where}: {p}" for p in format_problems(ClipMeta(item.title, item.caption, tuple(item.hashtags)))]`.
- `_default_clip_meta(entry)`: `event = entry.get("event", "other")`. It returns `generate_meta(ClipFacts(event if event in EVENT_TYPES else "other")).to_dict()`.
- `_meta_body(job_id, job, edits: MetaEdits | None)` returns `{"job_id": job_id, "reel": <edits.reel.model_dump() or REEL_DEFAULT.to_dict()>, "clips": [...]}`. There is one clip item per `job['segments']` entry, in job order: `{"file": entry['file'], "title", "caption", "hashtags"}`. Each item uses the saved values for that file name when `edits` has them, and `_default_clip_meta(entry)` otherwise. Saved clips whose file is no longer in the job are ignored.

Routes (both are in the OpenAPI schema):
- `GET /highlights/{job_id}/meta`:
  - `_load_job` fails → 404 `{"detail": "not found"}`.
  - It then tries `MetaEdits.model_validate_json((job_dir / META_FILE).read_bytes())`. `OSError` or `ValidationError` means `edits = None` (defaults).
  - It returns `_meta_body(...)`.
- `PUT /highlights/{job_id}/meta` with body `MetaEdits`:
  - Pydantic shape errors → 422 with FastAPI's list `detail`. These are checked before the job lookup, as in put_segments.
  - Unknown job → 404 `not found`.
  - If `[c.file for c in edits.clips] != [e['file'] for e in job['segments']]` → 422 `"clips must match the job's clips"`.
  - Next, `problems = _meta_problems('reel', edits.reel) + [p for i, c in enumerate(edits.clips, 1) for p in _meta_problems(f'clip {i}', c)]`. Any problems → 422 with `detail = '; '.join(problems)`, and meta.json is not written.
  - Otherwise `_write_job(job_dir / META_FILE, edits.model_dump())` and return `_meta_body(job_id, job, edits)` (200).

The values are stored exactly as sent: no strip, no NFC, no '#' added.

After `PUT /segments`, the clip file names change. The clip blocks therefore fall back to defaults, and the saved reel text stays.

### 3. `sportscut/web/metafmt.js` (new, pure classic script)

Same wrapper as `filters.js`: `(function (root) { ... root.SportsCutMeta = api; if (typeof module === "object" && module.exports) module.exports = api })(globalThis)`. The source must not contain `document`, `window`, `fetch`, `localStorage`, `XMLHttpRequest` or `navigator`.

- `parseHashtags(text)`: a non-string gives `[]`. Otherwise `text.split(/[\s,]+/).filter(Boolean)`. It does not deduplicate, add '#' or validate; the server does that.
- `formatHashtags(tags)`: `tags.join(" ")`.
- `copyText(meta)`: `` `${meta.title}\n${meta.caption}\n${formatHashtags(meta.hashtags)}` ``.
- `clipSources(highlight)`:
  - It returns `[]` unless `highlight?.clip_url` is a non-empty string.
  - Otherwise it returns `[{ label: "Bản gốc", url: clip_url }]`.
  - It appends `{ label: "Lồng tiếng", url: voiceover_url }` when `voiceover_url` is a non-empty string.

### 4. `sportscut/web/preview.html`

- Insert `<script src="/static/metafmt.js" defer></script>` between filters.js and preview.js.
- In `template#segment-row`, after the `video.clip-player`, add `<button type="button" class="voiceover" aria-pressed="false" hidden>Lồng tiếng</button>`.
- Between `#save` and `#status`, add:

```html
<section id="meta" hidden>
  <h2>Tiêu đề, mô tả và hashtag</h2>
  <ol id="meta-list"></ol>
  <button type="button" id="save-meta" disabled>Lưu tiêu đề và hashtag</button>
</section>
<template id="meta-row"><li class="meta-item">
  <h3 class="meta-name"></h3>
  <label>Tiêu đề <input class="meta-title" type="text"></label>
  <label>Mô tả <textarea class="meta-caption" rows="3"></textarea></label>
  <label>Hashtag <input class="meta-hashtags" type="text" placeholder="#BongDa #Highlight"></label>
  <button type="button" class="copy">Sao chép</button>
</li></template>
```

Add no `<a>`, no `src`/`href` and no http(s) URL.

### 5. `sportscut/web/preview.js`

Keep every existing marker and ordering that the T-009/T-016 tests pin. In particular:
- `save.disabled = true\naddSegment.disabled = true` stays adjacent.
- `save.disabled = false\n    addSegment.disabled = false` stays right after `acceptResponse(data)` in loadJob.
- The first `fetch(` after `save.addEventListener("click"` stays the segments PUT.
- `addSegment.disabled = false` occurs once.

The changes:
- Top: `const M = globalThis.SportsCutMeta`, the element constants `metaSection`, `metaList`, `metaTemplate` and `saveMeta`, a `saveMeta.disabled = true` line placed after the two existing disable lines, and `let metaClips = []`.
- `acceptResponse` also keeps `voiceover_url` from each highlight.
- `render()`, inside the existing `if (seg.clip_url)` block: `const sources = M.clipSources(seg)`. When `sources.length > 1`, it un-hides `.voiceover`. On click it flips `aria-pressed` and sets `clipPlayer.src = sources[pressed ? 1 : 0].url`.
- New functions, placed after `loadJob` and before the final `try { jobId = ...`, using textContent/value only (no innerHTML):
  - `readMeta(row)` returns `{ title: .meta-title value, caption: .meta-caption value, hashtags: M.parseHashtags(.meta-hashtags value) }`.
  - `acceptMeta(data)`:
    - It throws unless `data.reel` is an object and `data.clips` is an array.
    - It sets `metaClips = data.clips` and renders the blocks into `#meta-list`: the first is named 'Cả video (reel)', the rest `Đoạn ${index + 1}`. Inputs are filled from the data, with hashtags shown through `M.formatHashtags(`.
    - Each `.copy` is wired to `copyMeta(row)`, and `metaSection.hidden = false`.
  - `async copyMeta(row)` calls `await navigator.clipboard.writeText(M.copyText(readMeta(row)))`. Success sets #status to 'Đã sao chép.' (visible). Any exception, including a missing clipboard, calls `showError('Không sao chép được. Hãy chọn chữ và sao chép thủ công.')`.
  - `async loadMeta()` calls ``fetch(`/highlights/${encodeURIComponent(jobId)}/meta`)``. Not OK → `` showError(`Lỗi ${response.status}: ${responseMessage(data, "Không thể tải tiêu đề.")}`) ``. OK → `acceptMeta(data)` then `saveMeta.disabled = false`. A network or JSON failure gives the existing 'Không thể kết nối hoặc phản hồi từ máy chủ không hợp lệ.' message.
  - `saveMeta` click handler:
    1. Clears #error and builds `{ reel: readMeta(rows[0]), clips: metaClips.map((clip, index) => ({ file: clip.file, ...readMeta(rows[index + 1]) })) }`.
    2. Sets `saveMeta.disabled = true`, then calls ``fetch(`/highlights/${encodeURIComponent(jobId)}/meta`, {`` with `method: "PUT"` and the JSON header.
    3. Not OK → `Lỗi <status>: <responseMessage(...)>`. OK → `acceptMeta(data)` and #status 'Đã lưu tiêu đề và hashtag.'.
    4. The catch shows the connection message, and `finally` sets `saveMeta.disabled = false`.
- Call `loadMeta()` in two places: in `loadJob` after its `render()`, and in the segments save handler after `render()` on success. File names change after a re-cut.

There is no client-side copy of the format rules; the server is the source of truth (YAGNI).

### 6. `sportscut/web/style.css`

Append `#meta { margin-top: 2rem; }`, `.meta-item label { display: block; }`, `.meta-item input, .meta-item textarea { width: 100%; }` and `.meta-item button { width: auto; }`.

### 7. Existing tests this task must update (authorised, nothing else)

- `tests/test_t016_acceptance.py`: the exact preview `resources == [...]` list gains `"/static/metafmt.js"` between `"/static/filters.js"` and `"/static/preview.js"`. That is a one-line contract update, matching T-016's own amendment of the T-009 order.
- `tests/test_t034b_acceptance.py::test_ac9_ac10_scope_and_size`: this one-PR scope and size guard runs a merge-base diff, so it fails on every later branch that touches api.py or preview.*. Pin it to the T-041 commit itself:
  1. Add `commit = "373a8438e6184d1048024bf48656139e158f2e2e"`. Skip with 'git or the T-041 commit is not available' when `shutil.which('git') is None` or `git('cat-file', '-e', commit + '^{commit}').returncode` is non-zero.
  2. Delete the `base = ...` line, and use `commit + '^', commit` in place of `base` in both `git diff` calls.
  3. Delete the 2-line untracked-files loop, which only meant something on the T-041 branch.

  The paths, allowed set and budgets stay as they are. On main today, that commit's numstat is app.js 80, index.html 27, style.css 14, test_player_page.py 80 and test_t034b_acceptance.py 130, which is 331 < 380. So the test still passes and still guards T-041's change.

### 8. Docs

- README.md, section `## Trang web: tải lên, xem trước và chỉnh mốc cắt`: add steps 13 and 14 before the 404 line.
  - Step 13: the 'Tiêu đề, mô tả và hashtag' section, editing, 'Sao chép', and 'Lưu tiêu đề và hashtag' (rules 10–80 / 1–300 / 3–8 hashtags, as in eval-meta).
  - Step 14: after 'Lưu' re-cuts the clips, clip texts return to the defaults and the reel text stays. A 'Lồng tiếng' button appears when a clip has a voice-over.

  Keep it to 6 lines or fewer, with no images.
- Append a `## Updated by T-028` note to the T-009, T-016, T-023 and T-041 design specs (texts listed under related_specs and decisions).

## Files

- sportscut/commentary/eval_meta.py
- sportscut/api.py
- sportscut/web/metafmt.js (new)
- sportscut/web/preview.html
- sportscut/web/preview.js
- sportscut/web/style.css
- README.md
- tests/test_meta_page.py (new, Developer)
- tests/test_t028_acceptance.py (new, Tester)
- tests/test_t016_acceptance.py (one line)
- tests/test_t034b_acceptance.py (pin)
- the four spec notes

## Steps (TDD: write the test, watch it fail for the right reason, implement, watch it pass)

0. Run the Step 0 precondition. It must print READY.
1. `format_problems`:
   - Test in tests/test_meta_page.py: [] for `generate_meta(ClipFacts(e))` for every event, plus a few exact messages. It fails with ImportError.
   - Refactor eval_meta.py.
   - Run `pytest -q tests/test_eval_meta.py tests/test_t023_acceptance.py tests/test_commentary_meta.py`.
2. `GET /highlights/{id}/meta`: the defaults test and the 404 test, using a hand-written job dir with no ffmpeg (copy `_write_hand_job` from test_web_filters.py). They fail with 404/405 because the route is missing. Then implement the models, helpers and GET.
3. `PUT /highlights/{id}/meta`: tests for valid → persists, format 422, mismatch 422 and shape 422. Then implement.
4. metafmt.js: a node test, skipped with reason 'node is required on PATH' when node is absent (copy `_node_eval` from test_preview.py). Then write the module.
5. preview.html: a static parse test. Then update the HTML, and update the T-016 resources line in the same step. Run `pytest -q tests/test_t016_acceptance.py tests/test_t009_acceptance.py tests/test_preview.py tests/test_web_filters.py`.
6. preview.js: a source-marker test. Then implement preview.js and add the CSS.
7. Pin the T-041 scope test. Run `pytest -q tests/test_t034b_acceptance.py`.
8. Add the README steps and the spec notes.
9. Verify (below).

## Verify (quote the summary lines)

- `.venv/bin/python -m pytest -q tests/test_meta_page.py tests/test_t028_acceptance.py -rs` → 0 failed and 0 skipped (node on PATH).
- `.venv/bin/python -m pytest -q` → 0 failed.
- `.venv/bin/python -m sportscut eval-meta tests/fixtures/eval_meta --json` → score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0 (README baseline, unchanged).
- `git diff --numstat $(git merge-base main HEAD) -- . ':(exclude)docs/superpowers'` plus untracked files → total < 430 changed lines. Budgets: production + README + the two edited old tests ≤ 225, tests/test_meta_page.py ≤ 80, tests/test_t028_acceptance.py ≤ 120.
- Manual check: run `sportscut serve`, upload a clip, and on `/jobs/ID` edit a title, press 'Sao chép', paste it somewhere, then press 'Lưu tiêu đề và hashtag' and reload.

## Assumptions

- Without T-024, the defaults are the T-023 template with the event only: no team, minute or competition, and no invented names. The reel default equals what T-024's planned `generate_reel_meta` gives with no match info and no named events.
- One save button for all blocks is enough. The copy text uses the order title, caption, hashtags on three lines, the same body as T-024's planned captions.txt block.
- Clip metadata is keyed by clip file name, so a re-cut gives new clips fresh defaults. Re-cut clips are different clips.
- Today no highlight has `voiceover_url`, so the toggle never shows in real use until T-027 adds the field to `GET /highlights/{id}` highlights.

## Review focus

1. The existing T-009/T-016 preview.js ordering markers still hold. Run their tests.
2. An invalid PUT never creates or changes meta.json, and job.json is never written by the meta routes.
3. score_case output is unchanged (eval-meta JSON identical).
4. No innerHTML is used. User text goes only through `.value`/`.textContent`.

## Test plan

- Developer, tests/test_meta_page.py (≤ 80 lines), fixtures: a hand-written job dir via SPORTSCUT_DATA_DIR (no ffmpeg) and the node helper from test_preview.py. Tests: test_format_problems_rules (AC2 messages + [] for template output); test_get_meta_defaults (AC3); test_put_meta_valid_persists_and_invalid_422 (AC5/AC6 core); test_put_meta_clip_mismatch_422 (AC7, one case); test_preview_html_meta_contract (static HTML parse, AC10 elements); test_metafmt_node_contract (AC11 core, skipped when node is absent); test_preview_js_meta_markers (AC12).
- Tester, tests/test_t028_acceptance.py (≤ 120 lines), written from the ACs, not from the Developer tests. It covers: the 404 matrix for GET and PUT (AC4); the exact default body (AC3); the persist round trip with the job.json bytes check (AC5); the exact 422 detail strings and unchanged meta.json (AC6); all four mismatch variants (AC7); the schema-error matrix (AC8); re-cut fallback and corrupt meta.json (AC9); GET /jobs/{id} body equality plus the resource list and the metafmt.js static response (AC10); the full metafmt.js node contract including keys and purity (AC11); and the preview.js markers and ordering (AC12).
- Tester confirms the tests can fail. It temporarily breaks one rule (for example, makes format_problems return [] or drops the clips-match check) or runs against main, sees AC3/AC6/AC7 fail, then restores the code.
- Tester must NOT add a git-diff scope/size test to the pytest suite. That kind of test fails on every later branch (see the T-041 pin). Scope and size are checked with the Verify commands and in review.
- Regression: run tests/test_eval_meta.py, tests/test_commentary_meta.py, tests/test_t023_acceptance.py, tests/test_preview.py, tests/test_t009_acceptance.py, tests/test_web_filters.py, tests/test_t016_acceptance.py and tests/test_t034b_acceptance.py, then the full `python -m pytest -q`.
- Eval: `python -m sportscut eval-meta tests/fixtures/eval_meta --json` equals the README baseline (score 1.0). Detection is untouched, so the `sportscut eval` F1 gate does not apply.

## Deviations

- Step 7 / AC13 (T-041 pin) not applied. This plan was written against main 0c613ee. On the actual base dc06807, T-015 (Tech Lead decision, round 1, DECISIONS.md) had already rewritten `tests/test_t034b_acceptance.py::test_ac9_ac10_scope_and_size`: it now only checks that pyproject.toml, tests/conftest.py and agent-office/ are unchanged against the merge base. It no longer has the `base = ...` allowlist/size diffs or the untracked-files loop that step 7 edits, and it passes on this branch (`3 passed`). Pinning it to 373a843 would bring back the allowlist and size assertions that T-015 removed on purpose, which contradicts a newer decision. So the file is left untouched; only tests/test_t016_acceptance.py changes among the old tests. The Tech Lead decides if the pin is still wanted.
- The Developer clip-mismatch check (AC7, swapped order) is inside `test_put_meta_valid_persists_and_invalid_422` instead of its own `test_put_meta_clip_mismatch_422`, to keep tests/test_meta_page.py at 80 lines.
