import json
import os
from pathlib import Path
import shutil
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from sportscut import pipeline
from sportscut.media import MediaError
from sportscut.pipeline import PipelineError


DEFAULT_MAX_UPLOAD_BYTES = 2 * 1024**3
CHUNK_BYTES = 1024 * 1024
INPUT_NAME = "input"
CLIPS_DIR = "clips"

app = FastAPI(title="SportsCut")


def _data_dir() -> Path:
    return Path(os.environ.get("SPORTSCUT_DATA_DIR", "sportscut-data")).resolve()


@app.post("/highlights")
def create_highlights(
    request: Request,
    file: UploadFile = File(...),
    top: int = Form(10, ge=1),
    min_len: float = Form(10, gt=0, allow_inf_nan=False),
    max_len: float = Form(30, gt=0, allow_inf_nan=False),
) -> dict:
    if min_len > max_len:
        raise HTTPException(422, "min_len must be <= max_len")

    job_id = str(uuid.uuid4())
    job_dir = _data_dir() / "jobs" / job_id
    job_dir.mkdir(parents=True)
    input_path = job_dir / INPUT_NAME
    try:
        limit = int(os.environ.get("SPORTSCUT_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES))
        total = 0
        with input_path.open("wb") as destination:
            while chunk := file.file.read(CHUNK_BYTES):
                total += len(chunk)
                if total > limit:
                    raise HTTPException(413, f"upload exceeds {limit} bytes")
                destination.write(chunk)
        entries = pipeline.run(
            input_path, job_dir / CLIPS_DIR,
            top=top, min_len=min_len, max_len=max_len,
        )
    except PipelineError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(400, str(exc).replace(str(input_path), "upload")) from exc
    except MediaError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(500, "processing failed") from exc
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    return {
        "job_id": job_id,
        "highlights": [
            {
                "start": entry["start"],
                "end": entry["end"],
                "score": entry["score"],
                "reason": entry["reason"],
                "clip_url": str(request.url_for(
                    "get_clip", job_id=job_id, name=entry["file"]
                )),
            }
            for entry in entries
        ],
    }


@app.get("/highlights/{job_id}/clips/{name}", name="get_clip")
def get_clip(job_id: str, name: str) -> FileResponse:
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise ValueError
        clips_dir = _data_dir() / "jobs" / job_id / CLIPS_DIR
        entries = json.loads((clips_dir / "highlights.json").read_text())
        if name not in {entry["file"] for entry in entries}:
            raise ValueError
        path = clips_dir / name
        if not path.is_file():
            raise ValueError
    except (ValueError, OSError, json.JSONDecodeError, KeyError, TypeError):
        raise HTTPException(404, "not found") from None
    return FileResponse(path, media_type="video/mp4")
