# Plan T-025: Add an optional Claude LLM backend for metadata with fact validation and template fallback

Design: `docs/superpowers/specs/2026-11-23-t-025-add-an-optional-claude-llm-backend-design.md`.

## Implementation plan

# T-025: Optional Claude LLM backend for clip metadata, with fact validation and template fallback

Request R-005. This builds on T-023 (`sportscut/commentary/`, merged in 37f4067). Before coding, read `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md` and the T-023 lines in `docs/superpowers/DECISIONS.md`.

## Goal

Users can choose to have Claude write the Vietnamese title, caption and hashtags instead of the offline template. The LLM output is accepted only if it passes the same rules eval-meta uses: format, no numbers or names outside the facts, Vietnamese, and every given fact mentioned. Anything else falls back to the template for that clip. The default stays offline and free. CI never touches the network.

## What main has today (read before coding)

- `sportscut/commentary/meta.py`: `generate_meta(facts, backend='template')` works per clip. Any other backend raises `ValueError('unknown backend: <b>')`. `tests/test_commentary_meta.py:63` and `tests/test_t023_acceptance.py:234` pin this. **meta.py is not changed by this task.**
- `sportscut/commentary/eval_meta.py`: `load_cases`, `score_case`, `evaluate_meta_dir(path)`. evaluate_meta_dir calls `meta_module.generate_meta(case.facts)` with ONE positional argument. Existing tests monkeypatch it with `lambda facts: ...`, so the template path must keep exactly that call.
- `sportscut/cli.py`: `eval-meta DIRECTORY [--json]`. The CLI configures no logging, so a WARNING log record reaches stderr through Python's last-resort handler.
- T-024 (`cut --meta`, `sportscut meta`, POST meta fields) was **not merged** because of diff_size, so main has no `cut --meta`, no `annotate.py` and no variants. This task therefore wires `--meta-backend` only into `eval-meta`, plus the library function `generate_metas_llm`. When T-024's re-split lands, it calls `generate_metas_llm` once per match from `cut`, `meta` and the API.
- Per-task scope tests freeze `pyproject.toml` on every later branch: test_t023 ac16, test_t013 ac15, test_t014 ac15 and test_t034b ac9_ac10. test_t034b ac9_ac10 also fails on any branch that changes a non-web file, because it asserts that every changed path is in the T-034B allow-list. These tests must be narrowed, following the DECISIONS precedent from T-013 ('a per-task scope rule cannot freeze a file for later tasks').

## Design

### 1. `pyproject.toml`

Add `llm = ["anthropic>=0.40"]` under `[project.optional-dependencies]`. `dependencies`, `api`, `youtube` and `dev` stay unchanged; test_t005 and test_t006 pin them. anthropic is NOT added to `dev`, so CI never installs or imports it.

### 2. `sportscut/commentary/eval_meta.py`: shared checks plus `validate_meta`

Move the existing checks out of `score_case` into private helpers. `score_case` output must stay byte-identical, and all existing tests must pass unchanged.
- `_format_problems(meta) -> list[str]`: the current title, caption, hashtag-count, bad-hashtag and duplicate-hashtag checks, with the same strings.
- `_unexpected_numbers(facts, output: str) -> list[str]`: the numbers in `output` that are not in `_facts_text(facts)`, in first-seen order.
- `_is_vi(facts, meta) -> bool`: the current 30% diacritic heuristic.

`score_case` uses these three helpers.

Add the public function `validate_meta(facts: ClipFacts, meta: ClipMeta) -> list[str]`. It returns problems in this order; `[]` means valid:
1. `_format_problems(meta)`.
2. `f'number {n} not in facts'` for each unexpected number. Use the same `_output_text` as score_case, so title, caption and hashtags are all checked.
3. Names: split the title and the caption separately with `re.split(r'[.!?:|]\s+', text)`. In each segment, take the letter tokens `re.findall(r'[^\W\d_]+', NFC(segment))` and skip the segment's first token. Any other token whose first character `isupper()` and whose casefold is not among the casefolded letter tokens of home, away and competition gives `f'name {token} not in facts'`, once per distinct token.
4. Missing facts. Each of these must appear, NFC plus casefold, as a substring of title + '\n' + caption (hashtags are not counted):
   - `EVENT_LABELS[facts.event]`;
   - each non-None home, away and competition, verbatim;
   - `f'phút {facts.minute}'` when the minute is set;
   - the score when it is set.

   Each absent one gives `f'missing {text}'`, using the original text (for example 'missing phút 23', 'missing Pha cứu thua').
