import contextlib, hashlib, inspect, io, json, re, shutil  # noqa: E401  (T-048 Tester acceptance tests)
from pathlib import Path
import pytest
from sportscut import cli, pipeline
from sportscut.commentary import publish, script
from sportscut.commentary.facts import facts_from_entry

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ["--home", "Việt Nam", "--away", "Thái Lan", "--kickoff", "0"]
MATCH = {"home": "Việt Nam", "away": "Thái Lan", "kickoff": 0.0}
META_FILES = ("highlights.json", publish.CAPTIONS_NAME, publish.REEL_NAME)
def call(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()  # noqa: E731
manifest = lambda out: json.loads((out / "highlights.json").read_text(encoding="utf-8"))  # noqa: E731
def scripts(out):
    return [(e, json.loads((out / e["script_file"]).read_text(encoding="utf-8"))) for e in manifest(out)]
@pytest.fixture(scope="module")
def runs(burst_video, tmp_path_factory):
    base = tmp_path_factory.mktemp("t048")
    extra = {"plain": [], "meta": ["--meta", *FLAGS], "vo": ["--voiceover"], "vo_match": ["--voiceover", *FLAGS]}
    result = {}
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli.voiceover, "default_synthesizer", lambda: None)
        for name, args in extra.items():
            out = base / name
            result[name] = (out, *call(["cut", str(burst_video), "--out", str(out), "--top", "1", *args]))
            assert result[name][1] == 0, result[name][3]
    return result
def test_ac1_help_lists_options():
    for cmd, opts in (("cut", ["--meta", "--meta-backend"]), ("meta", ["OUT_DIR", "--meta-backend"])):
        code, out, _ = call([cmd, "--help"])
        assert code == 0 and all(o in out for o in opts + ["--home", "--away", "--competition", "--kickoff", "--match-info"])
    text = " ".join(call(["meta", "--help"])[1].split())
    assert "kickoff time in seconds into the video; the minute needs it" in text
    assert "match.json with home, away, competition, score, kickoff; flags win" in text
@pytest.mark.parametrize("bad", [{"kickoff": -1}, {"kickoff": float("nan")}, {"venue": "X"}, {"home": "h" * 41}, ["home"]])
def test_ac2_bad_match_before_ffmpeg(tmp_path, monkeypatch, bad):
    assert [(p.name, p.default) for p in inspect.signature(pipeline.run).parameters.values()][-1] == ("match", None)
    monkeypatch.setattr(pipeline, "require_ffmpeg", lambda: pytest.fail("require_ffmpeg called"))
    with pytest.raises(pipeline.PipelineError):
        pipeline.run(tmp_path / "x.mp4", tmp_path / "out", match=bad)
    assert not (tmp_path / "out").exists()
def test_ac3_meta_end_to_end_equals_cut_then_meta(runs, tmp_path):
    out, code, stdout, _ = runs["meta"]
    entries = manifest(out)
    assert entries and all(list(e)[-3:] == ["title", "caption", "hashtags"] and "#VietNam" in e["hashtags"] for e in entries)
    assert "#VietNam" in (out / publish.CAPTIONS_NAME).read_text(encoding="utf-8")
    assert json.loads((out / publish.REEL_NAME).read_text(encoding="utf-8"))["title"] == "Tổng hợp highlight: Việt Nam vs Thái Lan"
    assert stdout.splitlines() == [str(out / e["file"]) for e in entries] + [str(out / publish.CAPTIONS_NAME), str(out / publish.REEL_NAME)]
    copy = shutil.copytree(runs["plain"][0], tmp_path / "copy")
    assert call(["meta", str(copy), *FLAGS])[0] == 0
    assert all((copy / name).read_bytes() == (out / name).read_bytes() for name in META_FILES)
