# Plan T-050: Add several deterministic Vietnamese phrasings per event to the metadata templates

Design: `docs/superpowers/specs/2026-11-27-t-050-add-several-deterministic-vietnamese-phrasings-per-design.md`.

## Implementation plan

# T-050: Several deterministic Vietnamese phrasings per event in the metadata templates

Request R-005, template slice of T-024 (T-024 was dropped on diff_size; see DECISIONS 2026-11-23/26).

## Context

`sportscut/commentary/meta.py` (T-023) turns `ClipFacts` into `ClipMeta(title, caption, hashtags)`. Today there is one fixed phrasing per event, so every goal clip of a match reads 'Bàn thắng: …'. This task adds at least 3 title phrasings and 3 caption phrasings per event. One of them is picked deterministically from a SHA-256 hash of the facts, so the same facts always give the same text and different clips usually differ. Nothing else changes: the format rules (eval_meta.format_problems), the base hashtags and team tags, the CLI, the API, the LLM backend and `cases.json`.

Callers of `generate_meta` (do not change any of them): `sportscut/api.py::_default_clip_meta` (`generate_meta(ClipFacts(event))`), `sportscut/commentary/llm.py` (template fallback), and `sportscut/commentary/eval_meta.py::evaluate_meta_dir` (`meta_module.generate_meta(case.facts)`, called with one positional argument; tests monkeypatch it with `lambda facts: ...`).

## Design

### Data (module level in meta.py)

`EVENT_LABELS` and `EVENT_TAGS` are unchanged. Add the two tables below. Copy the strings exactly. Index 0 is always the T-023 phrasing.

```python
TITLE_LEADS = {
    "goal": ("Bàn thắng", "Siêu phẩm", "Pha lập công", "Khoảnh khắc ghi bàn"),
    "save": ("Pha cứu thua", "Cứu thua xuất thần", "Pha cản phá đẳng cấp"),
    "red_card": ("Thẻ đỏ", "Tấm thẻ đỏ", "Pha nhận thẻ đỏ"),
    "controversy": ("Tình huống gây tranh cãi", "Pha bóng gây tranh cãi", "Khoảnh khắc gây tranh cãi"),
    "other": ("Khoảnh khắc đáng chú ý", "Pha bóng đáng xem", "Khoảnh khắc ấn tượng"),
}
CAPTION_STYLES = {  # (opener, closer)
    "goal": (("Bàn thắng", "Cùng xem lại khoảnh khắc này!"),
             ("Bàn thắng đẹp mắt", "Xem ngay pha lập công này!"),
             ("Một bàn thắng đáng nhớ", "Hãy cùng xem lại nhé!")),
    "save": (("Pha cứu thua", "Cùng xem lại khoảnh khắc này!"),
             ("Pha cứu thua xuất thần", "Đừng bỏ lỡ pha bóng này!"),
             ("Một pha cứu thua đẳng cấp", "Hãy cùng xem lại nhé!")),
    "red_card": (("Thẻ đỏ", "Cùng xem lại khoảnh khắc này!"),
                 ("Tấm thẻ đỏ", "Đừng bỏ lỡ tình huống này!"),
                 ("Chiếc thẻ đỏ được rút ra", "Hãy cùng xem lại nhé!")),
    "controversy": (("Tình huống gây tranh cãi", "Cùng xem lại khoảnh khắc này!"),
                    ("Tình huống gây tranh cãi lớn", "Bạn nghĩ sao về tình huống này?"),
                    ("Một tình huống gây tranh cãi", "Hãy cùng xem lại nhé!")),
    "other": (("Khoảnh khắc đáng chú ý", "Cùng xem lại khoảnh khắc này!"),
              ("Một khoảnh khắc đáng chú ý", "Đừng bỏ lỡ pha bóng này!"),
              ("Khoảnh khắc đáng chú ý không thể bỏ lỡ", "Hãy cùng xem lại nhé!")),
}
```

Rules for the tables (tests check them):
- `TITLE_LEADS[e][0] == EVENT_LABELS[e]`, and `CAPTION_STYLES[e][0] == (EVENT_LABELS[e], 'Cùng xem lại khoảnh khắc này!')`.
- Every event has at least 3 title leads and 3 caption styles, and they are pairwise different.
- Every caption opener contains `EVENT_LABELS[e]` case-insensitively. This keeps eval must_mention ('bàn thắng', 'cứu thua', 'thẻ đỏ', 'tranh cãi', 'khoảnh khắc') and the validate_meta 'missing <label>' check satisfied, whatever title is picked.
- No string has a digit. The only capitalised word in any string is its first word, so `_unknown_names` never flags one. No 'VAR', 'Highlight' or other proper noun.

### Selection

```python
def _pick(part: str, facts: ClipFacts, clip: int | None, count: int) -> int:
    key = json.dumps([part, facts.event, facts.minute, facts.home, facts.away, clip], ensure_ascii=False)
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % count
```

