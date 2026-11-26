# Plan T-044: Re-land the reviewed T-017/T-042 9:16 reframing eval (reframe, probe_size, eval-crop) on current main

Design: `docs/superpowers/specs/2026-11-25-t-044-re-land-the-reviewed-t-017-design.md`.

## Implementation plan

# T-044: Land the reviewed T-017/T-042 9:16 reframing eval on current main again

## Context
T-017 (reframe.plan_crop and crop_width, media.probe_size, `sportscut eval-crop`, the synthetic eval_crop fixtures and the centre-crop baseline) was finished and reviewed. T-042 was meant to land it on main. Its finished commits are on `office/T-042`: base `888573b`, then `98c6f3c` (the work, committed by the orchestrator), `0987533` (feat: one DECISIONS line plus the rename to tests/test_t042_acceptance.py), `46c7999` (tests/test_t042_tester_acceptance.py) and `64c51ea` (tests/test_t042_round2_acceptance.py). The tip `6e2935e` ('wip(office): T-042 blocked') is a partial merge of main. It is **not** ported as a whole. We only take from it the conflict resolution of five shared code/test files, which were checked to equal current main plus pure additions (see Step 1). T-042 was dropped because main moved under it, the same base_ref problem as T-015 (see DECISIONS 2026-11-25 T-015). T-044 ports the same content onto a fresh branch from current main (`dc06807`). No production behaviour changes. T-019 is waiting on this: its Step 0 check must print READY.

State of main, checked: no reframe.py, eval_crop.py, probe_size, eval-crop, T-017/T-042 docs or DECISIONS/INDEX rows exist on main. Main's sportscut eval F1 is 0.8421. `.gitignore` already ignores `*.mp4`. `cli.py` and `test_cli.py` are unchanged on main since 888573b. Main added `sample_top_band` to media.py and its tests to test_media.py (T-013). Main dropped `sportscut/evaluate.py` from test_t023 AC16 (T-013 decision). README gained sections, but its last section ('Trang web ...', ending with 'Trang trả về lỗi 404 nếu `JOB_ID` không tồn tại.') is unchanged.

## Hard rules for the Developer
- Never run git commands that write the index or refs (`checkout -- path`, `add`, `mv`, `rm`, `stash`, `commit`, `apply --index`, `add -N`). Port files with `git show <ref>:<path> > <path>` (create parent dirs with `mkdir -p`) and compare with `git hash-object <path>` against `git rev-parse <ref>:<path>`. The orchestrator stages and commits.
- Never touch `agent-office/`, `.agent-office/`, `.gitignore`, `pyproject.toml`, `tests/conftest.py`, `sportscut/pipeline.py`, `sportscut/evaluate.py`, `sportscut/eval_player.py` or `sportscut/export.py`. Never commit media: the fixture `clip.mp4` files are git-ignored.
- Shared files are append-only against `git merge-base main HEAD` (0 deleted lines). The one exception is tests/test_t023_acceptance.py: exactly 1 line is replaced, the T-042 reviewed AC16 change.

## Steps (in order)

### Step 0: Baseline
Run `python -m pytest -q` and `python -m sportscut eval tests/fixtures/eval --json`. If the eval videos are missing, build them first with `python tests/fixtures/eval/build.py`. Record the summary line and f1 (expected 0.8421). `MB=$(git merge-base main HEAD)`.

