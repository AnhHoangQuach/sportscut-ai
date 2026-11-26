# T-044: Re-land the reviewed T-017/T-042 9:16 reframing eval (reframe, probe_size, eval-crop) on current main

Request R-004. Plan: `docs/superpowers/plans/2026-11-25-t-044-re-land-the-reviewed-t-017.md`.

## Product Owner request

Tự xuất video dọc 9:16 cho TikTok/Reels: tự bám theo bóng và cầu thủ để crop, có phụ đề và tỉ số.

## Goal

Port the finished and reviewed commits from office/T-042 (0987533 feat, 64c51ea tests; base 888573b) onto current main with no behaviour change. The files are sportscut/reframe.py, sportscut/eval_crop.py, media.probe_size (appended to sportscut/media.py), the eval-crop subcommand in sportscut/cli.py, tests/fixtures/eval_crop/build.py plus the 4 labels.json files, tests/test_reframe.py, tests/test_eval_crop.py, tests/test_eval_crop_fixtures.py, tests/test_t017_acceptance.py, tests/test_t042_acceptance.py, tests/test_t042_round2_acceptance.py, tests/test_t042_tester_acceptance.py, the tests/test_cli.py and tests/test_media.py additions, the README eval-crop section (last section, centre baseline ball_in_crop 0.2821, players_in_crop 0.4024, jitter 0.0), the T-017 and T-042 specs and plans, and the T-036 spec bullets. Resolve conflicts with main's newer media.py, test_media.py, README.md and test_t023_acceptance.py by appending after main's content. Never touch agent-office/. Acceptance: (1) the T-019 Step 0 command prints READY; (2) `python -m pytest -q` reports 0 failed; (3) `python -m sportscut eval-crop tests/fixtures/eval_crop --json` after building the fixtures matches the README baseline; (4) `git diff --name-only $(git merge-base main HEAD)` lists no agent-office/ path, no .mp4, and none of pipeline.py, evaluate.py, eval_player.py, export.py, conftest.py or pyproject.toml; (5) `python -m sportscut eval tests/fixtures/eval --json` gives the same f1 as main; (6) scope and diff tests compare against `git merge-base main HEAD`, never a two-dot `main`. This is a port of reviewed code, so the size is the T-042 size (about 2700 lines outside docs/superpowers, under the 4000-line guardrail).

## Acceptance criteria

- AC1: On the committed branch, the T-019 Step 0 command prints exactly `READY`: `test -f sportscut/reframe.py && grep -q 'def plan_crop' sportscut/reframe.py && grep -q 'def sample_times' sportscut/reframe.py && grep -q 'def probe_size' sportscut/media.py && test -f sportscut/eval_crop.py && test -f tests/fixtures/eval_crop/build.py && grep -q 'eval-crop' sportscut/cli.py && test -f tests/test_t017_acceptance.py && echo READY`
- AC2: `python -m pytest -q` on the committed branch reports 0 failed and 0 errors. Quote the summary line.
- AC3: After `python tests/fixtures/eval_crop/build.py`, `python -m sportscut eval-crop tests/fixtures/eval_crop --json` exits 0 and prints one JSON line with ball_in_crop == 0.2821, players_in_crop == 0.4024 and jitter == 0.0. per_clip lists long_pass, occluded, slow_dribble and white_distractor. With every seconds_per_min removed, it equals the JSON block in the README eval-crop section.
- AC4: `git diff --name-only $(git merge-base main HEAD)` lists no path under agent-office/ or .agent-office/, no .mp4, and none of sportscut/pipeline.py, sportscut/evaluate.py, sportscut/eval_player.py, sportscut/export.py, tests/conftest.py, pyproject.toml or .gitignore. `git ls-files '*.mp4'` prints nothing.
- AC5: `python -m sportscut eval tests/fixtures/eval --json` gives f1 equal to the f1 measured on main in Step 0 (0.8421).
- AC6: Each Step 2 file is byte-identical to 64c51ea: `git hash-object <path>` == `git rev-parse 64c51ea:<path>`, checked at port time. tests/test_t042_acceptance.py and tests/test_t042_tester_acceptance.py are identical to 6e2935e. tests/test_t042_round2_acceptance.py differs from 6e2935e only by the one deleted line `assert set(stats) == set(SHARED_FILES)`.
- AC7: Against `git merge-base main HEAD`, `git diff --numstat` shows 0 deleted lines for sportscut/media.py (23 added), sportscut/cli.py (15), tests/test_media.py (23), tests/test_cli.py (45), README.md (29), the T-036 spec (6), the T-023 spec, docs/superpowers/DECISIONS.md and docs/superpowers/INDEX.md. tests/test_t023_acceptance.py shows exactly 10 added and 1 deleted. main's sample_top_band and its tests are still present.
- AC8: README.md ends with the reviewed eval-crop section (`## Video dọc 9:16: đo khung cắt (eval-crop)` through the end of `git show 314d171:README.md`). media.probe_size's source equals the one in 314d171. DECISIONS.md contains '2026-11-23 T-017 (R-004)'. INDEX.md has the T-017 and T-042 rows.
- AC9: tests/test_t023_acceptance.py::test_ac16 calls `git merge-base main HEAD` and then `git diff --name-only <mb> -- sportscut/export.py pyproject.toml tests/conftest.py`. It skips with 'main is required for scope check' when merge-base fails or prints nothing, and fails when that diff lists a file.
- AC10: No scope or diff test added or ported by this task compares against a two-dot `main`. `grep -n -E '"(--name-only|--numstat|--stat|--quiet)", "main"' tests/test_t023_acceptance.py tests/test_t042_acceptance.py tests/test_t042_round2_acceptance.py tests/test_t042_tester_acceptance.py tests/test_t044_acceptance.py` prints nothing.
- AC11: The ported T-042 tests still pass where the merge-base is HEAD (main after the merge). test_t042_round2_acceptance.test_ac3_shared_files_are_append_only passes when the numstat output is empty.
- AC12: Changed lines outside docs/superpowers against the merge-base are under 4000 (expected about 2650).

