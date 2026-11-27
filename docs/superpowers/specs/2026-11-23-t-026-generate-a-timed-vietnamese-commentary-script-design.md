# T-026: Generate a timed Vietnamese commentary script per clip

Request R-005. Plan: `docs/superpowers/plans/2026-11-23-t-026-generate-a-timed-vietnamese-commentary-script.md`.

## Product Owner request

Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt.

## Goal

Add `commentary/script.py` with `write_script(facts, clip_len, backend) -> list[(t_start, text)]`. It writes 1-3 short Vietnamese commentary lines placed around the event moment, which is the audio peak inside the clip. The length budget is about 3.5 syllables per second of available time, so speech never overruns the clip. Template and LLM backends both go through the same validation. Extend eval-meta with `script_fits` (estimated speech duration is at most the available window and lines don't overlap) and the existing fact checks. Write `clip_NN.script.json` when `--voiceover` is requested; audio arrives in task 5. Tests: hand-made facts give scripts that fit 10 s and 30 s clips. The eval score must not drop.

## Acceptance criteria

- AC1 `sportscut.commentary.script.write_script(facts, clip_len, backend='template', *, peak=None, client=None)` returns a list of 1-3 `(start: float, text: str)` tuples in time order. For each of the 8 cases in tests/fixtures/eval_meta/cases.json and clip_len 10.0 and 30.0, with peak None, peak 0.0 and peak clip_len-0.01, the result is non-empty and `validate_script(facts, lines, clip_len) == []`.
- AC2 Timing contract: with end = start + syllables(text)/3.5, every line has start >= 0.25 and end <= clip_len - 0.25, and each line starts at or after the previous line's end (tolerance 1e-6). `script_fits` returns False for scripts that overlap, overrun, start before 0.25 s, are unsorted, are empty or have more than 3 lines, and True for a hand-made fitting script. `syllables` counts letter runs plus digits, and NFD and NFC input give the same count.
- AC3 The moment line is placed at the event moment. It is the line containing the event's key word (bàn thắng / cứu thua / thẻ đỏ / tranh cãi / khoảnh khắc). It starts exactly at `peak` when peak + its duration <= clip_len - 0.25. Otherwise it starts at clip_len - 0.25 - duration. A line before it never contains that key word. With peak=None the peak is clip_len*8/12.
- AC4 With facts ClipFacts('goal', 23, 'Hà Nội FC', 'Hải Phòng', 'V.League 2026', '1-0') and clip_len 30.0, the joined script text contains (NFC casefold) 'bàn thắng', 'Hà Nội FC', 'Hải Phòng', 'phút 23', 'V.League 2026' and '1-0'. With clip_len 10.0 it still contains 'bàn thắng' and fits. No template script contains a number that is not in the facts.
- AC5 `script.audio_peak(samples, clip_len)` returns the centre (i + 0.5) of the loudest whole second within min(len(samples)//16000, floor(clip_len)) seconds, the first on ties, and None when that count is 0.
- AC6 `write_script` raises ValueError for clip_len <= 0, NaN/inf or bool, for peak < 0, peak >= clip_len or non-finite, and for an unknown backend. It returns [] for clip_len 1.0 (nothing fits).
- AC7 The LLM backend goes through the same `validate_script`. A fake client returning valid `{before, at, after}` JSON gives lines with exactly those texts at the placed times. A response that overruns the clip, contains a number not in the facts, is not valid JSON, or raises gives exactly the template result and logs a WARNING containing 'template fallback'. With no ANTHROPIC_API_KEY and client=None, no client is created and the template result is returned. No log record contains the API key value.
- AC8 `python -m sportscut eval-meta tests/fixtures/eval_meta --json` output is unchanged from main: the headline is {score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0}, with the same key order and per_case as main.
- AC9 `python -m sportscut eval-meta tests/fixtures/eval_meta --json --script` exits 0 and prints keys in the order score, script_fits, fact_recall, hallucination_rate, vi_rate, per_case. per_case has 16 items (each case at 10.0 then 30.0) with keys id, clip_len, score, script_fits, fact_recall, hallucinated, vi, problems, lines. For the template it gives script_fits == 1.0, hallucination_rate == 0.0, vi_rate == 1.0 and score >= 0.9. An item whose script does not fit scores 0.0. `--script --meta-backend llm` with no key exits 0 with the template numbers.
- AC10 `pipeline.run(video, out, voiceover=True)` writes `out/clip_NN.script.json` for every exported clip. Each is UTF-8 JSON `{clip, clip_len, peak, backend: 'template', lines: [{start, end, text}]}` whose lines pass script_fits(clip_len). `peak` equals script.audio_peak(media.extract_audio(clip), clip_len), or default_peak when that is None. The manifest entry gains `script_file` as its last key. With voiceover=False (the default), no *.script.json is written and the manifest keys are unchanged.
- AC11 `sportscut cut VIDEO --out OUT --voiceover` passes voiceover=True to run and prints each script path after its clip (and vertical) path. Without the flag it passes voiceover=False and the output is unchanged. `--help` for cut lists --voiceover, and `--help` for eval-meta lists --script.
- AC12 No regression: `python -m pytest -q` passes with no existing test deleted, skipped or weakened, and `python -m sportscut eval tests/fixtures/eval --json` f1 equals main's. export.py, models.py, ranking.py, facts.py, meta.py, api.py, tests/conftest.py, tests/fixtures/ and agent-office/ are unchanged against `git merge-base main HEAD`.
- AC13 The README eval-meta section keeps the T-023 baseline as its first json block and gains the 'Kịch bản bình luận' subsection with the `--script` command and its measured headline, which equals the command output. The T-023, T-046 and T-004 design specs each gain an appended 'Updated by T-026' paragraph.

## Out of scope

- Text-to-speech, audio mixing, voiceover_url in the API or web preview (task 5 / T-027).
- Choosing the LLM backend from `cut` (no `cut --meta-backend`), and batching several clips into one LLM request for scripts.
- Writing title/caption/hashtag metadata files from `cut` (T-024 was dropped), and match info (teams, kickoff, score) input to `cut`.
- API/web changes, including a voiceover option on POST /highlights.
- Real syllable counting for foreign names, or measuring TTS speaking rate.
- Changing tests/fixtures/eval_meta/cases.json or adding script-specific eval fixtures.
- Second-half minute handling, and player names in commentary.

## Decisions

- T-026: `sportscut/commentary/script.py` owns scripts: `write_script(facts, clip_len, backend='template', *, peak=None, client=None) -> list[tuple[float, str]]`. `peak` (clip seconds) is the event moment, and None means the detector anchor clip_len*PRE_SEC/(PRE_SEC+POST_SEC). In the pipeline the peak is the audio peak inside the clip: `audio_peak` gives the centre of the loudest whole second of the clip audio.
- T-026: The length budget is 3.5 syllables/second. syllables = letter runs + digits (NFC). The available window is [0.25, clip_len - 0.25]. A script fits when it has 1-3 lines, each line's estimated end is inside the window, and each line starts at or after the previous line's estimated end (EPS 1e-6). Placement is deterministic and shared by all backends: the moment line starts at the peak (pulled earlier only to avoid overrunning), the before line ends 0.25 s before it, and the after line starts 0.25 s after it.
- T-026: Roles are before (context, never names the event), at (the event moment, contains the label key word), after (`Tỉ số X-Y.`). The template tries candidates from the most facts to the fewest: before variants are full / without competition / minute only / none, each with and without the score line. It returns the first that passes validate_script, and returns [] only when even the moment line alone does not fit.
- T-026: validate_script(facts, lines, clip_len) is the single validation for the template and LLM scripts: fit problems, text format (1-200 chars, stripped), numbers not in facts, capitalised names not in facts (same rule as validate_meta), and the Vietnamese heuristic. A rejected or missing LLM script falls back to the template with a WARNING containing 'template fallback', and never logs the key, the request or str(exc).
- T-026: eval_meta gains `_unknown_names` and `_is_vi_text`, extracted from validate_meta/_is_vi with identical behaviour. script.py imports eval_meta at top level, and eval_meta imports script lazily inside evaluate_meta_dir (circular import, same pattern as llm).
- T-026: The default `eval-meta` report is unchanged (T-023 key order and baseline). Script scoring is opt-in via `eval-meta --script` / `evaluate_meta_dir(..., script=True)`. It scores every case at SCRIPT_CLIP_LENS = (10.0, 30.0) with the default peak, using report keys score, script_fits, fact_recall, hallucination_rate, vi_rate, per_case. The item score is fact_recall if script_fits and not hallucinated and vi, else 0. A later script change must not lower the --script score (template baseline recorded in the README, expected 1.0, floor 0.9).
- T-026: llm.py gains SCRIPT_PROMPT and script_roles_llm(facts, limits, client=None) -> {before, at, after} | None, one request per clip. generate_metas_llm, build_request, parse_response and SYSTEM_PROMPT stay byte-identical.
- T-026: `pipeline.run(..., voiceover=False)` is the new last parameter, and `cut --voiceover` always passes it. With voiceover it writes OUT/<clip stem>.script.json = {clip, clip_len, peak, backend:'template', lines:[{start, end, text}]} (UTF-8, ensure_ascii=False, indent 2) and appends `script_file` as the last manifest key. Without voiceover, files and manifest are unchanged. The cut path uses the template backend only. Audio (voiceover_url) is task 5.
- T-026: The facts for pipeline scripts come from facts_from_entry(entry) with no match info, so pipeline scripts contain only facts present in the entry (the event). The minute and names appear only when match info exists (eval or future tasks).

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md`
- `docs/superpowers/specs/2026-11-26-t-046-re-land-the-reviewed-t-025-design.md`
- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`

## Updated by T-027

Updated by T-027: the script lines now drive audio. With `cut --voiceover` and the `[tts]` extra installed, each clip's `(start, text)` lines from `write_script` are synthesized by Piper (`sportscut.commentary.voiceover`), placed at their scripted times (a line that runs long delays the next one, audio past the clip end is dropped) and mixed over the clip with the original audio lowered by 12 dB during speech. The result is `OUT/clip_NN.vo.mp4` (and `OUT/vertical/clip_NN.vo.mp4` with `--vertical`); manifest keys `voiceover_file` / `vertical_voiceover_file` follow `script_file`. `_write_script` now also returns the lines; the script.json file is unchanged. Without the extra, `--voiceover` prints a one-line stderr notice, still writes the scripts and exits 0, exactly as in T-026.

### Updated by T-048

Updated by T-048: scripts written by the pipeline now use `facts_from_entry(entry, match)`, where `match` is the new `pipeline.run(match=None)` keyword fed by the `cut` match options (`--home`, `--away`, `--competition`, `--kickoff`, `--match-info`). A script names the teams, the competition, the score or the minute only when they are given (the minute needs a kickoff at or before the clip). Without match info the scripts are byte-identical to before; the script.json record keys and the `template` backend are unchanged.
