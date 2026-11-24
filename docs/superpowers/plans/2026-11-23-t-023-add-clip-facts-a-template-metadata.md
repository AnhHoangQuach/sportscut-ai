# Plan T-023: Add clip facts, a template metadata generator and a `sportscut eval-meta` score

Design: `docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md`.

## Implementation plan

# T-023: Clip facts, a template metadata generator and `sportscut eval-meta`

Request R-005 (Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt).

## Context (what is on main)

- `sportscut/models.py`: `EVENT_TYPES = ('goal','save','red_card','controversy','other')`, and `Segment(start, end, score, reason, event='other')`, which T-010 added.
- `sportscut/export.py`: `MANIFEST_NAME = 'highlights.json'`. The manifest entries are `{start, end, score, reason, event, file}`, and `sportscut.pipeline.run` returns the same entries.
- `sportscut/detect.py`: `PRE_SEC = 8.0` and `POST_SEC = 4.0`. A detected clip puts its audio peak at `start + (end-start) * PRE_SEC / (PRE_SEC + POST_SEC)`.
- `sportscut/cli.py`: the argparse subcommands `detect`, `cut`, `eval`, `eval-player`, `player` and `serve`. The eval commands print `json.dumps(report)` with `--json` and `indent=2` without it. A bad input gives `sportscut <cmd>: error: <msg>` on stderr and exit 2.
- `pyproject.toml` finds the packages with `include = ['sportscut*']`, so the new subpackage `sportscut/commentary/` only needs an `__init__.py`.

## Step 0: precondition (run this first, exactly)

The Tech Lead decided that T-023 runs only after T-004 and T-010 have merged. Run:

```bash
python - <<'EOF'
import importlib
def chk():
    m = importlib.import_module
    yield 'T-035 Segment', lambda: m('sportscut.models').Segment
    yield 'T-010 EVENT_TYPES', lambda: m('sportscut.models').EVENT_TYPES
    yield 'T-010 Segment.event', lambda: m('sportscut.models').Segment(0, 1, 0, 'x').to_dict()['event']
    yield 'T-002 detect PRE_SEC/POST_SEC', lambda: (m('sportscut.detect').PRE_SEC, m('sportscut.detect').POST_SEC)
    yield 'T-003 MANIFEST_NAME', lambda: m('sportscut.export').MANIFEST_NAME
    yield 'T-004 pipeline.run', lambda: m('sportscut.pipeline').run
    yield 'T-010 evaluate.evaluate_dir', lambda: m('sportscut.evaluate').evaluate_dir
missing = []
for name, f in chk():
    try: f()
    except Exception as exc: missing.append(f'{name} ({exc})')
print('READY' if not missing else 'BLOCKED: ' + '; '.join(missing))
EOF
```

Continue only if it prints `READY`. If it does not, stop, report BLOCKED with the missing check, and do not re-create any prerequisite file.

## Design

There are three small modules under a new package `sportscut/commentary/`. They are pure Python with no new dependency and no ffmpeg.

### `sportscut/commentary/facts.py`

```python
@dataclass(frozen=True)
class ClipFacts:
    event: str                       # one of models.EVENT_TYPES
    minute: int | None = None        # 1..130
    home: str | None = None
    away: str | None = None
    competition: str | None = None
    score: str | None = None         # 'H-A', e.g. '2-1'

def facts_from_entry(entry: Mapping, match: Mapping | None = None) -> ClipFacts
```

`ClipFacts.__post_init__` validates strictly and never normalises. It raises `ValueError` with the field name in the message when:

- `event` is not in `EVENT_TYPES`.
- `minute` is not None and is either not an `int` (a `bool` counts as not an int) or outside 1..130.
- `home`, `away` or `competition` is not None and is either not a `str`, empty, different from its `.strip()`, or longer than 40 characters.
- `score` is not None and does not fully match `^\d{1,2}-\d{1,2}$`.

`facts_from_entry` builds a `ClipFacts` from a manifest entry, which needs `start`, `end` and `event`, plus an optional match mapping:

