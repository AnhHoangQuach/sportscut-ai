import ast
import json
import subprocess
from pathlib import Path

import numpy as np
import pytest

from sportscut.cli import main
from sportscut.media import probe_duration
from sportscut.player import PlayerQuery, Touch
from sportscut.reel import make_player_reel, plan_windows, reel_name


@pytest.mark.parametrize(
    "times,duration,pre,post,merge_gap,expected",
    [
        ([12, 10, 30], 100, 3, 2, 4, [(7, 14), (27, 32)]),
        ([10, 19], 100, 3, 2, 4, [(7, 12), (16, 21)]),
        ([1.0], 6.0, 3, 2, 4, [(0.0, 3.0)]),
        ([5.5], 6.0, 1, 2, 0, [(4.5, 6.0)]),
        ([10], 6.0, 3, 2, 4, []),
        ([], 6.0, 3, 2, 4, []),
        ([1, 2], 10, 1, 1, 0, [(0, 3)]),
    ],
)
def test_plan_windows(times, duration, pre, post, merge_gap, expected):
    assert plan_windows(times, duration, pre, post, merge_gap) == expected


def test_plan_windows_merges_when_gap_is_strictly_less():
    assert plan_windows([10, 18.9], 100, 3, 2, 4)[0] == pytest.approx((7, 20.9))


@pytest.mark.parametrize(
    "query,expected",
    [
        (PlayerQuery("RED", 10), "player_red_10.mp4"),
        (PlayerQuery("#FF0000", 7), "player_ff0000_7.mp4"),
    ],
)
def test_reel_name(query, expected):
    assert reel_name(query) == expected


def test_make_player_reel_sorts_touches_and_writes_manifest(monkeypatch, tmp_path):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    touches = [
        Touch(4.5, "red", 10, 0.8, None),
        Touch(1.0004, "red", 10, 0.9, (1, 2, 3, 4)),
        Touch(1.8, "red", 10, 0.7, None),
    ]
    calls = []
    monkeypatch.setattr("sportscut.reel.probe_duration", lambda path: 6.0)
    monkeypatch.setattr("sportscut.player.find_touches", lambda path, query: calls.append((path, query)) or touches)
    monkeypatch.setattr("sportscut.reel.export_clips", lambda video, segments, out: [Path(out) / "clip.mp4"])
    monkeypatch.setattr("sportscut.reel.concat_clips", lambda clips, dest: Path(dest).write_bytes(b"reel") or Path(dest))

    manifest = make_player_reel(video, PlayerQuery("RED", 10), tmp_path / "out", 0.5, 0.5, 0.5)

    assert calls == [(video, PlayerQuery("red", 10))]
    assert manifest == {
        "query": {"team": "red", "number": 10},
        "touches": [
            {"t": 1.0, "team": "red", "number": 10, "confidence": 0.9, "bbox": [1, 2, 3, 4], "start": 0.5, "end": 2.3},
            {"t": 1.8, "team": "red", "number": 10, "confidence": 0.7, "bbox": None, "start": 0.5, "end": 2.3},
            {"t": 4.5, "team": "red", "number": 10, "confidence": 0.8, "bbox": None, "start": 4.0, "end": 5.0},
        ],
        "clips": [{"start": 0.5, "end": 2.3}, {"start": 4.0, "end": 5.0}],
        "total_duration": 2.8,
        "reel": "player_red_10.mp4",
    }
    assert json.loads((tmp_path / "out" / "player.json").read_text()) == manifest


@pytest.mark.parametrize(
    "pre,post,merge_gap,message",
    [
        (-1, 2, 4, "--pre must be >= 0"),
        (3, -1, 4, "--post must be >= 0"),
        (0, 0, 4, "--pre and --post cannot both be 0"),
        (3, 2, -1, "--merge-gap must be >= 0"),
        (float("nan"), 2, 4, "--pre must be >= 0"),
    ],
)
def test_make_player_reel_validates_options_before_io(tmp_path, pre, post, merge_gap, message):
    with pytest.raises(ValueError, match="^" + message.replace("-", "\\-") + "$"):
        make_player_reel(tmp_path / "missing.mp4", PlayerQuery("red", 10), tmp_path / "out", pre, post, merge_gap)
    assert not (tmp_path / "out").exists()


def _gray_mean(video: Path, time: float) -> float:
    output = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(time), "-i", str(video),
         "-frames:v", "1", "-vf", "scale=8:6,format=gray", "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True,
    ).stdout
    return float(np.frombuffer(output, np.uint8).mean())


