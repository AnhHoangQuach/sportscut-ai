# T-010: Add event types to segments and a `sportscut eval` command with per-event metrics

Request R-003. Plan: `docs/superpowers/plans/2026-11-23-t-010-add-event-types-to-segments-and.md`.

## Product Owner request

Highlight theo sự kiện: gắn nhãn bàn thắng, cứu thua, thẻ đỏ, pha tranh cãi. Người dùng lọc "chỉ bàn thắng" hoặc "top 5 pha hay".

## Goal

Goal of R-003: every highlight carries an event label (goal, save, red_card, controversy, other), and the user can ask for `--events goal` (goals only) or `--top 5` (top 5 plays). We will know it works when `sportscut eval tests/fixtures/eval --json` prints `{"f1", "precision", "recall", "event_accuracy", "per_event": {"goal": {"precision", "recall", "f1"}, ...}, "precision_at_5", "per_match": [...]}` and per-event recall on the synthetic set is at least 0.9, with goal recall at least 0.95. Approaches considered: (a) cheap rule-based classifiers per event on ffmpeg signals (audio shape, whistle tone, scoreboard-region pixel change, red-dominant close-ups), each gated by the eval; (b) a learned model (logistic regression over per-segment features), which needs labelled real matches we don't have yet; (c) vision/OCR models, which are heavy and break the CPU budget. We pick (a) because it needs no data, no ML and no extra install, and (b)/(c) can come later as optional extras if the numbers fall short. This task: add `event: str = "other"` to `Segment` (kept in `to_dict`); load labels from `labels.json` (`[{start, end, type, importance}]`) and `labels.csv` (`mm:ss,mm:ss,type`); match one-to-one (temporal IoU ≥ 0.3, or the clip fully contains the label); compute overall metrics plus per-event and type accuracy over matched pairs; add the `sportscut eval DIR --json` subcommand. Unit tests use hand-made segments and labels, plus one end-to-end run on a conftest synthetic video. Assumptions: the label vocabulary is `goal, save, red_card, controversy, chance, yellow_card, foul, other`, and labels outside the four R-003 types are scored as `other`. This must start after R-001 (T-001..T-005: `Segment`, `find_highlights`, `pipeline.run`, the API) is merged on main; if any of it is missing, report BLOCKED and do not re-create it.

## Acceptance criteria

