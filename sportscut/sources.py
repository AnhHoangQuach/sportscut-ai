from pathlib import Path
from urllib.parse import urlsplit


ALLOWED_HOSTS = frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"})
MAX_URL_LENGTH = 2048
MAX_DURATION_SECONDS = 3 * 3600
MAX_DOWNLOAD_BYTES = 2 * 1024**3
FORMAT = "bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]"
OUTPUT_NAME = "source.mp4"
URL_ERROR = "url must be an http(s) link to youtube.com or youtu.be"
EXTRA_ERROR = "YouTube links need the [youtube] extra: pip install 'sportscut[youtube]'"


class SourceError(Exception):
    """The video source (link or download) is invalid or failed."""


def check_youtube_url(url: str) -> None:
    if (not isinstance(url, str) or not url or len(url) > MAX_URL_LENGTH or
            any(ord(char) <= 0x20 or ord(char) == 0x7f or char == "\\" for char in url)):
        raise SourceError(URL_ERROR)
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise SourceError(URL_ERROR) from exc
    if (parts.scheme.lower() not in {"http", "https"} or
            parts.username is not None or parts.password is not None or
            port is not None or parts.hostname not in ALLOWED_HOSTS):
        raise SourceError(URL_ERROR)


def download_youtube(url: str, dest_dir: str | Path) -> Path:
    check_youtube_url(url)
    try:
        import yt_dlp
    except ImportError as exc:
        raise SourceError(EXTRA_ERROR) from exc

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": FORMAT,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "max_filesize": MAX_DOWNLOAD_BYTES,
        "outtmpl": str(dest / "source.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "cachedir": False,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
            if (info.get("_type", "video") != "video" or
                    info.get("extractor_key") != "Youtube"):
                raise SourceError("link must point to a single YouTube video")
            if info.get("is_live") or info.get("live_status") in {"is_live", "is_upcoming"}:
                raise SourceError("live streams are not supported")
            duration = info.get("duration")
            if duration is None:
                raise SourceError("video length is unknown")
            if duration > MAX_DURATION_SECONDS:
                raise SourceError("video is longer than 3 hours")
            ydl.process_ie_result(info, download=True)
    except yt_dlp.utils.YoutubeDLError as exc:
        message = str(exc).replace(str(dest), "download")
        raise SourceError("could not download video: " + message) from exc

    path = dest / OUTPUT_NAME
    if not path.is_file():
        raise SourceError("download produced no video file")
    if path.stat().st_size > MAX_DOWNLOAD_BYTES:
        raise SourceError(f"video exceeds {MAX_DOWNLOAD_BYTES} bytes")
    return path
