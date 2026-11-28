# Plan T-053: Add the optional [ocr] EasyOCR number reader, SPORTSCUT_NUMBER_READER and `download-models --ocr`

Design: `docs/superpowers/specs/2026-11-28-t-053-add-the-optional-ocr-easyocr-number-design.md`.

## Implementation plan

# T-053: Add the optional [ocr] EasyOCR number reader, SPORTSCUT_NUMBER_READER and `download-models --ocr`

Request R-006 (Theo dõi cầu thủ). This is the third and last slice of T-033. The Tech Lead split T-033 into T-051, T-052 and T-053. This slice adds the OCR parts of the T-033 design (plan §2 OcrReader/get_reader/ocr_dir/ocr_available/download_ocr_models, §4 `download-models --ocr`, §5 pyproject/conftest/README). The full T-033 plan is in commit `11413ad` (`git show 11413ad:docs/superpowers/plans/2026-11-23-t-033-read-jersey-numbers-around-each-touch.md`). Its design spec is `docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md`.

## Context (main at e930c89)

- `sportscut/jersey.py` (T-051) holds the numpy-only DigitReader, `vote`, the `NumberReader` Protocol and `get_reader()`. Right now `get_reader()` always returns `DigitReader()` and never reads os.environ. Its top-level imports are `__future__`, `math`, `collections.abc`, `typing` and `numpy`.
- `sportscut/player.py` (T-052) calls `jersey.get_reader()` through the module attribute in `detect_touches`/`find_touches`, before `_analyse`. `_read_numbers` already honours `reader.max_reads` (evenly spaced crops). So an OcrReader with `max_reads = OCR_MAX_READS` needs no player change.
- `sportscut/cli.py`: `download-models` (faster-whisper) and `download-models --tts` (Piper) exist at lines 178-185 and 279-301. `player` maps ValueError to exit 2 and MediaError/OSError to exit 1.
- `voiceover.voice_dir()` sets the cache pattern `Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "sportscut" / ...`.
- `tests/conftest.py` is frozen for the whole project (T-015 decision; several scope tests fail on any change to it). The autouse reader fixture therefore goes in a new **repo-root `conftest.py`**. pytest loads it for every test because rootdir is the repo root. The blocked T-033 attempt checked this.
- Some pre-existing tests pin the slice boundary 'no OCR yet'. This slice has to supersede them, so they get the minimal edits listed in §6:
  - `tests/test_jersey.py::test_get_reader_ignores_env`, `::test_constants_and_protocol` and `::test_jersey_imports_numpy_only`;
  - `tests/test_t033a_acceptance.py::test_ac4_constants_protocol_and_no_ocr`, `::test_ac4_get_reader_ignores_env` and `::test_ac5_top_level_imports_numpy_only`;
  - `tests/test_t033b_acceptance.py::test_ac11_readme_section`, line 174, which forbids `SPORTSCUT_NUMBER_READER`, `easyocr`, `[ocr]` and `download-models --ocr` in the README section.
- `tests/test_t033a_acceptance.py::test_ac9_t033_spec_appendix` requires the T-033 design spec to have no `\n## ` after `## Updated by T-051`. `tests/test_t033b_acceptance.py::test_ac12_spec_endings` requires the last blank-line-separated paragraph of that spec to start with `Updated by T-052:` and contain `TRACK_MERGE` and `T-053`. So the T-053 note is one line appended with a single `\n` directly after the current last line: no blank line before it and no heading.

## Design

### 1. `sportscut/jersey.py`

New top-level imports: `import importlib.util`, `import os`, `from pathlib import Path`. `easyocr` is imported only inside `OcrReader._load` and `download_ocr_models`, never at module level. Add these constants after DIGIT_MIN_SCORE and before DIGIT_FONT:

```python
OCR_SCALE = 4            # crop upscale factor before OCR (fixed)
OCR_MAX_READS = 4        # OCR reads per touch, evenly spaced over the tracked crops (tunable 2..8)
OCR_MODEL_FILES = ("craft_mlt_25k.pth", "english_g2.pth")
READER_ENV = "SPORTSCUT_NUMBER_READER"
OCR_HINT = "pip install 'sportscut[ocr]' && sportscut download-models --ocr"
```

Add these functions and the class after `vote`:

```python
def ocr_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "sportscut" / "easyocr"

def ocr_available() -> bool:
    """easyocr importable (find_spec, no import) and every OCR_MODEL_FILES file present in ocr_dir()."""
    return importlib.util.find_spec("easyocr") is not None and all((ocr_dir() / f).is_file() for f in OCR_MODEL_FILES)

class OcrReader:
    name = "ocr"
    max_reads: int | None = OCR_MAX_READS
    def __init__(self) -> None: self._reader = None   # nothing loaded at construction
    def read(self, crop: np.ndarray) -> tuple[int | None, float]: ...

def download_ocr_models() -> Path: ...
def get_reader() -> NumberReader: ...
```

