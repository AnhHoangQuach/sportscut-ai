"""T-050 Tester acceptance tests: written from the acceptance criteria, not from the dev tests."""
import hashlib
import importlib.util
import io
import itertools
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from sportscut.commentary import eval_meta, meta
from sportscut.commentary.facts import ClipFacts
from sportscut.commentary.meta import ClipMeta, generate_meta
from sportscut.models import EVENT_TYPES

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "eval_meta"
HEADLINE = ("score", "format_ok", "fact_recall", "hallucination_rate", "vi_rate")

# Copied by hand from the spec (AC1: "exactly the strings in the spec").
SPEC_TITLE_LEADS = {
    "goal": ("Bàn thắng", "Siêu phẩm", "Pha lập công", "Khoảnh khắc ghi bàn"),
    "save": ("Pha cứu thua", "Cứu thua xuất thần", "Pha cản phá đẳng cấp"),
    "red_card": ("Thẻ đỏ", "Tấm thẻ đỏ", "Pha nhận thẻ đỏ"),
    "controversy": ("Tình huống gây tranh cãi", "Pha bóng gây tranh cãi", "Khoảnh khắc gây tranh cãi"),
    "other": ("Khoảnh khắc đáng chú ý", "Pha bóng đáng xem", "Khoảnh khắc ấn tượng"),
}
SPEC_CAPTION_STYLES = {
    "goal": (("Bàn thắng", "Cùng xem lại khoảnh khắc này!"),
             ("Bàn thắng đẹp mắt", "Xem ngay pha lập công này!"),
             ("Một bàn thắng đáng nhớ", "Hãy cùng xem lại nhé!")),
    "save": (("Pha cứu thua", "Cùng xem lại khoảnh khắc này!"),
             ("Pha cứu thua xuất thần", "Đừng bỏ lỡ pha bóng này!"),
             ("Một pha cứu thua đẳng cấp", "Hãy cùng xem lại nhé!")),
    "red_card": (("Thẻ đỏ", "Cùng xem lại khoảnh khắc này!"),
                 ("Tấm thẻ đỏ", "Đừng bỏ lỡ tình huống này!"),
                 ("Chiếc thẻ đỏ được rút ra", "Hãy cùng xem lại nhé!")),
    "controversy": (("Tình huống gây tranh cãi", "Cùng xem lại khoảnh khắc này!"),
                    ("Tình huống gây tranh cãi lớn", "Bạn nghĩ sao về tình huống này?"),
                    ("Một tình huống gây tranh cãi", "Hãy cùng xem lại nhé!")),
    "other": (("Khoảnh khắc đáng chú ý", "Cùng xem lại khoảnh khắc này!"),
              ("Một khoảnh khắc đáng chú ý", "Đừng bỏ lỡ pha bóng này!"),
              ("Khoảnh khắc đáng chú ý không thể bỏ lỡ", "Hãy cùng xem lại nhé!")),
}
FULL_GOAL = ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0")

GRID = [
    ClipFacts(event, minute, home, away, comp, score)
    for event, minute, (home, away), (comp, score) in itertools.product(
        EVENT_TYPES,
        (None, 1, 130),
        ((None, None), ("A", None), (None, "Bình Dương"), ("Hà Nội FC", "Hải Phòng"), ("Q" * 40, "W" * 40)),
        ((None, None), ("Night Wolf V.League 1", "3-2"), ("C" * 40, "99-99")),
    )
]


def _expected_index(part, facts, clip, count):
    key = json.dumps([part, facts.event, facts.minute, facts.home, facts.away, clip], ensure_ascii=False)
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % count


def _force(monkeypatch, i, j):
    monkeypatch.setattr(meta, "_pick", lambda part, facts, clip, count: (i if part == "title" else j) % count)


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")


def _main_ref():
    for ref in ("main", "origin/main"):
        if _git("rev-parse", "--verify", "--quiet", ref).returncode == 0:
            return ref
    pytest.skip("no main branch to compare against")


