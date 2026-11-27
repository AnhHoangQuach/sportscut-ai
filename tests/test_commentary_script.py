import json, logging, math, sys, unicodedata
from pathlib import Path
from types import SimpleNamespace as NS
import numpy as np
import pytest
from sportscut.commentary import eval_meta, script
from sportscut.commentary.facts import ClipFacts
ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/eval_meta"
CASES = eval_meta.load_cases(FIXTURE / "cases.json")
SR = 16_000
GOAL = ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0")
KEYS = {"goal": "bàn thắng", "save": "cứu thua", "red_card": "thẻ đỏ", "controversy": "tranh cãi", "other": "khoảnh khắc"}
NFC = lambda s: unicodedata.normalize("NFC", s).casefold()  # noqa: E731

def fake_client(text=None, exc=None):
    def create(**kwargs):
        if calls.append(kwargs) or exc:
            raise exc
        return NS(content=[NS(type="text", text=text)])
    calls = []
    return NS(calls=calls, messages=NS(create=create))

# --- syllables / speech_seconds (AC2)

@pytest.mark.parametrize("text,want", [
    ("Phút 23, Hà Nội FC.", 6), ("Vào! Bàn thắng!", 3), ("Tỉ số 1-0.", 4), ("", 0), ("phút 120", 4),
])
def test_syllables_counts_letter_runs_and_digits(text, want):
    assert script.syllables(text) == want

def test_syllables_nfd_equals_nfc():
    text = "Thép Xanh Nam Định gặp Hoàng Anh Gia Lai"
    assert script.syllables(unicodedata.normalize("NFD", text)) == script.syllables(text) == 9

def test_speech_seconds_is_syllables_over_rate():
    assert script.speech_seconds("Phút 23, Hà Nội FC.") == pytest.approx(6 / 3.5)

# --- audio_peak (AC5)

def _seconds(levels):
    return np.concatenate([np.full(SR, level, dtype=np.float32) for level in levels])

def test_audio_peak_loudest_second_centre():
    assert script.audio_peak(_seconds([0.1, 0.1, 0.2, 0.9, 0.1]), 5.0) == 3.5

def test_audio_peak_under_one_second_is_none():
    assert script.audio_peak(np.ones(SR - 1, dtype=np.float32), 5.0) is None
    assert script.audio_peak(_seconds([0.5, 0.9]), 0.9) is None

def test_audio_peak_ignores_seconds_past_clip_len():
    assert script.audio_peak(_seconds([0.1, 0.5, 0.2, 0.9]), 3.7) == 1.5

def test_audio_peak_ties_take_first():
    assert script.audio_peak(_seconds([0.1, 0.7, 0.3, -0.7]), 4.0) == 1.5

# --- fit_problems / script_fits (AC2)

FITS = [(0.25, "Phút 23."), (1.5, "Vào! Bàn thắng!"), (3.0, "Tỉ số 1-0.")]

def test_script_fits_hand_made():
    assert script.fit_problems(FITS, 10.0) == []
    assert script.script_fits(FITS, 10.0)

@pytest.mark.parametrize("lines,clip_len,want", [
    ([(9.0, "Vào! Bàn thắng!")], 9.5, ["line 1 overruns the clip"]),
    ([(0.1, "Vào!")], 10.0, ["line 1 starts before the window"]),
    ([(float("nan"), "Vào!")], 10.0, ["line 1 starts before the window"]),
    ([(1.0, "Vào! Bàn thắng!"), (1.5, "Tỉ số.")], 10.0, ["line 2 overlaps line 1"]),
    ([(5.0, "Vào!"), (1.0, "Tỉ số.")], 10.0, ["line 2 overlaps line 1"]),
    ([], 10.0, ["line count 0"]),
    ([(0.5, "a"), (1.0, "b"), (1.5, "c"), (2.0, "d")], 10.0, ["line count 4"]),
])
def test_fit_problems_flags(lines, clip_len, want):
    assert script.fit_problems(lines, clip_len) == want
    assert not script.script_fits(lines, clip_len)

def test_fit_problems_boundaries_within_eps():
    d = script.speech_seconds("Vào! Bàn thắng!")
    assert script.script_fits([(0.25, "Vào! Bàn thắng!"), (0.25 + d, "Tỉ số.")], 0.25 + d + 2 / 3.5 + 0.25)

# --- validate_script (AC1, AC7)

