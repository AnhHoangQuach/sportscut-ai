# T-033: Read jersey numbers around each touch with a pluggable reader and keep only the chosen player

Request R-006. Plan: `docs/superpowers/plans/2026-11-23-t-033-read-jersey-numbers-around-each-touch.md`.

## Product Owner request

Theo dõi cầu thủ: chọn một cầu thủ, xuất video tổng hợp mọi pha chạm bóng của người đó.

## Goal

For each same-team touch, follow the toucher's blob by nearest-centroid matching across about ±2 s of 5 fps frames (sampled only around touches, never the whole match). Read the number on each crop with a `NumberReader` protocol and take a confidence-weighted vote. Add two backends: a numpy `digits` template reader with no extra dependency, which handles the synthetic font and clean real kits, and an optional `[ocr]` extra (for example easyocr, models downloaded by a separate command and not committed) that is used automatically when installed. `find_touches` then keeps touches whose voted number equals the query and whose confidence passes a threshold. `--min-confidence` lets the user trade precision for recall. Report F1, precision, recall and id_accuracy before and after. Merge only if F1 ≥ 0.85 on the synthetic set, including the number-turned-away case, and if the processing time stays within budget with and without the extra. Assumption: on real broadcasts, numbers are often unreadable in wide shots, so real-match recall depends on the PO's labelled `data/eval_player/`. That number goes in the PR when the data exists.

## Acceptance criteria

