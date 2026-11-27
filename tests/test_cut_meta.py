import argparse
import inspect
import json

import pytest

from sportscut import cli, pipeline
from sportscut.pipeline import PipelineError

TEAMS = ["--home", "Việt Nam", "--away", "Thái Lan", "--kickoff", "0"]


def test_meta_help_unchanged(capsys):
    with pytest.raises(SystemExit):
        cli.main(["meta", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    for needle in ("OUT_DIR", "--home HOME home team name", "--away AWAY away team name",
                   "--competition COMPETITION competition name",
                   "kickoff time in seconds into the video; the minute needs it",
                   "match.json with home, away, competition, score, kickoff; flags win",
                   "--meta-backend {template,llm}"):
        assert needle in out


def _ns(**kw):
    return argparse.Namespace(**{k: kw.get(k) for k in ("match_info", "home", "away", "competition", "kickoff")})


def test_match_from_args_merges_file_and_flags(tmp_path):
    f = tmp_path / "m.json"
    f.write_text('{"home": "A", "score": "1-0"}', encoding="utf-8")
    assert cli._match_from_args(_ns(match_info=str(f), home="B", kickoff=0.0)) == {
        "home": "B", "score": "1-0", "kickoff": 0.0}
    assert cli._match_from_args(_ns()) is None
    with pytest.raises(ValueError, match="^cannot read"):
        cli._match_from_args(_ns(match_info=str(tmp_path / "missing.json")))
    f.write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError, match="expected a JSON object$"):
        cli._match_from_args(_ns(match_info=str(f)))


def test_run_signature_last_param_match():
    params = inspect.signature(pipeline.run).parameters
    assert list(params)[-1] == "match"
    assert params["match"].default is None


@pytest.mark.parametrize("match", [{"kickoff": -1}, {"kickoff": float("nan")},
                                   {"venue": "X"}, {"home": "x" * 41}, ["home"]])
def test_run_bad_match_raises_before_writing(tmp_path, monkeypatch, match):
    monkeypatch.setattr(pipeline, "require_ffmpeg", lambda: pytest.fail("ffmpeg checked first"))
    pytest.raises(PipelineError, pipeline.run, tmp_path / "v.mp4", tmp_path / "out", match=match)
    assert not (tmp_path / "out").exists()


def _script_text(out):
    return " ".join(line["text"] for p in sorted(out.glob("clip_*.script.json"))
                    for line in json.loads(p.read_text(encoding="utf-8"))["lines"])


def test_write_script_uses_match(burst_video, tmp_path):
    match = {"home": "Việt Nam", "away": "Thái Lan", "kickoff": 0}
    pipeline.run(burst_video, tmp_path / "out", top=1, voiceover=True, match=match)
    assert all(name in _script_text(tmp_path / "out") for name in ("Việt Nam", "Thái Lan"))


def test_kickoff_after_clip_no_minute(burst_video, tmp_path):
    pipeline.run(burst_video, tmp_path / "out", top=1, voiceover=True, match={"kickoff": 9999})
    assert "Phút" not in _script_text(tmp_path / "out")


@pytest.fixture
def fakes(monkeypatch):
    calls = {"run": [], "meta": [], "entries": [{"file": "clip_01.mp4"}]}

    def fake_run(*a, **kw):
        calls["run"].append(kw)
        return calls["entries"]

    def fake_meta(out_dir, match=None, backend="template"):
        calls["meta"].append((out_dir, match, backend)) if calls["run"] else pytest.fail("meta before run")

    monkeypatch.setattr(cli, "run", fake_run)
    monkeypatch.setattr(cli.publish, "write_meta", fake_meta)
    monkeypatch.setattr(cli.voiceover, "default_synthesizer", lambda: None)
    return calls


def _cut(tmp_path, *extra):
    return cli.main(["cut", "v.mp4", "--out", str(tmp_path / "o"), *extra])


@pytest.mark.parametrize("extra, match", [
    ([], None), (["--voiceover", "--home", "Việt Nam", "--kickoff", "0"], {"home": "Việt Nam", "kickoff": 0.0}),
])
def test_cut_match_forwarded_without_meta(fakes, tmp_path, extra, match):
    assert _cut(tmp_path, *extra) == 0
    assert fakes["run"][-1]["match"] == match and fakes["meta"] == []


def test_cut_meta_merges_file_and_prints_paths(fakes, tmp_path, capsys):
    f = tmp_path / "f.json"
    f.write_text('{"away": "Y", "competition": "V.League 2026"}', encoding="utf-8")
    assert _cut(tmp_path, "--meta", "--match-info", str(f), "--away", "X") == 0
    out, match = tmp_path / "o", {"away": "X", "competition": "V.League 2026"}
    assert fakes["meta"] == [(str(out), match, "template")] and fakes["run"][-1]["match"] == match
    assert capsys.readouterr().out.splitlines() == [
        str(out / "clip_01.mp4"), str(out / "captions.txt"), str(out / "reel.json")]
    assert _cut(tmp_path, "--meta", "--meta-backend", "llm") == 0 and fakes["meta"][-1][2] == "llm"


NEED = "--home, --away, --competition, --kickoff and --match-info need --meta or --voiceover"


@pytest.mark.parametrize("extra, msg", [(["--home", "X"], NEED), (["--kickoff", "0"], NEED),
                                        (["--match-info", "m.json"], NEED), (["--meta-backend", "llm"], "--meta-backend needs --meta")])
def test_cut_usage_errors(fakes, tmp_path, capsys, extra, msg):
    with pytest.raises(SystemExit) as exc:
        _cut(tmp_path, *extra)
    assert exc.value.code == 2 and fakes["run"] == []
    assert msg in capsys.readouterr().err


def test_cut_missing_match_file(fakes, tmp_path, capsys):
    assert _cut(tmp_path, "--meta", "--match-info", str(tmp_path / "no.json")) == 1
    out, err = capsys.readouterr()
    assert out == "" and err.startswith("sportscut: error: cannot read") and fakes["run"] == []


def test_cut_write_meta_error(fakes, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli.publish, "write_meta", lambda *a, **kw: (_ for _ in ()).throw(ValueError("boom")))
    assert _cut(tmp_path, "--meta") == 1
    assert capsys.readouterr() == ("", "sportscut: error: boom\n")


def test_cut_meta_no_clips_notice(fakes, tmp_path, capsys):
    fakes["entries"] = []
    assert _cut(tmp_path, "--meta") == 0 and fakes["meta"] == []
    assert capsys.readouterr() == ("", "sportscut: notice: no clips were cut; --meta wrote nothing\n")


def test_cut_meta_end_to_end(burst_video, tmp_path, capsys):
    out = tmp_path / "out"
    assert cli.main(["cut", str(burst_video), "--out", str(out), "--top", "1", "--meta", *TEAMS]) == 0
    for entry in json.loads((out / "highlights.json").read_text(encoding="utf-8")):
        assert list(entry)[-3:] == ["title", "caption", "hashtags"] and "#VietNam" in entry["hashtags"]
    assert "#VietNam" in (out / "captions.txt").read_text(encoding="utf-8")
    reel = json.loads((out / "reel.json").read_text(encoding="utf-8"))
    assert reel["title"] == "Tổng hợp highlight: Việt Nam vs Thái Lan"
    assert capsys.readouterr().out.splitlines()[-2:] == [str(out / "captions.txt"), str(out / "reel.json")]
