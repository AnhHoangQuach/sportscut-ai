import json, logging, sys, unicodedata
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from sportscut.cli import main
from sportscut.commentary import eval_meta, llm, meta
from sportscut.commentary.facts import ClipFacts
from sportscut.commentary.meta import ClipMeta
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/eval_meta"
CASES = eval_meta.load_cases(FIXTURE / "cases.json")
FACTS = [case.facts for case in CASES]
TEMPLATE = [meta.generate_meta(f) for f in FACTS]
TEXT = {n: (ROOT / f"tests/fixtures/llm_meta/{n}.json").read_text(encoding="utf-8") for n in ("good", "hallucinated")}
GOOD = [ClipMeta(c["title"], c["caption"], tuple(c["hashtags"])) for c in json.loads(TEXT["good"])["clips"]]
TAGS, GOAL = ("#BongDa", "#BanThang", "#HaNoiFC"), ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0")
NFD = lambda s: unicodedata.normalize("NFD", s)  # noqa: E731

def fake_client(text=None, exc=None):
    def create(**kwargs):
        if calls.append(kwargs) or exc:
            raise exc
        return NS(content=[NS(type="text", text=text)])
    calls = []
    return NS(calls=calls, messages=NS(create=create))

def fake_anthropic(monkeypatch, text=None, exc=None):
    calls = []
    monkeypatch.setitem(sys.modules, "anthropic", NS(Anthropic=lambda **kw: calls.append(kw) or fake_client(text, exc)))
    return calls

def run_llm(caplog, text=None, exc=None):
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="sportscut.commentary.llm"):
        out = llm.generate_metas_llm(FACTS, client=fake_client(text, exc))
    return out, [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]

def test_validate_meta_template_and_good_fixture_pass():
    for case, template, good in zip(CASES, TEMPLATE, GOOD):
        assert eval_meta.validate_meta(case.facts, template) == eval_meta.validate_meta(case.facts, good) == []
        assert eval_meta.score_case(case, good)["score"] == 1.0

@pytest.mark.parametrize("facts,title,caption,tags,want", [
    (GOAL, "Bàn thắng: Hà Nội FC vs Hải Phòng", "Bàn thắng ở phút 24 tại V.League 2026. Tỉ số: 1-0.", TAGS, ["number 24 not in facts", "missing phút 23"]),
    (ClipFacts("red_card", 88), "Thẻ đỏ ở phút 88 rồi", "Thẻ đỏ dành cho Sergio Ramos ở phút 88. Cùng xem lại!", TAGS, ["name Sergio not in facts", "name Ramos not in facts"]),
    (GOAL, "Tuyệt vời: Bàn thắng phút 23 | Hà Nội FC", "Hải Phòng thua! Đẹp quá? Ừ. V.League 2026 tỉ số 1-0", TAGS, []),
    (ClipFacts("other"), "Great moment of the match", "What a moment. Watch it again!", TAGS,
     ["missing Khoảnh khắc đáng chú ý", "not vietnamese"]),
    (ClipFacts("save", 67, "Arsenal", score="2-1"), "Cứu thua đẹp mắt quá", "Một pha bóng hay.", TAGS,
     ["missing Pha cứu thua", "missing Arsenal", "missing phút 67", "missing 2-1"]),
    (ClipFacts("red_card", 88), "Thẻ đỏ ở phút 88 rồi", "Thẻ đỏ ở phút 88.", TAGS[:2], ["hashtag count 2"]),
    (ClipFacts("goal", 9, "Hà Nội FC"), NFD("Bàn thắng của Hà Nội FC"), NFD("Bàn thắng ở phút 9 của Hà Nội FC."), TAGS, []),
])
def test_validate_meta_problems(facts, title, caption, tags, want):
    assert eval_meta.validate_meta(facts, ClipMeta(title, caption, tags)) == want

@pytest.mark.parametrize("env,model", [("  ", "claude-haiku-5-5"), (" claude-sonnet-5-5 ", "claude-sonnet-5-5")])
def test_build_request_shape_and_model_env(monkeypatch, env, model):
    monkeypatch.setenv("SPORTSCUT_LLM_MODEL", env)
    client = fake_client(TEXT["good"])
    llm.generate_metas_llm(FACTS, client=client)
    assert llm.generate_metas_llm([], client=client) == []
    (kwargs,) = client.calls
    assert set(kwargs) == {"model", "max_tokens", "system", "messages"}
    assert (kwargs["model"], kwargs["max_tokens"], kwargs["system"]) == (model, 4096, llm.SYSTEM_PROMPT)
    assert all(s in llm.SYSTEM_PROMPT for s in ("JSON", "phút", "#[A-Za-z0-9_]+"))
    ((role, message),) = [(m["role"], m["content"]) for m in kwargs["messages"]]
    want = [{"id": i, "label": meta.EVENT_LABELS[f.event], **{k: v for k, v in vars(f).items() if v is not None}} for i, f in enumerate(FACTS)]
    assert role == "user" and json.loads(message)["clips"] == want
    monkeypatch.delenv("SPORTSCUT_LLM_MODEL")
    assert llm.model_name() == "claude-haiku-5-5"

