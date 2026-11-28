"""T-056: one-entry caches for extract_audio and sample_top_band (fake ffmpeg)."""
import os
import subprocess
from pathlib import Path
import numpy as np
import pytest
from sportscut import media
from sportscut.media import MediaError

FUNCS = ["extract_audio", "sample_top_band"]
BAND = media.BAND_W * media.BAND_H
REAL_FIND_TOOL = media.find_tool


def _payload(func: str, fill: int) -> bytes:
    if func == "extract_audio":
        return np.full(8, fill / 10, dtype="<f4").tobytes()
    return bytes([fill]) * (2 * BAND)


class FakeRun:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fill = 1
        self.returncode = 0

    def __call__(self, args, **kwargs):
        self.calls.append(list(args))
        func = "extract_audio" if "f32le" in args else "sample_top_band"
        return subprocess.CompletedProcess(args, self.returncode, _payload(func, self.fill), b"boom")

    def count(self, func: str) -> int:
        return sum(("f32le" in a) == (func == "extract_audio") for a in self.calls)


@pytest.fixture(autouse=True)
def fake(monkeypatch):
    monkeypatch.setattr(media, "_audio_cache", None)
    monkeypatch.setattr(media, "_band_cache", None)
    monkeypatch.setattr(media, "find_tool", lambda n: "/tools/ffmpeg")
    run = FakeRun()
    monkeypatch.setattr(media.subprocess, "run", run)
    return run


@pytest.fixture
def video(tmp_path) -> Path:
    p = tmp_path / "a.mp4"; p.write_bytes(b"video-a")
    return p


@pytest.mark.parametrize("func", FUNCS)
def test_hit_returns_same_readonly_object(func, fake, video):
    first = getattr(media, func)(video)
    second = getattr(media, func)(video)
    assert fake.count(func) == 1 and first is second
    assert not first.flags.writeable
    with pytest.raises(ValueError):
        first[0] = 0
    expected = (np.float32, (8,)) if func == "extract_audio" else (np.uint8, (2, 30, 160))
    assert (first.dtype, first.shape) == expected


@pytest.mark.parametrize("func", FUNCS)
def test_size_change_redecodes(func, fake, video):
    getattr(media, func)(video)
    video.write_bytes(video.read_bytes() + b"x")
    fake.fill = 5
    fresh = getattr(media, func)(video)
    assert fake.count(func) == 2
    assert np.all(fresh == (np.float32(0.5) if func == "extract_audio" else 5))


@pytest.mark.parametrize("func", FUNCS)
def test_mtime_change_redecodes(func, fake, video):
    getattr(media, func)(video)
    st = video.stat()
    os.utime(video, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    getattr(media, func)(video)
    assert fake.count(func) == 2


@pytest.mark.parametrize("func", FUNCS)
def test_failure_not_cached(func, fake, video):
    fake.returncode = 1
    with pytest.raises(MediaError, match="ffmpeg failed for"):
        getattr(media, func)(video)
    fake.returncode = 0
    assert getattr(media, func)(video).size > 0
    assert fake.count(func) == 2


@pytest.mark.parametrize("func", FUNCS)
def test_deleted_cached_file_raises_not_found(func, video):
    getattr(media, func)(video)
    video.unlink()
    with pytest.raises(MediaError, match=f"^media file not found: {video}$"):
        getattr(media, func)(video)


@pytest.mark.parametrize("func", FUNCS)
def test_missing_tool_beats_cache(func, monkeypatch, video, tmp_path):
    getattr(media, func)(video)
    monkeypatch.setattr(media, "find_tool", REAL_FIND_TOOL)
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(MediaError, match="^ffmpeg not found on PATH; install ffmpeg$"):
        getattr(media, func)(video)


@pytest.mark.parametrize("func", FUNCS)
def test_one_entry_lru(func, fake, video, tmp_path):
    other = tmp_path / "b.mp4"; other.write_bytes(b"video-b")
    for p in (video, other, video):
        getattr(media, func)(p)
    assert fake.count(func) == 3


def test_caches_independent(fake, video):
    media.extract_audio(video)
    media.sample_top_band(video)
    media.extract_audio(video)
    assert fake.count("extract_audio") == 1 and fake.count("sample_top_band") == 1


@pytest.mark.parametrize("func", FUNCS)
def test_relative_and_absolute_share_entry(func, fake, video, monkeypatch):
    monkeypatch.chdir(video.parent)
    getattr(media, func)(Path(video.name))
    getattr(media, func)(video.resolve())
    assert fake.count(func) == 1
