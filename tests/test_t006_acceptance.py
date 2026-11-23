import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sportscut import pipeline, sources
from sportscut.api import app


GOOD_URLS = [
    "https://www.youtube.com/watch?v=abc123",
    "http://youtube.com/watch?v=abc123",
    "https://m.youtube.com/watch?v=abc123",
    "https://youtu.be/abc123",
    "https://WWW.YouTube.com/watch?v=abc123",
]
BAD_URLS = [
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


@pytest.mark.parametrize("url", GOOD_URLS)
def test_t006_acceptance_allowed_url_matrix(url):
    assert sources.check_youtube_url(url) is None


@pytest.mark.parametrize("url", BAD_URLS)
def test_t006_acceptance_rejected_url_matrix(url):
    with pytest.raises(sources.SourceError) as error:
        sources.check_youtube_url(url)
    assert str(error.value) == sources.URL_ERROR


@pytest.fixture
def acceptance_ytdlp(monkeypatch):
    state = {
        "calls": [],
        "info": {"extractor_key": "Youtube", "duration": 60},
        "content": b"video",
    }

    class YoutubeDLError(Exception):
        pass

    class DownloadError(YoutubeDLError):
        pass

    class YoutubeDL:
        def __init__(self, opts):
            state["opts"] = opts
            state["calls"].append(("construct", opts))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, url, **kwargs):
            state["calls"].append(("inspect", url, kwargs))
            if state.get("error_at") == "inspect":
                raise DownloadError(state["error"])
            return state["info"]

        def process_ie_result(self, info, **kwargs):
            state["calls"].append(("download", info, kwargs))
            if state.get("error_at") == "download":
                raise DownloadError(state["error"])
            if state["content"] is not None:
                Path(state["opts"]["outtmpl"].replace("%(ext)s", "mp4")).write_bytes(
                    state["content"]
                )

    fake = types.ModuleType("yt_dlp")
    fake.YoutubeDL = YoutubeDL
    fake.utils = types.SimpleNamespace(
        YoutubeDLError=YoutubeDLError, DownloadError=DownloadError
    )
    monkeypatch.setitem(sys.modules, "yt_dlp", fake)
    return state


def test_t006_acceptance_download_contract(acceptance_ytdlp, tmp_path):
    dest = tmp_path / "not-created-yet"
    result = sources.download_youtube("https://youtu.be/abc123", dest)
    assert result == dest / "source.mp4"
    assert result.read_bytes() == b"video"
    assert acceptance_ytdlp["opts"] == {
        "format": "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]",
        "merge_output_format": "mp4", "noplaylist": True,
        "max_filesize": 2147483648, "outtmpl": str(dest / "source.%(ext)s"),
        "quiet": True, "no_warnings": True, "noprogress": True, "cachedir": False,
    }
    assert [item[0] for item in acceptance_ytdlp["calls"]] == [
        "construct", "inspect", "download"
    ]
    assert acceptance_ytdlp["calls"][1][2] == {"download": False, "process": False}
    assert acceptance_ytdlp["calls"][2][2] == {"download": True}


@pytest.mark.parametrize(("info", "message"), [
    ({"_type": "playlist", "extractor_key": "Youtube", "duration": 60},
     "link must point to a single YouTube video"),
    ({"extractor_key": "YoutubeTab", "duration": 60},
     "link must point to a single YouTube video"),
    ({"extractor_key": "Youtube", "duration": 60, "is_live": True},
     "live streams are not supported"),
    ({"extractor_key": "Youtube", "duration": 60, "live_status": "is_upcoming"},
     "live streams are not supported"),
    ({"extractor_key": "Youtube"}, "video length is unknown"),
    ({"extractor_key": "Youtube", "duration": 10801}, "video is longer than 3 hours"),
])
def test_t006_acceptance_download_guards_do_not_download(
    acceptance_ytdlp, tmp_path, info, message
):
    acceptance_ytdlp["info"] = info
    with pytest.raises(sources.SourceError) as error:
        sources.download_youtube("https://youtu.be/x", tmp_path / "download")
    assert str(error.value) == message
    assert "download" not in [item[0] for item in acceptance_ytdlp["calls"]]


def test_t006_acceptance_duration_size_and_output_boundaries(
    acceptance_ytdlp, monkeypatch, tmp_path
):
    acceptance_ytdlp["info"]["duration"] = 10800
    monkeypatch.setattr(sources, "MAX_DOWNLOAD_BYTES", 5)
    acceptance_ytdlp["content"] = b"12345"
    assert sources.download_youtube("https://youtu.be/x", tmp_path / "exact").is_file()
    assert acceptance_ytdlp["opts"]["max_filesize"] == 5

    acceptance_ytdlp["content"] = b"123456"
    with pytest.raises(sources.SourceError, match="^video exceeds 5 bytes$"):
        sources.download_youtube("https://youtu.be/x", tmp_path / "large")
    acceptance_ytdlp["content"] = None
    with pytest.raises(sources.SourceError, match="^download produced no video file$"):
        sources.download_youtube("https://youtu.be/x", tmp_path / "missing")


@pytest.mark.parametrize("stage", ["inspect", "download"])
def test_t006_acceptance_downloader_error_hides_server_path(
    acceptance_ytdlp, tmp_path, stage
):
    dest = tmp_path / "private-path"
    acceptance_ytdlp.update(error_at=stage, error=f"failed at {dest}")
    with pytest.raises(sources.SourceError) as error:
        sources.download_youtube("https://youtu.be/x", dest)
    assert str(error.value).startswith("could not download video: ")
    assert "failed at download" in str(error.value)
    assert str(dest) not in str(error.value)


