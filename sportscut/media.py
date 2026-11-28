import math
import shutil
import subprocess
import tempfile
from pathlib import Path
import numpy as np
SAMPLE_RATE = 16_000
BAND_W = 160
BAND_H = 30
class MediaError(RuntimeError):
    """Any ffmpeg/ffprobe discovery, probing or decoding failure."""
def find_tool(name: str) -> str:
    tool = shutil.which(name)
    if tool is None:
        raise MediaError(f"{name} not found on PATH; install ffmpeg")
    return tool

def require_ffmpeg() -> None:
    """Raise MediaError unless both ffmpeg and ffprobe are on PATH."""
    find_tool("ffmpeg")
    find_tool("ffprobe")

def _failure_detail(stderr: str | bytes, returncode: int) -> str:
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-1] if lines else f"exit code {returncode}"

def has_audio(path: str | Path) -> bool:
    """Return whether a media file contains at least one audio stream."""
    p = Path(path)
    if not p.is_file():
        raise MediaError(f"media file not found: {path}")
    ffprobe = find_tool("ffprobe")
    args = [
        ffprobe, "-v", "error", "-select_streams", "a", "-show_entries",
        "stream=index", "-of", "csv=p=0", "-i", str(p),
    ]
    result = subprocess.run(args, capture_output=True, check=False, text=True)
    if result.returncode:
        detail = _failure_detail(result.stderr, result.returncode)
        raise MediaError(f"ffprobe failed for {path}: {detail}")
    return bool(result.stdout.strip())

def probe_duration(path: str | Path) -> float:
    p = Path(path)
    if not p.is_file():
        raise MediaError(f"media file not found: {path}")
    ffprobe = find_tool("ffprobe")
    args = [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of",
            "default=noprint_wrappers=1:nokey=1", "-i", str(p)]
    result = subprocess.run(args, capture_output=True, check=False, text=True)
    if result.returncode:
        detail = _failure_detail(result.stderr, result.returncode)
        raise MediaError(f"ffprobe failed for {path}: {detail}")
    try:
        return float(result.stdout.strip())
    except ValueError:
        raise MediaError(f"ffprobe returned no duration for {path}") from None


def probe_size(path: str | Path) -> tuple[int, int]:
    """Return the width and height of the first video stream."""
    p = Path(path)
    if not p.is_file():
        raise MediaError(f"media file not found: {path}")
    ffprobe = find_tool("ffprobe")
    args = [
        ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=width,height", "-of", "csv=p=0:s=x", "-i", str(p),
    ]
    result = subprocess.run(args, capture_output=True, check=False, text=True)
    if result.returncode:
        detail = _failure_detail(result.stderr, result.returncode)
        raise MediaError(f"ffprobe failed for {path}: {detail}")
    output = result.stdout.strip()
    if not output:
        raise MediaError(f"no video stream in {path}")
    width, height = output.splitlines()[0].split("x")
    return int(width), int(height)


def extract_audio(path: str | Path) -> np.ndarray:
    p = Path(path)
    if not p.is_file():
        raise MediaError(f"media file not found: {path}")
    ffmpeg = find_tool("ffmpeg")
    args = [ffmpeg, "-v", "error", "-nostdin", "-i", str(p), "-vn", "-ac", "1",
            "-ar", str(SAMPLE_RATE), "-f", "f32le", "pipe:1"]
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode:
        detail = _failure_detail(result.stderr, result.returncode)
        raise MediaError(f"ffmpeg failed for {path}: {detail}")
    return np.frombuffer(result.stdout, dtype="<f4").astype(np.float32)


def sample_top_band(path: str | Path) -> np.ndarray:
    """Sample one tiny grayscale top-band frame per second."""
    p = Path(path)
    if not p.is_file():
        raise MediaError(f"media file not found: {path}")
    ffmpeg = find_tool("ffmpeg")
    args = [
        ffmpeg,
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(p),
        "-an",
        "-vf",
        "fps=1,scale=160:90,format=gray,crop=160:30:0:0",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "pipe:1",
    ]
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode:
        detail = _failure_detail(result.stderr, result.returncode)
        raise MediaError(f"ffmpeg failed for {path}: {detail}")
    frame_size = BAND_W * BAND_H
    count = len(result.stdout) // frame_size
    return np.frombuffer(result.stdout, np.uint8)[: count * frame_size].reshape(
        count, BAND_H, BAND_W
    )


