# T-025: Add an optional Claude LLM backend for metadata with fact validation and template fallback

Request R-005. Plan: `docs/superpowers/plans/2026-11-23-t-025-add-an-optional-claude-llm-backend.md`.

## Product Owner request

Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt.

## Goal

Add a `sportscut[llm]` extra (the anthropic SDK). It is used with `--meta-backend llm` and the `ANTHROPIC_API_KEY` environment variable, and the key is never stored or logged. The default model is `claude-haiku-5-5`, overridable with `SPORTSCUT_LLM_MODEL`. Each match makes one request that sends the facts for all clips and asks for strict JSON. Every result is validated with the eval-meta rules (format, no facts outside the input). An invalid result, a missing key or a network error falls back to the template for that clip and logs a warning. Tests use a fake client with recorded responses, including a hallucinating one that must be rejected, so CI needs no network. A live eval run is reported in the PR. Merge only if the live eval score is at least the template score and hallucination_rate is 0. Assumption: LLM use is opt-in, so the default output stays offline and free.

## Acceptance criteria

- AC1: pyproject.toml has `[project.optional-dependencies] llm == ['anthropic>=0.40']`. `dependencies` (['numpy>=1.26']), `api`, `dev` and `youtube` are unchanged. No module under sportscut/ imports anthropic at module top level, as checked with ast: no top-level Import/ImportFrom of 'anthropic'. `import sportscut.cli` and `import sportscut.commentary.llm` succeed with `sys.modules['anthropic'] = None`.
- AC2: `validate_meta(facts, meta)` exists in sportscut/commentary/eval_meta.py and returns [] for `meta.generate_meta(f)` for every fixture case in tests/fixtures/eval_meta/cases.json, and for every clip of tests/fixtures/llm_meta/good.json with its case's facts.
- AC3: For `ClipFacts('goal', 23, 'Hà Nội FC', 'Hải Phòng', 'V.League 2026', '1-0')`, a caption that says 'phút 24' instead of 'phút 23' gives problems containing 'number 24 not in facts' and 'missing phút 23'. For `ClipFacts('red_card', 88)`, the caption 'Thẻ đỏ dành cho Sergio Ramos ở phút 88. Cùng xem lại tình huống này!' gives 'name Sergio not in facts' and 'name Ramos not in facts'. Capitalised words at the start of the title, or after '. ', '! ', '? ', ': ' or ' | ', are not flagged, and neither are tokens of home, away or competition. An English-only title and caption gives 'not vietnamese'. Leaving out the label, a given name, 'phút <m>' or the score gives 'missing <text>' (for example 'missing Pha cứu thua', 'missing Arsenal', 'missing phút 67', 'missing 2-1'). A 2-hashtag output gives 'hashtag count 2'. Input in NFD form is matched the same as NFC.
- AC4: `score_case` and `evaluate_meta_dir(path)` behave exactly as before. Every existing test in tests/test_eval_meta.py, tests/test_commentary_meta.py and tests/test_t023_acceptance.py passes without edits, except the one-line pyproject removal in test_t023 ac16. `python -m sportscut eval-meta tests/fixtures/eval_meta --json` prints score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0 and vi_rate 1.0. `generate_meta(ClipFacts('goal'), backend='llm')` still raises ValueError('unknown backend: llm').
- AC5: `generate_metas_llm(<the 8 fixture facts>, client=fake)` makes exactly one `client.messages.create` call. Its kwargs have exactly the keys model, max_tokens, system and messages.
- model is 'claude-haiku-5-5' when SPORTSCUT_LLM_MODEL is unset or blank. With SPORTSCUT_LLM_MODEL=' claude-sonnet-5-5 ' it is 'claude-sonnet-5-5'.
- max_tokens is 4096.
- system is SYSTEM_PROMPT, which contains 'JSON', 'phút' and '#[A-Za-z0-9_]+'.
- messages is a single user message whose content json.loads to {'clips': [...]} with 8 entries, ids 0-7. Each entry has event, label == EVENT_LABELS[event], and exactly the non-None facts of that clip, with no None values.

