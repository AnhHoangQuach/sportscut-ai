# Plan T-048: Add `sportscut cut --meta` with the match-info options, also feeding the match info into voice-over scripts

Design: `docs/superpowers/specs/2026-11-27-t-048-add-sportscut-cut-meta-with-the-design.md`.

## Implementation plan

# T-048: `sportscut cut --meta` with match info, and match info in voice-over scripts. Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `sportscut cut` can write titles, captions and hashtags (`--meta`) in the same run, using the same match-info options as `sportscut meta`. Those options also reach the `--voiceover` commentary scripts, so a script names the teams or the minute only when the user gives them.

**Architecture:** cli.py gets two shared helpers. `_add_match_options(parser)` is used by both `meta` and `cut`. `_match_from_args(args) -> dict | None` is the T-047 inline parsing block, moved into a function. `cut` passes `match` to `pipeline.run(..., match=match)` and, with `--meta`, calls the existing `publish.write_meta(out, match, backend=...)` after `run` returns. `pipeline.run` gets one new last keyword `match=None`. It validates the value up front and passes it to `facts_from_entry(entry, match)` in `_write_script`. publish.py, facts.py, script.py and meta.py do not change.

**Tech Stack:** Python 3.11, argparse, pytest, ffmpeg (synthetic fixture videos only).

**Spec:** this file (design). Related specs: T-047 (sportscut meta / publish.write_meta), T-026 (scripts), T-004 (pipeline.run).

## Context (read first)
- `sportscut/cli.py:123-132` defines the `meta` options. `sportscut/cli.py:263-280` holds the inline match parsing (`--match-info` JSON object; flags --home/--away/--competition/--kickoff override its keys; `match or None`). The task text calls this the "parsing helper from task 1". T-047 left it inline, so this task first extracts it, with no change in behaviour.
- `sportscut/commentary/publish.py`: `write_meta(out_dir, match=None, backend='template', client=None)` and the constants `MANIFEST_NAME`, `CAPTIONS_NAME` (captions.txt) and `REEL_NAME` (reel.json). It validates `match` and highlights.json before writing anything. Do not change it.
- `sportscut/pipeline.py:29-41` is the signature of `run`. `pipeline.py:123-139` is `_write_script`, which today calls `facts_from_entry(entry)`.
- `sportscut/commentary/facts.py`: `facts_from_entry(entry, match)` raises ValueError for unknown match keys, a non-mapping match, a bad kickoff (negative or not finite) or bad names (over 40 characters). The minute is set only when a kickoff is given.
- `sportscut/commentary/script.py`: `write_script`, `validate_script(facts, lines, clip_len)` (fit + numbers + names + Vietnamese, the same checks eval-meta --script uses) and `script_fits`.
- Every existing test that fakes `cli.run` accepts `**kwargs`, so always passing `match=` is safe.

