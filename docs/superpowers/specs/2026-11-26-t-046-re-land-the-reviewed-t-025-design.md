# T-046: Re-land the reviewed T-025 Claude LLM metadata backend (validate_meta, generate_metas_llm, eval-meta --meta-backend) on 

Request R-005. Plan: `docs/superpowers/plans/2026-11-26-t-046-re-land-the-reviewed-t-025.md`.

## Product Owner request

Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt.

## Goal

Request R-005. This replaces T-025, whose branch hit the diff_size guardrail only because the guardrail counted three tasks merged in from main (T-015, T-028, T-044) against its stale start base 0c613ee. The behaviour, spec and acceptance criteria are exactly those of docs/superpowers/specs/2026-11-25-t-025-add-an-optional-claude-llm-backend-design.md and the T-025 plan. Read them first; nothing is redesigned.

HOW: start from current main. Port each file from the reviewed commit 4c336f8 with `git show 4c336f8:<path> > <path>` and confirm with `git hash-object`. Never run git commands that write the index (checkout -- path, add, mv, stash, commit), per T-042. The orchestrator stages the work. Files to port verbatim:
- pyproject.toml
- sportscut/cli.py
- sportscut/commentary/eval_meta.py
- sportscut/commentary/llm.py
- tests/fixtures/llm_meta/good.json
- tests/fixtures/llm_meta/hallucinated.json
- tests/test_commentary_llm.py
- tests/test_t025_acceptance.py
- README.md
- the scope-test narrowings in tests/test_t013_acceptance.py, test_t014_acceptance.py, test_t015_acceptance.py, test_t023_acceptance.py, test_t034b_acceptance.py, test_t042_acceptance.py, test_t042_round2_acceptance.py, test_t042_tester_acceptance.py and test_t044_acceptance.py. Each only removes 'pyproject.toml' (and, in the two t042 SHARED lists, 'sportscut/cli.py') from frozen or forbidden lists, per the T-013 precedent.
- the docs/superpowers spec notes (T-013 AC15, T-014 AC15, T-015, T-023 AC16 plus '## Updated by T-025', T-041 AC9) and the T-025 spec and plan.
If main moves again and a ported file differs from main on lines that T-025 did not change, apply only T-025's hunks (`git diff 9aa5a85 4c336f8 -- <path>`) onto main's version. Do not overwrite another task's work. Add a T-046 INDEX line. Do not edit DECISIONS.md (the orchestrator appends).

FIX ONE GAP: the AC13 scope test is missing from tests/test_t025_acceptance.py at 4c336f8, apparently dropped during a merge resolution. The Tester restores a compact test_ac13_scope_and_size of at most 15 lines that checks the following against `git merge-base main HEAD`:
- none of facts.py, meta.py, export.py, pipeline.py, api.py, models.py, tests/conftest.py, tests/fixtures/eval_meta/cases.json or agent-office/ is touched;
- the only edited pre-existing test files are the scope tests listed above (allow-list t013, t014, t015, t023, t034b, t042, t042_round2, t042_tester, t044);
- the --numstat total outside docs/superpowers is < 520.
The 520 budget replaces T-025's 500 only to make room for this restored test. Nothing else grows.

VERIFY and quote the summary lines:
- `git diff --shortstat main -- . ':(exclude)docs/superpowers'`, under 520 lines;
- `python -m pytest -q`, 0 failed;
- `PATH=/nonexistent python -m pytest -q tests/test_commentary_llm.py tests/test_t025_acceptance.py tests/test_eval_meta.py` passes;
- `python -m sportscut eval-meta tests/fixtures/eval_meta --json` prints score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0.

AC15 LIVE GATE: if ANTHROPIC_API_KEY is absent, write 'LIVE EVAL NOT RUN: no ANTHROPIC_API_KEY' in the report and finish DONE, not BLOCKED. The PR is not merged until a live run shows score >= 1.0, hallucination_rate 0.0 and no 'template fallback' in stderr. The README result line is then replaced with the measured one. Never echo, log or store any key.

## Acceptance criteria