- **Match keys.** The allowed keys are exactly `home`, `away`, `competition`, `score` and `kickoff`. Any other key raises `ValueError('unknown match key: <k>')`. A missing key, or a None value, means unknown.
- **String values.** `home`, `away` and `competition` must be `str`. They are NFC-normalised and stripped, and an empty result becomes None.
- **Score.** `score` is NFC-normalised and stripped, and spaces around `-` are removed, so `' 2 - 1 '` becomes `'2-1'`. ClipFacts then validates it.
- **Kickoff.** `kickoff` is the number of seconds into the video where the match starts. It must be a finite int or float, not a `bool`, and >= 0. Otherwise it raises `ValueError`.
- **Entry times.** `entry['start']` and `entry['end']` must be finite numbers, and `end` must be greater than `start`. Otherwise it raises `ValueError`.
- **Minute.** The minute is computed only when `kickoff` is given:
  - `anchor = start + (end - start) * detect.PRE_SEC / (detect.PRE_SEC + detect.POST_SEC)`, which is the detector's peak.
  - `elapsed = anchor - kickoff`.
  - `minute = None if elapsed < 0 else min(int(elapsed // 60) + 1, 130)`.
  - Example: `{start:1370, end:1382, event:'goal'}` gives anchor 1378. With `kickoff=0` the minute is 23. With `kickoff=120` it is 21. With `kickoff=1400` it is None. With no kickoff it is None.

### `sportscut/commentary/meta.py`

```python
@dataclass(frozen=True)
class ClipMeta:
    title: str
    caption: str
    hashtags: tuple[str, ...]
    def to_dict(self) -> dict  # {'title', 'caption', 'hashtags': list}, in that key order

def generate_meta(facts: ClipFacts, backend: str = 'template') -> ClipMeta
def hashtag(text: str) -> str | None
```

Any backend other than `'template'` raises `ValueError('unknown backend: <name>')`.

The template uses these constants:

- `EVENT_LABELS = {'goal': 'Bàn thắng', 'save': 'Pha cứu thua', 'red_card': 'Thẻ đỏ', 'controversy': 'Tình huống gây tranh cãi', 'other': 'Khoảnh khắc đáng chú ý'}`
- `EVENT_TAGS = {'goal': 'BanThang', 'save': 'CuuThua', 'red_card': 'TheDo', 'controversy': 'TranhCai', 'other': 'KhoanhKhac'}`

With `L = EVENT_LABELS[event]` and `M = f'phút {minute}'`, the teams text `T` is `f'{home} vs {away}'` when both are known, the one known name when only one is, and None when neither is.

**Title.** Use the first of these candidates whose parts are all known and whose length is between 10 and 80:

1. `f'{L}: {T}, {M}'`
2. `f'{L}: {T}'`
3. `f'{L}, {M}'`
4. `f'{L} trong trận đấu'`

Candidate 4 always fits.

**Caption.** Concatenate these parts in order:

1. `L`
2. The match text:
   - `f' trong trận {home} gặp {away}'` if both teams are known,
   - else `f' trong trận đấu của {name}'` if one is known,
   - else `' trong trận đấu'`.
3. `f' ở phút {minute}'` if the minute is known.
4. `f' tại {competition}'` if the competition is known.
5. `'.'`
6. `f' Tỉ số: {score}.'` if the score is known.
7. `' Cùng xem lại khoảnh khắc này!'`

The caption never says who scored, because that is not a fact we have. The 40-character name limits keep it under 300 characters.

**Hashtags.** Start with `['#BongDa', '#' + EVENT_TAGS[event], '#Highlight']`. Then append `hashtag(home)`, `hashtag(away)` and `hashtag(competition)` when they are not None. Drop duplicates case-insensitively, keeping the first. The result is a tuple of 3 to 6 tags.

`hashtag(text)` works as follows:

1. Replace `đ` with `d` and `Đ` with `D`.
2. NFD-normalise and drop characters of category `Mn`.
3. Split on runs of characters that are not `[A-Za-z0-9]`.
4. Upper-case the first character of each non-empty part and join the parts.
5. Return `'#' + result`, or None if the result is empty.

Examples: `'Hà Nội FC'` gives `'#HaNoiFC'`, `'V.League 2026'` gives `'#VLeague2026'`, and `'U23 Việt Nam'` gives `'#U23VietNam'`.

**Worked example.** `generate_meta(ClipFacts('goal', 23, 'Hà Nội FC', 'Hải Phòng', 'V.League 2026', '1-0'))` gives:

- title `'Bàn thắng: Hà Nội FC vs Hải Phòng, phút 23'`
- caption `'Bàn thắng trong trận Hà Nội FC gặp Hải Phòng ở phút 23 tại V.League 2026. Tỉ số: 1-0. Cùng xem lại khoảnh khắc này!'`
- hashtags `('#BongDa', '#BanThang', '#Highlight', '#HaNoiFC', '#HaiPhong', '#VLeague2026')`

`generate_meta(ClipFacts('other'))` gives:

