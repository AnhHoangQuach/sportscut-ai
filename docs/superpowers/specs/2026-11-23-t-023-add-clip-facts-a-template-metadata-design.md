# T-023: Add clip facts, a template metadata generator and a `sportscut eval-meta` score

Request R-005. Plan: `docs/superpowers/plans/2026-11-23-t-023-add-clip-facts-a-template-metadata.md`.

## Product Owner request

Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt.

## Goal

Goal of R-005: every exported highlight gets a Vietnamese title, a caption and hashtags, and optionally a Vietnamese AI voice-over mixed into the clip. Text is checked by `sportscut eval-meta tests/fixtures/eval_meta --json`, which prints `{"score", "format_ok", "fact_recall", "hallucination_rate", "vi_rate", "per_case": [...]}`. Voice-over is checked by measurable timing and loudness tests. Approaches considered: (a) offline Vietnamese templates driven by structured facts, with an optional LLM backend behind the same interface, gated by the eval; (b) LLM only, which needs network and an API key and can't be tested offline or in CI; (c) a local LLM, which is too heavy for the laptop CPU budget. We pick (a): it works offline, it is deterministic in tests, and the LLM is added only where it raises the number. This task: add `sportscut/commentary/facts.py` with `ClipFacts` (event, match minute, home/away, competition, optional score text) built from a manifest entry plus optional match info, and `meta.py` with `ClipMeta(title, caption, hashtags)` and `generate_meta(facts, backend="template")`. Add committed fixtures `tests/fixtures/eval_meta/cases.json` (facts plus `must_mention` any-of lists and forbidden facts) and the scorer. Format rules: title 10-80 chars, caption at most 300 chars, 3-8 unique hashtags matching `#[A-Za-z0-9_]+`. Hallucination means a number or team name in the output that is not in the facts. vi_rate is a Vietnamese-diacritics heuristic. Record the template baseline in the README. Assumptions: this needs R-001 (T-001..T-004) and R-003's `event` field (T-010) on main, otherwise report BLOCKED and do not re-create them. The match minute is computed only when a kickoff offset is given. The F1 gate is unchanged, and this score is reported in every R-005 PR.

## Acceptance criteria

- AC1: The Step 0 precondition prints READY on the task branch before any code is written. If it prints BLOCKED, the task stops and reports the missing check without creating prerequisite files.
- AC2: `ClipFacts(event, minute=None, home=None, away=None, competition=None, score=None)` is a frozen dataclass in `sportscut/commentary/facts.py`. Each of these raises ValueError: event 'penalty' or 'Goal'; minute 0, 131, True or 2.0; a home/away/competition that is empty, a non-str, longer than 40 characters, or has leading or trailing spaces; score '2:1' or '100-1'. `ClipFacts('goal', 23, 'Hà Nội FC', 'Hải Phòng', 'V.League 2026', '1-0')` is valid.
- AC3: `facts_from_entry({'start':1370,'end':1382,'event':'goal'}, {'kickoff':0})` gives minute 23. kickoff 120 gives 21. kickoff 1400 gives None. With no match, or a match without kickoff, the minute is None. An entry whose anchor equals kickoff gives minute 1. The event comes from the entry.
- AC4: `facts_from_entry` strips and NFC-normalises names and turns blank names into None, so `' Arsenal '` becomes 'Arsenal' and `'  '` becomes None. It normalises the score ' 2 - 1 ' to '2-1'. It raises ValueError for an unknown match key (message contains 'unknown match key'), for a kickoff of -1, True, nan or '10', and for an entry with a non-finite start or end <= start.
- AC5: For `ClipFacts('goal', 23, 'Hà Nội FC', 'Hải Phòng', 'V.League 2026', '1-0')`, `generate_meta(facts)` returns:
- title 'Bàn thắng: Hà Nội FC vs Hải Phòng, phút 23'
- caption 'Bàn thắng trong trận Hà Nội FC gặp Hải Phòng ở phút 23 tại V.League 2026. Tỉ số: 1-0. Cùng xem lại khoảnh khắc này!'
- hashtags ('#BongDa', '#BanThang', '#Highlight', '#HaNoiFC', '#HaiPhong', '#VLeague2026')

