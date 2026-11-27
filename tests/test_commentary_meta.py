import pytest

from sportscut.commentary.facts import ClipFacts


def test_hashtag_ascii_folding() -> None:
    from sportscut.commentary.meta import hashtag

    assert hashtag("Hà Nội FC") == "#HaNoiFC"
    assert hashtag("U23 Việt Nam") == "#U23VietNam"
    assert hashtag("V.League 2026") == "#VLeague2026"
    assert hashtag("!!!") is None


def test_generate_meta_full_goal() -> None:
    from sportscut.commentary.meta import generate_meta

    result = generate_meta(ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0"))
    assert result.title == "Pha lập công: Hà Nội FC vs Hải Phòng, phút 23"
    assert result.caption == (
        "Một bàn thắng đáng nhớ trong trận Hà Nội FC gặp Hải Phòng ở phút 23 tại V.League 2026. "
        "Tỉ số: 1-0. Hãy cùng xem lại nhé!"
    )
    assert result.hashtags == (
        "#BongDa", "#BanThang", "#Highlight", "#HaNoiFC", "#HaiPhong", "#VLeague2026"
    )


def test_generate_meta_bare_other() -> None:
    from sportscut.commentary.meta import generate_meta

    result = generate_meta(ClipFacts("other"))
    assert result.title == "Khoảnh khắc ấn tượng trong trận đấu"
    assert result.caption == "Khoảnh khắc đáng chú ý trong trận đấu. Cùng xem lại khoảnh khắc này!"
    assert result.hashtags == ("#BongDa", "#KhoanhKhac", "#Highlight")


def test_title_fallbacks_and_single_team_caption() -> None:
    from sportscut.commentary.meta import generate_meta

    long_names = ClipFacts(
        "goal", 120, "Câu lạc bộ Bóng đá Công an Hà Nội", "Becamex Bình Dương Football Club"
    )
    assert generate_meta(long_names).title == (
        "Khoảnh khắc ghi bàn, phút 120"
    )
    assert generate_meta(ClipFacts("red_card", 88)).title == "Tấm thẻ đỏ, phút 88"
    one_team = generate_meta(ClipFacts("goal", home="Arsenal"))
    assert one_team.title == "Siêu phẩm: Arsenal"
    assert "trong trận đấu của Arsenal" in one_team.caption


def test_hashtags_are_deduplicated_case_insensitively() -> None:
    from sportscut.commentary.meta import generate_meta

    tags = generate_meta(ClipFacts("goal", home="Ha Noi", away="Hà Nội")).hashtags
    assert tags == ("#BongDa", "#BanThang", "#Highlight", "#HaNoi")


def test_unknown_backend_and_to_dict_order() -> None:
    from sportscut.commentary.meta import ClipMeta, generate_meta

    with pytest.raises(ValueError, match="^unknown backend: llm$"):
        generate_meta(ClipFacts("goal"), backend="llm")
    result = ClipMeta("0123456789", "caption", ("#One", "#Two", "#Three")).to_dict()
    assert list(result) == ["title", "caption", "hashtags"]
    assert result["hashtags"] == ["#One", "#Two", "#Three"]
