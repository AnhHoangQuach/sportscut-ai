# Plan T-012: Let users filter by event and pick the top N in the CLI and API

Design: `docs/superpowers/specs/2026-11-23-t-012-let-users-filter-by-event-and-design.md`.

## Implementation plan

# T-012: Let users filter by event and pick the top N in the CLI and API

Request R-003. Depends on T-010 (merged: `Segment.event`, `EVENT_TYPES`, `sportscut eval`). It edits `sportscut/api.py`, so it runs one after the other with any other api.py task (for example T-007).

## Context (current code)

- `sportscut/models.py`: `EVENT_TYPES = ('goal','save','red_card','controversy','other')`. `Segment(start, end, score, reason, event='other')` is a frozen dataclass. `to_dict()` returns keys start, end, score, reason, event.
- `sportscut/detect.py`: `find_highlights(video, top=10, min_len=10, max_len=30)` greedily keeps non-overlapping windows sorted by `(-z, start)`, stops at `top`, and returns them in time order. Scores are z-scores >= `MIN_Z` (3.0), so they are always positive.
- `sportscut/pipeline.py`: `run()` calls `find_highlights(top=top)` and then `export_clips()`, which sorts by `(start, end)` and writes `highlights.json`. The manifest entries are `{**segment.to_dict(), 'file': 'clip_NN.mp4'}`.
- `sportscut/cli.py`: `cut` has `--top/--min-len/--max-len` and calls `run(...)`.
- `sportscut/api.py`: `POST /highlights` has form fields `file|url, top, min_len, max_len`. Its response items are `{start,end,score,reason,clip_url}` (the `event` key was deliberately left out by T-010). `GET /highlights/{job_id}/clips/{name}` serves a clip. **No JSON job read exists yet.** This task adds `GET /highlights/{job_id}`.
- No event classifier exists yet, so every segment is `other`. This task is plumbing only.

## Design

The pipeline order becomes: **detect all candidates -> (classifiers will go here) -> filter by events -> rank and take the top N -> export in time order.** `top` now applies after the filter, so 'top 5 goals' means the 5 best goals among all candidates, not the goals that happen to be in the 5 loudest moments.

### 1. `sportscut/models.py`

Add a last field `event_confidence: float = 0.0` (0.0 = no classifier has judged the segment). `__post_init__` raises `ValueError('event_confidence must be between 0 and 1')` unless `0.0 <= event_confidence <= 1.0`; NaN fails that comparison, so it is rejected too. `to_dict()` adds `'event_confidence': float(self.event_confidence)` as the last key. The key order becomes start, end, score, reason, event, event_confidence.

### 2. New `sportscut/ranking.py`

```python
from collections.abc import Iterable
from sportscut.models import EVENT_TYPES, Segment

EVENT_PRIORITY = {"goal": 5, "red_card": 4, "controversy": 3, "save": 2, "other": 1}

def parse_events(text: str) -> tuple[str, ...]: ...
def select_segments(segments: Iterable[Segment], top: int, events: Iterable[str] | None = None) -> list[Segment]: ...
```

- `parse_events(text)`: split on `,`, then strip and lower-case each item. Every item must be in `EVENT_TYPES`; an empty item counts as unknown. The first bad item raises `ValueError(f"unknown event {name!r}; choose from goal, save, red_card, controversy, other")`. Duplicates are removed and first-seen order is kept. Examples: `'Goal, save,goal'` -> `('goal','save')`. `''`, `'goal,'` and `'goal,,save'` raise (unknown event `''`). `'penalty'` raises (unknown event `'penalty'`).
- `select_segments(segments, top, events=None)`:
  1. `top < 1` -> `ValueError('top must be >= 1')`.
  2. If `events is not None`: every name must be in `EVENT_TYPES`, otherwise raise the same `unknown event` ValueError. Keep only segments whose `event` is in `events`. An empty `events` keeps nothing.
  3. Rank by the key `(-(s.score * EVENT_PRIORITY[s.event]), -EVENT_PRIORITY[s.event], s.start, s.end)` and take the first `top`.
  4. Return the kept segments sorted by `(start, end)` (time order).

### 3. `sportscut/detect.py`

