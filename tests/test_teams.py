import importlib.util
from pathlib import Path

import numpy as np
import pytest

from sportscut import media, player
from sportscut.cli import main
from sportscut.eval_player import evaluate_dir
from sportscut.player import PlayerQuery, Touch

FIELD, RED, DARK_RED, BLUE, ORANGE = (40, 140, 60), (200, 30, 30), (180, 25, 25), (30, 60, 200), (240, 140, 20)


def F(*rgb: int) -> np.ndarray:
    return player.colour_features(np.array([rgb], np.uint8))[0]


def test_colour_features_values() -> None:
    rgb = np.array([[255, 0, 0], [0, 0, 255], [255, 255, 255], [0, 0, 0], [200, 30, 30]], np.uint8)
    got = player.colour_features(rgb)
    assert got.dtype == np.float64 and got.shape == (5, 3)
    np.testing.assert_allclose(got, [[1, 0, 1], [-0.5, -0.866025, 1], [0, 0, 1], [0, 0, 0], [0.85, 0, 0.784314]], atol=1e-5)
    assert tuple(player.TEAM_RGB) == player.TEAM_NAMES
    assert player.TEAM_RGB == {
        "black": (0, 0, 0), "blue": (0, 0, 255), "green": (0, 128, 0), "orange": (255, 165, 0),
        "pink": (255, 105, 180), "purple": (128, 0, 128), "red": (255, 0, 0),
        "sky": (135, 206, 235), "white": (255, 255, 255), "yellow": (255, 255, 0),
    }


def test_kmeans_separates_and_is_deterministic() -> None:
    offsets = np.array([[(i % 5 - 2) * 0.01, (i % 3 - 1) * 0.01, (i % 7 - 3) * 0.005] for i in range(30)])
    a, b = np.array([1.0, 0.0, 1.0]) + offsets, np.array([-0.5, -0.87, 1.0]) + offsets[:20]
    points = np.vstack([a, b])
    centroids, labels = player.kmeans(points, 2)
    assert centroids.shape == (2, 3) and labels.shape == (50,)
    assert len(set(labels[:30])) == 1 and len(set(labels[30:])) == 1 and labels[0] != labels[30]
    assert np.linalg.norm(centroids[labels[0]] - a.mean(axis=0)) < 0.05
    assert np.linalg.norm(centroids[labels[30]] - b.mean(axis=0)) < 0.05
    again = player.kmeans(points, 2)
    assert np.array_equal(centroids, again[0]) and np.array_equal(labels, again[1])
    centroids, labels = player.kmeans(np.array([[1.0, 0.0, 1.0]] * 6 + [[0.0, 1.0, 0.5]] * 4), 3)
    assert centroids.shape == (3, 3) and labels.shape == (10,)


def field_frame() -> np.ndarray:
    frame = np.empty((180, 320, 3), np.uint8)
    frame[:] = FIELD
    return frame


def draw_disc(frame: np.ndarray, x: int, y: int, r: int = 2) -> None:
    yy, xx = np.ogrid[: frame.shape[0], : frame.shape[1]]
    frame[(xx - x) ** 2 + (yy - y) ** 2 <= r * r] = 255


def draw_shirt(frame: np.ndarray, x: int, y: int, colour, digit: bool = True) -> None:
    frame[y : y + 16, x : x + 8] = colour
    if digit:
        frame[y + 6 : y + 8, x + 3 : x + 5] = 255


def shirt_frames(colours, extras: bool = True) -> np.ndarray:
    frames = []
    for i in range(6):
        frame = field_frame()
        for j, colour in enumerate(colours):
            draw_shirt(frame, 12 + 26 * j, 40 + 60 * (j % 2), colour, digit=extras)
        if extras:
            draw_disc(frame, 40 + 10 * i, 150)
        frames.append(frame)
    return np.stack(frames)


def test_team_colours_two_teams_drop_keeper() -> None:
    for extras in (True, False):
        frames = shirt_frames([RED] * 6 + [BLUE] * 4 + [ORANGE], extras=extras)
        colours = player.team_colours(frames)
        assert isinstance(colours, player.TeamColours) and colours.names == ("red", "blue")
        assert len(colours.centroids) == 2 and all(len(c) == 3 for c in colours.centroids)
        assert np.linalg.norm(np.array(colours.centroids[0]) - F(*RED)) < 0.03
        assert player.team_colours(frames) == colours


