# Plan T-039: Make the T-004 ffmpeg-dependent tests skip cleanly when ffmpeg is absent

Design: `docs/superpowers/specs/2026-11-23-t-039-make-the-t-004-ffmpeg-dependent-design.md`.

## Implementation plan

# T-039: Make the T-004 ffmpeg-dependent tests skip cleanly when ffmpeg is absent

## Context
R-001 assumes, from T-001 and T-036, that `python -m pytest -q` never fails when ffmpeg/ffprobe are missing from PATH. A test that needs the tools must skip, using the session fixture `require_ffmpeg` in `tests/conftest.py`. Its skip reason is exactly `ffmpeg and ffprobe are required on PATH`.

T-004 (cd445e6) left 5 tests that fail when the tools are missing. The Tech Lead logged this in DECISIONS.md under T-030 dev_blocked on 2026-11-23. The cause is that `sportscut.pipeline.run` calls `require_ffmpeg()` first. This is the decided contract (T-004 decision: a missing ffmpeg is `MediaError`, which the API maps to 500, not `PipelineError`). So these tests get `MediaError: ffmpeg not found on PATH; install ffmpeg`, or `FileNotFoundError` when the test itself calls ffmpeg, before reaching the `PipelineError` they assert:

1. `tests/test_pipeline.py::test_run_missing_file_raises_pipeline_error` (no fixture; expects `PipelineError` `media file not found: <path>`).
2. `tests/test_t004_acceptance.py::test_bad_inputs_are_pipeline_errors_without_output_acceptance[missing-...]`
3. `...[text-...]`
4. `...[silent-...]` (this one also calls ffmpeg directly through `_video_only`).
5. `tests/test_t004_acceptance.py::test_cut_cli_failure_help_and_required_out_acceptance` (its subprocess inherits PATH, so stderr starts with `sportscut: error: ffmpeg not found ...` instead of `ffprobe failed for ...`).

The fix is in the tests only: each of these tests requests the existing `require_ffmpeg` fixture. No production code changes. `require_ffmpeg()` stays the first statement of `pipeline.run`.

## Design
The `require_ffmpeg` fixture is session-scoped and skips when `shutil.which('ffmpeg')` or `shutil.which('ffprobe')` is None. With the tools present it does nothing, so the test runs exactly as before and the pass count does not change.

### Change 1 (Developer): `tests/test_pipeline.py`
Add the fixture as a parameter, in the same style as the neighbouring tests at lines 40 and 48:
```python
def test_run_missing_file_raises_pipeline_error(require_ffmpeg, tmp_path):
```
The body stays unchanged. Do NOT touch `test_run_without_ffmpeg_raises_media_error`. It must keep running without the fixture, because it sets PATH itself and checks the MediaError contract.

### Change 2 (Tester owns this file): `tests/test_t004_acceptance.py`
This module imports `require_ffmpeg` from `sportscut.media` at module level, and `test_media_helpers_acceptance` calls it. Use the marker form rather than a function parameter, so the imported name is not shadowed:
```python
@pytest.mark.usefixtures("require_ffmpeg")
@pytest.mark.parametrize(
    ("kind", "message"),
    ...
)
def test_bad_inputs_are_pipeline_errors_without_output_acceptance(...):

@pytest.mark.usefixtures("require_ffmpeg")
def test_cut_cli_failure_help_and_required_out_acceptance(tmp_path: Path) -> None:
```
A `usefixtures` mark on a parametrized function applies to every case (missing, text, silent). Do not change any assertion, parametrize value, helper or other test in the file. `test_invalid_options_and_missing_tools_have_distinct_errors_acceptance` already depends on `burst_video` and stays unchanged.

### Change 3 (Developer): T-004 design spec note
Append this note to the end of `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`:
```
## Updated by T-039

AC3 and AC7 (PipelineError and CLI messages for missing, non-video and silent inputs) hold when ffmpeg and ffprobe are on PATH. Without them, AC4 applies first: `run` calls `require_ffmpeg()` before any input check and raises MediaError. The tests for AC3 and AC7 therefore request the conftest `require_ffmpeg` fixture and skip with `ffmpeg and ffprobe are required on PATH`, while the AC4 tests keep running.
```

