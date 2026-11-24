# T-039: Make the T-004 ffmpeg-dependent tests skip cleanly when ffmpeg is absent

Request R-001. Plan: `docs/superpowers/plans/2026-11-23-t-039-make-the-t-004-ffmpeg-dependent.md`.

## Product Owner request

Tạo API POST /highlights nhận video, trả về danh sách đoạn highlight và file đã cắt

## Goal

Closes the last R-001 gap: the suite must pass or skip, never fail, when ffmpeg/ffprobe are not on PATH (T-001/T-036 assumption, deferred by the Tech Lead's 2026-11-23 T-030 dev_blocked decision). Files: tests/test_pipeline.py, tests/test_t004_acceptance.py, plus the T-004 design spec (docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md) if it describes the no-ffmpeg behaviour, and the usual task design/plan/INDEX/DECISIONS records. Do NOT change sportscut/pipeline.py or any production code. require_ffmpeg() staying first in pipeline.run is the decided contract (MediaError, not PipelineError, when the tools are missing). Change: add the existing conftest `require_ffmpeg` skip fixture to tests/test_pipeline.py::test_run_missing_file_raises_pipeline_error, to every parametrized case of tests/test_t004_acceptance.py::test_bad_inputs_are_pipeline_errors_without_output_acceptance, and to tests/test_t004_acceptance.py::test_cut_cli_failure_help_and_required_out_acceptance. Assertions must not be weakened or removed. The Tester owns test_t004_acceptance.py, so the Tester makes that edit. Acceptance criteria: (1) `python -m pytest -q` with ffmpeg present has the same pass count as main and no failures; (2) with ffmpeg and ffprobe hidden from PATH (e.g. PATH containing only the Python interpreter's bin dir), `python -m pytest -q` reports 0 failures and 0 errors, and every ffmpeg-dependent test is skipped with reason 'ffmpeg and ffprobe are required on PATH'; (3) tests/test_pipeline.py::test_run_without_ffmpeg_raises_media_error and the missing-tools part of tests/test_t004_acceptance.py::test_invalid_options_and_missing_tools_have_distinct_errors_acceptance still run and pass; (4) quote both pytest summary lines in the task report; (5) the diff is under 50 changed lines outside docs/superpowers/.

## Acceptance criteria

- AC1: With ffmpeg and ffprobe on PATH, `python -m pytest -q` reports 0 failed and 0 errors, and the same `passed` count as on main at the base commit (the 5 edited tests still run and pass; nothing new is skipped).
- AC2: With ffmpeg and ffprobe hidden (`env PATH=/nonexistent "$PY" -m pytest -q -rs`, where `$PY` is `sys.executable` and `shutil.which` returns None for both tools under that PATH), the summary line has 0 failed and 0 errors, and every SKIPPED line shows the reason `ffmpeg and ffprobe are required on PATH`.
- AC3: In the no-ffmpeg run, `tests/test_pipeline.py::test_run_missing_file_raises_pipeline_error`, all three cases of `tests/test_t004_acceptance.py::test_bad_inputs_are_pipeline_errors_without_output_acceptance` (missing, text, silent) and `tests/test_t004_acceptance.py::test_cut_cli_failure_help_and_required_out_acceptance` are reported SKIPPED with the reason `ffmpeg and ffprobe are required on PATH`. Check with `-rs` or `-v`.
- AC4: `tests/test_pipeline.py::test_run_without_ffmpeg_raises_media_error` is PASSED in both runs (with and without ffmpeg on PATH). `tests/test_t004_acceptance.py::test_invalid_options_and_missing_tools_have_distinct_errors_acceptance`, including its missing-tools MediaError block, is PASSED in the ffmpeg-present run.
- AC5: No assertion, parametrize value or helper is removed or weakened. `git diff main -- tests/` shows only the fixture parameter added to `test_run_missing_file_raises_pipeline_error` and two `@pytest.mark.usefixtures("require_ffmpeg")` lines in tests/test_t004_acceptance.py.
- AC6: `git diff --stat main -- sportscut/ tests/conftest.py agent-office/ pyproject.toml` is empty. `sportscut/pipeline.py` still calls `require_ffmpeg()` as the first statement of `run`.
- AC7: The T-004 design spec ends with an `## Updated by T-039` section stating that AC3/AC7 hold when ffmpeg/ffprobe are on PATH, that AC4 applies first without them, and that those tests skip with `ffmpeg and ffprobe are required on PATH`.
- AC8: `git diff --numstat main -- . ':!docs/superpowers'` sums to fewer than 50 changed lines.
- AC9: The task report quotes both pytest summary lines: the ffmpeg-present run and the PATH=/nonexistent run.

## Out of scope

- Any change to sportscut/pipeline.py or other production code, including moving the missing-file check before require_ffmpeg()
- Changing tests/conftest.py, the skip reason text, or adding a new fixture or marker
- Splitting test_cut_cli_failure_help_and_required_out_acceptance so its help and missing --out parts run without ffmpeg
- Adding skips to other test files (test_cli, test_api, test_t005/T-029/T-030 acceptance, and so on). If one fails without ffmpeg, report it to the Tech Lead instead.
- CI matrix or workflow changes that run the suite without ffmpeg
- Any detection or eval change (F1 is unaffected)

## Decisions

- T-039 (R-001): `require_ffmpeg()` stays the first call in `sportscut.pipeline.run`, so a missing ffmpeg/ffprobe is always MediaError, even for a missing input file. Tests that assert PipelineError for bad inputs must therefore request the conftest `require_ffmpeg` fixture and skip without the tools.
- T-039 (R-001): Rule for all tests: a test whose assertion needs ffmpeg/ffprobe, directly or through pipeline.run/media helpers, requests the `require_ffmpeg` fixture (or a fixture that depends on it). Tests of the missing-tools contract set PATH themselves and must NOT request it.
- T-039 (R-001): In modules that import `sportscut.media.require_ffmpeg` by name (tests/test_t004_acceptance.py), the fixture is attached with `@pytest.mark.usefixtures("require_ffmpeg")` so the imported function is not shadowed. Elsewhere a `require_ffmpeg` function parameter is used, as in the existing tests.
- T-039 (R-001): The no-ffmpeg check is `env PATH=/nonexistent <sys.executable> -m pytest -q -rs`, after confirming `shutil.which` returns None for both tools. The allowed outcome is 0 failed, 0 errors, and only `ffmpeg and ffprobe are required on PATH` skips (plus fastapi importorskip only if the dev extra is not installed).
- T-039 (R-001): The T-004 design spec gets an `Updated by T-039` note: AC3/AC7 apply when the tools are present, and AC4 takes precedence when they are missing.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md`