- AC1: Step 0 runs before any file change. On a base where `from sportscut.player import TeamColours, pick_team, _analyse, find_touches` imports, it prints READY and records the untouched base's one-line `python -m sportscut eval-player tests/fixtures/eval_player --json` and `python -m sportscut eval tests/fixtures/eval --json`. Otherwise the Developer reports `BLOCKED: T-033 needs T-032 team attribution on the base` and the diff is empty.
- AC2: `jersey.vote`:
- `vote([(8,.9),(8,.8),(3,.5),(None,0.0)]) == (8, 0.5152)`;
- `vote([(10,1.0)]*5) == (10, 1.0)`;
- `vote([(7,.5),(9,.5)]) == (7, 0.1667)`;
- `vote([]) == vote([(None,0.0)]*3) == vote([(4,0.0)]) == (None, 0.0)`.
The number is a Python int or None and the confidence a Python float in [0,1].
- AC3: `jersey.DigitReader`:
- `DigitReader().name == 'digits'`, `max_reads is None`, and `jersey.DIGIT_FONT == build.FONT` (tests/fixtures/eval_player/build.py).
- For every n in 1..99: a 20×36 crop (a 2 px grass (40,140,60) border around a 16×32 shirt of build.TEAM_RGB red or blue, with n drawn by build._draw_number) reads `(n, c)` with `c >= jersey.DIGIT_MIN_SCORE`. The same holds after `np.repeat` scaling ×2 and ×3 on both axes.
- Dark (20,20,20) numbers drawn the same way on a (235,235,235) shirt and scaled ×3 read correctly for n in (3, 8, 10, 23, 99).
- A shirt with no number, a grass-only crop and a (0,10,3) crop each give `(None, 0.0)`.
- Two calls on the same crop give equal results.
- AC4: `jersey.OcrReader` with a fake `easyocr` module (a tmp `easyocr.py` on sys.path):
- Construction alone does not create `easyocr.Reader`.
- The first `read` creates it exactly once, with `(['en'], gpu=False, model_storage_directory=str(jersey.ocr_dir()), download_enabled=False, verbose=False)`. Later reads reuse it.
- `readtext` receives the crop scaled by OCR_SCALE on both axes, `allowlist='0123456789'` and `detail=1`.
- Results `[(b,'10',.9),(b,'7',.95),(b,'abc',.99),(b,'123',.99),(b,'07',.99)]` give `(7, 0.95)`. `[]` gives `(None, 0.0)`. A conf of 1.3 is clipped to 1.0.
- `name == 'ocr'` and `max_reads == jersey.OCR_MAX_READS`.
- AC5: `jersey.get_reader` and availability:
- `ocr_dir() == Path(XDG_CACHE_HOME)/'sportscut'/'easyocr'` when XDG_CACHE_HOME is set.
- `ocr_available()` is False without an importable easyocr. It is False with the fake module but a missing model file, and True with the fake module and both OCR_MODEL_FILES present in ocr_dir().
- With SPORTSCUT_NUMBER_READER unset or 'auto', get_reader returns an OcrReader exactly when ocr_available() is True, and a DigitReader otherwise.
- 'digits' always returns a DigitReader.
- 'ocr' without availability raises ValueError containing "pip install 'sportscut[ocr]'" and 'download-models --ocr'.
- 'tesseract' raises ValueError 'SPORTSCUT_NUMBER_READER must be auto, digits or ocr'.
- Importing sportscut.jersey or sportscut.player never imports easyocr.
- AC6: `sportscut download-models --ocr`:
- With jersey.download_ocr_models patched to return P, it exits 0 and prints `downloaded EasyOCR models to P`.
- Without easyocr it exits 1 with stderr exactly `sportscut download-models: error: needs the [ocr] extra: pip install 'sportscut[ocr]'\n`.
- With a RuntimeError('offline') it exits 1 with `sportscut download-models: error: offline`.
- `download-models --ocr --tts` exits 2.
- With the fake easyocr module, download_ocr_models() creates ocr_dir(), calls easyocr.Reader with download_enabled=True and model_storage_directory=str(ocr_dir()), and returns ocr_dir().
- The existing `download-models` and `download-models --tts` tests pass unchanged.
- AC7: `media.sample_window`:
- `sample_window(clip, 2.0, 1.0, 5, 640, 360)` on the built number_hidden clip returns uint8 of shape (n, 360, 640, 3) with 4 ≤ n ≤ 6.
- Its frame 0 equals `sample_frames(clip, 5, 640, 360)[10]` within a mean absolute difference ≤ 2.
- A missing file raises MediaError('media file not found: ...') without running ffmpeg. start=-1, duration=0 and duration=nan each raise ValueError.
- The ffmpeg args contain `-ss 2.000 -t 1.000` before `-i`.
- `sample_frames` keeps its exact argument list.
- AC8: `player._read_numbers(video, touches, reader)` with media.probe_size → (640, 360) and media.sample_window monkeypatched to numpy frames (a 16×32 red shirt with number 7 moving 6 px per sample, the number blanked for samples within ±1 s of the touch). Tests use a recording reader that wraps DigitReader.
- It returns `[(7, c)]` with `c >= player.MIN_CONFIDENCE` for one touch seeded with the shirt's bbox.
- A bbox farther than TRACK_GATE×height from every blob, and `bbox=None`, each give `(None, 0.0)`.
- `[]` returns `[]` and calls neither probe_size nor sample_window.
- If the shirt jumps 100 px at t+1 s, no crop after the jump is read.
- A reader with max_reads=2 is called exactly 2 times per tracked touch.
- Two touches 1.0 s apart cause exactly one sample_window call, whose start is a multiple of 0.2 and ≥ 0. Touches 10 s apart cause two calls.
- Each touch's vote is the same whether it is read alone or together with a neighbour.
- AC9: detect_touches and find_touches, with `_analyse` patched to return ([red(1.0), blue(2.0), red(3.0), None-team(4.0)], C) and `_read_numbers` patched to return [(10, .9), (7, .4)] for the red pair and [(10, .9)] for blue:
- `find_touches(x, PlayerQuery('red', 10)) == [replace(red1, number=10)]`.
- `PlayerQuery('red', 7)` gives [] at the default threshold and `[replace(red3, number=7)]` with min_confidence 0.3.
- `_analyse` is called once per call.
- `_read_numbers` receives only same-team touches in find_touches, and only team-labelled touches in detect_touches.
- The `'#ff00ff'` tie still raises 'equally close' before `_read_numbers` runs. colours None gives [] with no read.
- detect_touches returns the 4 touches with numbers [10, None, None, None] (7 is below MIN_CONFIDENCE), and t/team/confidence/bbox unchanged.
- With `jersey.get_reader` raising ValueError, both functions raise it.
- AC10: PlayerQuery and the CLI:
- `PlayerQuery('red', 10) == PlayerQuery('red', 10, player.MIN_CONFIDENCE)` and `.min_confidence` is a float.
- min_confidence values -0.1, 1.01, nan, True and '0.5' each raise ValueError 'min confidence must be between 0 and 1'; 0 and 1 are accepted.
- `python -m sportscut player CLIP --team blue --number 8 --min-confidence 1.5 --out D` exits 2 with `sportscut player: error: min confidence must be between 0 and 1` and does not create D.
- With find_touches patched, `--min-confidence 0.3` passes `PlayerQuery('blue', 8, 0.3)`, and no flag passes `PlayerQuery('blue', 8)`.
- `player --help` mentions --min-confidence.
- AC11: Merge gate. On the built synthetic set with SPORTSCUT_NUMBER_READER=digits, `python -m sportscut eval-player tests/fixtures/eval_player --json` gives:
- f1 ≥ 0.85, and per_clip number_hidden f1 ≥ 0.85;
- id_accuracy ≥ 0.75 and precision > 0.4205;
- team_accuracy ≥ 0.95, touch_f1_any ≥ 0.9737, and per-clip touch_f1_any ≥ dribble 1.0, near_miss 1.0, number_hidden 1.0, short_passes 0.9091;
- 0 < seconds_per_min ≤ 6.0.
For every case and labelled query, every find_touches(clip, q) result is in detect_touches(clip) and has team == q.team and number == q.number.
`python -m sportscut player <built number_hidden clip> --team blue --number 8 --out D` exits 0. Every D/player.json touch has team 'blue' and number 8, and at least 3 of the 4 labelled blue-8 times (4.0, 5.2, 9.0, 14.0) are within 0.5 s of a manifest touch.
`python -m sportscut eval tests/fixtures/eval --json` f1 equals the Step 0 value.
- AC12: The gate can fail:
- With `jersey.get_reader` patched to a reader that always returns (None, 0.0), evaluate_dir gives f1 == 0.0 and id_accuracy == 0.0.
- With `player.NUMBER_SPAN` patched to 0.4 (no frame outside the hidden ±1 s), the number_hidden per-clip f1 is < 0.85.
- On number_hidden, the find_touches results for PlayerQuery('blue', 8, 0.0) ⊇ PlayerQuery('blue', 8) ⊇ PlayerQuery('blue', 8, 1.0).
- AC13: Frames are sampled only around touches:
- During one find_touches call on the built clips, media.sample_frames is called exactly once (the _analyse pass).
- Every media.sample_window call (start, duration) has start ≥ 0, start a multiple of 0.2 (within 1e-6), and [start, start+duration] inside the union of [t-NUMBER_SPAN-0.2, t+NUMBER_SPAN+0.4] over the queried team's touches.
- On short_passes, find_touches(clip, PlayerQuery('red', 7)) makes no sample_window call whose span contains t = 12.0 (only blue touches are near it).
- AC14: Time budget with the extra. A test marked `skipif(not jersey.ocr_available())` sets SPORTSCUT_NUMBER_READER=ocr and asserts that evaluate_dir on the built set gives seconds_per_min ≤ 6.0, and prints the report. The PR quotes this JSON, or states `OCR timing not measured: [ocr] extra not installed`.
- AC15: Regression and scope:
- `python -m pytest -q` reports 0 failed. No test is deleted, renamed, skipped or marked xfail.
- Pre-existing tests change only in these functions, and each change only adds a monkeypatch of `player._read_numbers` / `media.sample_window` / env, or updates the listed assert:
  - tests/test_player.py::test_detect_touches_stub_and_find_filters (patch _read_numbers, final expected list);
  - tests/test_teams.py::test_detect_touches_labels_team (patch _read_numbers to (None, 0.0); `PlayerQuery('red', 99)` now expects []);
  - tests/test_teams.py::test_find_touches_team_only_single_pass (patch _read_numbers, expected lists);
  - tests/test_teams.py::test_eval_player_team_gate (id_accuracy == 0.0 → ≥ 0.75);
  - tests/test_t032_acceptance.py::test_ac8_detect_touches_team (patch _read_numbers);
  - tests/test_t032_acceptance.py::test_ac9_find_touches_and_cli (patch _read_numbers, expected lists);
  - tests/test_t032_acceptance.py::test_ac10_eval_player_gate_and_queries (id_accuracy == 0 → ≥ .75);
  - tests/test_t031_acceptance.py::test_ac5_real_set_touch_shape (number None → None or 1..99);
  - tests/test_eval_player_fixtures.py::test_eval_player_cli_baseline_json (id_accuracy == 0.0 → ≥ 0.75).