For `ClipFacts('other')` it returns:
- title 'Khoảnh khắc đáng chú ý trong trận đấu'
- caption 'Khoảnh khắc đáng chú ý trong trận đấu. Cùng xem lại khoảnh khắc này!'
- hashtags ('#BongDa', '#KhoanhKhac', '#Highlight')
- AC6: Title fallbacks:
- The goal_long_names facts give exactly 'Bàn thắng: Câu lạc bộ Bóng đá Công an Hà Nội vs Becamex Bình Dương Football Club' (80 characters).
- `ClipFacts('red_card', 88)` gives 'Thẻ đỏ, phút 88'.
- `ClipFacts('goal', home='Arsenal')` gives title 'Bàn thắng: Arsenal' and a caption containing 'trong trận đấu của Arsenal'.

For every ClipFacts in the fixture, the title is 10 to 80 characters and the caption is at most 300 characters.
- AC7: `hashtag('Hà Nội FC') == '#HaNoiFC'`, `hashtag('U23 Việt Nam') == '#U23VietNam'`, `hashtag('V.League 2026') == '#VLeague2026'`, and `hashtag('!!!') is None`. Hashtags are deduplicated case-insensitively, so home 'Ha Noi' with away 'Hà Nội' gives 4 tags. `generate_meta(facts, backend='llm')` raises ValueError('unknown backend: llm'). `ClipMeta.to_dict()` has the keys title, caption, hashtags in that order, and hashtags is a list.
- AC8: `score_case` sets format_ok False and lists one matching problem for each of these: a 9-character title, an 81-character title, a 301-character caption, an empty caption, 2 hashtags, 9 hashtags, '#Bóng' or 'BongDa' (bad pattern), and '#BongDa' with '#bongda' (duplicate). Valid metadata has format_ok True and problems [].
- AC9: `score_case` sets hallucinated True, with 'number 24 not in facts', when the output says 'phút 24' and the facts have minute 23. It also sets hallucinated True, with 'forbidden Liverpool', when a forbidden 'Liverpool' appears in the caption case-insensitively. Digits that come from the facts (the score, '2026' from the competition, '23' from 'U23') are not hallucinations. A hallucinated or non-Vietnamese case has a case score of 0.0.
- AC10: vi is False for the English-only caption 'Great goal by the home side' with the title 'Goal: Arsenal vs Chelsea, minute 23'. vi is True for every template output in the fixture. Tokens of team and competition names are excluded before computing the 30% ratio.
- AC11: fact_recall is the share of must_mention groups in which any alternative appears, case-insensitively and after NFC normalisation, in the title, caption or hashtags. One of two groups met gives 0.5. The report's fact_recall is micro-averaged over all groups. The per_case entries have exactly the keys id, score, format_ok, fact_recall, hallucinated, vi, problems, title, caption, hashtags, in that order.
- AC12: `load_cases` and `evaluate_meta_dir` raise ValueError for each of the following: a path that is not a directory ('not a directory'), a missing cases.json ('missing cases.json'), invalid JSON, a top level that is not a list, an empty list ('no eval cases'), a duplicate id, an unknown facts key, invalid facts, an empty must_mention, an empty group, and a forbidden string that is present in the facts. Except for the directory errors, the messages contain 'cases.json'.
- AC13: The report keys are exactly score, format_ok, fact_recall, hallucination_rate, vi_rate, per_case, in that order, with floats rounded to 4 decimals. With `meta.generate_meta` monkeypatched over two cases (one perfect, one hallucinated), score is 0.5 and hallucination_rate is 0.5.
- AC14: `python -m sportscut eval-meta tests/fixtures/eval_meta --json` exits 0 and prints one JSON line with score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0 and 8 per_case entries, in the order goal_full, save_teams, red_card_minute_only, controversy_no_minute, other_bare, goal_long_names, goal_u23, save_competition_only. Without --json it prints the same report with indent=2. A missing directory prints 'sportscut eval-meta: error: ' on stderr, nothing on stdout, and exits 2. `sportscut eval-meta --help` lists DIRECTORY and --json.
- AC15: README.md has an eval-meta section with the command, the case format, the format and score rules, and a JSON block whose five headline values equal what AC14 printed.
- AC16: The T-023 diff does not change detect.py, evaluate.py, models.py, export.py, pipeline.py, api.py, pyproject.toml or tests/conftest.py, and adds no dependency. Later tasks may update evaluate.py; T-013 does so to add goal classification, so it is no longer protected after T-023. `python -m pytest -q` passes. The new tests pass with `PATH=/nonexistent`, because they need no ffmpeg. (updated by T-013) (updated by T-025: pyproject.toml may gain optional extras; the llm extra is added by T-025)

## Out of scope

