# Plan T-046: Re-land the reviewed T-025 Claude LLM metadata backend (validate_meta, generate_metas_llm, eval-meta --meta-backend) on 

Design: `docs/superpowers/specs/2026-11-26-t-046-re-land-the-reviewed-t-025-design.md`.

## Implementation plan

# T-046: Re-land the reviewed T-025 Claude LLM metadata backend on current main

Request R-005. This replaces T-025 (`office/T-025`, reviewed tip `4c336f8`). T-025 was blocked by the diff_size guardrail only because the guardrail measured against the stale start base `0c613ee`, so the three tasks merged in from main (T-015 `dc06807`, T-028 `0b89c5a`, T-044 `9aa5a85`) counted against it. Nothing is redesigned. The behaviour, interfaces, ACs and decisions are exactly those of `docs/superpowers/specs/2026-11-23-t-025-add-an-optional-claude-llm-backend-design.md` and `docs/superpowers/plans/2026-11-23-t-025-add-an-optional-claude-llm-backend.md`. Both exist only at `4c336f8`; read them with `git show 4c336f8:<path>`. The task text calls the design file `2026-11-25-...`. Its real name is `2026-11-23-...`.

## Facts checked by the PM on 2026-11-26
- `git merge-base 9aa5a85 4c336f8` = `9aa5a85` = current main. So `4c336f8` is main plus T-025's changes only, and every ported file equals main's version plus T-025's hunks.
- `git diff --shortstat 9aa5a85 4c336f8 -- . ':(exclude)docs/superpowers'` = `18 files changed, 466 insertions(+), 31 deletions(-)` (497 lines). A restored test of at most 15 lines keeps the total under 520.
- `tests/test_t025_acceptance.py` at `4c336f8` has 139 lines and no `test_ac13*`. The DECISIONS entry '2026-11-26 T-025 Developer (review round 2)' shows it was dropped on purpose. The reason was the T-028 concern that git-diff scope tests break on later branches. The guard in the restored test fixes exactly that concern (Decision D2).

## Interfaces (unchanged from T-025, for the Tester)
- `sportscut/commentary/llm.py`: `SYSTEM_PROMPT: str`, `generate_metas_llm(facts_list, client=None) -> list[ClipMeta]`, logger `sportscut.commentary.llm`.
- `sportscut/commentary/eval_meta.py`: `validate_meta(facts, meta) -> list[str]` and `evaluate_meta_dir(path, backend='template')`. `score_case` is unchanged.
- CLI: `sportscut eval-meta DIR [--json] [--meta-backend {template,llm}]`.
- `pyproject.toml`: `[project.optional-dependencies] llm = ['anthropic>=0.40']`.

## Rules for every step
- Never run a git command that writes the index or refs: `checkout -- path`, `add`, `add -N`, `mv`, `rm`, `stash`, `commit`, `apply --index` (T-042 rule). Port a file with `mkdir -p <dir>; git show 4c336f8:<path> > <path>`. Then check that `git hash-object <path>` equals `git rev-parse 4c336f8:<path>`. The orchestrator stages and commits.
- Git-based checks (AC9, AC10, the ac13 test) see untracked files as absent. They are judged on the branch after the orchestrator commits the Developer's work (same as T-044). Before that commit, check new files with `git hash-object`.
- Do not edit `docs/superpowers/DECISIONS.md`. The orchestrator appends to it.

## Steps

### Step 0: main has not moved
`git rev-parse main` must print `9aa5a85...`. If it does not, then for each file below run `git diff 9aa5a85 4c336f8 -- <path>` and apply only those hunks by hand onto main's version, keeping every other task's lines. If it does, use verbatim `git show` ports.

### Step 1: port code, fixtures and Developer tests (verbatim from 4c336f8)
pyproject.toml, sportscut/cli.py, sportscut/commentary/eval_meta.py, sportscut/commentary/llm.py, tests/fixtures/llm_meta/good.json, tests/fixtures/llm_meta/hallucinated.json, tests/test_commentary_llm.py, README.md.

### Step 2: port the scope-test narrowings (verbatim from 4c336f8)
tests/test_t013_acceptance.py, test_t014_acceptance.py, test_t015_acceptance.py, test_t023_acceptance.py, test_t034b_acceptance.py, test_t042_acceptance.py, test_t042_round2_acceptance.py, test_t042_tester_acceptance.py, test_t044_acceptance.py.

