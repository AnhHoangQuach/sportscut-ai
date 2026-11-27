import hashlib
import itertools
import json
import os
import re
import subprocess
import sys

import pytest

from sportscut.commentary import meta
from sportscut.commentary.eval_meta import evaluate_meta_dir, format_problems, validate_meta
from sportscut.commentary.facts import ClipFacts
from sportscut.models import EVENT_TYPES

FULL_GOAL = ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0")


def _force(monkeypatch, title_index, caption_index):
    monkeypatch.setattr(
        meta, "_pick", lambda part, facts, clip, count: title_index if part == "title" else caption_index
    )


def _index(part, facts, clip, count):
    key = json.dumps([part, facts.event, facts.minute, facts.home, facts.away, clip], ensure_ascii=False)
    return int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest()[:8], "big") % count


def test_tables_shape():
    for event in EVENT_TYPES:
        leads = meta.TITLE_LEADS[event]
        styles = meta.CAPTION_STYLES[event]
        label = meta.EVENT_LABELS[event]
        assert len(leads) >= 3 and len(set(leads)) == len(leads)
        assert len(styles) >= 3 and len(set(styles)) == len(styles)
        assert leads[0] == label
        assert styles[0] == (label, "Cùng xem lại khoảnh khắc này!")
        for opener, _ in styles:
            assert label.casefold() in opener.casefold()
        for text in (*leads, *(part for style in styles for part in style)):
            assert re.search(r"\d", text) is None, text
            assert not any(word[0].isupper() for word in text.split()[1:]), text


GRID = list(itertools.product(
    EVENT_TYPES,
    (None, 1, 130),
    ((None, None), ("A", None), (None, "Bình Dương"), ("Hà Nội FC", "Hải Phòng"), ("Q" * 40, "W" * 40)),
    ((None, None), ("Night Wolf V.League 1", "3-2"), ("C" * 40, "99-99")),
))


def test_every_variant_is_valid(monkeypatch):
    for event, minute, (home, away), (competition, score) in GRID:
        facts = ClipFacts(event, minute, home, away, competition, score)
        for i in range(len(meta.TITLE_LEADS[event])):
            for j in range(len(meta.CAPTION_STYLES[event])):
                _force(monkeypatch, i, j)
                result = meta.generate_meta(facts)
                assert format_problems(result) == [], (facts, i, j, result)
                assert validate_meta(facts, result) == [], (facts, i, j, result)


def test_index_zero_is_t023(monkeypatch):
    _force(monkeypatch, 0, 0)
    assert meta.generate_meta(FULL_GOAL) == meta.ClipMeta(
        "Bàn thắng: Hà Nội FC vs Hải Phòng, phút 23",
        "Bàn thắng trong trận Hà Nội FC gặp Hải Phòng ở phút 23 tại V.League 2026. Tỉ số: 1-0. "
        "Cùng xem lại khoảnh khắc này!",
        ("#BongDa", "#BanThang", "#Highlight", "#HaNoiFC", "#HaiPhong", "#VLeague2026"),
    )


def test_pick_formula():
    cases = [
        (FULL_GOAL, None),
        (FULL_GOAL, 0),
        (FULL_GOAL, 7),
        (ClipFacts("save", 67, "Arsenal", "Chelsea"), None),
        (ClipFacts("red_card", 88), 3),
        (ClipFacts("controversy", home="Bình Dương"), 0),
        (ClipFacts("other"), None),
    ]
    for facts, clip in cases:
        result = meta.generate_meta(facts, clip=clip)
        lead = meta.TITLE_LEADS[facts.event][_index("title", facts, clip, len(meta.TITLE_LEADS[facts.event]))]
        opener, closer = meta.CAPTION_STYLES[facts.event][
            _index("caption", facts, clip, len(meta.CAPTION_STYLES[facts.event]))
        ]
        assert result.title.startswith(lead), (facts, clip, result.title)
        assert result.caption.startswith(opener) and result.caption.endswith(" " + closer), (facts, clip)
    none_key = json.dumps(["title", "goal", 23, "Hà Nội FC", "Hải Phòng", None], ensure_ascii=False)
    zero_key = json.dumps(["title", "goal", 23, "Hà Nội FC", "Hải Phòng", 0], ensure_ascii=False)
    assert none_key != zero_key


@pytest.mark.parametrize("bad", [-1, True, 1.5, "1"])
def test_clip_and_backend_validation(bad):
    with pytest.raises(ValueError, match="^clip must be a non-negative integer$"):
        meta.generate_meta(FULL_GOAL, clip=bad)
    with pytest.raises(ValueError, match="^unknown backend: llm$"):
        meta.generate_meta(FULL_GOAL, backend="llm")
    assert isinstance(meta.generate_meta(FULL_GOAL), meta.ClipMeta)


def test_variety():
    goals = [meta.generate_meta(ClipFacts("goal", m, "Hà Nội FC", "Hải Phòng")) for m in range(1, 21)]
    assert len({g.title for g in goals}) >= 2
    assert len({g.caption for g in goals}) >= 2
    bare = [meta.generate_meta(ClipFacts("goal"), clip=c) for c in range(10)]
    assert len({b.title for b in bare}) >= 2


def test_hashtags_unchanged_by_variant(monkeypatch):
    for i in range(len(meta.TITLE_LEADS["goal"])):
        for j in range(len(meta.CAPTION_STYLES["goal"])):
            _force(monkeypatch, i, j)
            assert meta.generate_meta(FULL_GOAL).hashtags == (
                "#BongDa", "#BanThang", "#Highlight", "#HaNoiFC", "#HaiPhong", "#VLeague2026"
            )
            assert len(meta.generate_meta(ClipFacts("goal", home="Ha Noi", away="Hà Nội")).hashtags) == 4


SCRIPT = """
import json
from sportscut.commentary.facts import ClipFacts
from sportscut.commentary.meta import generate_meta
cases = [
    (ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0"), None),
    (ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0"), 4),
    (ClipFacts("save", 67, "Arsenal", "Chelsea"), 0),
    (ClipFacts("red_card", 88), 2),
    (ClipFacts("other"), None),
]
print(json.dumps([generate_meta(f, clip=c).to_dict() for f, c in cases], ensure_ascii=False))
"""


def test_deterministic_across_hash_seeds():
    outputs = []
    for seed in ("0", "4242"):
        run = subprocess.run(
            [sys.executable, "-c", SCRIPT], env={**os.environ, "PYTHONHASHSEED": seed},
            capture_output=True, text=True, encoding="utf-8", check=True,
        )
        outputs.append(run.stdout.strip())
    namespace = {}
    exec(SCRIPT.replace("print(", "result = ("), namespace)
    assert outputs[0] == outputs[1] == namespace["result"]
    assert meta.generate_meta(FULL_GOAL, clip=5) == meta.generate_meta(FULL_GOAL, clip=5)


def test_eval_meta_every_variant(monkeypatch):
    for k in range(4):
        monkeypatch.setattr(meta, "_pick", lambda part, facts, clip, count, k=k: k % count)
        report = evaluate_meta_dir("tests/fixtures/eval_meta")
        values = [report[key] for key in ("score", "format_ok", "fact_recall", "hallucination_rate", "vi_rate")]
        assert values == [1.0, 1.0, 1.0, 0.0, 1.0], (k, report)