- AC1: `sportscut.models.EVENT_TYPES == ('goal','save','red_card','controversy','other')`. `Segment` has `event: str = 'other'`, and `Segment(start=1.0,end=3.5,score=0.8,reason='crowd noise').to_dict()` equals `{'start':1.0,'end':3.5,'score':0.8,'reason':'crowd noise','event':'other','event_confidence':0.0}` with keys in that order. `event='goal'` round-trips, and `event=np.str_('save')` gives a native `str`. An event outside EVENT_TYPES ('penalty', 'Goal', '') raises ValueError. (updated by T-012)
- AC2: `sportscut detect VIDEO --json` items and `pipeline.run` / highlights.json entries now have exactly the keys {start,end,score,reason,event,event_confidence} and {start,end,score,reason,event,event_confidence,file} respectively, with event 'other' and event_confidence 0.0. The `POST /highlights` response items have exactly the keys {start,end,score,reason,event,event_confidence,clip_url}. The full `python -m pytest -q` passes. (updated by T-012)
- AC3: `sportscut.evaluate.to_event` maps goal, save, red_card and controversy to themselves, and maps chance, yellow_card, foul and other to 'other'. `LABEL_TYPES` is the 8-type vocabulary in the order goal, save, red_card, controversy, chance, yellow_card, foul, other.
- AC4: `load_labels('labels.json')` parses a list of `{start,end,type[,importance]}` into `Label(start,end,type)`, with the type stripped and lower-cased. An empty list returns []. Each of the following raises ValueError, and the message contains the file path: a non-list top level, a non-object item, a missing, bool, non-finite or negative start, end <= start, an unknown type, or invalid JSON.
- AC5: `load_labels('labels.csv')` parses `mm:ss,mm:ss,type` lines. '00:20,00:21,goal' gives Label(20.0,21.0,'goal'), '93:05,93:12.5,Save' gives Label(5585.0,5592.5,'save'), and an optional 'start,end,type' header, blank lines and '#' lines are skipped. Each of the following raises ValueError, and the message contains the path and 'line N': '12:60', '1:2:3', a wrong column count, end <= start, or an unknown type.
- AC6: `temporal_iou(0,6,3,10) == 0.3`. `match_segments` matches a pair when IoU >= 0.3 or when the segment fully contains the label: seg [0,6] vs label [3,10] matches, [0,6] vs [3,10.1] does not, [10,20] vs [12,14] matches (contained), and [10,20] vs [17,25] does not. Matching is one-to-one: two segments [10,20] and [11,21] with one label [12,18] give exactly [(0,0)], and one segment [0,30] with labels [5,7] and [20,22] gives exactly [(0,0)].
- AC7: `summarize(score_case(...))` on the worked example in the spec (segments A-D, labels L0-L3) returns precision 0.75, recall 0.75, f1 0.75, event_accuracy 0.6667 and precision_at_5 0.75, plus per_event goal {0.5,0.5,0.5}, save {precision 0.0, recall None, f1 None}, red_card {precision None, recall 0.0, f1 None}, controversy all None and other {1.0,1.0,1.0}. The top-level key order is f1, precision, recall, event_accuracy, per_event, precision_at_5. per_event has exactly the 5 EVENT_TYPES keys, each holding exactly {precision, recall, f1}.
- AC8: Precision@5 ranks segments by (-score, start), takes the top min(5, n) and divides the matched ones by min(5, n). With 7 segments where 3 of the top 5 match, it is 0.6. With 2 segments where 1 matches, it is 0.5. With no segments, it is 0.0. With no matched pairs, event_accuracy is None.
- AC9: `evaluate_dir` raises ValueError, before calling find_highlights, for each of: a path that is not a directory ('not a directory'), no case subdirectories ('no eval cases found'), a case with both labels.json and labels.csv ('has both'), and a case with zero or two videos (.mp4/.mkv/.mov) ('expected exactly one video'). It sums counts over cases and returns per_match entries, sorted by directory name, with exactly the keys match, labels, predictions, f1, precision, recall, event_accuracy, precision_at_5. After validation and detection, it runs `scoreboard.tag_goals` before scoring. (updated by T-013)
- AC10: For a temp dir `burst/` holding the conftest burst_video as video.mp4 and labels.json `[{start:20,end:21,type:goal},{start:50,end:51,type:controversy},{start:5,end:7,type:chance}]`, `sportscut eval DIR --json` exits 0 and prints exactly one line of JSON with the keys f1, precision, recall, event_accuracy, per_event, precision_at_5 and per_match. In that output:
- f1, precision and recall are each 0.6667.
- event_accuracy is 0.0.
- precision_at_5 is 0.6667.
- per_event.goal.recall is 0.0 and per_event.other.precision is 0.0.
- per_match is a single entry with match 'burst', labels 3 and predictions 3.
Without --json, the same report is printed with indent=2.
- AC11: `sportscut eval` on a bad directory (missing, or a case with no video) prints `sportscut eval: error: <msg>` to stderr, prints nothing to stdout and exits 2. `sportscut eval --help` lists DIRECTORY and --json.
- AC12: The diff does not change api.py, detect.py, pipeline.py, export.py, conftest.py or pyproject.toml, and adds no dependency. Specs T-035 AC5, T-002 AC9 and T-004 AC1 are updated to include `event`. `PATH=/nonexistent python -m pytest -q` has no new failures compared with main. The new tests that need ffmpeg skip with 'ffmpeg and ffprobe are required on PATH'.

## Out of scope

- Event classifiers (audio shape, whistle tone, scoreboard-region change, red-dominant close-ups): the detector keeps emitting event 'other' in this task.
- The synthetic labelled event set in tests/fixtures/eval/ and reaching the R-003 targets (per-event recall >= 0.9, goal recall >= 0.95). Those belong to later R-003 tasks that use this eval.
- `--events` and `--top N` filtering on cut/detect/API, and exposing `event` in the POST /highlights response.
- Importance-weighted metrics or using `importance` to rank precision@5.
- Per-event metrics inside per_match entries, confusion matrices, a CI workflow and a stored baseline file.
- Optimal (Hungarian) matching, h:mm:ss CSV times, and video formats other than .mp4/.mkv/.mov.
- Logistic-regression or vision/OCR models, and any new dependency.

