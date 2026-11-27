"""T-026 Tester acceptance tests, written from the acceptance criteria in .office/TASK.md.

They use their own hand-made ClipFacts and an independent syllable counter (AC2 rule:
letter runs + decimal digits) instead of the Developer's helpers wherever the AC allows.
"""
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import tarfile
import io
import unicodedata
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np
import pytest

from sportscut import cli, media, pipeline
from sportscut.commentary import eval_meta, llm, script
from sportscut.commentary.facts import ClipFacts

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/eval_meta"
CASES = eval_meta.load_cases(FIXTURE / "cases.json")
SR = 16000
PAD = 0.25
TOL = 1e-6
KEYWORDS = {
    "goal": "bàn thắng",
    "save": "cứu thua",
    "red_card": "thẻ đỏ",
    "controversy": "tranh cãi",
    "other": "khoảnh khắc",
}
GOAL_FULL = ClipFacts("goal", 23, "Hà Nội FC", "Hải Phòng", "V.League 2026", "1-0")
OWN_FACTS = {
    "save_comp_only": ClipFacts("save", competition="AFF Cup 2026"),
    "red_long_names": ClipFacts("red_card", 90, "Sông Lam Nghệ An Football Club",
                                "Hoàng Anh Gia Lai Football Club", "Giải Vô địch Quốc gia 2026", "2-2"),
    "controversy_one_team": ClipFacts("controversy", 5, home="Đà Nẵng"),
    "other_score_only": ClipFacts("other", score="0-0"),
    "goal_minute_only": ClipFacts("goal", 1),
    "goal_full": GOAL_FULL,
    "save_away_only": ClipFacts("save", 77, away="Thanh Hóa", score="10-9"),
}


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def own_syllables(text: str) -> int:
    """Independent AC2 count: runs of letters plus each decimal digit (on NFC text)."""
    count, in_run = 0, False
    for char in nfc(text):
        if char.isalpha():
            if not in_run:
                count += 1
            in_run = True
        else:
            in_run = False
            if char.isdecimal():
                count += 1
    return count


def own_dur(text: str) -> float:
    return own_syllables(text) / 3.5


def own_fits(lines, clip_len) -> bool:
    if not 1 <= len(lines) <= 3:
        return False
    prev_end = None
    for start, text in lines:
        if not math.isfinite(start) or start < PAD - TOL:
            return False
        end = start + own_dur(text)
        if end > clip_len - PAD + TOL:
            return False
        if prev_end is not None and start < prev_end - TOL:
            return False
        prev_end = end
    return True


def moment_index(lines, event):
    hits = [i for i, (_, t) in enumerate(lines) if KEYWORDS[event] in nfc(t).casefold()]
    assert len(hits) == 1, (event, lines)
    return hits[0]


def expected_moment_start(peak, text, clip_len):
    dur = own_dur(text)
    if peak + dur <= clip_len - PAD:
        return max(peak, PAD)
    return clip_len - PAD - dur


def facts_numbers(facts):
    blob = " ".join(str(v) for v in vars(facts).values() if v is not None)
    return set(re.findall(r"\d+", blob))


def all_facts():
    out = [(c.id, c.facts) for c in CASES]
    out += list(OWN_FACTS.items())
    return out


# ---------------------------------------------------------------- AC1
@pytest.mark.parametrize("clip_len", [10.0, 30.0])
@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_ac1_fixture_cases_fit_and_validate(case, clip_len):
    for peak in (None, 0.0, clip_len - 0.01):
        lines = script.write_script(case.facts, clip_len, "template", peak=peak)
        assert isinstance(lines, list) and 1 <= len(lines) <= 3, (peak, lines)
        for item in lines:
            assert isinstance(item, tuple) and len(item) == 2
            assert isinstance(item[0], float) and isinstance(item[1], str)
        starts = [s for s, _ in lines]
        assert starts == sorted(starts)
        assert script.validate_script(case.facts, lines, clip_len) == [], (peak, lines)