def test_ac4_clips_and_manifest_unchanged(runs):
    plain, meta = runs["plain"][0], runs["meta"][0]
    clips = sorted(p.name for p in plain.glob("clip_*.mp4"))
    assert clips and clips == sorted(p.name for p in meta.glob("clip_*.mp4"))
    assert all(sha(plain / c) == sha(meta / c) for c in clips)
    assert [{k: v for k, v in e.items() if k not in publish.META_KEYS} for e in manifest(meta)] == manifest(plain)
    assert not (plain / publish.CAPTIONS_NAME).exists() and not (plain / publish.REEL_NAME).exists()
    assert (plain / "highlights.json").read_text(encoding="utf-8") == json.dumps(manifest(plain), indent=2) + "\n"
def test_ac5_voiceover_scripts_with_match(runs):
    out, vo = runs["vo_match"][0], runs["vo"][0]
    for entry, record in scripts(out):
        facts = facts_from_entry(entry, MATCH)
        lines = [(l["start"], l["text"]) for l in record["lines"]]
        clip_len = entry["end"] - entry["start"]
        assert script.validate_script(facts, lines, clip_len) == [] and script.script_fits(lines, clip_len)
        joined = " ".join(t for _, t in lines)
        assert "Việt Nam" in joined and "Thái Lan" in joined and f"Phút {facts.minute}" in joined
    assert (out / "highlights.json").read_bytes() == (vo / "highlights.json").read_bytes()
    assert all(sha(out / p.name) == sha(p) for p in vo.glob("clip_*.mp4"))
def test_ac6_voiceover_without_match_unchanged(runs):
    for entry, record in scripts(runs["vo"][0]):
        texts = [l["text"] for l in record["lines"]]
        assert not any(w in t for t in texts for w in ("Phút", "Việt Nam", "Thái Lan"))
        clip_len = entry["end"] - entry["start"]
        lines = script.write_script(facts_from_entry(entry), clip_len, "template", peak=record["peak"])
        want = {"clip": entry["file"], "clip_len": clip_len, "peak": record["peak"], "backend": "template",
                "lines": [{"start": s, "end": s + script.speech_seconds(t), "text": t} for s, t in lines]}
        assert (runs["vo"][0] / entry["script_file"]).read_text(encoding="utf-8") == json.dumps(want, ensure_ascii=False, indent=2) + "\n"
def test_focus3_score_in_match_info(burst_video, tmp_path, monkeypatch):
    (info := tmp_path / "m.json").write_text(json.dumps({"home": "Việt Nam", "away": "Thái Lan", "score": "2-1", "kickoff": 0}), encoding="utf-8")
    monkeypatch.setattr(cli.voiceover, "default_synthesizer", lambda: None)
    out = tmp_path / "out"
    assert call(["cut", str(burst_video), "--out", str(out), "--top", "1", "--voiceover", "--match-info", str(info)])[0] == 0
    for entry, record in scripts(out):
        lines = [(l["start"], l["text"]) for l in record["lines"]]
        facts = facts_from_entry(entry, json.loads(info.read_text(encoding="utf-8")))
        assert script.validate_script(facts, lines, entry["end"] - entry["start"]) == []
def test_focus5_meta_twice_same_bytes(runs, burst_video):
    before = {n: ((out := runs["meta"][0]) / n).read_bytes() for n in META_FILES}
    assert call(["cut", str(burst_video), "--out", str(out), "--top", "1", "--meta", *FLAGS])[0] == 0
    assert {n: (out / n).read_bytes() for n in META_FILES} == before
@pytest.mark.parametrize("args, msg", [
    (["--home", "X"], "need --meta or --voiceover"), (["--kickoff", "0"], "need --meta or --voiceover"),
    (["--match-info", "m.json"], "need --meta or --voiceover"), (["--competition", "C"], "need --meta or --voiceover"),
    (["--meta-backend", "llm"], "--meta-backend needs --meta"), (["--meta", "--meta-backend", "foo"], "invalid choice"),
])
def test_ac8_usage_errors(tmp_path, monkeypatch, args, msg):
    monkeypatch.setattr(cli, "run", lambda *a, **k: pytest.fail("run called"))
    code, out, err = call(["cut", str(tmp_path / "v.mp4"), "--out", str(tmp_path / "o"), *args])
    assert code == 2 and msg in err and out == ""