def _own_branch():
    if not _git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip().startswith("office/T-050"):
        pytest.skip("scope checks only run on the T-050 branch")


def _main_meta_module():
    """Load main's (T-023) meta.py as a separate module, for the index-0 byte-identity check."""
    out = _git("show", f"{_main_ref()}:sportscut/commentary/meta.py")
    assert out.returncode == 0, out.stderr
    spec = importlib.util.spec_from_loader("t023_main_meta", loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(compile(out.stdout, "main:meta.py", "exec"), module.__dict__)
    return module


# ---------- AC1 ----------

def test_ac1_tables_match_spec_exactly():
    assert {e: tuple(v) for e, v in meta.TITLE_LEADS.items()} == SPEC_TITLE_LEADS
    assert {e: tuple(tuple(s) for s in v) for e, v in meta.CAPTION_STYLES.items()} == SPEC_CAPTION_STYLES
    assert set(meta.TITLE_LEADS) == set(EVENT_TYPES) == set(meta.CAPTION_STYLES)


def test_ac1_table_rules():
    for event in EVENT_TYPES:
        label = meta.EVENT_LABELS[event]
        leads, styles = meta.TITLE_LEADS[event], meta.CAPTION_STYLES[event]
        assert len(leads) >= 3 and len(set(leads)) == len(leads)
        assert len(styles) >= 3 and len(set(styles)) == len(styles)
        assert leads[0] == label
        assert tuple(styles[0]) == (label, "Cùng xem lại khoảnh khắc này!")
        for opener, closer in styles:
            assert label.casefold() in opener.casefold(), opener
        for text in (*leads, *(s for style in styles for s in style)):
            assert not re.search(r"\d", text), text
            assert all(not w[0].isupper() for w in re.findall(r"[^\W\d_]+", text)[1:]), text


# ---------- AC2 ----------

def test_ac2_every_forced_variant_valid_over_grid(monkeypatch):
    assert len(GRID) == len(EVENT_TYPES) * 3 * 5 * 3
    failures = []
    for facts in GRID:
        for i in range(len(meta.TITLE_LEADS[facts.event])):
            for j in range(len(meta.CAPTION_STYLES[facts.event])):
                _force(monkeypatch, i, j)
                m = generate_meta(facts)
                fp = eval_meta.format_problems(m)
                vp = eval_meta.validate_meta(facts, m)
                if fp or vp:
                    failures.append((facts, i, j, fp, vp))
    assert failures == []


def test_ac2_hashed_pick_valid_with_clip_indices():
    for facts in GRID:
        for clip in (None, 0, 1, 7, 1000):
            m = generate_meta(facts, clip=clip)
            assert eval_meta.validate_meta(facts, m) == [], (facts, clip, m)


@pytest.mark.parametrize("bad_lead, expected", [
    ("Bàn thắng số 1", "number 1 not in facts"),
    ("Bàn thắng của Messi", "name Messi not in facts"),
])
def test_ac2_check_can_fail_on_a_bad_template(monkeypatch, bad_lead, expected):
    """Mutation: a template with a digit or a capitalised mid-sentence word must be caught."""
    monkeypatch.setitem(meta.TITLE_LEADS, "goal", (bad_lead, *SPEC_TITLE_LEADS["goal"][1:]))
    _force(monkeypatch, 0, 0)
    facts = ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng")
    assert expected in eval_meta.validate_meta(facts, generate_meta(facts))


def test_ac2_check_can_fail_on_opener_without_label(monkeypatch):
    monkeypatch.setitem(meta.CAPTION_STYLES, "save", (("Cú bay người", "Xem nhé!"),))
    monkeypatch.setitem(meta.TITLE_LEADS, "save", ("Cú bay người",))
    facts = ClipFacts("save", 10)
    m = generate_meta(facts)
    assert "missing Pha cứu thua" in eval_meta.validate_meta(facts, m)


# ---------- AC3 ----------

COMBOS = [
    (FULL_GOAL, None),
    (FULL_GOAL, 0),
    (FULL_GOAL, 3),
    (ClipFacts("goal"), None),
    (ClipFacts("goal"), 0),
    (ClipFacts("save", 45, "Bình Dương"), 2),
    (ClipFacts("red_card", 88), None),
    (ClipFacts("controversy", 1, None, "Hải Phòng"), 5),
    (ClipFacts("other", 130, "A", "B", "C", "0-0"), 9),
]


@pytest.mark.parametrize("facts, clip", COMBOS)
def test_ac3_pick_matches_sha256_formula(facts, clip):
    m = generate_meta(facts, clip=clip)
    leads, styles = SPEC_TITLE_LEADS[facts.event], SPEC_CAPTION_STYLES[facts.event]
    lead = leads[_expected_index("title", facts, clip, len(leads))]
    opener, closer = styles[_expected_index("caption", facts, clip, len(styles))]
    assert m.title.startswith(lead), (m.title, lead)
    # The lead must be the whole prefix (not a shorter lead that is a prefix of the expected one).
    assert m.title[len(lead)] in ": ,", m.title
    assert m.caption.startswith(opener + " "), (m.caption, opener)
    assert m.caption.endswith(" " + closer), (m.caption, closer)
    assert meta._pick("title", facts, clip, len(leads)) == _expected_index("title", facts, clip, len(leads))


def test_ac3_clip_none_and_zero_are_different_keys():
    for facts in (FULL_GOAL, ClipFacts("goal")):
        assert json.dumps(["title", facts.event, facts.minute, facts.home, facts.away, None]) != json.dumps(
            ["title", facts.event, facts.minute, facts.home, facts.away, 0])
    # Over many facts, None vs 0 must change the pick at least once (raw 64-bit values differ).
    differs = any(
        meta._pick("title", ClipFacts("goal", minute), None, 4) != meta._pick("title", ClipFacts("goal", minute), 0, 4)
        for minute in range(1, 40)
    )
    assert differs


def test_ac3_competition_and_score_not_in_key():
    a = generate_meta(ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng"))
    b = generate_meta(FULL_GOAL)
    assert a.title.split(":")[0] == b.title.split(":")[0]
    assert a.caption.split(" trong trận")[0] == b.caption.split(" trong trận")[0]
    assert a.caption.rsplit(". ", 1)[-1] == b.caption.rsplit(". ", 1)[-1]


def test_ac3_pick_looked_up_at_call_time(monkeypatch):
    calls = []

    def spy(part, facts, clip, count):
        calls.append((part, facts, clip, count))
        return count - 1

    monkeypatch.setattr(meta, "_pick", spy)
    m = generate_meta(FULL_GOAL, clip=4)
    assert {c[0] for c in calls} == {"title", "caption"}
    assert all(c[1] == FULL_GOAL and c[2] == 4 for c in calls)
    assert m.title.startswith("Khoảnh khắc ghi bàn")
    assert m.caption.startswith("Một bàn thắng đáng nhớ") and m.caption.endswith("Hãy cùng xem lại nhé!")


def test_ac3_no_builtin_hash_or_random_in_meta_source():
    source = "\n".join(l.split("#", 1)[0] for l in Path(meta.__file__).read_text(encoding="utf-8").splitlines())
    assert not re.search(r"(?<![\w.])hash\(", source)
    assert "import random" not in source and "from random" not in source


# ---------- AC4 ----------

def test_ac4_index_zero_is_byte_identical_to_main(monkeypatch):
    _own_branch()
    old = _main_meta_module()
    _force(monkeypatch, 0, 0)
    extra = [
        ClipFacts("goal", 120, "Câu lạc bộ Bóng đá Công an Hà Nội", "Becamex Bình Dương Football Club"),
        ClipFacts("goal", home="Arsenal"),
        ClipFacts("red_card", 88),
        FULL_GOAL,
        ClipFacts("goal", home="Ha Noi", away="Hà Nội"),
    ]
    for facts in GRID + extra:
        new, base = generate_meta(facts), old.generate_meta(facts)
        assert (new.title, new.caption, new.hashtags) == (base.title, base.caption, base.hashtags), facts


def test_ac4_fallback_chain_with_long_lead(monkeypatch):
    _force(monkeypatch, 3, 0)  # "Khoảnh khắc ghi bàn" (19 chars)
    teams = ("Câu lạc bộ Bóng đá Công an Hà Nội", "Becamex Bình Dương Football Club")
    lead = "Khoảnh khắc ghi bàn"
    # lead: teams, minute -> too long; lead: teams -> 19 + 2 + 70 > 80; lead, minute wins.
    assert generate_meta(ClipFacts("goal", 120, *teams)).title == f"{lead}, phút 120"
    # No minute: lead: teams too long -> lead trong trận đấu.
    assert generate_meta(ClipFacts("goal", None, *teams)).title == f"{lead} trong trận đấu"
    assert generate_meta(ClipFacts("goal", 5, "A", "B")).title == f"{lead}: A vs B, phút 5"
    assert generate_meta(ClipFacts("goal", None, "A")).title == f"{lead}: A"
    assert generate_meta(ClipFacts("goal")).title == f"{lead} trong trận đấu"


def test_ac4_caption_layout(monkeypatch):
    _force(monkeypatch, 0, 1)
    assert generate_meta(FULL_GOAL).caption == (
        "Bàn thắng đẹp mắt trong trận Hà Nội FC gặp Hải Phòng ở phút 23 tại V.League 2026. "
        "Tỉ số: 1-0. Xem ngay pha lập công này!"
    )
    _force(monkeypatch, 0, 2)
    assert generate_meta(ClipFacts("save", away="Hải Phòng")).caption == (
        "Một pha cứu thua đẳng cấp trong trận đấu của Hải Phòng. Hãy cùng xem lại nhé!"
    )
    _force(monkeypatch, 0, 1)
    assert generate_meta(ClipFacts("controversy", 90, score="2-2")).caption == (
        "Tình huống gây tranh cãi lớn trong trận đấu ở phút 90. Tỉ số: 2-2. Bạn nghĩ sao về tình huống này?"
    )


# ---------- AC5 ----------

def test_ac5_hashtags_independent_of_variant(monkeypatch):
    for i in range(4):
        for j in range(3):
            _force(monkeypatch, i, j)
            assert generate_meta(FULL_GOAL).hashtags == (
                "#BongDa", "#BanThang", "#Highlight", "#HaNoiFC", "#HaiPhong", "#VLeague2026")
            assert len(generate_meta(ClipFacts("goal", home="Ha Noi", away="Hà Nội")).hashtags) == 4
    monkeypatch.undo()
    for clip in (None, 0, 1, 2, 3, 50):
        assert generate_meta(FULL_GOAL, clip=clip).hashtags == (
            "#BongDa", "#BanThang", "#Highlight", "#HaNoiFC", "#HaiPhong", "#VLeague2026")


# ---------- AC6 ----------

SCRIPT = """
import json
from sportscut.commentary.facts import ClipFacts
from sportscut.commentary.meta import generate_meta
facts = [ClipFacts('goal', 23, 'Hà Nội FC', 'Hải Phòng', 'V.League 2026', '1-0'), ClipFacts('goal'),
         ClipFacts('save', 45, 'Bình Dương'), ClipFacts('red_card', 88), ClipFacts('controversy', 1, None, 'B'),
         ClipFacts('other', 130, 'A', 'B')]
print(json.dumps([generate_meta(f, clip=c).to_dict() for f in facts for c in (None, 0, 1, 2, 9)],
                 ensure_ascii=False))
"""


def _in_process():
    ns = {}
    body = SCRIPT.replace("print(json.dumps(", "RESULT = (json.dumps(")
    exec(body, ns)
    return ns["RESULT"]


def test_ac6_deterministic_across_hash_seeds():
    outs = []
    for seed in ("0", "4242", "random"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(ROOT), "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run([sys.executable, "-c", SCRIPT], cwd=ROOT, env=env, capture_output=True)
        assert out.returncode == 0, out.stderr
        outs.append(out.stdout)
    assert outs[0] == outs[1] == outs[2]
    assert outs[0].decode("utf-8").strip() == _in_process()


def test_ac6_equal_facts_give_equal_meta():
    for facts in GRID[::7]:
        twin = ClipFacts(**{f: getattr(facts, f) for f in ClipFacts.__dataclass_fields__})
        for clip in (None, 0, 3):
            assert generate_meta(facts, clip=clip) == generate_meta(twin, clip=clip)


# ---------- AC7 ----------

def test_ac7_variety():
    metas = [generate_meta(ClipFacts("goal", m, "Hà Nội FC", "Hải Phòng")) for m in range(1, 21)]
    leads = {next(l for l in sorted(SPEC_TITLE_LEADS["goal"], key=len, reverse=True) if x.title.startswith(l))
             for x in metas}
    assert len({x.title for x in metas}) >= 2
    assert len(leads) >= 2, "different minutes must give different leads, not just different minute text"
    assert len({x.caption.split(" trong trận")[0] for x in metas}) >= 2
    assert len({generate_meta(ClipFacts("goal"), clip=c).title for c in range(10)}) >= 2


# ---------- AC8 ----------

@pytest.mark.parametrize("bad", [-1, True, False, 1.5, "1", 0.0])
def test_ac8_bad_clip_rejected(bad):
    with pytest.raises(ValueError, match=r"^clip must be a non-negative integer$"):
        generate_meta(FULL_GOAL, clip=bad)


def test_ac8_backend_check_first_and_positional_call():
    with pytest.raises(ValueError, match=r"^unknown backend: llm$"):
        generate_meta(FULL_GOAL, backend="llm")
    with pytest.raises(ValueError, match=r"^unknown backend: llm$"):
        generate_meta(FULL_GOAL, "llm", -1)
    assert isinstance(generate_meta(FULL_GOAL), ClipMeta)
    assert generate_meta(FULL_GOAL) == generate_meta(FULL_GOAL, "template") == generate_meta(FULL_GOAL, clip=None)


def test_ac8_existing_callers_still_work():
    from sportscut import api
    from sportscut.commentary import llm
    assert api._default_clip_meta is not None and llm is not None
    result = eval_meta.evaluate_meta_dir(FIXTURE)
    assert [result[k] for k in HEADLINE] == [1.0, 1.0, 1.0, 0.0, 1.0]


# ---------- AC9 ----------

def _cli(*args, pythonpath=ROOT):
    env = {**os.environ, "PYTHONPATH": str(pythonpath)}
    env.pop("ANTHROPIC_API_KEY", None)
    out = subprocess.run([sys.executable, "-m", "sportscut", *args], cwd=ROOT, env=env,
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return out.stdout


def test_ac9_cli_eval_meta_json():
    report = json.loads(_cli("eval-meta", str(FIXTURE), "--json"))
    assert {k: report[k] for k in HEADLINE} == {
        "score": 1.0, "format_ok": 1.0, "fact_recall": 1.0, "hallucination_rate": 0.0, "vi_rate": 1.0}


@pytest.mark.parametrize("k", range(4))
def test_ac9_eval_meta_every_forced_variant(monkeypatch, k):
    monkeypatch.setattr(meta, "_pick", lambda part, facts, clip, count: k % count)
    report = eval_meta.evaluate_meta_dir(FIXTURE)
    assert [report[key] for key in HEADLINE] == [1.0, 1.0, 1.0, 0.0, 1.0], report["per_case"]


def test_ac9_script_report_unchanged_from_main(tmp_path):
    ref = _main_ref()
    archive = subprocess.run(["git", "archive", ref, "sportscut"], cwd=ROOT, capture_output=True)
    assert archive.returncode == 0
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(tmp_path, filter="data")
    args = ("eval-meta", str(FIXTURE), "--json", "--script")
    assert _cli(*args) == _cli(*args, pythonpath=tmp_path)


def test_ac9_cases_json_unchanged():
    ref = _main_ref()
    out = _git("diff", ref, "--", "tests/fixtures/eval_meta/cases.json")
    assert out.returncode == 0 and out.stdout == ""
    assert _git("status", "--porcelain", "--", "tests/fixtures/eval_meta").stdout == ""


# ---------- AC10 / AC12 ----------

PINNED_FILES = ("tests/test_commentary_meta.py", "tests/test_t023_acceptance.py",
                "tests/test_t025_acceptance.py", "tests/test_t028_acceptance.py")


def _diff_lines(path):
    out = _git("diff", "-U0", _main_ref(), "--", path)
    assert out.returncode == 0
    lines = [l for l in out.stdout.splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]
    return [l[1:] for l in lines if l[0] == "-"], [l[1:] for l in lines if l[0] == "+"]


def test_ac10_pinned_test_edits_only_change_literals():
    _own_branch()
    for path in PINNED_FILES:
        removed, added = _diff_lines(path)
        joined = "\n".join(added)
        assert "skip" not in joined and "xfail" not in joined, path
        # New expected values are literals, never a call to generate_meta.
        assert all("==" not in l or "generate_meta(" not in l.split("==", 1)[1] for l in added), path
        assert sum(l.count("assert") for l in removed) == sum(l.count("assert") for l in added), path
        assert sum(l.count("==") for l in removed) == sum(l.count("==") for l in added), path
        # No hashtag literal changes.
        assert sorted(re.findall(r"#\w+", "\n".join(removed))) == sorted(re.findall(r"#\w+", joined)), path
        assert "trong trận đấu của Arsenal" not in "\n".join(removed), path


def test_ac10_t026_t027_gate_edits_only():
    _own_branch()
    removed, added = _diff_lines("tests/test_t026_acceptance.py")
    assert [l.strip() for l in removed] == [
        "base = _base()", "if base is None:", 'pytest.skip("no main branch to compare against")']
    assert [l.strip() for l in added] == ["base = _own_branch_base()"]
    removed, added = _diff_lines("tests/test_t027_acceptance.py")
    assert removed == []
    assert [l.strip() for l in added][0] == "if not extra:"
    assert added[1].strip().startswith("_own_branch_base()") and len(added) == 2


ALLOWED = {
    "sportscut/commentary/meta.py", "tests/test_meta_variants.py", "tests/test_t050_acceptance.py",
    *PINNED_FILES, "tests/test_t026_acceptance.py", "tests/test_t027_acceptance.py",
}


def test_ac12_diff_size_and_file_list():
    _own_branch()
    ref = _main_ref()
    out = _git("diff", "--numstat", ref, "--", ".", ":!docs/superpowers", ":!.office")
    assert out.returncode == 0
    total, files = 0, set()
    for line in out.stdout.splitlines():
        add, rem, path = line.split("\t")
        files.add(path)
        if path != "tests/test_t050_acceptance.py":  # Tester file is not the Developer's diff budget
            total += int(add) + int(rem)
    assert files <= ALLOWED, files - ALLOWED
    assert total < 300, total


# ---------- AC11 ----------

def test_ac11_docs_updated():
    spec = (ROOT / "docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md"
            ).read_text(encoding="utf-8")
    section = spec.split("## Updated by T-050", 1)
    assert len(section) == 2
    tail = section[1]
    for needle in ("TITLE_LEADS", "CAPTION_STYLES", "sha256", "clip", "Pha lập công", "T-026", "T-027"):
        assert needle in tail, needle
    for name in ("2026-11-23-t-025-add-an-optional-claude-llm-backend-design.md",
                 "2026-11-23-t-028-show-and-copy-title-caption-and-design.md"):
        assert "Updated by T-050" in (ROOT / "docs/superpowers/specs" / name).read_text(encoding="utf-8")
    _own_branch()
    assert "## " not in tail.replace("## Updated by T-050", ""), "T-050 section must be the last section"
    removed, added = _diff_lines("docs/superpowers/INDEX.md")
    assert removed == [] and len(added) == 1 and "| T-050 |" in added[0]