5. `'not vietnamese'` when `_is_vi` is False.

The template always passes, because its caption states the label, every name, 'phút m' and the score. `score_case` (the eval) does not use the name and missing checks; they are runtime-only.

Change `evaluate_meta_dir(path, backend='template')`:
- An unknown backend raises `ValueError(f'unknown backend: {backend}')` before any file is read.
- For `'template'`, keep the current list comprehension that calls `meta_module.generate_meta(case.facts)`.
- For `'llm'`, do `from sportscut.commentary import llm` inside the function (a top-level import would be circular), then `outputs = llm.generate_metas_llm([case.facts for case in cases])`. The whole eval set counts as one 'match', so it is one request.

The report keys and the rounding are unchanged.

### 3. `sportscut/commentary/llm.py` (new, at most about 110 lines)

```python
DEFAULT_MODEL = 'claude-haiku-5-5'
MODEL_ENV = 'SPORTSCUT_LLM_MODEL'
KEY_ENV = 'ANTHROPIC_API_KEY'
MAX_TOKENS = 4096
TIMEOUT_SEC = 60.0
SYSTEM_PROMPT = '...'  # see below
logger = logging.getLogger(__name__)  # 'sportscut.commentary.llm'

def model_name() -> str                      # os.environ.get(MODEL_ENV, '').strip() or DEFAULT_MODEL
def build_request(facts_list) -> dict        # kwargs for client.messages.create
def parse_response(text: str, count: int) -> list[ClipMeta | None] | None
def generate_metas_llm(facts_list, client=None) -> list[ClipMeta]
```

There is no top-level `import anthropic`. It is imported lazily inside generate_metas_llm and only when `client is None`.

`build_request(facts_list)` returns exactly these keys:
- `model=model_name()`
- `max_tokens=MAX_TOKENS`
- `system=SYSTEM_PROMPT`
- `messages=[{'role': 'user', 'content': json.dumps({'clips': clips}, ensure_ascii=False)}]`

Clip i is `{'id': i, 'event': f.event, 'label': EVENT_LABELS[f.event]}`, plus minute, home, away, competition and score only when they are not None. It has no temperature or other parameters.

SYSTEM_PROMPT is English instructions; the output is Vietnamese. Content:
- You write Vietnamese social-media metadata for football highlight clips.
- The input JSON has 'clips', each with id, event, label and optional minute, home, away, competition and score.
- Reply with JSON only (no prose, no code fence): {'clips': [{'id', 'title', 'caption', 'hashtags'}]}, one object per input clip.
- Write Vietnamese with diacritics.
- The title is 10-80 characters and the caption 1-300 characters.
- Give 3-8 unique hashtags matching #[A-Za-z0-9_]+.
- The title or caption must contain the label verbatim, every given name verbatim, 'phút <minute>' when a minute is given, and the score verbatim when it is given.
- Use no number that is not in that clip's facts.
- Name no player, team, coach, referee or competition that is not in the facts.
- Never say who scored.
- Capitalise only the first word of a sentence and the given names.

The constant must contain the substrings 'JSON', 'phút' and '#[A-Za-z0-9_]+'.

`parse_response(text, count)`:
1. Strip the text. If it fully matches `` ```(?:json)?\s*(.*?)\s*``` `` (DOTALL), use group 1.
2. Parse it with `json.loads`. Return `None` (a whole-response failure) on a JSON error, a non-dict, or a missing or non-list `'clips'`.
3. Otherwise build a list of length `count`, all None. For each element that is a dict with:
   - an `id` that is an int (not a bool), in `range(count)` and not already filled;
   - a str `title` and a str `caption`;
   - a `hashtags` list of str,

   set slot id to `ClipMeta(NFC(title), NFC(caption), tuple(NFC(h) for h in hashtags))`. Other elements and extra keys are ignored. No stripping or fixing is done; validation decides.