def test_ac9_runtime_errors(tmp_path, monkeypatch, burst_video):
    ran = []
    monkeypatch.setattr(cli, "run", lambda *a, **k: ran.append(k) or [{"file": "clip_01.mp4"}])
    (lst := tmp_path / "list.json").write_text("[1]", encoding="utf-8")
    for path, start in ((tmp_path / "missing.json", "sportscut: error: cannot read"), (lst, "sportscut: error: ")):
        code, out, err = call(["cut", "v.mp4", "--out", str(tmp_path / "o"), "--meta", "--match-info", str(path)])
        assert (code, out, ran) == (1, "", []) and err.startswith(start)
    assert err.rstrip().endswith("expected a JSON object")
    for exc in (ValueError("boom"), OSError("boom")):
        monkeypatch.setattr(cli.publish, "write_meta", lambda *a, **k: (_ for _ in ()).throw(exc))
        assert call(["cut", "v.mp4", "--out", str(tmp_path / "o"), "--meta"]) == (1, "", "sportscut: error: boom\n")
    monkeypatch.undo()
    out_dir = tmp_path / "real"
    code, out, err = call(["cut", str(burst_video), "--out", str(out_dir), "--top", "1", "--meta", "--kickoff", "-1"])
    assert (code, out) == (1, "") and "sportscut: error: kickoff must be non-negative" in err
    assert not out_dir.exists() or not list(out_dir.glob("clip_*"))
def test_ac7_ac10_forwarding_and_no_clips(tmp_path, monkeypatch):
    ran, calls = [], []
    monkeypatch.setattr(cli, "run", lambda *a, **k: ran.append(k["match"]) or [])
    monkeypatch.setattr(cli.publish, "write_meta", lambda *a, **k: pytest.fail("write_meta called"))
    assert call(["cut", "v.mp4", "--out", str(tmp_path), "--meta", *FLAGS]) == (0, "", "sportscut: notice: no clips were cut; --meta wrote nothing\n")
    monkeypatch.setattr(cli, "run", lambda *a, **k: ran.append(k["match"]) or [{"file": "c.mp4"}])
    monkeypatch.setattr(cli.publish, "write_meta", lambda *a, **k: calls.append((a, k, list(ran))))
    for extra in ([], ["--meta", "--meta-backend", "llm", "--kickoff", "5"], ["--meta", "--away", "B"]):
        assert call(["cut", "v.mp4", "--out", str(tmp_path), *extra])[0] == 0
    assert ran == [MATCH, None, {"kickoff": 5.0}, {"away": "B"}]
    assert calls == [((str(tmp_path), {"kickoff": 5.0}), {"backend": "llm"}, ran[:3]), ((str(tmp_path), {"away": "B"}), {"backend": "template"}, ran)]
def test_ac11_ac12_docs():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    sec = readme.split("## Xuất tiêu đề, caption, hashtag cho clip đã cắt (sportscut meta)", 1)[1]
    sub = sec.split("## Theo dõi cầu thủ: đo độ chính xác (eval-player)", 1)[0].split("### Tạo luôn khi cắt (cut --meta)", 1)[1]
    assert all(w in sub for w in ("cut", "--meta", "--voiceover", "--kickoff", "Việt Nam"))
    assert not re.search(r"^## ", sub, re.M) and "```json" not in sub and "sẽ có ở task sau" not in sub
    specs = ROOT / "docs/superpowers/specs"
    for prefix, needle in (("2026-11-23-t-004", "match=None"), ("2026-11-23-t-026", "facts_from_entry(entry, match)"),
                           ("2026-11-27-t-047", "cut --meta")):
        text = next(specs.glob(f"{prefix}-*-design.md")).read_text(encoding="utf-8")
        tail = text.split("## Updated by T-048", 1)
        assert len(tail) == 2 and needle in tail[1] and "\n## " not in tail[1]
    index = (ROOT / "docs/superpowers/INDEX.md").read_text(encoding="utf-8").splitlines()
    assert sum("| T-048 |" in line for line in index) == 1 and "| T-048 |" in index[-1]