- title `'Khoảnh khắc đáng chú ý trong trận đấu'`
- caption `'Khoảnh khắc đáng chú ý trong trận đấu. Cùng xem lại khoảnh khắc này!'`
- hashtags `('#BongDa', '#KhoanhKhac', '#Highlight')`

### `sportscut/commentary/eval_meta.py`

```python
class MetaCase(NamedTuple):
    id: str
    facts: ClipFacts
    must_mention: list[list[str]]   # groups; a group is met if ANY string appears
    forbidden: list[str]

def load_cases(path) -> list[MetaCase]                 # path = DIR/cases.json
def score_case(case: MetaCase, meta: ClipMeta) -> dict
def evaluate_meta_dir(path) -> dict                    # calls meta.generate_meta(case.facts) via the module
```

**Loading.** `evaluate_meta_dir` raises `ValueError` when:

- DIR is not a directory: `'not a directory: <dir>'`.
- `DIR/cases.json` is missing: `'missing cases.json in <dir>'`.

`load_cases` raises `ValueError` with the file path and `[i]` in the message when:

- The JSON is invalid.
- The top level is not a list, or the list is empty (`'no eval cases'`).
- An item is not an object.
- `id` is not a non-empty str, or is duplicated.
- `facts` is not an object, has an unknown key, or fails ClipFacts validation. A `TypeError` from `ClipFacts(**facts)` is turned into `ValueError`.
- `must_mention` is not a non-empty list of non-empty lists of non-empty strings.
- `forbidden` is not a list of non-empty strings (it may be empty).
- A forbidden string appears, compared case-folded, in the facts text.

**Normalisation.**

- The output text is `title + '\n' + caption + '\n' + ' '.join(hashtags)`, NFC-normalised and case-folded.
- The facts text is `str(minute)` (when known), `score`, `home`, `away` and `competition`, joined by newlines.
- Every needle (a must_mention or forbidden string) is NFC-normalised and case-folded before the substring test.

**Scoring one case.** `score_case` checks four things and collects `problems`, a list of strings:

- **format_ok** is True only when every check below passes. Each failing check adds the problem string shown:
  - The title is 10 to 80 characters (`len`) and equals its `.strip()`: `'title length N'`.
  - The caption is 1 to 300 characters: `'caption length N'`.
  - There are 3 to 8 hashtags: `'hashtag count N'`.
  - Each hashtag fully matches `#[A-Za-z0-9_]+`: `'bad hashtag X'`.
  - The hashtags are unique case-insensitively: `'duplicate hashtag X'`.
- **fact_recall** is the number of met groups divided by the number of groups.
- **hallucinated** is True when either of these holds:
  - Some integer from `re.findall(r'\d+', output)` is not in the set of integers found by `re.findall(r'\d+', facts_text)`. This adds `'number N not in facts'`.
  - Some forbidden string occurs in the output. This adds `'forbidden X'`.
  - Team names that are not in the facts are detected only through each case's `forbidden` list.
- **vi** works like this:
  - Tokens are `re.findall(r'[^\W\d_]+', casefold(NFC(title + ' ' + caption)))`.
  - Remove every token that also occurs among the tokens of home, away and competition.
  - `vi` is True when at least one token remains and at least 30% of the remaining tokens contain a character of `VI_CHARS`. If not, add the problem `'not vietnamese'`.
  - `VI_CHARS = 'àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ'`
- The case score is `fact_recall` if `format_ok and not hallucinated and vi`, and 0.0 otherwise.

`score_case` returns a dict with keys in this order: `id, score, format_ok, fact_recall, hallucinated, vi, problems, title, caption, hashtags`, where hashtags is a list.

**Report.** The report keys are in this order:

- `score`: the mean of the case scores.
- `format_ok`: the share of cases with format_ok.
- `fact_recall`: micro-averaged, i.e. all met groups divided by all groups.
- `hallucination_rate`: the share of hallucinated cases.
- `vi_rate`: the share of vi cases.
- `per_case`: the case results in file order.

All floats are rounded to 4 decimals.

### CLI

Add `eval-meta` to `sportscut/cli.py`, with help `'evaluate clip titles, captions and hashtags'`, a positional `directory` (metavar DIRECTORY) and `--json`. On success it prints the report the same way `eval` does and exits 0. A `ValueError` or `OSError` prints `sportscut eval-meta: error: <msg>` to stderr, prints nothing to stdout and exits 2.

### Fixture `tests/fixtures/eval_meta/cases.json` (committed, UTF-8, NFC)

The file is a JSON list of exactly these 8 cases, in this order. The facts use ClipFacts field names, and omitted fields are null or absent.