`generate_metas_llm(facts_list, client=None)`. Here `fallback(f) = meta.generate_meta(f)`, called through the module attribute, and n = len(facts_list).
1. If n == 0, return [] and make no request.
2. If client is None:
   - `key = os.environ.get(KEY_ENV, '').strip()`. If it is empty, log `logger.warning('ANTHROPIC_API_KEY is not set; template fallback for all %d clips', n)` and return all fallbacks.
   - `import anthropic`. On ImportError, warn `"the llm backend needs the [llm] extra (pip install 'sportscut[llm]'); template fallback for all %d clips"` and return all fallbacks.
   - `client = anthropic.Anthropic(api_key=key, timeout=TIMEOUT_SEC)`.

   The key lives only in that local variable. It is never logged, written, put in the request body or returned.
3. `response = client.messages.create(**build_request(facts_list))`. If it raises any `Exception as exc`, warn `'LLM request failed (%s); template fallback for all %d clips'` with `type(exc).__name__`. Never log `str(exc)`. Return all fallbacks.
4. `text = ''.join(block.text for block in response.content if getattr(block, 'type', None) == 'text')`.
5. `parsed = parse_response(text, n)`. If it is None, warn `'LLM response is not valid JSON; template fallback for all %d clips'` and return all fallbacks.
6. For each i:
   - If `parsed[i] is None`, warn `'clip %d: missing or malformed in LLM response; template fallback'` and use the fallback.
   - Else, if `problems := validate_meta(facts_list[i], parsed[i])`, warn `'clip %d: rejected LLM metadata (%s); template fallback'` with `'; '.join(problems)` and use the fallback.
   - Else use `parsed[i]`.

Every fallback warning contains the phrase 'template fallback'. The live merge gate checks stderr for it.

### 4. `sportscut/cli.py`

`eval-meta` gets `--meta-backend` with `choices=('template', 'llm')`, `default='template'`, and help 'metadata generator to score; llm needs ANTHROPIC_API_KEY and the [llm] extra'. Call `eval_meta.evaluate_meta_dir(args.directory, backend=args.meta_backend)`. Error handling and output stay as they are.

### 5. Recorded responses: `tests/fixtures/llm_meta/good.json` and `hallucinated.json`

Each file is the raw text a model would return for the 8 cases of `tests/fixtures/eval_meta/cases.json`, in fixture order (ids 0-7). The format is `{"clips": [` on the first line, then one clip object per line, then `]}`, in UTF-8 with literal Vietnamese.

good.json:
- 0: title 'Bàn thắng đẹp mắt: Hà Nội FC vs Hải Phòng'
  - caption 'Bàn thắng ở phút 23 trong trận Hà Nội FC gặp Hải Phòng tại V.League 2026. Tỉ số: 1-0. Đừng bỏ lỡ!'
  - hashtags #BongDa #BanThang #HaNoiFC #HaiPhong #VLeague
- 1: title 'Pha cứu thua xuất sắc: Arsenal vs Chelsea'
  - caption 'Pha cứu thua ở phút 67 trong trận Arsenal gặp Chelsea tại Premier League. Cùng xem lại pha bóng này!'
  - hashtags #BongDa #CuuThua #Arsenal #Chelsea #PremierLeague
- 2: title 'Thẻ đỏ gây chú ý ở phút 88'
  - caption 'Thẻ đỏ được rút ra ở phút 88. Cùng xem lại tình huống này!'
  - hashtags #BongDa #TheDo #Highlight
- 3: title 'Tình huống gây tranh cãi tại Cúp Quốc gia'
  - caption 'Tình huống gây tranh cãi trong trận Thép Xanh Nam Định gặp Hoàng Anh Gia Lai tại Cúp Quốc gia. Bạn nghĩ sao về pha bóng này?'
  - hashtags #BongDa #TranhCai #ThepXanhNamDinh #HoangAnhGiaLai #CupQuocGia
- 4: title 'Khoảnh khắc đáng chú ý không thể bỏ qua'
  - caption 'Khoảnh khắc đáng chú ý trong trận đấu. Hãy cùng xem lại nhé!'
  - hashtags #BongDa #KhoanhKhac #Highlight
- 5: title 'Bàn thắng phút 120, tỉ số 3-2'
  - caption 'Bàn thắng ở phút 120 trong trận Câu lạc bộ Bóng đá Công an Hà Nội gặp Becamex Bình Dương Football Club tại Night Wolf V.League 1. Tỉ số: 3-2. Cùng xem lại!'
  - hashtags #BongDa #BanThang #CongAnHaNoi #BinhDuong #VLeague
