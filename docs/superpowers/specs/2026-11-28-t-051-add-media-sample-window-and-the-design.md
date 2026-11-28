# T-051: Add media.sample_window and the jersey module with the number vote and the numpy digits reader

Request R-006. Plan: `docs/superpowers/plans/2026-11-28-t-051-add-media-sample-window-and-the.md`.

## Product Owner request

Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó.

## Goal

Library-only first slice of T-033 (R-006); no CLI or player behaviour changes. Implement exactly per the T-033 design spec §1 and §2 (digits part): media.sample_window (with the ValueError/MediaError checks done before ffmpeg runs, `-ss {start:.3f} -t {duration:.3f}` before -i, and sample_frames args unchanged, so T-033 AC7 holds); a new sportscut/jersey.py with VOTE_MIN_READS, INK_CONTRAST, INK_MIN_PIXELS, NUMBER_TOP, DIGIT_MIN_SCORE, DIGIT_FONT (== tests/fixtures/eval_player/build.py FONT), the NumberReader Protocol (name, max_reads, read), DigitReader (name 'digits', max_reads None), vote(), and get_reader() that returns DigitReader() and ignores the environment for now. No OCR code, no env var, no pyproject change. jersey.py is numpy-only and does not import sportscut.player. Tests: T-033 AC2 (vote examples), AC3 (all of 1..99 at ×1/×2/×3, dark-on-light, blanks, determinism) and AC7. Files: sportscut/media.py, sportscut/jersey.py, tests/test_jersey.py, tests/test_t033a_acceptance.py, docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md. Budget: <600 changed lines outside docs/superpowers. `python -m pytest -q` reports 0 failed, and `sportscut eval` and eval-player JSON are unchanged from main.

## Acceptance criteria

