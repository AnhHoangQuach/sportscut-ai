import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from sportscut.cli import main
from sportscut.commentary import eval_meta, publish
from sportscut.commentary.facts import ClipFacts, facts_from_entry
from sportscut.commentary.meta import EVENT_LABELS, ClipMeta, generate_meta

ROOT = Path(__file__).resolve().parents[1]
MATCH = {"home": "Hà Nội FC", "away": "Hải Phòng", "competition": "V.League 2026", "kickoff": 0}
ENTRIES = [
    {"start": 1370, "end": 1382, "score": 0.9, "reason": "loud", "event": "goal", "event_confidence": 0.8, "file": "clip_01.mp4"},
    {"start": 2400, "end": 2412, "score": 0.7, "reason": "crowd", "event": "save", "event_confidence": 0.6,
     "file": "clip_02.mp4", "vertical_file": "clip_02_vertical.mp4"},
    {"start": 3000, "end": 3010, "score": 0.5, "reason": "x", "event_confidence": 0.1, "file": "clip_03.mp4"},
]
EVENTS = ["goal", "save", "other"]
def manifest(tmp_path, entries=ENTRIES):
    return (tmp_path / "highlights.json").write_text(json.dumps(entries, indent=2), encoding="utf-8") and tmp_path
def facts_list(match=MATCH):
    return [facts_from_entry({**e, "event": ev}, match) for e, ev in zip(ENTRIES, EVENTS)]
def llm_meta(f, i):
    return {"id": i, "title": f"{EVENT_LABELS[f.event]} | {f.home} vs {f.away}",
            "caption": f"{EVENT_LABELS[f.event]} ở phút {f.minute} tại {f.competition}, xem lại ngay nhé!",
            "hashtags": ["#BongDa", "#TuLLM", "#Highlight"]}
def fake_client(payload):
    calls = []
    create = lambda **kw: calls.append(kw) or NS(content=[NS(type="text", text=json.dumps(payload, ensure_ascii=False))])  # noqa: E731
    return NS(calls=calls, messages=NS(create=create))
def test_ac2_keys_order_values_and_utf8(tmp_path):
    result = publish.write_meta(manifest(tmp_path), MATCH)
    raw = (tmp_path / "highlights.json").read_text(encoding="utf-8")
    assert raw.endswith("\n") and "\\u" not in raw and "Hà Nội FC" in raw
    assert json.loads(raw) == result
    for old, new, i in zip(ENTRIES, result, range(3)):
        assert list(new) == list(old) + ["title", "caption", "hashtags"]
        assert {k: new[k] for k in old} == old
        assert new == {**old, **generate_meta(facts_list()[i], clip=i).to_dict()}
        assert eval_meta.validate_meta(facts_list()[i], ClipMeta(new["title"], new["caption"], tuple(new["hashtags"]))) == []
def test_ac6_captions_exact_two_clips(tmp_path):
    result = publish.write_meta(manifest(tmp_path, ENTRIES[:2]), MATCH)
    text = (tmp_path / "captions.txt").read_text(encoding="utf-8")
    want = "".join(f"{e['file']}\n{e['title']}\n{e['caption']}\n{' '.join(e['hashtags'])}" + sep
                   for e, sep in zip(result, ("\n\n", "\n")))
    assert text == want and not text.endswith("\n\n")
    assert [len(b.split("\n")) for b in text.strip().split("\n\n")] == [4, 4]
def test_ac7_reel_exact_examples_and_overflow():
    m = dict(home="Hà Nội FC", away="Hải Phòng", competition="V.League 2026", score="2-1")
    assert publish.reel_meta([ClipFacts(e, **m) for e in ("goal", "save", "goal")]) == ClipMeta(
        "Tổng hợp highlight: Hà Nội FC vs Hải Phòng",
        "Tổng hợp 3 khoảnh khắc đáng chú ý trong trận Hà Nội FC gặp Hải Phòng tại V.League 2026: "
        "2 bàn thắng, 1 pha cứu thua. Tỉ số: 2-1. Cùng xem lại nhé!",
        ("#BongDa", "#Highlight", "#TongHop", "#HaNoiFC", "#HaiPhong", "#VLeague2026", "#BanThang", "#CuuThua"))
    assert publish.reel_meta([ClipFacts("goal"), ClipFacts("other")]) == ClipMeta(
        "Tổng hợp highlight trận đấu",
        "Tổng hợp 2 khoảnh khắc đáng chú ý trong trận đấu: 1 bàn thắng, 1 khoảnh khắc đáng chú ý. Cùng xem lại nhé!",
        ("#BongDa", "#Highlight", "#TongHop", "#BanThang", "#KhoanhKhac"))
    big = dict(home="A" * 40, away="B" * 40, competition="C" * 40, score="99-99")
    reel = publish.reel_meta([ClipFacts(e, **big) for e in EVENT_LABELS for _ in range(10)])
    assert reel.title == "Tổng hợp highlight trận đấu" and len(reel.caption) <= 300
    assert "Tổng hợp 50 khoảnh khắc" in reel.caption and "bàn thắng" not in reel.caption
    assert len(reel.hashtags) == 8 and eval_meta.format_problems(reel) == []
