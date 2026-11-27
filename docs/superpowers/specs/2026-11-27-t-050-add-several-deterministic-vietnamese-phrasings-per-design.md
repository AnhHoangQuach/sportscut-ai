# T-050: Add several deterministic Vietnamese phrasings per event to the metadata templates

Request R-005. Plan: `docs/superpowers/plans/2026-11-27-t-050-add-several-deterministic-vietnamese-phrasings-per.md`.

## Product Owner request

Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt.

## Goal

Request R-005, template slice of T-024. In sportscut/commentary/meta.py, give each event 3+ title patterns and 3+ caption patterns, e.g. 'Siêu phẩm', 'Pha lập công', 'Khoảnh khắc' variants for goals. Pick deterministically from a stable hash of the facts, e.g. event, minute, home, away and an optional clip index field, and never from Python's randomised hash(). The same facts always give the same text, and different clips of the same event usually differ. Keep the base tags (#BongDa #Highlight plus the event tag) and the diacritic-stripped team tags. Every variant must meet the T-023 format rules and never invent a team or number. Tests: every variant for every event passes format_problems for facts with and without teams or minute; generation is deterministic across runs (a subprocess with a different PYTHONHASHSEED gives the same output); at least two different titles across clips with different minutes. Files: sportscut/commentary/meta.py, tests/test_meta_variants.py (new), docs/superpowers spec (note under T-023 '## Updated by'), INDEX. Do not edit tests/fixtures/eval_meta/cases.json; if a must_mention check fails, change the templates, not the fixtures. Verify: `python -m sportscut eval-meta tests/fixtures/eval_meta --json` keeps score 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0; pytest 0 failed; diff < 300 lines outside docs/superpowers.

## Acceptance criteria

- AC1: meta.TITLE_LEADS and meta.CAPTION_STYLES exist with exactly the strings in the spec. For every event in EVENT_TYPES there are ≥ 3 pairwise-distinct title leads and ≥ 3 pairwise-distinct (opener, closer) caption styles. TITLE_LEADS[e][0] == EVENT_LABELS[e] and CAPTION_STYLES[e][0] == (EVENT_LABELS[e], 'Cùng xem lại khoảnh khắc này!'). Every opener contains EVENT_LABELS[e] case-insensitively, and no string has a digit.
- AC2: For every event, every forced (title index, caption index) pair (via monkeypatched meta._pick) and every facts combination in the grid (minute None/1/130; no team, home only, away only, two short teams, two 40-character teams; with and without competition+score), eval_meta.format_problems(meta) == [] and eval_meta.validate_meta(facts, meta) == [] (no number or capitalised name outside the facts, label, teams, competition, 'phút M' and score present, Vietnamese).
- AC3: generate_meta(facts, clip=c) picks title lead index int.from_bytes(sha256(json.dumps(['title', event, minute, home, away, clip], ensure_ascii=False).encode('utf-8')).digest()[:8], 'big') % len(TITLE_LEADS[event]) and the caption style from the same formula with 'caption'. A test that recomputes this with hashlib agrees for at least 5 facts/clip combinations, including clip None and clip 0.
- AC4: The title runs the T-023 fallback chain (lead: teams, minute → lead: teams → lead, minute → lead trong trận đấu, first with 10–80 chars). The caption is opener + T-023 match text + optional ' ở phút M' + ' tại C' + '.' + optional ' Tỉ số: S.' + ' ' + closer. With both indices forced to 0, the output equals the T-023 output (for example 'Bàn thắng: Hà Nội FC vs Hải Phòng, phút 23' and its T-023 caption).
- AC5: Hashtags do not depend on the variant. For ClipFacts('goal', 23, 'Hà Nội FC', 'Hải Phòng', 'V.League 2026', '1-0'), every forced variant gives ('#BongDa', '#BanThang', '#Highlight', '#HaNoiFC', '#HaiPhong', '#VLeague2026'), and ClipFacts('goal', home='Ha Noi', away='Hà Nội') still gives 4 tags.
- AC6: Determinism. Two subprocesses running the same generation script with PYTHONHASHSEED=0 and PYTHONHASHSEED=4242 print byte-identical JSON, equal to the in-process result. Calling generate_meta twice on equal facts returns equal ClipMeta.
- AC7: Variety. Goal facts with home 'Hà Nội FC' and away 'Hải Phòng' and minutes 1..20 give at least 2 distinct titles and at least 2 distinct captions. ClipFacts('goal') with clip 0..9 gives at least 2 distinct titles.
- AC8: generate_meta(facts, backend='llm') still raises ValueError('unknown backend: llm'). clip values -1, True, 1.5 and '1' raise ValueError('clip must be a non-negative integer'). generate_meta(facts) with one positional argument still works.
- AC9: `python -m sportscut eval-meta tests/fixtures/eval_meta --json` gives score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0. The same five values hold when meta._pick is forced to each index 0..3 (modulo count). The `--script` report is unchanged. tests/fixtures/eval_meta/cases.json has no diff.
- AC10: `python -m pytest -q` reports 0 failed. In tests/test_commentary_meta.py, tests/test_t023_acceptance.py, tests/test_t025_acceptance.py and tests/test_t028_acceptance.py, the only changed lines are the pinned title/caption literals (and the long-names length 80) listed in the spec. Each is replaced by an exact string/int literal of the new output. No assert is removed, skipped or loosened, and no hashtag literal changes.
- AC11: The T-023 design spec ends with a '## Updated by T-050' section describing the variant tables, the hash formula, the clip argument and the superseded exact strings of AC5/AC6. The T-025/T-028 specs get a one-line 'Updated by T-050' note if their pinned strings changed. docs/superpowers/INDEX.md gains a T-050 row and nothing else in it changes.
- AC12: The diff outside docs/superpowers is under 300 changed lines, and no file outside the spec's file list changes.