### Step 1: Shared code and tests, taken from the resolved T-042 tip `6e2935e`
First check that each file is exactly current main plus the T-042 additions. `git diff --numstat HEAD 6e2935e -- <file>` must print:
- `sportscut/media.py`: 23 0 (probe_size, inserted after probe_duration as reviewed)
- `sportscut/cli.py`: 15 0 (`from sportscut import eval_crop`, the eval-crop parser after eval-meta and before player, the handler after eval-meta and before cut)
- `tests/test_media.py`: 23 0 (the `probe_size` import plus 3 tests)
- `tests/test_cli.py`: 45 0
- `tests/test_t023_acceptance.py`: 10 1 (AC16 runs `git merge-base main HEAD`, skips with 'main is required for scope check' when that fails or is empty, then `git diff --name-only <mb> -- sportscut/export.py pyproject.toml tests/conftest.py`. This is main's protected list, without evaluate.py.)

If all five match, port each with `git show 6e2935e:<file> > <file>`. If any count differs (main moved again), apply that file's hunks from `git diff 888573b 64c51ea -- <file>` by hand on top of HEAD's file, adding after main's content and keeping main's lines. For test_t023 use main's protected list.

### Step 2: Whole new files from `64c51ea` (byte-identical)
`sportscut/reframe.py`, `sportscut/eval_crop.py`, `tests/fixtures/eval_crop/build.py`, `tests/fixtures/eval_crop/{long_pass,occluded,slow_dribble,white_distractor}/labels.json`, `tests/test_reframe.py`, `tests/test_eval_crop.py`, `tests/test_eval_crop_fixtures.py`, `tests/test_t017_acceptance.py`, `docs/superpowers/specs/2026-11-23-t-017-add-a-measurable-9-16-reframing-design.md`, `docs/superpowers/plans/2026-11-23-t-017-add-a-measurable-9-16-reframing.md`, `docs/superpowers/specs/2026-11-24-t-042-land-the-t-017-9-16-design.md`, `docs/superpowers/plans/2026-11-24-t-042-land-the-t-017-9-16.md`.

### Step 3: T-042 acceptance tests from `6e2935e`
Port `tests/test_t042_acceptance.py`, `tests/test_t042_round2_acceptance.py` and `tests/test_t042_tester_acceptance.py` from `6e2935e`. Each differs from 64c51ea by exactly one deleted line, `"sportscut/evaluate.py",` in the expected AC16 call list, to match main's AC16 list (T-013 decision). Then make one more edit, in `tests/test_t042_round2_acceptance.py::test_ac3_shared_files_are_append_only`: delete the line `assert set(stats) == set(SHARED_FILES)` and keep the `deleted == "0"` assertion. Reason: 'every shared file changed' is true only on the landing branch. Once merged, `git merge-base main HEAD` is HEAD on main, so the set is empty and the test would fail on main and on every later branch. Write the failing proof first. Tester test (b) below fails before this edit and passes after it.

### Step 4: Docs, append-only
- `README.md`: after main's last line, add one blank line and then the section from `## Video dọc 9:16: đo khung cắt (eval-crop)` to the end of `git show 314d171:README.md`, verbatim. It is the same text as 64c51ea: centre baseline ball_in_crop 0.2821, players_in_crop 0.4024, jitter 0.0. numstat vs MB: 29 0.
- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`: insert the 6 lines of the 888573b..64c51ea hunk ('## Assumptions', the 'T-017: same exception for the reframing eval set ...' bullet and the 'Updated by T-017: ...' paragraph). They go at the same place, between the 'Updated by T-030' and 'Updated by T-004' paragraphs. numstat vs MB: 6 0.
- `docs/superpowers/DECISIONS.md`: append at the end the 24 added lines of `git diff 888573b 64c51ea -- docs/superpowers/DECISIONS.md` (the T-017 and T-042 lines), verbatim and in order.
- `docs/superpowers/INDEX.md`: append the 2 added rows of `git diff 888573b 64c51ea -- docs/superpowers/INDEX.md` (T-042, then T-017), verbatim.
- `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md`: append the line `Updated by T-044 (T-042 review): AC16 diffs against \`git merge-base main HEAD\` (skip 'main is required for scope check' when unavailable) instead of the moving \`main\` ref; after T-013 its protected list is sportscut/export.py, pyproject.toml and tests/conftest.py.`
- `docs/superpowers/specs/2026-11-24-t-042-land-the-t-017-9-16-design.md` (after the Step 2 copy): append `Updated by T-044: landed from office/T-042 onto main dc06807. The T-042 AC16 expectations drop sportscut/evaluate.py (T-013), and round-2 test_ac3 no longer requires every shared file to change, because that holds only on the landing branch.`

### Step 5: Verify (commands under Acceptance)
Git-based checks that compare the working tree with refs (T-042 ac2 `git diff --quiet office/T-017-r2`, ac3 numstat) see untracked files as absent. They are judged on the branch after the orchestrator commits the Developer's work. Before that, check the new files with `git hash-object` instead.

## Interfaces (unchanged from the reviewed T-017 design spec, which stays authoritative)
- `reframe.crop_width(w, h, aspect=9/16) -> int` = `min(w, max(2, 2*floor(h*aspect/2)))`. `reframe.sample_times(duration)` is a 5 Hz grid. `reframe.plan_crop(path) -> list[(t, x_left)]` is a static centre crop.
- `media.probe_size(path) -> (width, height)`. It raises `MediaError` with 'media file not found: <path>', 'no video stream in <path>' or 'ffprobe failed for <path>: <detail>'.
- `eval_crop.evaluate_dir(dir) -> dict` with keys in order ball_in_crop, players_in_crop, jitter, seconds_per_min, per_clip.
- `sportscut eval-crop DIRECTORY [--json]` exits 0 and prints the report. On ValueError, OSError or MediaError it exits 2 with 'sportscut eval-crop: error: ...' on stderr.

## Assumptions
- `office/T-017-r2`, `314d171`, `64c51ea` and `6e2935e` exist in the local repo (checked). The ported T-042 tests read them.
- ffmpeg/ffprobe are on PATH where the suite runs, as for all existing media tests.
- Size: about 2650 changed lines outside docs/superpowers, which is the T-042 size and under the 4000-line guardrail.

## Test plan

- Developer: no new production tests. The ported Developer tests (tests/test_reframe.py, tests/test_eval_crop.py, tests/test_eval_crop_fixtures.py, plus the probe_size tests in tests/test_media.py and the eval-crop tests in tests/test_cli.py) must pass unchanged. Before Step 3's set-equality removal, run Tester test (b) and watch it fail. Then make the edit and watch it pass.
- Tester: write tests/test_t044_acceptance.py with only checks that stay true after the merge and on later branches. Do not freeze files with hash checks or 'file X unchanged' checks in pytest; those are verified by command (AC4, AC6, AC7, AC12) and quoted in the report.
- Tester test (a): the T-019 Step 0 markers. sportscut/reframe.py defines plan_crop and sample_times, sportscut/media.py defines probe_size, sportscut/eval_crop.py and tests/fixtures/eval_crop/build.py exist, `cli.main(['eval-crop', '--help'])` exits 0, and tests/test_t017_acceptance.py exists.
- Tester test (b): load tests/test_t042_round2_acceptance.py with importlib. Monkeypatch its `_merge_base` to return 'abc123' and its `_git` to return CompletedProcess(returncode=0, stdout=''). test_ac3_shared_files_are_append_only must not raise. Also feed one numstat line with deleted '3' and check that it raises AssertionError, so the append-only check is still active.
- Tester test (c): load tests/test_t023_acceptance.py and monkeypatch shutil.which and subprocess.run. Assert the exact calls: ['git','merge-base','main','HEAD'], then ['git','diff','--name-only','abc123','--','sportscut/export.py','pyproject.toml','tests/conftest.py']. Assert it skips with 'main is required for scope check' for returncode 128 and for empty stdout. Assert AssertionError when the diff prints 'pyproject.toml'.
- Tester test (d): read README.md and check that the last '## ' heading is 'Video dọc 9:16: đo khung cắt (eval-crop)'. The JSON block there must have ball_in_crop 0.2821, players_in_crop 0.4024 and jitter 0.0.
- Tester test (e, needs ffmpeg, else skip): build the eval_crop fixtures into tmp_path with build.build_all. Run `python -m sportscut eval-crop <tmp> --json` through subprocess and compare it to the README baseline, ignoring every seconds_per_min.
- Tester test (f): run the AC10 grep over the listed test files as a subprocess and assert that it prints nothing.
- Tester confirms that (b) and (c) can fail: temporarily restore the set-equality line, or the two-dot AC16, in a temp copy loaded by path, and see the test go red.
- Tester runs and quotes: the AC1 command, `python -m pytest -q`, the AC3 build plus eval-crop, the AC4 and AC7 git diff commands with `git ls-files '*.mp4'`, the AC5 eval on both main (Step 0 value) and the branch, and `git diff --numstat $(git merge-base main HEAD) -- . ':!docs/superpowers'` summed for AC12.

## Deviations

- Base: main had moved from dc06807 to 0b89c5a (T-028) when the work started. `git diff --numstat HEAD 6e2935e` still printed exactly 23/0, 15/0, 23/0, 45/0 and 10/1 for the five shared files, so Step 1 ported them from 6e2935e as planned. The README append is still 29/0 against the merge base. The Step 4 'Updated by T-044' line in the T-042 design spec names the real base 0b89c5a instead of dc06807.
- Unplanned scope-test conflict: tests/test_t014_acceptance.py::test_ac15 and tests/test_t015_acceptance.py::test_ac16 (added to main after 888573b) forbid any change to sportscut/media.py against the merge base, so AC2 (0 failed) and AC1/AC8 (probe_size in media.py) could not both hold. 'sportscut/media.py' is removed from those two forbidden sets only (1 line each, nothing else changes). This is logged in DECISIONS (pending Tech Lead review), with 'Updated by T-044' notes in the T-014 and T-015 specs. Those two test files are not on the AC4 do-not-touch list.
