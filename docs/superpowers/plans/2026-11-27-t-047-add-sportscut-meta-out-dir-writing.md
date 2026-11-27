# Plan T-047: Add `sportscut meta OUT_DIR` writing title, caption and hashtags into highlights.json, captions.txt and reel.json

Design: `docs/superpowers/specs/2026-11-27-t-047-add-sportscut-meta-out-dir-writing-design.md`.

## Implementation plan

# T-047: `sportscut meta OUT_DIR` writes title, caption and hashtags into highlights.json, captions.txt and reel.json

Request R-005 (Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt). This brings back the first slice of the dropped T-024, which hit the diff-size guardrail. Read these first: T-023 (`docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md`, including its 'Updated by T-025/T-028/T-026/T-050' notes), T-025/T-046 (LLM backend, `generate_metas_llm`, `validate_meta`), T-028 (`format_problems`, REEL_DEFAULT) and T-050 (hashed variants, `clip=` argument).

## Context (as it is on main b517c32)
- `sportscut/commentary/facts.py`: `ClipFacts(event, minute, home, away, competition, score)` and `facts_from_entry(entry, match=None)`. `match` keys are a subset of `MATCH_KEYS = {home, away, competition, score, kickoff}`. Unknown keys raise `ValueError('unknown match key: ...')`. The minute is computed only when `kickoff` is given. Names are NFC-normalised and stripped, and blank names become None.
- `sportscut/commentary/meta.py`: `generate_meta(facts, backend='template', clip=None) -> ClipMeta`, `ClipMeta.to_dict()` (keys title, caption, hashtags; hashtags is a list), `EVENT_LABELS`, `EVENT_TAGS`, `hashtag(text)`.
- `sportscut/commentary/llm.py`: `generate_metas_llm(facts_list, client=None) -> list[ClipMeta]` sends one request. Each clip that fails `validate_meta` falls back to `meta.generate_meta(facts)` (no clip index) and logs a warning ending in 'template fallback'.
- `sportscut/commentary/eval_meta.py`: `format_problems(meta)`, `validate_meta(facts, meta)`, `_unknown_names(facts, texts)`, `_is_vi_text(facts, text)`.
- `sportscut cut` writes `OUT/highlights.json`: a JSON list of entries `{start, end, score, reason, event, event_confidence, file, ...optional vertical_file/script_file/voiceover_file...}`, written as `json.dumps(entries, indent=2) + '\n'`.
- `sportscut/models.py`: `EVENT_TYPES = ('goal','save','red_card','controversy','other')`.

Do NOT touch: sportscut/commentary/facts.py, meta.py, llm.py, eval_meta.py, sportscut/pipeline.py, sportscut/api.py, sportscut/export.py, sportscut/models.py, pyproject.toml, tests/conftest.py, tests/fixtures/, any other existing test file, agent-office/, or docs/superpowers/DECISIONS.md (the orchestrator appends to it).

## Design

### New module `sportscut/commentary/publish.py`

```python
CAPTIONS_NAME = "captions.txt"
REEL_NAME = "reel.json"
META_KEYS = ("title", "caption", "hashtags")

def reel_meta(facts_list: list[ClipFacts]) -> ClipMeta: ...
def write_meta(out_dir, match=None, backend="template", client=None) -> list[dict]: ...
```

`write_meta(out_dir, match=None, backend='template', client=None)` works as follows:
1. If `backend` is not 'template' or 'llm', raise `ValueError(f'unknown backend: {backend}')` before reading anything.
2. Read `Path(out_dir) / export.MANIFEST_NAME` ('highlights.json') as UTF-8 JSON. Each of the following raises ValueError, and the message always contains 'highlights.json':
   - the file is missing (`f'missing {path}'`);
   - it can't be read, or the JSON is invalid;
   - the top level is not a list;
   - the list is empty ('no clips');
   - an entry is not an object;
   - an entry's `file` is not a non-empty string;
   - `facts_from_entry` raises ValueError, KeyError or TypeError for an entry (bad start/end, missing start/end). The message becomes `f'{path}: [{i}]: {exc}'`.
3. For entry i, the event is `entry.get('event')` when it is in EVENT_TYPES, and 'other' otherwise (the T-028 rule). facts_i = `facts_from_entry({**entry, 'event': event}, match)`. Match errors from facts_from_entry ('unknown match key', bad kickoff, a non-string name, a score that is not H-A) are raised as ValueError and are not rewritten.
4. Metadata:
   - 'template': `metas = [generate_meta(f, clip=i) for i, f in enumerate(facts)]`. The 0-based clip index feeds the T-050 hash, so clips of the same event usually differ.
   - 'llm': `metas = llm.generate_metas_llm(facts, client=client)`. This is one request; the per-clip fallback is llm.py's own, unchanged.