- The LLM backend (network, API key) and any backend other than 'template'.
- Vietnamese voice-over (TTS), mixing audio into clips, and the timing and loudness tests for it, which belong to later R-005 tasks.
- Writing title, caption or hashtags into highlights.json, the `cut` CLI, the POST /highlights response or the web page.
- A match-info file format or CLI flags (--home/--away/--kickoff) for feeding match info in from users.
- Second-half kickoff offsets, stoppage-time notation (45+2'), and naming the scorer or the scoring team.
- A dictionary of known team names for open-ended hallucination detection; this task uses only the per-case `forbidden` lists.
- Real-match metadata labels in data/ and a CI workflow file.
- Any change to the highlight detector, the `sportscut eval` F1 gate, or existing tests.

## Decisions

- T-023 (R-005): T-023 starts only after T-004 and T-010 are merged (Tech Lead, dev_blocked). The Step 0 python precondition must print READY. Otherwise the task reports BLOCKED and does not re-create prerequisite files.
- T-023 (R-005): The new package is `sportscut/commentary/` with facts.py (ClipFacts, facts_from_entry), meta.py (ClipMeta, generate_meta, hashtag, EVENT_LABELS, EVENT_TAGS) and eval_meta.py (MetaCase, load_cases, score_case, evaluate_meta_dir). It is pure Python with no new dependency and no ffmpeg.
- T-023 (R-005): ClipFacts fields are, in order, event, minute, home, away, competition, score. `__post_init__` validates strictly and never normalises:
- event is in EVENT_TYPES;
- minute is an int (not a bool) from 1 to 130;
- names are non-empty, already stripped, and at most 40 characters;
- score matches ^\d{1,2}-\d{1,2}$.

facts_from_entry does the normalising (NFC, strip, blank -> None, spaces around '-' removed from the score). It rejects unknown match keys.
- T-023 (R-005): The minute is computed only when a kickoff offset (in seconds into the video) is given:
- anchor = start + (end-start) * detect.PRE_SEC / (PRE_SEC + POST_SEC), which is the detector's peak;
- minute = floor((anchor - kickoff) / 60) + 1, capped at 130;
- an anchor before kickoff gives None.

The minute is continuous elapsed time. Second-half offsets are not handled yet.
- T-023 (R-005): The template is deterministic. The Vietnamese event labels are Bàn thắng / Pha cứu thua / Thẻ đỏ / Tình huống gây tranh cãi / Khoảnh khắc đáng chú ý. The title is the first fitting candidate of '{L}: {T}, phút {m}', '{L}: {T}', '{L}, phút {m}', '{L} trong trận đấu'. The caption never states who scored. The hashtags are #BongDa, #<EventTag> and #Highlight, followed by ASCII-folded tags for home, away and competition, deduplicated case-insensitively.
- T-023 (R-005): generate_meta(facts, backend='template') is the single interface for metadata. Any other backend raises ValueError until a later task adds it. A new backend is accepted only if `sportscut eval-meta tests/fixtures/eval_meta --json` does not lower score.
- T-023 (R-005): eval-meta reads DIR/cases.json, a list of {id, facts, must_mention, forbidden}. must_mention is a list of any-of groups, and forbidden lists names that must not appear. Matching is NFC plus casefold substring over title, caption and hashtags.
- T-023 (R-005): The format rules are: title 10 to 80 characters (len, stripped), caption 1 to 300 characters, and 3 to 8 hashtags that are unique case-insensitively and each fully match #[A-Za-z0-9_]+.
- T-023 (R-005): A case is hallucinated if any integer in the output is missing from the integers in the facts text (minute, score, names, competition), or if any forbidden string appears. Team names are checked only through `forbidden`.
- T-023 (R-005): vi is a heuristic. A case counts as Vietnamese when at least 30% of the letter tokens in title+caption contain a Vietnamese diacritic (VI_CHARS), after removing tokens that come from the team and competition names.
- T-023 (R-005): The case score is fact_recall if the case is format_ok, not hallucinated and vi, and 0 otherwise. In the report:
- score is the mean case score;
- format_ok, hallucination_rate and vi_rate are shares of cases;
- fact_recall is micro-averaged over groups.

The key order is score, format_ok, fact_recall, hallucination_rate, vi_rate, per_case. per_case entries are {id, score, format_ok, fact_recall, hallucinated, vi, problems, title, caption, hashtags}. Floats are rounded to 4 decimals.
- T-023 (R-005): The `sportscut eval-meta DIRECTORY [--json]` CLI mirrors `sportscut eval`: ValueError or OSError gives 'sportscut eval-meta: error: <msg>' on stderr and exit 2. It has no --backend flag yet.
- T-023 (R-005): The template baseline on tests/fixtures/eval_meta is recorded in the README. Every R-005 PR reports the eval-meta score and must not lower it. The existing `sportscut eval` F1 gate is unchanged.
- Tech Lead (dev_blocked): 2026-11-23 T-023: restart from the latest base only after T-004 and T-010 merge; the failure is a missing dependency caused by an empty depends_on, not a code defect.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-010-add-event-types-to-segments-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-003-export-segments-as-mp4-clips-plus-design.md`
- `docs/superpowers/specs/2026-11-23-t-002-detect-highlight-segments-from-audio-excitement-design.md`

## Updated by T-025

The optional Claude LLM backend works per match through
`sportscut.commentary.llm.generate_metas_llm(facts_list)` (one request for all clips) and runs
through `sportscut eval-meta DIRECTORY --meta-backend llm`. `generate_meta` stays template-only
and per clip (`backend='llm'` still raises `ValueError('unknown backend: llm')`).
`eval_meta.validate_meta(facts, meta)` is the runtime gate: an LLM clip is kept only when it
returns no problems; otherwise that clip falls back to the template. `score_case` is unchanged.

## Updated by T-028

Updated by T-028: the format checks at the top of `score_case` are exposed unchanged as `sportscut.commentary.eval_meta.format_problems(meta) -> list[str]` (same messages, same order). `score_case` calls it, so the eval-meta output is unchanged, and `PUT /highlights/{id}/meta` reuses it to return 422 '<where>: <problem>'.
Updated by T-044 (T-042 review): AC16 diffs against `git merge-base main HEAD` (skip 'main is required for scope check' when unavailable) instead of the moving `main` ref; after T-013 its protected list is sportscut/export.py, pyproject.toml and tests/conftest.py.

## Updated by T-026

Updated by T-026: the name and Vietnamese checks are exposed unchanged as `eval_meta._unknown_names(facts, texts)` and `eval_meta._is_vi_text(facts, text)` (`validate_meta` and `_is_vi` call them, so their output is unchanged), and `sportscut.commentary.script.validate_script` reuses them. `evaluate_meta_dir(path, backend="template", script=False)` gains `script=True` (CLI `eval-meta --script`): each case is scored as a timed commentary script at clip lengths 10.0 and 30.0 (`SCRIPT_CLIP_LENS`) with report keys `score, script_fits, fact_recall, hallucination_rate, vi_rate, per_case` (16 items for the fixture). Without `--script` the report is byte-identical to before.

## Updated by T-050

Updated by T-050: each event now has several phrasings. `meta.TITLE_LEADS[event]` (goal 4, other events 3 title leads) and `meta.CAPTION_STYLES[event]` (3 `(opener, closer)` pairs each) hold them; index 0 is the T-023 phrasing (`EVENT_LABELS[event]` and the closer 'Cùng xem lại khoảnh khắc này!'), and every opener contains `EVENT_LABELS[event]`. `generate_meta(facts, backend="template", clip=None)` picks the title lead and the caption style independently with `_pick(part, facts, clip, count) = int.from_bytes(sha256(json.dumps([part, event, minute, home, away, clip], ensure_ascii=False).encode("utf-8")).digest()[:8], "big") % count` (part 'title' or 'caption'; never `hash()` or `random`, so the output does not depend on PYTHONHASHSEED). `clip` is an optional 0-based clip index (None or an int ≥ 0, not a bool; anything else raises ValueError('clip must be a non-negative integer')). The title runs the same fallback chain with the lead in place of the label; the caption is opener + the same match text and optional parts + ' ' + closer; hashtags are unchanged and do not depend on the variant. With both indices 0 the output is byte-identical to T-023. The exact strings of AC5/AC6 are superseded by the hashed picks: the full goal facts give 'Pha lập công: Hà Nội FC vs Hải Phòng, phút 23' and 'Một bàn thắng đáng nhớ trong trận Hà Nội FC gặp Hải Phòng ở phút 23 tại V.League 2026. Tỉ số: 1-0. Hãy cùng xem lại nhé!' (same hashtags); `ClipFacts('other')` gives 'Khoảnh khắc ấn tượng trong trận đấu' (caption unchanged); goal_long_names gives 'Khoảnh khắc ghi bàn, phút 120' (29 characters); `ClipFacts('red_card', 88)` gives 'Tấm thẻ đỏ, phút 88'; `ClipFacts('goal', home='Arsenal')` gives 'Siêu phẩm: Arsenal' (caption still contains 'trong trận đấu của Arsenal'). The eval-meta report stays at score 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0 for every forced variant.
