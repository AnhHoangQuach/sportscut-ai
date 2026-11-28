import dataclasses
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from sportscut import jersey, media, player, reel
from sportscut.cli import main
from sportscut.eval_player import evaluate_dir
from sportscut.player import PlayerQuery, TeamColours, Touch

_spec = importlib.util.spec_from_file_location("eval_player_build_t052", Path(__file__).parent / "fixtures/eval_player/build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)
T = 5.0  # touch time of the moving red 7
SCENES = {  # (number, x, y, number shown) per shirt, drawn in order
    "hidden": lambda t: [(7, round(100 + 30 * t), 150, abs(t - T) > 1 + 1e-9)],  # 6 px per 0.2 s, blank within +-1 s
    "jump": lambda t: [(7, round(100 + 30 * t) + 100 * (t >= T + 1 - 1e-9), 150, abs(t - T) > 1 + 1e-9)],  # +100 px at T+1
    "crossing": lambda t: [(9, 320, 150, True), (7, round(280 + 40 * (t - T)), 150, True)],  # red 7 crosses a static red 9
}


def install(monkeypatch, scene="hidden", calls=None, keep=1.0):
    def sample_window(video, start, duration, fps, width, height):
        assert (width, height) == (640, 360)
        calls is None or calls.append((start, duration))
        frames = np.full((round(duration * fps), 360, 640, 3), (40, 140, 60), np.uint8)
        for k, frame in enumerate(frames):
            t = start + k / fps  # frames are a pure function of absolute time
            for number, x, y, show in SCENES[scene](t):
                frame[y:y + 32, x:x + 16] = (200, 30, 30 + round(t * 5))  # time in the blue channel
                show and build._draw_number(frame, number, x, y)
        return frames[: math.ceil(len(frames) * keep)]
    monkeypatch.setattr(media, "probe_size", lambda video: (640, 360))
    monkeypatch.setattr(media, "sample_window", sample_window)


def recorder(max_reads=None):  # DigitReader that records (crop time, number) of each read
    def read(crop):
        out = jersey.DigitReader().read(crop)
        reads.append(((float(np.median(crop[..., 2])) - 30) / 5, out[0]))
        return out
    return SimpleNamespace(name="recorder", max_reads=max_reads, read=read, reads=(reads := []))


def touch(t, scene="hidden", dx=0):
    _, x, y, _ = SCENES[scene](t)[-1]
    return Touch(t, "red", None, 0.5, (x + dx, y, 16, 32))


def test_player_query_min_confidence() -> None:
    assert PlayerQuery("red", 10) == PlayerQuery("red", 10, player.MIN_CONFIDENCE)
    assert hash(PlayerQuery("red", 10)) == hash(PlayerQuery("red", 10, player.MIN_CONFIDENCE))
    assert type(PlayerQuery("red", 10, 1).min_confidence) is float and PlayerQuery("red", 10, 0).min_confidence == 0.0
    for bad in (-0.1, 1.01, float("nan"), float("inf"), True, "0.5"):
        with pytest.raises(ValueError, match="^min confidence must be between 0 and 1$"):
            PlayerQuery("red", 10, bad)
    assert (player.NUMBER_SPAN, player.NUMBER_WIDTH) == (2.0, 1280) and 0.5 <= player.TRACK_GATE <= 2.0 and 1.2 <= player.TRACK_MERGE <= 1.6 and 0.3 <= player.MIN_CONFIDENCE <= 0.8


@pytest.mark.parametrize("scene", ["hidden", "crossing"])
def test_read_numbers_reads_hidden_number_and_keeps_identity_through_a_crossing(monkeypatch, scene) -> None:
    install(monkeypatch, scene)
    [(number, conf)] = player._read_numbers("x.mp4", [touch(T, scene)], reader := recorder())
    assert number == 7 and conf >= player.MIN_CONFIDENCE
    assert reader.reads and all(n in (7, None) for _, n in reader.reads)


def test_read_numbers_gates_jump_max_reads_missing_bbox_and_windows(monkeypatch) -> None:
    install(monkeypatch, "jump")
    player._read_numbers("x.mp4", [touch(T, "jump")], reader := recorder())
    assert reader.reads and max(t for t, _ in reader.reads) <= T + 0.8 + 1e-6
    install(monkeypatch)
    reader, nobox = recorder(max_reads=2), Touch(T, "red", None, .5, None)
    assert player._read_numbers("x.mp4", [touch(T, dx=200), nobox, touch(T)], reader)[:2] == [(None, 0.0)] * 2
    assert len(reader.reads) == 2
    monkeypatch.setattr(media, "probe_size", lambda *a: pytest.fail("decoded"))
    monkeypatch.setattr(media, "sample_window", lambda *a: pytest.fail("decoded"))
    assert player._read_numbers("x.mp4", [], recorder()) == [] and player._read_numbers("x.mp4", [nobox], recorder()) == [(None, 0.0)]
    for times, n_calls in (((5.0, 6.0), 1), ((5.0, 15.0), 2), (tuple(5.0 + 3 * i for i in range(10)), 2), ((0.4,), 1)):
        install(monkeypatch, calls=(calls := []))
        player._read_numbers("x.mp4", [touch(t) for t in times], recorder())
        assert len(calls) == n_calls and all(d <= player.NUMBER_GROUP_MAX + 0.2 + 1e-6 for _, d in calls)
        assert all(start >= 0 and abs(start * 5 - round(start * 5)) < 1e-6 for start, _ in calls)
    assert calls[0][0] == 0.0
    a, b = touch(T), touch(6.0)
    together = player._read_numbers("x.mp4", [a, b], recorder())
    assert together == player._read_numbers("x.mp4", [a], recorder()) + player._read_numbers("x.mp4", [b], recorder())
    install(monkeypatch, keep=0.5)
    assert len(player._read_numbers("x.mp4", [a, b], recorder())) == 2


def test_detect_and_find_filter_by_number(monkeypatch) -> None:
    COLOURS = TeamColours(((0.85, 0.0, 0.78), (-0.4, -0.5, 0.78)), ("red", "blue"))
    VOTES = {1.0: (10, 0.9), 2.0: (10, 0.9), 3.0: (7, 0.4)}
    B, rep = (10, 10, 16, 32), dataclasses.replace
    ts = [Touch(1.0, "red", None, .5, B), Touch(2.0, "blue", None, .5, B), Touch(3.0, "red", None, .5, B), Touch(4.0, None, None, .5, B)]
    analysed, seen, colours = [], [], [COLOURS]
    monkeypatch.setattr(player, "_analyse", lambda video: (analysed.append(video), (ts, colours[0]))[1])
    monkeypatch.setattr(player, "_read_numbers", lambda video, xs, reader: (seen.append(list(xs)), [VOTES[x.t] for x in xs])[1])
    assert player.find_touches("x", PlayerQuery("red", 10)) == [rep(ts[0], number=10)]
    assert analysed == ["x"] and seen == [[ts[0], ts[2]]]
    assert player.find_touches("x", PlayerQuery("red", 7)) == [] and player.find_touches("x", PlayerQuery("red", 7, 0.3)) == [rep(ts[2], number=7)]
    assert player.find_touches("x", PlayerQuery("#0000ff", 10)) == [rep(ts[1], number=10)] and seen[-1] == [ts[1]]
    seen.clear()
    with pytest.raises(ValueError, match="equally close"):
        player.find_touches("x", PlayerQuery("#ff00ff", 7))
    analysed.clear()
    got = player.detect_touches("x")
    assert analysed == ["x"] and seen == [ts[:3]] and [t.number for t in got] == [10, 10, None, None]
    assert [(t.t, t.team, t.confidence, t.bbox) for t in got] == [(t.t, t.team, t.confidence, t.bbox) for t in ts]
    colours[0], seen[:], analysed[:] = None, [], []
    assert player.find_touches("x", PlayerQuery("red", 10)) == [] and seen == [] and analysed == ["x"]
    monkeypatch.setattr(jersey, "get_reader", lambda: (_ for _ in ()).throw(ValueError("x")))
    for call in (lambda: player.detect_touches("x"), lambda: player.find_touches("x", PlayerQuery("red", 10))):
        with pytest.raises(ValueError, match="^x$"):
            call()
    assert analysed == ["x"]  # the reader is obtained before _analyse


def test_cli_min_confidence(tmp_path, monkeypatch, capsys) -> None:
    clip, out, queries = tmp_path / "clip.mp4", tmp_path / "bad", []
    args = ["player", str(clip), "--team", "blue", "--number", "8", "--out", str(out)]
    assert main(args + ["--min-confidence", "1.5"]) == 2 and not out.exists()
    assert "sportscut player: error: min confidence must be between 0 and 1" in capsys.readouterr().err
    monkeypatch.setattr(reel, "probe_duration", lambda video: 10.0)
    monkeypatch.setattr(player, "find_touches", lambda video, query: queries.append(query) or [])
    assert [main(args + extra) for extra in (["--min-confidence", "0.3"], [])] == [0, 0]
    assert queries == [PlayerQuery("blue", 8, 0.3), PlayerQuery("blue", 8)]
    with pytest.raises(SystemExit):
        main(["player", "--help"])
    assert "--min-confidence" in capsys.readouterr().out


@pytest.fixture(scope="module")
def built(require_ffmpeg, tmp_path_factory):
    build.build_all(root := tmp_path_factory.mktemp("eval_player_t052"))
    return root


def test_eval_player_number_gate(built, tmp_path) -> None:
    r = evaluate_dir(built)
    clips = {e["clip"]: e for e in r["per_clip"]}
    assert r["f1"] >= 0.85 and clips["number_hidden"]["f1"] >= 0.85 and r["id_accuracy"] >= 0.75
    assert r["precision"] > 0.4205 and r["team_accuracy"] >= 0.95 and r["touch_f1_any"] >= 0.9737 and 0 < r["seconds_per_min"] <= 6.0
    floors = {"dribble": 1.0, "near_miss": 1.0, "number_hidden": 1.0, "short_passes": 0.9091}
    assert all(clips[name]["touch_f1_any"] >= floor for name, floor in floors.items()), clips
    for name in build.CASES:
        video, detected = built / name / "clip.mp4", player.detect_touches(built / name / "clip.mp4")
        for label in build.case_labels(name)["players"]:
            q = PlayerQuery(label["team"], label["number"])
            assert all(t in detected and (t.team, t.number) == (q.team, q.number) for t in player.find_touches(video, q))
    assert main(["player", str(built / "number_hidden/clip.mp4"), "--team", "blue", "--number", "8", "--out", str(out := tmp_path / "reel")]) == 0
    got = json.loads((out / "player.json").read_text())["touches"]
    assert all((t["team"], t["number"]) == ("blue", 8) for t in got)
    assert sum(any(abs(t["t"] - x) <= 0.5 for t in got) for x in (4.0, 5.2, 9.0, 14.0)) >= 3


def test_number_gate_can_fail(built, tmp_path, monkeypatch) -> None:
    clip = built / "number_hidden" / "clip.mp4"
    found = [set(player.find_touches(clip, PlayerQuery("blue", 8, c))) for c in (0.0, player.MIN_CONFIDENCE, 1.0)]
    assert found[0] >= found[1] >= found[2]
    with monkeypatch.context() as m:
        m.setattr(jersey, "get_reader", lambda: SimpleNamespace(name="blind", max_reads=None, read=lambda crop: (None, 0.0)))
        r = evaluate_dir(built)
    assert r["f1"] == 0.0 and r["id_accuracy"] == 0.0
    (tmp_path / "number_hidden").symlink_to(built / "number_hidden")
    monkeypatch.setattr(player, "NUMBER_SPAN", 0.4)
    assert evaluate_dir(tmp_path)["per_clip"][0]["f1"] < 0.85


def test_frames_sampled_only_around_touches(built, monkeypatch) -> None:
    frames, window, log = media.sample_frames, media.sample_window, []
    monkeypatch.setattr(media, "sample_frames", lambda *a: (log.append(None), frames(*a))[1])
    monkeypatch.setattr(media, "sample_window", lambda v, s, d, *a: (log.append((s, d)), window(v, s, d, *a))[1])
    for name in build.CASES:
        clip, (_, team, number) = built / name / "clip.mp4", build.CASES[name]["touches"][0]
        q = PlayerQuery("red", 7) if name == "short_passes" else PlayerQuery(team, number)
        touches, colours = player._analyse(clip)
        times = [t.t for t in touches if t.team == player.pick_team(q.team, colours)]
        log.clear()
        assert player.find_touches(clip, q) is not None and log.count(None) == 1 and len(log) > 1
        for s, d in filter(None, log):
            assert s >= 0 and abs(s * 5 - round(s * 5)) < 1e-6
            assert all(any(t - 2.2 - 1e-6 <= x <= t + 2.4 + 1e-6 for t in times) for x in np.linspace(s, s + d, 200))
            assert name != "short_passes" or not s <= 12.0 <= s + d