1. **`goal_full`**
   - facts: goal, minute 23, `Hà Nội FC` vs `Hải Phòng`, `V.League 2026`, score `1-0`
   - must_mention: `[['bàn thắng'],['Hà Nội FC'],['Hải Phòng'],['phút 23'],['1-0'],['V.League']]`
   - forbidden: `['Viettel','Nam Định']`
2. **`save_teams`**
   - facts: save, minute 67, `Arsenal` vs `Chelsea`, `Premier League`
   - must_mention: `[['cứu thua'],['Arsenal'],['Chelsea'],['phút 67'],['Premier League']]`
   - forbidden: `['Tottenham','Liverpool']`
3. **`red_card_minute_only`**
   - facts: red_card, minute 88
   - must_mention: `[['thẻ đỏ'],['phút 88']]`
   - forbidden: `['Real Madrid']`
4. **`controversy_no_minute`**
   - facts: controversy, `Thép Xanh Nam Định` vs `Hoàng Anh Gia Lai`, `Cúp Quốc gia`
   - must_mention: `[['tranh cãi'],['Nam Định'],['Hoàng Anh Gia Lai'],['Cúp Quốc gia']]`
   - forbidden: `['Hà Nội']`
5. **`other_bare`**
   - facts: other
   - must_mention: `[['khoảnh khắc']]`
   - forbidden: `['Barcelona']`
6. **`goal_long_names`**
   - facts: goal, minute 120, `Câu lạc bộ Bóng đá Công an Hà Nội` (33 chars) vs `Becamex Bình Dương Football Club` (32 chars), `Night Wolf V.League 1`, score `3-2`
   - must_mention: `[['bàn thắng'],['Công an Hà Nội'],['Bình Dương'],['phút 120'],['3-2']]`
   - forbidden: `['Thể Công']`
   - Candidate 1 is 90 characters, so the title falls back to candidate 2, which is exactly 80.
7. **`goal_u23`**
   - facts: goal, minute 45, `U23 Việt Nam` vs `U23 Thái Lan`, `SEA Games 33`, score `2-2`
   - must_mention: `[['bàn thắng'],['Việt Nam'],['Thái Lan'],['phút 45'],['2-2'],['SEA Games']]`
   - forbidden: `['Indonesia','Malaysia']`
8. **`save_competition_only`**
   - facts: save, minute 5, `Champions League`, score `0-0`
   - must_mention: `[['cứu thua'],['phút 5'],['0-0'],['Champions League']]`
   - forbidden: `['Bayern']`

The expected template baseline is `score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0`.

### README

Add the section `## Bình luận AI: đo chất lượng tiêu đề, caption, hashtag (eval-meta)`. It contains:

- The command `python -m sportscut eval-meta tests/fixtures/eval_meta --json`.
- The case format (facts, must_mention any-of groups, forbidden).
- The format rules and the score definition, in one short paragraph.
- The template baseline measured in T-023 as a JSON block holding the five headline keys exactly as printed (per_case left out).
- A note that every R-005 PR reports this score and must not lower it.

## Files

- Create:
  - `sportscut/commentary/__init__.py` (empty)
  - `sportscut/commentary/facts.py`
  - `sportscut/commentary/meta.py`
  - `sportscut/commentary/eval_meta.py`
  - `tests/fixtures/eval_meta/cases.json`
  - `tests/test_commentary_facts.py`
  - `tests/test_commentary_meta.py`
  - `tests/test_eval_meta.py`
- Change:
  - `sportscut/cli.py` (the eval-meta subcommand only)
  - `README.md` (the new section only)
- The Tester adds `tests/test_t023_acceptance.py`.
- Do not change `detect.py`, `evaluate.py`, `models.py`, `export.py`, `pipeline.py`, `api.py`, `pyproject.toml` or `tests/conftest.py`.

## Steps (TDD; run `python -m pytest -q <file>` after each and watch it fail, then pass)

0. Run the precondition. It must print READY.
1. **ClipFacts validation.**
   - Test: valid construction; each invalid field raises ValueError (event 'penalty', minute 0, 131, True, 2.0, a 41-character name, `' Arsenal'`, score `'2:1'`).
   - Code: the dataclass and `__post_init__`.
2. **facts_from_entry.**
   - Test: the minute examples above; a minute at exactly kickoff is 1; normalisation of names and score; unknown match key; bad kickoff (-1, True, nan, '10'); bad start/end; event carried from the entry; `match=None` gives only the event.
   - Code: the function.
