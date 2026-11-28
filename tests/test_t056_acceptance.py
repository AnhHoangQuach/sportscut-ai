"""T-056 acceptance: one audio decode and one top-band decode per pipeline run (Tester)."""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from sportscut import media, pipeline

BAND_VF = "fps=1,scale=160:90,format=gray,crop=160:30:0:0"
SPEC = (Path(__file__).parent.parent / "docs" / "superpowers" / "specs"
        / "2026-11-23-t-036-add-ffmpeg-media-helpers-and-synthetic-design.md")
T056_NOTE = (
    "Updated by T-056: extract_audio(path) and sample_top_band(path) keep a one-entry cache each, "
    "keyed by (resolved path, size, mtime_ns), and return read-only arrays (AC5's 'writable' no "
    "longer holds); a changed file or a failed decode is never served from the cache."
)


@pytest.fixture(scope="module")
def mixed_video(tmp_path_factory, require_ffmpeg):
    build_path = Path(__file__).parent / "fixtures" / "eval" / "build.py"
    spec = importlib.util.spec_from_file_location("t056_eval_build", build_path)
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    folder = tmp_path_factory.mktemp("t056") / "mixed"
    folder.mkdir()
    video = folder / "video.mp4"
    build._encode_match("mixed", video)
    return video


@pytest.fixture(autouse=True)
def _reset_caches(monkeypatch):
    monkeypatch.setattr(media, "_audio_cache", None)
    monkeypatch.setattr(media, "_band_cache", None)


class Spy:
    def __init__(self, monkeypatch, video):
        self.video, self.audio, self.band, self.real = str(video), 0, 0, subprocess.run
        monkeypatch.setattr(media.subprocess, "run", self)

    def __call__(self, args, *a, **kw):
        args_list = [str(x) for x in args] if isinstance(args, (list, tuple)) else []
        if "-i" in args_list and args_list[args_list.index("-i") + 1] == self.video:
            self.audio += "f32le" in args_list
            self.band += BAND_VF in args_list
        return self.real(args, *a, **kw)


def _cache_off(monkeypatch):
    monkeypatch.setattr(media, "_cache_key", lambda p: object())


def test_ac1_single_decode_per_run(mixed_video, tmp_path, monkeypatch):
    spy = Spy(monkeypatch, mixed_video)
    pipeline.run(mixed_video, tmp_path / "out")
    assert (spy.audio, spy.band) == (1, 1)
    _cache_off(monkeypatch)
    spy.audio = spy.band = 0
    pipeline.run(mixed_video, tmp_path / "out2")
    assert spy.audio >= 2 and spy.band >= 2, (spy.audio, spy.band)


def test_ac2_byte_identical_manifest(mixed_video, tmp_path, monkeypatch):
    cached = pipeline.run(mixed_video, tmp_path / "out")
    with monkeypatch.context() as m:
        _cache_off(m)
        uncached = pipeline.run(mixed_video, tmp_path / "out2")
    assert (tmp_path / "out" / "highlights.json").read_bytes() == \
        (tmp_path / "out2" / "highlights.json").read_bytes()
    assert cached == uncached
    assert cached == json.loads((tmp_path / "out" / "highlights.json").read_text())


def test_ac3_changed_file_redecodes_in_pipeline(mixed_video, tmp_path, monkeypatch):
    work = tmp_path / "video.mp4"
    shutil.copy2(mixed_video, work)
    spy = Spy(monkeypatch, work)
    pipeline.run(work, tmp_path / "out")
    assert (spy.audio, spy.band) == (1, 1)
    pipeline.run(work, tmp_path / "out_again")
    assert (spy.audio, spy.band) == (1, 1), "unchanged file must be served from the cache"
    st = work.stat()
    os.utime(work, ns=(st.st_atime_ns, st.st_mtime_ns + 5 * 10**9))
    pipeline.run(work, tmp_path / "out2")
    assert (spy.audio, spy.band) == (2, 2)


def test_ac3_size_change_returns_new_data(mixed_video, tmp_path, require_ffmpeg):
    a = tmp_path / "a.mp4"
    shutil.copy2(mixed_video, a)
    first = media.extract_audio(a)
    assert media.extract_audio(a) is first
    # Replace content with a much shorter clip (different size) at the same path.
    subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-y", "-i", str(mixed_video), "-t", "3",
                    "-c", "copy", str(tmp_path / "short.mp4")], check=True)
    os.replace(tmp_path / "short.mp4", a)
    second = media.extract_audio(a)
    assert second is not first and len(second) < len(first)


def test_ac4_readonly_on_real_video(mixed_video):
    for fresh in (True, False):
        audio = media.extract_audio(mixed_video)
        band = media.sample_top_band(mixed_video)
        assert audio.dtype == np.float32 and audio.ndim == 1 and audio.size > 0
        assert band.dtype == np.uint8 and band.ndim == 3 and band.shape[1:] == (30, 160)
        for arr in (audio, band):
            assert arr.flags.writeable is False
            with pytest.raises(ValueError):
                arr[0] = 0


def test_ac5_failure_not_cached_and_errors_beat_cache(mixed_video, tmp_path, monkeypatch):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video at all")
    spy = Spy(monkeypatch, bad)
    for _ in range(2):
        with pytest.raises(media.MediaError, match="ffmpeg failed"):
            media.extract_audio(bad)
        with pytest.raises(media.MediaError, match="ffmpeg failed"):
            media.sample_top_band(bad)
    assert (spy.audio, spy.band) == (2, 2)

    gone = tmp_path / "gone.mp4"
    shutil.copy2(mixed_video, gone)
    media.extract_audio(gone)
    media.sample_top_band(gone)
    monkeypatch.setattr(media.shutil, "which", lambda name: None)
    for fn in (media.extract_audio, media.sample_top_band):
        with pytest.raises(media.MediaError, match=r"^ffmpeg not found on PATH; install ffmpeg$"):
            fn(gone)
    gone.unlink()
    for fn in (media.extract_audio, media.sample_top_band):
        with pytest.raises(media.MediaError, match=rf"^media file not found: {gone}$"):
            fn(gone)


def test_ac6_one_entry_independent_and_relative_path(mixed_video, tmp_path, monkeypatch):
    a, b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    shutil.copy2(mixed_video, a)
    shutil.copy2(mixed_video, b)
    calls = []
    real = subprocess.run
    monkeypatch.setattr(media.subprocess, "run",
                        lambda args, *x, **k: (calls.append(list(args)), real(args, *x, **k))[1])
    media.extract_audio(a), media.extract_audio(b), media.extract_audio(a)
    assert sum("f32le" in c for c in calls) == 3
    calls.clear()
    media.extract_audio(a), media.sample_top_band(a), media.extract_audio(a)
    assert sum("f32le" in c for c in calls) == 0  # a is still the audio entry
    assert sum(BAND_VF in c for c in calls) == 1
    calls.clear()
    monkeypatch.chdir(tmp_path)
    assert media.extract_audio("a.mp4") is media.extract_audio(a.resolve())
    assert media.sample_top_band("a.mp4") is media.sample_top_band(a.resolve())
    assert calls == []


def test_ac8_t036_note():
    paragraphs = [p.strip() for p in SPEC.read_text(encoding="utf-8").split("\n\n") if p.strip()]
    assert T056_NOTE in paragraphs
    assert paragraphs[-1].startswith("Updated by T-004:")
    assert paragraphs.index(T056_NOTE) == len(paragraphs) - 2
