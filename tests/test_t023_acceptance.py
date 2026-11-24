"""Independent acceptance coverage for T-023.

These tests exercise only the public functions and CLI behavior described in the
task acceptance criteria.  They intentionally do not share helpers with the
Developer's unit tests.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from sportscut.commentary import meta as meta_module
from sportscut.commentary.eval_meta import (
    MetaCase,
    evaluate_meta_dir,
    load_cases,
    score_case,
)
from sportscut.commentary.facts import ClipFacts, facts_from_entry
from sportscut.commentary.meta import ClipMeta, generate_meta, hashtag


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "eval_meta"
EXPECTED_IDS = [
    "goal_full",
    "save_teams",
    "red_card_minute_only",
    "controversy_no_minute",
    "other_bare",
    "goal_long_names",
    "goal_u23",
    "save_competition_only",
]
HEADLINE = {
    "score": 1.0,
    "format_ok": 1.0,
    "fact_recall": 1.0,
    "hallucination_rate": 0.0,
    "vi_rate": 1.0,
}


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "sportscut", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_cases(directory: Path, cases: object) -> Path:
    directory.mkdir()
    path = directory / "cases.json"
    path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    return path


def _case_payload(
    case_id: str = "case",
    *,
    event: str = "goal",
    minute: int = 23,
    must_mention: list[list[str]] | None = None,
    forbidden: list[str] | None = None,
) -> dict:
    return {
        "id": case_id,
        "facts": {"event": event, "minute": minute},
        "must_mention": must_mention or [["bàn thắng"]],
        "forbidden": forbidden or [],
    }


@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"event": "penalty"}, "event"),
        ({"event": "Goal"}, "event"),
        ({"event": "goal", "minute": 0}, "minute"),
        ({"event": "goal", "minute": 131}, "minute"),
        ({"event": "goal", "minute": True}, "minute"),
        ({"event": "goal", "minute": 2.0}, "minute"),
        *[
            ({"event": "goal", name: value}, name)
            for name in ("home", "away", "competition")
            for value in ("", 7, "x" * 41, " Arsenal", "Arsenal ")
        ],
        ({"event": "goal", "score": "2:1"}, "score"),
        ({"event": "goal", "score": "100-1"}, "score"),
    ],
)
def test_ac2_clip_facts_rejects_every_invalid_public_value(kwargs, field):
    with pytest.raises(ValueError, match=field):
        ClipFacts(**kwargs)


def test_ac2_clip_facts_is_valid_and_frozen():
    facts = ClipFacts(
        "goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0"
    )
    assert facts.event == "goal"
    with pytest.raises(FrozenInstanceError):
        facts.minute = 24  # type: ignore[misc]


def test_ac3_minute_is_anchored_to_the_peak_only_when_kickoff_is_known():
    entry = {"start": 1370, "end": 1382, "event": "goal"}
    assert facts_from_entry(entry, {"kickoff": 0}).minute == 23
    assert facts_from_entry(entry, {"kickoff": 120}).minute == 21
    assert facts_from_entry(entry, {"kickoff": 1400}).minute is None
    assert facts_from_entry(entry).minute is None
    assert facts_from_entry(entry, {"home": "Arsenal"}).minute is None

    anchor_entry = {"start": 10, "end": 22, "event": "save"}
    anchored = facts_from_entry(anchor_entry, {"kickoff": 18})
    assert (anchored.event, anchored.minute) == ("save", 1)
    assert facts_from_entry(
        {"start": 8992, "end": 9004, "event": "other"}, {"kickoff": 0}
    ).minute == 130


def test_ac4_match_values_are_normalized_and_blanks_become_unknown():
    result = facts_from_entry(
        {"start": 0, "end": 12, "event": "goal"},
        {
            "home": " A\u0301rsenal ",
            "away": "  ",
            "competition": " V.League ",
            "score": " 2 - 1 ",
        },
    )
    assert result == ClipFacts("goal", None, "Ársenal", None, "V.League", "2-1")
    assert unicodedata.is_normalized("NFC", result.home)


@pytest.mark.parametrize("kickoff", [-1, True, float("nan"), "10"])
def test_ac4_bad_kickoff_is_rejected(kickoff):
    with pytest.raises(ValueError, match="kickoff"):
        facts_from_entry(
            {"start": 0, "end": 12, "event": "goal"}, {"kickoff": kickoff}
        )


@pytest.mark.parametrize(
    "entry",
    [
        {"start": float("nan"), "end": 12, "event": "goal"},
        {"start": 0, "end": float("inf"), "event": "goal"},
        {"start": "0", "end": 12, "event": "goal"},
        {"start": 12, "end": 12, "event": "goal"},
        {"start": 13, "end": 12, "event": "goal"},
    ],
)
def test_ac4_bad_entry_times_are_rejected(entry):
    with pytest.raises(ValueError):
        facts_from_entry(entry)


def test_ac4_unknown_match_key_and_non_string_name_are_rejected():
    entry = {"start": 0, "end": 12, "event": "goal"}
    with pytest.raises(ValueError, match="unknown match key"):
        facts_from_entry(entry, {"stadium": "Mỹ Đình"})
    with pytest.raises(ValueError, match="home"):
        facts_from_entry(entry, {"home": 23})


def test_ac5_exact_template_outputs_for_full_and_bare_facts():
    full = generate_meta(
        ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0")
    )
    assert full == ClipMeta(
        "Bàn thắng: Hà Nội FC vs Hải Phòng, phút 23",
        "Bàn thắng trong trận Hà Nội FC gặp Hải Phòng ở phút 23 tại "
        "V.League 2026. Tỉ số: 1-0. Cùng xem lại khoảnh khắc này!",
        (
            "#BongDa",
            "#BanThang",
            "#Highlight",
            "#HaNoiFC",
            "#HaiPhong",
            "#VLeague2026",
        ),
    )
    assert generate_meta(ClipFacts("other")) == ClipMeta(
        "Khoảnh khắc đáng chú ý trong trận đấu",
        "Khoảnh khắc đáng chú ý trong trận đấu. Cùng xem lại khoảnh khắc này!",
        ("#BongDa", "#KhoanhKhac", "#Highlight"),
    )


def test_ac6_title_fallbacks_and_every_fixture_output_stays_in_bounds():
    long_names = ClipFacts(
        "goal",
        120,
        "Câu lạc bộ Bóng đá Công an Hà Nội",
        "Becamex Bình Dương Football Club",
        "Night Wolf V.League 1",
        "3-2",
    )
    assert generate_meta(long_names).title == (
        "Bàn thắng: Câu lạc bộ Bóng đá Công an Hà Nội vs "
        "Becamex Bình Dương Football Club"
    )
    assert len(generate_meta(long_names).title) == 80
    assert generate_meta(ClipFacts("red_card", 88)).title == "Thẻ đỏ, phút 88"
    one_team = generate_meta(ClipFacts("goal", home="Arsenal"))
    assert one_team.title == "Bàn thắng: Arsenal"
    assert "trong trận đấu của Arsenal" in one_team.caption

    for case in load_cases(FIXTURE / "cases.json"):
        output = generate_meta(case.facts)
        assert 10 <= len(output.title) <= 80
        assert 1 <= len(output.caption) <= 300


def test_ac7_hashtag_backend_deduplication_and_serialization_contract():
    assert hashtag("Hà Nội FC") == "#HaNoiFC"
    assert hashtag("U23 Việt Nam") == "#U23VietNam"
    assert hashtag("V.League 2026") == "#VLeague2026"
    assert hashtag("!!!") is None
    assert len(generate_meta(ClipFacts("goal", home="Ha Noi", away="Hà Nội")).hashtags) == 4
    with pytest.raises(ValueError, match="^unknown backend: llm$"):
        generate_meta(ClipFacts("goal"), backend="llm")

    serialized = ClipMeta("Bàn thắng đẹp", "Một caption.", ("#BongDa",)).to_dict()
    assert list(serialized) == ["title", "caption", "hashtags"]
    assert serialized["hashtags"] == ["#BongDa"]


def _format_case() -> MetaCase:
    return MetaCase("format", ClipFacts("goal"), [["bàn thắng"]], [])


def _valid_meta() -> ClipMeta:
    return ClipMeta(
        "Bàn thắng đẹp",
        "Bàn thắng tuyệt đẹp.",
        ("#BongDa", "#BanThang", "#Highlight"),
    )


@pytest.mark.parametrize(
    ("output", "problem"),
    [
        (ClipMeta("123456789", "Bàn thắng đẹp.", ("#A", "#B", "#C")), "title length 9"),
        (ClipMeta("à" * 81, "Bàn thắng đẹp.", ("#A", "#B", "#C")), "title length 81"),
        (ClipMeta("Bàn thắng đẹp", "à" * 301, ("#A", "#B", "#C")), "caption length 301"),
        (ClipMeta("Bàn thắng đẹp", "", ("#A", "#B", "#C")), "caption length 0"),
        (ClipMeta("Bàn thắng đẹp", "Bàn thắng đẹp.", ("#A", "#B")), "hashtag count 2"),
        (
            ClipMeta(
                "Bàn thắng đẹp",
                "Bàn thắng đẹp.",
                tuple(f"#Tag{i}" for i in range(9)),
            ),
            "hashtag count 9",
        ),
        (ClipMeta("Bàn thắng đẹp", "Bàn thắng đẹp.", ("#Bóng", "#B", "#C")), "bad hashtag #Bóng"),
        (ClipMeta("Bàn thắng đẹp", "Bàn thắng đẹp.", ("BongDa", "#B", "#C")), "bad hashtag BongDa"),
        (
            ClipMeta(
                "Bàn thắng đẹp",
                "Bàn thắng đẹp.",
                ("#BongDa", "#bongda", "#Highlight"),
            ),
            "duplicate hashtag #bongda",
        ),
    ],
)
def test_ac8_each_bad_format_is_detected(output, problem):
    result = score_case(_format_case(), output)
    assert result["format_ok"] is False
    assert problem in result["problems"]


def test_ac8_valid_metadata_has_no_problems():
    result = score_case(_format_case(), _valid_meta())
    assert result["format_ok"] is True
    assert result["problems"] == []


def test_ac9_hallucinated_number_and_forbidden_name_zero_the_case_score():
    case = MetaCase(
        "hallucination",
        ClipFacts("goal", 23, "Arsenal", "Chelsea"),
        [["bàn thắng"]],
        ["Liverpool"],
    )
    wrong_minute = ClipMeta(
        "Bàn thắng phút 24",
        "Bàn thắng tuyệt đẹp.",
        ("#BongDa", "#BanThang", "#Highlight"),
    )
    result = score_case(case, wrong_minute)
    assert result["hallucinated"] is True
    assert "number 24 not in facts" in result["problems"]
    assert result["score"] == 0.0

    forbidden = ClipMeta(
        "Bàn thắng tuyệt đẹp",
        "LIVERPOOL có bàn thắng đẹp.",
        ("#BongDa", "#BanThang", "#Highlight"),
    )
    result = score_case(case, forbidden)
    assert result["hallucinated"] is True
    assert "forbidden Liverpool" in result["problems"]
    assert result["score"] == 0.0


def test_ac9_all_numbers_supplied_by_facts_are_not_hallucinations():
    facts = ClipFacts("goal", 23, "U23 Việt Nam", "U23 Thái Lan", "V.League 2026", "2-2")
    case = MetaCase("numbers", facts, [["bàn thắng"]], [])
    assert score_case(case, generate_meta(facts))["hallucinated"] is False


def test_ac10_vietnamese_heuristic_rejects_english_and_accepts_fixture_templates():
    english_case = MetaCase(
        "english",
        ClipFacts("goal", 23, "Arsenal", "Chelsea"),
        [["goal"]],
        [],
    )
    english = ClipMeta(
        "Goal: Arsenal vs Chelsea, minute 23",
        "Great goal by the home side",
        ("#Football", "#Goal", "#Highlight"),
    )
    result = score_case(english_case, english)
    assert result["vi"] is False
    assert "not vietnamese" in result["problems"]
    assert result["score"] == 0.0

    for case in load_cases(FIXTURE / "cases.json"):
        assert score_case(case, generate_meta(case.facts))["vi"] is True


def test_ac11_any_of_recall_includes_hashtags_and_result_key_order_is_stable():
    case = MetaCase(
        "recall",
        ClipFacts("goal", home="Arsenal"),
        [["không có", "bàn thắng"], ["Arsenal"]],
        [],
    )
    output = ClipMeta(
        "BÀN THẮNG đẹp",
        "Một khoảnh khắc tuyệt vời.",
        ("#BongDa", "#Highlight", "#Arsenal"),
    )
    result = score_case(case, output)
    assert result["fact_recall"] == 1.0
    assert list(result) == [
        "id",
        "score",
        "format_ok",
        "fact_recall",
        "hallucinated",
        "vi",
        "problems",
        "title",
        "caption",
        "hashtags",
    ]

    half = MetaCase("half", ClipFacts("goal"), [["bàn thắng"], ["Arsenal"]], [])
    assert score_case(half, _valid_meta())["fact_recall"] == 0.5


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        [1],
        [{"id": "", "facts": {"event": "goal"}, "must_mention": [["x"]], "forbidden": []}],
        [
            _case_payload("duplicate"),
            _case_payload("duplicate", event="save", minute=67, must_mention=[["cứu thua"]]),
        ],
        [{"id": "unknown", "facts": {"event": "goal", "stadium": "x"}, "must_mention": [["x"]], "forbidden": []}],
        [{"id": "invalid", "facts": {"event": "goal", "minute": 0}, "must_mention": [["x"]], "forbidden": []}],
        [{"id": "must", "facts": {"event": "goal"}, "must_mention": [], "forbidden": []}],
        [{"id": "group", "facts": {"event": "goal"}, "must_mention": [[]], "forbidden": []}],
        [{"id": "forbidden", "facts": {"event": "goal", "home": "Arsenal"}, "must_mention": [["x"]], "forbidden": ["arsenal"]}],
    ],
)
def test_ac12_malformed_case_files_are_rejected_with_the_filename(tmp_path, payload):
    path = _write_cases(tmp_path / "eval", payload)
    with pytest.raises(ValueError, match="cases\\.json"):
        load_cases(path)


def test_ac12_invalid_json_and_directory_errors_are_clear(tmp_path):
    invalid_dir = tmp_path / "invalid"
    invalid_dir.mkdir()
    invalid_json = invalid_dir / "cases.json"
    invalid_json.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="cases\\.json"):
        load_cases(invalid_json)

    with pytest.raises(ValueError, match="not a directory"):
        evaluate_meta_dir(tmp_path / "absent")
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="missing cases\\.json"):
        evaluate_meta_dir(empty_dir)


def test_ac13_aggregate_is_micro_averaged_ordered_and_sensitive(monkeypatch, tmp_path):
    directory = tmp_path / "two-cases"
    _write_cases(
        directory,
        [
            _case_payload("good", must_mention=[["bàn thắng"], ["phút 23"]]),
            _case_payload(
                "hallucinated",
                event="save",
                minute=67,
                must_mention=[["cứu thua"]],
            ),
        ],
    )

    def generated(facts: ClipFacts) -> ClipMeta:
        output = generate_meta(facts)
        if facts.event == "save":
            return ClipMeta(
                output.title,
                output.caption + " phút 99.",
                output.hashtags,
            )
        return output

    monkeypatch.setattr(meta_module, "generate_meta", generated)
    report = evaluate_meta_dir(directory)
    assert list(report) == [
        "score",
        "format_ok",
        "fact_recall",
        "hallucination_rate",
        "vi_rate",
        "per_case",
    ]
    assert report["score"] == 0.5
    assert report["fact_recall"] == 1.0
    assert report["hallucination_rate"] == 0.5
    assert report["per_case"][1]["score"] == 0.0
    assert all(
        not isinstance(value, float) or len(str(value).partition(".")[2]) <= 4
        for key, value in report.items()
        if key != "per_case"
    )


def test_ac14_cli_json_pretty_error_and_help_contracts(tmp_path):
    compact = _run_cli("eval-meta", str(FIXTURE), "--json")
    assert compact.returncode == 0, compact.stderr
    assert compact.stderr == ""
    assert compact.stdout.count("\n") == 1
    report = json.loads(compact.stdout)
    assert {key: report[key] for key in HEADLINE} == HEADLINE
    assert [case["id"] for case in report["per_case"]] == EXPECTED_IDS

    pretty = _run_cli("eval-meta", str(FIXTURE))
    assert pretty.returncode == 0, pretty.stderr
    assert json.loads(pretty.stdout) == report
    assert "\n  \"score\"" in pretty.stdout

    missing = _run_cli("eval-meta", str(tmp_path / "missing"), "--json")
    assert missing.returncode == 2
    assert missing.stdout == ""
    assert missing.stderr.startswith("sportscut eval-meta: error: ")

    help_result = _run_cli("eval-meta", "--help")
    assert help_result.returncode == 0
    assert "DIRECTORY" in help_result.stdout
    assert "--json" in help_result.stdout


def test_ac14_fixture_is_exact_order_utf8_nfc_and_has_the_baseline():
    fixture_text = (FIXTURE / "cases.json").read_text(encoding="utf-8")
    assert unicodedata.is_normalized("NFC", fixture_text)
    payload = json.loads(fixture_text)
    assert len(payload) == 8
    assert [case["id"] for case in payload] == EXPECTED_IDS
    report = evaluate_meta_dir(FIXTURE)
    assert {key: report[key] for key in HEADLINE} == HEADLINE


def test_ac15_readme_documents_the_measured_cli_baseline():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    heading = "## Bình luận AI: đo chất lượng tiêu đề, caption, hashtag (eval-meta)"
    assert heading in readme
    section = readme.split(heading, 1)[1].split("\n## ", 1)[0]
    assert "python -m sportscut eval-meta tests/fixtures/eval_meta --json" in section
    assert all(word in section for word in ("facts", "must_mention", "forbidden"))
    assert all(rule in section for rule in ("10", "80", "300", "3", "8", "score"))
    blocks = re.findall(r"```json\s*(\{.*?\})\s*```", section, flags=re.DOTALL)
    assert blocks, "eval-meta README section has no JSON baseline block"
    assert json.loads(blocks[0]) == HEADLINE

    command_report = json.loads(_run_cli("eval-meta", str(FIXTURE), "--json").stdout)
    assert {key: command_report[key] for key in HEADLINE} == json.loads(blocks[0])


def test_ac16_protected_implementation_files_are_unchanged_from_main():
    protected = [
        "sportscut/detect.py",
        "sportscut/evaluate.py",
        "sportscut/models.py",
        "sportscut/export.py",
        "sportscut/pipeline.py",
        "sportscut/api.py",
        "pyproject.toml",
        "tests/conftest.py",
    ]
    result = subprocess.run(
        ["git", "diff", "--name-only", "main", "--", *protected],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