Each one only removes `"pyproject.toml"` from a frozen or forbidden list. The two t042 SHARED lists (round2 `SHARED_FILES`, tester `SHARED_PATHS`) also lose `"sportscut/cli.py"`. Check with `git diff 9aa5a85 4c336f8 -- <file>`: the diff must contain only those removals (t015 and t034b and t044 each show 1 line changed, the two t042 SHARED files 3 deletions, the rest 1 deletion).

### Step 3: port the Tester acceptance file and restore ac13 (Tester)
Port `tests/test_t025_acceptance.py` verbatim from `4c336f8`, then append one function, `test_ac13_scope_and_size`, of at most 15 lines. It uses the module's existing `subprocess`, `pytest` and `ROOT` and adds no new imports. Behaviour:
1. `base = git merge-base main HEAD` (run with cwd=ROOT). If it fails or is empty: `pytest.skip('main is required for scope check')`.
2. Guard: if `tests/test_t025_acceptance.py` is not in `git diff --name-only --diff-filter=A <base>`: `pytest.skip('T-025 is not this branch\'s change')`. This keeps the test from freezing files for later tasks, and it does not run on main after merge.
3. `changed = git diff --name-only <base>`. None equals sportscut/commentary/facts.py, sportscut/commentary/meta.py, sportscut/export.py, sportscut/pipeline.py, sportscut/api.py, sportscut/models.py, tests/conftest.py or tests/fixtures/eval_meta/cases.json, and none starts with `agent-office/`.
4. `git diff --name-only --diff-filter=M <base> -- tests` is a subset of {tests/test_t013_acceptance.py, test_t014, test_t015, test_t023, test_t034b, test_t042, test_t042_round2, test_t042_tester, test_t044} (full `tests/test_<x>_acceptance.py` paths).
5. Sum `added+deleted` over `git diff --numstat <base> -- . ':(exclude)docs/superpowers'` (lines with `-` for binary count as 0). The sum is < 520.

Show that it can fail with a temporary local edit: append a comment line to sportscut/commentary/meta.py, check the test fails on the branch, then revert with a plain editor undo (no git command that writes the index).

### Step 4: docs
- Port verbatim from 4c336f8: the T-025 design spec and plan, and the spec notes in the T-013, T-014, T-015, T-023 (AC16 note plus '## Updated by T-025') and T-041 design specs.
- Then append one line to the ported T-025 design spec under AC13: `- (updated by T-046: the scope/size check is back as tests/test_t025_acceptance.py::test_ac13_scope_and_size. It runs only on the branch that adds that file, the allow-list is t013, t014, t015, t023, t034b, t042, t042_round2, t042_tester, t044, and the size limit is < 520.)`
- Append one row to docs/superpowers/INDEX.md: `| 2026-11-26 | T-046 | Re-land the reviewed T-025 Claude LLM metadata backend (validate_meta, generate_metas_llm, eval-meta --meta-backend) on current main | R-005 | [design](specs/2026-11-26-t-046-re-land-the-reviewed-t-025-design.md) | [plan](plans/2026-11-26-t-046-re-land-the-reviewed-t-025.md) | docs/superpowers/specs/2026-11-23-t-025-add-an-optional-claude-llm-backend-design.md, docs/superpowers/plans/2026-11-23-t-025-add-an-optional-claude-llm-backend.md, docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md, docs/superpowers/specs/2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md, docs/superpowers/specs/2026-11-23-t-014-tag-saves-using-whistle-detection-and-design.md, docs/superpowers/specs/2026-11-23-t-015-tag-red-cards-and-controversial-incidents-design.md, docs/superpowers/specs/2026-11-24-t-041-add-the-theo-d-i-c-design.md |`. Adjust the design and plan links to the file names the orchestrator actually writes.

### Step 5: verify and quote the summary lines
- `git diff --shortstat main -- . ':(exclude)docs/superpowers'`: under 520 changed lines (after the orchestrator commit).
- `python -m pytest -q`: 0 failed.
- `PATH=/nonexistent python -m pytest -q tests/test_commentary_llm.py tests/test_t025_acceptance.py tests/test_eval_meta.py`: passes.
- `python -m sportscut eval-meta tests/fixtures/eval_meta --json`: score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0.
- AC15 live gate. If ANTHROPIC_API_KEY is absent, the report says `LIVE EVAL NOT RUN: no ANTHROPIC_API_KEY` and the task ends DONE (not BLOCKED). The PR stays unmerged until a run with a key shows score >= 1.0, hallucination_rate 0.0 and no 'template fallback' in stderr. The README line 'Kết quả chạy thật (T-025): ...' is then replaced with the measured values. Never echo, log or store the key.

