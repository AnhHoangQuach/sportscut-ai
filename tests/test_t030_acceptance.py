"""Independent acceptance coverage for T-030's public player-reel behavior."""

import ast
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from sportscut.cli import main
from sportscut.media import MediaError, concat_clips, cut_clip, probe_duration
from sportscut.player import PlayerQuery, Touch
from sportscut.reel import plan_windows, reel_name


def _gray_mean(video: Path, at: float) -> float:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-ss", str(at), "-i", str(video),
         "-frames:v", "1", "-vf", "scale=8:6,format=gray", "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True,
    ).stdout
    assert len(raw) == 48
    return float(np.frombuffer(raw, dtype=np.uint8).mean())


@pytest.mark.parametrize(
    "times,duration,pre,post,gap,expected",
    [
        ([12, 10, 30], 100, 3, 2, 4, [(7, 14), (27, 32)]),
        ([10, 19], 100, 3, 2, 4, [(7, 12), (16, 21)]),
        ([10, 18.9], 100, 3, 2, 4, [(7, 20.9)]),
        ([1.0], 6.0, 3, 2, 4, [(0.0, 3.0)]),
        ([5.5], 6.0, 1, 2, 0, [(4.5, 6.0)]),
        ([10], 6.0, 3, 2, 4, []),
        ([], 6.0, 3, 2, 4, []),
        ([1, 2], 10, 1, 1, 0, [(0, 3)]),
    ],
)
def test_window_planning_and_boundaries_acceptance(times, duration, pre, post, gap, expected):
    actual = plan_windows(times, duration, pre, post, gap)
    assert len(actual) == len(expected)
    assert all(got == pytest.approx(want) for got, want in zip(actual, expected))


def test_public_reel_names_acceptance():
    assert reel_name(PlayerQuery("RED", 10)) == "player_red_10.mp4"
    assert reel_name(PlayerQuery("#FF0000", 7)) == "player_ff0000_7.mp4"


def test_concat_rejects_empty_and_missing_before_tool_lookup_acceptance(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="^no clips to concatenate$"):
        concat_clips([], tmp_path / "out.mp4")
    missing = tmp_path / "missing.mp4"
    monkeypatch.setenv("PATH", "/nonexistent")
    with pytest.raises(MediaError) as exc:
        concat_clips([missing], tmp_path / "out.mp4")
    assert str(exc.value) == f"media file not found: {missing}"