5. New entries: `{**{k: v for k, v in entry.items() if k not in META_KEYS}, **metas[i].to_dict()}`. Every other key keeps its order and value, and title, caption and hashtags are the last three keys. Running the command twice gives the same keys, with the old metadata replaced.
6. reel = `reel_meta(facts)` (always template, whatever the backend).
7. Only after all of the above succeeds, write the three files (on any earlier error, no file is created or changed):
   - `highlights.json`: `json.dumps(new_entries, ensure_ascii=False, indent=2) + '\n'`, UTF-8.
   - `captions.txt`: one block per clip in manifest order. A block is `file`, title, caption, and `' '.join(hashtags)`, one per line. The file is `'\n\n'.join(blocks) + '\n'`, UTF-8: blocks are separated by exactly one blank line and the file ends with one newline.
   - `reel.json`: `json.dumps(reel.to_dict(), ensure_ascii=False, indent=2) + '\n'`, UTF-8, with keys exactly title, caption, hashtags.
8. Return new_entries.

`reel_meta(facts_list)` takes the match fields home, away, competition and score from `facts_list[0]` (they are identical for every clip). n = len(facts_list), and counts = the number of clips per event in EVENT_TYPES order, keeping only counts > 0.
- teams = 'H vs A' if both are set, else H or A, else None.
- title: the first of `[f'Tổng hợp highlight: {teams}' (only if teams), 'Tổng hợp highlight trận đấu']` with 10 to 80 characters.
- match_text: ' trong trận {H} gặp {A}' / ' trong trận đấu của {H or A}' / ' trong trận đấu' (same as T-023).
- caption = `f'Tổng hợp {n} khoảnh khắc đáng chú ý' + match_text + (f' tại {C}' if C) + ': ' + ', '.join(f'{count} {EVENT_LABELS[e].lower()}') + '.' + (f' Tỉ số: {S}.' if S) + ' Cùng xem lại nhé!'`. If the result is longer than 300 characters, build it again without the `': ' + counts` part (the '.' stays).
- hashtags: `['#BongDa', '#Highlight', '#TongHop']`, then `hashtag()` of home, away and competition (skip None), then `'#' + EVENT_TAGS[e]` for each counted event in EVENT_TYPES order. Deduplicate case-insensitively and keep the first 8.

Exact examples (these become ACs):
- Facts with H 'Hà Nội FC', A 'Hải Phòng', C 'V.League 2026', S '2-1', and events goal, save, goal:
  - title 'Tổng hợp highlight: Hà Nội FC vs Hải Phòng'
  - caption 'Tổng hợp 3 khoảnh khắc đáng chú ý trong trận Hà Nội FC gặp Hải Phòng tại V.League 2026: 2 bàn thắng, 1 pha cứu thua. Tỉ số: 2-1. Cùng xem lại nhé!'
  - hashtags ('#BongDa', '#Highlight', '#TongHop', '#HaNoiFC', '#HaiPhong', '#VLeague2026', '#BanThang', '#CuuThua')
- No match info, events goal and other:
  - title 'Tổng hợp highlight trận đấu' (the T-028 REEL_DEFAULT title)
  - caption 'Tổng hợp 2 khoảnh khắc đáng chú ý trong trận đấu: 1 bàn thắng, 1 khoảnh khắc đáng chú ý. Cùng xem lại nhé!'
  - hashtags ('#BongDa', '#Highlight', '#TongHop', '#BanThang', '#KhoanhKhac')

You can import `MANIFEST_NAME` from `sportscut.export`. Importing `llm` at module top level is fine, because llm.py does not import publish. Size: about 90 lines.

### CLI (`sportscut/cli.py`, insert-only)

```
sportscut meta OUT_DIR [--home H] [--away A] [--competition C] [--kickoff SECONDS]
                      [--match-info match.json] [--meta-backend template|llm]
```