@pytest.mark.parametrize("lines,want", [
    ([(1.0, "Vào! Bàn thắng phút 24!")], ["number 24 not in facts"]),
    ([(1.0, "Bàn thắng của Nguyễn Văn Quyết!")], ["name Nguyễn not in facts", "name Văn not in facts", "name Quyết not in facts"]),
    ([(1.0, "What a goal by them!")], ["not vietnamese"]),
    ([(1.0, "Vào! Bàn thắng!"), (5.0, "")], ["line 2 text"]),
    ([(1.0, " Vào! Bàn thắng!")], ["line 1 text"]),
    ([(0.25, "à " * 100 + "a")], ["line 1 text"]),
    ([], ["line count 0", "not vietnamese"]),
])
def test_validate_script_problems(lines, want):
    assert script.validate_script(GOAL, lines, 60.0) == want

def test_validate_script_accepts_facts():
    lines = [(0.25, "Phút 23, Hà Nội FC gặp Hải Phòng."), (3.0, "Vào! Bàn thắng!"), (4.5, "Tỉ số 1-0.")]
    assert script.validate_script(GOAL, lines, 10.0) == []

# --- template write_script (AC1, AC3, AC4, AC6)

def _check_template(facts, clip_len, peak):
    lines = script.write_script(facts, clip_len, peak=peak)
    assert 1 <= len(lines) <= 3
    assert all(isinstance(s, float) and isinstance(t, str) for s, t in lines)
    assert script.validate_script(facts, lines, clip_len) == []
    key = KEYS[facts.event]
    idx = [i for i, (_, t) in enumerate(lines) if key in NFC(t)]
    assert idx, lines
    moment = idx[0]
    assert all(key not in NFC(t) for _, t in lines[:moment])
    used = clip_len * 8 / 12 if peak is None else peak
    start, text = lines[moment]
    d = script.speech_seconds(text)
    if used + d <= clip_len - 0.25 and used >= 0.25:
        assert start == used
    elif used + d > clip_len - 0.25:
        assert start == pytest.approx(clip_len - 0.25 - d)
    return lines

@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
@pytest.mark.parametrize("clip_len", [10.0, 30.0])
@pytest.mark.parametrize("peak", ["none", "zero", "end"])
def test_template_fits_every_fixture_case(case, clip_len, peak):
    value = {"none": None, "zero": 0.0, "end": clip_len - 0.01}[peak]
    _check_template(case.facts, clip_len, value)

def test_template_full_facts_at_30s_mentions_everything():
    text = NFC(" ".join(t for _, t in script.write_script(GOAL, 30.0)))
    for needle in ("bàn thắng", "Hà Nội FC", "Hải Phòng", "phút 23", "V.League 2026", "1-0"):
        assert NFC(needle) in text

def test_template_full_facts_at_10s_still_fits():
    lines = _check_template(GOAL, 10.0, None)
    assert "bàn thắng" in NFC(" ".join(t for _, t in lines))

def test_template_default_peak_and_exact_layout():
    lines = script.write_script(GOAL, 30.0)
    assert [t for _, t in lines] == ["Phút 23, Hà Nội FC gặp Hải Phòng tại V.League 2026.", "Vào! Bàn thắng!", "Tỉ số 1-0."]
    d = script.speech_seconds
    assert lines[1][0] == 20.0
    assert lines[0][0] == pytest.approx(20.0 - 0.25 - d(lines[0][1]))
    assert lines[2][0] == pytest.approx(20.0 + d(lines[1][1]) + 0.25)

def test_template_bare_facts_is_moment_line_only():
    assert script.write_script(ClipFacts("other"), 10.0, peak=4.0) == [(4.0, "Khoảnh khắc đáng chú ý!")]

def test_template_one_team_and_no_minute():
    lines = script.write_script(ClipFacts("save", home="Arsenal"), 30.0)
    assert [t for _, t in lines] == ["Trận đấu của Arsenal.", "Pha cứu thua tuyệt vời!"]

def test_default_peak():
    assert script.default_peak(12.0) == 8.0

@pytest.mark.parametrize("kwargs", [
    dict(clip_len=0.0), dict(clip_len=-1.0), dict(clip_len=float("nan")), dict(clip_len=float("inf")),
    dict(clip_len=True), dict(clip_len="10"), dict(clip_len=10.0, peak=-0.1), dict(clip_len=10.0, peak=10.0),
    dict(clip_len=10.0, peak=float("nan")), dict(clip_len=10.0, backend="gpt"),
])
def test_write_script_rejects_bad_input(kwargs):
    with pytest.raises(ValueError):
        script.write_script(GOAL, **kwargs)

def test_write_script_too_short_clip_is_empty():
    assert script.write_script(GOAL, 1.0) == []

# --- LLM backend (AC7)

def _llm(monkeypatch, caplog, client, facts=GOAL, clip_len=10.0, peak=None):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-key")
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="sportscut.commentary"):
        out = script.write_script(facts, clip_len, "llm", peak=peak, client=client)
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert not any("sk-secret-key" in m for m in messages)
    return out, messages

