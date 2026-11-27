import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from sportscut import media, player, reframe
from sportscut.cli import main
from sportscut.eval_player import evaluate_dir
from sportscut.media import MediaError


FIELD = (40, 140, 60)
RED = (200, 30, 30)


def field_frame(w: int = 320, h: int = 180) -> np.ndarray:
    frame = np.empty((h, w, 3), np.uint8)
    frame[:] = FIELD
    return frame


def draw_disc(frame: np.ndarray, x: int, y: int, r: int = 2) -> None:
    yy, xx = np.ogrid[: frame.shape[0], : frame.shape[1]]
    frame[(xx - x) ** 2 + (yy - y) ** 2 <= r * r] = 255


def test_player_blobs_single_rect() -> None:
    frame = field_frame()
    frame[60:76, 100:108] = RED
    assert player.player_blobs(frame) == [(100, 60, 8, 16)]


def test_player_blobs_ignores_ball_and_no_field() -> None:
    frame = field_frame()
    draw_disc(frame, 50, 50)
    assert player.player_blobs(frame) == []

    gray = np.full((180, 320, 3), 128, np.uint8)
    gray[60:76, 100:108] = RED
    assert player.player_blobs(gray) == []

    two = field_frame()
    two[60:76, 100:108] = RED
    two[40:56, 118:126] = RED  # 10 px to the right of the first, higher up
    assert player.player_blobs(two) == [(118, 40, 8, 16), (100, 60, 8, 16)]


def path(points) -> list[tuple[float, float] | None]:
    return [(float(x), float(y)) for x, y in points]


TURN = path([(4 * i, 0) for i in range(8)] + [(28, 4 * (i - 7)) for i in range(8, 15)])


@pytest.fixture(params=[1, 2], autouse=False)
def span(request, monkeypatch: pytest.MonkeyPatch) -> int:
    """Run the hit-list cases with the shipped KICK_SPAN and with the plan's S=2."""
    monkeypatch.setattr(player, "KICK_SPAN", request.param)
    return request.param


def test_find_kicks_straight_none(span: int) -> None:
    assert player.find_kicks(path([(4 * i, 0) for i in range(15)]), 320) == []


def test_find_kicks_turn_peaks_at_turn(span: int) -> None:
    kicks = player.find_kicks(TURN, 320)
    index, strength = max(kicks, key=lambda kick: kick[1])
    assert index == 7 and strength >= 0.5
    assert all(0 < s <= 1 for _, s in kicks)
    assert [i for i, _ in kicks] == sorted(i for i, _ in kicks)


def test_find_kicks_start_from_rest(span: int) -> None:
    hits = path([(100, 50)] * 6 + [(100 + 4 * (i - 5), 50) for i in range(6, 15)])
    assert (5, 1.0) in player.find_kicks(hits, 320)


def test_find_kicks_rest_is_not_a_kick(span: int) -> None:
    hits = path([(4 * min(i, 6), 0) for i in range(15)])  # no movement from sample 7 on
    assert [i for i, _ in player.find_kicks(hits, 320) if i >= 6] == []


def test_find_kicks_near_miss_wobble_none(span: int) -> None:
    angle = np.radians(3.0)
    step = 4 * 1.05
    hits = path([(4 * i, 0) for i in range(8)]
                + [(28 + step * (i - 7) * np.cos(angle), step * (i - 7) * np.sin(angle)) for i in range(8, 15)])
    assert player.find_kicks(hits, 320) == []


def test_find_kicks_gaps_skip(span: int) -> None:
    hits = list(TURN)
    hits[5] = None
    assert {i for i, _ in player.find_kicks(hits, 320)} & {5 - span, 5, 5 + span} == set()
    assert player.find_kicks(TURN[: 2 * span], 320) == []
    assert player.find_kicks([], 320) == []


def touches(*pairs) -> list[player.Touch]:
    return [player.Touch(t, None, None, c, None) for t, c in pairs]


def test_suppress_touches_radius_and_ties() -> None:
    kept = player.suppress_touches(touches((1.0, 0.6), (1.2, 0.9), (1.4, 0.5), (1.6, 0.9), (2.0, 0.7)))
    assert [t.t for t in kept] == [1.2, 2.0]
    assert [t.t for t in player.suppress_touches(touches((1.4, 0.5), (1.0, 0.9)))] == [1.0]
    assert [t.t for t in player.suppress_touches(touches((1.6, 0.5), (1.0, 0.9)))] == [1.0, 1.6]
    assert [t.t for t in player.suppress_touches(touches((1.2, 0.5), (1.0, 0.5)))] == [1.0]
    assert player.suppress_touches([]) == []


