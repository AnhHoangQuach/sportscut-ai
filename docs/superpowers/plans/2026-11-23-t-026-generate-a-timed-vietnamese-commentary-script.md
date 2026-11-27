# Plan T-026: Generate a timed Vietnamese commentary script per clip

Design: `docs/superpowers/specs/2026-11-23-t-026-generate-a-timed-vietnamese-commentary-script-design.md`.

## Implementation plan

# T-026: Generate a timed Vietnamese commentary script per clip

Request R-005 (Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt). This task produces **text and timing only**. The voice-over audio is task 5 (T-027). T-028's preview already shows a 'Lồng tiếng' toggle when a highlight carries `voiceover_url`. T-026 never emits that field.

Read these first:
- `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md` and the T-023 lines in `DECISIONS.md` (ClipFacts, labels, eval-meta rules and report keys).
- `docs/superpowers/specs/2026-11-26-t-046-re-land-the-reviewed-t-025-design.md` (llm.py, validate_meta, fallback and logging rules).
- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md` (pipeline.run, manifest).
- `sportscut/commentary/{facts,meta,eval_meta,llm}.py`, `sportscut/pipeline.py`, `sportscut/cli.py`, `sportscut/detect.py` (PRE_SEC=8, POST_SEC=4).

**Step 0 (precondition).** `python -c "from sportscut.commentary import llm, eval_meta; from sportscut.commentary.eval_meta import validate_meta; print('READY')"` must print READY. Otherwise report BLOCKED.

## Design

### 1. `sportscut/commentary/script.py` (new)

Pure Python plus numpy. It runs no external tools. Imports: `math`, `re`, `unicodedata`, `logging`, `numpy`, `sportscut.detect` (PRE_SEC, POST_SEC), `sportscut.media.SAMPLE_RATE`, `sportscut.commentary.eval_meta` (helpers, see §2), and `sportscut.commentary.meta.EVENT_LABELS`. It imports `sportscut.commentary.llm` lazily inside `write_script`. `logger = logging.getLogger(__name__)`.

Constants:
```python
SYLLABLES_PER_SEC = 3.5
PAD = 0.25        # silence kept at the clip start and end (s)
GAP = 0.25        # pause between lines when placing (s)
MAX_LINES = 3
MAX_TEXT = 200    # characters per line
EPS = 1e-6
MOMENT_LINES = {
    "goal": "Vào! Bàn thắng!",
    "save": "Pha cứu thua tuyệt vời!",
    "red_card": "Trọng tài rút thẻ đỏ!",
    "controversy": "Tình huống gây tranh cãi!",
    "other": "Khoảnh khắc đáng chú ý!",
}
```

Functions (public):
- `syllables(text: str) -> int`: on the NFC text, the number of letter runs (regex `[^\W\d_]+`) plus the number of decimal digits. Vietnamese writes one syllable per word, and each digit is read as about one syllable. Example: `syllables("Phút 23, Hà Nội FC.") == 6`.
- `speech_seconds(text: str) -> float`: `syllables(text) / SYLLABLES_PER_SEC`.
- `default_peak(clip_len: float) -> float`: `clip_len * PRE_SEC / (PRE_SEC + POST_SEC)`. This is the detector's peak position, the same anchor that facts_from_entry uses.
- `audio_peak(samples: np.ndarray, clip_len: float) -> float | None`: the centre of the loudest whole second inside the clip. Let `n = min(len(samples) // SAMPLE_RATE, math.floor(clip_len))`. If n == 0, return None. Otherwise compute the per-second RMS over `samples[: n*SAMPLE_RATE].reshape(n, SAMPLE_RATE)` and return `float(argmax) + 0.5`, where the first maximum wins ties. The result is always `< clip_len`.
- `fit_problems(lines, clip_len) -> list[str]`: the timing contract. `lines` is a sequence of `(start, text)`. Let `end_i = start_i + speech_seconds(text_i)`. Problems are:
  - `line count N` unless 1 <= N <= MAX_LINES;
  - `line i starts before the window` if start_i is not finite or start_i < PAD - EPS;
  - `line i overruns the clip` if end_i > clip_len - PAD + EPS;
  - `line i overlaps line i-1` if start_i < end_(i-1) - EPS (this also covers unsorted lines).
  Lines are 1-based in messages. Together these rules mean that the total estimated speech is at most the available window `clip_len - 2*PAD`, that is about 3.5 syllables per second of available time.
- `script_fits(lines, clip_len) -> bool`: `not fit_problems(lines, clip_len)`.
- `validate_script(facts, lines, clip_len) -> list[str]`: the single validation for every backend. It returns `fit_problems`, then:
  - `line i text` for a text that is not a str, is empty, is not stripped, or is longer than MAX_TEXT;
  - `number X not in facts` from `eval_meta._unexpected_numbers(facts, joined)`;
  - `name X not in facts` from `eval_meta._unknown_names(facts, texts)`;
  - `not vietnamese` unless `eval_meta._is_vi_text(facts, joined)`.
  Here `joined = "\n".join(texts)`. An empty list gives `line count 0` plus `not vietnamese`.
- `write_script(facts, clip_len, backend="template", *, peak=None, client=None) -> list[tuple[float, str]]`:
  - **Input checks:** `clip_len` must be a finite int/float (not a bool) > 0, and `peak` must be None or finite with 0 <= peak < clip_len. Otherwise raise ValueError. A `backend` other than `template` or `llm` also raises ValueError (`unknown backend: X`). `peak=None` means `default_peak(clip_len)`.
  - **Return value:** 1-3 `(start, text)` tuples in time order (start in clip seconds, float, not rounded). It returns `[]` only when not even the moment line fits (clips under about 2 s).

Placement (private `_place(before, at, after, clip_len, peak)`, used by both backends; `before` and `after` may be None):
```
d = speech_seconds
s_at = max(PAD, min(peak, clip_len - PAD - d(at)))   # the moment line starts at the audio peak, pulled earlier only if it would overrun
before line start = s_at - GAP - d(before)
after line start  = s_at + d(at) + GAP
result = [before?, at, after?] as (start, text)
```
Placement never drops a line. Only `validate_script` decides whether a candidate is usable.

Template backend: candidates are tried in order, and the first with `validate_script(...) == []` is returned. If none passes, return `[]`.
- `at = MOMENT_LINES[facts.event]`. Every moment line contains the event label's key words (bàn thắng, cứu thua, thẻ đỏ, tranh cãi, khoảnh khắc).
- The teams part T is `"{home} gặp {away}"` when both are given, `"trận đấu của {x}"` when one is given, and `"trận đấu"` otherwise. The competition part is C = `" tại {competition}"`, or empty.
- `before` variants, in order and de-duplicated, are used only if the facts have a minute, home, away or competition:
  1. full: `"Phút {m}, {T}{C}."` if minute, else `T + C + "."` with the first character upper-cased;
  2. the same without C;
  3. `"Phút {m}."` if minute;
  4. None.
  With no such facts, the only variant is None.
- `after = "Tỉ score {score}."` → exactly `"Tỉ số {score}."` if a score is given, else None.
- The order is: for each before variant, first with `after`, then with None (only None when there is no score). The last candidate is the moment line alone.
- The before line gives context and never names the event. The event is named at the peak, and the score comes after it. No line says who scored.

LLM backend: compute the limits
- `before_max_syllables = max(0, floor(3.5 * (peak - PAD - GAP)))`
- `at_after_max_syllables = max(0, floor(3.5 * (clip_len - PAD - max(peak, PAD))))`

Call `llm.script_roles_llm(facts, {"clip_len": clip_len, "peak": peak, "before_max_syllables": ..., "at_after_max_syllables": ...}, client=client)`.
- If it returns None, use the template; llm has already logged why.
- Otherwise call `_place(roles["before"], roles["at"], roles["after"], clip_len, peak)` and then `validate_script`.
- If there are problems, log `logger.warning("rejected LLM script (%s); template fallback", "; ".join(problems))` and return the template result. Otherwise return the placed lines.

### 2. `sportscut/commentary/eval_meta.py` (change)
- Refactor without changing behaviour:
  - Extract `_unknown_names(facts, texts: list[str]) -> list[str]` from the name check in `validate_meta`. It returns the unique offending tokens in order: segments split on `[.!?:|]\s+`, the first token of each segment skipped, a capitalised token not in `_name_tokens(facts)`. `validate_meta` builds its `name X not in facts` messages from it.
  - Extract `_is_vi_text(facts, text) -> bool`. `_is_vi(facts, meta)` becomes `_is_vi_text(facts, meta.title + " " + meta.caption)`.
  - Every existing test passes unchanged.
- Add `SCRIPT_CLIP_LENS = (10.0, 30.0)`.
- Add `score_script_case(case, clip_len, lines) -> dict` with keys in this order: `id, clip_len, score, script_fits, fact_recall, hallucinated, vi, problems, lines`.
  - `text = "\n".join(texts)` and `output = _normalise(text)`.
  - `script_fits = script.script_fits(lines, clip_len)`.
  - `fact_recall = _met_groups(case, output) / len(case.must_mention)`.
  - `hallucinated` is set by an unexpected number or by a forbidden needle in output.
  - `vi = _is_vi_text(case.facts, text)`.
  - `problems` = fit_problems + `number X not in facts` + `forbidden X` + `not vietnamese`.
  - `score = fact_recall if script_fits and not hallucinated and vi else 0.0`.
  - `lines` is `[{"start": s, "text": t}]`.
  - Floats are rounded to 4 places as in score_case, except the line starts.
- `evaluate_meta_dir(path, backend="template", script=False)`:
  - With `script=False`, the code path and output stay byte-identical to today.
  - With `script=True`, import `sportscut.commentary.script` lazily (a top-level import would be circular). For each case in file order, and for each clip_len in SCRIPT_CLIP_LENS, call `lines = script.write_script(case.facts, clip_len, backend)` and then `score_script_case`.
  - Report keys, in order: `score` (mean item score), `script_fits` (share of items), `fact_recall` (micro over must_mention groups of all items), `hallucination_rate`, `vi_rate`, `per_case` (2 items per case: 10.0 first, then 30.0). All values are rounded to 4 places.
  - The directory and cases.json checks are the same as today. `tests/fixtures/eval_meta/cases.json` is not changed.

### 3. `sportscut/commentary/llm.py` (additive; `generate_metas_llm`, `build_request`, `parse_response` and SYSTEM_PROMPT stay byte-identical)
- Add `SCRIPT_PROMPT` (Vietnamese football commentary for one clip). It says:
  - reply with JSON only `{"before": str|null, "at": str, "after": str|null}`;
  - `at` is spoken at the event moment and contains the label;
  - `before` is context before the moment and must not reveal the event;
  - keep `before` within before_max_syllables and `at`+`after` within at_after_max_syllables (one syllable per Vietnamese word, one per digit);
  - Vietnamese with diacritics;
  - no number or name that is not in the facts;
  - never say who scored;
  - capitalise only sentence starts and the given names.
- Add `script_roles_llm(facts, limits: dict, client=None) -> dict | None`.
  - The request is `{"model": model_name(), "max_tokens": 1024, "system": SCRIPT_PROMPT, "messages": [{"role": "user", "content": json.dumps({"label": EVENT_LABELS[facts.event], **non-None facts fields, **limits}, ensure_ascii=False)}]}`.
  - The key, import, client and exception handling are the same as `generate_metas_llm`:
    - no `ANTHROPIC_API_KEY` → warning `ANTHROPIC_API_KEY is not set; template fallback` and no network call;
    - ImportError → warning containing `pip install 'sportscut[llm]'` and `template fallback`;
    - any exception → warning `LLM script request failed (<ExceptionTypeName>); template fallback`.
  - Never log str(exc), the key or the request.
  - Parsing: strip a ```json fence, then json.loads. The result must be a dict. `at` must be a str that is non-empty after NFC+strip. `before` and `after` must each be None or a str (NFC+strip; empty → None). Anything else → warning `LLM script response is not valid; template fallback` and return None.
  - It returns `{"before": ..., "at": ..., "after": ...}` (NFC, stripped).

### 4. `sportscut/pipeline.py` (change)
- New last parameter `voiceover: bool = False` (after `score_box`). With `voiceover=False`, behaviour, files and manifest are unchanged.
- With `voiceover=True`, after export and after the vertical block, for each entry:
  - `clip = out/entry["file"]` and `clip_len = entry["end"] - entry["start"]`;
  - `peak = script.audio_peak(media.extract_audio(clip), clip_len)`, then `used = peak if peak is not None else script.default_peak(clip_len)`;
  - `lines = script.write_script(facts_from_entry(entry), clip_len, "template", peak=used)`;
  - write `out/<stem>.script.json` (for example `clip_01.script.json`) with `json.dumps(record, ensure_ascii=False, indent=2) + "\n"` in UTF-8;
  - set `entry["script_file"] = "clip_01.script.json"`. It is the last key, so it comes after `vertical_file` when present.
- The manifest is rewritten once if vertical or voiceover.
- `record = {"clip": entry["file"], "clip_len": clip_len, "peak": used, "backend": "template", "lines": [{"start": s, "end": s + script.speech_seconds(t), "text": t} ...]}`.
- MediaError from extract_audio propagates (as on the vertical path).
- pipeline still imports no subprocess.

### 5. `sportscut/cli.py` (change)
- `cut --voiceover` (store_true). Help: `also write OUT/clip_NN.script.json: a timed Vietnamese commentary script per clip (voice-over audio comes later)`.
- `cut` always passes `voiceover=args.voiceover` to `run`. Existing fakes take `**kwargs`.
- After each clip line (and after the vertical line), print `Path(args.out) / entry["script_file"]` when that key is present.
- `eval-meta --script` (store_true) passes `script=args.script` to `evaluate_meta_dir`. Help: `score timed commentary scripts (10 s and 30 s clips) instead of metadata`.
- It works with `--meta-backend`. Error handling and exit codes are unchanged.

### 6. `README.md` (insert only)
Inside the `## Bình luận AI: ... (eval-meta)` section, after the `### Backend LLM (tùy chọn)` text and before the next `## `, add `### Kịch bản bình luận có mốc thời gian (eval-meta --script, cut --voiceover)`. It explains:
- 1-3 lines around the audio peak;
- 3.5 âm tiết/giây;
- `script_fits`;
- the command `python -m sportscut eval-meta tests/fixtures/eval_meta --json --script`, with a JSON block holding the measured headline (every key except per_case);
- `sportscut cut VIDEO --out OUT --voiceover` writing `clip_NN.script.json`, and that audio comes in a later task.

The first ```json block of the section stays the T-023 baseline, as T-023 AC15 requires.

### 7. Spec notes (append-only)
Append one `Updated by T-026: ...` paragraph to each of these:
- the T-023 design (eval-meta `--script` report; `_unknown_names` and `_is_vi_text` helpers);
- the T-046 design (llm.py gains `script_roles_llm` and `SCRIPT_PROMPT`; generate_metas_llm is unchanged);
- the T-004 design (`run(..., voiceover=False)`; `script_file` manifest key only with voiceover).

Do not edit INDEX.md or DECISIONS.md; the orchestrator appends them.

## Files
Create:
- `sportscut/commentary/script.py`
- `tests/test_commentary_script.py` (Developer)
- `tests/test_t026_acceptance.py` (Tester)

Change:
- `sportscut/commentary/eval_meta.py`
- `sportscut/commentary/llm.py`
- `sportscut/pipeline.py`
- `sportscut/cli.py`
- `README.md`
- the three spec files in §7

Forbidden (existing scope tests freeze them):
- `sportscut/export.py`, `sportscut/models.py`, `sportscut/ranking.py`, `sportscut/evaluate.py`, `sportscut/eval_player.py`, `sportscut/events/audio_cues.py`, `sportscut/commentary/facts.py`, `sportscut/commentary/meta.py`, `sportscut/api.py`;
- `tests/conftest.py`, `tests/fixtures/**`;
- `agent-office/`, `.agent-office/`.

Size target: under 700 changed lines including tests and docs. Production code is about 300 lines.

## Steps (test first; run `python -m pytest -q tests/test_commentary_script.py` after each)
1. Tests for `syllables` and `speech_seconds` (examples above, NFD input equals NFC), then code.
2. Tests for `audio_peak`, then code. Synthetic numpy samples: the loud second at index 3 → 3.5; shorter than 1 s → None; audio longer than clip_len ignores seconds past floor(clip_len); ties → the first.
3. Tests for `fit_problems` and `script_fits`, then code: hand-made line lists that fit, overrun, start before PAD, overlap, are unsorted, have 0 lines, or have 4 lines.
4. Refactor eval_meta (`_unknown_names`, `_is_vi_text`). Run `python -m pytest -q tests/test_eval_meta.py tests/test_t023_acceptance.py tests/test_commentary_llm.py tests/test_t025_acceptance.py`; all pass unchanged.
5. Tests for `validate_script`, then code: an invented number, an invented capitalised name, English text, an empty line, a 201-character line.
6. Tests for the template `write_script`, then code:
   - every fixture case at 10.0 and 30.0 with default peak, at peak 0.0 and at peak clip_len-0.01 → 1-3 lines, `validate_script == []`, the moment line containing the event key word;
   - full facts at 30 s → the joined text contains every fact;
   - input ValueErrors;
   - clip_len 1.0 → [].
7. Tests for the LLM path, then code. Use `fake_client` as in test_commentary_llm.py:
   - good JSON → returns the LLM texts at the placed times;
   - an overlong before line, an invented number, bad JSON and a request exception → template result plus a warning containing `template fallback`;
   - no key and client None → no network call (monkeypatch an `anthropic` module that fails the test if used) and template.
8. Tests for the `eval-meta --script` report: key order, 16 per_case items, a monkeypatched write_script giving an overlapping script → script_fits < 1. Then code. The CLI flag follows.
9. Tests for pipeline and CLI, then code:
   - `run(burst_video, out, voiceover=True)` writes `clip_NN.script.json` per clip with the record schema;
   - with script.audio_peak monkeypatched to 2.5, the file's peak is 2.5 and the moment line starts at 2.5;
   - a manifest `script_file` key;
   - without voiceover, no *.script.json and keys unchanged;
   - CLI `--voiceover` forwarded and printed.
10. README and spec notes; run the full suite and the eval commands below.

## Verify (quote the summary lines in the PR)
- `python -m pytest -q` → all pass.
- `python -m sportscut eval-meta tests/fixtures/eval_meta --json` → headline `{"score": 1.0, "format_ok": 1.0, "fact_recall": 1.0, "hallucination_rate": 0.0, "vi_rate": 1.0}`, unchanged.
- `python -m sportscut eval-meta tests/fixtures/eval_meta --json --script` → `script_fits` 1.0, `hallucination_rate` 0.0, `vi_rate` 1.0, `score` >= 0.9 (the expected template value is 1.0); record the measured value in the README.
- `python -m sportscut eval tests/fixtures/eval --json` → f1 equal to main's.
- Manual check: `python -m sportscut cut <synthetic.mp4> --out /tmp/o --voiceover` prints the clip and script paths.

## Assumptions
- The syllable estimate (letter runs + digits) is a heuristic. Foreign names are under-counted (e.g. 'Manchester' = 1). The 0.25 s pads and the validation keep speech inside the clip by estimate, not by measured TTS. Task 5 can re-check against real audio length.
- `facts.score` is shown after the moment line as `Tỉ số X-Y.`. The pipeline has no match info (T-024 was dropped), so `cut --voiceover` scripts carry only the event line, plus a context line when facts allow.
- `cut --voiceover` always uses the template backend. The LLM script backend is reachable through `write_script(..., "llm")` and `eval-meta --script --meta-backend llm`.

## Test plan

- Developer unit tests, tests/test_commentary_script.py: syllables and speech_seconds examples, including NFD vs NFC and digits counted one each (AC2).
- Developer unit test: audio_peak on numpy arrays at SAMPLE_RATE 16000 (loud second 3 → 3.5, under 1 s → None, seconds past floor(clip_len) ignored, ties → first) (AC5).
- Developer unit test: fit_problems and script_fits on hand-made line lists: fits, overrun, start < PAD, overlap, unsorted, 0 lines, 4 lines (AC2).
- Developer unit test: validate_script flags an invented number, an invented capitalised name, English-only text, an empty line, a non-stripped line and a 201-char line (AC1, AC7).
- Developer unit test: template write_script over all fixture cases × {10.0, 30.0} × peaks {None, 0.0, clip_len-0.01} → 1-3 lines, validate_script empty, moment line placement rule, no key word before the moment line (AC1, AC3).
- Developer unit test: goal_full facts at 30 s mention all facts, and at 10 s still mention 'bàn thắng' (AC4). ValueError inputs and clip_len 1.0 → [] (AC6).
- Developer unit tests for the LLM path: use the fake_client pattern from tests/test_commentary_llm.py; good JSON is used, and overlong, invented-number, bad JSON and exception responses fall back to the template with a 'template fallback' WARNING (caplog on sportscut.commentary). With no key, monkeypatch sys.modules['anthropic'] to fail if constructed. Assert the request keys {model, max_tokens, system, messages} and that the user content JSON has label, clip_len, peak, before_max_syllables and at_after_max_syllables (AC7).
- Developer unit test: evaluate_meta_dir(FIXTURE, script=True) key order, 16 items, aggregates. With script.write_script monkeypatched to return overlapping lines, that item scores 0.0 and script_fits < 1. evaluate_meta_dir(FIXTURE) without script equals main's report (AC8, AC9).
- Developer integration tests (burst_video fixture from conftest, needs ffmpeg): run(..., voiceover=True) writes clip_NN.script.json with the record schema and the script_file manifest key. With script.audio_peak monkeypatched to 2.5, record peak == 2.5 and the moment line starts at 2.5. Default run writes no script files and keeps the manifest keys (AC10).
- Developer CLI tests: monkeypatch sportscut.cli.run (fake taking **kwargs) to check voiceover forwarding and printed paths. eval-meta --script --json parses and has the AC9 keys. --help texts (AC11).
- Tester acceptance tests, tests/test_t026_acceptance.py, written from the ACs, not the Developer's tests:
- its own hand-made ClipFacts (not the fixture), for example a save with only a competition and a red card with long team names, at 10 s and 30 s;
- an independent re-check of the timing contract using its own syllable count rule from AC2;
- the moment placement;
- the LLM fallback via fake clients;
- the eval-meta default output equal to `git show $(git merge-base main HEAD):README.md` baseline, and the --script thresholds via subprocess `python -m sportscut eval-meta ... --script --json`;
- a pipeline voiceover end-to-end on a synthetic ffmpeg video built in tmp_path;
- the AC12 scope check against `git merge-base main HEAD`, gated to branches starting with `office/T-026` (T-013/T-021 rule).
- Tester confirms the tests can fail. For example, temporarily set SYLLABLES_PER_SEC to 10 or drop the overlap check, see the AC2/AC9 tests fail, and restore. Then run `python -m pytest -q`, both eval-meta commands and `python -m sportscut eval tests/fixtures/eval --json`, and quote their summary lines.

## Deviations

- `pipeline.run`: the spec says `voiceover` goes "after `score_box`" as the new last parameter; T-022 has since added `transcriber` after `score_box`, so `voiceover` is placed last, after `transcriber` (still keyword-compatible, still the last parameter).
- `script.py` does not import `meta.EVENT_LABELS`: the moment lines are fixed constants (`MOMENT_LINES`) and nothing else needed the labels, so the import would be unused.
