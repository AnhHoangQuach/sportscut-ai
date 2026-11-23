# Plan T-010: Add event types to segments and a `sportscut eval` command with per-event metrics

Design: `docs/superpowers/specs/2026-11-23-t-010-add-event-types-to-segments-and-design.md`.

## Implementation plan

# T-010: Event types on segments and a `sportscut eval` command with per-event metrics

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:test-driven-development for each step. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every `Segment` gets an `event` label. `sportscut eval DIR --json` scores `find_highlights` against labelled matches and prints overall, per-event, type-accuracy and precision@5 metrics.

**Architecture:** There is one new pure-Python module, `sportscut/evaluate.py`. It holds label loading (JSON and CSV), one-to-one temporal matching, per-case counting, metric summaries and `evaluate_dir`. It reuses `prf` from `sportscut/eval_player.py`. `sportscut/cli.py` gets an `eval` subcommand that follows the existing `eval-player` subcommand. `Segment` gets `event: str = "other"`, which is validated against `EVENT_TYPES` and emitted last in `to_dict()`. This task adds no event classifier: the detector still emits `event="other"`. The rule-based classifiers and the synthetic event set `tests/fixtures/eval/` are later R-003 tasks.

**Tech stack:** Python 3.11 standard library (json, csv, re, pathlib) and the existing numpy/ffmpeg detector. No new dependencies.

**Related specs this task changes:** T-035 AC5 (`Segment.to_dict` keys), T-002 AC9 (`detect --json` keys) and T-004 AC1 (manifest entry keys). Each of these key sets gains `event`. The API response from T-005 is unchanged, because `api.py` picks its keys explicitly.

## Global constraints
- Runtime dependencies stay `numpy` only, and nothing changes in `pyproject.toml`.
- Do not change `sportscut/api.py`, `sportscut/detect.py`, `sportscut/pipeline.py`, `sportscut/export.py` or `tests/conftest.py`.
- Keep the implementation diff under about 400 changed lines. The orchestrator-written `docs/superpowers` files do not count. Keep the tests compact by using `pytest.mark.parametrize` for the validation cases.
- Metric floats are rounded to 4 decimals with `round(x, 4)`, as in `eval_player.metrics`.
- `python -m pytest -q` must pass. Without ffmpeg on PATH, this task must add no new failures. The e2e tests skip through the existing `require_ffmpeg` fixture chain (`burst_video`).

## Step 0: precondition (run it before any edit)
```bash
python -c "import pathlib; from sportscut.models import Segment; from sportscut.detect import find_highlights; from sportscut.pipeline import run; assert pathlib.Path('sportscut/api.py').is_file(); print('READY')"
```
Continue only if this prints `READY`. Otherwise report BLOCKED. Do not re-create or cherry-pick Segment, find_highlights, pipeline.run or api.py.

## Files
- Modify `sportscut/models.py`: add `EVENT_TYPES` and the `event` field, its validation and its `to_dict` key.
- Create `sportscut/evaluate.py`: `Label`, `LABEL_TYPES`, `to_event`, `temporal_iou`, `match_segments`, `load_labels`, `score_case`, `summarize`, `evaluate_dir`.
- Modify `sportscut/cli.py`: add the `eval` subparser and its handler.
- Modify `tests/test_models.py`: add the new `event` tests and update the key-order test to include `event`.
- Create `tests/test_evaluate.py`: unit tests plus the CLI e2e test.
- Modify the key-set assertions to add `"event"`, and change nothing else in these tests: `tests/test_cli.py` (test_detect_json), `tests/test_pipeline.py` (test_run_returns_manifest_entries) and `tests/test_t004_acceptance.py` (two `set(entry) == {...}` lines). This follows the intended spec change. It does not weaken any test.
- Update the AC text in the docs: `docs/superpowers/specs/2026-11-23-t-035-...-design.md` AC5, `...t-002-...-design.md` AC9 and `...t-004-...-design.md` AC1. In each, add `event` to the key list and append `(updated by T-010)`.
- The Tester creates `tests/test_t010_acceptance.py`.

## Interfaces

### `sportscut/models.py`
```python
EVENT_TYPES = ("goal", "save", "red_card", "controversy", "other")

@dataclass(frozen=True)
class Segment:
    start: float; end: float; score: float; reason: str
    event: str = "other"
```
- If `event not in EVENT_TYPES`, `__post_init__` raises `ValueError("event must be one of goal, save, red_card, controversy, other")`. A `np.str_` value is accepted.
- `to_dict()` returns `{start, end, score, reason, event}` in that order, with `event` as a native `str`.

