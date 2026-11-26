import ast, json, logging, subprocess, sys, tomllib, types, unicodedata
from pathlib import Path
import pytest
from sportscut import cli
from sportscut.commentary import eval_meta, llm, meta
from sportscut.commentary.facts import ClipFacts
from sportscut.commentary.meta import EVENT_LABELS, ClipMeta

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "eval_meta"
FACTS = [c.facts for c in eval_meta.load_cases(FIX / "cases.json")]
TEMPLATE = [meta.generate_meta(f) for f in FACTS]
TEXT = {n: (ROOT / "tests/fixtures/llm_meta" / f"{n}.json").read_text("utf-8") for n in ("good", "hallucinated")}
REC = {n: [ClipMeta(c["title"], c["caption"], tuple(c["hashtags"])) for c in json.loads(t)["clips"]] for n, t in TEXT.items()}
KEY, TAGS = "sk-ant-test-SECRET", ("#BongDa", "#BanThang", "#VLeague")
FULL = ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0")
HEADLINE = ("score", "format_ok", "fact_recall", "hallucination_rate", "vi_rate")
nfd = lambda s: unicodedata.normalize("NFD", s)
def Client(text=None, exc=None):
    NS, calls = types.SimpleNamespace, []
    def create(**kwargs):
        if calls.append(kwargs) or exc:
            raise exc
        return NS(content=[NS(type="text", text=text)])
    return NS(calls=calls, exc=exc, messages=NS(create=create))