def test_t006_acceptance_missing_extra_after_validation(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "yt_dlp", None)
    with pytest.raises(sources.SourceError) as error:
        sources.download_youtube("https://youtu.be/x", tmp_path)
    assert str(error.value) == sources.EXTRA_ERROR
    with pytest.raises(sources.SourceError) as error:
        sources.download_youtube("https://evil.com/x", tmp_path)
    assert str(error.value) == sources.URL_ERROR


@pytest.fixture
def acceptance_client(monkeypatch, tmp_path):
    monkeypatch.setenv("SPORTSCUT_DATA_DIR", str(tmp_path))
    return TestClient(app), tmp_path


def _jobs(root):
    jobs = root / "jobs"
    return set(jobs.iterdir()) if jobs.exists() else set()


@pytest.mark.parametrize("mode", ["both", "neither"])
def test_t006_acceptance_requires_exactly_one_source(
    acceptance_client, monkeypatch, mode
):
    client, root = acceptance_client
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda *_a, **_k: calls.append("pipeline"))
    monkeypatch.setattr(sources, "download_youtube", lambda *_a: calls.append("download"))
    files = {"file": ("x.mp4", b"x")} if mode == "both" else None
    data = {"url": "https://youtu.be/abc123"} if mode == "both" else None
    response = client.post("/highlights", files=files, data=data)
    assert response.status_code == 422
    assert response.json() == {"detail": "send exactly one of file or url"}
    assert calls == [] and _jobs(root) == set()


@pytest.mark.parametrize("blank", ["", "   "])
def test_t006_acceptance_blank_url_is_an_upload(
    acceptance_client, monkeypatch, blank
):
    client, root = acceptance_client
    monkeypatch.setattr(pipeline, "run", lambda *_a, **_k: [])
    response = client.post(
        "/highlights", files={"file": ("short.mp4", b"x")}, data={"url": blank}
    )
    assert response.status_code == 200
    job = root / "jobs" / response.json()["job_id"]
    assert json.loads((job / "job.json").read_text()) == {"source_url": None}
    assert client.get(f"/highlights/{job.name}/clips/job.json").status_code == 404


@pytest.mark.parametrize("url", ["https://evil.com/x", "http://169.254.169.254/"])
def test_t006_acceptance_invalid_url_has_no_side_effects(
    acceptance_client, monkeypatch, url
):
    client, root = acceptance_client
    calls = []
    monkeypatch.setattr(pipeline, "run", lambda *_a, **_k: calls.append("pipeline"))
    monkeypatch.setattr(sources, "download_youtube", lambda *_a: calls.append("download"))
    response = client.post("/highlights", data={"url": url})
    assert response.status_code == 400
    assert response.json() == {"detail": sources.URL_ERROR}
    assert calls == [] and _jobs(root) == set()


def test_t006_acceptance_url_job_layout_and_response(acceptance_client, monkeypatch):
    client, root = acceptance_client
    calls = []

    def download(url, dest):
        calls.append((url, dest))
        dest.mkdir(parents=True)
        output = dest / "source.mp4"
        output.write_bytes(b"synthetic-video")
        return output

    monkeypatch.setattr(sources, "download_youtube", download)
    monkeypatch.setattr(pipeline, "run", lambda *_a, **_k: [])
    url = "https://youtu.be/abc123"
    response = client.post("/highlights", data={"url": url})
    assert response.status_code == 200
    assert set(response.json()) == {"job_id", "highlights"}
    job = root / "jobs" / response.json()["job_id"]
    assert calls == [(url, job / "download")]
    assert (job / "input").read_bytes() == b"synthetic-video"
    assert not (job / "download").exists()
    assert json.loads((job / "job.json").read_text()) == {"source_url": url}


@pytest.mark.parametrize("unexpected", [False, True])
def test_t006_acceptance_download_failure_cleans_job(
    acceptance_client, monkeypatch, unexpected
):
    client, root = acceptance_client
    message = "unexpected" if unexpected else "could not download video: unavailable"
    error_type = RuntimeError if unexpected else sources.SourceError
    monkeypatch.setattr(
        sources, "download_youtube",
        lambda *_a: (_ for _ in ()).throw(error_type(message)),
    )
    monkeypatch.setattr(
        pipeline, "run", lambda *_a, **_k: pytest.fail("pipeline must not run")
    )
    if unexpected:
        with pytest.raises(RuntimeError, match="unexpected"):
            client.post("/highlights", data={"url": "https://youtu.be/x"})
    else:
        response = client.post("/highlights", data={"url": "https://youtu.be/x"})
        assert response.status_code == 400
        assert response.json() == {"detail": message}
    assert _jobs(root) == set()


def test_t006_acceptance_import_packaging_and_documentation():
    api_import = "import sys, sportscut.api; assert 'yt_dlp' not in sys.modules"
    cli_import = (
        "import sys, sportscut.cli; "
        "assert all(x not in sys.modules for x in ('fastapi','uvicorn','yt_dlp'))"
    )
    assert subprocess.run([sys.executable, "-c", api_import], check=False).returncode == 0
    assert subprocess.run([sys.executable, "-c", cli_import], check=False).returncode == 0

    import tomllib
    project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
    assert project["optional-dependencies"]["youtube"] == ["yt-dlp>=2024.8.6"]
    readme = Path("README.md").read_text()
    assert "## API HTTP" in readme
    assert "pip install -e '.[api,youtube]'" in readme
    assert "curl -F url=" in readme
    design = Path(
        "docs/superpowers/specs/2026-11-23-t-005-expose-post-highlights-over-http-with-design.md"
    ).read_text()
    assert "## Updated by T-006" in design
