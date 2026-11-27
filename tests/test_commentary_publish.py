import json
import re
from types import SimpleNamespace as NS

import pytest

from sportscut import cli
from sportscut.commentary import eval_meta, publish
from sportscut.commentary.facts import ClipFacts, facts_from_entry
from sportscut.commentary.meta import EVENT_TAGS, ClipMeta, generate_meta

MATCH = {"home": "Hà Nội FC", "away": "Hải Phòng", "competition": "V.League 2026", "kickoff": 0}
KEYS = ["title", "caption", "hashtags"]
ENTRIES = [{"start": s, "end": s + 12, "score": 0.5, "reason": "audio", "event_confidence": 0.5, "file": f"clip_0{i}.mp4"}
           for i, s in enumerate((1370, 2400, 3000), 1)]
ENTRIES[0].update(event="goal", script_file="clip_01.script.json")
ENTRIES[1]["event"] = "save"
EVENTS = ["goal", "save", "other"]
FACTS = [facts_from_entry({**e, "event": ev}, MATCH) for e, ev in zip(ENTRIES, EVENTS)]

def _manifest(tmp_path, entries=ENTRIES):
    (tmp_path / "highlights.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")
    return tmp_path

_meta = lambda e: ClipMeta(e["title"], e["caption"], tuple(e["hashtags"]))  # noqa: E731
_read = lambda path: json.loads(path.read_text(encoding="utf-8"))  # noqa: E731

def test_template_fields_last_valid_and_idempotent(tmp_path):
    out = publish.write_meta(_manifest(tmp_path), MATCH)
    raw = (tmp_path / "highlights.json").read_text(encoding="utf-8")
    assert raw.endswith("\n") and "Hà Nội" in raw and "\\u" not in raw and json.loads(raw) == out
    for i, (old, new, facts) in enumerate(zip(ENTRIES, out, FACTS)):
        assert list(new) == list(old) + KEYS and {k: new[k] for k in old} == old
        assert eval_meta.format_problems(_meta(new)) == eval_meta.validate_meta(facts, _meta(new)) == []
        assert {k: new[k] for k in KEYS} == generate_meta(facts, clip=i).to_dict()
    assert "phút 23" in out[0]["title"] + out[0]["caption"]
    assert publish.write_meta(tmp_path, MATCH) == out and (tmp_path / "highlights.json").read_text(encoding="utf-8") == raw
    text = (tmp_path / "captions.txt").read_text(encoding="utf-8")
    assert text == "\n\n".join(f"{e['file']}\n{e['title']}\n{e['caption']}\n" + " ".join(e["hashtags"]) for e in out) + "\n"
    assert [len(b.split("\n")) for b in text.strip().split("\n\n")] == [4, 4, 4] and not text.endswith("\n\n")

def test_generic_without_match(tmp_path):
    for e, ev in zip(publish.write_meta(_manifest(tmp_path)), EVENTS):
        assert "phút" not in e["title"] + e["caption"]
        assert eval_meta._unknown_names(ClipFacts(ev), [e["title"], e["caption"]]) == []
        assert e["hashtags"] == ["#BongDa", "#" + EVENT_TAGS[ev], "#Highlight"]
    reel = _read(tmp_path / "reel.json")
    assert reel["title"] == "Tổng hợp highlight trận đấu" and reel["hashtags"][:3] == ["#BongDa", "#Highlight", "#TongHop"]
    assert set(reel["hashtags"][3:]) <= {"#" + t for t in EVENT_TAGS.values()}