## Decisions

- T-010 (R-003): `Segment` gets `event: str = 'other'` as its last field. It is validated against `sportscut.models.EVENT_TYPES = ('goal','save','red_card','controversy','other')` (exact lowercase match), and `to_dict()` emits it as the last key. As a result, `detect --json` items and the highlights.json/pipeline.run entries gain `event`. This updates T-035 AC5, T-002 AC9 and T-004 AC1. The POST /highlights response keys stay unchanged.
- T-010 (R-003): The label vocabulary is `LABEL_TYPES = (goal, save, red_card, controversy, chance, yellow_card, foul, other)`. Types are stripped and lower-cased on load, and an unknown type is a ValueError. chance, yellow_card, foul and other are scored as event 'other' (`to_event`).
- T-010 (R-003): The eval lives in `sportscut/evaluate.py` (not `eval.py`, to avoid shadowing the builtin). It reuses `eval_player.prf`, calls `detect.find_highlights` through the module with default options, then calls `scoreboard.tag_goals` through the module before scoring, and validates every case before running any detection. (updated by T-013) (updated by T-014: `audio_cues.tag_saves` runs after `scoreboard.tag_goals` and before scoring)
- T-010 (R-003): Eval layout: `DIR/<match>/` with exactly one video (.mp4/.mkv/.mov) and exactly one of labels.json or labels.csv. Subdirectories without labels are ignored. Errors are ValueError, and the CLI turns them into `sportscut eval: error: <msg>` with exit 2 (the same for OSError and MediaError), mirroring eval-player.
- T-010 (R-003): labels.json is a list of {start, end, type} in seconds. `importance` and other keys are accepted and ignored. labels.csv is `mm:ss,mm:ss,type`: minutes may exceed 59, seconds are 00-59 with an optional fraction, and an optional `start,...` header, blank lines and '#' lines are skipped.
- T-010 (R-003): Matching is one-to-one. A candidate pair needs temporal IoU >= 0.3 or a segment that fully contains its label. Candidates are taken greedily by (-iou, label index, segment index).
- T-010 (R-003): Overall precision, recall and f1 are micro-averaged over all matches (0.0 when undefined). event_accuracy is the share of matched pairs whose segment event equals the scored label event, or null when there are no matched pairs. In per_event, a matched pair counts as tp only if both sides have that event. Precision, recall and f1 are null when their denominator is 0, and f1 is null if either input is null.
- T-010 (R-003): precision_at_5 takes, per match, the top min(5, n) segments by (-score, start) and counts those matched to any label. Hits and totals are pooled across matches. It is 0.0 when there are no segments.
- T-010 (R-003): The report key order is f1, precision, recall, event_accuracy, per_event (all 5 EVENT_TYPES in order), precision_at_5, per_match. per_match entries are {match, labels, predictions, f1, precision, recall, event_accuracy, precision_at_5}, sorted by directory name. Floats are rounded to 4 decimals.
- T-010 (R-003): Updating the key-set assertions in tests/test_cli.py, tests/test_pipeline.py and tests/test_t004_acceptance.py to include 'event' follows an intended spec change. It does not weaken those tests, and nothing else in them changes.
- Tech Lead (dev_blocked): 2026-11-23 T-010: restart after T-005 is merged because the failure is the intended precondition detecting a missing R-001 dependency, not an implementation defect; T-010 must depend on T-005.
- Updated by T-010 review round 2: malformed label text and oversized JSON numbers raise path-qualified `ValueError`s, and dot-prefixed metadata files are ignored when counting case videos.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-035-scaffold-sportscut-packaging-version-cli-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-002-detect-highlight-segments-from-audio-excitement-design.md`
- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`

## Updated by T-023

- Updated by T-023: `commentary.ClipFacts` carries the manifest entry's validated `event` into the
  deterministic Vietnamese metadata template. The event vocabulary and existing
  `sportscut eval` F1 gate are unchanged.
Updated by T-055: evaluate_dir calls detect.find_highlights(video, top=None) like pipeline.run and adds top-level goal_coverage.