- The positional argument has `metavar='OUT_DIR'`. `--kickoff` is `type=float`, so a non-number is an argparse error with exit 2. `--meta-backend` has `choices=('template','llm')` and default 'template', with the same help text as eval-meta. The help says that the minute needs --kickoff and that llm needs ANTHROPIC_API_KEY and the [llm] extra.
- match = {} by default. If `--match-info` is given, read it as UTF-8 JSON; it must be an object. A missing file, invalid JSON or a non-object raises ValueError, and the message contains the file path. Then each flag that is not None overrides its key: `home`, `away`, `competition`, `kickoff`. match.json may also carry `score`. Pass `match or None` to `write_meta`.
- On success, print `OUT_DIR/highlights.json`, `OUT_DIR/captions.txt` and `OUT_DIR/reel.json`, one path per line on stdout (built with `Path(out_dir) / name`), and exit 0.
- On ValueError or OSError: print `sportscut meta: error: <msg>` to stderr, print nothing to stdout, and exit 1. No file is written or changed.
- No other subcommand, flag or output changes. Do not delete or reword any existing cli.py line; only add lines (an import, the parser block and the handler block placed before `if args.command == "cut":`).

### README.md (insert-only)

Insert a new section `## Xuất tiêu đề, caption, hashtag cho clip đã cắt (sportscut meta)` directly before the line `## Theo dõi cầu thủ: đo độ chính xác (eval-player)`. It contains:
- a ```bash block with `sportscut meta out --home 'Hà Nội FC' --away 'Hải Phòng' --competition 'V.League 2026' --kickoff 0` and `sportscut meta out --match-info match.json --meta-backend llm`;
- one line describing match.json keys (home, away, competition, score, kickoff, in seconds into the video), with flags winning over the file;
- a statement that the minute ('phút') is written only when kickoff is given, and that without team info the text names no team;
- what is written: `title`/`caption`/`hashtags` in `highlights.json`, `captions.txt` (one block per clip: file name, title, caption, hashtags) and `reel.json` (the whole set);
- a statement that the llm backend sends one request per match and falls back to the template for each clip with `template fallback` on stderr.

It must not contain '```json' or the phrase 'sẽ có ở task sau', because T-027 AC16 scans the text from '### Lồng tiếng bình luận' to the eval-player heading. No existing README line is deleted or changed, and the eval-crop section stays last and unchanged.

### Docs
- Add this spec and plan under docs/superpowers (the orchestrator writes them).
- Append one T-047 row to docs/superpowers/INDEX.md.
- Append a '## Updated by T-047' note at the end of the T-023 design spec. The note says: `sportscut meta` now writes title, caption and hashtags into highlights.json, plus captions.txt and reel.json, using `generate_meta(facts, clip=i)` or `generate_metas_llm`. The T-023 out-of-scope items 'writing title/caption/hashtags into highlights.json' and 'match-info file format or CLI flags' are now done for the CLI. `cut --meta` and the API stay out of scope.

## Ordered steps (TDD)
1. Write tests/test_commentary_publish.py with a `_manifest(tmp_path, entries)` helper that writes highlights.json. Write template-path tests (key order, format_problems, validate_meta, generic text) and run `python -m pytest -q tests/test_commentary_publish.py`. It must fail with ImportError on `sportscut.commentary.publish`.
2. Write publish.py up to `write_meta` for the template backend. Run the tests until they pass.
3. Add tests for reel_meta (both exact examples and the overflow case), watch them fail, then implement.
4. Add tests for captions.txt and reel.json, error cases (missing file, invalid JSON, empty list, bad entry, unknown backend, with no files changed) and the llm backend with `fake_client`. Watch them fail, then implement.
5. Add CLI tests (`cli.main([...])` with capsys) for success output, flag override over match.json, exit 1 with the stderr prefix, and `--help` listing OUT_DIR, --kickoff, --match-info and --meta-backend. Watch them fail, then add the cli.py blocks.
6. Add the README section and the docs notes.
7. Run the verify commands below.

## Verify (quote the summary lines)
- `python -m pytest -q`: 0 failed.
- `PATH=/nonexistent python -m pytest -q tests/test_commentary_publish.py tests/test_t047_acceptance.py` passes (no ffmpeg, no network, anthropic not installed).
- `python -m sportscut eval-meta tests/fixtures/eval_meta --json` prints score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0.
- `python -m sportscut eval tests/fixtures/eval --json`: f1 equals the value on main (0.8421).
- `git diff --shortstat $(git merge-base main HEAD) -- . ':(exclude)docs/superpowers'` plus the untracked new files: < 400 changed lines.
- Manual: copy a synthetic highlights.json into /tmp/out, then run `python -m sportscut meta /tmp/out --home 'Hà Nội FC' --away 'Hải Phòng' --kickoff 0` and `cat /tmp/out/captions.txt /tmp/out/reel.json`.