def test_reel_meta_examples_and_overflow():
    full = dict(home="Hà Nội FC", away="Hải Phòng", competition="V.League 2026", score="2-1")
    assert publish.reel_meta([ClipFacts(e, **full) for e in ("goal", "save", "goal")]) == ClipMeta(
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
    assert big.title == "Tổng hợp highlight trận đấu" and len(big.hashtags) == 8 and eval_meta.format_problems(big) == []
    assert len(big.caption) <= 300 and "Tổng hợp 50 khoảnh khắc" in big.caption and "bàn thắng" not in big.caption
    dup = publish.reel_meta([ClipFacts("goal", home="Highlight", away="Ban Thắng")])
    assert dup.hashtags == ("#BongDa", "#Highlight", "#TongHop", "#BanThang")

def test_reel_json_valid_and_no_invented_numbers(tmp_path):
    publish.write_meta(_manifest(tmp_path), {**MATCH, "score": "2-1"})
    raw = (tmp_path / "reel.json").read_text(encoding="utf-8")
    reel, text = json.loads(raw), json.loads(raw)["title"] + " " + json.loads(raw)["caption"]
    assert raw.endswith("\n") and "Tổng hợp" in raw and "\\u" not in raw and list(reel) == KEYS
    assert eval_meta.format_problems(_meta(reel)) == [] and set(re.findall(r"\d+", text)) <= {"3", "1", "2026", "2"}
    facts = ClipFacts("other", home="Hà Nội FC", away="Hải Phòng", competition="V.League 2026", score="2-1")
    assert eval_meta._unknown_names(facts, [reel["title"], reel["caption"]]) == [] and eval_meta._is_vi_text(facts, text)

def fake_client(text=None, exc=None):
    def create(**kwargs):
        if calls.append(kwargs) or exc:
            raise exc
        return NS(content=[NS(type="text", text=text)])
    calls = []
    return NS(calls=calls, messages=NS(create=create))

@pytest.mark.parametrize("bad", [None, "Pha cứu thua của Liverpool tại V.League 2026.", "Pha cứu thua phút 99."])
def test_llm_backend_and_per_clip_fallback(tmp_path, bad):
    clips = [{"id": i, "title": f"{publish.EVENT_LABELS[f.event]} cực đẹp: {f.home} vs {f.away}",
              "caption": f"Trận đấu tại {f.competition}, phút {f.minute}. Xem ngay nhé!",
              "hashtags": ["#BongDa", "#Hay", "#Clip"]} for i, f in enumerate(FACTS)]
    want = [{k: c[k] for k in KEYS} for c in clips]
    if bad:
        clips[1]["caption"], want[1] = bad, generate_meta(FACTS[1]).to_dict()
    client = fake_client(json.dumps({"clips": clips}, ensure_ascii=False))
    out = publish.write_meta(_manifest(tmp_path), MATCH, backend="llm", client=client)
    assert [{k: e[k] for k in KEYS} for e in out] == want
    assert all(w["caption"] in (tmp_path / "captions.txt").read_text(encoding="utf-8") for w in want)
    (call,) = client.calls
    assert len(json.loads(call["messages"][0]["content"])["clips"]) == 3 and len(call["messages"]) == 1
    assert _read(tmp_path / "reel.json") == publish.reel_meta(FACTS).to_dict()
    out = publish.write_meta(tmp_path, MATCH, backend="llm", client=fake_client(exc=RuntimeError("boom")))
    assert [{k: e[k] for k in KEYS} for e in out] == [generate_meta(f).to_dict() for f in FACTS]

BAD = [None, "{not json", "{}", "[]", '["x"]', '[{"start": 1, "end": 5}]', '[{"start": 5, "end": 5, "file": "a.mp4"}]']

@pytest.mark.parametrize("raw,match,backend,msg", [(r, MATCH, "template", "highlights.json") for r in BAD] + [
    (json.dumps(ENTRIES), MATCH, "gpt", "^unknown backend: gpt$"),
    (json.dumps(ENTRIES), {"venue": "Mỹ Đình"}, "template", "unknown match key")])
def test_errors_change_nothing(tmp_path, raw, match, backend, msg):
    if raw is not None:
        (tmp_path / "highlights.json").write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError, match=msg):
        publish.write_meta(tmp_path, match, backend=backend)
    assert sorted(p.name for p in tmp_path.iterdir()) == ([] if raw is None else ["highlights.json"])
    assert raw is None or (tmp_path / "highlights.json").read_text(encoding="utf-8") == raw

def test_cli_meta_success_and_errors(tmp_path, capsys):
    d = _manifest(tmp_path)
    assert cli.main(["meta", str(d), "--home", "Hà Nội FC", "--away", "Hải Phòng", "--kickoff", "0"]) == 0
    assert capsys.readouterr().out.splitlines() == [str(d / n) for n in ("highlights.json", "captions.txt", "reel.json")]
    assert "phút 23" in _read(d / "highlights.json")[0]["caption"]
    (tmp_path / "m.json").write_text('{"home": "Arsenal", "away": "Chelsea", "score": "1-0"}', encoding="utf-8")
    assert cli.main(["meta", str(d), "--match-info", str(tmp_path / "m.json"), "--home", "Hà Nội FC"]) == 0
    entries = _read(d / "highlights.json")
    assert all("Hà Nội FC" in e["caption"] and "Arsenal" not in e["caption"] + e["title"] for e in entries)
    assert "Tỉ số: 1-0" in _read(d / "reel.json")["caption"]
    (empty := tmp_path / "empty").mkdir()
    (empty / "bad.json").write_text("[1]", encoding="utf-8")
    capsys.readouterr()
    for argv in ([empty], [d, "--match-info", empty / "bad.json"], [d, "--match-info", empty / "nope.json"]):
        assert cli.main(["meta", *map(str, argv)]) == 1
        err = capsys.readouterr()
        assert err.out == "" and err.err.startswith("sportscut meta: error: ")
    assert sorted(p.name for p in empty.iterdir()) == ["bad.json"]
    for argv in (["--kickoff", "abc"], ["--meta-backend", "gpt"], ["--help"]):
        with pytest.raises(SystemExit) as exc:
            cli.main(["meta", str(d), *argv])
        assert exc.value.code == (0 if argv == ["--help"] else 2)
    help_text = capsys.readouterr().out
    assert all(o in help_text for o in ("OUT_DIR", "--home", "--away", "--competition", "--kickoff", "--match-info", "--meta-backend"))