`part` is `"title"` or `"caption"`, so the two choices are independent. competition and score are not in the key. Never use the built-in `hash()` or `random`. `generate_meta` must look `_pick` up at call time as a module global, so tests can monkeypatch `meta._pick` to force a variant.

### generate_meta

New signature: `generate_meta(facts: ClipFacts, backend: str = "template", clip: int | None = None) -> ClipMeta`.
- The backend check comes first and stays the same: `ValueError('unknown backend: <x>')`.
- `clip` is an optional clip index (0-based position in the reel). It must be None or an int ≥ 0 that is not a bool. Anything else raises `ValueError('clip must be a non-negative integer')`.
- Title: `lead = TITLE_LEADS[event][_pick('title', facts, clip, len(TITLE_LEADS[event]))]`. Then run the T-023 fallback chain with `lead` in place of `label`: `f'{lead}: {teams}, {minute}'`, `f'{lead}: {teams}'`, `f'{lead}, {minute}'`, `f'{lead} trong trận đấu'`. The first one with 10 ≤ len ≤ 80 wins. teams and minute are built as today.
- Caption: `opener, closer = CAPTION_STYLES[event][_pick('caption', ...)]`. The caption is `opener + match_text + [' ở phút M'] + [' tại C'] + '.' + [' Tỉ số: S.'] + ' ' + closer`. match_text (' trong trận H gặp A' / ' trong trận đấu của X' / ' trong trận đấu') and the optional parts are the same as T-023.
- Hashtags: the same code as today ('#BongDa', '#<EVENT_TAG>', '#Highlight', then the diacritic-stripped home/away/competition tags, deduplicated case-insensitively). They do not depend on the variant.
- Add `import hashlib` and `import json`. No new dependency.

With index 0 picked, the output is byte-identical to T-023.

### Pinned T-023 strings (intentional behaviour change)

Some tests pin exact T-023 strings. Their facts may now hash to a different variant. Edit only the literals listed below, and only if they changed. Replace each one with the exact new output as a string literal (never with a call to generate_meta). Keep every assert, and keep every equality an equality.
- `tests/test_commentary_meta.py`:
  - `test_generate_meta_full_goal`: title and caption literals.
  - `test_generate_meta_bare_other`: title and caption literals.
  - `test_title_fallbacks_and_single_team_caption`: the three title literals.