### `sportscut/evaluate.py`
```python
LABEL_TYPES = ("goal", "save", "red_card", "controversy", "chance", "yellow_card", "foul", "other")
MIN_IOU = 0.3
VIDEO_SUFFIXES = (".mp4", ".mkv", ".mov")

class Label(NamedTuple):
    start: float
    end: float
    type: str        # raw vocabulary type, already stripped and lower-cased

def to_event(label_type: str) -> str      # label type -> scored event; non-R-003 types -> "other"
def temporal_iou(a_start, a_end, b_start, b_end) -> float   # overlap / union; 0.0 when disjoint
def match_segments(segments: Sequence[Segment], labels: Sequence[Label]) -> list[tuple[int, int]]
def load_labels(path: str | Path) -> list[Label]   # dispatch on suffix: .json or .csv
def score_case(segments: Sequence[Segment], labels: Sequence[Label]) -> dict
def summarize(counts: dict) -> dict
def evaluate_dir(path: str | Path) -> dict
```

**`match_segments`:**
1. A pair (segment i, label j) is a candidate when `temporal_iou >= MIN_IOU - 1e-9`, or when the segment fully contains the label (`seg.start <= label.start and label.end <= seg.end`).
2. Sort the candidates by `(-iou, j, i)`.
3. Take candidates greedily, keeping a pair only if neither its segment nor its label is already used.
4. Return `(segment_index, label_index)` pairs sorted by label index.

**`score_case` counts dict:** `{"tp", "fp", "fn", "type_hits", "p5_hits", "p5_total", "events": {e: {"tp", "fp", "fn"} for e in EVENT_TYPES}}`.
- `tp` is the number of matched pairs, `fp` = segments - tp and `fn` = labels - tp.
- `type_hits` counts matched pairs where `segment.event == to_event(label.type)`.
- Per event e:
  - `tp_e` counts matched pairs where both the segment's event and `to_event(label.type)` equal e.
  - `fp_e` = (number of segments with event e) - `tp_e`.
  - `fn_e` = (number of labels with `to_event == e`) - `tp_e`.
- Precision@5:
  - Take the top-5 segments by `(-score, start)`.
  - `p5_total` = `min(5, len(segments))`.
  - `p5_hits` counts those top-5 segments that appear in a matched pair, whatever the type.

**`summarize(counts)`** returns a dict whose keys are in exactly this order:
- `f1`, `precision`, `recall`: from `eval_player.prf(tp, fp, fn)`. These are 0.0 when undefined.
- `event_accuracy`: `type_hits / tp`, or `None` when `tp == 0`.
- `per_event`: all 5 `EVENT_TYPES` in order, each `{"precision", "recall", "f1"}`.
  - precision is `None` when `tp_e + fp_e == 0`.
  - recall is `None` when `tp_e + fn_e == 0`.
  - f1 is `None` if either is `None`. Otherwise it is `2pr/(p+r)`, or 0.0 when `p + r == 0`.
- `precision_at_5`: `p5_hits / p5_total`, or 0.0 when `p5_total == 0`.

All floats are rounded to 4 decimals.

**`evaluate_dir(path)`:**
1. Validate the whole directory before running any detection:
   - `path` is not a directory: raise `ValueError(f"not a directory: {path}")`.
   - The cases are the sorted subdirectories that contain `labels.json` or `labels.csv`. If one has both, raise `ValueError(f"{case}: has both labels.json and labels.csv")`. If there are no cases, raise `ValueError(f"no eval cases found in {path}")`.
   - Each case needs exactly one file whose lower-cased suffix is in `VIDEO_SUFFIXES`. Otherwise raise `ValueError(f"{case}: expected exactly one video (.mp4, .mkv, .mov), found {n}")`.
   - Load every case's labels.
2. Run the detection: `find_highlights(video)` with default options, imported as `from sportscut import detect` and called as `detect.find_highlights` so it can be monkeypatched.
3. Sum the counts over all cases.
4. Return `{**summarize(totals), "per_match": [...]}`. Each `per_match` entry is `{"match": case_dir.name, "labels": n_labels, "predictions": n_segments, "f1", "precision", "recall", "event_accuracy", "precision_at_5"}`, taken from `summarize(case_counts)` without `per_event`. Entries are in sorted case order.

### Label formats (`load_labels`)
In every format, `type` is `str(value).strip().lower()`. It must be in `LABEL_TYPES`, or the loader raises `ValueError` naming the type.

**`labels.json`:**
- The top level must be a list.
- Each item must be an object with:
  - `start` and `end`: numbers, not bool, finite, with `0 <= start < end`.
  - `type`: a string.
- `importance` and any other keys are optional and ignored.
- Errors raise `ValueError(f"{path}: [{i}]: <reason>")`. Unreadable or invalid JSON raises `ValueError(f"{path}: <exc>")`.
- An empty list is valid and means a match with no events.