## Global Constraints
- `sportscut cut` without `--meta` and without any match option behaves as today. highlights.json, clip_NN.mp4, clip_NN.script.json, stdout and stderr stay byte-identical.
- `pipeline.run(...)` without `match` (or with `match=None`) gives byte-identical output to today.
- publish.py, facts.py, script.py, meta.py, llm.py, eval_meta.py, export.py and tests/fixtures/ are not changed.
- README.md is insert-only. The new text goes inside the `## Xuất tiêu đề, caption, hashtag cho clip đã cắt (sportscut meta)` section, before `## Theo dõi cầu thủ: đo độ chính xác (eval-player)`. It contains no `## ` heading, no ```` ```json ```` and not the text `sẽ có ở task sau` (T-047 AC15, T-027 AC16).
- Size: < 400 changed lines outside docs/superpowers (cli.py ≈ 45, pipeline.py ≈ 10, README ≈ 15, tests/test_cut_meta.py ≤ 150, tests/test_t048_acceptance.py ≤ 150). Scope and size are checked by commands in review, not by pytest git-diff tests (T-028 rule).
- No subprocess import in cli.py or pipeline.py (T-027 AC2, test_pipeline).

## Design

### CLI options (`cut`)
- `--meta` (store_true). Help: `also write titles, captions and hashtags: OUT/captions.txt, OUT/reel.json and the title, caption, hashtags keys in OUT/highlights.json`.
- `--meta-backend {template,llm}`, default None (treated as `template`). Help: `metadata generator for --meta (default template); llm needs ANTHROPIC_API_KEY and the [llm] extra`.
- `--home`, `--away`, `--competition`, `--kickoff` (float) and `--match-info` come from the shared `_add_match_options(parser)`, with exactly the help texts `meta` has today (`home team name`, `away team name`, `competition name`, `kickoff time in seconds into the video; the minute needs it`, `match.json with home, away, competition, score, kickoff; flags win`). `meta` calls the same helper, so its help output is unchanged.

### Usage errors (argparse, exit 2, `run` is never called)
- Any of --home/--away/--competition/--kickoff/--match-info without `--meta` and without `--voiceover` gives `cut_parser.error('--home, --away, --competition, --kickoff and --match-info need --meta or --voiceover')`.
- `--meta-backend` without `--meta` gives `cut_parser.error('--meta-backend needs --meta')`.
- A bad `--meta-backend` choice or a non-float `--kickoff` is a normal argparse error.

### `_match_from_args(args) -> dict | None`
This is the T-047 block, moved as is. If `args.match_info` is set, it reads the file as UTF-8 JSON. On OSError or ValueError it raises `ValueError(f"cannot read {args.match_info}: {exc}")`. If the result is not a dict, it raises `ValueError(f"{args.match_info}: expected a JSON object")`. It then applies the non-None flags home, away, competition and kickoff over the file's keys and returns `match or None`. It does not validate values: `run` and `write_meta` do that. `meta` becomes `publish.write_meta(args.out_dir, _match_from_args(args), backend=args.meta_backend)` inside its existing try, with the same messages and exit codes.

### `cut` flow (cli.py)
1. `match = _match_from_args(args)`. On ValueError or OSError: stderr `sportscut: error: <msg>`, empty stdout, return 1. This happens before the transcriber and synthesizer are created and before `run` is called.
2. Transcriber and synthesizer stay as today.
3. `entries = run(..., synthesizer=synthesizer, match=match)`. `match` is always passed (None when no option is given). The existing `except (PipelineError, MediaError)` is unchanged.
4. If `args.meta` and `entries` is non-empty: call `publish.write_meta(args.out, match, backend=args.meta_backend or 'template')` in its own `try/except (ValueError, OSError)`. On error: stderr `sportscut: error: <msg>`, nothing on stdout, return 1. The clips already written stay.
5. If `args.meta` and `entries == []`: do not call write_meta. Print `sportscut: notice: no clips were cut; --meta wrote nothing` to stderr.
6. Print the entry lines exactly as today. With `--meta` and non-empty entries, then print `Path(args.out) / publish.CAPTIONS_NAME` and `Path(args.out) / publish.REEL_NAME`, one per line. highlights.json is not printed, as today.

### pipeline.run
The signature becomes `run(video, out_dir, top=10, min_len=10, max_len=30, events=None, vertical=False, score_box=None, transcriber=None, voiceover=False, synthesizer=None, match=None) -> list[dict]`. Right after the `synthesizer needs voiceover=True` check and before `require_ffmpeg()`:
```python
if match is not None:
    try:
        facts_from_entry({"start": 0, "end": 1, "event": "other"}, match)
    except ValueError as exc:
        raise PipelineError(str(exc)) from exc
```
Invalid match info therefore fails before any file is written. `_write_script(out_dir, entry, match)` uses `facts_from_entry(entry, match)`. The script record keys and backend (`template`) stay the same, and `match` is not stored in the record or the manifest. `match` without `voiceover` is accepted and has no effect on output.

### README (insert-only)
Add a `### Tạo luôn khi cắt (cut --meta)` subsection at the end of the `sportscut meta` section. It shows `sportscut cut match.mp4 --out out --meta --home 'Việt Nam' --away 'Thái Lan' --kickoff 0`. It explains that the match options are the same as in `sportscut meta`, that `--meta-backend llm` exists, that `--voiceover` with match options lets the commentary name the teams and the minute (only when they are given), and that without `--meta` and match options the output is unchanged.

### Docs (docs/superpowers)
Append `## Updated by T-048` to:
- the T-004 spec (`run` has `match=None` as its last keyword),
- the T-026 spec (scripts from the pipeline use `facts_from_entry(entry, match)`),
- the T-047 spec (`sportscut cut --meta` now exists; the out-of-scope line about pipeline.py staying untouched is superseded).
Append one INDEX.md row for T-048. INDEX.md is append-only.