def test_team_colours_none_cases() -> None:
    assert player.team_colours(shirt_frames([RED] * 6)) is None
    assert player.team_colours(shirt_frames([RED] * 5 + [DARK_RED] * 5)) is None
    grey = np.full((6, 180, 320, 3), 128, np.uint8)
    grey[:, 40:56, 12:20], grey[:, 40:56, 60:68] = RED, BLUE
    assert player.team_colours(grey) is None
    assert player.team_colours(np.zeros((0, 180, 320, 3), np.uint8)) is None


def test_shirt_pixels_mask_box_and_saturation() -> None:
    grey = np.full((180, 320, 3), 128, np.uint8)
    grey[40:56, 12:20] = RED
    assert player.shirt_pixels(grey).shape == player.shirt_pixels(grey, (0, 0, 50, 50)).shape == (0, 3)
    frame = field_frame()
    draw_shirt(frame, 100, 60, RED, digit=False)
    draw_shirt(frame, 200, 60, BLUE, digit=False)
    assert player.shirt_pixels(frame).shape == (2 * 6 * 14, 3)
    inside = player.shirt_pixels(frame, (99, 59, 10, 18))
    assert inside.shape == (6 * 14, 3)
    np.testing.assert_allclose(inside, np.tile(F(*RED), (84, 1)))
    white = field_frame()
    white[60:76, 100:108] = 255
    draw_shirt(white, 200, 60, RED, digit=True)
    pixels = player.shirt_pixels(white)
    assert len(pixels) == 6 * 14 - 4 and np.all(np.hypot(pixels[:, 0], pixels[:, 1]) >= player.TEAM_MIN_SAT)


def test_name_teams_distinct() -> None:
    assert player.name_teams(np.array([F(*RED), F(*BLUE)])) == ("red", "blue")
    assert player.name_teams(np.array([F(*BLUE), F(*RED)])) == ("blue", "red")
    names = player.name_teams(np.array([F(*RED), F(*DARK_RED)]))
    assert len(set(names)) == 2 and "red" in names and set(names) <= set(player.TEAM_NAMES)


def pure_colours() -> "player.TeamColours":
    return player.TeamColours((tuple(F(255, 0, 0)), tuple(F(0, 0, 255))), ("red", "blue"))


def test_team_of_majority_and_none() -> None:
    frame = field_frame()
    draw_shirt(frame, 100, 60, RED)
    draw_shirt(frame, 200, 60, BLUE)
    colours = player.team_colours(np.stack([frame] * 6))
    assert colours is not None
    assert player.team_of(frame, (99, 59, 10, 18), colours) == "red"
    assert player.team_of(frame, (199, 59, 10, 18), colours) == "blue"
    mixed = field_frame()  # mostly blue box with a few red pixels: majority wins
    mixed[60:76, 100:108], mixed[61:63, 101:107] = BLUE, RED
    assert player.team_of(mixed, (99, 59, 10, 18), colours) == "blue"
    assert player.team_of(frame, (10, 120, 20, 20), colours) is None
    assert player.team_of(frame, (99, 59, 10, 18), None) is None


def test_pick_team_mapping_and_tie() -> None:
    C = pure_colours()
    assert [player.pick_team(t, C) for t in ("blue", "red", "#ff0000", "orange", "sky")] == ["blue", "red", "red", "red", "blue"]
    with pytest.raises(ValueError) as error:
        player.pick_team("#ff00ff", C)
    assert str(error.value) == (
        "team colour '#ff00ff' is equally close to both team shirts (red, blue); "
        "use --team red, --team blue or a closer #rrggbb"
    )


OTHER_SHIRTS = [(20, 20, RED), (60, 140, RED), (20, 120, BLUE), (280, 20, BLUE), (280, 140, BLUE)]


def two_team_ball_frames() -> np.ndarray:
    frames = []
    for i in range(15):
        frame = field_frame()
        for x, y, colour in [(150, 60, RED)] + OTHER_SHIRTS:
            draw_shirt(frame, x, y, colour)
        draw_disc(frame, *((154 - 6 * (7 - i), 82) if i <= 7 else (154, 82 + 6 * (i - 7))))
        frames.append(frame)
    return np.stack(frames)