- 6: title 'Bàn thắng đáng nhớ: U23 Việt Nam vs U23 Thái Lan'
  - caption 'Bàn thắng ở phút 45 trong trận U23 Việt Nam gặp U23 Thái Lan tại SEA Games 33. Tỉ số: 2-2. Xem ngay!'
  - hashtags #BongDa #BanThang #U23VietNam #U23ThaiLan #SEAGames33
- 7: title 'Pha cứu thua ở phút 5 tại Champions League'
  - caption 'Pha cứu thua ở phút 5 tại Champions League. Tỉ số: 0-0. Cùng xem lại pha bóng này!'
  - hashtags #BongDa #CuuThua #ChampionsLeague

hallucinated.json is the same, except:
- 0: caption 'Bàn thắng ở phút 24 trong trận Hà Nội FC gặp Hải Phòng tại V.League 2026. Tỉ số: 1-0. Đừng bỏ lỡ!' (an invented number).
- 2: caption 'Thẻ đỏ dành cho Sergio Ramos ở phút 88. Cùng xem lại tình huống này!' (an invented player).
- 4: title 'Great moment of the match', caption 'What a moment. Watch it again!' (English, no label).
- 7: hashtags #BongDa #CuuThua only (format).

If a good.json line fails `validate_meta` or `score_case` because of a heuristic detail, the Developer may reword that line in Vietnamese as long as it keeps every listed fact. They must not loosen the rules.

### 6. Narrow the scope tests (Tech Lead precedent from T-013; no other assertion changes)

- `tests/test_t023_acceptance.py::test_ac16...`: remove 'pyproject.toml' from `protected`.
- `tests/test_t013_acceptance.py::test_ac15...`: remove 'pyproject.toml' from `forbidden`.
- `tests/test_t014_acceptance.py::test_ac15...`: remove 'pyproject.toml' from `forbidden`.
- `tests/test_t034b_acceptance.py::test_ac9_ac10_scope_and_size`:
  - remove 'pyproject.toml' from the `--exit-code` diff;
  - in the `--numstat` diff, replace `'.', ':(exclude)docs/superpowers'` with `'sportscut/web', 'tests/test_player_page.py', 'tests/test_t034b_acceptance.py'`;
  - in the `ls-files` call, replace `'sportscut', 'tests'` with the same three paths.

  The allow-list and the line budgets are unchanged. They now measure only T-034B's own files.

### 7. Docs

- README.md: under the eval-meta section, add a subsection '### Backend LLM (tùy chọn)'. It covers:
  - `pip install 'sportscut[llm]'`;
  - `ANTHROPIC_API_KEY` (read only from the environment, never stored or logged);
  - `SPORTSCUT_LLM_MODEL` (default `claude-haiku-5-5`);
  - the command `python -m sportscut eval-meta tests/fixtures/eval_meta --json --meta-backend llm`;
  - one request per match, and the per-clip template fallback with a 'template fallback' warning;
  - the live result line from Step 9.

  The T-023 baseline JSON line stays byte-identical.
- Specs: append '(updated by T-025: pyproject.toml may gain optional extras; the llm extra is added by T-025)' to:
  - T-023 AC16;
  - T-013 AC15;
  - T-014 AC15;
  - T-041 AC9, where the note also says the T-034B scope/size check covers only its own files.

  Also append a '## Updated by T-025' paragraph to the T-023 spec. It says the LLM backend is per match via `generate_metas_llm` and runs through `eval-meta --meta-backend llm`, that `generate_meta` stays template-only, and that `validate_meta` is the runtime gate.

## Steps (TDD: write the failing test, run it and see it fail for the right reason, implement, see it pass)