**OcrReader.read(crop)**
1. On the first call only (when `self._reader is None`), run `import easyocr` and `self._reader = easyocr.Reader(["en"], gpu=False, model_storage_directory=str(ocr_dir()), download_enabled=False, verbose=False)`. Later calls reuse it.
2. `image = np.repeat(np.repeat(crop, OCR_SCALE, axis=0), OCR_SCALE, axis=1)`.
3. `results = self._reader.readtext(image, allowlist="0123456789", detail=1)`.
4. A result `(box, text, conf)` is a candidate when `re.fullmatch(r"[1-9][0-9]?", str(text))`: digits only, 1..99, no leading zero. `re` is stdlib; add `import re` at the top (allowed in §6).
5. Return the candidate with the highest conf (ties go to the earlier one) as `(int(text), round(min(1.0, max(0.0, float(conf))), 4))`. With no candidate, return `(None, 0.0)`.

**download_ocr_models()**
1. `import easyocr`, letting ImportError propagate.
2. `d = ocr_dir(); d.mkdir(parents=True, exist_ok=True)`.
3. `easyocr.Reader(["en"], gpu=False, model_storage_directory=str(d), download_enabled=True, verbose=False)`.
4. Return `d`.

**get_reader()**
- Read `value = os.environ.get(READER_ENV, "")`. The match is exact: no strip and no lower-casing.
- `""` or `"auto"`: `_cached_ocr()` if `ocr_available()`, else `DigitReader()`.
- `"digits"`: `DigitReader()`.
- `"ocr"`: `_cached_ocr()` if `ocr_available()`, else `raise ValueError(f"{READER_ENV}=ocr needs the [ocr] extra and its models: {OCR_HINT}")`.
- Anything else: `raise ValueError("SPORTSCUT_NUMBER_READER must be auto, digits or ocr")`.
- `_ocr_reader: OcrReader | None = None` is a module global. `_cached_ocr()` creates it once and returns the same instance from then on, so the model loads once per process. Tests reset it with `monkeypatch.setattr(jersey, "_ocr_reader", None)`.
- Replace the docstring with: `"""The number reader chosen by SPORTSCUT_NUMBER_READER (auto | digits | ocr)."""`.

Update the module docstring to mention the optional OCR backend. DigitReader, vote, the Protocol and all T-051 constants stay byte-identical.

### 2. `sportscut/cli.py` (insert-only: 0 deleted lines)

- Add the import `from sportscut import jersey` next to the other `from sportscut import ...` lines.
- After the `--tts` argument, add `download_parser.add_argument("--ocr", action="store_true", help="download the EasyOCR models used to read jersey numbers instead")`.
- After the `--meta-backend needs --meta` check, add: `if args.command == "download-models" and args.ocr and args.tts: download_parser.error("--ocr and --tts cannot be combined")`. argparse makes this exit 2.
- Insert this block before `if args.command == "download-models" and args.tts:`:
```python
    if args.command == "download-models" and args.ocr:
        try:
            path = jersey.download_ocr_models()
        except ImportError:
            print("sportscut download-models: error: needs the [ocr] extra: pip install 'sportscut[ocr]'", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"sportscut download-models: error: {exc}", file=sys.stderr)
            return 1
        print(f"downloaded EasyOCR models to {path}")
        return 0
```
- The plain and `--tts` paths, the top-level `download-models` help and every other command stay unchanged. Call `jersey.download_ocr_models` through the module attribute so tests can patch it.

### 3. `pyproject.toml`

Add exactly one line, `ocr = ["easyocr>=1.7"]`, after `tts = ["piper-tts>=1.3"]`. `dependencies`, every other extra and `dev` stay unchanged.

### 4. Repo-root `conftest.py` (new)

```python
"""Repo-wide test setup: the suite always uses the numpy digits number reader (T-033)."""
import pytest


@pytest.fixture(autouse=True)
def _digits_number_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPORTSCUT_NUMBER_READER", "digits")
```

This makes the suite behave the same with or without the extra. Tests of auto/ocr override the variable with setenv/delenv. `tests/conftest.py` is not touched.

### 5. `README.md` (insert-only, inside `## Số áo cầu thủ (T-033)`)

