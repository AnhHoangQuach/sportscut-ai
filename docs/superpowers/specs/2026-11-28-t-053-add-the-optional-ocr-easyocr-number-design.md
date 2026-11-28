# T-053: Add the optional [ocr] EasyOCR number reader, SPORTSCUT_NUMBER_READER and `download-models --ocr`

Request R-006. Plan: `docs/superpowers/plans/2026-11-28-t-053-add-the-optional-ocr-easyocr-number.md`.

## Product Owner request

Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó.

## Goal

Third slice of T-033 (R-006). Implement the OCR parts of T-033 design spec §2, §4 and §5. In jersey.py add OCR_SCALE, OCR_MAX_READS, OCR_MODEL_FILES, READER_ENV, OCR_HINT, ocr_dir(), ocr_available(), OcrReader (lazy model load once per instance, download_enabled=False, digit allowlist, 1..99 without a leading zero), download_ocr_models(), and the full get_reader() env handling: auto/''/unset picks OCR when available, 'digits', 'ocr' fails with the hint when unavailable, anything else raises 'must be auto, digits or ocr', and the OcrReader is cached per process. In cli.py add `download-models --ocr`: it cannot be combined with --tts (exit 2), prints a success line, exits 1 on ImportError and other errors, and leaves the --tts and plain paths unchanged. pyproject gets only `ocr = ["easyocr>=1.7"]`. The autouse fixture setting SPORTSCUT_NUMBER_READER=digits goes in the repo-root conftest.py (tests/conftest.py is frozen). Append to the README T-033 section (insert-only): the two backends, pip install 'sportscut[ocr]', sportscut download-models --ocr, SPORTSCUT_NUMBER_READER, models not committed, and OCR_SCALE/OCR_MAX_READS in the text block. Acceptance: T-033 AC4, AC5 and AC6 using a fake easyocr.py on sys.path; AC14 (an OCR timing test skipped when ocr_available() is False; the PR quotes the JSON or 'OCR timing not measured: [ocr] extra not installed'); importing jersey/player never imports easyocr; `git ls-files '*.pth'` is empty; eval-player with digits is unchanged from the previous slice. Files: sportscut/jersey.py, sportscut/cli.py, pyproject.toml, conftest.py, README.md, tests/test_jersey_ocr.py, tests/test_t033c_acceptance.py, docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md. Budget: <600 changed lines outside docs/superpowers.

## Acceptance criteria