- AC1: Before the orchestrator commit, for every file in Steps 1 and 2 and the docs ported in Step 4 (except the T-025 design spec, which gets one appended T-046 line), `git hash-object <path>` equals `git rev-parse 4c336f8:<path>`. If main moved past 9aa5a85, `git diff 4c336f8 -- <path>` shows only the other tasks' lines that main added.
- AC2: All of T-025's AC1-AC12 and AC14 hold unchanged, as checked by the ported tests/test_commentary_llm.py and tests/test_t025_acceptance.py (validate_meta, generate_metas_llm one-request shape, good/hallucinated fixtures, fallbacks, key never leaked, evaluate_meta_dir backend, --meta-backend CLI flag, README '### Backend LLM (tùy chọn)' section).
- AC3: tests/test_t025_acceptance.py equals 4c336f8's version plus one appended function test_ac13_scope_and_size of at most 15 lines (`git diff --numstat` against 4c336f8's blob: <= 15 added, 0 deleted). It adds no imports.
- AC4: test_ac13_scope_and_size skips with 'main is required for scope check' when `git merge-base main HEAD` fails. It also skips when tests/test_t025_acceptance.py is not added (diff-filter=A) relative to the merge base, so it skips on main after merge and on later branches.
- AC5: On the committed T-046 branch, test_ac13_scope_and_size runs (not skipped) and passes. It asserts: no changed path is sportscut/commentary/facts.py, sportscut/commentary/meta.py, sportscut/export.py, sportscut/pipeline.py, sportscut/api.py, sportscut/models.py, tests/conftest.py or tests/fixtures/eval_meta/cases.json, or under agent-office/. The modified (diff-filter=M) files under tests/ are a subset of the t013, t014, t015, t023, t034b, t042, t042_round2, t042_tester and t044 acceptance files. The numstat added+deleted outside docs/superpowers is < 520.
- AC6: test_ac13_scope_and_size can fail. With a temporary extra line in sportscut/commentary/meta.py on the committed branch, `python -m pytest -q tests/test_t025_acceptance.py -k ac13` reports 1 failed. After reverting, it passes.
- AC7: `git diff 9aa5a85 -- tests/test_t013_acceptance.py tests/test_t014_acceptance.py tests/test_t015_acceptance.py tests/test_t023_acceptance.py tests/test_t034b_acceptance.py tests/test_t042_acceptance.py tests/test_t042_round2_acceptance.py tests/test_t042_tester_acceptance.py tests/test_t044_acceptance.py` removes only list entries "pyproject.toml" (and "sportscut/cli.py" from test_t042_round2 SHARED_FILES and test_t042_tester SHARED_PATHS). No other line is added, removed or changed.
- AC8: `python -m pytest -q` reports 0 failed. `PATH=/nonexistent python -m pytest -q tests/test_commentary_llm.py tests/test_t025_acceptance.py tests/test_eval_meta.py` passes with anthropic not installed and no network.
- AC9: `git diff --shortstat main -- . ':(exclude)docs/superpowers'` on the committed branch reports fewer than 520 changed lines (insertions + deletions).
- AC10: `git diff --name-only main` contains no path under agent-office/ or .agent-office/, does not contain docs/superpowers/DECISIONS.md, and `git ls-files '*.mp4'` is empty.
- AC11: `python -m sportscut eval-meta tests/fixtures/eval_meta --json` prints score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0. The `sportscut eval` F1 gate is not lowered.
- AC12: docs/superpowers/INDEX.md gains exactly one appended T-046 row (existing rows unchanged). The T-025 design spec and plan exist under docs/superpowers. The T-025 design spec's AC13 carries an '(updated by T-046' note. The T-013, T-014, T-015, T-023 and T-041 design specs carry 4c336f8's '(updated by T-025' notes.
- AC13 (live gate, not CI): without ANTHROPIC_API_KEY the report contains 'LIVE EVAL NOT RUN: no ANTHROPIC_API_KEY' and the task finishes DONE. Merge requires a run with a key of `python -m sportscut eval-meta tests/fixtures/eval_meta --json --meta-backend llm` with score >= 1.0, hallucination_rate 0.0 and no 'template fallback' in stderr, after which the README 'Kết quả chạy thật (T-025)' line is replaced with the measured values. The key never appears in any output, log or file.

## Out of scope

- Any change to T-025's behaviour, interfaces, prompt, model, fallback rules or fixtures.
- --meta-backend on `sportscut cut`, `sportscut meta` or the API (T-024 re-split).
- Vietnamese voice-over / TTS.
- Editing docs/superpowers/DECISIONS.md (the orchestrator appends).
- Fixing the office guardrail's stale base_ref (agent-office/ is protected).
- Narrowing or editing any other existing test beyond the listed pyproject.toml / cli.py list removals.
- Live-network tests in CI or recording new responses.
- Raising any other size budget besides 500 -> 520 for the restored ac13 test.

## Decisions

- D1 T-046 (R-005): T-046 ports content, not commits. Because merge-base(main, 4c336f8) == 9aa5a85 == main, every file is ported byte-identical with `git show 4c336f8:<path> > <path>` and checked with `git hash-object`. If main moves, only `git diff 9aa5a85 4c336f8 -- <path>` hunks are applied onto main's version. No index-writing git commands (T-042 rule).
- D2 T-046 (R-005): test_ac13_scope_and_size is restored against `git merge-base main HEAD`, with a guard: it skips unless tests/test_t025_acceptance.py is an added file in that diff. This follows the T-013 rule that a per-task scope test cannot freeze files for later tasks, and it answers the T-028 concern that led T-025 round 2 to drop ac13. The test checks the T-046 branch once and skips on main and on every later branch. It supersedes the 2026-11-26 T-025 round-2 entry 'test_t025_acceptance.py has no ac13'.
- D3 T-046 (R-005): The ac13 allow-list of edited pre-existing tests is t013, t014, t015, t023, t034b, t042, t042_round2, t042_tester, t044. The forbidden set is facts.py, meta.py, export.py, pipeline.py, api.py, models.py, tests/conftest.py, tests/fixtures/eval_meta/cases.json and agent-office/.
- D4 T-046 (R-005): The size budget outside docs/superpowers becomes < 520 (T-025: < 500) only to fit the restored <= 15-line test. T-025 measured 497 lines. The Tester acceptance file budget becomes <= 155 lines. All other T-025 budgets (llm.py <= 110, Developer tests <= 130) are unchanged.
- D5 T-046 (R-005): Git-based checks (ac13, shortstat, name-only) are judged on the branch after the orchestrator commits the Developer's work, because untracked files are absent from `git diff` (T-044 precedent).
- D6 T-046 (R-005): A missing ANTHROPIC_API_KEY ends the task DONE with 'LIVE EVAL NOT RUN: no ANTHROPIC_API_KEY'. The T-025 AC15 live gate stays a merge gate, not a task-completion gate.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-025-add-an-optional-claude-llm-backend-design.md`
- `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md`
- `docs/superpowers/specs/2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md`
- `docs/superpowers/specs/2026-11-23-t-014-tag-saves-using-whistle-detection-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-015-tag-red-cards-and-controversial-incidents-design.md`
- `docs/superpowers/specs/2026-11-24-t-041-add-the-theo-d-i-c-design.md`
- `docs/superpowers/specs/2026-11-25-t-044-re-land-the-reviewed-t-017-design.md`
- `docs/superpowers/specs/2026-11-24-t-042-land-the-t-017-9-16-design.md`

## Updated by T-026

Updated by T-026: `llm.py` gains `SCRIPT_PROMPT` and `script_roles_llm(facts, limits, client=None) -> dict | None`, which asks for `{"before", "at", "after"}` commentary roles for one clip with the same key, import, exception and no-secret logging rules as `generate_metas_llm` (warnings end with `template fallback`). `generate_metas_llm`, `build_request`, `parse_response` and `SYSTEM_PROMPT` are unchanged. The returned roles are placed and checked by `script.validate_script`; a rejected script falls back to the template.