`generate_metas_llm([], client=fake)` returns [] and makes no call.
- AC6: With a fake client returning the text of tests/fixtures/llm_meta/good.json, generate_metas_llm returns the 8 recorded ClipMeta exactly (title, caption, hashtags as a tuple), and logger 'sportscut.commentary.llm' logs no WARNING. The same text wrapped in a ```json ... ``` fence gives the same result.
- AC7: With the text of tests/fixtures/llm_meta/hallucinated.json:
- clips 0, 2, 4 and 7 equal `meta.generate_meta(facts)` (the template), and clips 1, 3, 5 and 6 equal the recorded ones;
- exactly 4 WARNING records are logged, each containing 'clip <i>' and 'template fallback';
- clip 0's warning contains 'number 24 not in facts', clip 2's 'name Ramos not in facts', clip 4's 'not vietnamese' and clip 7's 'hashtag count 2'.
- AC8: Whole-response failures return the template for every clip and log one WARNING containing 'template fallback for all 8 clips'. The failures are:
- (a) a client whose create raises ConnectionError('boom sk-ant-secret'): the warning contains 'ConnectionError' and does not contain 'boom' or 'sk-ant-secret';
- (b) the response text 'not json';
- (c) valid JSON without a 'clips' list.

Per-clip defects fall back only that clip, with the warning 'clip <i>: missing or malformed in LLM response; template fallback'. The defects are: an entry missing for an id, a str or bool id, an out-of-range id, a duplicate id (the first one wins), a non-str title, and hashtags that are not a list.
- AC9: With client=None:
- If ANTHROPIC_API_KEY is unset or whitespace, every clip is the template and one warning contains 'ANTHROPIC_API_KEY is not set'.
- If the key is set and sys.modules['anthropic'] is None, every clip is the template and the warning contains "pip install 'sportscut[llm]'".
- If the key is ' sk-ant-test ' and a fake anthropic module is installed, `anthropic.Anthropic` is called once with api_key='sk-ant-test' and timeout=60.0.
- AC10: The key is never stored or logged. Setup: ANTHROPIC_API_KEY='sk-ant-test-SECRET', a fake anthropic module whose client raises an exception whose message contains the key, and cwd set to tmp_path. Then `main(['eval-meta', FIXTURE, '--json', '--meta-backend', 'llm'])` returns 0, and the key string appears in none of: captured stdout, captured stderr, caplog.text, or any file under tmp_path. In a successful run, the key does not appear in `json.dumps(create_kwargs, ensure_ascii=False)`.
- AC11: `evaluate_meta_dir(FIXTURE, backend='llm')`, with a fake anthropic module and a key set, gives these results:
- With good.json: score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0 and vi_rate 1.0, and the per_case titles equal the good.json titles.
- With hallucinated.json: the same five values, and per_case[0]['title'] equals the template title 'Bàn thắng: Hà Nội FC vs Hải Phòng, phút 23'.