def fake_anthropic(monkeypatch, text=None, exc=None, key=KEY):
    mod = types.ModuleType("anthropic")
    mod.made, mod.client = [], Client(text, exc)
    mod.Anthropic = lambda **kw: mod.made.append(kw) or mod.client
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    return mod
def warns(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "sportscut.commentary.llm" and r.levelno >= logging.WARNING]
def test_ac1_extra_and_no_top_level_anthropic_import():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert project["optional-dependencies"]["llm"] == ["anthropic>=0.40"] and project["dependencies"] == ["numpy>=1.26"]
    for path in (ROOT / "sportscut").rglob("*.py"):
        top = [s for s in ast.parse(path.read_text("utf-8")).body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        for node in (n for s in top for n in ast.walk(s) if isinstance(n, (ast.Import, ast.ImportFrom))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            assert all(n.split(".")[0] != "anthropic" for n in names), path
    code = "import sys; sys.modules['anthropic'] = None; import sportscut.cli, sportscut.commentary.llm"
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True)
@pytest.mark.parametrize("facts,title,caption,tags,expected", [
    (FULL, "Bàn thắng đẹp mắt", "Bàn thắng ở phút 24 trong trận Hà Nội FC gặp Hải Phòng tại V.League 2026. Tỉ số 1-0.", TAGS, ["number 24 not in facts", "missing phút 23"]),
    (ClipFacts("red_card", 88), "Thẻ đỏ ở phút 88", "Thẻ đỏ dành cho Sergio Ramos ở phút 88. Cùng xem lại tình huống này!", TAGS, ["name Sergio not in facts", "name Ramos not in facts"]),
    (ClipFacts("other"), "Great moment of the match", "What a moment. Watch it again!", TAGS, ["not vietnamese"]),
    (ClipFacts("save", 67, "Arsenal", "Chelsea", None, "2-1"), "Một tình huống đáng xem", "Cùng xem lại trận đấu hay!", TAGS, ["missing Pha cứu thua", "missing Arsenal", "missing Chelsea", "missing phút 67", "missing 2-1"]),
    (FULL, TEMPLATE[0].title, TEMPLATE[0].caption, ("#BongDa", "#BanThang"), ["hashtag count 2"]),
    (ClipFacts("red_card", 88), "Thẻ đỏ phút 88. Xem lại! Hay? Tuyệt: Đẹp | Mạnh", "Thẻ đỏ ở phút 88. Cùng xem lại!", TAGS, []),
    (ClipFacts(**{k: nfd(v) if k in ("home", "away", "competition") else v for k, v in vars(FULL).items()}), nfd(TEMPLATE[0].title), nfd(TEMPLATE[0].caption), TEMPLATE[0].hashtags, []),
])
def test_ac3_validate_meta_problems(facts, title, caption, tags, expected):
    problems = eval_meta.validate_meta(facts, ClipMeta(title, caption, tags))
    assert set(expected) <= set(problems) and (expected or problems == []), problems
def test_ac2_template_and_good_fixture_are_valid():
    for facts, template, good in zip(FACTS, TEMPLATE, REC["good"]):
        assert eval_meta.validate_meta(facts, template) == [] == eval_meta.validate_meta(facts, good)
        assert eval_meta.validate_meta(facts, ClipMeta(nfd(good.title), nfd(good.caption), good.hashtags)) == []
def test_ac5_one_request_shape(monkeypatch):
    for value, model in ((None, "claude-haiku-5-5"), ("   ", "claude-haiku-5-5"), (" claude-sonnet-5-5 ", "claude-sonnet-5-5")):
        monkeypatch.delenv("SPORTSCUT_LLM_MODEL", raising=False) if value is None else monkeypatch.setenv("SPORTSCUT_LLM_MODEL", value)
        llm.generate_metas_llm(FACTS, client=(client := Client(TEXT["good"])))
        [kw] = client.calls
        assert set(kw) == {"model", "max_tokens", "system", "messages"} and kw["model"] == model
    assert kw["max_tokens"] == 4096 and kw["system"] == llm.SYSTEM_PROMPT and all(s in llm.SYSTEM_PROMPT for s in ("JSON", "phút", "#[A-Za-z0-9_]+"))
    assert [m["role"] for m in kw["messages"]] == ["user"]  # the clips below carry ids 0-7 in order
    assert json.loads(kw["messages"][0]["content"])["clips"] == [{"id": i, "label": EVENT_LABELS[f.event], **{k: v for k, v in vars(f).items() if v is not None}} for i, f in enumerate(FACTS)]
    assert llm.generate_metas_llm([], client=(empty := Client(TEXT["good"]))) == [] and empty.calls == []
def test_ac7_hallucinated_clips_rejected(caplog):
    out = llm.generate_metas_llm(FACTS, client=Client(TEXT["hallucinated"]))
    assert out == [TEMPLATE[i] if i in (0, 2, 4, 7) else REC["hallucinated"][i] for i in range(8)]
    assert len(w := warns(caplog)) == 4 and all("template fallback" in m for m in w)
    for (i, problem), m in zip([(0, "number 24 not in facts"), (2, "name Ramos not in facts"), (4, "not vietnamese"), (7, "hashtag count 2")], w):
        assert f"clip {i}" in m and problem in m
@pytest.mark.parametrize("client", [Client(exc=ConnectionError("boom sk-ant-secret")), Client("not json"), Client('{"other": []}'), Client('{"clips": {}}')])
def test_ac8_whole_response_failure(client, caplog):
    assert llm.generate_metas_llm(FACTS, client=client) == TEMPLATE
    [w] = warns(caplog)
    assert "template fallback for all 8 clips" in w and "boom" not in w and "sk-ant-secret" not in w and (client.exc is None or "ConnectionError" in w)
@pytest.mark.parametrize("bad", [None, {"id": "1"}, {"id": True}, {"id": 99}, {"id": 0}, {"title": 5}, {"hashtags": "#BongDa"}])
def test_ac8_per_clip_defect_falls_back_that_clip(bad, caplog):
    clips = json.loads(TEXT["good"])["clips"]  # {"id": 0} on clip 1 is a duplicate: the first wins, slot 1 is missing
    clips = [c for c in clips if c["id"] != 1] if bad is None else [{**c, **bad} if c["id"] == 1 else c for c in clips]
    out = llm.generate_metas_llm(FACTS, client=Client(json.dumps({"clips": clips}, ensure_ascii=False)))
    assert out == [TEMPLATE[1] if i == 1 else REC["good"][i] for i in range(8)]
    assert warns(caplog) == ["clip 1: missing or malformed in LLM response; template fallback"]
def test_ac9_key_and_package(monkeypatch, caplog):
    for value in (None, "  "):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False) if value is None else monkeypatch.setenv("ANTHROPIC_API_KEY", value)
        assert llm.generate_metas_llm(FACTS) == TEMPLATE
    assert len(warns(caplog)) == 2 and all("ANTHROPIC_API_KEY is not set" in w for w in warns(caplog))
    monkeypatch.setenv("ANTHROPIC_API_KEY", KEY) or monkeypatch.setitem(sys.modules, "anthropic", None)
    assert llm.generate_metas_llm(FACTS) == TEMPLATE and "pip install 'sportscut[llm]'" in warns(caplog)[-1]
    mod = fake_anthropic(monkeypatch, TEXT["good"], key=" sk-ant-test ")
    assert llm.generate_metas_llm(FACTS) == REC["good"] and mod.made == [{"api_key": "sk-ant-test", "timeout": 60.0}]
