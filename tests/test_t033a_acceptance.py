"""T-051 (T-033 slice A) Tester acceptance tests, written from the acceptance criteria."""
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
from sportscut.media import MediaError

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("eval_player_build_t051", ROOT / "tests/fixtures/eval_player/build.py")
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)
GRASS = (40, 140, 60)

def crop_for(n, shirt, ink=None, k=1):
    crop = np.full((36, 20, 3), GRASS, dtype=np.uint8)
    crop[2:34, 2:18] = shirt
    build._draw_number(crop, n, 2, 2)
    if ink is not None:
        crop[(crop == 255).all(axis=2)] = ink
    return np.repeat(np.repeat(crop, k, axis=0), k, axis=1)

@pytest.mark.parametrize("reads, expected", [
    ([(8, .9), (8, .8), (3, .5), (None, 0.0)], (8, 0.5152)),
    ([(10, 1.0)] * 5, (10, 1.0)),
    ([(7, .5), (9, .5)], (7, 0.1667)),
    ([(9, .5), (7, .5)], (7, 0.1667)),                      # tie -> smaller n regardless of order
    ([(9, .5), (4, .25), (4, .25)], (4, 0.3333)),           # equal W -> smaller n wins, conf scaled by 2/3 reads
    ([(5, -1.0), (6, .5)], (6, 0.3333)),                    # non-positive conf is ignored
    ([], (None, 0.0)),
    ([(None, 0.0)] * 3, (None, 0.0)),
    ([(4, 0.0)], (None, 0.0)),
])
def test_ac1_vote_examples(reads, expected):
    assert jersey.vote(reads) == expected

def test_ac1_vote_numpy_inputs_return_python_types():
    number, conf = jersey.vote([(np.int64(8), np.float64(.9))])
    assert type(number) is int and number == 8
    assert type(conf) is float and 0.0 <= conf <= 1.0

def test_ac2_reader_identity_and_font():
    assert jersey.DigitReader().name == "digits"
    assert jersey.DigitReader.max_reads is None
    assert jersey.DIGIT_FONT == build.FONT

@pytest.mark.parametrize("k", [1, 2, 3])
@pytest.mark.parametrize("team", sorted(build.TEAM_RGB))
def test_ac2_reads_every_number(team, k):
    reader = jersey.DigitReader()
    wrong = []
    for n in range(1, 100):
        number, conf = reader.read(crop_for(n, build.TEAM_RGB[team], k=k))
        if not (type(number) is int and number == n and type(conf) is float and conf >= jersey.DIGIT_MIN_SCORE):
            wrong.append((n, number, conf))
    assert wrong == []

@pytest.mark.parametrize("n", [3, 8, 10, 23, 99])
def test_ac3_dark_numbers_on_light_shirt(n):
    number, conf = jersey.DigitReader().read(crop_for(n, (235, 235, 235), ink=(20, 20, 20), k=3))
    assert (number, type(number)) == (n, int) and conf >= jersey.DIGIT_MIN_SCORE

def _blank_shirt():
    crop = np.full((36, 20, 3), GRASS, dtype=np.uint8)
    crop[2:34, 2:18] = build.TEAM_RGB["red"]
    return crop

@pytest.mark.parametrize("crop", [
    _blank_shirt(),
    np.full((36, 20, 3), GRASS, dtype=np.uint8),
    np.zeros((36, 20, 3), dtype=np.uint8),
    np.zeros((0, 10, 3), dtype=np.uint8),
    np.zeros((0, 5, 3), dtype=np.uint8),
    np.zeros((5, 0, 3), dtype=np.uint8),
    np.zeros((36, 20), dtype=np.uint8),                    # not 3-D
], ids=["red-blank", "grass", "black", "0x10", "0x5", "5x0", "2d"])
def test_ac3_unreadable_crops(crop):
    result = jersey.DigitReader().read(crop)
    assert result == (None, 0.0) and result[0] is None and type(result[1]) is float

def test_ac3_read_is_deterministic():
    crop = crop_for(47, build.TEAM_RGB["blue"])
    reader = jersey.DigitReader()
    first = reader.read(crop)
    assert first == reader.read(crop) == jersey.DigitReader().read(crop.copy())
    assert first[0] == 47

def test_ac4_constants_protocol_and_no_ocr():
    assert (jersey.VOTE_MIN_READS, jersey.INK_CONTRAST, jersey.INK_MIN_PIXELS,
            jersey.NUMBER_TOP, jersey.DIGIT_MIN_SCORE) == (3, 80, 6, 0.6, 0.6)
    assert typing.Protocol in jersey.NumberReader.__mro__ and jersey.NumberReader._is_protocol
    assert {"name", "max_reads"} <= set(typing.get_type_hints(jersey.NumberReader)) | set(jersey.NumberReader.__annotations__)
    assert callable(getattr(jersey.NumberReader, "read", None))
    assert not [n for n in ("OcrReader", "ocr_available", "download_ocr_models", "READER_ENV") if hasattr(jersey, n)]
    source = Path(jersey.__file__).read_text()
    assert "easyocr" not in source and "environ" not in source

