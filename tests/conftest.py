"""Synthetic 6 s clip: black/white at 3 s; stereo noise bursts at 2-3 s."""
from pathlib import Path
import shutil
import subprocess
import pytest
@pytest.fixture(scope="session")
def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg and ffprobe are required on PATH")
@pytest.fixture(scope="session")
def synthetic_video(
    require_ffmpeg: None, tmp_path_factory: pytest.TempPathFactory
) -> Path:
    path = tmp_path_factory.mktemp("media") / "synthetic.mp4"
    args = [
        "ffmpeg", "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
        "color=c=black:s=160x120:r=10:d=3", "-f", "lavfi", "-i",
        "color=c=white:s=160x120:r=10:d=3", "-f", "lavfi", "-i",
        "anoisesrc=d=6:c=white:r=44100:a=0.02:seed=42", "-filter_complex",
        "[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a]volume=volume=20:enable='between(t,2,3)',aformat=channel_layouts=stereo[a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "mpeg4", "-q:v", "5",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", "-t", "6", str(path),
    ]
    subprocess.run(args, check=True, capture_output=True)
    return path