## Assumptions
- The match options of `cut` are independent of `--meta`. Without `--meta` they only change the `--voiceover` scripts, so without `--voiceover` either they would do nothing and are rejected as a usage error. This follows the `--score-box needs --vertical` precedent.
- With `--meta`, `run` also receives `match`. Scripts (when `--voiceover` is set) and titles therefore use the same facts.
- Zero clips with `--meta` is not an error (exit 0 plus a notice), because the cut itself succeeded.
- `cut --meta` gives exactly the same three files as `cut` followed by `sportscut meta OUT` with the same match options. That is how AC3 checks it.

## Review Focus
1. A kickoff later than the clip (`--kickoff 9999`): the minute is None, so neither the scripts nor the titles mention a minute. Test: E-case in test_cut_meta (pipeline with voiceover, kickoff 9999, no 'Phút' in any line).
2. Names with extra spaces (`--home '  Việt Nam '`): stripped by facts. Scripts and captions say 'Việt Nam' and the hashtag is `#VietNam`. Test in test_cut_meta (CLI forwards the raw string; the end-to-end meta result has `#VietNam`).
3. `--match-info` with `score`: the script gets 'Tỉ số 2-1.' when it fits, and the eval checks still pass. Test in test_t048_acceptance (voiceover + match-info containing score '2-1': validate_script == []).
4. Invalid match (negative or NaN kickoff, unknown key, a name over 40 characters) with `cut --meta`: exit 1 before any clip is written. Tests in both files.
5. Running `--meta` again on an OUT that already has captions.txt: the file is overwritten, and old title/caption/hashtags keys are replaced, not duplicated (publish rule). Test in test_t048_acceptance (cut --meta twice into the same OUT gives bytes equal to the first run).

---

### Task 1: extract match helpers in cli.py (no behaviour change)
**Files:** Modify `sportscut/cli.py:123-132` and `sportscut/cli.py:263-280`. Test: `tests/test_cut_meta.py` (new).
**Interfaces:** Produces `_add_match_options(parser) -> None` and `_match_from_args(args) -> dict | None`.
- [ ] Step 1: Write `test_meta_help_unchanged` (the `meta --help` output contains OUT_DIR, --home, --away, --competition, --kickoff, --match-info and --meta-backend, with the same help strings). Also write `test_match_from_args_merges_file_and_flags`: a namespace with match_info=file containing `{"home": "A", "score": "1-0"}` and home='B', kickoff=0.0 gives `{'home': 'B', 'score': '1-0', 'kickoff': 0.0}`; all None gives None; a missing file raises ValueError starting with 'cannot read'; a JSON list raises ValueError ending with 'expected a JSON object'.
- [ ] Step 2: `python -m pytest -q tests/test_cut_meta.py` fails (no helper).
- [ ] Step 3: Implement both helpers and make `meta` use them.
- [ ] Step 4: `python -m pytest -q tests/test_cut_meta.py tests/test_t047_acceptance.py tests/test_commentary_publish.py` passes.

### Task 2: `pipeline.run(match=None)`
**Files:** Modify `sportscut/pipeline.py:29-48,99-101,123-128`. Test: `tests/test_cut_meta.py`.
**Interfaces:** Produces `run(..., synthesizer=None, match=None)` and `_write_script(out_dir: Path, entry: dict, match) -> list[tuple[float, str]]`.
- [ ] Step 1: Write `test_run_signature_last_param_match`: `list(inspect.signature(pipeline.run).parameters)[-1] == 'match'` and its default is None.
- [ ] Step 2: Write `test_run_bad_match_raises_before_writing` (parametrize `{'kickoff': -1}`, `{'venue': 'X'}`, `{'home': 'x' * 41}`, `{'kickoff': float('nan')}`): `pytest.raises(PipelineError)` and `not (tmp_path / 'out').exists()`. Monkeypatch `pipeline.require_ffmpeg` to `pytest.fail` to prove the check comes first.
- [ ] Step 3: Write `test_write_script_uses_match` (burst_video, `top=1`, `voiceover=True`, `match={'home': 'Việt Nam', 'away': 'Thái Lan', 'kickoff': 0}`). Every script line text joined contains 'Việt Nam' and 'Thái Lan'. Also write `test_kickoff_after_clip_no_minute` (kickoff 9999: no line contains 'Phút').
- [ ] Step 4: Run and see the tests fail. Implement. Run and see them pass.