@pytest.mark.parametrize("clip_len", [10.0, 30.0])
@pytest.mark.parametrize("name", list(OWN_FACTS))
def test_ac1_own_facts_fit_and_validate(name, clip_len):
    facts = OWN_FACTS[name]
    for peak in (None, 0.0, 0.3, clip_len / 2, clip_len - 0.01):
        lines = script.write_script(facts, clip_len, peak=peak)
        assert 1 <= len(lines) <= 3, (peak, lines)
        assert script.validate_script(facts, lines, clip_len) == [], (peak, lines)


def test_ac1_default_backend_is_template():
    assert script.write_script(GOAL_FULL, 30.0) == script.write_script(GOAL_FULL, 30.0, "template")


# ---------------------------------------------------------------- AC2
def test_ac2_independent_timing_contract_over_many_inputs():
    for name, facts in all_facts():
        for clip_len in (2.5, 4.0, 6.0, 10.0, 12.0, 30.0, 60.0):
            for frac in (None, 0.0, 0.1, 0.33, 0.5, 0.67, 0.9, 0.999):
                peak = None if frac is None else frac * clip_len
                lines = script.write_script(facts, clip_len, peak=peak)
                assert lines, (name, clip_len, peak)
                assert own_fits(lines, clip_len), (name, clip_len, peak, lines)
                assert script.script_fits(lines, clip_len)


def test_ac2_syllables_rule_and_nfd():
    samples = ["Phút 23, Hà Nội FC.", "Vào! Bàn thắng!", "Tỉ số 10-9.", "Hoàng Anh Gia Lai",
               "V.League 2026", "Câu lạc bộ Bóng đá Công an Hà Nội", "", "!!! ...", "a1b2"]
    for text in samples:
        assert script.syllables(text) == own_syllables(text), text
        assert script.syllables(unicodedata.normalize("NFD", text)) == script.syllables(nfc(text))
    assert script.syllables("Phút 23, Hà Nội FC.") == 6
    assert script.syllables("Tỉ số 10-9.") == 5
    assert script.speech_seconds("Tỉ số 10-9.") == pytest.approx(5 / 3.5)


def test_ac2_script_fits_rejects_bad_scripts():
    a, b = "Phút 23, Hà Nội FC.", "Vào! Bàn thắng!"  # 6 and 3 syllables
    da = 6 / 3.5
    good = [(0.25, a), (0.25 + da, b)]
    assert script.script_fits(good, 10.0) is True
    assert script.fit_problems(good, 10.0) == []
    bad = {
        "overlap": [(0.25, a), (0.25 + da - 0.01, b)],
        "overrun": [(10.0 - 0.25 - 3 / 3.5 + 0.01, b)],
        "before_pad": [(0.24, b)],
        "negative": [(-1.0, b)],
        "nan_start": [(float("nan"), b)],
        "unsorted": [(5.0, b), (0.25, a)],
        "empty": [],
        "four_lines": [(0.25, "Một."), (1.0, "Hai."), (2.0, "Ba."), (3.0, "Bốn.")],
    }
    for label, lines in bad.items():
        assert script.script_fits(lines, 10.0) is False, label
        assert script.fit_problems(lines, 10.0), label
    # exact boundaries within tolerance still fit
    assert script.script_fits([(10.0 - 0.25 - 3 / 3.5, b)], 10.0)
    assert script.script_fits([(0.25, a), (0.25 + da, b)], 0.25 + da + 3 / 3.5 + 0.25)


# ---------------------------------------------------------------- AC3
def test_ac3_moment_line_placement_and_keyword_order():
    for name, facts in all_facts():
        for clip_len in (6.0, 10.0, 30.0):
            for peak in (0.25, 1.0, 3.0, clip_len * 0.5, clip_len * 2 / 3, clip_len - 1.0, clip_len - 0.01):
                lines = script.write_script(facts, clip_len, peak=peak)
                i = moment_index(lines, facts.event)
                start, text = lines[i]
                assert start == pytest.approx(expected_moment_start(peak, text, clip_len), abs=TOL), \
                    (name, clip_len, peak, lines)
                for _, before in lines[:i]:
                    assert KEYWORDS[facts.event] not in nfc(before).casefold()