1. Narrow the four scope tests (section 6). Run `python -m pytest -q tests/test_t023_acceptance.py tests/test_t013_acceptance.py tests/test_t014_acceptance.py tests/test_t034b_acceptance.py`; it passes on the clean branch.
2. Write the validate_meta tests in tests/test_commentary_llm.py, then refactor eval_meta.py and add validate_meta. Run `python -m pytest -q tests/test_eval_meta.py tests/test_t023_acceptance.py`; it is unchanged and green.
3. Write the two fixture files, plus a test that every good.json clip passes validate_meta and scores 1.0 with score_case.
4. Write the build_request, model_name and parse_response tests, then implement them.
5. Write the generate_metas_llm tests: fake client, good, hallucinated, errors, no key, no package, key hygiene. Then implement.
6. Write the evaluate_meta_dir backend tests (fake `anthropic` module via `monkeypatch.setitem(sys.modules, 'anthropic', fake)` plus `setenv`), then implement.
7. Write the CLI `--meta-backend` tests, then implement.
8. Add the pyproject extra, the README section and the spec notes, with a README test.
9. Verify:
   - `python -m pytest -q`: quote the summary line.
   - `PATH=/nonexistent python -m pytest -q tests/test_commentary_llm.py tests/test_eval_meta.py tests/test_t023_acceptance.py` passes.
   - `python -m sportscut eval-meta tests/fixtures/eval_meta --json` still prints score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0.
   - Live run, if `ANTHROPIC_API_KEY` is set: `pip install -e '.[llm]' && python -m sportscut eval-meta tests/fixtures/eval_meta --json --meta-backend llm 2> /tmp/t025.err`. Report the five headline values, the model and the content of /tmp/t025.err. If no key is available, write 'LIVE EVAL NOT RUN: no ANTHROPIC_API_KEY' in the report. Never echo the key.

## Merge gate

Merge only if the live run shows:
- score >= 1.0 (the template baseline);
- hallucination_rate == 0.0;
- no 'template fallback' line in stderr, so the number measures the model and not the fallback.

Without a live run the PR is not merged. The `sportscut eval` F1 gate is untouched.

## Budgets

Changed lines outside docs/superpowers must stay under 500:
- production code about 170 (llm.py <= 110, eval_meta.py +45, cli.py +6, pyproject +1);
- fixtures about 20;
- Developer tests <= 130;
- Tester acceptance <= 140;
- scope-test edits <= 12;
- README about 20.

## Assumptions

- LLM use is opt-in (`--meta-backend llm`). The default is the offline template, byte-identical to today.
- In eval-meta, the whole fixture set is sent as one request, standing in for one match.
- A missing anthropic package is treated like a missing key: warn and fall back, exit 0. The user still gets usable metadata.
- The name check is a conservative heuristic: capitalised tokens that are not at the start of a sentence must come from the given names. A single invented name that opens a sentence is not caught; the prompt forbids it.
- Requiring every given fact to be mentioned keeps an accepted LLM clip from scoring below the template on fact_recall.

## Test plan

- Developer, tests/test_commentary_llm.py (<= 130 lines, pure Python, no ffmpeg): FakeClient/FakeMessages built on SimpleNamespace record the create kwargs and return `SimpleNamespace(content=[SimpleNamespace(type='text', text=TEXT)])` or raise. A helper loads the fixture facts with eval_meta.load_cases.
- test_validate_meta_template_and_good_fixture_pass: [] for the template output of every case and for every good.json clip; score_case on every good.json clip gives score 1.0.
- test_validate_meta_problems: parametrised over wrong number, invented name, sentence-start capitals allowed, name tokens allowed, English, missing label/name/minute/score, 2 hashtags and NFD input; asserts the exact problem strings from AC3.
- test_build_request_shape_and_model_env: AC5, including blank SPORTSCUT_LLM_MODEL, a stripped override, no None-valued keys, and the SYSTEM_PROMPT substrings.
- test_parse_response: fence stripping; the whole-response None cases (bad JSON, non-dict, no clips list); per-element rejects (str/bool/out-of-range/duplicate id, non-str title, non-list hashtags); NFC normalisation of NFD title text.
- test_generate_good_and_hallucinated: AC6 and AC7 with caplog at WARNING on 'sportscut.commentary.llm'; checks the per-clip sources and the warning texts.
- test_generate_failures_and_no_key: AC8 and AC9. Exception class name only in the log; the key env var unset or blank; `monkeypatch.setitem(sys.modules, 'anthropic', None)`; a fake anthropic module that records the Anthropic(api_key, timeout) call.
- test_eval_meta_llm_backend_and_cli: evaluate_meta_dir(FIXTURE, backend='llm') with the fake module and good/hallucinated text (AC11); backend='gpt' raises ValueError; CLI --meta-backend template/llm/gpt and --help (AC12).
- test_readme_llm_section: the AC14 README strings.
- Tester, tests/test_t025_acceptance.py (<= 140 lines), written from the ACs and not from the Developer tests. It builds its own fake client and fake `anthropic` module (types.ModuleType with an Anthropic class) and covers AC1 (ast scan of sportscut/**/*.py for a top-level anthropic import, a pyproject tomllib check, import with sys.modules['anthropic']=None), AC3, AC5, AC7, AC8, AC9, AC10 (key-leak check across stdout, stderr, caplog and tmp_path files) and AC11-AC12. (Updated by T-025 review round 2: AC13 scope and size are not tested in pytest, per the T-028 decision; they are checked by the Verify commands and in review.)
- Tester confirms that the tests can fail: temporarily accepting LLM output without calling validate_meta must make the hallucinated-fixture test fail; logging str(exc) must make the key-leak test fail. Revert afterwards and report both.
- Regression run: `python -m pytest -q` (quote the summary line); `PATH=/nonexistent python -m pytest -q tests/test_commentary_llm.py tests/test_t025_acceptance.py tests/test_eval_meta.py`; `python -m sportscut eval-meta tests/fixtures/eval_meta --json` prints the unchanged baseline 1.0/1.0/1.0/0.0/1.0.
- Live eval (manual, PR report): `pip install -e '.[llm]'` then `python -m sportscut eval-meta tests/fixtures/eval_meta --json --meta-backend llm 2> /tmp/t025.err`. Report score, hallucination_rate, model and stderr; the gate is in AC15.