- **New Vietnamese paragraph(s) and a bash block.** Put them after the `Giới hạn đã biết: ...` paragraph and before `Các hằng số ...`. They contain:
  - the two backends: `digits` (numpy, built in) and `ocr` (EasyOCR, optional);
  - `pip install 'sportscut[ocr]'` and `sportscut download-models --ocr`, in a ```bash block;
  - `SPORTSCUT_NUMBER_READER` with `auto` (the default: OCR when the extra and the models are present, otherwise digits), `digits` and `ocr` (an error with the install hint when it is missing);
  - a note that the models go to `~/.cache/sportscut/easyocr` (or `$XDG_CACHE_HOME`), are never downloaded while the tool runs, and are not committed to git.
- **Two new lines** in the existing ```text block, after `DIGIT_MIN_SCORE = 0.6 ...`:
  - `OCR_SCALE = 4         # hệ số phóng to khung cắt trước khi OCR`
  - `OCR_MAX_READS = 4     # số lần OCR tối đa mỗi pha chạm`
- **Nothing else changes.** The `Trước T-033:`/`Sau T-033:` JSON blocks stay as they are, and the heading order stays the same.

### 6. Allowed edits to pre-existing tests

Only these edits are allowed. Test names stay the same, and no test is deleted, skipped or marked xfail.

- **`tests/test_jersey.py::test_get_reader_ignores_env`** (parametrize `[None, "ocr", "tesseract"]` unchanged)
  - Add `monkeypatch.setattr(jersey, "ocr_available", lambda: False)`.
  - None: still `isinstance(get_reader(), jersey.DigitReader)`.
  - 'ocr': `pytest.raises(ValueError, match="download-models --ocr")`.
  - 'tesseract': `pytest.raises(ValueError, match="must be auto, digits or ocr")`.
- **`tests/test_jersey.py::test_constants_and_protocol`**: lines 90-93 become `for name in ("OcrReader", "ocr_available", "download_ocr_models", "READER_ENV"): assert hasattr(jersey, name)`. The `"easyocr" not in source and "environ" not in source` assert is removed. The fresh-import check covers the same risk.
- **`tests/test_jersey.py::test_jersey_imports_numpy_only`**: the allowed root set becomes `{"math", "os", "re", "importlib.util", "pathlib", "collections.abc", "typing", "numpy", "__future__"}`. The subprocess sys.modules check is unchanged.
- **`tests/test_t033a_acceptance.py::test_ac4_constants_protocol_and_no_ocr`**: line 101 becomes `assert all(hasattr(jersey, n) for n in (...same four...))`. Line 103 is removed.
- **`tests/test_t033a_acceptance.py::test_ac4_get_reader_ignores_env`** (params `[None, "ocr", "tesseract", "digits"]` unchanged)
  - Add `monkeypatch.setattr(jersey, "ocr_available", lambda: False)`.
  - None and 'digits': keep both original asserts.
  - 'ocr' and 'tesseract': `pytest.raises(ValueError)` with the messages above.
- **`tests/test_t033a_acceptance.py::test_ac5_top_level_imports_numpy_only`**: the same allowed root set as above.
- **`tests/test_t033b_acceptance.py::test_ac11_readme_section`**: line 174 (`for bad in ...: assert bad not in s`) becomes `for need in ("SPORTSCUT_NUMBER_READER", "pip install 'sportscut[ocr]'", "download-models --ocr"): assert need in s`.

### 7. Spec note

Append one line to `docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md`, directly after its current last line. Join it with a single newline: no blank line before it and no `## ` heading. The line starts with `Updated by T-053:` and names:
- `OcrReader`, `SPORTSCUT_NUMBER_READER` (auto/digits/ocr) and `download-models --ocr`;
- the `[ocr]` extra;
- the move of the autouse digits fixture from tests/conftest.py (frozen) to the repo-root `conftest.py`;
- the AC14 OCR timing line.

The rest of the file is unchanged.

## Files

| File | Change |
|---|---|
| sportscut/jersey.py | ≈ +70 lines |
| sportscut/cli.py | ≈ +16, insert-only |
| pyproject.toml | +1 |
| conftest.py | new, ≈ 8 lines |
| README.md | ≈ +15, insert-only |
| tests/test_jersey.py | §6 edits |
| tests/test_t033a_acceptance.py | §6 edits |
| tests/test_t033b_acceptance.py | §6 edit |
| tests/test_jersey_ocr.py | new, Developer, ≤ 190 lines |
| tests/test_t033c_acceptance.py | new, Tester, ≤ 190 lines |
| docs/superpowers/specs/2026-11-23-t-033-...-design.md | one appended line |

The budget is < 600 changed lines outside docs/superpowers, new test files included.

## Fake easyocr fixture (used by the Developer and Tester tests)