- AC1 (T-033 AC2) `jersey.vote`:
- `vote([(8,.9),(8,.8),(3,.5),(None,0.0)]) == (8, 0.5152)`;
- `vote([(10,1.0)]*5) == (10, 1.0)`;
- `vote([(7,.5),(9,.5)]) == (7, 0.1667)`;
- `vote([]) == vote([(None,0.0)]*3) == vote([(4,0.0)]) == (None, 0.0)`;
- `vote([(np.int64(8), np.float64(.9))])` returns a Python `int` and a Python `float` in [0, 1].
- AC2 (T-033 AC3, part 1) `jersey.DigitReader`:
- `DigitReader().name == 'digits'`, `DigitReader.max_reads is None`, and `jersey.DIGIT_FONT == build.FONT` (tests/fixtures/eval_player/build.py loaded via importlib).
- For every n in 1..99, both teams (build.TEAM_RGB red and blue) and every k in (1, 2, 3), the 36×20 crop has a 2 px (40,140,60) grass border around a 16×32 shirt, n drawn by `build._draw_number(crop, n, 2, 2)`, and both axes scaled ×k with np.repeat. It reads `(n, c)` with `type(n) is int`, `type(c) is float` and `c >= jersey.DIGIT_MIN_SCORE`.
- AC3 (T-033 AC3, part 2):
- Dark (20,20,20) numbers drawn the same way on a (235,235,235) shirt with the grass border and scaled ×3 read correctly for n in (3, 8, 10, 23, 99).
- Each of these returns exactly `(None, 0.0)`: a red shirt with no number (grass border), a 36×20 grass-only crop, a 36×20 (0,10,3) crop, a (0,5,3) crop and a (5,0,3) crop.
- Two `read` calls on the same crop (blue 47) give equal results.
- AC4 Module surface:
- `jersey.VOTE_MIN_READS == 3`, `INK_CONTRAST == 80`, `INK_MIN_PIXELS == 6`, `NUMBER_TOP == 0.6` and `DIGIT_MIN_SCORE == 0.6`.
- `jersey.NumberReader` is a `typing.Protocol` whose annotations include `name` and `max_reads`, and it defines `read`.
- `jersey.get_reader()` returns a `DigitReader` instance with SPORTSCUT_NUMBER_READER unset, set to 'ocr' and set to 'tesseract'; none of these raises.
- The module defines no `OcrReader`, `ocr_available`, `download_ocr_models` or `READER_ENV`, and its source contains neither 'easyocr' nor 'environ'.
- AC5 Import hygiene:
- The top-level imports of sportscut/jersey.py (parsed with ast) come only from {math, collections.abc, typing, numpy, __future__}.
- A fresh subprocess `python -c 'import sys, sportscut.jersey; ...'` reports that neither sportscut.player nor sportscut.media nor easyocr is in sys.modules.
- tests/test_media.py::test_only_media_module_imports_subprocess still passes.
- AC6 (T-033 AC7, decode) On the number_hidden clip built by `build.build_all(tmp)` (needs ffmpeg; skipped without it via the `require_ffmpeg` fixture):
- `media.sample_window(clip, 2.0, 1.0, 5, 640, 360)` returns a uint8 array of shape (n, 360, 640, 3) with 4 ≤ n ≤ 6.
- `np.abs(win[0].astype(int) - media.sample_frames(clip, 5, 640, 360)[10].astype(int)).mean() <= 2`.
- AC7 (T-033 AC7, contract):
- On a missing path, `sample_window` raises `MediaError` whose message starts with 'media file not found: ', and neither media.find_tool nor media.subprocess.run is called.
- On an existing file, (start, duration) = (-1, 1), (0, 0), (0, -1), (0, nan), (nan, 1) and (inf, 1) each raise `ValueError('window start must be >= 0 and duration > 0')` without calling find_tool or subprocess.run.
- With subprocess.run captured, `sample_window(p, 2, 1, 5, 640, 360)` passes args equal to `[ffmpeg, '-v','error','-nostdin','-ss','2.000','-t','1.000','-i',str(p),'-an','-sn','-vf','fps=5,scale=640:360:flags=area','-f','rawvideo','-pix_fmt','rgb24','pipe:1']`, with `-ss` and `-t` before `-i`.
- `sample_frames(p, 5, 640, 360)` passes exactly `[ffmpeg, '-v','error','-nostdin','-i',str(p),'-an','-sn','-vf','fps=5,scale=640:360:flags=area','-f','rawvideo','-pix_fmt','rgb24','pipe:1']`.
- A captured non-zero return code makes sample_window raise `MediaError` whose message starts with `ffmpeg failed for `.
- AC8 No behaviour change and scope (checked by commands and in review, not by pytest git-diff tests):
- `python -m pytest -q` reports 0 failed; no test is deleted, skipped, xfailed or edited.
- `git diff --numstat $(git merge-base main HEAD) -- sportscut/media.py tests/test_media.py` shows 0 deleted lines, which the existing T-042 tests enforce.
- The only changed or added files outside the orchestrator-written docs are sportscut/media.py, sportscut/jersey.py, tests/test_jersey.py, tests/test_t033a_acceptance.py and the T-033 design spec.
- `sportscut eval tests/fixtures/eval --json` is identical to the base.
- `sportscut eval-player tests/fixtures/eval_player --json` is identical to the base in every key except seconds_per_min, which stays ≤ 6.0.
- Changed lines outside docs/superpowers, new files included, total < 600.
- AC9 Docs:
- `docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md` exists. When it was absent on the base, its content before the new section is byte-identical to `git show 11413ad:<same path>`.
- It ends with a `## Updated by T-051` section that names `media.sample_window`, `DigitReader`, `vote` and `get_reader`, the border-ink rule, and that get_reader ignores SPORTSCUT_NUMBER_READER until the OCR slice. It also states that player number filtering, `--min-confidence`, OcrReader and `download-models --ocr` have not landed yet.
- No other existing spec file is edited.

## Out of scope