**`labels.csv`:**
- Lines are `mm:ss,mm:ss,type`. Cells are whitespace-stripped.
- Blank lines and lines whose first cell starts with `#` are skipped.
- If the first data line's first cell is `start` (case-insensitive), it is a header and is skipped.
- Each line must have exactly 3 cells.
- Times match `^(\d+):([0-5]\d)(\.\d+)?$`, so minutes may exceed 59. The value is `minutes*60 + seconds`.
- Errors raise `ValueError(f"{path}: line {n}: <reason>")` with a 1-based physical line number.
- The same `start < end` and type checks apply.

### CLI
Usage: `sportscut eval DIRECTORY [--json]`.
- `--json` prints `json.dumps(report)` on a single line. Without it, the report is printed with `indent=2`.
- The exit code is 0 on success.
- `ValueError`, `OSError` or `MediaError` prints `sportscut eval: error: <msg>` to stderr and exits 2. This mirrors `eval-player`.

## Steps (test first)
- [ ] **Step 0:** Run the precondition and confirm it prints `READY`.
- [ ] **Step 1:** Write the failing tests in `tests/test_models.py`:
  - `Segment(1,3.5,0.8,'crowd noise').to_dict()` equals `{start:1.0, end:3.5, score:0.8, reason:'crowd noise', event:'other'}`, with key order `[start, end, score, reason, event]`.
  - `event='goal'` round-trips through `to_dict()`.
  - `event=np.str_('save')` gives `type(to_dict()['event']) is str`.
  - Each of `event='penalty'`, `'Goal'` and `''` raises `ValueError`.
  - `EVENT_TYPES == ('goal','save','red_card','controversy','other')`.
- [ ] **Step 2:** Run `python -m pytest -q tests/test_models.py` and confirm it fails because of the missing `event` / `EVENT_TYPES`.
- [ ] **Step 3:** Implement the `models.py` change.
- [ ] **Step 4:** Update the four key-set assertions (test_cli test_detect_json, test_pipeline test_run_returns_manifest_entries and the two in test_t004_acceptance) to add `"event"`. Run `python -m pytest -q` and confirm it passes.
- [ ] **Step 5:** Write the failing matching and label tests in `tests/test_evaluate.py` (see the test plan), then implement `Label`, `LABEL_TYPES`, `to_event`, `temporal_iou`, `match_segments` and `load_labels` until they pass.
- [ ] **Step 6:** Write the failing `score_case`/`summarize` tests on the worked example below, then implement both until they pass.
- [ ] **Step 7:** Write the failing `evaluate_dir` validation tests (no detection needed), then implement `evaluate_dir`.
- [ ] **Step 8:** Write the failing CLI tests (e2e on `burst_video`, plus the error exit 2), then add the `eval` subcommand in `cli.py`. Run `python -m pytest -q tests/test_evaluate.py`; it must pass.
- [ ] **Step 9:** Update the three spec AC lines listed under Files.
- [ ] **Step 10:** Verify with:
  - `python -m pytest -q`: quote the summary line.
  - `PATH=/nonexistent python -m pytest -q`: no new failures compared with main.
  - The e2e command, run by hand:
    ```bash
    mkdir -p /tmp/t010/burst && cp <burst.mp4> /tmp/t010/burst/video.mp4
    printf '[{"start":20,"end":21,"type":"goal"},{"start":50,"end":51,"type":"controversy"},{"start":5,"end":7,"type":"chance"}]' > /tmp/t010/burst/labels.json
    sportscut eval /tmp/t010 --json
    ```
    It prints one JSON line with the keys `f1, precision, recall, event_accuracy, per_event, precision_at_5, per_match`.

## Worked example (the `score_case` unit test)
**Segments:**
- A [0,10] score 5, event goal
- B [20,30] score 4, event save
- C [40,50] score 3, event other
- D [60,70] score 2, event goal

**Labels:**
- L0 [2,6] goal
- L1 [22,26] goal
- L2 [42,46] foul
- L3 [80,85] red_card

**Matching:** A-L0, B-L1 and C-L2 match because each segment contains its label. D and L3 stay unmatched.

**`summarize` must give:**
- precision 0.75, recall 0.75, f1 0.75
- event_accuracy 0.6667
- precision_at_5 0.75
- per_event:
  - goal `{precision 0.5, recall 0.5, f1 0.5}`
  - save `{precision 0.0, recall None, f1 None}`
  - red_card `{precision None, recall 0.0, f1 None}`
  - controversy all None
  - other `{1.0, 1.0, 1.0}`

## E2E expectation (conftest `burst_video`; the detector finds 3 segments of about 12 s around 20 s, 50 s and 75 s, all event other)
With the labels from Step 10, the report is:
- precision, recall and f1 are each 0.6667.
- event_accuracy is 0.0.
- precision_at_5 is 0.6667.
- per_event:
  - goal: precision None, recall 0.0, f1 None.
  - controversy: precision None, recall 0.0, f1 None.
  - other: precision 0.0, recall 0.0, f1 0.0.
  - save and red_card: all None.
