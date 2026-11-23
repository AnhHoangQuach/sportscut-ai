import subprocess
import sys
import types
from pathlib import Path

import pytest

from sportscut import sources


VALID_URLS = [
    "https://www.youtube.com/watch?v=abc123",
    "http://youtube.com/watch?v=abc123",
    "https://m.youtube.com/watch?v=abc123",
    "https://youtu.be/abc123",
    "https://WWW.YouTube.com/watch?v=abc123",
]

INVALID_URLS = [
    "", "youtube.com/watch?v=x", "ftp://youtube.com/x", "file:///etc/passwd",
    "https://evil.com/watch?v=x", "https://youtube.com.evil.com/watch?v=x",
    "https://evil.com/?u=youtube.com", "https://youtube.com@evil.com/",
    "https://user:pw@youtube.com/watch?v=x", "https://youtube.com:8080/watch?v=x",
    "https://youtube.com:abc/", "http://127.0.0.1/",
    "http://169.254.169.254/latest/meta-data/", "https://[::1]/",
    "https://music.youtube.com/watch?v=x", "https://youtube.com\\@evil.com/",
    " https://youtu.be/x", "https://youtu.be/x\n", "https://youtu.be/" + "a" * 2048,
    None,
]


@pytest.mark.parametrize("url", VALID_URLS)
def test_check_accepts_youtube_hosts(url):
    assert sources.check_youtube_url(url) is None


@pytest.mark.parametrize("url", INVALID_URLS)
def test_check_rejects_invalid_urls(url):
    with pytest.raises(sources.SourceError, match="^url must be an http\\(s\\) link to youtube.com or youtu.be$"):
        sources.check_youtube_url(url)


@pytest.fixture
def fake_ytdlp(monkeypatch):
    state = {"calls": [], "info": {"extractor_key": "Youtube", "duration": 60}, "bytes": b"mp4"}

    class YoutubeDLError(Exception):
        pass

    class DownloadError(YoutubeDLError):
        pass

    class YoutubeDL:
        def __init__(self, opts):
            state["opts"] = opts
            state["calls"].append(("init", opts))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, **kwargs):
            state["calls"].append(("extract", url, kwargs))
            if state.get("raise_at") == "extract":
                raise DownloadError(state["error"])
            return state["info"]

        def process_ie_result(self, info, **kwargs):
            state["calls"].append(("process", info, kwargs))
            if state.get("raise_at") == "process":
                raise DownloadError(state["error"])
            if state["bytes"] is not None:
                Path(state["opts"]["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(state["bytes"])

    module = types.ModuleType("yt_dlp")
    module.YoutubeDL = YoutubeDL
    module.utils = types.SimpleNamespace(YoutubeDLError=YoutubeDLError, DownloadError=DownloadError)
    monkeypatch.setitem(sys.modules, "yt_dlp", module)
    return state


def test_download_options_and_call_order(fake_ytdlp, tmp_path):
    dest = tmp_path / "new"
    result = sources.download_youtube("https://youtu.be/abc123", dest)
    assert result == dest / "source.mp4"
    assert result.read_bytes() == b"mp4"
    opts = fake_ytdlp["opts"]
    assert opts == {
        "format": sources.FORMAT, "merge_output_format": "mp4", "noplaylist": True,
        "max_filesize": 2147483648, "outtmpl": str(dest / "source.%(ext)s"),
        "quiet": True, "no_warnings": True, "noprogress": True, "cachedir": False,
    }
    assert [call[0] for call in fake_ytdlp["calls"]] == ["init", "extract", "process"]
    assert fake_ytdlp["calls"][1][2] == {"download": False, "process": False}
    assert fake_ytdlp["calls"][2][2] == {"download": True}


@pytest.mark.parametrize(("info", "message"), [
    ({"_type": "playlist", "extractor_key": "Youtube", "duration": 60}, "link must point to a single YouTube video"),
    ({"extractor_key": "YoutubeTab", "duration": 60}, "link must point to a single YouTube video"),
    ({"extractor_key": "Youtube", "duration": 60, "is_live": True}, "live streams are not supported"),
    ({"extractor_key": "Youtube", "duration": 60, "live_status": "is_upcoming"}, "live streams are not supported"),
    ({"extractor_key": "Youtube"}, "video length is unknown"),
    ({"extractor_key": "Youtube", "duration": 10801}, "video is longer than 3 hours"),
])
def test_download_rejects_guards(fake_ytdlp, tmp_path, info, message):
    fake_ytdlp["info"] = info
    with pytest.raises(sources.SourceError, match=f"^{message}$"):
        sources.download_youtube("https://youtu.be/x", tmp_path / "d")
    assert not any(call[0] == "process" for call in fake_ytdlp["calls"])


def test_duration_at_limit_ok(fake_ytdlp, tmp_path):
    fake_ytdlp["info"]["duration"] = 10800
    assert sources.download_youtube("https://youtu.be/x", tmp_path / "d").is_file()


@pytest.mark.parametrize("stage", ["extract", "process"])
def test_download_error_wrapped_and_path_hidden(fake_ytdlp, tmp_path, stage):
    dest = tmp_path / "secret"
    fake_ytdlp.update(raise_at=stage, error=f"failed inside {dest}")
    with pytest.raises(sources.SourceError) as caught:
        sources.download_youtube("https://youtu.be/x", dest)
    assert str(caught.value).startswith("could not download video: ")
    assert "failed inside download" in str(caught.value)
    assert str(dest) not in str(caught.value)


def test_missing_output(fake_ytdlp, tmp_path):
    fake_ytdlp["bytes"] = None
    with pytest.raises(sources.SourceError, match="^download produced no video file$"):
        sources.download_youtube("https://youtu.be/x", tmp_path / "d")


@pytest.mark.parametrize(("content", "fails"), [(b"123456", True), (b"12345", False)])
def test_size_cap(fake_ytdlp, monkeypatch, tmp_path, content, fails):
    monkeypatch.setattr(sources, "MAX_DOWNLOAD_BYTES", 5)
    fake_ytdlp["bytes"] = content
    if fails:
        with pytest.raises(sources.SourceError, match="^video exceeds 5 bytes$"):
            sources.download_youtube("https://youtu.be/x", tmp_path / "d")
    else:
        assert sources.download_youtube("https://youtu.be/x", tmp_path / "d").is_file()
    assert fake_ytdlp["opts"]["max_filesize"] == 5


def test_missing_extra_validates_first(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "yt_dlp", None)
    with pytest.raises(sources.SourceError, match="^YouTube links need the \\[youtube\\] extra"):
        sources.download_youtube("https://youtu.be/x", tmp_path)
    with pytest.raises(sources.SourceError, match="^url must be"):
        sources.download_youtube("https://evil.com/x", tmp_path)


def test_import_guards():
    api_code = "import sys, sportscut.api; assert 'yt_dlp' not in sys.modules"
    cli_code = "import sys, sportscut.cli; assert all(x not in sys.modules for x in ('fastapi','uvicorn','yt_dlp'))"
    assert subprocess.run([sys.executable, "-c", api_code]).returncode == 0
    assert subprocess.run([sys.executable, "-c", cli_code]).returncode == 0
