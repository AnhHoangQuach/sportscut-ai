import json
import re
from types import SimpleNamespace as NS

import pytest

from sportscut import cli
from sportscut.commentary import eval_meta, publish
from sportscut.commentary.facts import ClipFacts, facts_from_entry
from sportscut.commentary.meta import EVENT_TAGS, ClipMeta, generate_meta

MATCH = {"home": "Hà Nội FC", "away": "Hải Phòng", "competition": "V.League 2026", "kickoff": 0}
ENTRIES = [
    {"start": 1370, "end": 1382, "score": 0.9, "reason": "audio", "event": "goal", "event_confidence": 0.8,
     "file": "clip_01.mp4", "script_file": "clip_01.script.json"},
    {"start": 2400, "end": 2412, "score": 0.7, "reason": "audio", "event": "save", "event_confidence": 0.6,
     "file": "clip_02.mp4"},
    {"start": 3000, "end": 3010, "score": 0.5, "reason": "audio", "event_confidence": 0.1, "file": "clip_03.mp4"},
]
EVENTS = ["goal", "save", "other"]


def _manifest(tmp_path, entries=ENTRIES):
    (tmp_path / "highlights.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return tmp_path


def _meta(entry):
    return ClipMeta(entry["title"], entry["caption"], tuple(entry["hashtags"]))


def test_template_fields_last_and_valid(tmp_path):
    out = publish.write_meta(_manifest(tmp_path), MATCH)
    raw = (tmp_path / "highlights.json").read_text(encoding="utf-8")
    assert raw.endswith("\n") and "Hà Nội" in raw and "\\u" not in raw
    assert json.loads(raw) == out
    for i, (old, new, ev) in enumerate(zip(ENTRIES, out, EVENTS)):
        assert list(new) == list(old) + ["title", "caption", "hashtags"]
        assert {k: new[k] for k in old} == old
        facts = facts_from_entry({**old, "event": ev}, MATCH)
        assert eval_meta.format_problems(_meta(new)) == []
        assert eval_meta.validate_meta(facts, _meta(new)) == []
        assert {k: new[k] for k in publish.META_KEYS} == generate_meta(facts, clip=i).to_dict()
    assert "phút 23" in out[0]["title"] + out[0]["caption"]


def test_generic_without_match(tmp_path):
    out = publish.write_meta(_manifest(tmp_path))
    for entry, ev in zip(out, EVENTS):
        assert "phút" not in entry["title"] + entry["caption"]
        assert eval_meta._unknown_names(ClipFacts(ev), [entry["title"], entry["caption"]]) == []
        assert entry["hashtags"] == ["#BongDa", "#" + EVENT_TAGS[ev], "#Highlight"]
    reel = json.loads((tmp_path / "reel.json").read_text(encoding="utf-8"))
    assert reel["title"] == "Tổng hợp highlight trận đấu"
    assert reel["hashtags"][:3] == ["#BongDa", "#Highlight", "#TongHop"]
    assert set(reel["hashtags"][3:]) <= {"#" + t for t in EVENT_TAGS.values()}


def test_rerun_is_idempotent(tmp_path):
    publish.write_meta(_manifest(tmp_path), MATCH)
    first = (tmp_path / "highlights.json").read_bytes()
    out = publish.write_meta(tmp_path, MATCH)
    assert (tmp_path / "highlights.json").read_bytes() == first
    assert all(list(e)[-3:] == ["title", "caption", "hashtags"] for e in out)


def test_reel_meta_examples_and_overflow():
    full = dict(home="Hà Nội FC", away="Hải Phòng", competition="V.League 2026", score="2-1")
    reel = publish.reel_meta([ClipFacts(e, **full) for e in ("goal", "save", "goal")])
    assert reel == ClipMeta(
        "Tổng hợp highlight: Hà Nội FC vs Hải Phòng",
        "Tổng hợp 3 khoảnh khắc đáng chú ý trong trận Hà Nội FC gặp Hải Phòng tại V.League 2026: "
        "2 bàn thắng, 1 pha cứu thua. Tỉ số: 2-1. Cùng xem lại nhé!",
        ("#BongDa", "#Highlight", "#TongHop", "#HaNoiFC", "#HaiPhong", "#VLeague2026", "#BanThang", "#CuuThua"))
    assert publish.reel_meta([ClipFacts("goal"), ClipFacts("other")]) == ClipMeta(
        "Tổng hợp highlight trận đấu",
        "Tổng hợp 2 khoảnh khắc đáng chú ý trong trận đấu: 1 bàn thắng, 1 khoảnh khắc đáng chú ý. Cùng xem lại nhé!",
        ("#BongDa", "#Highlight", "#TongHop", "#BanThang", "#KhoanhKhac"))
    names = dict(home="H" * 40, away="A" * 40, competition="C" * 40, score="99-99")
    big = publish.reel_meta([ClipFacts(e, **names) for e in ("goal", "save", "red_card", "controversy", "other") * 10])
    assert big.title == "Tổng hợp highlight trận đấu"
    assert len(big.caption) <= 300 and "Tổng hợp 50 khoảnh khắc" in big.caption and "bàn thắng" not in big.caption
    assert len(big.hashtags) == 8 and eval_meta.format_problems(big) == []
    dup = publish.reel_meta([ClipFacts("goal", home="Highlight", away="Ban Thắng")])
    assert dup.hashtags == ("#BongDa", "#Highlight", "#TongHop", "#BanThang")


def test_reel_json_valid_and_no_invented_numbers(tmp_path):
    match = {**MATCH, "score": "2-1"}
    publish.write_meta(_manifest(tmp_path), match)
    raw = (tmp_path / "reel.json").read_text(encoding="utf-8")
    assert raw.endswith("\n") and "Tổng hợp" in raw and "\\u" not in raw
    reel = json.loads(raw)
    assert list(reel) == ["title", "caption", "hashtags"] and isinstance(reel["hashtags"], list)
    assert eval_meta.format_problems(_meta(reel)) == []
    text = reel["title"] + " " + reel["caption"]
    allowed = {"3", "1"} | set(re.findall(r"\d+", " ".join(str(match[k]) for k in ("home", "away", "competition", "score"))))
    assert set(re.findall(r"\d+", text)) <= allowed
    facts = ClipFacts("other", home=match["home"], away=match["away"], competition=match["competition"], score="2-1")
    assert eval_meta._unknown_names(facts, [reel["title"], reel["caption"]]) == []
    assert eval_meta._is_vi_text(facts, text)


def test_captions_txt_blocks(tmp_path):
    out = publish.write_meta(_manifest(tmp_path), MATCH)
    text = (tmp_path / "captions.txt").read_text(encoding="utf-8")
    want = "\n\n".join(f"{e['file']}\n{e['title']}\n{e['caption']}\n" + " ".join(e["hashtags"]) for e in out) + "\n"
    assert text == want and not text.endswith("\n\n")
    assert [len(block.split("\n")) for block in text.strip().split("\n\n")] == [4, 4, 4]


def fake_client(text=None, exc=None):
    def create(**kwargs):
        if calls.append(kwargs) or exc:
            raise exc
        return NS(content=[NS(type="text", text=text)])
    calls = []
    return NS(calls=calls, messages=NS(create=create))


def _facts():
    return [facts_from_entry({**e, "event": ev}, MATCH) for e, ev in zip(ENTRIES, EVENTS)]


def _llm_text(bad=None):
    clips = [{"id": i, "title": f"{publish.EVENT_LABELS[f.event]} cực đẹp: {f.home} vs {f.away}",
              "caption": f"Trận đấu tại {f.competition}, phút {f.minute}. Xem ngay nhé!",
              "hashtags": ["#BongDa", "#Hay", "#Clip"]} for i, f in enumerate(_facts())]
    if bad:
        clips[1]["caption"] = bad
    return json.dumps({"clips": clips}, ensure_ascii=False), clips


def test_llm_backend_fake_client(tmp_path):
    text, clips = _llm_text()
    for f, c in zip(_facts(), clips):
        assert eval_meta.validate_meta(f, ClipMeta(c["title"], c["caption"], tuple(c["hashtags"]))) == []
    client = fake_client(text)
    out = publish.write_meta(_manifest(tmp_path), MATCH, backend="llm", client=client)
    assert [{k: e[k] for k in publish.META_KEYS} for e in out] == [{k: c[k] for k in publish.META_KEYS} for c in clips]
    captions = (tmp_path / "captions.txt").read_text(encoding="utf-8")
    assert all(c["title"] in captions and c["caption"] in captions for c in clips)
    (call,) = client.calls
    (message,) = call["messages"]
    assert len(json.loads(message["content"])["clips"]) == 3
    reel = json.loads((tmp_path / "reel.json").read_text(encoding="utf-8"))
    assert reel == publish.reel_meta(_facts()).to_dict()


@pytest.mark.parametrize("bad", ["Pha cứu thua của Liverpool tại V.League 2026, phút 40.", "Pha cứu thua phút 99."])
def test_llm_hallucination_falls_back_per_clip(tmp_path, bad):
    text, clips = _llm_text(bad)
    out = publish.write_meta(_manifest(tmp_path), MATCH, backend="llm", client=fake_client(text))
    got = [{k: e[k] for k in publish.META_KEYS} for e in out]
    assert got[1] == generate_meta(_facts()[1]).to_dict()
    assert [got[0], got[2]] == [{k: clips[i][k] for k in publish.META_KEYS} for i in (0, 2)]
    out = publish.write_meta(tmp_path, MATCH, backend="llm", client=fake_client(exc=RuntimeError("boom")))
    assert [{k: e[k] for k in publish.META_KEYS} for e in out] == [generate_meta(f).to_dict() for f in _facts()]
    assert all((tmp_path / n).is_file() for n in ("highlights.json", "captions.txt", "reel.json"))


BAD = [None, "{not json", json.dumps({"clips": []}), "[]", '["x"]',
       json.dumps([{"start": 1, "end": 5}]), json.dumps([{"start": 5, "end": 5, "file": "a.mp4"}])]


@pytest.mark.parametrize("raw", BAD)
def test_errors_change_nothing(tmp_path, raw):
    if raw is not None:
        (tmp_path / "highlights.json").write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match="highlights.json"):
        publish.write_meta(tmp_path, MATCH)
    assert not (tmp_path / "captions.txt").exists() and not (tmp_path / "reel.json").exists()
    if raw is not None:
        assert (tmp_path / "highlights.json").read_text(encoding="utf-8") == raw