@pytest.mark.parametrize("bad", ["phút 99", "Liverpool"])
def test_ac9_llm_one_call_and_per_clip_fallback(tmp_path, bad):
    facts = facts_list()
    clips = [llm_meta(f, i) for i, f in enumerate(facts)]
    clips[1]["caption"] = clips[1]["caption"].replace("xem lại", f"{bad} xem lại")
    client = fake_client({"clips": clips})
    result = publish.write_meta(manifest(tmp_path), MATCH, backend="llm", client=client)
    (call,) = client.calls
    assert [c["id"] for c in json.loads(call["messages"][0]["content"])["clips"]] == [0, 1, 2]
    got = [{k: e[k] for k in ("title", "caption", "hashtags")} for e in result]
    want = [{k: v for k, v in c.items() if k != "id"} for c in clips]
    assert got[0] == want[0] and got[2] == want[2] and got[1] == generate_meta(facts[1]).to_dict()
    assert want[0]["caption"] in (tmp_path / "captions.txt").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "reel.json").read_text(encoding="utf-8")) == publish.reel_meta(facts).to_dict()
def test_ac12_match_info_and_flag_override(tmp_path):
    info = tmp_path / "match.json"
    info.write_text(json.dumps({"home": "Arsenal", "away": "Chelsea", "competition": "Premier League", "score": "1-0", "kickoff": 0}))
    assert main(["meta", str(manifest(tmp_path)), "--match-info", str(info), "--home", "Hà Nội FC"]) == 0
    for e in json.loads((tmp_path / "highlights.json").read_text(encoding="utf-8")):
        body = e["title"] + " " + e["caption"]
        assert all(s in body for s in ("Hà Nội FC", "Chelsea", "Premier League")) and "Arsenal" not in json.dumps(e)
    assert "Tỉ số: 1-0" in json.loads((tmp_path / "reel.json").read_text(encoding="utf-8"))["caption"]
    info.write_text(json.dumps({"home": "Arsenal", "away": "Chelsea"}))
    assert main(["meta", str(tmp_path), "--match-info", str(info)]) == 0
    assert "phút" not in (tmp_path / "highlights.json").read_text(encoding="utf-8")
@pytest.mark.parametrize("setup,needle", [
    (lambda d: None, "highlights.json"), (lambda d: (d / "highlights.json").write_text("{oops"), "highlights.json"),
    (lambda d: manifest(d) and (d / "m.json").write_text("[1]"), "m.json"),
    (lambda d: manifest(d) and (d / "m.json").write_text("{bad"), "m.json"), (lambda d: manifest(d), "m.json")])
def test_ac13_cli_errors_exit_1_and_write_nothing(tmp_path, capsys, setup, needle):
    setup(tmp_path)
    before = (tmp_path / "highlights.json").read_bytes() if (tmp_path / "highlights.json").exists() else None
    argv = ["meta", str(tmp_path)] + (["--match-info", str(tmp_path / "m.json")] if needle == "m.json" else [])
    assert main(argv) == 1
    out, err = capsys.readouterr()
    assert out == "" and err.startswith("sportscut meta: error: ") and needle in err
    assert not (tmp_path / "captions.txt").exists() and not (tmp_path / "reel.json").exists()
    assert before is None or (tmp_path / "highlights.json").read_bytes() == before
def test_ac13_argparse_and_help(tmp_path, capsys):
    for argv in (["--kickoff", "abc"], ["--meta-backend", "gpt"], ["--help"]):
        with pytest.raises(SystemExit) as exc:
            main(["meta", str(manifest(tmp_path))] + argv)
        assert exc.value.code == (0 if argv == ["--help"] else 2)
    help_text = capsys.readouterr().out
    assert all(o in help_text for o in ("OUT_DIR", "--home", "--away", "--competition", "--kickoff", "--match-info", "--meta-backend"))
    assert not (tmp_path / "captions.txt").exists()
    assert main(["meta", str(tmp_path), "--home", "Hà Nội FC", "--away", "Hải Phòng", "--kickoff", "0"]) == 0
    assert capsys.readouterr().out.splitlines() == [str(tmp_path / n) for n in ("highlights.json", "captions.txt", "reel.json")]
def test_ac15_readme_section():
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    head = lines.index("## Xuất tiêu đề, caption, hashtag cho clip đã cắt (sportscut meta)")
    nxt = lines.index("## Theo dõi cầu thủ: đo độ chính xác (eval-player)")
    assert lines.index("### Lồng tiếng bình luận (--voiceover)") < head < nxt
    assert all(not ln.startswith("## ") for ln in lines[head + 1:nxt])
    section = "\n".join(lines[head:nxt])
    for s in ("sportscut meta", "--match-info", "--kickoff", "captions.txt", "reel.json", "highlights.json", "template fallback"):
        assert s in section
    assert "```json" not in section and "sẽ có ở task sau" not in section
