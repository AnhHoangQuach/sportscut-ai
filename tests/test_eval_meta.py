import json
from pathlib import Path

import pytest

from sportscut.commentary.facts import ClipFacts
from sportscut.commentary.meta import ClipMeta

FIXTURE = Path("tests/fixtures/eval_meta")


def _case(facts=None, must=None, forbidden=None):
    from sportscut.commentary.eval_meta import MetaCase

    return MetaCase("case", facts or ClipFacts("goal"), must or [["bàn thắng"]], forbidden or [])


def _valid(**changes):
    values = {
        "title": "Bàn thắng đẹp",
        "caption": "Bàn thắng tuyệt vời.",
        "hashtags": ("#BongDa", "#BanThang", "#Highlight"),
    }
    values.update(changes)
    return ClipMeta(**values)


@pytest.mark.parametrize(
    ("meta", "problem"),
    [
        (_valid(title="123456789"), "title length 9"),
        (_valid(title="x" * 81), "title length 81"),
        (_valid(title=" Bàn thắng đẹp "), "title length 15"),
        (_valid(caption=""), "caption length 0"),
        (_valid(caption="x" * 301), "caption length 301"),
        (_valid(hashtags=("#One", "#Two")), "hashtag count 2"),
        (_valid(hashtags=tuple(f"#Tag{i}" for i in range(9))), "hashtag count 9"),
        (_valid(hashtags=("#Bóng", "#Two", "#Three")), "bad hashtag #Bóng"),
        (_valid(hashtags=("BongDa", "#Two", "#Three")), "bad hashtag BongDa"),
        (_valid(hashtags=("#BongDa", "#bongda", "#Three")), "duplicate hashtag #bongda"),
    ],
)
def test_score_case_reports_each_format_problem(meta, problem: str) -> None:
    from sportscut.commentary.eval_meta import score_case

    result = score_case(_case(), meta)
    assert result["format_ok"] is False
    assert problem in result["problems"]


def test_score_case_valid_metadata_and_key_order() -> None:
    from sportscut.commentary.eval_meta import score_case

    result = score_case(_case(), _valid())
    assert list(result) == [
        "id", "score", "format_ok", "fact_recall", "hallucinated", "vi",
        "problems", "title", "caption", "hashtags",
    ]
    assert result["format_ok"] is True
    assert result["hallucinated"] is False
    assert result["vi"] is True
    assert result["problems"] == []


def test_score_case_recall_any_of_and_hashtags() -> None:
    from sportscut.commentary.eval_meta import score_case

    case = _case(must=[["không có", "BÀN THẮNG"], ["specialtag"], ["missing"]])
    result = score_case(case, _valid(hashtags=("#BongDa", "#SpecialTag", "#Highlight")))
    assert result["fact_recall"] == 0.6667
    half = score_case(_case(must=[["absent", "BÀN THẮNG"], ["missing"]]), _valid())
    assert half["fact_recall"] == 0.5


def test_score_case_detects_wrong_number_and_forbidden_name() -> None:
    from sportscut.commentary.eval_meta import score_case

    facts = ClipFacts("goal", 23, "Arsenal", "Chelsea")
    wrong = score_case(_case(facts, forbidden=["Liverpool"]), _valid(caption="Bàn thắng ở phút 24."))
    assert wrong["hallucinated"] is True
    assert "number 24 not in facts" in wrong["problems"]
    assert wrong["score"] == 0.0
    forbidden = score_case(_case(facts, forbidden=["Liverpool"]), _valid(caption="Bàn thắng trước LIVERPOOL."))
    assert forbidden["hallucinated"] is True
    assert "forbidden Liverpool" in forbidden["problems"]


def test_score_case_accepts_all_numbers_from_facts() -> None:
    from sportscut.commentary.eval_meta import score_case

    facts = ClipFacts("goal", 23, "U23 Việt Nam", "Chelsea", "V.League 2026", "1-0")
    output = _valid(caption="Bàn thắng U23 ở phút 23 tại V.League 2026, tỉ số 1-0.")
    assert score_case(_case(facts), output)["hallucinated"] is False