The signature becomes `find_highlights(video, top: int | None = 10, min_len=10, max_len=30)`. `top=None` means no cap: every non-overlapping candidate is returned. The check becomes `if top is not None and top < 1`, and the loop stops only `if top is not None and len(kept) == top`. Nothing else changes, so the default behaviour and the eval (which calls the default `top=10`) stay byte-identical.

### 4. `sportscut/pipeline.py`

```python
def run(video, out_dir, top: int = 10, min_len: float = 10, max_len: float = 30,
        events: Iterable[str] | None = None) -> list[dict]:
```

1. `if top < 1: raise PipelineError('top must be >= 1')` comes first, before `require_ffmpeg()`, so a bad value fails before the slow detection runs.
2. `require_ffmpeg()`, then inside the existing `try`: `has_audio` check -> `candidates = find_highlights(video, top=None, min_len=min_len, max_len=max_len)` -> the comment `# event classifiers (later R-003 tasks) label candidates here` -> `segments = select_segments(candidates, top=top, events=events)`. ValueError and MediaError become PipelineError, as before.
3. `export_clips(video, segments, out_dir)` is unchanged. An empty list writes `highlights.json` = `[]\n` and cuts no clip, and `run` returns `[]`.

Why behaviour is unchanged when every segment is `other`: the greedy keep-loop with a break at N gives exactly the first N windows that the uncapped loop accepts, in `(-score, start)` order. Ranking with priority 1 for all segments picks the same N. Leave `find_highlights` imported by name in pipeline.py, so tests can monkeypatch `sportscut.pipeline.find_highlights`.

### 5. `sportscut/cli.py`

In `cut`, add `--events` with `type=_events_arg`, `default=None` and help `comma-separated events to keep: goal,save,red_card,controversy,other`. `_events_arg(text)` calls `ranking.parse_events` and re-raises a ValueError as `argparse.ArgumentTypeError(str(exc))`, so argparse prints `sportscut cut: error: argument --events: unknown event 'penalty'; choose from ...` and exits 2 before any ffmpeg call. Pass it on as `run(..., events=args.events)`. The output is unchanged: one clip path per line, and nothing on stdout (exit 0) when the filter removes everything. `detect` gets no new flag.

### 6. `sportscut/api.py`

- `POST /highlights` gets a new form field `events: str | None = Form(None)`. Blank or whitespace-only counts as absent (`None`). Validation order: exactly-one source (422), `min_len <= max_len` (422), then `events` -> `ranking.parse_events` (a ValueError gives 422 with `detail = str(exc)`), then the URL check (400). All of these happen before a job dir is created and before `pipeline.run`. Always call `pipeline.run(input_path, job_dir / CLIPS_DIR, top=top, min_len=min_len, max_len=max_len, events=<tuple or None>)`.
- Add a helper `_highlights(request, job_id, entries) -> list[dict]` that builds items with the keys, in this order, `start, end, score, reason, event, event_confidence, clip_url`. Use `entry.get('event', 'other')` and `entry.get('event_confidence', 0.0)` so manifests and stubs written before T-012 still load. The POST response stays `{job_id, highlights: _highlights(...)}`.
- Add a helper `_manifest(job_id) -> list[dict]` that holds the existing get_clip checks (canonical lowercase UUID, `clips/highlights.json` exists, parses to a list of objects). Any failure raises `HTTPException(404, 'not found')`. `get_clip` uses it, and its behaviour is unchanged.
- New `@app.get('/highlights/{job_id}', name='get_job')` `def get_job(request: Request, job_id: str, event: str | None = None) -> dict`. A non-blank `event` goes through `parse_events` first (comma lists are allowed; unknown gives 422 with `detail = str(exc)`, before the job lookup). Then it calls `_manifest(job_id)` (404 if missing), keeps the entries whose `entry.get('event','other')` is in the set when a filter is given (manifest order, which is time order), and returns `{'job_id': job_id, 'highlights': _highlights(...)}`. A blank `?event=` means no filter. No `top` on the read. It never serves `input`, `job.json` or files.

### 7. Docs

