import math
import unicodedata

import pytest


def test_clip_facts_valid_and_frozen() -> None:
    from sportscut.commentary.facts import ClipFacts

    facts = ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0")
    assert facts.event == "goal"
    with pytest.raises(AttributeError):
        facts.event = "save"


@pytest.mark.parametrize(
    ("args", "field"),
    [
        (("penalty",), "event"),
        (("Goal",), "event"),
        (("goal", 0), "minute"),
        (("goal", 131), "minute"),
        (("goal", True), "minute"),
        (("goal", 2.0), "minute"),
        (("goal", None, ""), "home"),
        (("goal", None, 3), "home"),
        (("goal", None, "x" * 41), "home"),
        (("goal", None, " Arsenal"), "home"),
        (("goal", None, None, "Chelsea "), "away"),
        (("goal", None, None, None, ""), "competition"),
        (("goal", None, None, None, None, "2:1"), "score"),
        (("goal", None, None, None, None, "100-1"), "score"),
    ],
)
def test_clip_facts_rejects_invalid_fields(args, field: str) -> None:
    from sportscut.commentary.facts import ClipFacts

    with pytest.raises(ValueError, match=field):
        ClipFacts(*args)


@pytest.mark.parametrize(
    ("match", "minute"),
    [
        ({"kickoff": 0}, 23),
        ({"kickoff": 120}, 21),
        ({"kickoff": 1400}, None),
        ({}, None),
        (None, None),
    ],
)
def test_facts_from_entry_computes_minute(match, minute) -> None:
    from sportscut.commentary.facts import facts_from_entry

    facts = facts_from_entry({"start": 1370, "end": 1382, "event": "goal"}, match)
    assert facts.event == "goal"
    assert facts.minute == minute


def test_facts_from_entry_minute_boundary_and_cap() -> None:
    from sportscut.commentary.facts import facts_from_entry

    assert facts_from_entry({"start": 0, "end": 12, "event": "save"}, {"kickoff": 8}).minute == 1
    assert facts_from_entry({"start": 8992, "end": 9004, "event": "save"}, {"kickoff": 0}).minute == 130


def test_facts_from_entry_normalises_match_values() -> None:
    from sportscut.commentary.facts import facts_from_entry

    decomposed = unicodedata.normalize("NFD", "Hà Nội")
    facts = facts_from_entry(
        {"start": 0, "end": 12, "event": "goal"},
        {"home": f" {decomposed} ", "away": "  ", "competition": None, "score": " 2 - 1 "},
    )
    assert facts.home == "Hà Nội"
    assert unicodedata.is_normalized("NFC", facts.home)
    assert facts.away is None
    assert facts.competition is None
    assert facts.score == "2-1"


def test_facts_from_entry_rejects_unknown_match_key() -> None:
    from sportscut.commentary.facts import facts_from_entry

    with pytest.raises(ValueError, match="unknown match key: venue"):
        facts_from_entry({"start": 0, "end": 1, "event": "goal"}, {"venue": "Hà Nội"})


@pytest.mark.parametrize("kickoff", [-1, True, math.nan, "10"])
def test_facts_from_entry_rejects_bad_kickoff(kickoff) -> None:
    from sportscut.commentary.facts import facts_from_entry

    with pytest.raises(ValueError, match="kickoff"):
        facts_from_entry({"start": 0, "end": 1, "event": "goal"}, {"kickoff": kickoff})


@pytest.mark.parametrize(
    "entry",
    [
        {"start": math.nan, "end": 2, "event": "goal"},
        {"start": 0, "end": math.inf, "event": "goal"},
        {"start": True, "end": 2, "event": "goal"},
        {"start": "0", "end": 2, "event": "goal"},
        {"start": 2, "end": 2, "event": "goal"},
        {"start": 3, "end": 2, "event": "goal"},
    ],
)
def test_facts_from_entry_rejects_bad_entry_times(entry) -> None:
    from sportscut.commentary.facts import facts_from_entry

    with pytest.raises(ValueError):
        facts_from_entry(entry)