## Assumptions
- An entry whose event is missing or not in EVENT_TYPES is treated as 'other' (T-028 rule).
- An empty highlights.json list is an error (exit 1). With nothing to publish, we write nothing.
- The reel text is always template. The LLM backend writes only per-clip text, which keeps one request per match and adds no reel prompt.
- An LLM fallback clip gets `generate_meta(facts)` with no clip index, because llm.py is frozen. Template-only runs use `clip=i`.
- Every error exits 1, whether it comes from highlights.json, match.json or bad match values. Argparse usage errors stay exit 2.
- captions.txt lists clips only, not the reel.
- Files are written in place, not atomically. They are written only after every input has been validated and all text generated.

## Test plan

- Developer, tests/test_commentary_publish.py (new, ≤ 130 lines, no ffmpeg). The helper `_manifest(tmp_path, entries)` writes highlights.json with `json.dumps(entries, indent=2)`, and the AC2 three-entry fixture is built inline.
- test_template_fields_last_and_valid: AC2 + AC3. Check key order, values preserved, format_problems == [], validate_meta == [], equality with generate_meta(facts, clip=i), and 'phút 23' on clip_01.
- test_generic_without_match: AC4. No 'phút', _unknown_names == [], clip hashtags are the 3 base tags, and the reel title is generic.
- test_rerun_is_idempotent: AC5.
- test_captions_txt_blocks: AC6. Exact string built from the rewritten manifest, and 3 blocks of 4 lines.
- test_reel_meta_examples_and_overflow: AC7. Both exact examples plus the 40-character/50-clip overflow case.
- test_reel_json_valid_and_no_invented_numbers: AC8. Keys, format_problems, integers drawn from counts or match values, _unknown_names, _is_vi_text, UTF-8 literal characters.
- test_llm_backend_fake_client: AC9 good path. The fake client returns `{"clips": [...]}` with valid text for ids 0..2. Assert one call, LLM text in highlights.json and captions.txt, template reel.
- test_llm_hallucination_falls_back_per_clip: AC9. Clip 1 says 'Liverpool', so clip 1 equals generate_meta(facts_1) and the others keep the LLM text. Also a fake client raising RuntimeError: all clips are template and all files are written.
- test_errors_change_nothing: AC10, parametrised over the missing, invalid JSON, dict, [], ['x'], missing file key and end <= start cases. Assert ValueError mentioning 'highlights.json', no captions.txt or reel.json, manifest bytes unchanged. Plus the unknown backend and 'venue' match key cases.
- test_cli_meta_success_and_errors: AC11 + AC13, via cli.main and capsys (exit codes, stdout lines, stderr prefix, --help options).
- Tester, tests/test_t047_acceptance.py (new, ≤ 120 lines, written from the ACs, not from the Developer tests). Independently cover: AC2 key order including an extra key on a non-first entry; AC6 exact captions.txt for a 2-clip manifest; AC7 exact reel strings; AC9 hallucinated 'phút 99' fallback; AC12 match.json plus flag override and no minute without kickoff; AC13 CLI exit codes and that no files are created; AC15 README section position and content.
- Tester: show the tests can fail. Temporarily make reel_meta drop '#TongHop' and confirm AC7 fails, then revert. Temporarily ignore `--home` overrides and confirm AC12 fails, then revert. Report both '1 failed' summary lines.
- Tester: run `python -m pytest -q` (0 failed); `PATH=/nonexistent python -m pytest -q tests/test_commentary_publish.py tests/test_t047_acceptance.py`; `python -m sportscut eval-meta tests/fixtures/eval_meta --json` (score 1.0, etc.); `python -m sportscut eval tests/fixtures/eval --json` (f1 equal to main, 0.8421); `git diff --numstat $(git merge-base main HEAD)` plus untracked line counts outside docs/superpowers < 400; `git diff -U0 $(git merge-base main HEAD) -- README.md sportscut/cli.py` has no '-' content lines. Quote the summary lines.

## Deviations

- tests/test_commentary_publish.py is 140 lines, not ≤ 130. Code came in under its estimate (publish.py 85, cli.py 30, README 20), so the change outside docs/superpowers is 275 lines and stays < 400 with the Tester's ≤ 120-line file.
- `python -m pytest -q` is not 0 failed. Four checks in tests/test_t050_acceptance.py fail (AC4, AC10, AC11, AC12). They diff against `main`, which already contains T-050, and three of them fail on a clean main checkout too. This task may not edit that file, so the decision belongs to the Tech Lead (see .office/DEV_NOTES.md).
- Resolved by Tech Lead decision (T-047 round 1): tests/test_t050_acceptance.py gets an `_own_branch()` gate (12 changed lines, no assert removed or loosened) so its git-diff scope checks only run on office/T-050. AC16 now also allows that file; the < 400 budget over the other non-docs files stays at 396. `python -m pytest -q` is now 0 failed.