- `README.md`, CLI and API sections: add `sportscut cut match.mp4 --out clips --events goal --top 5`, `-F events=goal,save`, and `GET /highlights/<job_id>?event=goal`.
- Update the specs that this task changes, adding the marker `(updated by T-012)` and **keeping every existing `(updated by T-010)` marker** (tests/test_t010_acceptance.py checks those):
  - T-035 AC5 (to_dict keys now end with event_confidence)
  - T-002 AC1 (`top=None` = uncapped) and AC9 (detect --json keys)
  - T-004 AC1 (`run(..., events=None)`, entry keys)
  - T-005 AC2 (highlight keys now include event and event_confidence)
  - T-010 AC1 and AC2 (this reverses 'POST /highlights response keys are unchanged')

## Existing tests that change on purpose (key-set updates only, like the T-010 precedent)

- `tests/test_models.py:23-25`, `tests/test_t010_acceptance.py:33-35,52,58,64`, `tests/test_cli.py:54`, `tests/test_pipeline.py:27`, `tests/test_t004_acceptance.py:63`: add `event_confidence` (value 0.0) to the expected keys or dicts.
- `tests/test_api.py:51,57` and `tests/test_t005_acceptance.py:83,86`: the response key set becomes `{start,end,score,reason,event,event_confidence,clip_url}`, and the manifest comparison excludes only `file`.
- `tests/test_t010_acceptance.py:228`: rename it to `test_t010_ac2_api_response_keys` (renaming is optional) and assert the new 7-key set.
- `tests/test_api.py:182` and `tests/test_t005_acceptance.py:180`: the expected pipeline kwargs gain `'events': None`.

No other assertion in those files changes. This follows an intended spec change and does not weaken any test.

## Steps (TDD: each test is red before the code exists)

1. `tests/test_models.py`: tests for the event_confidence default, order, range and native float -> red. Implement models.py, then apply the key-set updates listed above -> green.
2. `tests/test_ranking.py`: parse_events and select_segments on the worked example -> red (ImportError). Create ranking.py -> green.
3. `tests/test_detect.py`: on burst_video, `find_highlights(top=None)` returns >= 3 segments, its first 2 by (-score, start) equal `find_highlights(top=2)`, and `top=0` still raises -> red. Change detect.py -> green.
4. `tests/test_pipeline.py`: monkeypatch `sportscut.pipeline.find_highlights` to a spy that returns the worked-example segments; check ordering and filtering, the empty result, `top=None` passed to the detector, top=0 -> PipelineError before ffmpeg -> red. Change pipeline.py -> green.
5. `tests/test_cli.py`: `--events` parsing, error and empty-result tests -> red. Change cli.py -> green.
6. `tests/test_api.py`: the POST events field, 422 checks, response keys, GET job read and ?event= tests -> red. Change api.py (plus the kwargs updates) -> green.
7. Update README and the specs, then run the full suite and the eval check.

Keep the diff under about 400 changed lines. Add no dependency, and do not touch `pyproject.toml`, `conftest.py`, `export.py`, `evaluate.py`, the web page or `agent-office/`.

## Worked example (hand-built segments, used by unit and acceptance tests)

| id | start | end | score | event | rank = score x priority |
|---|---|---|---|---|---|
| F | 0 | 5 | 10.0 | other | 10 |
| A | 10 | 20 | 4.0 | other | 4 |
| B | 30 | 40 | 2.0 | goal | 10 |
| C | 50 | 60 | 3.0 | save | 6 |
| D | 70 | 80 | 5.0 | red_card | 20 |
| E | 85 | 89 | 6.0 | controversy | 18 |

- top=3, no filter -> D, E, then B beats F on the tie at 10 (goal wins) -> returned in time order **[B, D, E]**.
- top=4 -> [F, B, D, E].
- events=('goal',), top=10 -> [B].
- events=('save','goal'), top=5 -> [B, C].
- events=('other',), top=1 -> [F].
- events=('controversy','red_card'), top=1 -> [D].
- all-`other` segments with events=('goal',) -> [].
- two `other` segments with equal score 4.0 at start 30 and 10, top=1 -> the one at start 10.

All ends are <= 89, so the segments fit inside the 90 s `burst_video` for pipeline tests that really cut clips.