## Assumptions
- main is still `9aa5a85` when the Developer starts, so ports are byte-identical. Otherwise Step 0's hunk rule applies.
- The Tester role ports `tests/test_t025_acceptance.py`, because it contains the Tester-owned ac13 test. The Developer ports everything else.
- The restored test's size budget comes out of the 20-line headroom (497 to < 520). The T-025 per-file budget 'Tester acceptance <= 140' becomes <= 155 for this file only. All other budgets are unchanged.

## Test plan

- Port tests/test_commentary_llm.py and tests/test_t025_acceptance.py verbatim. They cover T-025 AC1-AC12 and AC14 with fake clients and fixtures, with no network.
- tests/test_t025_acceptance.py::test_ac13_scope_and_size (new, <= 15 lines, Tester): git merge-base skip, diff-filter=A guard skip, forbidden-path check, modified-tests allow-list check, numstat < 520 check.
- Fail check for ac13: temporarily add a line to sportscut/commentary/meta.py on the committed branch and see 1 failure, then revert with an editor (no index-writing git command).
- Skip check for ac13: on main (or with merge-base == HEAD), `python -m pytest -q tests/test_t025_acceptance.py -k ac13 -rs` shows 1 skipped with the T-025 guard message.
- Run the ported scope tests (test_t013 ac15, test_t014 ac15, test_t015 ac16/ac11, test_t023 ac16, test_t034b ac9_ac10, test_t042*, test_t044) through `python -m pytest -q`. All pass.
- Commands: `git diff --shortstat main -- . ':(exclude)docs/superpowers'` (< 520), `python -m pytest -q` (0 failed), `PATH=/nonexistent python -m pytest -q tests/test_commentary_llm.py tests/test_t025_acceptance.py tests/test_eval_meta.py` (passes), `python -m sportscut eval-meta tests/fixtures/eval_meta --json` (1.0/1.0/1.0/0.0/1.0). Quote each summary line.
- hash-object check: for each ported path, `git hash-object <path>` == `git rev-parse 4c336f8:<path>` (the T-025 design spec and test_t025_acceptance.py are expected to differ only by their T-046 appends).
- Live eval only if ANTHROPIC_API_KEY is present: `python -m sportscut eval-meta tests/fixtures/eval_meta --json --meta-backend llm`. Quote the five headline values, the model name and stderr. Otherwise report 'LIVE EVAL NOT RUN: no ANTHROPIC_API_KEY'.

## Deviations
- Step 0: main had moved. The worktree HEAD was 71cb0cc (T-043), not 9aa5a85. So the Developer applied `git diff 9aa5a85 4c336f8` (minus DECISIONS.md and INDEX.md) to the working tree with plain `git apply` (no `--index`). Every ported file except README.md and sportscut/cli.py is byte-identical to 4c336f8 (`git hash-object` == `git rev-parse 4c336f8:<path>`). README.md and sportscut/cli.py differ from 4c336f8 by exactly T-043's lines (`git diff 4c336f8 -- <p>` has the same +/- lines as `git diff 9aa5a85 71cb0cc -- <p>`), which meets AC1's moved-main clause. The cli.py hunks applied at offset +5.
- Later, main moved again to 189f3c1 (T-021), which also edits README.md and sportscut/cli.py. The worktree cannot be rebased (no index or ref writes), so the T-046 hunks were dry-run onto a scratch copy of 189f3c1: they apply cleanly (cli.py at offsets +14/+16). There, tests/test_cli.py, test_commentary_llm.py, test_eval_meta.py, test_t025_acceptance.py, test_t021_acceptance.py and test_vertical_overlay.py gave `298 passed, 5 skipped`. T-021's scope tests are gated to `office/T-021` branches. Its README test pins only the text from the eval-crop heading onward, and T-025's README section sits earlier, at '### Backend LLM (tùy chọn)'.
- Step 3: the Developer ported tests/test_t025_acceptance.py verbatim from 4c336f8 (it is in TASK.md's port list), so AC2 could be checked. The Tester still appends test_ac13_scope_and_size.
- Step 4: the T-046 INDEX row was already present (the orchestrator wrote it), so no second row was added.
- Step 5: under `PATH=/nonexistent` a bare `python` cannot be found, so the offline run uses the venv's absolute interpreter path: `PATH=/nonexistent "$(command -v python)" -m pytest -q ...`.