- `git diff main -- sportscut/eval_player.py sportscut/reel.py sportscut/api.py sportscut/reframe.py tests/fixtures/eval_player` is empty.
- In sportscut/player.py, `_analyse`, find_kicks, player_blobs, suppress_touches, _box_gap, every T-031/T-032 constant, colour_features, kmeans, team_colours, team_of, pick_team and name_teams are byte-identical. The T-031 grep on sportscut/player.py prints nothing.
- pyproject.toml differs only by the added `ocr = ["easyocr>=1.7"]` extra.
- `git ls-files '*.pth' '*.mp4'` is empty.
- AC16: README.md is insert-only (0 deleted lines vs main). It has exactly one `## Số áo cầu thủ (T-033)` heading, immediately followed by the next heading `## Đội theo màu áo (T-032)`. The section contains:
- `--min-confidence`, `SPORTSCUT_NUMBER_READER`, `pip install 'sportscut[ocr]'`, `sportscut download-models --ocr`, `góc rộng` and `data/eval_player/`;
- a ```text block whose NUMBER_SPAN, NUMBER_WIDTH, TRACK_GATE, MIN_CONFIDENCE (player) and VOTE_MIN_READS, INK_CONTRAST, INK_MIN_PIXELS, NUMBER_TOP, DIGIT_MIN_SCORE, OCR_SCALE, OCR_MAX_READS (jersey) values equal the module constants;
- `Trước T-033:` and `Sau T-033:`, each followed by a one-line ```json report. 'Trước' has id_accuracy 0.0, and 'Sau' has f1 ≥ 0.85 and id_accuracy ≥ 0.75.
The T-031 and T-032 README tests still pass.
- AC17: Specs and size:
- The T-030, T-031 and T-032 design specs each end with a `## Updated by T-033` section that names `--min-confidence`, the number vote and `find_touches` filtering by number. Their other text is unchanged, and the T-029/T-031 'Existing specs this task changes' lists are not edited.
- Changed lines outside docs/superpowers total < 800, counting new test files.
- The Developer report and PR body quote the before and after eval-player JSON (f1, precision, recall, id_accuracy, seconds_per_min), the OCR line from AC14, and the data/eval_player line.