- `tests/test_t023_acceptance.py`:
  - `test_ac5_…`: the two title and two caption literals inside the ClipMeta(...) literals. The hashtag tuples stay as they are.
  - `test_ac6_…`: the long-names title literal, the `== 80` length (becomes the new literal's length), and the red_card 88 and Arsenal title literals.
- `tests/test_t025_acceptance.py:111`: the hallucinated-case template title literal.
- `tests/test_t028_acceptance.py:10-11`: the title/caption values of GOAL (`ClipFacts('goal')`) and OTHER (`ClipFacts('other')`).

The `'trong trận đấu của Arsenal' in caption` checks, all hashtag asserts and every other line of these files stay as they are. `tests/fixtures/eval_meta/cases.json` is not touched. If a must_mention check fails, change the template strings.

## Files to touch
- `sportscut/commentary/meta.py`: tables, `_pick`, `generate_meta(..., clip=None)`.
- `tests/test_meta_variants.py` (new): Developer unit tests.
- `tests/test_commentary_meta.py`, `tests/test_t023_acceptance.py`, `tests/test_t025_acceptance.py`, `tests/test_t028_acceptance.py`: only the literal updates listed above, only if needed.
- `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md`: append `## Updated by T-050`.
- `docs/superpowers/specs/2026-11-23-t-025-add-an-optional-claude-llm-backend-design.md` and `docs/superpowers/specs/2026-11-23-t-028-show-and-copy-title-caption-and-design.md`: append a one-line `Updated by T-050` note if their pinned template strings changed.
- `docs/superpowers/INDEX.md`: append a T-050 row.

## Steps (test-first)
0. Run `python -m pytest -q` and `python -m sportscut eval-meta tests/fixtures/eval_meta --json` on the base and record both summary lines (baseline: score 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0).
1. Write `tests/test_meta_variants.py::test_tables_shape`. It checks the table rules above (counts ≥ 3, index 0 equals the T-023 phrasing, pairwise distinct, every opener contains the label case-insensitively, no digits). Watch it fail with AttributeError (no TITLE_LEADS), then add the tables.
2. Write `test_every_variant_is_valid` (the facts grid is described in the test plan). It monkeypatches `meta._pick` to `lambda part, facts, clip, count: i if part == 'title' else j` for every (i, j) and asserts `format_problems(m) == []` and `validate_meta(facts, m) == []`. Watch it fail (`_pick` is missing), then add `_pick` and the variant-aware `generate_meta`.
3. Write `test_pick_formula`. For a few facts and clip values, `generate_meta(...).title` must start with `TITLE_LEADS[e][k]` and the caption must start with `CAPTION_STYLES[e][k2][0]`, where k and k2 are recomputed in the test with hashlib from the formula above. Check that `clip=None` and `clip=0` can give different keys (`json.dumps` gives null vs 0). Check that bad clip values (-1, True, 1.5, '1') raise the ValueError.
4. Write `test_variety`. Goal facts ('Hà Nội FC', 'Hải Phòng') with minutes 1..20 give ≥ 2 distinct titles and ≥ 2 distinct captions. `ClipFacts('goal')` with clip 0..9 gives ≥ 2 distinct titles.
5. Write `test_deterministic_across_hash_seeds`. Run `sys.executable -c <script>` twice with env PYTHONHASHSEED=0 and PYTHONHASHSEED=4242. The script prints `json.dumps([generate_meta(f, clip=c).to_dict() ...], ensure_ascii=False)` for a fixed list of facts and clips. Both stdouts must be equal to each other and to the in-process result.
6. Write `test_hashtags_unchanged_by_variant` and `test_eval_meta_every_variant`, then make them pass.
7. Run the full suite. For each pinned T-023/T-025/T-028 literal that now fails, update it as allowed above.
8. Append the spec notes and the INDEX row. Run the verify commands.

## Verify
- `python -m pytest -q` → 0 failed (quote the summary line).
- `python -m pytest -q tests/test_meta_variants.py` → all pass.
- `python -m sportscut eval-meta tests/fixtures/eval_meta --json` → score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0.
- `python -m sportscut eval-meta tests/fixtures/eval_meta --json --script` → unchanged from step 0.
- `git diff --stat main -- . ':!docs/superpowers'` → under 300 changed lines.
- `git diff main -- tests/fixtures/eval_meta/cases.json` → empty.

## Assumptions
- Phrasings may be marketing-toned ('Siêu phẩm', 'xuất thần') but never add a fact: no player, team, number, card type (for example 'trực tiếp') or ranking ('nhất').
- Variety follows minute, teams and clip. Two clips with the same event, minute and teams and no clip index give the same text, which is acceptable ('usually differ').
- The API and the LLM fallback keep calling `generate_meta(facts)` without a clip index. Passing the reel position as `clip` belongs to a later T-024 API/CLI slice.
- The tester-owned test edits follow the T-031 precedent (DECISIONS: 'allowed edits to pre-existing tests … because the behaviour they pinned is intentionally replaced').

## Test plan

- tests/test_meta_variants.py::test_tables_shape: checks AC1 over EVENT_TYPES (counts, index 0 equals T-023, distinct, opener contains label casefolded, no re.search(r'\d') in any string).
- tests/test_meta_variants.py::test_every_variant_is_valid: the facts grid is event × minute {None, 1, 130} × teams {(None, None), ('A', None), (None, 'Bình Dương'), ('Hà Nội FC', 'Hải Phòng'), ('Q'*40, 'W'*40)} × extra {(None, None), ('Night Wolf V.League 1', '3-2'), ('C'*40, '99-99')}. For every title index i and caption index j, monkeypatch meta._pick, then assert format_problems == [] and validate_meta == [] (message names the failing facts and indices).
- tests/test_meta_variants.py::test_pick_formula: recomputes the SHA-256 index in the test for ≥ 5 facts/clip combinations (including clip None vs 0) and asserts the title starts with the expected lead and the caption starts with the expected opener and ends with the expected closer.
- tests/test_meta_variants.py::test_index_zero_is_t023: with _pick forced to 0, the full goal facts give the exact T-023 title, caption and hashtags.
- tests/test_meta_variants.py::test_hashtags_unchanged_by_variant: AC5 over every forced variant.
- tests/test_meta_variants.py::test_variety: AC7 (minutes 1..20 give ≥ 2 titles and ≥ 2 captions; clip 0..9 gives ≥ 2 titles).
- tests/test_meta_variants.py::test_deterministic_across_hash_seeds: subprocess.run([sys.executable, '-c', script], env={**os.environ, 'PYTHONHASHSEED': seed}) for seeds '0' and '4242'. Stdouts are equal to each other and to json.dumps of the in-process result.
- tests/test_meta_variants.py::test_clip_and_backend_validation: AC8 error messages, plus a one-positional-argument call.
- tests/test_meta_variants.py::test_eval_meta_every_variant: for k in range(4), monkeypatch meta._pick to `lambda part, facts, clip, count: k % count`, run evaluate_meta_dir('tests/fixtures/eval_meta'), and assert the first five values are 1.0, 1.0, 1.0, 0.0, 1.0.
- Tester acceptance tests (own file, e.g. tests/test_t050_acceptance.py): write independently from the ACs. Reimplement the hash formula, check AC2 with mutation-style failures (for example, a template with a digit or a capitalised mid-sentence word makes validate_meta fail, which shows the check can fail), run the PYTHONHASHSEED subprocess, run the eval-meta CLI with --json and parse it, and check that `git diff main -- tests/fixtures/eval_meta/cases.json` is empty.
- Regression: full `python -m pytest -q`, including the updated pinned literals in test_commentary_meta.py, test_t023_acceptance.py, test_t025_acceptance.py and test_t028_acceptance.py.