Write `tmp_path/"fake"/"easyocr.py"` with:
- `CALLS = []`, `RESULTS = []` and `IMAGES = []`;
- `class Reader` whose `__init__(self, *args, **kwargs)` appends `(args, kwargs)` to CALLS, and whose `readtext(self, image, **kw)` appends `(image, kw)` to IMAGES and returns `list(RESULTS)`.

The fixture runs, in order:
1. `monkeypatch.delitem(sys.modules, "easyocr", raising=False)`, then `monkeypatch.syspath_prepend(str(tmp_path/"fake"))`;
2. `monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path/"cache"))`;
3. `monkeypatch.setattr(jersey, "_ocr_reader", None)`;
4. it yields the imported fake module and pops `easyocr` from sys.modules on teardown.

To get 'easyocr not importable' deterministically, even when the real package is installed, use `monkeypatch.setitem(sys.modules, "easyocr", None)`. Then `importlib.util.find_spec` returns None and `import easyocr` raises ImportError. For 'models present', create both OCR_MODEL_FILES as empty files in `jersey.ocr_dir()`.

## Steps (test-first; run `python -m pytest -q <file>` after each)

0. Build the eval set and record the base digits report:
   - `python tests/fixtures/eval_player/build.py && SPORTSCUT_NUMBER_READER=digits python -m sportscut eval-player tests/fixtures/eval_player --json`
   - `python -m sportscut eval tests/fixtures/eval --json`
   - Save both JSON lines.
1. Write the fake-easyocr fixture and OcrReader tests in tests/test_jersey_ocr.py (AC1) and watch them fail with AttributeError. Then add the constants and OcrReader.
2. Write the ocr_dir/ocr_available/get_reader tests (AC2) and the import-isolation test (AC5). They fail. Then implement ocr_dir, ocr_available, the `_ocr_reader` cache and get_reader. Make the §6 edits to test_jersey.py and test_t033a_acceptance.py in this step. Check that each edited test failed on the new code before its edit and passes after.
3. Write the download_ocr_models and CLI tests (AC3). They fail. Then implement download_ocr_models and the cli.py insertions.
4. Add the pyproject extra and the repo-root conftest.py (AC4, AC6).
5. Add the AC7 timing test (skipped unless `jersey.ocr_available()`).
6. Write the README insertions (AC8). Make the §6 edit to test_t033b_acceptance.py line 174, confirming that the old line fails on the new README and the new line passes.
7. Append the spec line (AC9). Then run the full suite and every command below.

## Commands that prove it

- `python -m pytest -q` reports 0 failed.
- `python tests/fixtures/eval_player/build.py && SPORTSCUT_NUMBER_READER=digits python -m sportscut eval-player tests/fixtures/eval_player --json` gives f1 0.9474, precision 0.973, recall 0.9231, id_accuracy 0.973 and touch_f1_any 0.9737, the same as the README 'Sau T-033' report and Step 0, with seconds_per_min ≤ 6.0.
- `python -m sportscut eval tests/fixtures/eval --json`: f1 equals Step 0.
- `python -m sportscut download-models --ocr --tts; echo $?` prints `2`.
- Without easyocr installed:
  - `python -m sportscut download-models --ocr` exits 1 with `sportscut download-models: error: needs the [ocr] extra: pip install 'sportscut[ocr]'`.
  - `SPORTSCUT_NUMBER_READER=ocr python -m sportscut player tests/fixtures/eval_player/number_hidden/clip.mp4 --team blue --number 8 --out /tmp/t053_reel` exits 2, and its stderr contains `pip install 'sportscut[ocr]'`.
- `SPORTSCUT_NUMBER_READER=tesseract python -m sportscut player tests/fixtures/eval_player/number_hidden/clip.mp4 --team blue --number 8 --out /tmp/t053_reel2` exits 2 with `sportscut player: error: SPORTSCUT_NUMBER_READER must be auto, digits or ocr`.
- `python -c "import sys, sportscut.player; print('easyocr' in sys.modules)"` prints `False`.
- `git ls-files '*.pth'` prints nothing.
- If `python -c 'from sportscut import jersey; print(jersey.ocr_available())'` prints True, run `SPORTSCUT_NUMBER_READER=ocr python -m sportscut eval-player tests/fixtures/eval_player --json` and quote it in the PR. Otherwise the PR says `OCR timing not measured: [ocr] extra not installed`.

## Assumptions