def test_player_cli_cuts_merges_and_joins(synthetic_video, monkeypatch, tmp_path, capsys):
    touches = [
        Touch(4.5, "red", 10, 0.8, None), Touch(1.0, "red", 10, 0.9, (1, 2, 3, 4)),
        Touch(1.8, "red", 10, 0.7, None),
    ]
    calls = []
    monkeypatch.setattr("sportscut.player.find_touches", lambda video, query: calls.append((video, query)) or touches)
    out = tmp_path / "out"
    code = main(["player", str(synthetic_video), "--team", "RED", "--number", "10", "--out", str(out),
                 "--pre", "0.5", "--post", "0.5", "--merge-gap", "0.5"])
    manifest = json.loads((out / "player.json").read_text())
    assert code == 0 and calls == [(str(synthetic_video), PlayerQuery("red", 10))]
    assert {path.name for path in out.iterdir()} == {"player_red_10.mp4", "player.json"}
    assert manifest["clips"] == [{"start": 0.5, "end": 2.3}, {"start": 4.0, "end": 5.0}]
    assert manifest["total_duration"] == 2.8 and manifest["touches"][0]["bbox"] == [1, 2, 3, 4]
    reel = out / manifest["reel"]
    assert probe_duration(reel) == pytest.approx(2.8, abs=0.5)
    assert _gray_mean(reel, 0.3) < 64 and _gray_mean(reel, 2.2) > 192
    stdout = capsys.readouterr().out
    assert "player_red_10.mp4" in stdout and "3 touches in 2 clips" in stdout


def test_player_cli_default_options_clamp_and_merge(synthetic_video, monkeypatch, tmp_path):
    monkeypatch.setattr("sportscut.player.find_touches", lambda *_: [
        Touch(1.0, "red", 10, 1.0, None), Touch(5.5, "red", 10, 1.0, None)])
    out = tmp_path / "out"
    assert main(["player", str(synthetic_video), "--team", "red", "--number", "10", "--out", str(out)]) == 0
    duration = probe_duration(synthetic_video)
    manifest = json.loads((out / "player.json").read_text())
    assert manifest["clips"] == [{"start": 0.0, "end": round(duration, 3)}]
    assert probe_duration(out / manifest["reel"]) == pytest.approx(duration, abs=0.5)


@pytest.mark.parametrize("touches", [[], [Touch(10, "red", 10, 1.0, None)]])
def test_player_cli_no_clip_windows(synthetic_video, monkeypatch, tmp_path, capsys, touches):
    monkeypatch.setattr("sportscut.player.find_touches", lambda *_: touches)
    out = tmp_path / "out"
    assert main(["player", str(synthetic_video), "--team", "red", "--number", "10", "--out", str(out)]) == 0
    manifest = json.loads((out / "player.json").read_text())
    assert manifest["clips"] == [] and manifest["reel"] is None and not list(out.glob("*.mp4"))
    assert manifest["touches"] == ([] if not touches else [{**touches[0].to_dict(), "start": None, "end": None}])
    assert "no touches found for red 10" in capsys.readouterr().out


@pytest.mark.parametrize("extra", [
    ["--team", "maroon", "--number", "10"], ["--team", "red", "--number", "0"],
    ["--team", "red", "--number", "100"], ["--team", "red", "--number", "10", "--pre", "-1"],
    ["--team", "red", "--number", "10", "--post", "-1"],
    ["--team", "red", "--number", "10", "--merge-gap", "-1"],
    ["--team", "red", "--number", "10", "--pre", "0", "--post", "0"],
])
def test_player_cli_rejects_bad_query_and_options(monkeypatch, tmp_path, capsys, extra):
    monkeypatch.setattr("sportscut.player.find_touches", lambda *_: pytest.fail("detector called"))
    out = tmp_path / "out"
    assert main(["player", str(tmp_path / "missing.mp4"), *extra, "--out", str(out)]) == 2
    assert capsys.readouterr().err.startswith("sportscut player: error:") and not out.exists()


def test_player_cli_usage_missing_video_and_help(monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["player", "video.mp4", "--team", "red", "--number", "abc", "--out", "out"])
    assert exc.value.code == 2
    capsys.readouterr()
    missing = tmp_path / "missing.mp4"
    out = tmp_path / "out"
    monkeypatch.setattr("sportscut.player.find_touches", lambda *_: pytest.fail("detector called"))
    assert main(["player", str(missing), "--team", "red", "--number", "10", "--out", str(out)]) == 1
    assert capsys.readouterr().err == f"sportscut player: error: media file not found: {missing}\n"
    assert main([]) == 0 and "player" in capsys.readouterr().out


def test_reel_module_does_not_import_subprocess():
    tree = ast.parse(Path("sportscut/reel.py").read_text())
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) and
                   (getattr(node, "module", None) == "subprocess" or
                    any(alias.name == "subprocess" for alias in getattr(node, "names", [])))
                   for node in ast.walk(tree))