def turning_ball_frames() -> np.ndarray:
    frames = []
    for i in range(15):
        frame = field_frame()
        frame[60:76, 100:108] = RED
        x, y = (104 - 6 * (7 - i), 82) if i <= 7 else (104, 82 + 6 * (i - 7))
        draw_disc(frame, x, y)
        frames.append(frame)
    return np.stack(frames)


def test_detect_touches_monkeypatched_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(media, "probe_size", lambda video: (640, 360))

    def fake_sample_frames(video, fps, width, height):
        calls.append((video, fps, width, height))
        return turning_ball_frames()

    monkeypatch.setattr(media, "sample_frames", fake_sample_frames)
    result = player.detect_touches("clip.mp4")
    assert calls == [("clip.mp4", reframe.SAMPLE_HZ, 320, 180)]
    assert len(result) == 1
    touch = result[0]
    assert touch.t == 1.4 and touch.team is None and touch.number is None
    assert 0 < touch.confidence <= 1
    assert touch.bbox == (200, 120, 16, 32)


def test_detect_touches_narrow_video_and_no_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(media, "probe_size", lambda video: (160, 90))

    def fake_sample_frames(video, fps, width, height):
        calls.append((width, height))
        return np.zeros((0, height, width, 3), np.uint8)

    monkeypatch.setattr(media, "sample_frames", fake_sample_frames)
    assert player.detect_touches("small.mp4") == []
    assert calls == [(160, 90)]


def test_detect_touches_no_field_and_missing(synthetic_video: Path) -> None:
    assert player.detect_touches(synthetic_video) == []
    with pytest.raises(MediaError):
        player.detect_touches("missing-x.mp4")


BUILD_PATH = Path(__file__).parent / "fixtures/eval_player/build.py"


def load_build():
    spec = importlib.util.spec_from_file_location("eval_player_build_t031", BUILD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = load_build()


@pytest.fixture(scope="module")
def eval_player_set(require_ffmpeg, tmp_path_factory) -> Path:
    directory = tmp_path_factory.mktemp("eval_player_t031")
    build.build_all(directory)
    return directory


def test_eval_player_gate(eval_player_set: Path) -> None:
    report = evaluate_dir(eval_player_set)
    assert report["touch_f1_any"] >= 0.9
    assert report["f1"] > 0.0
    for name in build.CASES:
        clip = eval_player_set / name / "clip.mp4"
        detected = player.detect_touches(clip)
        for entry in build.case_labels(name)["players"]:
            for touch in player.find_touches(clip, player.PlayerQuery(entry["team"], entry["number"])):
                assert touch in detected and touch.team == entry["team"]


def test_cli_debug_candidates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    for name in ("a", "b"):
        case = tmp_path / name
        case.mkdir()
        (case / "clip.mp4").write_bytes(b"")
        (case / "labels.json").write_text(json.dumps(
            {"players": [{"team": "red", "number": 7}], "touches": [{"t": 1.0, "team": "red", "number": 7}]}))
    fake = {"a": [player.Touch(1.2, None, None, 0.5, (1, 2, 3, 4))], "b": []}
    monkeypatch.setattr(media, "probe_duration", lambda clip: 10.0)
    monkeypatch.setattr(player, "detect_touches", lambda clip: fake[Path(clip).parent.name])
    monkeypatch.setattr(player, "find_touches", lambda clip, query: [])

    assert main(["eval-player", str(tmp_path), "--json", "--debug"]) == 0
    out = capsys.readouterr().out
    assert len(out.splitlines()) == 1
    report = json.loads(out)
    for entry in report["per_clip"]:
        assert list(entry)[-1] == "candidates"
        assert entry["candidates"] == [t.to_dict() for t in player.detect_touches(tmp_path / entry["clip"] / "clip.mp4")]
    assert report["per_clip"][0]["candidates"] == [{"t": 1.2, "team": None, "number": None, "confidence": 0.5, "bbox": [1, 2, 3, 4]}]

    assert main(["eval-player", str(tmp_path), "--json"]) == 0
    plain = json.loads(capsys.readouterr().out)
    assert set(plain) == set(report)
    assert all("candidates" not in entry for entry in plain["per_clip"])