3. **hashtag() and generate_meta.**
   - Test: the three hashtag examples; `hashtag('!!!')` is None; both worked examples above; title fallbacks (goal_long_names facts give `'Bàn thắng: Câu lạc bộ Bóng đá Công an Hà Nội vs Becamex Bình Dương Football Club'`; minute only gives `'Thẻ đỏ, phút 88'`; one team gives `'Bàn thắng: Arsenal'` and a caption containing `'trong trận đấu của Arsenal'`); duplicate team tags collapse (home and away `'Ha Noi'`/`'Hà Nội'` give 4 tags); `backend='llm'` raises ValueError; `to_dict` key order.
   - Code: meta.py.
4. **score_case.**
   - Test with hand-made ClipMeta values: each format problem; a number not in facts ('phút 24' when the minute is 23) makes hallucinated True; a forbidden name in the caption; vi False for an English-only caption; recall 0.5 when one of two groups is met; any-of matching; a hashtag counts for must_mention; a case score of 0 when hallucinated.
   - Code: the scorer.
5. **load_cases and evaluate_meta_dir.**
   - Test: each loader error; a monkeypatched `meta.generate_meta` returning bad output lowers the score; aggregation over two cases (one good with recall 1.0, one hallucinated) gives score 0.5 and hallucination_rate 0.5; report key order.
   - Code: the loader and aggregate.
6. **CLI.**
   - Test in `tests/test_eval_meta.py`: `main(['eval-meta', FIXTURE, '--json'])` prints one JSON line with the six keys and the baseline values; without `--json` it prints indent=2; a missing dir gives exit 2 and the stderr prefix; `--help` lists DIRECTORY and --json.
   - Code: cli.py.
7. Create the committed fixture and a test that loads it: 8 cases, all ids unique, baseline as stated.
8. Add the README section with the printed baseline.
9. Run `python -m pytest -q` (everything passes) and `python -m sportscut eval-meta tests/fixtures/eval_meta --json`.

## Verify

```bash
python -m pytest -q
python -m sportscut eval-meta tests/fixtures/eval_meta --json
# expect score 1.0, format_ok 1.0, fact_recall 1.0, hallucination_rate 0.0, vi_rate 1.0
PATH=/nonexistent python -m pytest -q tests/test_commentary_facts.py tests/test_commentary_meta.py tests/test_eval_meta.py
```

## Assumptions

- The match minute is elapsed time since a single kickoff offset. Second-half offsets and stoppage-time notation (45+2) are not handled, so the minute is continuous and capped at 130.
- The detector's peak (2/3 of the way through the clip) anchors the minute, because the manifest has no peak field.
- A team name that does not belong can only be detected through the per-case `forbidden` list, since there is no offline team dictionary.
- The eval runs only the template backend. A later LLM backend plugs into `generate_meta(backend=...)` and is gated by this score.

## Test plan

- tests/test_commentary_facts.py (unit): ClipFacts validation table covering every invalid field in AC2. facts_from_entry minute cases from AC3, including anchor == kickoff -> 1 and the 130 cap (kickoff 0 with an anchor at 9000 s -> 130). Normalisation, unknown key, bad kickoff and bad entry cases from AC4.
- tests/test_commentary_meta.py (unit): the exact outputs in AC5. The title fallbacks and single-team caption in AC6. The hashtag() examples, dedupe, unknown backend and to_dict order in AC7. A loop over all fixture facts asserting the format limits.
- tests/test_eval_meta.py (unit + CLI): score_case with hand-made ClipMeta for each format problem (AC8), the hallucination cases (AC9), the vi cases (AC10), and any-of recall with hashtags counted (AC11). Loader errors written to tmp_path (AC12). Two-case aggregation with monkeypatched meta.generate_meta (AC13). `cli.main(['eval-meta', 'tests/fixtures/eval_meta', '--json'])` via capsys asserting the baseline, the order of the 8 ids, the indent=2 variant, the error path with exit 2 and empty stdout, and --help (AC14).
- Fixture: tests/fixtures/eval_meta/cases.json with the 8 cases listed in the spec (committed, UTF-8, NFC). No media files are needed.
- Tester (tests/test_t023_acceptance.py): independent acceptance tests written from AC2-AC16. Include a mutation check that a template emitting 'phút 24' for minute 23 or a 2-tag list drops the score below 1.0, so the eval can fail. Also run `python -m sportscut eval-meta tests/fixtures/eval_meta --json` and compare its headline keys to the README block.
- Regression: the full `python -m pytest -q` passes, and `git diff --stat main` shows no change to the files listed as unchanged in AC16.
