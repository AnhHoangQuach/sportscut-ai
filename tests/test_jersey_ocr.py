"""T-053: optional EasyOCR number reader, SPORTSCUT_NUMBER_READER and download-models --ocr."""
import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np
import pytest

from sportscut import cli, jersey, subtitles
from sportscut.commentary import voiceover

ROOT = Path(__file__).resolve().parents[1]
FAKE = """CALLS, RESULTS, IMAGES = [], [], []
class Reader:
    def __init__(self, *args, **kwargs):
        CALLS.append((args, kwargs))
    def readtext(self, image, **kw):
        IMAGES.append((image, kw))
        return list(RESULTS)
"""
B = [[0, 0], [1, 0], [1, 1], [0, 1]]

@pytest.fixture
def fake_easyocr(tmp_path, monkeypatch):
    (tmp_path / "fake").mkdir()
    (tmp_path / "fake" / "easyocr.py").write_text(FAKE)
    monkeypatch.delitem(sys.modules, "easyocr", raising=False)
    monkeypatch.syspath_prepend(str(tmp_path / "fake"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(jersey, "_ocr_reader", None)
    import easyocr
    yield easyocr
    sys.modules.pop("easyocr", None)

def _models():
    jersey.ocr_dir().mkdir(parents=True, exist_ok=True)
    for name in jersey.OCR_MODEL_FILES:
        (jersey.ocr_dir() / name).touch()

def test_ocr_reader_lazy_load_once(fake_easyocr):
    reader = jersey.OcrReader()
    assert fake_easyocr.CALLS == []
    crop = np.zeros((6, 4, 3), np.uint8)
    for _ in range(3):
        reader.read(crop)
    assert fake_easyocr.CALLS == [((["en"],), {"gpu": False, "model_storage_directory": str(jersey.ocr_dir()),
                                               "download_enabled": False, "verbose": False})]

def test_ocr_reader_scales_crop_and_allowlist(fake_easyocr):
    crop = np.arange(6 * 4 * 3, dtype=np.uint8).reshape(6, 4, 3)
    jersey.OcrReader().read(crop)
    ((image, kw),) = fake_easyocr.IMAGES
    assert image.shape == (24, 16, 3)
    assert np.array_equal(image, np.repeat(np.repeat(crop, 4, 0), 4, 1))
    assert kw == {"allowlist": "0123456789", "detail": 1}

def test_ocr_reader_parses_results(fake_easyocr):
    reader, crop = jersey.OcrReader(), np.zeros((6, 4, 3), np.uint8)
    cases = [([(B, "10", .9), (B, "7", .95), (B, "abc", .99), (B, "123", .99), (B, "07", .99)], (7, 0.95)),
             ([], (None, 0.0)), ([(B, "9", 1.3)], (9, 1.0)), ([(B, "12", .8), (B, "21", .8)], (12, 0.8)),
             ([(B, "0", .9), (B, "5", -0.2)], (5, 0.0))]
    for results, expected in cases:
        fake_easyocr.RESULTS[:] = results
        number, conf = reader.read(crop)
        assert (number, conf) == expected
        assert (number is None or type(number) is int) and type(conf) is float

def test_ocr_reader_identity_constants():
    assert jersey.OcrReader.name == "ocr"
    assert jersey.OcrReader().max_reads == jersey.OCR_MAX_READS == 4
    assert jersey.OCR_SCALE == 4
    assert jersey.OCR_MODEL_FILES == ("craft_mlt_25k.pth", "english_g2.pth")
    assert jersey.READER_ENV == "SPORTSCUT_NUMBER_READER"

def test_ocr_dir_uses_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert jersey.ocr_dir() == tmp_path / "sportscut" / "easyocr"

def test_ocr_available_needs_module_and_both_models(fake_easyocr, monkeypatch):
    _models()
    monkeypatch.setitem(sys.modules, "easyocr", None)
    assert jersey.ocr_available() is False
    monkeypatch.setitem(sys.modules, "easyocr", fake_easyocr)
    (jersey.ocr_dir() / jersey.OCR_MODEL_FILES[1]).unlink()
    assert jersey.ocr_available() is False
    _models()
    assert jersey.ocr_available() is True

@pytest.mark.parametrize("available", [True, False])
@pytest.mark.parametrize("value", [None, "", "auto", "digits", "ocr", "tesseract", "OCR"])
def test_get_reader_env_matrix(fake_easyocr, monkeypatch, value, available):
    if available:
        _models()
    if value is None:
        monkeypatch.delenv("SPORTSCUT_NUMBER_READER", raising=False)
    else:
        monkeypatch.setenv("SPORTSCUT_NUMBER_READER", value)
    assert jersey.ocr_available() is available
    if value in ("tesseract", "OCR"):
        with pytest.raises(ValueError) as err:
            jersey.get_reader()
        assert str(err.value) == "SPORTSCUT_NUMBER_READER must be auto, digits or ocr"
    elif value == "ocr" and not available:
        with pytest.raises(ValueError, match="download-models --ocr") as err:
            jersey.get_reader()
        assert "pip install 'sportscut[ocr]'" in str(err.value)
    else:
        want_ocr = available and value != "digits"
        assert type(jersey.get_reader()) is (jersey.OcrReader if want_ocr else jersey.DigitReader)

def test_get_reader_caches_ocr_instance(fake_easyocr, monkeypatch):
    _models()
    monkeypatch.setenv("SPORTSCUT_NUMBER_READER", "ocr")
    first, second = jersey.get_reader(), jersey.get_reader()
    assert first is second
    first.read(np.zeros((4, 4, 3), np.uint8))
    second.read(np.zeros((4, 4, 3), np.uint8))
    assert len(fake_easyocr.CALLS) == 1

def test_download_ocr_models_with_fake(fake_easyocr):
    assert jersey.download_ocr_models() == jersey.ocr_dir()
    assert jersey.ocr_dir().is_dir()
    assert fake_easyocr.CALLS == [((["en"],), {"gpu": False, "model_storage_directory": str(jersey.ocr_dir()),
                                               "download_enabled": True, "verbose": False})]

@pytest.fixture
def no_other_downloads(monkeypatch):
    monkeypatch.setattr(subtitles, "download_models", lambda: pytest.fail("asr download called"))
    monkeypatch.setattr(voiceover, "download_voice", lambda: pytest.fail("tts download called"))

def test_cli_download_ocr_ok(monkeypatch, capsys, no_other_downloads):
    monkeypatch.setattr(jersey, "download_ocr_models", lambda: Path("/c/ocr"))
    assert cli.main(["download-models", "--ocr"]) == 0
    assert capsys.readouterr().out == "downloaded EasyOCR models to /c/ocr\n"

def test_cli_download_ocr_missing_extra(monkeypatch, capsys, no_other_downloads):
    monkeypatch.setitem(sys.modules, "easyocr", None)
    assert cli.main(["download-models", "--ocr"]) == 1
    assert capsys.readouterr().err == (
        "sportscut download-models: error: needs the [ocr] extra: pip install 'sportscut[ocr]'\n")

def test_cli_download_ocr_failure(monkeypatch, capsys, no_other_downloads):
    monkeypatch.setattr(jersey, "download_ocr_models", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    assert cli.main(["download-models", "--ocr"]) == 1
    assert capsys.readouterr().err == "sportscut download-models: error: offline\n"

def test_cli_download_ocr_and_tts_exit_2(monkeypatch, capsys, no_other_downloads):
    monkeypatch.setattr(jersey, "download_ocr_models", lambda: pytest.fail("ocr download called"))
    with pytest.raises(SystemExit) as err:
        cli.main(["download-models", "--ocr", "--tts"])
    assert err.value.code == 2
    assert "--ocr and --tts cannot be combined" in capsys.readouterr().err
    help_text = subprocess.run([sys.executable, "-m", "sportscut", "download-models", "--help"],
                               cwd=ROOT, capture_output=True, text=True, check=True).stdout
    assert "--ocr" in help_text and "--tts" in help_text

def test_imports_never_load_easyocr():
    code = "import sys, sportscut.jersey, sportscut.player; print('easyocr' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"

def test_pyproject_ocr_extra():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    extras = project["optional-dependencies"]
    assert extras["ocr"] == ["easyocr>=1.7"]
    assert project["dependencies"] == ["numpy>=1.26"]
    assert not any("easyocr" in dep for dep in extras["dev"])

def test_root_conftest_forces_digits():
    assert (ROOT / "conftest.py").is_file()
    assert os.environ["SPORTSCUT_NUMBER_READER"] == "digits"

@pytest.mark.skipif(not jersey.ocr_available(), reason="[ocr] extra not installed")
def test_ocr_timing_budget(require_ffmpeg, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("eval_player_build_t053", ROOT / "tests/fixtures/eval_player/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    from sportscut.eval_player import evaluate_dir
    build.build_all(tmp_path)
    monkeypatch.setenv("SPORTSCUT_NUMBER_READER", "ocr")
    monkeypatch.setattr(jersey, "_ocr_reader", None)
    report = evaluate_dir(tmp_path)
    print(json.dumps(report))
    assert report["seconds_per_min"] <= 6.0
