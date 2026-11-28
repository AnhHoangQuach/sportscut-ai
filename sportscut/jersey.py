"""Jersey numbers: a pluggable per-crop reader (numpy digits, or optional EasyOCR) and a confidence-weighted vote."""
from __future__ import annotations

import importlib.util
import math
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np

VOTE_MIN_READS = 3       # reads of the winning number for full vote confidence (tunable 1..5)
INK_CONTRAST = 80        # min |luma - crop median luma| of a number pixel (tunable 40..120)
INK_MIN_PIXELS = 6       # fewer ink pixels = unreadable (fixed)
NUMBER_TOP = 0.6         # only the top 60 % of crop rows is searched (fixed)
DIGIT_MIN_SCORE = 0.6    # min template correlation to accept a read (tunable 0.4..0.9)
OCR_SCALE = 4            # crop upscale factor before OCR (fixed)
OCR_MAX_READS = 4        # OCR reads per touch, evenly spaced over the tracked crops (tunable 2..8)
OCR_MODEL_FILES = ("craft_mlt_25k.pth", "english_g2.pth")
READER_ENV = "SPORTSCUT_NUMBER_READER"
OCR_HINT = "pip install 'sportscut[ocr]' && sportscut download-models --ocr"
DIGIT_FONT = {           # literal copy of tests/fixtures/eval_player/build.py FONT
    "0": ("111", "101", "101", "101", "111"), "1": ("010", "110", "010", "010", "111"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "111", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
}


def _template(n: int) -> np.ndarray:
    rows = ["0".join(DIGIT_FONT[d][r] for d in str(n)) for r in range(5)]
    return np.array([[float(bit) for bit in row] for row in rows])


_TEMPLATES = {n: _template(n) for n in range(1, 100)}


class NumberReader(Protocol):
    name: str
    max_reads: int | None  # None = read every tracked crop

    def read(self, crop: np.ndarray) -> tuple[int | None, float]: ...


def _drop_border_ink(ink: np.ndarray) -> np.ndarray:
    """Remove ink 8-connected through ink to the crop's outer edge (iterative flood fill)."""
    reached = np.zeros_like(ink)
    reached[[0, -1], :] = ink[[0, -1], :]
    reached[:, [0, -1]] |= ink[:, [0, -1]]
    while True:
        padded = np.pad(reached, 1)
        h, w = ink.shape
        grown = np.zeros_like(ink)
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                grown |= padded[dy:dy + h, dx:dx + w]
        grown &= ink
        if (grown == reached).all():
            return ink & ~reached
        reached = grown


def _resample(box: np.ndarray, rows: int, cols: int) -> np.ndarray:
    """Ink fraction per cell of a rows x cols grid laid over the box; empty cells are 0.0."""
    ys = np.round(np.linspace(0, box.shape[0], rows + 1)).astype(int)
    xs = np.round(np.linspace(0, box.shape[1], cols + 1)).astype(int)
    grid = np.zeros((rows, cols))
    for i in range(rows):
        for j in range(cols):
            cell = box[ys[i]:ys[i + 1], xs[j]:xs[j + 1]]
            grid[i, j] = cell.mean() if cell.size else 0.0
    return grid


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    a, b = a.ravel() - a.mean(), b.ravel() - b.mean()
    norm = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return float((a * b).sum()) / norm if norm > 0 else 0.0


class DigitReader:
    """Deterministic template reader for the 3x5 synthetic font, either polarity."""

    name = "digits"
    max_reads: int | None = None

    def read(self, crop: np.ndarray) -> tuple[int | None, float]:
        if crop.ndim != 3 or crop.shape[0] == 0 or crop.shape[1] == 0:
            return None, 0.0
        top = crop[: math.ceil(NUMBER_TOP * crop.shape[0])].astype(np.float64)
        luma = 0.299 * top[..., 0] + 0.587 * top[..., 1] + 0.114 * top[..., 2]
        ink = _drop_border_ink(np.abs(luma - np.median(luma)) >= INK_CONTRAST)
        if int(ink.sum()) < INK_MIN_PIXELS:
            return None, 0.0
        ys, xs = np.nonzero(ink)
        box = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float64)
        grids = {shape: _resample(box, *shape) for shape in {t.shape for t in _TEMPLATES.values()}}
        best_n, best = 0, -math.inf
        for n, template in _TEMPLATES.items():
            score = _correlation(grids[template.shape], template)
            if score > best:
                best_n, best = n, score
        if best < DIGIT_MIN_SCORE:
            return None, 0.0
        return int(best_n), round(float(best), 4)


