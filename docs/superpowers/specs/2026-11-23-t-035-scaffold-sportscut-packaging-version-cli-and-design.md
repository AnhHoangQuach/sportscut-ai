# T-035: Scaffold SportsCut packaging, version CLI, and Segment model

Request R-001. Plan: `docs/superpowers/plans/2026-11-23-t-035-scaffold-sportscut-packaging-version-cli-and.md`.

## Product Owner request

Tạo API POST /highlights nhận video, trả về danh sách đoạn highlight và file đã cắt

## Goal

Create `pyproject.toml`, `sportscut/__init__.py`, `sportscut/__main__.py`, `sportscut/cli.py`, `sportscut/models.py`, `tests/test_cli.py`, and `tests/test_models.py`. Configure root pytest collection to `tests/`, expose version 0.1.0 through both CLI entry points, and implement validated JSON-safe `Segment`. Develop test-first with genuine failing CLI and model tests, then verify editable offline installation, both version commands, root pytest, and the no-ffmpeg PATH run. Add only concise required task design/plan/index/decision records; persistent infrastructure files already present on the base are not recreated.

## Acceptance criteria

- AC1: An offline editable installation using `.venv/bin/python -m pip install --no-build-isolation --no-index -e '.[dev]'` exits 0 and installs the `sportscut` console entry point without changing files under `agent-office/` or contacting a package index.
- AC2: `.venv/bin/sportscut --version` and `.venv/bin/python -m sportscut --version` each exit 0, write exactly `sportscut 0.1.0\n` to stdout, and write nothing to stderr.
- AC3: Calling `sportscut.cli.main([])` returns 0 and prints help containing `usage: sportscut`; calling `main(['--version'])` raises `SystemExit` with code 0 and prints exactly the version line.
- AC4: Root `.venv/bin/python -m pytest -q` and `.venv/bin/python -m pytest -q tests` both exit 0 and collect only tests below the root `tests/` directory, never `agent-office/tests`.
- AC5: `Segment(start=1.0, end=3.5, score=0.8, reason='crowd noise').to_dict()` equals `{'start': 1.0, 'end': 3.5, 'score': 0.8, 'reason': 'crowd noise', 'event': 'other'}` with keys in that order and native `float`, `float`, `float`, `str`, and `str` value types. (updated by T-010)
- AC6: A `Segment` constructed with NumPy floating scalars produces a `to_dict()` result accepted by `json.dumps`, and each numeric result has exact type `float`.
- AC7: `Segment` is immutable, and construction raises `ValueError` for each of `start=-1,end=2`, `start=5,end=5`, and `start=5,end=4`. No score-range validation is applied.
- AC8: `PATH=/nonexistent .venv/bin/python -m pytest -q` exits 0 with zero failures and zero errors, proving this package/model slice does not accidentally require ffmpeg or ffprobe.
- AC9: Task history contains a genuine red run for the new CLI tests before CLI implementation and a genuine red run for the new model tests before model implementation, followed by green focused runs.
- AC10: The diff changes only the files listed by this spec; `.venv`, `.pth`, `.mp4`, `.wav`, generated package metadata, protected `agent-office/` files, and persistent infrastructure recreation are absent.

## Out of scope

- `POST /highlights`, FastAPI, multipart upload handling, response schemas, file serving, and HTTP tests.
- ffmpeg/ffprobe discovery, media probing, audio extraction, synthetic video fixtures, or any generated media; these belong to T-036.
- Highlight detection, scoring, scene analysis, peak selection, clip export, manifests, or concatenated highlight reels.
- CLI subcommands such as `cut`, `detect`, or `eval`, and their options.
- Segment deserialization, custom JSON encoders, schema libraries, finite-number checks, or score normalization.
- README or product-documentation updates beyond the required concise persistent task records.
- Recreating or altering persistent-spec infrastructure such as `.gitattributes` or docs directory scaffolding.

## Decisions

- T-035 is the package/model/CLI foundation split from the oversized T-001 attempt; T-036 owns all ffmpeg media work and depends on this task.
- Use setuptools and dynamic package versioning with `sportscut.__version__` as the single source of version 0.1.0.
- Keep NumPy as a runtime dependency in the foundation because dependent T-036 requires it for audio arrays; pytest is available only through the `dev` extra.
- Configure root pytest with `testpaths = ['tests']` and `pythonpath = ['.']` so fresh worktrees import product code while excluding the separate `agent-office/tests` suite.
- The console script and `python -m sportscut` share `sportscut.cli.main`; no-argument invocation prints help and succeeds.
- `Segment` is a frozen dataclass; it validates only temporal bounds, permits unbounded scores, and converts output fields to native JSON-safe primitives in `to_dict()`.
- Genuine red-before-green evidence must be preserved separately for CLI and model behavior; existing implementation from the discarded T-001 attempt must not be copied into the branch before those failing runs.
- Offline verification uses a worktree-local gitignored virtual environment, `--no-build-isolation`, and `--no-index`; no files under the protected Agent Office project are modified.
- Only concise task-specific design, plan, index, and decision records are added; persistent infrastructure already on the base is preserved rather than recreated.
- Tech Lead (merge_failed): 2026-11-23 T-035: Wait 60 minutes before retrying PR creation because the approved branch is clean and pushed, but GitHub CLI authentication lacks valid collaborator access and network resolution is currently unavailable.
- Tech Lead (git_error): 2026-11-23 T-035: restart from the latest main instead of retrying, because the merge failure is a loop in the office, not a code problem: on every dev step `_ensure_worktree` -> `specdocs.write_task_docs` appends new Tech Lead decision lines to docs/superpowers/DECISIONS.md without committing them, right before `wt.start_merge(main)`, so `git merge main` always aborts on that dirty file (and a retry would add this decision's line too). A fresh branch from main clears the merge flag. There is nothing to resolve by hand: DECISIONS.md and INDEX.md use the union merge driver. The old office/T-035 branch is kept only as a reference.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-persistent-specs-design.md`
- `docs/superpowers/specs/2026-11-23-worktree-setup-command-design.md`