- AC1 (T-033 AC4) OcrReader with the fake easyocr module:
- `jersey.OcrReader()` creates no easyocr.Reader (fake CALLS stays empty).
- The first `read` creates exactly one Reader with args `(['en'],)` and kwargs `{'gpu': False, 'model_storage_directory': str(jersey.ocr_dir()), 'download_enabled': False, 'verbose': False}`. A second and a third read on the same instance leave len(CALLS) == 1.
- `readtext` receives an image equal to `np.repeat(np.repeat(crop, 4, 0), 4, 1)` (shape (h*OCR_SCALE, w*OCR_SCALE, 3)) and kwargs `allowlist='0123456789', detail=1`.
- RESULTS `[(b,'10',.9),(b,'7',.95),(b,'abc',.99),(b,'123',.99),(b,'07',.99)]` give `(7, 0.95)`. `[]` gives `(None, 0.0)`. `[(b,'9',1.3)]` gives `(9, 1.0)`. Two candidates with equal conf return the earlier one. The number is a Python int and the conf a Python float.
- `OcrReader.name == 'ocr'`, `OcrReader().max_reads == jersey.OCR_MAX_READS == 4` and `jersey.OCR_SCALE == 4`.
- AC2 (T-033 AC5) availability and get_reader:
- With XDG_CACHE_HOME=X, `jersey.ocr_dir() == Path(X)/'sportscut'/'easyocr'`.
- `jersey.OCR_MODEL_FILES == ('craft_mlt_25k.pth', 'english_g2.pth')` and `jersey.READER_ENV == 'SPORTSCUT_NUMBER_READER'`.
- `ocr_available()` is False with sys.modules['easyocr']=None. It is False with the fake module and only one model file present, and True with the fake module and both files in ocr_dir().
- With SPORTSCUT_NUMBER_READER unset, '' or 'auto', get_reader() returns an OcrReader exactly when ocr_available() is True, and a DigitReader otherwise.
- 'digits' returns a DigitReader even when OCR is available.
- 'ocr' returns an OcrReader when available. Unavailable, it raises ValueError whose message contains "pip install 'sportscut[ocr]'" and 'download-models --ocr'.
- 'tesseract' and 'OCR' each raise ValueError with the message exactly 'SPORTSCUT_NUMBER_READER must be auto, digits or ocr'.
- Two get_reader() calls returning OCR give the same instance (`is`). After reading through both, the fake Reader was constructed once.
- AC3 (T-033 AC6) `sportscut download-models --ocr`:
- With jersey.download_ocr_models patched to return Path('/c/ocr'), `cli.main(['download-models','--ocr'])` returns 0 and stdout is `downloaded EasyOCR models to /c/ocr\n`. Neither subtitles.download_models nor voiceover.download_voice is called.
- With sys.modules['easyocr']=None (the real download_ocr_models), it returns 1 and stderr is exactly `sportscut download-models: error: needs the [ocr] extra: pip install 'sportscut[ocr]'\n`.
- With download_ocr_models raising RuntimeError('offline'), it returns 1 and stderr is `sportscut download-models: error: offline\n`.
- `cli.main(['download-models','--ocr','--tts'])` raises SystemExit with code 2 and stderr contains '--ocr and --tts cannot be combined'. Neither download function is called.
- `python -m sportscut download-models --help` lists both --ocr and --tts.
- With the fake module, `jersey.download_ocr_models()` creates ocr_dir(), constructs one Reader with `(['en'],)` and `{'gpu': False, 'model_storage_directory': str(ocr_dir()), 'download_enabled': True, 'verbose': False}`, and returns ocr_dir().
- tests/test_subtitles.py, tests/test_t022_acceptance.py and tests/test_t027_acceptance.py download-models tests pass unchanged.
- AC4 pyproject.toml parses with `optional-dependencies['ocr'] == ['easyocr>=1.7']`. `dependencies == ['numpy>=1.26']`. api, youtube, llm, asr, tts and dev are equal to main, and no dev entry contains 'easyocr'. `git diff main -- pyproject.toml` shows exactly one added line and no removed lines.
- AC5 Import isolation. A fresh subprocess running `import sys, sportscut.jersey, sportscut.player` reports 'easyocr' not in sys.modules. jersey.py's module-level imports (ast walk of tree.body) are a subset of {__future__, math, os, re, importlib.util, pathlib, collections.abc, typing, numpy}. `easyocr` appears in jersey.py only inside function bodies.
- AC6 Repo-root conftest.py exists and defines an autouse fixture that sets SPORTSCUT_NUMBER_READER=digits. A test that reads `os.environ['SPORTSCUT_NUMBER_READER']` without its own setenv sees 'digits'. `git diff main -- tests/conftest.py` is empty.
- AC7 (T-033 AC14) OCR timing:
- A test is marked `pytest.mark.skipif(not jersey.ocr_available(), reason='[ocr] extra not installed')`.
- It builds the eval-player set in tmp with build.build_all, sets SPORTSCUT_NUMBER_READER=ocr and resets jersey._ocr_reader.
- It asserts that `evaluate_dir(out)['seconds_per_min'] <= 6.0` and prints the report as JSON.
- Without the extra it reports SKIPPED, not failed. The PR body quotes the JSON or the line `OCR timing not measured: [ocr] extra not installed`.
- AC8 README.md has 0 deleted lines vs main. `## Số áo cầu thủ (T-033)` keeps its neighbours (`## Theo dõi cầu thủ: xuất video tổng hợp (player)` before it, `## Đội theo màu áo (T-032)` after it). The section contains:
- 'SPORTSCUT_NUMBER_READER', 'auto', 'digits', 'ocr', "pip install 'sportscut[ocr]'", 'sportscut download-models --ocr', 'EasyOCR' and 'git';
- in its ```text block, `OCR_SCALE = 4` and `OCR_MAX_READS = 4` equal to jersey.OCR_SCALE and jersey.OCR_MAX_READS, plus all the constants test_t033b_acceptance::test_ac11_readme_section already checks;
- the unchanged 'Trước T-033:' and 'Sau T-033:' JSON.
- AC9 The T-033 design spec gains exactly one line, added after its previous last line with a single newline (no blank line). The line starts with 'Updated by T-053:' and contains 'OcrReader', 'SPORTSCUT_NUMBER_READER', 'download-models --ocr', '[ocr]' and 'conftest.py'. `git diff main` of that file has 0 removed lines. test_t033a_acceptance::test_ac9_t033_spec_appendix and test_t033b_acceptance::test_ac12_spec_endings pass unchanged.
- AC10 No regression with digits. `SPORTSCUT_NUMBER_READER=digits python -m sportscut eval-player tests/fixtures/eval_player --json` (after build.py) gives f1 == 0.9474, precision == 0.973, recall == 0.9231, id_accuracy == 0.973, touch_f1_any == 0.9737 and seconds_per_min ≤ 6.0. `python -m sportscut eval tests/fixtures/eval --json` f1 equals the Step 0 value.
- AC11 CLI errors through the existing player path:
- SPORTSCUT_NUMBER_READER=tesseract makes `python -m sportscut player CLIP --team blue --number 8 --out D` exit 2 with stderr `sportscut player: error: SPORTSCUT_NUMBER_READER must be auto, digits or ocr`.
- SPORTSCUT_NUMBER_READER=ocr with ocr unavailable makes it exit 2 with stderr containing "pip install 'sportscut[ocr]'".
- In both cases D is not created or contains no .mp4.
- AC12 Regression and scope:
- `python -m pytest -q` reports 0 failed.
- Pre-existing tests change only in the seven functions listed in spec §6, as described there. No test is deleted, renamed, skipped or marked xfail.
- `git diff main -- sportscut/player.py sportscut/media.py sportscut/eval_player.py tests/conftest.py tests/fixtures` is empty.
- In jersey.py, DigitReader, vote, _drop_border_ink, _resample, _correlation, _template, NumberReader, DIGIT_FONT and the five T-051 constants are byte-identical to main.
- `git diff main --numstat -- sportscut/cli.py README.md pyproject.toml` shows 0 deleted lines.
- `git ls-files '*.pth' '*.mp4'` is empty.
- Changed lines outside docs/superpowers total < 600, new test files included.

## Out of scope

- Any change to sportscut/player.py, media.py, eval_player.py, reel.py, api.py or the synthetic eval-player fixtures/build.py
- Tuning DigitReader or player constants, or gating OCR f1 (it is reported only)
- Exposing the reader choice in the HTTP API, web page, POST /players or as a CLI flag (only the env var)
- Adding easyocr to the dev extra or to CI, or running the real OCR model in the default test suite
- GPU support, other OCR engines (tesseract, paddle), training or fine-tuning, or bundling models in git/wheel
- Downloading models at run time (download_enabled stays False outside download-models --ocr)
- Translating real easyocr/torch runtime import errors raised during OCR reads into friendly messages
- Case-insensitive or whitespace-tolerant SPORTSCUT_NUMBER_READER values
- Editing tests/conftest.py, or rewriting the stale 'bộ đọc chữ số numpy' README sentence (README is insert-only)
- Labelling real matches; data/eval_player/ stays PO-provided and git-ignored

## Decisions

- T-053 (R-006): jersey.py gains OCR_SCALE=4 (fixed), OCR_MAX_READS=4 (tunable 2..8, not tuned here), OCR_MODEL_FILES=('craft_mlt_25k.pth','english_g2.pth'), READER_ENV='SPORTSCUT_NUMBER_READER', OCR_HINT, ocr_dir(), ocr_available(), OcrReader, download_ocr_models() and the env-driven get_reader(), exactly as in T-033 plan §2. The T-051 DigitReader, vote, Protocol and constants stay byte-identical.
- T-053 (R-006): jersey.py's module-level imports may now include the stdlib modules os, re, importlib.util and pathlib. easyocr is imported only inside OcrReader's first read and download_ocr_models, so importing sportscut.jersey or sportscut.player never loads easyocr. This replaces the T-051 'numpy-only imports, no os/environ' rule.
- T-053 (R-006): ocr_available() = importlib.util.find_spec('easyocr') is not None and both OCR_MODEL_FILES are files in ocr_dir(); ocr_dir() = ($XDG_CACHE_HOME or ~/.cache)/sportscut/easyocr, the voiceover.voice_dir pattern. It does not import easyocr or check torch.
- T-053 (R-006): SPORTSCUT_NUMBER_READER values are exact and case-sensitive. Unset, '' and 'auto' give OCR when available, else digits. 'digits' gives DigitReader. 'ocr' gives OCR or a ValueError containing OCR_HINT. Anything else raises ValueError('SPORTSCUT_NUMBER_READER must be auto, digits or ocr'). These errors reach the user through the existing player ValueError → exit 2 path and the eval-player exit 2 path.
- T-053 (R-006): the OcrReader instance is cached in the module global jersey._ocr_reader, so the model loads once per process. The model is loaded on the first read, never at import or construction, always with download_enabled=False.
- T-053 (R-006): OcrReader accepts a result only when its text fully matches [1-9][0-9]? (1..99, no leading zero). It returns the highest-confidence candidate (ties go to the earlier one) with conf clipped to [0, 1] and rounded to 4 places, or (None, 0.0).
- T-053 (R-006): `download-models --ocr` is an insert-only cli.py change. It is checked before --tts, `--ocr --tts` is a parser error (exit 2), ImportError gives the fixed [ocr] hint with exit 1, and any other exception gives exit 1 with its message. The plain and --tts paths are unchanged. The CLI calls jersey.download_ocr_models through the module attribute.
- T-053 (R-006): the autouse SPORTSCUT_NUMBER_READER=digits fixture lives in a new repo-root conftest.py, not tests/conftest.py, because tests/conftest.py is frozen project-wide (T-015). This changes the T-033 design decision 'tests/conftest.py forces digits', and the T-033 spec note records it.
- T-053 (R-006): seven pre-existing test functions pinned the T-051/T-052 slice boundary ('no OCR yet'): test_jersey.py::test_get_reader_ignores_env, ::test_constants_and_protocol, ::test_jersey_imports_numpy_only; test_t033a_acceptance.py::test_ac4_constants_protocol_and_no_ocr, ::test_ac4_get_reader_ignores_env, ::test_ac5_top_level_imports_numpy_only; and test_t033b_acceptance.py::test_ac11_readme_section line 174. They are edited exactly as in the T-053 spec §6 (names kept; ocr_available patched to False where auto must give digits; the 'must not exist' asserts become 'must exist'; the README 'bad' words become required). No other pre-existing test changes.
- T-053 (R-006): the T-033 design spec gets one trailing line 'Updated by T-053: ...', joined with a single newline after the T-052 review-round line and with no '## ' heading. This keeps test_t033a::test_ac9 and test_t033b::test_ac12 valid without editing them.
- T-053 (R-006): README changes are insert-only inside '## Số áo cầu thủ (T-033)'. The OCR paragraph(s) and bash block go after the 'Giới hạn đã biết' paragraph and before 'Các hằng số'. OCR_SCALE and OCR_MAX_READS are added to the existing text block after DIGIT_MIN_SCORE, and the JSON reports are unchanged.
- T-053 (R-006): with digits, eval-player stays at the T-052 values (f1 0.9474, precision 0.973, recall 0.9231, id_accuracy 0.973, touch_f1_any 0.9737). OCR f1 is not gated. OCR timing (seconds_per_min ≤ 6.0) is enforced only by a skip-if-unavailable test, and the PR quotes its JSON or 'OCR timing not measured: [ocr] extra not installed'.
- T-053 (R-006): the budget is < 600 changed lines outside docs/superpowers, new test files included (Developer tests ≤ 190, Tester tests ≤ 190). Scope, size, byte-identity and insert-only rules are checked by commands in review, not by pytest git-diff tests.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md`
- `docs/superpowers/specs/2026-11-28-t-051-add-media-sample-window-and-the-design.md`
- `docs/superpowers/specs/2026-11-28-t-052-follow-the-toucher-around-each-touch-design.md`