def test_ac3_peak_exactly_when_room():
    lines = script.write_script(GOAL_FULL, 30.0, peak=12.0)
    start, _ = lines[moment_index(lines, "goal")]
    assert start == 12.0


def test_ac3_peak_none_is_eight_twelfths():
    for clip_len in (10.0, 12.0, 30.0):
        assert script.default_peak(clip_len) == pytest.approx(clip_len * 8 / 12)
        lines = script.write_script(GOAL_FULL, clip_len)
        assert lines == script.write_script(GOAL_FULL, clip_len, peak=clip_len * 8 / 12)
        start, text = lines[moment_index(lines, "goal")]
        assert start == pytest.approx(expected_moment_start(clip_len * 8 / 12, text, clip_len))


def test_ac3_peak_below_pad_is_clamped_to_pad():
    # AC2 forbids starts before 0.25 s, so a peak of 0.0 places the moment line at the pad.
    lines = script.write_script(OWN_FACTS["other_score_only"], 10.0, peak=0.0)
    assert lines[moment_index(lines, "other")][0] == pytest.approx(PAD)


# ---------------------------------------------------------------- AC4
def test_ac4_goal_full_30s_mentions_every_fact():
    lines = script.write_script(GOAL_FULL, 30.0)
    joined = nfc("\n".join(t for _, t in lines)).casefold()
    for needle in ("bàn thắng", "Hà Nội FC", "Hải Phòng", "phút 23", "V.League 2026", "1-0"):
        assert nfc(needle).casefold() in joined, (needle, lines)


def test_ac4_goal_full_10s_keeps_event_and_fits():
    lines = script.write_script(GOAL_FULL, 10.0)
    joined = nfc("\n".join(t for _, t in lines)).casefold()
    assert "bàn thắng" in joined
    assert own_fits(lines, 10.0)


def test_ac4_no_invented_numbers_in_any_template_script():
    for name, facts in all_facts():
        allowed = facts_numbers(facts)
        for clip_len in (3.0, 10.0, 30.0):
            for peak in (None, 0.0, clip_len - 0.01):
                lines = script.write_script(facts, clip_len, peak=peak)
                for _, text in lines:
                    for number in re.findall(r"\d+", text):
                        assert number in allowed, (name, number, text)