def sample_frames(path: str | Path, fps: float, width: int, height: int) -> np.ndarray:
    """RGB frames sampled at `fps`, scaled to width x height: uint8 array (n, height, width, 3)."""
    p = Path(path)
    if not p.is_file():
        raise MediaError(f"media file not found: {path}")
    args = [
        find_tool("ffmpeg"), "-v", "error", "-nostdin", "-i", str(p), "-an", "-sn",
        "-vf", f"fps={fps},scale={width}:{height}:flags=area",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    return _run_frames(args, path, width, height)


def sample_window(path: str | Path, start: float, duration: float, fps: float, width: int, height: int) -> np.ndarray:
    """RGB frames of [start, start+duration) sampled at fps, scaled to width x height: uint8 (n, height, width, 3)."""
    p = Path(path)
    if not p.is_file():
        raise MediaError(f"media file not found: {path}")
    if not (math.isfinite(start) and math.isfinite(duration)) or start < 0 or duration <= 0:
        raise ValueError("window start must be >= 0 and duration > 0")
    args = [
        find_tool("ffmpeg"), "-v", "error", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
        "-i", str(p), "-an", "-sn", "-vf", f"fps={fps},scale={width}:{height}:flags=area",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
    ]
    return _run_frames(args, path, width, height)


def _run_frames(args: list[str], path: str | Path, width: int, height: int) -> np.ndarray:
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode:
        detail = _failure_detail(result.stderr, result.returncode)
        raise MediaError(f"ffmpeg failed for {path}: {detail}")
    frame = width * height * 3
    n = len(result.stdout) // frame
    return np.frombuffer(result.stdout, np.uint8)[: n * frame].reshape(n, height, width, 3)


def cut_clip(path: str | Path, start: float, end: float, dest: str | Path) -> Path:
    p = Path(path)
    if not p.is_file():
        raise MediaError(f"media file not found: {path}")
    ffmpeg = find_tool("ffmpeg")
    args = [
        ffmpeg, "-v", "error", "-nostdin", "-y", "-ss", f"{start:.3f}",
        "-i", str(p), "-t", f"{end - start:.3f}", "-c:v", "libx264",
        "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
        "-movflags", "+faststart", str(dest),
    ]
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode:
        detail = _failure_detail(result.stderr, result.returncode)
        raise MediaError(f"ffmpeg failed for {path}: {detail}")
    return Path(dest)

def concat_clips(clips: list[str | Path], dest: str | Path) -> Path:
    if not clips:
        raise ValueError("no clips to concatenate")
    for clip in clips:
        if not Path(clip).is_file():
            raise MediaError(f"media file not found: {clip}")

    ffmpeg = find_tool("ffmpeg")
    destination = Path(dest)
    list_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            dir=destination.parent,
            delete=False,
            encoding="utf-8",
        ) as list_file:
            list_path = Path(list_file.name)
            for clip in clips:
                escaped = str(Path(clip).resolve()).replace("'", "'\\''")
                list_file.write(f"file '{escaped}'\n")
        args = [
            ffmpeg, "-v", "error", "-nostdin", "-y", "-f", "concat",
            "-safe", "0", "-i", str(list_path), "-c", "copy", "-movflags",
            "+faststart", str(destination),
        ]
        result = subprocess.run(args, capture_output=True, check=False)
        if result.returncode:
            detail = _failure_detail(result.stderr, result.returncode)
            raise MediaError(f"ffmpeg failed for {dest}: {detail}")
        return destination
    finally:
        if list_path is not None:
            list_path.unlink(missing_ok=True)


def filter_video(path: str | Path, video_filter: str, dest: str | Path) -> Path:
    """Re-encode the video through an ffmpeg -vf filter and copy the audio."""
    p = Path(path)
    if not p.is_file():
        raise MediaError(f"media file not found: {path}")
    ffmpeg = find_tool("ffmpeg")
    args = [
        ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(p),
        "-map", "0:v:0", "-map", "0:a?", "-vf", video_filter,
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", str(dest),
    ]
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode:
        detail = _failure_detail(result.stderr, result.returncode)
        raise MediaError(f"ffmpeg failed for {path}: {detail}")
    return Path(dest)


def _fontconfig_tool(name: str) -> str:
    tool = shutil.which(name)
    if tool is None:
        raise MediaError(f"{name} not found on PATH; install fontconfig to draw captions")
    return tool


def find_font() -> Path:
    """Return a font file that covers Vietnamese, resolved through fontconfig."""
    fc_list = _fontconfig_tool("fc-list")
    fc_match = _fontconfig_tool("fc-match")
    result = subprocess.run(
        [fc_list, "--format", "%{file}\n", ":lang=vi"],
        capture_output=True, check=False, text=True,
    )
    if result.returncode:
        raise MediaError(
            f"fc-list failed: {_failure_detail(result.stderr, result.returncode)}"
        )
    candidates = {
        line.strip() for line in result.stdout.splitlines()
        if line.strip() and Path(line.strip()).is_file()
    }
    if not candidates:
        raise MediaError(
            "no font with Vietnamese support found; install one (for example "
            "DejaVu Sans or Noto Sans) and check with: fc-list :lang=vi"
        )
    ranked = subprocess.run(
        [fc_match, "-s", "--format", "%{file}\n", "sans-serif:lang=vi"],
        capture_output=True, check=False, text=True,
    )
    if not ranked.returncode:
        for line in ranked.stdout.splitlines():
            if line.strip() in candidates:
                return Path(line.strip())
    return Path(sorted(candidates)[0])


def mix_audio(path: str | Path, voice: str | Path, audio_filter: str, dest: str | Path) -> Path:
    """Copy the video of `path` and replace its audio with `audio_filter` applied to [0:a] and [1:a] (voice)."""
    for item in (path, voice):
        if not Path(item).is_file():
            raise MediaError(f"media file not found: {item}")
    args = [
        find_tool("ffmpeg"), "-v", "error", "-nostdin", "-y", "-i", str(path), "-i", str(voice),
        "-filter_complex", audio_filter, "-map", "0:v:0", "-map", "[a]", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dest),
    ]
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(args, capture_output=True, check=False)
    if result.returncode:
        detail = _failure_detail(result.stderr, result.returncode)
        raise MediaError(f"ffmpeg failed for {path}: {detail}")
    return Path(dest)
