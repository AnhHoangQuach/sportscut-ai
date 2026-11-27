# T-048: Add `sportscut cut --meta` with the match-info options, also feeding the match info into voice-over scripts

Request R-005. Plan: `docs/superpowers/plans/2026-11-27-t-048-add-sportscut-cut-meta-with-the.md`.

## Product Owner request

Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt.

## Goal

Request R-005, second slice of T-024. `sportscut cut` gains `--meta`, `--meta-backend template|llm` and the same match-info options as `sportscut meta` (--home, --away, --competition, --kickoff, --match-info), reusing the parsing helper from task 1. After `run(...)` returns, `cut --meta` calls publish.write_meta(out, match, backend) and prints the paths of captions.txt and reel.json. `pipeline.run` gets one new last keyword `match=None`, and `_write_script` uses facts_from_entry(entry, match). This lets `--voiceover` scripts mention teams or the minute only when they are given. Without --meta and without match options, every output file (highlights.json, clips, scripts) stays byte-identical to today. An end-to-end test on the synthetic video compares hashes with and without the flags. Tests: an end-to-end `cut --meta --home 'Việt Nam' --away 'Thái Lan' --kickoff 0` on the synthetic video writes the fields and captions.txt, with `#VietNam` present. The scripts from `cut --voiceover` plus match info pass the eval-meta fact checks and still fit the clip window (script_fits). The scripts and manifest without match info are unchanged. Files: sportscut/cli.py, sportscut/pipeline.py, tests/test_cut_meta.py (new), README.md (insert-only), docs/superpowers spec and INDEX. Verify: pytest 0 failed; eval-meta (with and without --script) score unchanged; `sportscut eval` F1 unchanged; diff < 400 lines outside docs/superpowers.

## Acceptance criteria

- AC1 `sportscut cut --help` lists --meta, --meta-backend, --home, --away, --competition, --kickoff and --match-info. `sportscut meta --help` still lists OUT_DIR, --home, --away, --competition, --kickoff, --match-info and --meta-backend with unchanged help texts, and every test in tests/test_t047_acceptance.py and tests/test_commentary_publish.py passes unchanged.
- AC2 `pipeline.run` has `match` as its last parameter, defaulting to None. Invalid match info (kickoff -1 or NaN, the unknown key 'venue', a home name of 41 characters, a non-mapping) raises PipelineError before require_ffmpeg is called and before anything is written to out_dir.
- AC3 End to end on the burst_video fixture: `sportscut cut VIDEO --out OUT --top 1 --meta --home 'Việt Nam' --away 'Thái Lan' --kickoff 0` exits 0. Every highlights.json entry ends with the keys title, caption and hashtags, with '#VietNam' in hashtags. captions.txt exists and contains '#VietNam'. reel.json has the title 'Tổng hợp highlight: Việt Nam vs Thái Lan'. stdout is the clip paths followed by OUT/captions.txt and OUT/reel.json. The three files are byte-identical to running plain `cut` into another directory and then `sportscut meta` on it with the same match options.
- AC4 Hash comparison with and without the flags on burst_video: every clip_NN.mp4 from `cut --top 1` has the same sha256 as from `cut --top 1 --meta --home 'Việt Nam' --away 'Thái Lan' --kickoff 0`. The --meta highlights.json, with title, caption and hashtags removed, equals the plain highlights.json. The plain OUT contains no captions.txt and no reel.json, and its highlights.json bytes equal `json.dumps(entries, indent=2) + '\n'`.
- AC5 Voice-over with match info: in the scripts from `cut --top 1 --voiceover --home 'Việt Nam' --away 'Thái Lan' --kickoff 0` (synthesizer patched to None), for every entry with facts = facts_from_entry(entry, match), `script.validate_script(facts, lines, clip_len) == []` and `script.script_fits(lines, clip_len)`. The joined text contains 'Việt Nam', 'Thái Lan' and f'Phút {facts.minute}'. Its clip_NN.mp4 sha256 values and its highlights.json bytes equal those of `cut --top 1 --voiceover` without match info.
- AC6 Voice-over without match info: no script line contains 'Phút', 'Việt Nam' or 'Thái Lan'. Each clip_NN.script.json is byte-identical to the T-026 formula recomputed from the record's own peak: `json.dumps({'clip', 'clip_len', 'peak', 'backend': 'template', 'lines'} built from script.write_script(facts_from_entry(entry), clip_len, 'template', peak=record['peak']), ensure_ascii=False, indent=2) + '\n'`.
- AC7 Forwarding (with a fake run and a fake write_meta): without match options, run receives match=None and write_meta is not called. Flags give a dict of only the given keys, with kickoff as a float. --match-info keys are merged with the flags winning. With --meta, write_meta receives (OUT, the same match dict, 'template'), or 'llm' with --meta-backend llm, and is called only after run returns.
- AC8 Usage errors exit 2 without calling run: any of --home, --away, --competition, --kickoff or --match-info without --meta and without --voiceover (stderr contains '--home, --away, --competition, --kickoff and --match-info need --meta or --voiceover'). --meta-backend without --meta (stderr contains '--meta-backend needs --meta'). --meta-backend foo.
- AC9 Runtime errors exit 1 with an empty stdout. A missing or unreadable --match-info file, or one that is not a JSON object, gives stderr 'sportscut: error: cannot read ...' or '...: expected a JSON object' and run is not called. A real run with --kickoff -1 gives stderr 'sportscut: error: kickoff must be non-negative' and no clip file in OUT. write_meta raising ValueError('boom') or OSError gives stderr 'sportscut: error: boom'.
- AC10 When run returns [] and --meta is given, write_meta is not called, stderr is exactly 'sportscut: notice: no clips were cut; --meta wrote nothing\n', stdout is empty and the exit code is 0.
- AC11 README.md is changed insert-only. A '### Tạo luôn khi cắt (cut --meta)' subsection sits between '## Xuất tiêu đề, caption, hashtag cho clip đã cắt (sportscut meta)' and '## Theo dõi cầu thủ: đo độ chính xác (eval-player)'. It contains 'cut', '--meta', '--voiceover', '--kickoff' and '#VietNam' or 'Việt Nam', and it has no '## ' line, no '```json' and no 'sẽ có ở task sau'.
- AC12 The T-004, T-026 and T-047 specs each end with an appended '## Updated by T-048' section. T-004 mentions 'match=None', T-026 mentions 'facts_from_entry(entry, match)' and T-047 mentions 'cut --meta'. INDEX.md gets one appended T-048 row and no other INDEX line changes.
- AC13 `python -m pytest -q` reports 0 failed. `eval-meta tests/fixtures/eval_meta --json` and the same with `--script` print bytes identical to the merge-base. `sportscut eval tests/fixtures/eval --json` f1 equals the merge-base value. `cut --top 2 --voiceover` output on burst.mp4 matches the merge-base with `diff -r`. The diff outside docs/superpowers is < 400 changed lines.