# ---------------------------------------------------------------- AC5
def _seconds(levels, extra=0):
    rng = np.random.default_rng(0)
    parts = [rng.standard_normal(SR).astype(np.float32) * lvl for lvl in levels]
    if extra:
        parts.append(np.ones(extra, dtype=np.float32) * 100)
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def test_ac5_audio_peak():
    assert script.audio_peak(_seconds([0.1, 0.1, 0.2, 0.9, 0.1]), 5.0) == 3.5
    assert script.audio_peak(_seconds([0.9, 0.1]), 2.0) == 0.5
    # seconds beyond floor(clip_len) are ignored
    assert script.audio_peak(_seconds([0.1, 0.5, 0.1, 5.0]), 3.9) == 1.5
    # partial trailing second is ignored even if loud
    assert script.audio_peak(_seconds([0.1, 0.3], extra=SR // 2), 10.0) == 1.5
    # ties: the first maximum wins
    tie = np.concatenate([np.zeros(SR), np.ones(SR), np.zeros(SR), np.ones(SR)]).astype(np.float32)
    assert script.audio_peak(tie, 4.0) == 1.5
    # zero whole seconds -> None
    assert script.audio_peak(np.ones(SR - 1, dtype=np.float32), 10.0) is None
    assert script.audio_peak(np.ones(3 * SR, dtype=np.float32), 0.9) is None
    assert script.audio_peak(np.zeros(0, dtype=np.float32), 10.0) is None
    # always inside the clip
    assert script.audio_peak(_seconds([0.1] * 9 + [1.0]), 10.0) == 9.5


# ---------------------------------------------------------------- AC6
@pytest.mark.parametrize("clip_len", [0, 0.0, -1.0, float("nan"), float("inf"), True, False, "10"])
def test_ac6_bad_clip_len(clip_len):
    with pytest.raises(ValueError):
        script.write_script(GOAL_FULL, clip_len)


@pytest.mark.parametrize("peak", [-0.01, 10.0, 11.0, float("nan"), float("inf"), float("-inf")])
def test_ac6_bad_peak(peak):
    with pytest.raises(ValueError):
        script.write_script(GOAL_FULL, 10.0, peak=peak)


def test_ac6_unknown_backend_and_tiny_clip():
    with pytest.raises(ValueError):
        script.write_script(GOAL_FULL, 10.0, "gpt")
    assert script.write_script(GOAL_FULL, 1.0) == []
    assert script.write_script(ClipFacts("other"), 1.0) == []
    assert script.write_script(GOAL_FULL, 10, peak=0) != []  # ints are accepted


# ---------------------------------------------------------------- AC7
def fake_client(text=None, exc=None):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if exc is not None:
            raise exc
        return NS(content=[NS(type="text", text=text)])

    return NS(calls=calls, messages=NS(create=create))


def placed(before, at, after, clip_len, peak):
    s_at = max(PAD, min(peak, clip_len - PAD - own_dur(at)))
    out = []
    if before is not None:
        out.append((s_at - 0.25 - own_dur(before), before))
    out.append((s_at, at))
    if after is not None:
        out.append((s_at + own_dur(at) + 0.25, after))
    return out


GOOD_ROLES = {"before": "Phút 23, Hà Nội FC gặp Hải Phòng.", "at": "Vào rồi, bàn thắng đẹp mắt!",
              "after": "Tỉ số 1-0."}


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def test_ac7_good_llm_json_used_at_placed_times(caplog, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = fake_client("```json\n" + json.dumps(GOOD_ROLES, ensure_ascii=False) + "\n```")
    with caplog.at_level(logging.WARNING, logger="sportscut.commentary"):
        lines = script.write_script(GOAL_FULL, 30.0, "llm", peak=18.0, client=client)
    expected = placed(GOOD_ROLES["before"], GOOD_ROLES["at"], GOOD_ROLES["after"], 30.0, 18.0)
    assert [t for _, t in lines] == [t for _, t in expected]
    for (s, _), (e, _) in zip(lines, expected):
        assert s == pytest.approx(e, abs=TOL)
    assert lines != script.write_script(GOAL_FULL, 30.0, peak=18.0)
    assert not [m for m in _warnings(caplog) if "template fallback" in m]
    assert len(client.calls) == 1
    req = client.calls[0]
    assert set(req) >= {"model", "max_tokens", "system", "messages"}
    content = json.loads(req["messages"][0]["content"])
    for key in ("label", "clip_len", "peak", "before_max_syllables", "at_after_max_syllables"):
        assert key in content, key
    assert content["peak"] == 18.0 and content["clip_len"] == 30.0


def test_ac7_llm_null_before_after(monkeypatch):
    client = fake_client(json.dumps({"before": None, "at": "Bàn thắng!", "after": ""}))
    lines = script.write_script(GOAL_FULL, 10.0, "llm", peak=5.0, client=client)
    assert lines == [(5.0, "Bàn thắng!")]


BAD_RESPONSES = {
    "overrun": dict(text=json.dumps({"before": None, "at": "Bàn thắng! " + "Một pha bóng tuyệt vời. " * 12,
                                     "after": None}, ensure_ascii=False)),
    "overlong_before": dict(text=json.dumps({"before": ("Hà Nội FC gặp Hải Phòng " * 15).strip(), "at": "Bàn thắng!",
                                             "after": None}, ensure_ascii=False)),
    "invented_number": dict(text=json.dumps({"before": None, "at": "Bàn thắng thứ 99 của mùa giải!",
                                             "after": None}, ensure_ascii=False)),
    "invented_name": dict(text=json.dumps({"before": None, "at": "Bàn thắng của Quang Hải!",
                                           "after": None}, ensure_ascii=False)),
    "english": dict(text=json.dumps({"before": None, "at": "What a goal by the home side!", "after": None})),
    "not_json": dict(text="Bàn thắng tuyệt đẹp!"),
    "json_list": dict(text=json.dumps(["Bàn thắng!"])),
    "missing_at": dict(text=json.dumps({"before": None, "after": None})),
    "at_number": dict(text=json.dumps({"before": None, "at": 5, "after": None})),
    "raises": dict(exc=RuntimeError("boom")),
}


@pytest.mark.parametrize("name", list(BAD_RESPONSES))
def test_ac7_bad_llm_response_falls_back_to_template(name, caplog):
    peak = 20.0
    template = script.write_script(GOAL_FULL, 30.0, peak=peak)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="sportscut.commentary"):
        lines = script.write_script(GOAL_FULL, 30.0, "llm", peak=peak, client=fake_client(**BAD_RESPONSES[name]))
    assert lines == template
    assert any("template fallback" in m for m in _warnings(caplog)), _warnings(caplog)


def test_ac7_no_key_no_client_created(caplog, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def boom(**kwargs):
        raise AssertionError("anthropic client must not be created without a key")

    monkeypatch.setitem(sys.modules, "anthropic", NS(Anthropic=boom))
    with caplog.at_level(logging.WARNING, logger="sportscut.commentary"):
        lines = script.write_script(OWN_FACTS["save_comp_only"], 10.0, "llm")
    assert lines == script.write_script(OWN_FACTS["save_comp_only"], 10.0)
    assert any("template fallback" in m for m in _warnings(caplog))


def test_ac7_key_never_logged(caplog, monkeypatch):
    secret = "sk-ant-t026-SECRET-VALUE"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    created = []

    def make(**kwargs):
        created.append(kwargs)
        return fake_client(exc=RuntimeError(f"bad key {secret}"))

    monkeypatch.setitem(sys.modules, "anthropic", NS(Anthropic=make))
    with caplog.at_level(logging.DEBUG):
        lines = script.write_script(GOAL_FULL, 30.0, "llm")
    assert created and lines == script.write_script(GOAL_FULL, 30.0)
    assert any("template fallback" in m for m in _warnings(caplog))
    for record in caplog.records:
        assert secret not in record.getMessage()
    assert secret not in caplog.text


# ---------------------------------------------------------------- AC8 / AC9 (CLI subprocess)
def _cli(*args, env=None):
    full_env = dict(os.environ)
    full_env.pop("ANTHROPIC_API_KEY", None)
    if env:
        full_env.update(env)
    return subprocess.run([sys.executable, "-m", "sportscut", *args], cwd=ROOT, capture_output=True,
                          text=True, encoding="utf-8", env=full_env)


def _base():
    result = subprocess.run(["git", "merge-base", "main", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def test_ac8_default_eval_meta_headline_unchanged():
    result = _cli("eval-meta", "tests/fixtures/eval_meta", "--json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert list(report) == ["score", "format_ok", "fact_recall", "hallucination_rate", "vi_rate", "per_case"]
    headline = {k: v for k, v in report.items() if k != "per_case"}
    assert headline == {"score": 1.0, "format_ok": 1.0, "fact_recall": 1.0, "hallucination_rate": 0.0,
                        "vi_rate": 1.0}
    base = _base()
    if base is None:
        return
    readme = subprocess.run(["git", "show", f"{base}:README.md"], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8").stdout
    section = readme.split("## Bình luận AI", 1)[1]
    baseline = json.loads(section.split("```json\n", 1)[1].split("```", 1)[0])
    assert headline == baseline


def test_ac8_default_eval_meta_byte_identical_to_main(tmp_path):
    base = _base()
    if base is None:
        pytest.skip("no main branch to compare against")
    archive = subprocess.run(["git", "archive", base, "sportscut"], cwd=ROOT, capture_output=True)
    assert archive.returncode == 0
    with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
        tar.extractall(tmp_path)
    fixture = str(FIXTURE)
    main_out = subprocess.run([sys.executable, "-m", "sportscut", "eval-meta", fixture, "--json"],
                              cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
                              env={**os.environ, "PYTHONPATH": str(tmp_path)})
    assert main_out.returncode == 0, main_out.stderr
    ours = _cli("eval-meta", fixture, "--json")
    assert ours.returncode == 0
    assert ours.stdout == main_out.stdout


SCRIPT_KEYS = ["score", "script_fits", "fact_recall", "hallucination_rate", "vi_rate", "per_case"]
ITEM_KEYS = ["id", "clip_len", "score", "script_fits", "fact_recall", "hallucinated", "vi", "problems", "lines"]


def _check_script_report(report):
    assert list(report) == SCRIPT_KEYS
    assert report["script_fits"] == 1.0
    assert report["hallucination_rate"] == 0.0
    assert report["vi_rate"] == 1.0
    assert report["score"] >= 0.9
    items = report["per_case"]
    assert len(items) == 16
    assert [(i["id"], i["clip_len"]) for i in items] == [(c.id, L) for c in CASES for L in (10.0, 30.0)]
    for item in items:
        assert list(item) == ITEM_KEYS
        assert item["script_fits"] is True and item["problems"] == []
        lines = [(l["start"], l["text"]) for l in item["lines"]]
        assert own_fits(lines, item["clip_len"])
    assert report["score"] == pytest.approx(sum(i["score"] for i in items) / 16, abs=1e-4)


def test_ac9_eval_meta_script_cli():
    result = _cli("eval-meta", "tests/fixtures/eval_meta", "--json", "--script")
    assert result.returncode == 0, result.stderr
    _check_script_report(json.loads(result.stdout))


def test_ac9_eval_meta_script_llm_without_key_matches_template():
    template = _cli("eval-meta", "tests/fixtures/eval_meta", "--json", "--script")
    llm_run = _cli("eval-meta", "tests/fixtures/eval_meta", "--json", "--script", "--meta-backend", "llm")
    assert llm_run.returncode == 0, llm_run.stderr
    assert json.loads(llm_run.stdout) == json.loads(template.stdout)
    assert "template fallback" in llm_run.stderr


def test_ac9_non_fitting_script_scores_zero(monkeypatch):
    real = script.write_script

    def overlapping(facts, clip_len, backend="template", **kw):
        if facts == CASES[0].facts and clip_len == 30.0:
            return [(1.0, "Phút 23, Hà Nội FC gặp Hải Phòng tại V.League 2026."),
                    (1.5, "Vào! Bàn thắng!"), (20.0, "Tỉ số 1-0.")]
        return real(facts, clip_len, backend, **kw)

    monkeypatch.setattr(script, "write_script", overlapping)
    report = eval_meta.evaluate_meta_dir(FIXTURE, script=True)
    bad = report["per_case"][1]
    assert (bad["id"], bad["clip_len"]) == (CASES[0].id, 30.0)
    assert bad["script_fits"] is False and bad["score"] == 0.0
    assert bad["fact_recall"] == 1.0  # facts were all mentioned; only the timing failed
    assert report["script_fits"] < 1.0 and report["score"] < 1.0


def test_ac9_hallucinated_script_scores_zero(monkeypatch):
    real = script.write_script

    def invented(facts, clip_len, backend="template", **kw):
        if facts == CASES[0].facts and clip_len == 10.0:
            return [(2.0, "Bàn thắng thứ 77 cho Nam Định!")]
        return real(facts, clip_len, backend, **kw)

    monkeypatch.setattr(script, "write_script", invented)
    report = eval_meta.evaluate_meta_dir(FIXTURE, script=True)
    bad = report["per_case"][0]
    assert bad["hallucinated"] is True and bad["score"] == 0.0
    assert report["hallucination_rate"] > 0.0


# ---------------------------------------------------------------- AC10 (end-to-end with ffmpeg)
@pytest.fixture(scope="module")
def match_video(tmp_path_factory):
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required on PATH")
    path = tmp_path_factory.mktemp("t026") / "match.mp4"
    args = [
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i", "color=c=green:s=160x120:r=5:d=60",
        "-f", "lavfi", "-i", "anoisesrc=d=60:c=white:r=44100:a=0.02:seed=26", "-filter_complex",
        "[1:a]volume=volume=25:enable='between(t,18,19)',volume=volume=15:enable='between(t,44,45)',"
        "aformat=channel_layouts=stereo[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "mpeg4", "-q:v", "5", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "96k", "-t", "60", str(path),
    ]
    subprocess.run(args, check=True, capture_output=True)
    return path


def test_ac10_pipeline_voiceover_end_to_end(match_video, tmp_path):
    out = tmp_path / "out"
    entries = pipeline.run(match_video, out, top=2, voiceover=True)
    assert entries
    manifest = json.loads((out / "highlights.json").read_text(encoding="utf-8"))
    on_disk = manifest
    for entry in entries:
        stem = Path(entry["file"]).stem
        assert list(entry)[-1] == "script_file"
        assert entry["script_file"] == f"{stem}.script.json"
        raw = (out / entry["script_file"]).read_bytes()
        record = json.loads(raw.decode("utf-8"))
        assert list(record) == ["clip", "clip_len", "peak", "backend", "lines"]
        clip_len = entry["end"] - entry["start"]
        assert record["clip"] == entry["file"] and record["backend"] == "template"
        assert record["clip_len"] == pytest.approx(clip_len)
        expected_peak = script.audio_peak(media.extract_audio(out / entry["file"]), clip_len)
        if expected_peak is None:
            expected_peak = script.default_peak(clip_len)
        assert record["peak"] == pytest.approx(expected_peak)
        lines = [(l["start"], l["text"]) for l in record["lines"]]
        assert lines and own_fits(lines, clip_len)
        for l in record["lines"]:
            assert list(l) == ["start", "end", "text"]
            assert l["end"] == pytest.approx(l["start"] + own_dur(l["text"]))
        assert b"\\u" not in raw and raw.endswith(b"\n")  # UTF-8, ensure_ascii=False
    assert on_disk == entries  # manifest rewritten with the script_file keys


def test_ac10_pipeline_default_writes_no_script(match_video, tmp_path):
    plain = pipeline.run(match_video, tmp_path / "plain", top=2)
    voiced = pipeline.run(match_video, tmp_path / "voiced", top=2, voiceover=True)
    assert not list((tmp_path / "plain").rglob("*.script.json"))
    assert len(list((tmp_path / "voiced").glob("*.script.json"))) == len(voiced)
    for a, b in zip(plain, voiced):
        assert "script_file" not in a
        assert list(b)[:-1] == list(a)


# ---------------------------------------------------------------- AC11
def _fake_run(calls, entries):
    def run(video, out, **kwargs):
        calls.append(kwargs)
        return entries
    return run


def test_ac11_cut_voiceover_forwarded_and_printed(monkeypatch, capsys, tmp_path):
    calls = []
    entries = [{"file": "clip_01.mp4", "vertical_file": "vertical/clip_01.mp4", "script_file": "clip_01.script.json"},
               {"file": "clip_02.mp4", "script_file": "clip_02.script.json"}]
    monkeypatch.setattr(cli, "run", _fake_run(calls, entries))
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path), "--voiceover"]) == 0
    assert calls[-1]["voiceover"] is True
    assert capsys.readouterr().out.splitlines() == [
        str(tmp_path / "clip_01.mp4"), str(tmp_path / "vertical/clip_01.mp4"),
        str(tmp_path / "clip_01.script.json"), str(tmp_path / "clip_02.mp4"),
        str(tmp_path / "clip_02.script.json")]


def test_ac11_cut_without_flag(monkeypatch, capsys, tmp_path):
    calls = []
    monkeypatch.setattr(cli, "run", _fake_run(calls, [{"file": "clip_01.mp4"}]))
    assert cli.main(["cut", "v.mp4", "--out", str(tmp_path)]) == 0
    assert calls[-1]["voiceover"] is False
    assert capsys.readouterr().out.splitlines() == [str(tmp_path / "clip_01.mp4")]


def test_ac11_help_lists_flags():
    cut = _cli("cut", "--help")
    assert cut.returncode == 0 and "--voiceover" in cut.stdout
    ev = _cli("eval-meta", "--help")
    assert ev.returncode == 0 and "--script" in ev.stdout


# ---------------------------------------------------------------- AC12
def _own_branch_base():
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT,
                            capture_output=True, text=True).stdout.strip()
    if not branch.startswith("office/T-026"):
        pytest.skip("scope checks only run on the T-026 branch")
    base = _base()
    if base is None:
        pytest.skip("no main branch to compare against")
    return base


def test_ac12_frozen_paths_unchanged():
    base = _own_branch_base()
    paths = ["sportscut/export.py", "sportscut/models.py", "sportscut/ranking.py", "sportscut/evaluate.py",
             "sportscut/eval_player.py", "sportscut/events/audio_cues.py", "sportscut/commentary/facts.py",
             "sportscut/commentary/meta.py", "sportscut/api.py", "tests/conftest.py", "tests/fixtures/",
             "agent-office/", ".agent-office/"]
    diff = subprocess.run(["git", "diff", "--name-only", base, "--", *paths], cwd=ROOT,
                          capture_output=True, text=True)
    assert diff.returncode == 0 and diff.stdout.strip() == ""
    status = subprocess.run(["git", "status", "--porcelain", "--", *paths], cwd=ROOT,
                            capture_output=True, text=True).stdout
    assert all("__pycache__" in l or l.endswith(".pyc") for l in status.splitlines())


def test_ac12_existing_tests_not_weakened():
    base = _own_branch_base()
    diff = subprocess.run(["git", "diff", "--numstat", base, "--", "tests/"], cwd=ROOT,
                          capture_output=True, text=True)
    for line in diff.stdout.splitlines():
        added, deleted, name = line.split("\t")
        assert deleted == "0", line
    assert subprocess.run(["git", "ls-files", "*.mp4", "*.wav"], cwd=ROOT, capture_output=True,
                          text=True).stdout.strip() == ""


# ---------------------------------------------------------------- AC13
SPECS = ["docs/superpowers/specs/2026-11-23-t-023-add-clip-facts-a-template-metadata-design.md",
         "docs/superpowers/specs/2026-11-26-t-046-re-land-the-reviewed-t-025-design.md",
         "docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md"]


def test_ac13_readme_section_and_measured_headline():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    section = readme.split("## Bình luận AI", 1)[1].split("\n## ", 1)[0]
    blocks = re.findall(r"```json\n(.*?)```", section, re.S)
    assert json.loads(blocks[0]) == {"score": 1.0, "format_ok": 1.0, "fact_recall": 1.0,
                                     "hallucination_rate": 0.0, "vi_rate": 1.0}
    assert "### Kịch bản bình luận" in section
    sub = section.split("### Kịch bản bình luận", 1)[1]
    assert section.index("### Backend LLM") < section.index("### Kịch bản bình luận")
    assert "python -m sportscut eval-meta tests/fixtures/eval_meta --json --script" in sub
    assert "--voiceover" in sub and "clip_NN.script.json" in sub and "script_fits" in sub
    documented = json.loads(re.findall(r"```json\n(.*?)```", sub, re.S)[0])
    measured = json.loads(_cli("eval-meta", "tests/fixtures/eval_meta", "--json", "--script").stdout)
    measured.pop("per_case")
    assert documented == measured


@pytest.mark.parametrize("spec", SPECS)
def test_ac13_specs_have_t026_note(spec):
    text = (ROOT / spec).read_text(encoding="utf-8")
    assert "Updated by T-026" in text
    base = _base()
    if base is not None:
        old = subprocess.run(["git", "show", f"{base}:{spec}"], cwd=ROOT, capture_output=True,
                             text=True, encoding="utf-8")
        if old.returncode == 0:
            assert text.startswith(old.stdout.rstrip("\n"))  # append-only