def test_llm_good_json_used_at_placed_times(monkeypatch, caplog):
    roles = {"before": "Phút 23, Hà Nội FC tấn công.", "at": "Bàn thắng đẹp mắt!", "after": "Tỉ số 1-0."}
    client = fake_client(json.dumps(roles, ensure_ascii=False))
    out, messages = _llm(monkeypatch, caplog, client, clip_len=30.0, peak=20.0)
    assert messages == []
    d = script.speech_seconds
    assert out == [(20.0 - 0.25 - d(roles["before"]), roles["before"]), (20.0, roles["at"]),
                   (20.0 + d(roles["at"]) + 0.25, roles["after"])]
    request = client.calls[0]
    assert set(request) == {"model", "max_tokens", "system", "messages"}
    content = json.loads(request["messages"][0]["content"])
    assert content["label"] == "Bàn thắng" and content["minute"] == 23 and content["clip_len"] == 30.0
    assert content["peak"] == 20.0
    assert content["before_max_syllables"] == math.floor(3.5 * (20.0 - 0.5))
    assert content["at_after_max_syllables"] == math.floor(3.5 * (30.0 - 0.25 - 20.0))

def test_llm_fenced_json_with_null_roles(monkeypatch, caplog):
    client = fake_client('```json\n{"before": null, "at": " Bàn thắng! ", "after": ""}\n```')
    out, messages = _llm(monkeypatch, caplog, client, peak=5.0)
    assert out == [(5.0, "Bàn thắng!")] and messages == []

@pytest.mark.parametrize("text,exc,expect", [
    (json.dumps({"before": "Trận đấu " * 30, "at": "Bàn thắng!", "after": None}, ensure_ascii=False), None, "rejected LLM script"),
    (json.dumps({"before": None, "at": "Bàn thắng phút 99!", "after": None}, ensure_ascii=False), None, "number 99 not in facts"),
    ("not json", None, "not valid"),
    ('{"before": 1, "at": "Bàn thắng!"}', None, "not valid"),
    ('{"at": ""}', None, "not valid"),
    ("[]", None, "not valid"),
    (None, RuntimeError("boom sk-secret-key"), "LLM script request failed (RuntimeError)"),
])
def test_llm_bad_response_falls_back_to_template(monkeypatch, caplog, text, exc, expect):
    out, messages = _llm(monkeypatch, caplog, fake_client(text, exc))
    assert out == script.write_script(GOAL, 10.0)
    assert any("template fallback" in m and expect in m for m in messages), messages

def test_llm_no_key_makes_no_client(monkeypatch, caplog):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "anthropic", NS(Anthropic=lambda **kw: pytest.fail("client created")))
    with caplog.at_level(logging.WARNING, logger="sportscut.commentary"):
        out = script.write_script(GOAL, 30.0, "llm")
    assert out == script.write_script(GOAL, 30.0)
    assert any("ANTHROPIC_API_KEY is not set; template fallback" in r.getMessage() for r in caplog.records)

def test_llm_missing_package_falls_back(monkeypatch, caplog):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-key")
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with caplog.at_level(logging.WARNING, logger="sportscut.commentary"):
        out = script.write_script(GOAL, 30.0, "llm")
    assert out == script.write_script(GOAL, 30.0)
    assert any("pip install 'sportscut[llm]'" in r.getMessage() for r in caplog.records)

# --- eval-meta --script (AC8, AC9)

def test_eval_meta_script_report():
    report = eval_meta.evaluate_meta_dir(FIXTURE, script=True)
    assert list(report) == ["score", "script_fits", "fact_recall", "hallucination_rate", "vi_rate", "per_case"]
    items = report["per_case"]
    assert len(items) == 16
    assert [(i["id"], i["clip_len"]) for i in items] == [(c.id, L) for c in CASES for L in (10.0, 30.0)]
    assert list(items[0]) == ["id", "clip_len", "score", "script_fits", "fact_recall", "hallucinated", "vi", "problems", "lines"]
    assert report["script_fits"] == 1.0 and report["hallucination_rate"] == 0.0 and report["vi_rate"] == 1.0
    assert report["score"] >= 0.9
    assert list(items[0]["lines"][0]) == ["start", "text"]

def test_eval_meta_script_overlap_scores_zero(monkeypatch):
    real = script.write_script
    def fake(facts, clip_len, backend="template", **kw):
        lines = real(facts, clip_len, backend, **kw)
        return [(1.0, "Vào! Bàn thắng!"), (1.2, "Tỉ số.")] if clip_len == 10.0 and facts.event == "goal" else lines
    monkeypatch.setattr(script, "write_script", fake)
    report = eval_meta.evaluate_meta_dir(FIXTURE, script=True)
    assert report["script_fits"] < 1.0
    bad = [i for i in report["per_case"] if not i["script_fits"]]
    assert bad and all(i["score"] == 0.0 and "line 2 overlaps line 1" in i["problems"] for i in bad)

