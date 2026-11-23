# Plan T-035: Scaffold SportsCut packaging, version CLI, and Segment model

Design: `docs/superpowers/specs/2026-11-23-t-035-scaffold-sportscut-packaging-version-cli-and-design.md`.

## Implementation plan

# T-035: SportsCut packaging, version CLI, and Segment model

## Context

This is the replacement foundation slice created after T-001 was split for size and test-history reasons. The repository currently has no root `pyproject.toml`, `sportscut/`, or root `tests/`; `agent-office/` is a separate protected project and must not be changed. T-036 will add ffmpeg helpers and synthetic fixtures after this task.

The task establishes an installable Python 3.11+ package, prevents root pytest from collecting `agent-office/tests`, exposes version 0.1.0 through both supported entry points, and supplies the shared highlight-segment value object used by later detection, export, and API tasks.

## Files and exact design

### `pyproject.toml`

Use setuptools with this configuration:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "sportscut"
dynamic = ["version"]
description = "Find highlights in sports videos and export clips"
requires-python = ">=3.11"
dependencies = ["numpy>=1.26"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
sportscut = "sportscut.cli:main"

[tool.setuptools.dynamic]
version = {attr = "sportscut.__version__"}

[tool.setuptools.packages.find]
include = ["sportscut*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

`numpy` is declared here because T-036 depends on this foundation and will use it for audio arrays. Do not add an empty API extra or any undeclared future dependencies.

### `sportscut/__init__.py`

Expose the single version source:

```python
__version__ = "0.1.0"
```

### `sportscut/__main__.py`

Import `main` from `sportscut.cli` and terminate with `raise SystemExit(main())`. This makes `python -m sportscut` behave like the installed console script.

### `sportscut/cli.py`

Provide:

```python
def main(argv: list[str] | None = None) -> int:
```

Build an `argparse.ArgumentParser` with `prog="sportscut"` and a short SportsCut description. Add `--version` using argparse's `action="version"` and `version=f"sportscut {__version__}"`. `main(["--version"])` prints exactly `sportscut 0.1.0\n` and raises `SystemExit(0)`. With no arguments, print help to stdout and return 0. Do not add subcommands in this task.

### `sportscut/models.py`

Provide:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    score: float
    reason: str

    def to_dict(self) -> dict[str, float | str]: ...
```

`start` and `end` are seconds from the beginning of the video. In `__post_init__`, raise `ValueError` when `start < 0` or `end <= start`. Do not impose a score range because later detectors may use unbounded normalized scores.

`to_dict()` returns exactly these keys in this order: `start`, `end`, `score`, `reason`. Convert numeric values with `float()` and the reason with `str()` so the result contains native JSON-safe primitives even when callers supply NumPy scalar values. The dataclass remains frozen.

### Tests

`tests/test_cli.py` directly exercises `main`, help behavior, and a subprocess invocation of `python -m sportscut`. `tests/test_models.py` covers dictionary shape/order, native primitive conversion and JSON serialization with NumPy scalars, immutability, and invalid temporal bounds. Do not create `tests/__init__.py` or shared fixtures.

### Persistent records

Add only the generated T-035 design and plan, one T-035 row in `docs/superpowers/INDEX.md`, and the T-035 decisions in `docs/superpowers/DECISIONS.md`. Preserve all existing content. Do not recreate `.gitattributes`, the docs directory, index headings, or any persistent-spec infrastructure already present on the base.

## Ordered implementation sequence

1. Confirm the listed product/test files do not already exist and that unrelated dirty-worktree changes are left untouched.
2. Add `pyproject.toml` with the exact package, entry-point, dependency, and pytest configuration above.
3. Write `tests/test_cli.py` before package code. Run `.venv/bin/python -m pytest -q tests/test_cli.py`; preserve a genuine failing result caused by the missing `sportscut` package in task history.
4. Add `sportscut/__init__.py`, `sportscut/cli.py`, and `sportscut/__main__.py`; rerun the CLI tests to green.
5. Write `tests/test_models.py` before `sportscut/models.py`. Run it and preserve the expected missing-module failure in task history.
6. Add the minimal frozen `Segment` implementation and rerun the model tests to green.
7. Create a worktree-local, gitignored `.venv` from the available Agent Office interpreter. Give it read-only access to that interpreter's existing site-packages through a `.pth` file, then run `.venv/bin/python -m pip install --no-build-isolation --no-index -e '.[dev]'`. Do not download packages, modify `agent-office/`, or commit `.venv`/`.pth` files.
8. Run both version commands, focused tests, root pytest, explicit `tests` pytest, and the no-ffmpeg PATH command. Root collection must include only `tests/`.
9. Inspect `git status --short`; ensure only listed files are changed, no generated media or environment files appear, and the task-specific documentation remains concise.

## Verification commands

```bash
.venv/bin/python -m pip install --no-build-isolation --no-index -e '.[dev]'
.venv/bin/sportscut --version
.venv/bin/python -m sportscut --version
.venv/bin/python -m pytest -q tests/test_cli.py tests/test_models.py
.venv/bin/python -m pytest -q
.venv/bin/python -m pytest -q tests
PATH=/nonexistent .venv/bin/python -m pytest -q
git status --short
```

Both version commands must print exactly `sportscut 0.1.0`. Every pytest command must exit 0. The no-ffmpeg run must have zero failures and zero errors; this slice has no ffmpeg-dependent tests, so no skips are required. This task does not touch detection accuracy and `sportscut eval` does not exist yet, so there is no F1 command or minimum score for T-035.

## Assumptions

- Python 3.11 or newer is available, matching repository and Agent Office requirements.
- The worktree setup provides existing setuptools, pip, pytest, and NumPy packages for the offline editable-install procedure.
- Version 0.1.0 is sourced only from `sportscut.__version__`; packaging reads it dynamically.
- Segment intervals are half-open/continuous-time data for later consumers, but this task only enforces non-negative start and strictly increasing end.
- A score is intentionally any float-compatible value; normalization belongs to later detection logic.
- No ffmpeg executable is required by this foundation slice.

## Test plan

- Unit — `tests/test_cli.py::test_version_flag_prints_version`: call `main(['--version'])`, assert `SystemExit(0)`, exact stdout `sportscut 0.1.0\n`, and empty stderr.
- Unit — `tests/test_cli.py::test_no_args_prints_help_and_returns_zero`: assert `main([]) == 0`, stdout contains `usage: sportscut`, and stderr is empty.
- Integration — `tests/test_cli.py::test_module_entry_point`: run `[sys.executable, '-m', 'sportscut', '--version']` from the repository root; assert return code 0 and exact stdout/stderr.
- Unit — `tests/test_models.py::test_to_dict_shape_order_and_values`: assert exact mapping, insertion order `start,end,score,reason`, and native primitive types.
- Unit — `tests/test_models.py::test_to_dict_is_json_safe_for_numpy_scalars`: construct with `numpy.float32` values, call `json.dumps`, and assert all numeric dictionary values have exact type `float`.
- Unit — `tests/test_models.py::test_segment_is_frozen`: assigning a field raises `dataclasses.FrozenInstanceError`.
- Unit — `tests/test_models.py::test_invalid_time_bounds_raise`: parameterize negative start, equal endpoints, and reversed endpoints; each construction raises `ValueError`.
- Unit — `tests/test_models.py::test_score_is_not_range_limited`: representative negative and greater-than-one scores construct successfully, documenting the deliberate absence of score normalization here.
- Command/integration — after offline editable installation, run both installed-console and module version commands and compare exact output.
- Command/integration — run focused tests, root pytest, explicit `tests` pytest, and pytest under `PATH=/nonexistent`; no fixture is required and every run must have zero failures/errors.