def test_ac10_key_never_leaks(monkeypatch, tmp_path, capsys, caplog):
    monkeypatch.chdir(tmp_path) or caplog.set_level(logging.DEBUG)  # any level counts as logging the key
    fake_anthropic(monkeypatch, exc=RuntimeError(f"bad key {KEY}"))
    assert cli.main(["eval-meta", str(FIX), "--json", "--meta-backend", "llm"]) == 0
    files = [p.read_bytes().decode("utf-8", "replace") for p in tmp_path.rglob("*") if p.is_file()]
    assert all(KEY not in s for s in (*capsys.readouterr(), caplog.text, *files)) and "RuntimeError" in caplog.text
    mod = fake_anthropic(monkeypatch, TEXT["good"])
    assert llm.generate_metas_llm(FACTS) == REC["good"] and KEY not in json.dumps(mod.client.calls[0], ensure_ascii=False)
@pytest.mark.parametrize("name", ["good", "hallucinated"])
def test_ac11_evaluate_meta_dir_llm(name, monkeypatch):
    fake_anthropic(monkeypatch, TEXT[name])
    report = eval_meta.evaluate_meta_dir(FIX, backend="llm")
    assert [report[k] for k in HEADLINE] == [1.0, 1.0, 1.0, 0.0, 1.0]
    expected = [m.title for m in REC["good"]] if name == "good" else ["Bàn thắng: Hà Nội FC vs Hải Phòng, phút 23"]
    assert [c["title"] for c in report["per_case"]][: len(expected)] == expected
    with pytest.raises(ValueError, match="unknown backend: gpt"):
        eval_meta.evaluate_meta_dir(FIX, backend="gpt")
def test_ac12_cli_flag(monkeypatch, capsys):
    pytest.raises(SystemExit, cli.main, ["eval-meta", "--help"])
    assert "--meta-backend" in capsys.readouterr().out
    run = lambda *extra: (cli.main(["eval-meta", str(FIX), "--json", *extra]), capsys.readouterr().out)
    assert run() == run("--meta-backend", "template") and run()[0] == 0
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code, out = run("--meta-backend", "llm")
    assert code == 0 and json.loads(out)["score"] == 1.0
    with pytest.raises(SystemExit) as exc:
        cli.main(["eval-meta", str(FIX), "--meta-backend", "gpt"])
    assert exc.value.code == 2
@pytest.mark.parametrize("wrap", ["{}", "```json\n{}\n```", "```\n{}\n```"])
def test_ac6_good_fixture_accepted_even_fenced(wrap, caplog):
    assert llm.generate_metas_llm(FACTS, client=Client(wrap.replace("{}", TEXT["good"]))) == REC["good"] and warns(caplog) == []
    assert all(isinstance(m.hashtags, tuple) for m in REC["good"])
def test_ac4_template_default_unchanged(capsys):
    with pytest.raises(ValueError, match="unknown backend: llm"):
        meta.generate_meta(ClipFacts("goal"), backend="llm")
    assert cli.main(["eval-meta", str(FIX), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert [report[k] for k in HEADLINE] == [1.0, 1.0, 1.0, 0.0, 1.0]
def test_ac14_readme_llm_section():
    section = (ROOT / "README.md").read_text("utf-8").split("### Backend LLM (tùy chọn)", 1)[1].split("\n## ", 1)[0]
    needed = ("pip install 'sportscut[llm]'", "ANTHROPIC_API_KEY", "SPORTSCUT_LLM_MODEL", "claude-haiku-5-5", "python -m sportscut eval-meta tests/fixtures/eval_meta --json --meta-backend llm", "template fallback")
    assert all(s in section for s in needed)