def test_score_case_rejects_english_only_text() -> None:
    from sportscut.commentary.eval_meta import score_case

    facts = ClipFacts("goal", 23, "Arsenal", "Chelsea")
    output = _valid(title="Goal: Arsenal vs Chelsea, minute 23", caption="Great goal by the home side")
    result = score_case(_case(facts, must=[["goal"]]), output)
    assert result["vi"] is False
    assert "not vietnamese" in result["problems"]
    assert result["score"] == 0.0


def _write_cases(tmp_path: Path, data) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "data",
    [
        {}, [], [1], [{"id": "", "facts": {"event": "goal"}, "must_mention": [["x"]], "forbidden": []}],
        [{"id": "x", "facts": [], "must_mention": [["x"]], "forbidden": []}],
        [{"id": "x", "facts": {"event": "goal", "venue": "x"}, "must_mention": [["x"]], "forbidden": []}],
        [{"id": "x", "facts": {"event": "penalty"}, "must_mention": [["x"]], "forbidden": []}],
        [{"id": "x", "facts": {"event": "goal"}, "must_mention": [], "forbidden": []}],
        [{"id": "x", "facts": {"event": "goal"}, "must_mention": [[]], "forbidden": []}],
        [{"id": "x", "facts": {"event": "goal"}, "must_mention": [[""]], "forbidden": []}],
        [{"id": "x", "facts": {"event": "goal"}, "must_mention": [["x"]], "forbidden": [""]}],
        [{"id": "x", "facts": {"event": "goal", "home": "Arsenal"}, "must_mention": [["x"]], "forbidden": ["arsenal"]}],
    ],
)
def test_load_cases_rejects_invalid_shapes(tmp_path: Path, data) -> None:
    from sportscut.commentary.eval_meta import load_cases

    path = _write_cases(tmp_path, data)
    with pytest.raises(ValueError, match="cases.json"):
        load_cases(path)


def test_load_cases_rejects_invalid_json_and_duplicate_id(tmp_path: Path) -> None:
    from sportscut.commentary.eval_meta import load_cases

    path = tmp_path / "cases.json"
    path.write_text("{")
    with pytest.raises(ValueError, match="cases.json"):
        load_cases(path)


def test_load_cases_empty_error_and_indexed_error(tmp_path: Path) -> None:
    from sportscut.commentary.eval_meta import load_cases

    path = _write_cases(tmp_path, [])
    with pytest.raises(ValueError, match="no eval cases"):
        load_cases(path)
    path = _write_cases(tmp_path, [{"id": "x"}])
    with pytest.raises(ValueError, match=r"\[0\]"):
        load_cases(path)
    item = {"id": "same", "facts": {"event": "goal"}, "must_mention": [["x"]], "forbidden": []}
    path = _write_cases(tmp_path, [item, item])
    with pytest.raises(ValueError, match="cases.json"):
        load_cases(path)


def test_evaluate_meta_dir_validates_directory(tmp_path: Path) -> None:
    from sportscut.commentary.eval_meta import evaluate_meta_dir

    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="not a directory"):
        evaluate_meta_dir(missing)
    with pytest.raises(ValueError, match="missing cases.json"):
        evaluate_meta_dir(tmp_path)