### Task 3: `cut --meta` and the cut match options
**Files:** Modify `sportscut/cli.py` (cut parser, the checks after parse_args, the cut branch). Test: `tests/test_cut_meta.py`.
**Interfaces:** Consumes Task 1 helpers, Task 2 `run(match=)` and `publish.write_meta`, `publish.CAPTIONS_NAME`, `publish.REEL_NAME`.
- [ ] Step 1: Forwarding tests with a fake `cli.run` (returns `[{'file': 'clip_01.mp4'}]`) and a fake `cli.publish.write_meta` that records `(out_dir, match, backend)`:
  - no options: `calls[-1]['match'] is None` and write_meta is not called;
  - `--voiceover --home 'Việt Nam' --kickoff 0`: `match == {'home': 'Việt Nam', 'kickoff': 0.0}`;
  - `--meta --match-info f.json --away X`, where f.json is `{"away": "Y", "competition": "V.League 2026"}`: write_meta gets `(args.out, {'away': 'X', 'competition': 'V.League 2026'}, 'template')`, and `run` gets the same dict;
  - `--meta --meta-backend llm`: backend 'llm';
  - stdout is `[out/clip_01.mp4, out/captions.txt, out/reel.json]`.
- [ ] Step 2: Usage-error tests (SystemExit code 2, `run` must not be called, exact message in stderr) for `--home X`, `--kickoff 0`, `--match-info m.json` without --meta and --voiceover, and for `--meta-backend llm` without --meta.
- [ ] Step 3: Runtime-error tests: a missing --match-info file gives exit 1, stderr starting with `sportscut: error: cannot read`, empty stdout, and `run` is not called. A fake write_meta raising `ValueError('boom')` gives exit 1, stderr `sportscut: error: boom\n`, empty stdout. A fake run returning `[]` with --meta gives exit 0, write_meta not called, stderr `sportscut: notice: no clips were cut; --meta wrote nothing\n` and empty stdout.
- [ ] Step 4: End-to-end test `test_cut_meta_end_to_end` (burst_video): `main(['cut', str(burst_video), '--out', str(out), '--top', '1', '--meta', '--home', 'Việt Nam', '--away', 'Thái Lan', '--kickoff', '0']) == 0`. Assert:
  - every highlights.json entry ends with keys title, caption, hashtags, and '#VietNam' is in each `hashtags`;
  - captions.txt contains '#VietNam';
  - reel.json title == 'Tổng hợp highlight: Việt Nam vs Thái Lan';
  - stdout ends with the captions.txt and reel.json paths.
- [ ] Step 5: Run and see the tests fail. Implement. Run and see them pass.

### Task 4: README and docs
- [ ] Insert the README subsection (see Design). Append `## Updated by T-048` to the T-004, T-026 and T-047 specs and add the INDEX row.
- [ ] `python -m pytest -q tests/test_t047_acceptance.py tests/test_t027_acceptance.py` passes.

## Verification (all must hold; quote the summary lines)
1. `python -m pytest -q`: 0 failed.
2. `python -m sportscut eval-meta tests/fixtures/eval_meta --json` and `python -m sportscut eval-meta tests/fixtures/eval_meta --json --script` print the same bytes as on the merge-base. Compare with `git archive $(git merge-base main HEAD) | tar -x -C /tmp/t048-base` and `PYTHONPATH=/tmp/t048-base python -m sportscut eval-meta ...`. No branch switching or worktree is needed.
3. `python -m sportscut eval tests/fixtures/eval --json` gives the same f1 as the merge-base (same /tmp/t048-base method).
4. Today vs branch byte-identity: build burst.mp4 with the ffmpeg command from tests/conftest.py (burst_video). Then run `PYTHONPATH=/tmp/t048-base python -m sportscut cut /tmp/burst.mp4 --out /tmp/o-base --top 2 --voiceover` and `python -m sportscut cut /tmp/burst.mp4 --out /tmp/o-branch --top 2 --voiceover`. `diff -r /tmp/o-base /tmp/o-branch` prints nothing. If the [tts] extra is installed, add `-x '*.vo.mp4'`.
5. `git diff --numstat $(git merge-base main HEAD) -- . ':!docs/superpowers'` totals < 400 changed lines. README.md has 0 deleted lines.
6. CLI example: `python -m sportscut cut /tmp/burst.mp4 --out /tmp/o-meta --top 1 --meta --home 'Việt Nam' --away 'Thái Lan' --kickoff 0`. It exits 0, the last two stdout lines are /tmp/o-meta/captions.txt and /tmp/o-meta/reel.json, and `grep -c '#VietNam' /tmp/o-meta/captions.txt` is at least 1.