## Deviations

Written by the Developer (T-025).

- `generate_metas_llm`: reading `block.text` from `response.content` sits inside the same `try` as
  `client.messages.create`, so a malformed response object also falls back with the
  'LLM request failed (<ExcType>); template fallback for all n clips' warning instead of crashing.
- `build_request`: clip keys are built as id, label, then the non-None fields of `ClipFacts` in
  field order (event, minute, home, away, competition, score). Same keys as the spec; only the
  JSON key order differs.
- Size: the non-doc diff is about 409 changed lines before the Tester's file (production about
  190: llm.py 109 lines, eval_meta.py +57/-17, cli.py +5/-1, pyproject +1; fixtures 20;
  README 19; scope tests 9; Developer tests 171 against the 130 estimate; total 409). Once the Tester's
  file is added, the < 500 budget leaves the Tester about 90 lines, not 140. The 4000-line
  orchestrator guardrail is not at risk.
- Size, after the Tester's AC13 report (549 lines): the Developer side was trimmed to 354 changed lines
  (llm.py 106, eval_meta.py +52/-17, cli.py +5/-1, pyproject +1, fixtures 20, README 14, scope tests 9,
  Developer tests 129). With the Tester's 140 the non-doc diff is 494 (< 500). No test coverage or
  behaviour was removed; the tests were compacted and the name check was written as comprehensions.
- No live eval was run: no `ANTHROPIC_API_KEY` was available in the Developer session
  ('LIVE EVAL NOT RUN: no ANTHROPIC_API_KEY'). The README states this until a live run is recorded.
- Review round 1 (after T-015, dc06807, landed on main): main was merged into the branch (uncommitted, for the orchestrator to commit). Step 6's numstat/ls-files narrowing of test_t034b is dropped; that test keeps main's frozen-paths assert with only "pyproject.toml" removed. tests/test_t015_acceptance.py gets two one-line narrowings (ac16 FORBIDDEN without pyproject.toml; ac11 `removed` ignores the pyproject.toml line). The non-doc diff against main is 494 lines. The Tester's test_ac13 allow-list of edited old tests (t013, t014, t023, t034b) needs t015 added; see .office/DEV_NOTES.md.
- test_t015 ac11 line 532 narrowed from == to <= (per-task diff check; the AST holders check still pins the stubs); test_t025 ac13 allow-list gains t015 (Tech Lead round 1).
- Review round 2 (after T-028 landed on main): the round-1 test_t015 ac11 edits are reverted (`==` again, no `removed` filter), because T-028 pins that diff to T-015's own commit. test_t025's ac13 git scope/size test is deleted per the T-028 decision. In `generate_metas_llm` the `anthropic.Anthropic(...)` constructor now sits inside the same `try` as the request, so a constructor error also gives 'LLM request failed (<ExcType>); template fallback for all n clips' instead of a traceback.