- easyocr ≥ 1.7 stores its English models as `craft_mlt_25k.pth` and `english_g2.pth` directly in `model_storage_directory`. It also creates its own `~/.EasyOCR/user_network` directory; that is acceptable and not pinned.
- easyocr accepts an RGB uint8 numpy array. Colour order does not matter for reading digits.
- `ocr_available()` checks only that easyocr is importable (find_spec, no import) and that the model files exist. It does not check that torch imports. A broken torch install surfaces as the original ImportError on the first OCR read and is not translated.
- The values of SPORTSCUT_NUMBER_READER are case-sensitive and not stripped.
- The dev and CI environments do not install easyocr. All OCR unit tests use the fake module, and the timing test is skipped.
- The OCR f1 on the synthetic font is reported, not gated (T-033 decision). Real-kit accuracy is unknown until `data/eval_player/` exists.

## Test plan

- Step 0 (Developer, before edits): build the eval-player set and record the digits eval-player JSON and the eval JSON.
- tests/test_jersey_ocr.py (Developer, unit): a `fake_easyocr` fixture as described in the spec (tmp easyocr.py, syspath_prepend, XDG_CACHE_HOME=tmp, jersey._ocr_reader reset, sys.modules cleanup), plus a `models` helper that touches both OCR_MODEL_FILES in ocr_dir().
- tests/test_jersey_ocr.py: test_ocr_reader_lazy_load_once, test_ocr_reader_scales_crop_and_allowlist, test_ocr_reader_parses_results (the 5-result list → (7, .95), [] → (None, 0.0), 1.3 clipped, tie → earlier), test_ocr_reader_identity_constants (AC1).
- tests/test_jersey_ocr.py: test_ocr_dir_uses_xdg, test_ocr_available_needs_module_and_both_models (sys.modules['easyocr']=None / one file / both files), test_get_reader_env_matrix (parametrized over unset, '', 'auto', 'digits', 'ocr', 'tesseract', 'OCR' × available/unavailable), test_get_reader_caches_ocr_instance (AC2).
- tests/test_jersey_ocr.py: test_download_ocr_models_with_fake, test_cli_download_ocr_ok (patched download_ocr_models; subtitles/voiceover patched to pytest.fail), test_cli_download_ocr_missing_extra (sys.modules['easyocr']=None), test_cli_download_ocr_failure (RuntimeError('offline')), test_cli_download_ocr_and_tts_exit_2 (AC3).
- tests/test_jersey_ocr.py: test_imports_never_load_easyocr (a fresh subprocess imports sportscut.jersey and sportscut.player), test_pyproject_ocr_extra, test_root_conftest_forces_digits (AC4, AC5, AC6).
- tests/test_jersey_ocr.py: test_ocr_timing_budget, skipif not jersey.ocr_available(). It builds the set in tmp, sets env ocr, runs evaluate_dir, prints JSON and asserts seconds_per_min ≤ 6.0 (AC7).
- Pre-existing test edits (Developer, spec §6), each confirmed failing on the new code before the edit and passing after:
- tests/test_jersey.py::test_get_reader_ignores_env, ::test_constants_and_protocol, ::test_jersey_imports_numpy_only;
- tests/test_t033a_acceptance.py::test_ac4_constants_protocol_and_no_ocr, ::test_ac4_get_reader_ignores_env, ::test_ac5_top_level_imports_numpy_only;
- tests/test_t033b_acceptance.py::test_ac11_readme_section line 174.
- tests/test_t033c_acceptance.py (Tester, written independently from the ACs with its own fake easyocr module):
- AC1-AC3 and AC5 with the fake module and sys.modules['easyocr']=None;
- AC4 by parsing pyproject.toml with tomllib;
- AC6 by reading os.environ inside a test;
- AC7 as a skipif timing test;
- AC8: the README section text, OCR_SCALE/OCR_MAX_READS in the text block against the module values, neighbour headings;
- AC9: the spec last line starts with 'Updated by T-053:' and names the required words, and the last \n\n paragraph still starts with 'Updated by T-052:';
- AC11 via subprocess `python -m sportscut player` with env tesseract/ocr on a tiny ffmpeg-built clip (require_ffmpeg).
- Tester can-fail checks: it confirms that its AC1/AC2 tests fail when OcrReader loads the model in __init__, when get_reader ignores the env, or when the OCR instance is not cached. It confirms that the AC3 test fails when the --ocr/--tts check is removed. It records these in the report and does not commit them.
- Git-diff scope checks (AC10 numbers, AC12 byte-identity, insert-only, size, *.pth) run as commands in review and are quoted in the Developer and Tester reports. They are not pytest git-diff tests (T-028/T-049/T-051/T-052 rule).
- Full run: `python -m pytest -q` (0 failed, summary quoted), then every command in the spec 'Commands that prove it' section, with the eval-player and eval JSON quoted in the PR together with the OCR timing line.