def test_bad_backend_and_match_key_change_nothing(tmp_path):
    before = _manifest(tmp_path).joinpath("highlights.json").read_bytes()
    with pytest.raises(ValueError, match="^unknown backend: gpt$"):
        publish.write_meta(tmp_path, backend="gpt")
    with pytest.raises(ValueError, match="unknown match key"):
        publish.write_meta(tmp_path, {"venue": "Mỹ Đình"})
    assert (tmp_path / "highlights.json").read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["highlights.json"]


def test_cli_meta_success_and_errors(tmp_path, capsys):
    out_dir = _manifest(tmp_path)
    assert cli.main(["meta", str(out_dir), "--home", "Hà Nội FC", "--away", "Hải Phòng", "--kickoff", "0"]) == 0
    stdout = capsys.readouterr().out
    assert stdout.splitlines() == [str(out_dir / n) for n in ("highlights.json", "captions.txt", "reel.json")]
    assert "phút 23" in json.loads((out_dir / "highlights.json").read_text(encoding="utf-8"))[0]["caption"]
    (tmp_path / "match.json").write_text('{"home": "Arsenal", "away": "Chelsea", "score": "1-0"}', encoding="utf-8")
    assert cli.main(["meta", str(out_dir), "--match-info", str(tmp_path / "match.json"), "--home", "Hà Nội FC"]) == 0
    capsys.readouterr()
    entries = json.loads((out_dir / "highlights.json").read_text(encoding="utf-8"))
    assert all("Hà Nội FC" in e["title"] + e["caption"] and "Arsenal" not in e["caption"] for e in entries)
    assert "Tỉ số: 1-0" in json.loads((out_dir / "reel.json").read_text(encoding="utf-8"))["caption"]
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "bad.json").write_text("[1]", encoding="utf-8")
    for argv in ([str(empty)], [str(out_dir), "--match-info", str(empty / "bad.json")],
                 [str(out_dir), "--match-info", str(empty / "nope.json")]):
        assert cli.main(["meta", *argv]) == 1
        err = capsys.readouterr()
        assert err.out == "" and err.err.startswith("sportscut meta: error: ")
    assert sorted(p.name for p in empty.iterdir()) == ["bad.json"]
    for argv in (["--kickoff", "abc"], ["--meta-backend", "gpt"]):
        with pytest.raises(SystemExit) as exc:
            cli.main(["meta", str(out_dir), *argv])
        assert exc.value.code == 2
    with pytest.raises(SystemExit):
        cli.main(["meta", "--help"])
    help_text = capsys.readouterr().out
    assert all(o in help_text for o in ("OUT_DIR", "--home", "--away", "--competition", "--kickoff", "--match-info", "--meta-backend"))
