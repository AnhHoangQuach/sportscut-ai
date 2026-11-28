"""T-051: jersey number vote, numpy digits reader and media.sample_window."""
import ast
import importlib.util
import math
import subprocess
import sys
import typing
from pathlib import Path

import numpy as np
import pytest

from sportscut import jersey, media

_spec = importlib.util.spec_from_file_location("eval_player_build_t051", Path(__file__).parent / "fixtures/eval_player/build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)


def test_vote_examples() -> None:
    assert jersey.vote([(8, .9), (8, .8), (3, .5), (None, 0.0)]) == (8, 0.5152)
    assert jersey.vote([(10, 1.0)] * 5) == (10, 1.0)
    assert jersey.vote([(7, .5), (9, .5)]) == (7, 0.1667)
    assert jersey.vote([]) == jersey.vote([(None, 0.0)] * 3) == jersey.vote([(4, 0.0)]) == (None, 0.0)
    number, conf = jersey.vote([(np.int64(8), np.float64(.9))])
    assert type(number) is int and type(conf) is float and 0.0 <= conf <= 1.0


GRASS = (40, 140, 60)


def shirt_crop(n, shirt_rgb, ink=None, k=1) -> np.ndarray:
    crop = np.zeros((36, 20, 3), np.uint8)
    crop[:] = GRASS
    crop[2:34, 2:18] = shirt_rgb
    if n is not None:
        build._draw_number(crop, n, 2, 2)
    if ink is not None:
        crop[(crop == 255).all(axis=2)] = ink
    return np.repeat(np.repeat(crop, k, 0), k, 1)


def test_digit_reader_surface_and_font() -> None:
    assert jersey.DigitReader().name == "digits"
    assert jersey.DigitReader.max_reads is None
    assert jersey.DIGIT_FONT == build.FONT


@pytest.mark.parametrize("k", [1, 2, 3])
@pytest.mark.parametrize("team", ["red", "blue"])
def test_digit_reader_reads_every_number(team: str, k: int) -> None:
    reader = jersey.DigitReader()
    for n in range(1, 100):
        number, conf = reader.read(shirt_crop(n, build.TEAM_RGB[team], k=k))
        assert (number, type(number), type(conf)) == (n, int, float), (n, number, conf)
        assert conf >= jersey.DIGIT_MIN_SCORE


def test_digit_reader_dark_on_light_blank_and_deterministic() -> None:
    reader = jersey.DigitReader()
    for n in (3, 8, 10, 23, 99):
        assert reader.read(shirt_crop(n, (235, 235, 235), ink=(20, 20, 20), k=3))[0] == n
    grass = np.zeros((36, 20, 3), np.uint8)
    grass[:] = GRASS
    dark = np.zeros((36, 20, 3), np.uint8)
    dark[:] = (0, 10, 3)
    blanks = [shirt_crop(None, build.TEAM_RGB["red"]), grass, dark, np.zeros((36, 20), np.uint8),
              np.zeros((0, 5, 3), np.uint8), np.zeros((5, 0, 3), np.uint8)]
    for crop in blanks:
        assert reader.read(crop) == (None, 0.0)
    crop = shirt_crop(47, build.TEAM_RGB["blue"])
    assert reader.read(crop) == reader.read(crop)


@pytest.mark.parametrize("value", [None, "ocr", "tesseract"])
def test_get_reader_ignores_env(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    monkeypatch.setattr(jersey, "ocr_available", lambda: False)
    if value is None:
        monkeypatch.delenv("SPORTSCUT_NUMBER_READER", raising=False)
    else:
        monkeypatch.setenv("SPORTSCUT_NUMBER_READER", value)
    if value is None:
        assert isinstance(jersey.get_reader(), jersey.DigitReader)
    elif value == "ocr":
        with pytest.raises(ValueError, match="download-models --ocr"):
            jersey.get_reader()
    else:
        with pytest.raises(ValueError, match="must be auto, digits or ocr"):
            jersey.get_reader()


def test_constants_and_protocol() -> None:
    assert (jersey.VOTE_MIN_READS, jersey.INK_CONTRAST, jersey.INK_MIN_PIXELS) == (3, 80, 6)
    assert (jersey.NUMBER_TOP, jersey.DIGIT_MIN_SCORE) == (0.6, 0.6)
    assert typing.Protocol in jersey.NumberReader.__mro__
    assert {"name", "max_reads"} <= set(jersey.NumberReader.__annotations__)
    assert callable(jersey.NumberReader.read)
    for name in ("OcrReader", "ocr_available", "download_ocr_models", "READER_ENV"):
        assert hasattr(jersey, name)


def test_jersey_imports_numpy_only() -> None:
    tree = ast.parse(Path(jersey.__file__).read_text())
    roots = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add(node.module)
    assert roots <= {"math", "os", "re", "importlib.util", "pathlib", "collections.abc", "typing", "numpy", "__future__"}, roots
    code = ("import sys, sportscut.jersey; print(sorted(m for m in "
            "('sportscut.player', 'sportscut.media', 'easyocr') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


@pytest.fixture(scope="module")
def hidden_clip(require_ffmpeg: None, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("t051_eval_player")
    build.build_all(out)
    return out / "number_hidden" / "clip.mp4"


def test_sample_window_matches_sample_frames(hidden_clip: Path) -> None:
    win = media.sample_window(hidden_clip, 2.0, 1.0, 5, 640, 360)
    assert win.dtype == np.uint8 and win.shape[1:] == (360, 640, 3) and 4 <= win.shape[0] <= 6
    full = media.sample_frames(hidden_clip, 5, 640, 360)
    assert np.abs(win[0].astype(int) - full[10].astype(int)).mean() <= 2


def _forbid(*_args, **_kwargs):
    raise AssertionError("ffmpeg must not be looked up or run")


@pytest.mark.parametrize("start,duration", [(-1, 1), (0, 0), (0, -1), (0, math.nan), (math.nan, 1), (math.inf, 1)])
def test_sample_window_validation_before_ffmpeg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
                                                 start: float, duration: float) -> None:
    monkeypatch.setattr(media, "find_tool", _forbid)
    monkeypatch.setattr(media.subprocess, "run", _forbid)
    with pytest.raises(media.MediaError, match="^media file not found: "):
        media.sample_window(tmp_path / "missing.mp4", 2.0, 1.0, 5, 640, 360)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    with pytest.raises(ValueError) as info:
        media.sample_window(clip, start, duration, 5, 640, 360)
    assert str(info.value) == "window start must be >= 0 and duration > 0"


def test_sample_window_and_sample_frames_args(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    code = {"rc": 0}

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, code["rc"], b"", b"boom")

    monkeypatch.setattr(media, "find_tool", lambda name: f"/bin/{name}")
    monkeypatch.setattr(media.subprocess, "run", fake_run)
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"x")
    tail = ["-an", "-sn", "-vf", "fps=5,scale=640:360:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    assert media.sample_window(p, 2, 1, 5, 640, 360).shape == (0, 360, 640, 3)
    assert calls[-1] == ["/bin/ffmpeg", "-v", "error", "-nostdin", "-ss", "2.000", "-t", "1.000", "-i", str(p), *tail]
    media.sample_frames(p, 5, 640, 360)
    assert calls[-1] == ["/bin/ffmpeg", "-v", "error", "-nostdin", "-i", str(p), *tail]
    code["rc"] = 1
    with pytest.raises(media.MediaError, match="^ffmpeg failed for "):
        media.sample_window(p, 2, 1, 5, 640, 360)
