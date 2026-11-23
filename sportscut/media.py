import shutil
import subprocess
from pathlib import Path
import numpy as np
SAMPLE_RATE = 16_000
class MediaError(RuntimeError):
    """Any ffmpeg/ffprobe discovery, probing or decoding failure."""
def find_tool(name: str) -> str:
    tool = shutil.which(name)
    if tool is None:
        raise MediaError(f"{name} not found on PATH; install ffmpeg")
    return tool
def _failure_detail(stderr: str | bytes, returncode: int) -> str:
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", errors="replace")
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-1] if lines else f"exit code {returncode}"
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