def test_evaluate_meta_dir_aggregates_and_uses_module_generator(tmp_path: Path, monkeypatch) -> None:
    from sportscut.commentary import meta
    from sportscut.commentary.eval_meta import evaluate_meta_dir

    data = [
        {"id": "good", "facts": {"event": "goal", "minute": 23}, "must_mention": [["bàn thắng"]], "forbidden": []},
        {"id": "bad", "facts": {"event": "goal", "minute": 23}, "must_mention": [["bàn thắng"]], "forbidden": []},
    ]
    _write_cases(tmp_path, data)
    outputs = iter([_valid(), _valid(caption="Bàn thắng ở phút 24.")])
    monkeypatch.setattr(meta, "generate_meta", lambda facts: next(outputs))
    report = evaluate_meta_dir(tmp_path)
    assert list(report) == ["score", "format_ok", "fact_recall", "hallucination_rate", "vi_rate", "per_case"]
    assert report["score"] == 0.5
    assert report["fact_recall"] == 1.0
    assert report["hallucination_rate"] == 0.5


def test_evaluate_meta_dir_uses_raw_scores_and_micro_recall(tmp_path: Path, monkeypatch) -> None:
    from sportscut.commentary import meta
    from sportscut.commentary.eval_meta import evaluate_meta_dir

    data = [
        {"id": "all", "facts": {"event": "goal"}, "must_mention": [["bàn thắng"]], "forbidden": []},
        {
            "id": "third", "facts": {"event": "goal"},
            "must_mention": [["bàn thắng"], ["missing one"], ["missing two"]], "forbidden": [],
        },
    ]
    _write_cases(tmp_path, data)
    monkeypatch.setattr(meta, "generate_meta", lambda facts: _valid())
    report = evaluate_meta_dir(tmp_path)
    assert report["score"] == 0.6667
    assert report["fact_recall"] == 0.5


def test_fixture_baseline_and_format_limits() -> None:
    from sportscut.commentary import meta
    from sportscut.commentary.eval_meta import evaluate_meta_dir, load_cases

    cases = load_cases(FIXTURE / "cases.json")
    assert [case.id for case in cases] == [
        "goal_full", "save_teams", "red_card_minute_only", "controversy_no_minute",
        "other_bare", "goal_long_names", "goal_u23", "save_competition_only",
    ]
    for case in cases:
        output = meta.generate_meta(case.facts)
        assert 10 <= len(output.title) <= 80
        assert len(output.caption) <= 300
    report = evaluate_meta_dir(FIXTURE)
    assert {key: report[key] for key in list(report)[:5]} == {
        "score": 1.0, "format_ok": 1.0, "fact_recall": 1.0,
        "hallucination_rate": 0.0, "vi_rate": 1.0,
    }


def test_cli_eval_meta_json_pretty_error_and_help(tmp_path: Path, capsys) -> None:
    from sportscut.cli import main

    assert main(["eval-meta", str(FIXTURE), "--json"]) == 0
    compact = capsys.readouterr()
    report = json.loads(compact.out)
    assert len(compact.out.splitlines()) == 1
    assert list(report) == ["score", "format_ok", "fact_recall", "hallucination_rate", "vi_rate", "per_case"]
    assert main(["eval-meta", str(FIXTURE)]) == 0
    assert capsys.readouterr().out.startswith("{\n  \"score\": 1.0")
    assert main(["eval-meta", str(tmp_path / "missing")]) == 2
    error = capsys.readouterr()
    assert error.out == ""
    assert error.err.startswith("sportscut eval-meta: error: ")
    with pytest.raises(SystemExit) as exc:
        main(["eval-meta", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "DIRECTORY" in help_text and "--json" in help_text


def test_readme_records_eval_meta_contract_and_baseline() -> None:
    readme = Path("README.md").read_text(encoding="utf-8")
    assert "## Bình luận AI: đo chất lượng tiêu đề, caption, hashtag (eval-meta)" in readme
    assert "python -m sportscut eval-meta tests/fixtures/eval_meta --json" in readme
    assert all(word in readme for word in ("facts", "must_mention", "forbidden"))
    baseline = json.dumps(
        {"score": 1.0, "format_ok": 1.0, "fact_recall": 1.0, "hallucination_rate": 0.0, "vi_rate": 1.0},
        ensure_ascii=False,
    )
    assert baseline in readme
    assert "R-005" in readme and "không được giảm" in readme