## Files to touch
- `tests/test_pipeline.py`: Developer, 1 changed line.
- `tests/test_t004_acceptance.py`: Tester, 2 added lines.
- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`: Developer, appended note.
- `docs/superpowers/INDEX.md`, `docs/superpowers/DECISIONS.md`, and this task's design/plan files: orchestrator records, append-only.

Nothing else. In particular: no file under `sportscut/`, no `tests/conftest.py`, no other test file, nothing under `agent-office/`, and no `pyproject.toml`.

## Steps (test-first: the failing check is the no-ffmpeg run)
1. **Reproduce (red).** Run:
   ```sh
   PY="$(python -c 'import sys; print(sys.executable)')"
   env PATH=/nonexistent "$PY" -c "import shutil; print(shutil.which('ffmpeg'), shutil.which('ffprobe'))"
   ```
   It must print `None None`. Then run `env PATH=/nonexistent "$PY" -m pytest -q -rfEs` and confirm that exactly the 5 tests listed above fail. Save that summary line for the report.
2. **Developer: Change 1.** Re-run `env PATH=/nonexistent "$PY" -m pytest -q tests/test_pipeline.py -rs`. Expect 0 failures, with `test_run_missing_file_raises_pipeline_error` skipped for the ffmpeg reason and `test_run_without_ffmpeg_raises_media_error` passed.
3. **Tester: Change 2.** Re-run `env PATH=/nonexistent "$PY" -m pytest -q tests/test_t004_acceptance.py -rs`. Expect 0 failures, with the 3 parametrized cases and the CLI-failure test skipped for the ffmpeg reason.
4. **Developer: Change 3** (spec note).
5. **Green with ffmpeg present.** Run `python -m pytest -q` on the branch and on main (`git stash`/worktree or the orchestrator's base run) and compare the `N passed` counts. They must be equal, with 0 failed and 0 errors.
6. **Green without ffmpeg.** Run `env PATH=/nonexistent "$PY" -m pytest -q -rs`. Expect 0 failed and 0 errors. Every `SKIPPED` line must have the reason `ffmpeg and ffprobe are required on PATH`. The only allowed exception is the `fastapi` importorskip lines in test_api.py/test_t005_acceptance.py, and only when the dev extra is not installed.
7. Run `git diff --numstat main -- . ':!docs/superpowers'`. The total of added plus deleted lines must be < 50.
8. Quote both pytest summary lines (steps 5 and 6) in the task report.

## Contingency
If step 6 shows a failure or error outside the 5 tests above (for example a T-005 or T-030 test), do not widen scope and do not touch production code. Stop and report the test id and full error to the Tech Lead.

## Assumptions
- To hide the tools, PATH is set to `/nonexistent` and the interpreter is called by absolute path (`sys.executable`). This is the same method the Tech Lead used in the T-030 decision. The AC's 'PATH containing only the Python interpreter's bin dir' is an example. With Homebrew Python that bin dir can also contain ffmpeg, so the `None None` check in step 1 is required whichever PATH is used.
- The dev extra (fastapi, httpx) is installed in the worktree, as in normal runs, so no fastapi importorskip skips appear.
- Skipping the whole `test_cut_cli_failure_help_and_required_out_acceptance` also skips its ffmpeg-independent parts (missing `--out` exits 2, help output) when ffmpeg is absent. This is acceptable because `tests/test_cli.py::test_cut_requires_out` and `test_no_args_prints_help_and_returns_zero` already cover those without ffmpeg. Splitting the test would mean rewriting Tester-owned assertions.
- The missing-tools half of `test_invalid_options_and_missing_tools_have_distinct_errors_acceptance` runs only when ffmpeg is present, because it needs `burst_video`. Without ffmpeg, the MediaError contract is still covered by `test_run_without_ffmpeg_raises_media_error`, which runs in both environments.

## Test plan

- Before the change (red): `env PATH=/nonexistent "$PY" -m pytest -q -rfEs` shows exactly 5 failures: test_pipeline.py::test_run_missing_file_raises_pipeline_error, test_t004_acceptance.py::test_bad_inputs_are_pipeline_errors_without_output_acceptance[missing/text/silent] and test_t004_acceptance.py::test_cut_cli_failure_help_and_required_out_acceptance. Record the summary line.
- Developer: after adding `require_ffmpeg` to test_run_missing_file_raises_pipeline_error, `env PATH=/nonexistent "$PY" -m pytest -q tests/test_pipeline.py -rs` gives 0 failures, that test is skipped for the ffmpeg reason, and test_run_without_ffmpeg_raises_media_error passes.
- Tester (owns tests/test_t004_acceptance.py): add `@pytest.mark.usefixtures("require_ffmpeg")` to the two named tests. `env PATH=/nonexistent "$PY" -m pytest -q tests/test_t004_acceptance.py -rs` gives 0 failures and 4 ffmpeg-reason skips from those tests (plus the fixture-driven skips already there).
- Tester: confirm the skip can fail. Temporarily remove the new marker from the parametrized test and re-run with PATH=/nonexistent to see the 3 cases fail. Restore it before reporting.
- Full run with ffmpeg present: `python -m pytest -q`, 0 failed, and a passed count equal to main's.
- Full run without ffmpeg: `env PATH=/nonexistent "$PY" -m pytest -q -rs`, 0 failed, 0 errors, and every SKIPPED reason is `ffmpeg and ffprobe are required on PATH`.
- `git diff --numstat main -- . ':!docs/superpowers'` < 50 lines, and `git diff --stat main -- sportscut/ tests/conftest.py` is empty.
- No new fixture is needed. Reuse the session-scoped `require_ffmpeg` fixture in tests/conftest.py.