- OcrReader, ocr_dir, ocr_available, download_ocr_models, OCR_* constants, READER_ENV/SPORTSCUT_NUMBER_READER handling, the [ocr] pyproject extra, `download-models --ocr` and the root conftest fixture (OCR slice)
- player.py changes: NUMBER_SPAN/NUMBER_WIDTH/TRACK_GATE/MIN_CONFIDENCE, _read_numbers, tracking, PlayerQuery.min_confidence, detect_touches/find_touches number filtering (player-number-filter slice)
- cli.py `player --min-confidence`, the README section `## Số áo cầu thủ (T-033)`, and the `## Updated by T-033` notes on the T-030/T-031/T-032 specs (later slices)
- Editing any existing test (including the nine T-033 AC15 edits, which belong to the next slice), tests/test_media.py, tests/conftest.py or tests/fixtures/
- Restoring the T-033 plan file or the T-033 DECISIONS lines from 11413ad
- Any change to eval metrics, eval_player.py, reel.py, api.py or reframe.py, and any new dependency (scipy, opencv)

## Decisions

- T-051 (R-006): T-033 lands in three slices. T-051 ships only media.sample_window and the numpy part of sportscut/jersey.py (VOTE_MIN_READS=3, INK_CONTRAST=80, INK_MIN_PIXELS=6, NUMBER_TOP=0.6, DIGIT_MIN_SCORE=0.6, DIGIT_FONT, NumberReader, DigitReader, vote, get_reader). The module has no caller yet, so CLI, player, API and eval output are unchanged. All other T-033 design decisions (formulas, tuning ranges, gate) still apply to the later slices.
- T-051 (R-006): media.sample_window(path, start, duration, fps, width, height) checks the file (MediaError 'media file not found: ...') and then the window (ValueError 'window start must be >= 0 and duration > 0' for a non-finite value, start < 0 or duration <= 0) before find_tool or ffmpeg runs. It passes `-ss {start:.3f} -t {duration:.3f}` as input options before -i, with the same -vf/rawvideo/rgb24 output as sample_frames.
- T-051 (R-006): media.py stays append-only (0 deleted lines vs merge-base), as the T-042 shared-file tests require. The shared run-and-reshape helper `_run_frames` is created by inserting a `return _run_frames(...)` line into sample_frames and a `def _run_frames` header above the existing subprocess.run tail. The sample_frames args are unchanged.
- T-051 (R-006): DigitReader adds one step to the T-033 §2 algorithm. After the INK_CONTRAST test it drops every ink pixel 8-connected through ink to the crop edge (numpy flood fill, no scipy), so background such as grass against a light shirt is not read as the number. Without it, T-033 AC3's dark-on-light case fails. The rest is as specified: top 60 % rows, luma vs crop median for either polarity, the ink box resampled to 5×3/5×7 DIGIT_FONT grids, Pearson correlation, ties to the smaller n, and acceptance at ≥ DIGIT_MIN_SCORE.
- T-051 (R-006): DIGIT_FONT is a literal copy of tests/fixtures/eval_player/build.py FONT, and a test pins their equality. Product code never imports from tests/.
- T-051 (R-006): jersey.py is numpy-only. Its top-level imports are limited to math, collections.abc, typing and numpy, and it never imports sportscut.player, sportscut.media, subprocess or easyocr. get_reader() returns DigitReader() and ignores the environment until the OCR slice replaces it with the T-033 SPORTSCUT_NUMBER_READER rules.
- T-051 (R-006): vote returns a Python int and a Python float even for numpy inputs: confidence = round(W[win]/ΣW × min(1, count[win]/VOTE_MIN_READS), 4), reads with None or conf ≤ 0 are ignored, and no reads gives (None, 0.0).
- T-051 (R-006): The T-033 design spec was never merged. T-051 restores it byte-identically from commit 11413ad and appends `## Updated by T-051` recording what landed and what has not. Each later slice appends its own `## Updated by <task>` note.
- T-051 (R-006): Size (< 600 changed lines outside docs/superpowers, Tester file included), changed-file scope and eval/eval-player equality are checked by commands and in review, not by pytest git-diff tests (T-028/T-049 rule). No existing test file is edited in this slice.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md`