def test_eval_meta_default_unchanged():
    report = eval_meta.evaluate_meta_dir(FIXTURE)
    assert list(report) == ["score", "format_ok", "fact_recall", "hallucination_rate", "vi_rate", "per_case"]
    assert {k: report[k] for k in list(report)[:5]} == {
        "score": 1.0, "format_ok": 1.0, "fact_recall": 1.0, "hallucination_rate": 0.0, "vi_rate": 1.0}

# --- pipeline (AC10) and CLI (AC11)

def test_run_voiceover_writes_scripts(burst_video, tmp_path):
    from sportscut import media
    from sportscut.pipeline import run
    out = tmp_path / "out"
    entries = run(burst_video, out, voiceover=True)
    assert entries and not list(out.glob("vertical"))
    for entry in entries:
        stem = Path(entry["file"]).stem
        assert list(entry)[-1] == "script_file" and entry["script_file"] == f"{stem}.script.json"
        record = json.loads((out / entry["script_file"]).read_text(encoding="utf-8"))
        assert list(record) == ["clip", "clip_len", "peak", "backend", "lines"]
        clip_len = entry["end"] - entry["start"]
        assert record["clip"] == entry["file"] and record["clip_len"] == clip_len and record["backend"] == "template"
        peak = script.audio_peak(media.extract_audio(out / entry["file"]), clip_len)
        assert record["peak"] == (script.default_peak(clip_len) if peak is None else peak)
        lines = [(line["start"], line["text"]) for line in record["lines"]]
        assert all(list(line) == ["start", "end", "text"] for line in record["lines"])
        assert all(line["end"] == pytest.approx(line["start"] + script.speech_seconds(line["text"])) for line in record["lines"])
        assert lines and script.script_fits(lines, clip_len)
    from sportscut.export import MANIFEST_NAME
    manifest = json.loads((out / MANIFEST_NAME).read_text(encoding="utf-8"))
    assert [e["script_file"] for e in manifest] == [e["script_file"] for e in entries]

def test_run_voiceover_uses_audio_peak(burst_video, tmp_path, monkeypatch):
    from sportscut.pipeline import run
    monkeypatch.setattr(script, "audio_peak", lambda samples, clip_len: 2.5)
    out = tmp_path / "out"
    entries = run(burst_video, out, top=1, voiceover=True)
    record = json.loads((out / entries[0]["script_file"]).read_text(encoding="utf-8"))
    assert record["peak"] == 2.5
    moment = [line for line in record["lines"] if KEYS[entries[0]["event"]] in NFC(line["text"])][0]
    assert moment["start"] == 2.5

def test_run_without_voiceover_writes_no_script(burst_video, tmp_path):
    from sportscut.pipeline import run
    out = tmp_path / "out"
    entries = run(burst_video, out, top=2)
    assert not list(out.glob("*.script.json"))
    assert all("script_file" not in entry for entry in entries)

@pytest.mark.parametrize("flag", [True, False])
def test_cli_cut_voiceover_forwarded_and_printed(monkeypatch, capsys, flag):
    from sportscut import cli
    calls = []
    def fake_run(video, out, **kwargs):
        calls.append(kwargs)
        entry = {"file": "clip_01.mp4", "vertical_file": "vertical/clip_01.mp4"}
        return [{**entry, "script_file": "clip_01.script.json"} if kwargs["voiceover"] else entry]
    monkeypatch.setattr(cli, "run", fake_run)
    argv = ["cut", "v.mp4", "--out", "o", "--vertical"] + (["--voiceover"] if flag else [])
    assert cli.main(argv) == 0
    assert calls[0]["voiceover"] is flag
    want = [str(Path("o/clip_01.mp4")), str(Path("o/vertical/clip_01.mp4"))]
    assert capsys.readouterr().out.splitlines() == want + ([str(Path("o/clip_01.script.json"))] if flag else [])

def test_cli_eval_meta_script_json(capsys, monkeypatch):
    from sportscut import cli
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for extra in ([], ["--meta-backend", "llm"]):
        assert cli.main(["eval-meta", str(FIXTURE), "--json", "--script", *extra]) == 0
        report = json.loads(capsys.readouterr().out)
        assert list(report) == ["score", "script_fits", "fact_recall", "hallucination_rate", "vi_rate", "per_case"]
        assert report["script_fits"] == 1.0 and len(report["per_case"]) == 16

@pytest.mark.parametrize("command,flag", [("cut", "--voiceover"), ("eval-meta", "--script")])
def test_cli_help_lists_flag(capsys, command, flag):
    from sportscut import cli
    with pytest.raises(SystemExit):
        cli.main([command, "--help"])
    assert flag in capsys.readouterr().out