## Out of scope

- Changing eval_player.py metrics, labels, build.py or the synthetic clips, or adding new synthetic cases
- Changing T-031 touch detection or T-032 team attribution constants/algorithms (`_analyse` stays byte-identical)
- Exposing min_confidence or the reader choice in the HTTP API / web page (POST /players keeps the default)
- Adding min_confidence or vote confidence to player.json or Touch.to_dict (Touch keeps its five fields)
- Caching analysis or number reads between find_touches calls or eval queries
- Player re-identification across camera cuts, close-up/replay handling, or reading numbers outside ±2 s of a touch
- Training or fine-tuning any model, GPU support, other OCR engines (tesseract, paddle), or bundling OCR models in git/wheel
- Labelling or committing real matches; data/eval_player/ stays git-ignored and PO-provided
- Rewriting the stale T-030/T-032 README sentences (README is insert-only)
- Adding easyocr to the dev extra or CI

## Decisions

- T-033 (R-006): Number reading lives in a new numpy-only module sportscut/jersey.py (NumberReader protocol, DigitReader, OcrReader, vote, get_reader, ocr_dir, ocr_available, download_ocr_models). It is named jersey to avoid shadowing stdlib `numbers`. Tracking and filtering live in sportscut/player.py. ffmpeg stays in sportscut/media.py (new sample_window), and player.py still passes the T-031 grep.
- T-033 (R-006): Number crops come from a second decode at min(width, 1280) px, never upscaled, sampled at 5 Hz. Decoding happens only in grid-aligned ±NUMBER_SPAN (2.0 s) windows around the touches being read; overlapping windows are merged into one media.sample_window call. The whole match is never decoded at crop resolution. Tracking runs on frame[::s, ::s] at about the 320 px analysis scale using the unchanged player_blobs.
- T-033 (R-006): The toucher is followed by nearest-centre blob matching. The seed is the touch bbox in the frame nearest t. Tracking goes forward and backward separately and stops at the first sample where no blob centre lies within TRACK_GATE × previous box height. Each touch uses only frames inside its own ±NUMBER_SPAN, so its vote does not depend on window grouping and detect_touches and find_touches agree.
- T-033 (R-006): Vote: confidence = W[win]/ΣW × min(1, count[win]/VOTE_MIN_READS), where W sums the read confidences per number. Ties go to the smaller number. Unread crops (None or conf 0) do not count, and no reads gives (None, 0.0).
- T-033 (R-006): DigitReader uses the luma contrast against the crop median (either polarity) in the top 60 % of the crop. The ink bounding box is resampled to the DIGIT_FONT 5×3 / 5×7 grids, and the best Pearson correlation over 1..99 is accepted at ≥ DIGIT_MIN_SCORE. DIGIT_FONT equals the synthetic build.py FONT. Real-kit accuracy is unmeasured until data/eval_player/ exists.
- T-033 (R-006): The OCR backend is the optional extra `ocr = ["easyocr>=1.7"]`. Models (craft_mlt_25k.pth, english_g2.pth) are downloaded only by `sportscut download-models --ocr` into $XDG_CACHE_HOME|~/.cache/sportscut/easyocr, never at run time (download_enabled=False) and never committed. OcrReader upscales crops ×OCR_SCALE, uses a digit allowlist, accepts 1..99 without a leading zero, reads at most OCR_MAX_READS evenly spaced crops per touch, and loads the model once per process.
- T-033 (R-006): Reader choice: SPORTSCUT_NUMBER_READER = auto (default: ocr if easyocr is importable and both model files exist, else digits) | digits | ocr (error with the install hint if unavailable) | anything else gives ValueError. The env var exists so the same machine can measure both backends. tests/conftest.py forces digits with an autouse fixture so the suite is the same with or without the extra.
- T-033 (R-006): The threshold travels as PlayerQuery.min_confidence (default MIN_CONFIDENCE = 0.5, validated to 0..1), so the find_touches(video, query) and make_player_reel signatures and every existing monkeypatch stay valid. The CLI `player --min-confidence` sets it, and the API and eval labels use the default. player.json and Touch.to_dict are unchanged.
- T-033 (R-006): find_touches reads numbers only for touches of the mapped team. It returns replace(t, number=n) for votes with n == query.number and confidence ≥ query.min_confidence. detect_touches reads every team-labelled touch and sets number only when the confidence is ≥ MIN_CONFIDENCE, so eval's id_accuracy becomes meaningful. This supersedes T-032 AC8 (detect_touches == _analyse(video)[0]) and the T-032 'number ignored' rule. Touch t, team, confidence and bbox never change.
- T-033 (R-006): Merge gate on the synthetic eval-player set with the digits reader:
- f1 ≥ 0.85 overall and on number_hidden;
- id_accuracy ≥ 0.75 and precision > 0.4205;
- team_accuracy ≥ 0.95 and touch_f1_any unchanged from T-032 (≥ 0.9737 overall, per-clip floors);
- seconds_per_min ≤ 6.0;
- `sportscut eval` f1 unchanged.
With the extra installed, seconds_per_min ≤ 6.0 is enforced by a skip-if-unavailable test, and OCR f1 is reported but not gated (the 3×5 px synthetic font does not represent real kits). If OCR cannot be installed, the PR says so and the Tech Lead decides.
- T-033 (R-006): Tuning is allowed only for TRACK_GATE [0.5, 2.0], MIN_CONFIDENCE [0.3, 0.8], VOTE_MIN_READS [1, 5], INK_CONTRAST [40, 120], DIGIT_MIN_SCORE [0.4, 0.9] and OCR_MAX_READS [2, 8]. NUMBER_SPAN, NUMBER_WIDTH, INK_MIN_PIXELS, NUMBER_TOP, OCR_SCALE and all T-031/T-032 constants are fixed. If no setting meets the gate, the Developer reports BLOCKED with the best JSON.
- T-033 (R-006): Allowed edits to pre-existing tests are only the nine functions listed in AC15: monkeypatches of _read_numbers/sample_window/env and the id_accuracy/number/expected-list asserts that pinned the T-032 'number ignored' behaviour. No test is deleted, renamed, skipped or marked xfail.
- T-033 (R-006): The README section `## Số áo cầu thủ (T-033)` is insert-only and placed immediately before `## Đội theo màu áo (T-032)`, because the T-031, T-032 and T-027 tests pin the headings after the T-031 and T-032 sections and the last section. The T-030, T-031 and T-032 design specs get an appended `## Updated by T-033` section. The T-029/T-031 'Existing specs this task changes' lists are not edited (test_t032_acceptance::test_ac13 pins their last bullet).
- T-033 (R-006): Known limitation, documented and not solved: on real broadcasts numbers are often unreadable in wide shots, so real-match recall depends on the PO's labelled data/eval_player/. That eval-player JSON goes in the PR when the data exists, otherwise a 'not available' line.
- T-033 (R-006): The size budget is < 800 changed lines outside docs/superpowers, including the Tester file. It is above the 600 T-031/T-032 precedent because the task requires two backends, the CLI flag and the model download in one gated slice. No dependency is added to the core install; easyocr is only in the new [ocr] extra. The Tester's diff-scope asserts run only on office/T-033* branches.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-032-attribute-each-touch-to-a-team-design.md`
- `docs/superpowers/specs/2026-11-23-t-031-detect-ball-touches-by-any-player-design.md`
- `docs/superpowers/specs/2026-11-23-t-030-add-sportscut-player-cli-that-cuts-design.md`
- `docs/superpowers/specs/2026-11-23-t-029-build-the-player-touch-eval-synthetic-design.md`