## Proof commands

- `python -m pytest -q` -> all pass (quote the summary line).
- `python -m pytest -q tests/test_t010_acceptance.py` -> passes unchanged, apart from the key-set lines. AC10 still gives f1/precision/recall 0.6667, so eval F1 is unchanged.
- `sportscut cut <burst.mp4> --out /tmp/t012 --events goal` -> exit 0, no stdout, `/tmp/t012/highlights.json` is `[]`.
- `sportscut cut <burst.mp4> --out /tmp/t012b --events penalty` -> exit 2, stderr contains `argument --events: unknown event 'penalty'`.

## Assumptions

- 'Output JSON' means the `POST /highlights` and `GET /highlights/{job_id}` responses, `detect --json` (through `to_dict`) and `highlights.json`. `cut` keeps printing clip paths.
- Until classifiers exist, `event_confidence` is 0.0 for every segment.
- The 'job read' is a new JSON endpoint `GET /highlights/{job_id}`. The HTML page `/jobs/{id}` stays a later R-002 task.
- The web upload page gets no events control in this task.

## Test plan

- tests/test_models.py (unit): event_confidence default 0.0, key order, 0.75 round-trip, numpy float -> native float, and ValueError for -0.1/1.5/nan. Update the existing key-order assertions to include event_confidence.
- tests/test_ranking.py (unit, no ffmpeg): EVENT_PRIORITY values; parse_events normalisation, de-duplication and errors (''/'goal,'/'goal,,save'/'penalty'/'Goal' accepted); select_segments on the worked-example table for every case in AC3; tie rules (goal beats other at equal rank, earlier start wins at equal rank and priority); empty results for an all-filtered input and events=(); ValueError for top=0 and unknown events.
- tests/test_detect.py (integration, burst_video): top=None returns >= 3 segments, and its top 2 by (-score, start) equal find_highlights(top=2); top=0 still raises.
- tests/test_pipeline.py (integration, burst_video + monkeypatched sportscut.pipeline.find_highlights spy returning hand-built segments): top=3 ordering and events; spy received top=None; events=['goal'] gives one clip; an all-filtered input gives [] with highlights.json [] and no mp4; top=0 gives PipelineError with PATH=/nonexistent; with no events and the real detector, top=2 matches find_highlights(top=2). Update the existing key-set assertion.
- tests/test_cli.py: a monkeypatched sportscut.cli.run spy checks that `--events 'Goal, save'` gives events=('goal','save') and that no flag gives None and --top 5 gives top=5; SystemExit code 2 with an 'argument --events: unknown event' stderr for penalty/''/'goal,,save' and no run call; the real burst_video with --events goal gives exit 0, empty stdout and highlights.json []. Update the existing key-set assertion.
- tests/test_api.py (TestClient, SPORTSCUT_DATA_DIR=tmp): POST events forwarded as a tuple, blank -> None; 422 for an unknown event with no job dir and no run call; exact 7-key response item order with defaults for stub entries without event keys; GET /highlights/{job_id} on a hand-written job dir with and without ?event= (single, comma list, no match, blank); 422 for an unknown event; 404 for unknown/non-canonical/uppercase ids; clip_url equals the url_for get_clip. Update the existing key-set and kwargs assertions.
- tests/test_t004_acceptance.py, tests/test_t005_acceptance.py, tests/test_t010_acceptance.py: key-set/kwargs updates only (add event_confidence, and events=None in the pipeline.run kwargs, with the 7-key API set), as listed in the spec. Nothing else changes.
- tests/test_t012_acceptance.py (Tester, written from the ACs, not from the developer tests): one test per AC1-AC16. It uses the worked-example table for the ranking/pipeline/API cases, a hand-written job dir for the GET read, the real burst_video for the empty 'goals only' CLI/API runs, and reads the spec files and README for AC16. The Tester first confirms that the tests fail on main (ImportError for sportscut.ranking, missing --events, 404/405 for GET /highlights/{id}).
- Eval regression: run `python -m pytest -q tests/test_t010_acceptance.py` and confirm AC10 is still f1 0.6667 (no tests/fixtures/eval set exists yet). The detector default path is unchanged.