`evaluate_meta_dir(FIXTURE, backend='gpt')` raises ValueError('unknown backend: gpt').
- AC12: In `sportscut eval-meta --help`, --meta-backend is listed. `--meta-backend template` prints the same JSON as no flag. `--meta-backend llm` with ANTHROPIC_API_KEY unset exits 0 and prints score 1.0. `--meta-backend gpt` exits 2 through argparse.
- AC13: Scope:
- `git diff --name-only $(git merge-base main HEAD)` does not touch any of: sportscut/commentary/facts.py, sportscut/commentary/meta.py, sportscut/export.py, sportscut/pipeline.py, sportscut/api.py, sportscut/models.py, tests/conftest.py, tests/fixtures/eval_meta/cases.json, agent-office/.
- The only existing test files edited are the four scope tests listed in the spec, with exactly the narrowing described. (Updated by T-025 review round 1, after T-015 landed: test_t034b keeps main's frozen-paths form minus pyproject.toml, and tests/test_t015_acceptance.py is also edited: pyproject.toml leaves the ac16 FORBIDDEN set and ac11 ignores the removed pyproject.toml line in test_t014.)
- `python -m pytest -q` passes (including test_t013 ac15, test_t014 ac15, test_t023 ac16 and test_t034b ac9_ac10).
- `PATH=/nonexistent python -m pytest -q tests/test_commentary_llm.py tests/test_t025_acceptance.py tests/test_eval_meta.py` passes with anthropic not installed and no network.
- Changed lines outside docs/superpowers are fewer than 500.
- (updated by T-025 review round 2: following the T-028 decision, AC13's scope, edited-old-tests list and < 500 size limit are checked by the Verify commands and in review, not in tests/test_t025_acceptance.py, which has no ac13 test. The only edit to tests/test_t015_acceptance.py is the ac16 FORBIDDEN removal of pyproject.toml; ac11 is unchanged from main, which pins its diff to T-015's own commit.)
- (updated by T-046: the scope/size check is back as tests/test_t025_acceptance.py::test_ac13_scope_and_size. It runs only on the branch that adds that file, the allow-list is t013, t014, t015, t023, t034b, t042, t042_round2, t042_tester, t044, and the size limit is < 520.)
- AC14: README.md has a '### Backend LLM (tùy chọn)' subsection containing:
- "pip install 'sportscut[llm]'";
- 'ANTHROPIC_API_KEY';
- 'SPORTSCUT_LLM_MODEL';
- 'claude-haiku-5-5';
- 'python -m sportscut eval-meta tests/fixtures/eval_meta --json --meta-backend llm';
- 'template fallback'.

The T-023 baseline JSON line is unchanged. The T-023 spec has an '## Updated by T-025' paragraph. T-023 AC16, T-013 AC15, T-014 AC15 and T-041 AC9 carry '(updated by T-025' notes.
- AC15 (live gate, reported in the PR, not run in CI): with a real key, `python -m sportscut eval-meta tests/fixtures/eval_meta --json --meta-backend llm` prints score >= 1.0 and hallucination_rate 0.0, and its stderr contains no 'template fallback'. The PR quotes the five headline values, the model name and the stderr. Without a key, the report states 'LIVE EVAL NOT RUN: no ANTHROPIC_API_KEY' and the task is not merged.

## Out of scope

- `--meta-backend` on `sportscut cut`, `sportscut meta` or POST /highlights. Those commands and fields don't exist on main because T-024 was not merged. The T-024 re-split wires generate_metas_llm in, one call per match.
- Changing `generate_meta` or meta.py (variants, a new backend value). generate_meta stays template-only and per clip.
- Vietnamese voice-over (TTS) and audio mixing, which belong to later R-005 tasks.
- Retries, caching, rate limiting, streaming, structured-output/tool-use modes, prompt caching and cost reporting for the LLM call.
- A configurable timeout, max_tokens, temperature or prompt beyond SPORTSCUT_LLM_MODEL.
- Any other provider (OpenAI, local LLM) and a generic provider abstraction.
- A team or player name dictionary for open-ended hallucination detection. The runtime check is the capitalisation heuristic plus the number check.
- Adding live-network tests to CI, or recording responses with a real key in CI.
- Changing eval-meta scoring (score_case), cases.json, the report keys or the `sportscut eval` F1 gate.
- Fixing the other two-dot `git diff main` fragilities beyond removing pyproject.toml and narrowing the T-034B scope check.

## Decisions

- T-025 (R-005): The LLM backend works per match, not per clip. `sportscut/commentary/llm.py::generate_metas_llm(facts_list, client=None) -> list[ClipMeta]` sends one `messages.create` request for all clips. `meta.generate_meta` stays template-only and keeps raising ValueError('unknown backend: llm'), which revises the T-023 'single interface' decision for the batch case. eval-meta treats its whole fixture set as one match, so it makes one request.
- T-025 (R-005): Because T-024 was not merged (diff_size), `--meta-backend {template,llm}` (default template) is added only to `sportscut eval-meta`, through `evaluate_meta_dir(path, backend='template')`. The T-024 re-split must call generate_metas_llm once per match when it adds `cut --meta`, `sportscut meta` and the API fields.
- T-025 (R-005): The extra is `llm = ['anthropic>=0.40']`. anthropic is imported lazily and only when no client is injected. It is not in the dev extra, so CI never installs it. Tests use injected fake clients, or a fake `anthropic` module placed in sys.modules.
- T-025 (R-005): The model is SPORTSCUT_LLM_MODEL (stripped) or 'claude-haiku-5-5'. The request has exactly model, max_tokens=4096, system=SYSTEM_PROMPT and one user message holding JSON {'clips': [{id, event, label, non-None facts}]}. There is no temperature. The client is `anthropic.Anthropic(api_key=key, timeout=60.0)`.
- T-025 (R-005): The ANTHROPIC_API_KEY value is read only from the environment, into a local variable. It is never logged, written to disk, put in a request body or returned. Request errors log only `type(exc).__name__`, never str(exc).
- T-025 (R-005): `eval_meta.validate_meta(facts, meta)` is the runtime gate. It combines the eval-meta format rules, the unexpected-number check and the vi heuristic (shared private helpers, so score_case output is unchanged) with two runtime-only checks: (1) capitalised tokens not at a sentence start must come from home, away or competition; (2) the title or caption must contain the event label, every given name, 'phút <minute>' and the score. The template always passes it.
- T-025 (R-005): Fallback is per clip. A malformed or rejected clip gets `meta.generate_meta(facts)` and a warning containing 'clip <i>' and 'template fallback'. A missing key, a missing package, a request exception or an unparseable response falls back for all clips with one warning containing 'template fallback for all N clips'. Exit codes are unchanged: an LLM failure is never a CLI error.
- T-025 (R-005): The response parser accepts the JSON optionally wrapped in a single ``` or ```json fence. It NFC-normalises title, caption and hashtags, and does no other repair. Per-clip entries need an int (non-bool) id in range, used once; a str title and caption; and a list of str hashtags.
- T-025 (R-005): The live merge gate on `eval-meta tests/fixtures/eval_meta --json --meta-backend llm` is score >= 1.0 (the template baseline), hallucination_rate == 0.0, and no 'template fallback' in stderr. The last condition is added because, without it, fallbacks would make the score measure the template instead of the model. The PR reports the run. Without a key, the PR says 'LIVE EVAL NOT RUN' and is not merged.
- T-025 (R-005): The recorded responses live in tests/fixtures/llm_meta/good.json (8 valid clips scoring 1.0) and hallucinated.json (clips 0/2/4/7 carry an invented number, an invented player, English text and 2 hashtags). They are the only LLM test inputs, so CI needs no network.
- T-025 (R-005): Per-task scope tests may not freeze files for later tasks (same reasoning as the T-013 decision on T-023 AC16). pyproject.toml is removed from the protected lists in test_t023 ac16, test_t013 ac15 and test_t014 ac15. test_t034b ac9_ac10 now measures its scope and size only over sportscut/web, tests/test_player_page.py and tests/test_t034b_acceptance.py, and no longer protects pyproject.toml. No other assertion changes.
- T-025 (R-005): Size guardrail: changed lines outside docs/superpowers < 500. llm.py <= 110 lines, Developer tests <= 130, Tester acceptance <= 140. The eval-meta template baseline (1.0) and the `sportscut eval` F1 gate are unchanged.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md`
- `docs/superpowers/specs/2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md`
- `docs/superpowers/specs/2026-11-23-t-014-tag-saves-using-whistle-detection-and-design.md`
- `docs/superpowers/specs/2026-11-24-t-041-add-the-theo-d-i-c-design.md`
- `docs/superpowers/specs/2026-11-23-t-015-tag-red-cards-and-controversial-incidents-design.md`