@pytest.mark.parametrize("value", [None, "ocr", "tesseract", "digits"])
def test_ac4_get_reader_ignores_env(monkeypatch, value):
    monkeypatch.delenv("SPORTSCUT_NUMBER_READER", raising=False)
    if value is not None:
        monkeypatch.setenv("SPORTSCUT_NUMBER_READER", value)
    reader = jersey.get_reader()
    assert isinstance(reader, jersey.DigitReader)
    assert reader.read(crop_for(12, build.TEAM_RGB["red"]))[0] == 12

def test_ac5_top_level_imports_numpy_only():
    tree = ast.parse(Path(jersey.__file__).read_text())
    roots = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add(node.module)
    assert roots <= {"math", "collections.abc", "typing", "numpy", "__future__"}, roots

def test_ac5_fresh_import_does_not_load_player_media_or_ocr():
    code = ("import sys, sportscut.jersey; "
            "print(sorted(m for m in ('sportscut.player','sportscut.media','easyocr') if m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"

@pytest.fixture(scope="module")
def hidden_clip(require_ffmpeg, tmp_path_factory):
    out = tmp_path_factory.mktemp("t051_eval_player")
    build.build_all(out)
    return out / "number_hidden" / "clip.mp4"

def test_ac6_window_decodes_and_matches_sample_frames(hidden_clip):
    assert hidden_clip.is_file()
    win = media.sample_window(hidden_clip, 2.0, 1.0, 5, 640, 360)
    assert win.dtype == np.uint8 and win.shape[1:] == (360, 640, 3) and 4 <= win.shape[0] <= 6
    frames = media.sample_frames(hidden_clip, 5, 640, 360)
    assert np.abs(win[0].astype(int) - frames[10].astype(int)).mean() <= 2
    assert np.abs(win[0].astype(int) - frames[0].astype(int)).mean() > np.abs(win[0].astype(int) - frames[10].astype(int)).mean()

def _forbid_ffmpeg(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("ffmpeg must not be looked up or run")
    monkeypatch.setattr(media, "find_tool", boom)
    monkeypatch.setattr(media.subprocess, "run", boom)

def test_ac7_missing_file(monkeypatch, tmp_path):
    _forbid_ffmpeg(monkeypatch)
    with pytest.raises(MediaError) as info:
        media.sample_window(tmp_path / "nope.mp4", 0, 1, 5, 64, 36)
    assert str(info.value).startswith("media file not found: ")

@pytest.mark.parametrize("start, duration", [(-1, 1), (0, 0), (0, -1), (0, math.nan), (math.nan, 1), (math.inf, 1), (0, math.inf)])
def test_ac7_bad_window(monkeypatch, tmp_path, start, duration):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    _forbid_ffmpeg(monkeypatch)
    with pytest.raises(ValueError, match=r"^window start must be >= 0 and duration > 0$"):
        media.sample_window(clip, start, duration, 5, 640, 360)

def _capture(monkeypatch, code=0):
    calls = []

    def run(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, code, b"", b"boom")
    monkeypatch.setattr(media, "find_tool", lambda name: "/x/" + name)
    monkeypatch.setattr(media.subprocess, "run", run)
    return calls

def test_ac7_args(monkeypatch, tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    calls = _capture(monkeypatch)
    tail = ["-an", "-sn", "-vf", "fps=5,scale=640:360:flags=area", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    media.sample_window(clip, 2, 1, 5, 640, 360)
    assert calls[-1] == ["/x/ffmpeg", "-v", "error", "-nostdin", "-ss", "2.000", "-t", "1.000", "-i", str(clip)] + tail
    media.sample_window(clip, 12.3456, 0.4, 5, 640, 360)
    assert calls[-1][4:8] == ["-ss", "12.346", "-t", "0.400"] and calls[-1].index("-ss") < calls[-1].index("-i")
    media.sample_frames(clip, 5, 640, 360)
    assert calls[-1] == ["/x/ffmpeg", "-v", "error", "-nostdin", "-i", str(clip)] + tail

def test_ac7_nonzero_return_code(monkeypatch, tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"x")
    _capture(monkeypatch, code=1)
    with pytest.raises(MediaError) as info:
        media.sample_window(clip, 2, 1, 5, 640, 360)
    assert str(info.value).startswith("ffmpeg failed for ")

def test_ac9_t033_spec_appendix():
    text = (ROOT / "docs/superpowers/specs/2026-11-23-t-033-read-jersey-numbers-around-each-touch-design.md").read_text()
    head, sep, section = text.rpartition("\n## Updated by T-051")
    assert sep and head.startswith("# T-033") and "\n## " not in section
    for word in ("media.sample_window", "DigitReader", "vote", "get_reader", "border", "SPORTSCUT_NUMBER_READER",
                 "--min-confidence", "OcrReader", "download-models --ocr"):
        assert word in section, word