def test_concat_bad_input_and_real_order_acceptance(require_ffmpeg, synthetic_video, tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_text("not media", encoding="utf-8")
    with pytest.raises(MediaError, match=r"^ffmpeg failed for .+: .+"):
        concat_clips([bad], tmp_path / "bad-out.mp4")

    first = cut_clip(synthetic_video, 0.5, 1.5, tmp_path / "a.mp4")
    second = cut_clip(synthetic_video, 4.0, 5.0, tmp_path / "it's.mp4")
    dest = tmp_path / "joined.mp4"
    assert concat_clips([first, second], dest) == dest
    assert probe_duration(dest) == pytest.approx(2.0, abs=0.5)
    assert _gray_mean(dest, 0.3) < 64
    assert _gray_mean(dest, 1.5) > 192
    assert not list(tmp_path.glob("*.txt"))


def test_player_cli_real_reel_and_exact_manifest_acceptance(
    monkeypatch, synthetic_video, tmp_path, capsys
):
    touches = [
        Touch(4.5, "red", 10, 0.8, None),
        Touch(1.0, "red", 10, 0.9, (1, 2, 3, 4)),
        Touch(1.8, "red", 10, 0.7, None),
    ]
    calls = []
    monkeypatch.setattr(
        "sportscut.player.find_touches",
        lambda video, query: calls.append((video, query)) or touches,
    )
    out = tmp_path / "reel"
    rc = main(["player", str(synthetic_video), "--team", "RED", "--number", "10",
               "--out", str(out), "--pre", "0.5", "--post", "0.5",
               "--merge-gap", "0.5"])
    assert rc == 0
    assert calls == [(str(synthetic_video), PlayerQuery("red", 10))]
    assert {p.name for p in out.iterdir()} == {"player_red_10.mp4", "player.json"}
    reel = out / "player_red_10.mp4"
    assert probe_duration(reel) == pytest.approx(2.8, abs=0.5)
    assert _gray_mean(reel, 0.3) < 64 and _gray_mean(reel, 2.2) > 192
    stdout = capsys.readouterr().out
    assert "player_red_10.mp4" in stdout
    assert "3 touches in 2 clips" in stdout
    assert json.loads((out / "player.json").read_text(encoding="utf-8")) == {
        "query": {"team": "red", "number": 10},
        "touches": [
            {"t": 1.0, "team": "red", "number": 10, "confidence": 0.9,
             "bbox": [1, 2, 3, 4], "start": 0.5, "end": 2.3},
            {"t": 1.8, "team": "red", "number": 10, "confidence": 0.7,
             "bbox": None, "start": 0.5, "end": 2.3},
            {"t": 4.5, "team": "red", "number": 10, "confidence": 0.8,
             "bbox": None, "start": 4.0, "end": 5.0},
        ],
        "clips": [{"start": 0.5, "end": 2.3}, {"start": 4.0, "end": 5.0}],
        "total_duration": 2.8,
        "reel": "player_red_10.mp4",
    }


def test_defaults_zero_touches_and_dropped_touch_acceptance(
    monkeypatch, synthetic_video, tmp_path, capsys
):
    out = tmp_path / "default"
    monkeypatch.setattr("sportscut.player.find_touches", lambda *_: [
        Touch(1.0, "red", 10, 1.0, None), Touch(5.5, "red", 10, 1.0, None)])
    assert main(["player", str(synthetic_video), "--team", "red", "--number", "10",
                 "--out", str(out)]) == 0
    manifest = json.loads((out / "player.json").read_text())
    duration = probe_duration(synthetic_video)
    assert manifest["clips"] == [{"start": 0.0, "end": round(duration, 3)}]
    assert probe_duration(out / manifest["reel"]) == pytest.approx(duration, abs=0.5)

    for name, touches in [("empty", []), ("late", [Touch(10, "red", 10, 0.5, None)])]:
        target = tmp_path / name
        monkeypatch.setattr("sportscut.player.find_touches", lambda *_, value=touches: value)
        assert main(["player", str(synthetic_video), "--team", "red", "--number", "10",
                     "--out", str(target)]) == 0
        data = json.loads((target / "player.json").read_text())
        assert data["clips"] == [] and data["reel"] is None and data["total_duration"] == 0.0
        assert not list(target.glob("*.mp4"))
        if touches:
            assert data["touches"][0]["start"] is None and data["touches"][0]["end"] is None
    assert "no touches found for red 10" in capsys.readouterr().out


@pytest.mark.parametrize(
    "extra,code,text",
    [
        (["--team", "maroon", "--number", "10"], 2, "unknown team colour"),
        (["--team", "red", "--number", "0"], 2, "player number must be"),
        (["--team", "red", "--number", "100"], 2, "player number must be"),
        (["--team", "red", "--number", "10", "--pre", "-1"], 2, "sportscut player: error:"),
        (["--team", "red", "--number", "10", "--post", "-1"], 2, "sportscut player: error:"),
        (["--team", "red", "--number", "10", "--merge-gap", "-1"], 2, "sportscut player: error:"),
        (["--team", "red", "--number", "10", "--pre", "0", "--post", "0"], 2,
         "sportscut player: error:"),
    ],
)
def test_invalid_query_and_options_do_no_io_acceptance(monkeypatch, tmp_path, capsys, extra, code, text):
    monkeypatch.setattr("sportscut.player.find_touches", lambda *_: pytest.fail("called detector"))
    out = tmp_path / "out"
    assert main(["player", str(tmp_path / "missing.mp4"), *extra, "--out", str(out)]) == code
    assert text in capsys.readouterr().err
    assert not out.exists()


def test_usage_missing_video_help_and_architecture_acceptance(monkeypatch, tmp_path, capsys):
    out, missing = tmp_path / "out", tmp_path / "missing.mp4"
    monkeypatch.setattr("sportscut.player.find_touches", lambda *_: pytest.fail("called detector"))
    monkeypatch.setenv("PATH", "/nonexistent")
    assert main(["player", str(missing), "--team", "red", "--number", "10",
                 "--out", str(out)]) == 1
    assert capsys.readouterr().err == f"sportscut player: error: media file not found: {missing}\n"
    assert not out.exists()
    with pytest.raises(SystemExit) as exc:
        main(["player", "x", "--team", "red", "--number", "abc", "--out", "x"])
    assert exc.value.code == 2
    assert main([]) == 0
    assert "player" in capsys.readouterr().out
    tree = ast.parse(Path("sportscut/reel.py").read_text(encoding="utf-8"))
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) and
                   ((isinstance(n, ast.ImportFrom) and n.module == "subprocess") or
                    (isinstance(n, ast.Import) and any(a.name == "subprocess" for a in n.names)))
                   for n in ast.walk(tree))