def vote(reads: Sequence[tuple[int | None, float]]) -> tuple[int | None, float]:
    """Confidence-weighted vote over (number, conf) reads; ties go to the smaller number."""
    weight: dict[int, float] = {}
    count: dict[int, int] = {}
    for number, conf in reads:
        if number is None or not conf > 0:
            continue
        n = int(number)
        weight[n] = weight.get(n, 0.0) + float(conf)
        count[n] = count.get(n, 0) + 1
    if not weight:
        return None, 0.0
    win = min(weight, key=lambda n: (-weight[n], n))
    share = weight[win] / sum(weight.values())
    return win, round(float(share * min(1.0, count[win] / VOTE_MIN_READS)), 4)


def ocr_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "sportscut" / "easyocr"


def ocr_available() -> bool:
    """easyocr importable (find_spec, no import) and every OCR_MODEL_FILES file present in ocr_dir()."""
    return importlib.util.find_spec("easyocr") is not None and all(
        (ocr_dir() / f).is_file() for f in OCR_MODEL_FILES
    )


class OcrReader:
    """EasyOCR digits reader; the model loads on the first read, never downloads."""

    name = "ocr"
    max_reads: int | None = OCR_MAX_READS

    def __init__(self) -> None:
        self._reader = None

    def read(self, crop: np.ndarray) -> tuple[int | None, float]:
        if self._reader is None:
            import easyocr
            self._reader = easyocr.Reader(
                ["en"], gpu=False, model_storage_directory=str(ocr_dir()), download_enabled=False, verbose=False
            )
        image = np.repeat(np.repeat(crop, OCR_SCALE, axis=0), OCR_SCALE, axis=1)
        best: tuple[int | None, float] = (None, 0.0)
        best_conf = -math.inf
        for _box, text, conf in self._reader.readtext(image, allowlist="0123456789", detail=1):
            if re.fullmatch(r"[1-9][0-9]?", str(text)) and float(conf) > best_conf:
                best_conf = float(conf)
                best = (int(text), round(min(1.0, max(0.0, best_conf)), 4))
        return best


def download_ocr_models() -> Path:
    """Download the EasyOCR English models into ocr_dir() and return it (ImportError without the extra)."""
    import easyocr
    d = ocr_dir()
    d.mkdir(parents=True, exist_ok=True)
    easyocr.Reader(["en"], gpu=False, model_storage_directory=str(d), download_enabled=True, verbose=False)
    return d


_ocr_reader: OcrReader | None = None


def _cached_ocr() -> OcrReader:
    global _ocr_reader
    if _ocr_reader is None:
        _ocr_reader = OcrReader()
    return _ocr_reader


def get_reader() -> NumberReader:
    """The number reader chosen by SPORTSCUT_NUMBER_READER (auto | digits | ocr)."""
    value = os.environ.get(READER_ENV, "")
    if value in ("", "auto"):
        return _cached_ocr() if ocr_available() else DigitReader()
    if value == "digits":
        return DigitReader()
    if value == "ocr":
        if ocr_available():
            return _cached_ocr()
        raise ValueError(f"{READER_ENV}=ocr needs the [ocr] extra and its models: {OCR_HINT}")
    raise ValueError("SPORTSCUT_NUMBER_READER must be auto, digits or ocr")