def test_detect_touches_labels_team(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(media, "probe_size", lambda video: (640, 360))
    monkeypatch.setattr(media, "sample_frames", lambda video, fps, w, h: two_team_ball_frames())
    touches, colours = player._analyse("clip.mp4")
    assert colours is not None and set(colours.names) == {"red", "blue"} and len(touches) == 1
    touch = touches[0]
    assert touch.t == 1.4 and touch.team == "red" and touch.number is None and touch.bbox == (300, 120, 16, 32)
    monkeypatch.setattr(player, "_read_numbers", lambda video, touches, reader: [(None, 0.0)] * len(touches))
    assert player.detect_touches("clip.mp4") == touches
    assert player.find_touches("clip.mp4", PlayerQuery("red", 99)) == []
    assert player.find_touches("clip.mp4", PlayerQuery("sky", 1)) == []


def test_find_touches_team_only_single_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    values = [Touch(1, "red", None, 1, None), Touch(2, "blue", None, 1, None), Touch(3, "red", 7, 1, None)]
    calls, result = [], [values, pure_colours()]
    monkeypatch.setattr(player, "_analyse", lambda video: (calls.append(video), tuple(result))[1])
    monkeypatch.setattr(player, "_read_numbers", lambda video, touches, reader: [{1: (10, .9), 2: (3, .9), 3: (7, .9)}[t.t] for t in touches])
    assert player.find_touches("x.mp4", PlayerQuery("red", 10)) == [Touch(1, "red", 10, 1, None)]
    assert calls == ["x.mp4"]
    assert player.find_touches("x.mp4", PlayerQuery("#0000ff", 3)) == [Touch(2, "blue", 3, 1, None)]
    assert player.detect_touches("x.mp4") == [Touch(1, "red", 10, 1, None), Touch(2, "blue", 3, 1, None), values[2]]
    with pytest.raises(ValueError, match="equally close"):
        player.find_touches("x.mp4", PlayerQuery("#ff00ff", 7))
    result[1] = None
    assert player.find_touches("x.mp4", PlayerQuery("red", 10)) == []


def test_player_cli_tie_error(synthetic_video: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(player, "_analyse", lambda video: ([], pure_colours()))
    code = main(["player", str(synthetic_video), "--team", "#ff00ff", "--number", "7", "--out", str(tmp_path / "out")])
    err = capsys.readouterr().err
    assert code == 2 and "sportscut player: error:" in err and "equally close" in err


_spec = importlib.util.spec_from_file_location("eval_player_build_t032", Path(__file__).parent / "fixtures/eval_player/build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)
T031_CLIP_F1 = {"dribble": 1.0, "near_miss": 1.0, "number_hidden": 1.0, "short_passes": 0.9091}


def test_eval_player_team_gate(require_ffmpeg, tmp_path: Path) -> None:
    build.build_all(tmp_path)
    report = evaluate_dir(tmp_path)
    assert report["team_accuracy"] >= 0.95 and report["touch_f1_any"] >= 0.9737
    assert report["f1"] > 0.0 and report["id_accuracy"] >= 0.75 and report["seconds_per_min"] <= 6.0
    for entry in report["per_clip"]:
        assert entry["touch_f1_any"] >= T031_CLIP_F1[entry["clip"]], entry["clip"]
    for name in build.CASES:
        clip = tmp_path / name / "clip.mp4"
        detected = player.detect_touches(clip)
        for label in build.case_labels(name)["players"]:
            for touch in player.find_touches(clip, PlayerQuery(label["team"], label["number"])):
                assert touch in detected and touch.team == label["team"]
    clip = tmp_path / "short_passes" / "clip.mp4"
    red, blue = player.find_touches(clip, PlayerQuery("red", 7)), player.find_touches(clip, PlayerQuery("blue", 4))
    assert red and player.find_touches(clip, PlayerQuery("#c81e1e", 7)) == red
    assert blue and player.find_touches(clip, PlayerQuery("sky", 4)) == blue