def test_parse_response():
    for wrapped in (TEXT["good"], f"  ```json\n{TEXT['good']}\n```  ", f"```{TEXT['good']}```"):
        assert llm.parse_response(wrapped, 8) == GOOD
    assert [llm.parse_response(bad, 8) for bad in ("not json", "[1]", '{"clips": {}}', "{}")] == [None] * 4
    ok = {"title": "t", "caption": "c", "hashtags": ["#a"]}
    rows = [{"id": "0", **ok}, {"id": True, **ok}, {"id": 5, **ok}, {"id": 1, **ok, "extra": 1}, {"id": 1, **ok, "title": "dup"},
            {"id": 2, **ok, "title": 3}, {"id": 3, **ok, "hashtags": "#a"}, {"id": 4, **ok, "title": NFD("Bàn")}, 7]
    assert llm.parse_response(json.dumps({"clips": rows}), 5) == [None, ClipMeta("t", "c", ("#a",)), None, None, ClipMeta("Bàn", "c", ("#a",))]

def test_generate_good_and_hallucinated(caplog):
    assert run_llm(caplog, TEXT["good"]) == run_llm(caplog, f"```json\n{TEXT['good']}\n```") == (GOOD, [])
    out, warns = run_llm(caplog, TEXT["hallucinated"])
    bad = {0: "number 24 not in facts", 2: "name Ramos not in facts", 4: "not vietnamese", 7: "hashtag count 2"}
    assert out == [TEMPLATE[i] if i in bad else GOOD[i] for i in range(8)] and len(warns) == 4
    for (i, problem), warn in zip(bad.items(), warns):
        assert f"clip {i}:" in warn and "template fallback" in warn and problem in warn

def test_generate_failures_and_no_key(caplog, monkeypatch):
    for kwargs in ({"exc": ConnectionError("boom sk-ant-secret")}, {"text": "not json"}, {"text": '{"x": 1}'}):
        out, (warn,) = run_llm(caplog, **kwargs)
        assert out == TEMPLATE and "template fallback for all 8 clips" in warn and "sk-ant" not in warn
    assert "ConnectionError" in run_llm(caplog, exc=ConnectionError("x"))[1][0]
    assert run_llm(caplog, json.dumps({"clips": json.loads(TEXT["good"])["clips"][1:]})) == (
        TEMPLATE[:1] + GOOD[1:], ["clip 0: missing or malformed in LLM response; template fallback"])
    for key in ("", "  "):
        monkeypatch.setenv("ANTHROPIC_API_KEY", key)
        assert llm.generate_metas_llm(FACTS) == TEMPLATE and "ANTHROPIC_API_KEY is not set" in caplog.text
    monkeypatch.setenv("ANTHROPIC_API_KEY", " sk-ant-test ")
    monkeypatch.setitem(sys.modules, "anthropic", None)
    assert llm.generate_metas_llm(FACTS) == TEMPLATE and "pip install 'sportscut[llm]'" in caplog.text
    calls = fake_anthropic(monkeypatch, TEXT["good"])
    assert llm.generate_metas_llm(FACTS) == GOOD and calls == [{"api_key": "sk-ant-test", "timeout": 60.0}]
    monkeypatch.setitem(sys.modules, "anthropic", NS(Anthropic=lambda **kw: 1 / 0))  # the client constructor raises
    assert llm.generate_metas_llm(FACTS) == TEMPLATE and "LLM request failed (ZeroDivisionError)" in caplog.text

def test_eval_meta_llm_backend_and_cli(monkeypatch, capsys, caplog):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    headline = {"score": 1.0, "format_ok": 1.0, "fact_recall": 1.0, "hallucination_rate": 0.0, "vi_rate": 1.0}
    for name in ("good", "hallucinated"):
        fake_anthropic(monkeypatch, TEXT[name])
        assert {k: v for k, v in eval_meta.evaluate_meta_dir(FIXTURE, backend="llm").items() if k in headline} == headline
    with pytest.raises(ValueError, match="unknown backend: gpt"):
        eval_meta.evaluate_meta_dir("missing", backend="gpt")
    run = lambda *x: (main(["eval-meta", str(FIXTURE), "--json", *x]), *capsys.readouterr())  # noqa: E731
    assert (base := run()) == run("--meta-backend", "template") and base[0] == 0
    fake_anthropic(monkeypatch, exc=RuntimeError("sk-ant-test"))
    code, out, err = run("--meta-backend", "llm")
    assert code == 0 and json.loads(out)["score"] == 1.0 and "template fallback" in caplog.text
    assert all("sk-ant-test" not in text for text in (out, err, caplog.text))
    with pytest.raises(SystemExit, match="2"):
        main(["eval-meta", str(FIXTURE), "--meta-backend", "gpt"])

def test_readme_and_pyproject_llm_extra():
    section = (ROOT / "README.md").read_text(encoding="utf-8").split("### Backend LLM (tùy chọn)", 1)[1].split("\n## ")[0]
    for needle in ("pip install 'sportscut[llm]'", "ANTHROPIC_API_KEY", "SPORTSCUT_LLM_MODEL", "claude-haiku-5-5",
                   "template fallback", "python -m sportscut eval-meta tests/fixtures/eval_meta --json --meta-backend llm"):
        assert needle in section
    assert 'llm = ["anthropic>=0.40"]' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