## Out of scope

- Passing a clip index from sportscut/api.py (_default_clip_meta) or from a CLI `cut --meta` (later T-024 slices).
- Varying the hashtags (beyond the existing base and team tags), the reel-level default meta (REEL_DEFAULT) or the LLM backend prompts and validation.
- Changing the commentary script templates (script.py) or the voice-over.
- Adding a public `variant=` parameter or any configuration of phrasing tables.
- Editing tests/fixtures/eval_meta/cases.json or adding eval cases.
- Including competition or score in the hash key.

## Decisions

- T-050 (R-005): The template picks one of ≥ 3 title leads and ≥ 3 (opener, closer) caption styles per event. The index is int.from_bytes(sha256(json.dumps([part, event, minute, home, away, clip], ensure_ascii=False).encode('utf-8')).digest()[:8], 'big') % count, with part 'title' or 'caption'. Python's hash() and random are never used, so the output does not depend on PYTHONHASHSEED.
- T-050 (R-005): Index 0 of every table is the T-023 phrasing, so a forced index 0 reproduces T-023 byte-for-byte. Titles keep the T-023 fallback chain with the lead in place of the label, and captions keep the T-023 skeleton (match text, minute, competition, score) between the opener and the closer.
- T-050 (R-005): Every caption opener contains EVENT_LABELS[event] (case-insensitive), so eval must_mention and validate_meta's label check hold whatever title lead is picked. Template strings have no digits and no capitalised word except the first, so validate_meta(facts, generate_meta(facts)) == [] for every variant and facts combination.
- T-050 (R-005): generate_meta(facts, backend='template', clip=None) gains an optional keyword clip index (int ≥ 0, not bool) that only feeds the hash. Existing callers (api, llm fallback, eval) pass no clip and stay unchanged.
- T-050 (R-005): Hashtags do not depend on the variant (#BongDa, event tag, #Highlight, then diacritic-stripped home/away/competition, deduplicated case-insensitively).
- T-050 (R-005): T-023 AC5/AC6 exact strings, the T-025 AC11 hallucinated-case template title and the T-028 GOAL/OTHER defaults are superseded by the hashed variant output. In tests/test_commentary_meta.py, tests/test_t023_acceptance.py, tests/test_t025_acceptance.py and tests/test_t028_acceptance.py, only those literals (and the long-names length 80) may be replaced, by exact new literals. No assert is removed or weakened (T-031 precedent).
- T-050 (R-005): Size budget is < 300 changed lines outside docs/superpowers. No new dependency. cases.json is frozen: if a must_mention check fails, the template strings change, not the fixtures.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md`
- `docs/superpowers/specs/2026-11-23-t-025-add-an-optional-claude-llm-backend-design.md`
- `docs/superpowers/specs/2026-11-23-t-028-show-and-copy-title-caption-and-design.md`
- `docs/superpowers/specs/2026-11-26-t-046-re-land-the-reviewed-t-025-design.md`