## Out of scope

- Metadata in the HTTP API or web page (the remaining T-024 slice).
- Storing match info in highlights.json or script.json, or a match.json written by cut.
- Changing publish.write_meta, facts.py, script.py, meta.py, llm.py or the template wording.
- An llm script backend for the pipeline (scripts stay template).
- Adding the title or caption to vertical overlays or burning them into clips.
- Validating match info inside _match_from_args (run and write_meta already validate it).
- Auto-detecting teams, competition or kickoff from the video.

## Decisions

- T-048 extracts the T-047 inline match parsing in cli.py into `_match_from_args(args) -> dict | None` (same messages, returns `match or None`, no value validation) and the option definitions into `_add_match_options(parser)`. Both `meta` and `cut` use them, and `meta` behaviour and help text stay byte-identical. This supersedes T-047's 'cli.py insert-only' rule for these lines only.
- `pipeline.run` gets `match=None` as its last keyword. When it is not None, it is validated with `facts_from_entry({'start': 0, 'end': 1, 'event': 'other'}, match)` before require_ffmpeg, and a ValueError becomes PipelineError. `_write_script` uses `facts_from_entry(entry, match)`. Match is never stored in script.json or highlights.json, and without voiceover it has no effect on output.
- cut always passes `match=` to run (None when no option is given). The match options need `--meta` or `--voiceover`, otherwise argparse exits 2. `--meta-backend` defaults to None (meaning template) and needs `--meta`.
- `cut --meta` calls `publish.write_meta(out, match, backend)` after run returns and before anything is printed. On success it prints the clip lines as today, then OUT/captions.txt and OUT/reel.json. A ValueError or OSError from write_meta or `_match_from_args` gives exit 1 with 'sportscut: error: <msg>' and an empty stdout. The existing run error handling is unchanged.
- `cut --meta` with zero clips skips write_meta, prints 'sportscut: notice: no clips were cut; --meta wrote nothing' to stderr and exits 0.
- `cut --meta` output files are by definition byte-identical to `cut` followed by `sportscut meta OUT` with the same match options and backend.
- Byte-identity with today is proven in pytest by comparing hashes between runs with and without the flags, plus a recomputation from the T-026 formula. The comparison against the merge-base is done by commands using a `git archive` export under PYTHONPATH (no branch switch or worktree), following the T-028 rule that pytest has no git-diff tests.
- README text for cut --meta is an insert-only `###` subsection at the end of the `sportscut meta` section, keeping T-047 AC15 and T-027 AC16 valid.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-27-t-047-add-sportscut-meta-out-dir-writing-design.md`
- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-026-generate-a-timed-vietnamese-commentary-script-design.md`
- `docs/superpowers/specs/2026-11-23-t-027-add-an-offline-vietnamese-tts-voice-design.md`
- `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md`