## Updated by T-051

T-033 was split into three slices; T-051 is the first and is library-only (no CLI, player, API or eval change).
- Landed: `media.sample_window(path, start, duration, fps, width, height)` (validates the file and the window
  before ffmpeg runs; `-ss`/`-t` go before `-i`; `sample_frames` args are unchanged and both share `_run_frames`).
- Landed: `sportscut/jersey.py` (numpy only) with the constants, the `NumberReader` Protocol, `DigitReader`
  (name `digits`, `max_reads` None), `vote` and `get_reader`.
- Border-ink rule added to the §2 DigitReader algorithm: after thresholding, every ink pixel 8-connected through
  ink to the crop's outer edge is dropped (iterative numpy flood fill, no scipy), so a grass border is not read
  as ink against a light shirt.
- `get_reader()` always returns `DigitReader()` and ignores `SPORTSCUT_NUMBER_READER` until the OCR slice.
- Not landed yet: player number filtering around touches, `sportscut player --min-confidence`, `OcrReader`
  and `download-models --ocr` (later slices).

Updated by T-052: landed `player._read_numbers`, `PlayerQuery.min_confidence` (default MIN_CONFIDENCE 0.5,
validated to [0, 1]), number filtering in `detect_touches`/`find_touches`, `sportscut player --min-confidence`
and the README section `## Số áo cầu thủ (T-033)`. The §3 tracker is no longer a plain nearest-centre tracker:
each direction from the seed predicts the next centre with constant velocity (gate TRACK_GATE x previous box
height around the prediction), and a blob wider or taller than TRACK_MERGE (1.3) x the seed box is two merged
players, so the walk coasts on the prediction and reads no crop. Reason: the blocked T-033 attempt measured the
plain tracker at best number_hidden f1 0.7143, because blue 8 crosses another player and the track jumped to
that player. OcrReader, SPORTSCUT_NUMBER_READER and `download-models --ocr` are left for T-053.
Updated by T-052 (review round 1): merged sample_window groups are capped at NUMBER_GROUP_MAX = 20.0 s (fixed). A
touch joins the current group only when its window overlaps it and the group would still span at most
NUMBER_GROUP_MAX; otherwise it starts a new group, so a long chain of touches is decoded in several calls instead
of one. Votes are unchanged, because each touch's full window stays inside one grid-aligned group.