- per_match is `[{match:'burst', labels:3, predictions:3, ...}]`.

## Review focus
1. **A long clip covering two labels:** it must take only one of them (one-to-one), and the other label counts as fn.
2. **Two overlapping clips on one label:** only one of them counts as tp, and the other is fp.
3. **A CSV time past 59 minutes, e.g. `93:05`:** it parses to 5585 s, while `12:60` is rejected.
4. **Mixed-case or space-padded types in labels (` Goal `):** they are accepted as `goal`, but an unknown type (`penalty`) is rejected with the path named.
5. **A case directory with no video, or with two videos:** it fails before any detection runs, with exit code 2.

## Assumptions
- Eval layout: `DIR/<match>/` holds one video plus `labels.json` or `labels.csv`.
- Predictions come from `find_highlights` with its default options (top=10, min_len=10, max_len=30), the same defaults as `sportscut cut`.
- `importance` is parsed but not used in this task.
- Precision@5 counts any matched top-5 clip as a hit, whatever its type.

## Test plan

- tests/test_models.py:
- Update test_to_dict_shape_order_and_values to the 5-key dict and key order.
- test_event_roundtrip: goal is kept, and np.str_ becomes str.
- test_invalid_event_raises: parametrize over 'penalty', 'Goal' and ''.
- test_event_types_constant.
- tests/test_evaluate.py::test_to_event_mapping: parametrize over all 8 LABEL_TYPES.
- tests/test_evaluate.py::test_temporal_iou: (0,6,3,10) gives 0.3, and disjoint intervals give 0.0.
- tests/test_evaluate.py::test_match_rules: parametrize over IoU >= 0.3, IoU just below 0.3, a contained label, and partial overlap with low IoU.
- tests/test_evaluate.py one-to-one tests:
- test_match_one_to_one_two_segments_one_label
- test_match_one_to_one_one_segment_two_labels
- tests/test_evaluate.py::test_load_labels_json_ok: types are stripped and lower-cased, importance is ignored, and an empty list returns [].
- tests/test_evaluate.py::test_load_labels_json_invalid: parametrize over a non-list, a non-object, a missing start, a bool start, a NaN start, a negative start, end <= start, an unknown type and broken JSON. Each case raises ValueError, and the path is in the message.
- tests/test_evaluate.py::test_load_labels_csv_ok: a header, a blank line, a '#' comment, '00:20,00:21,goal' and '93:05,93:12.5,Save'.
- tests/test_evaluate.py::test_load_labels_csv_invalid: parametrize over '12:60', '1:2:3', 2 columns, end <= start and an unknown type. Each case raises ValueError with 'line N' and the path.
- tests/test_evaluate.py::test_score_case_worked_example: the A-D / L0-L3 example, asserting the full summarize dict, including the None values and the key order.
- tests/test_evaluate.py::test_precision_at_5: 7 segments with 3 of the top 5 matched gives 0.6, 2 segments with 1 matched gives 0.5, and 0 segments gives 0.0. With no matches, event_accuracy is None.
- tests/test_evaluate.py::test_evaluate_dir_validation: tmp dirs covering not a directory, no cases, both label files, zero videos and two videos. monkeypatch sportscut.detect.find_highlights to fail if called, which proves the validation happens before detection.
- tests/test_evaluate.py::test_evaluate_dir_aggregates_cases: two cases ('a', 'b') with dummy video files and a monkeypatched find_highlights that returns hand-made Segments for each video. Assert the summed totals and the per_match order and keys. No ffmpeg is needed.
- tests/test_evaluate.py::test_cli_eval_e2e (uses the burst_video fixture): copy the video to tmp/burst/video.mp4, write the AC10 labels and call main(['eval', dir, '--json']) with capsys. Assert exit 0, one stdout line and the AC10 values. Also check that main(['eval', dir]) prints indent=2 JSON that parses to the same dict.
- tests/test_evaluate.py::test_cli_eval_error_exit_2: a missing dir and a case without a video each give exit 2, `sportscut eval: error:` on stderr and empty stdout.
- Key-set updates: tests/test_cli.py::test_detect_json, tests/test_pipeline.py::test_run_returns_manifest_entries and tests/test_t004_acceptance.py (2 assertions) gain 'event'.
- Tester: tests/test_t010_acceptance.py, written independently from AC1-AC12. It includes at least the worked example, the CSV minute > 59 case, the one-to-one cases, the burst_video CLI e2e, and a check that the API response keys are unchanged (via TestClient with a monkeypatched pipeline.run).

## Deviations

- Review round 2 added focused hardening tests for path-qualified CSV/JSON decoding errors and for ignoring dot-prefixed video metadata files. These are small extensions requested by the review nits and do not change the evaluation metrics or public report shape.