## Out of scope

- Any change to reframe.plan_crop behaviour, i.e. ball/player tracking (T-019), and vertical rendering or `cut --vertical` (T-043).
- Making the other ported T-042 per-task checks safe for later tasks. Those are ac2 (`git diff --quiet office/T-017-r2` and `git show 314d171`), the ac3/ac10 append-only and protected-path checks, and ac7 README-ends-with. They stay as reviewed. A later task that legitimately changes those files updates them under its own recorded decision.
- Fixing the office guardrail's base_ref behaviour (agent-office/ is protected).
- Changes to two-dot scope tests in other files (test_t013 ac15 and similar).
- Porting anything else from 6e2935e (its README, T-036 spec, DECISIONS and INDEX edits, or its T-042 spec/plan notes).
- Subtitles, scoreboard overlay and TikTok/Reels export from the PO request (later R-004 tasks).

## Decisions

- T-044 ports content, not commits. Whole new files come byte-identical from 64c51ea. The five shared code/test files (media.py, cli.py, test_media.py, test_cli.py, test_t023_acceptance.py) come from 6e2935e, but only after `git diff --numstat HEAD 6e2935e` proves each is main plus pure additions (23/0, 15/0, 23/0, 45/0, 10/1). Otherwise the 888573b..64c51ea hunks are applied by hand after main's content.
- The three T-042 test files come from 6e2935e. Their AC16 expectation drops sportscut/evaluate.py to match main's AC16 list (T-013 decision: a per-task scope rule cannot freeze a file for later tasks). This is not a weakened test.
- tests/test_t042_round2_acceptance.py::test_ac3 loses `assert set(stats) == set(SHARED_FILES)` and keeps the 0-deleted-lines assertion. 'Every shared file changed' holds only on the landing branch. After the merge, merge-base == HEAD makes the set empty, so main and every later branch would fail. The landing fact is checked once by command (AC7).
- media.probe_size keeps its reviewed position right after probe_duration. That is a pure insertion with 0 deleted lines, so the shared-file rule is met. The task's word 'appended' means added without changing main's lines.
- The README eval-crop section is appended verbatim as the last README section. Baseline comparisons ignore seconds_per_min (wall clock). Every other number is deterministic and must match exactly.
- The T-017/T-042 DECISIONS lines and INDEX rows are appended verbatim (24 lines and 2 rows from 888573b..64c51ea), so the landed design can be found. DECISIONS.md and INDEX.md stay append-only.
- Every scope or diff check in T-044 uses `git merge-base main HEAD`, never a two-dot `main`.
- Tests that T-044 adds hold only facts that stay true after the merge (behaviour, call shapes, README baseline). Byte-identity and 'file unchanged' facts are proven by commands in the Tester report, not frozen into pytest.
- Developers never write the git index (no checkout -- path, add, mv, stash, commit, add -N). Ported files are written with `git show <ref>:<path> > <path>` and checked with git hash-object. Git-diff-based ported tests are judged after the orchestrator commits.
- The diff is about 2650 lines outside docs/superpowers, above the usual ~400-line PR size, only because it lands already-reviewed T-017/T-042 code, fixtures and tests. Review focuses on the shared-file hunks, the AC16 list, the one round-2 test edit and the scope commands.
- There is no eval-F1 risk: no detection code changes, and `sportscut eval` F1 must equal main's (0.8421).

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-017-add-a-measurable-9-16-reframing-design.md`
- `docs/superpowers/specs/2026-11-24-t-042-land-the-t-017-9-16-design.md`
- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`
- `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md`
- `docs/superpowers/specs/2026-11-23-t-013-tag-goals-from-scoreboard-region-changes-design.md`
Updated by T-045: E4. `test_e_eval_crop_cli_on_built_fixtures_matches_readme` keeps the subprocess CLI run and its shape checks, adds `jitter <= 0.002`, and checks the README baseline values (0.2821, 0.4024, jitter 0.0, all non-timing fields) in-process with `reframe.plan_crop` patched to `reframe.center_plan`.