## Test plan

- tests/test_cut_meta.py (Developer, ≤ 150 lines, TDD): test_meta_help_unchanged; test_match_from_args_merges_file_and_flags (flag override, None when empty, 'cannot read' and 'expected a JSON object' errors).
- tests/test_cut_meta.py: test_run_signature_last_param_match; test_run_bad_match_raises_before_writing, parametrized over kickoff -1, kickoff nan, unknown key 'venue' and a 41-character home, with pipeline.require_ffmpeg monkeypatched to pytest.fail and asserting out_dir does not exist.
- tests/test_cut_meta.py: test_write_script_uses_match (burst_video, top=1, voiceover=True, match home/away/kickoff 0: the lines name both teams); test_kickoff_after_clip_no_minute (kickoff 9999: no 'Phút').
- tests/test_cut_meta.py: CLI forwarding with fake cli.run and fake cli.publish.write_meta (match None or dict, merge with flags winning, backend template or llm, stdout order); usage errors exit 2 (match options without --meta/--voiceover, --meta-backend without --meta); runtime errors exit 1 (missing match file, write_meta ValueError); empty entries notice.
- tests/test_cut_meta.py: test_cut_meta_end_to_end on burst_video (hashtags with '#VietNam', captions.txt, reel.json title, stdout tail).
- tests/test_t048_acceptance.py (Tester, ≤ 150 lines, written from the ACs, not from the Developer tests). A module-scoped fixture runs cut on burst_video (--top 1) four times: plain; --meta with the Việt Nam/Thái Lan/kickoff 0 flags; --voiceover; --voiceover with the same flags. It monkeypatches cli.voiceover.default_synthesizer to return None so no TTS is needed.
- tests/test_t048_acceptance.py: AC3 equivalence (copy the plain OUT, run `main(['meta', copy, flags...])`, compare highlights.json, captions.txt and reel.json bytes with the --meta OUT); AC4 sha256 of every clip_NN.mp4 plain vs --meta, and highlights.json minus meta keys equals plain; AC5 validate_script == [], script_fits, names and 'Phút N' present, highlights.json bytes equal; AC6 no-match scripts byte-identical to the T-026 formula; Review Focus 3: --match-info containing score '2-1' gives validate_script == []; Review Focus 5: running cut --meta twice into the same OUT gives the same bytes.
- tests/test_t048_acceptance.py: AC8, AC9 and AC10 CLI errors (including a real --kickoff -1 run that writes no clip), AC11 README section checks and AC12 spec/INDEX needle checks. No git-diff assertions in pytest (T-028 rule); scope and size are checked by the Verification commands.
- Commands: `python -m pytest -q`; eval-meta (--json and --json --script) and `sportscut eval tests/fixtures/eval --json` compared with a `git archive` export of the merge-base under PYTHONPATH; `diff -r` of merge-base vs branch `cut --top 2 --voiceover` output on the conftest burst video; `git diff --numstat` size check.

## Deviations

- (Developer) The T-004 and T-026 specs get `### Updated by T-048` (level 3) instead of `## Updated by T-048`. The ungated tests `tests/test_t027_acceptance.py::test_ac16_spec_appendices` require that no `\n## ` line follows the `## Updated by T-027` appendix in those two files, and existing tests must not be weakened. The heading still contains the AC12 needle `## Updated by T-048` and is appended at the end. This matches the README `###` precedent (DECISIONS, T-048). The T-047 spec has no such constraint and keeps `## Updated by T-048`.
- (Developer) INDEX.md already had the T-048 row when the task started, so no second row was added.
- (Developer) Verification note: `PYTHONPATH=/tmp/t048-base python -m sportscut ...` run from the worktree still imports the branch code, because `python -m` puts the current directory first on sys.path. The merge-base comparisons were therefore run with `cd /tmp/t048-base && python -m sportscut ...` (checked: `pipeline.run`'s last parameter there is `synthesizer`).
