import json
from importlib import resources
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Annotated, Literal
import uuid

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from sportscut import export, media, pipeline, sources
from sportscut.media import MediaError
from sportscut.models import Segment
from sportscut.pipeline import PipelineError
from sportscut.ranking import parse_events
from sportscut.sources import SourceError


DEFAULT_MAX_UPLOAD_BYTES = 2 * 1024**3
CHUNK_BYTES = 1024 * 1024
INPUT_NAME = "input"
CLIPS_DIR = "clips"
DOWNLOAD_DIR = "download"
JOB_FILE = "job.json"
WEB_DIR = resources.files("sportscut").joinpath("web")

app = FastAPI(title="SportsCut")
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


def _replace_non_finite(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [_replace_non_finite(item) for item in value]
    if isinstance(value, dict):
        return {key: _replace_non_finite(item) for key, item in value.items()}
    return value


@app.exception_handler(RequestValidationError)
def validation_error_response(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = _replace_non_finite(jsonable_encoder(exc.errors()))
    return JSONResponse(status_code=422, content={"detail": errors})

FiniteFloat = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class SegmentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: FiniteFloat
    end: FiniteFloat
    reason: str | None = None
    event: Literal["goal", "save", "red_card", "controversy", "other"] | None = None


class SegmentEdits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    segments: list[SegmentEdit] = Field(max_length=50)


def _data_dir() -> Path:
    return Path(os.environ.get("SPORTSCUT_DATA_DIR", "sportscut-data")).resolve()


class _JobNotFound(Exception):
    pass


def _job_dir(job_id: str) -> Path:
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise _JobNotFound from None
    return _data_dir() / "jobs" / job_id


def _finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _validate_job(job: object) -> dict[str, object]:
    if not isinstance(job, dict) or set(job) != {
        "source_name", "source_url", "duration", "version", "segments"
    }:
        raise _JobNotFound
    source_name, source_url = job["source_name"], job["source_url"]
    if not (
        (isinstance(source_name, str) and source_name and source_url is None)
        or (source_name is None and isinstance(source_url, str) and source_url)
    ):
        raise _JobNotFound
    duration, version, segments = job["duration"], job["version"], job["segments"]
    if not _finite_number(duration) or duration < 0:
        raise _JobNotFound
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise _JobNotFound
    if not isinstance(segments, list):
        raise _JobNotFound
    required = {"start", "end", "score", "reason", "file"}
    optional = {"event", "event_confidence"}
    for entry in segments:
        if (
            not isinstance(entry, dict)
            or not required <= set(entry)
            or not set(entry) - required <= optional
        ):
            raise _JobNotFound
        start, end, score = entry["start"], entry["end"], entry["score"]
        name = entry["file"]
        if not (
            _finite_number(start) and _finite_number(end)
            and 0 <= start < end <= duration
            and (score is None or _finite_number(score))
            and isinstance(entry["reason"], str)
            and isinstance(name, str) and name not in ("", ".", "..")
            and "/" not in name and "\\" not in name
            and ("event" not in entry or isinstance(entry["event"], str))
            and (
                "event_confidence" not in entry
                or _finite_number(entry["event_confidence"])
                and 0 <= entry["event_confidence"] <= 1
            )
        ):
            raise _JobNotFound
    return job


def _load_job(job_id: str) -> tuple[Path, dict[str, object]]:
    job_dir = _job_dir(job_id)
    try:
        job = json.loads((job_dir / JOB_FILE).read_text(encoding="utf-8"))
        return job_dir, _validate_job(job)
    except (OSError, json.JSONDecodeError, UnicodeError, _JobNotFound):
        raise _JobNotFound from None


def _write_job(path: Path, job: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as output:
            temporary = Path(output.name)
            json.dump(job, output, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _highlights(
    request: Request, job_id: str, entries: list[dict]
) -> list[dict]:
    return [
        {
            "start": entry["start"],
            "end": entry["end"],
            "score": entry["score"],
            "reason": entry["reason"],
            "event": entry.get("event", "other"),
            "event_confidence": entry.get("event_confidence", 0.0),
            "clip_url": str(request.url_for(
                "get_clip", job_id=job_id, name=entry["file"]
            )),
        }
        for entry in entries
    ]


def _job_response(
    request: Request, job_id: str, job: dict[str, object],
    entries: list[dict] | None = None,
) -> dict[str, object]:
    if entries is None:
        entries = job["segments"]
        assert isinstance(entries, list)
    return {
        "job_id": job_id,
        "source_name": job["source_name"],
        "source_url": job["source_url"],
        "duration": job["duration"],
        "highlights": _highlights(request, job_id, entries),
    }


def _manifest(job_id: str) -> list[dict]:
    try:
        job_dir = _job_dir(job_id)
        entries = json.loads(
            (job_dir / CLIPS_DIR / "highlights.json").read_text(encoding="utf-8")
        )
        if not isinstance(entries, list) or any(
            not isinstance(entry, dict) or not isinstance(entry.get("file"), str)
            for entry in entries
        ):
            raise _JobNotFound
        return entries
    except (OSError, json.JSONDecodeError, UnicodeError, _JobNotFound):
        raise HTTPException(404, "not found") from None


def _file_chunks(path: Path, start: int, length: int):
    with path.open("rb") as source:
        source.seek(start)
        remaining = length
        while remaining:
            chunk = source.read(min(CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def _byte_range(value: str, total: int) -> tuple[int, int] | None:
    match = re.fullmatch(r"bytes=(\d*)-(\d*)", value)
    if match is None or (not match[1] and not match[2]):
        return None
    if not match[1]:
        suffix = int(match[2])
        if suffix == 0 or total == 0:
            return None
        return max(0, total - suffix), total - 1
    start = int(match[1])
    if start >= total:
        return None
    end = total - 1 if not match[2] else min(int(match[2]), total - 1)
    if end < start:
        return None
    return start, end


@app.get("/", include_in_schema=False)
def get_web_app() -> FileResponse:
    return FileResponse(WEB_DIR.joinpath("index.html"), media_type="text/html")


@app.get("/jobs/{job_id}", include_in_schema=False)
def get_preview_page(job_id: str) -> FileResponse:
    try:
        _load_job(job_id)
    except _JobNotFound:
        raise HTTPException(404, "not found") from None
    return FileResponse(WEB_DIR.joinpath("preview.html"), media_type="text/html")


@app.get("/highlights/{job_id}", name="get_job")
def get_job(
    request: Request, job_id: str, event: str | None = None
) -> dict[str, object]:
    selected_events = None
    if event is not None and event.strip():
        try:
            selected_events = parse_events(event)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    try:
        job_dir = _job_dir(job_id)
    except _JobNotFound:
        raise HTTPException(404, "not found") from None
    if (job_dir / JOB_FILE).exists():
        try:
            _, job = _load_job(job_id)
        except _JobNotFound:
            raise HTTPException(404, "not found") from None
        entries = job["segments"]
        assert isinstance(entries, list)
        if selected_events is not None:
            entries = [
                entry for entry in entries
                if entry.get("event", "other") in selected_events
            ]
        return _job_response(request, job_id, job, entries)
    if (job_dir / INPUT_NAME).exists():
        raise HTTPException(404, "not found")
    entries = _manifest(job_id)
    if selected_events is not None:
        entries = [
            entry for entry in entries
            if entry.get("event", "other") in selected_events
        ]
    return {"job_id": job_id, "highlights": _highlights(request, job_id, entries)}


@app.post("/highlights")
def create_highlights(
    request: Request,
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    top: int = Form(10, ge=1),
    min_len: float = Form(10, gt=0, allow_inf_nan=False),
    max_len: float = Form(30, gt=0, allow_inf_nan=False),
    events: str | None = Form(None),
) -> dict[str, object]:
    if url is not None and not url.strip():
        url = None
    if (file is None) == (url is None):
        raise HTTPException(422, "send exactly one of file or url")
    if min_len > max_len:
        raise HTTPException(422, "min_len must be <= max_len")
    selected_events = None
    if events is not None and events.strip():
        try:
            selected_events = parse_events(events)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    if url is not None:
        try:
            sources.check_youtube_url(url)
        except SourceError as exc:
            raise HTTPException(400, str(exc)) from exc

    job_id = str(uuid.uuid4())
    job_dir = _data_dir() / "jobs" / job_id
    job_dir.mkdir(parents=True)
    input_path = job_dir / INPUT_NAME
    try:
        if file is not None:
            limit = int(os.environ.get("SPORTSCUT_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES))
            total = 0
            with input_path.open("wb") as destination:
                while chunk := file.file.read(CHUNK_BYTES):
                    total += len(chunk)
                    if total > limit:
                        raise HTTPException(413, f"upload exceeds {limit} bytes")
                    destination.write(chunk)
        else:
            downloaded = sources.download_youtube(url, job_dir / DOWNLOAD_DIR)
            os.replace(downloaded, input_path)
            shutil.rmtree(job_dir / DOWNLOAD_DIR, ignore_errors=True)
        entries = pipeline.run(
            input_path, job_dir / CLIPS_DIR,
            top=top, min_len=min_len, max_len=max_len, events=selected_events,
        )
        job: dict[str, object] = {
            "source_name": (file.filename or "upload") if file is not None else None,
            "source_url": url,
            "duration": media.probe_duration(input_path),
            "version": 0,
            "segments": entries,
        }
        _write_job(job_dir / JOB_FILE, job)
    except SourceError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc
    except PipelineError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(400, str(exc).replace(str(input_path), "upload")) from exc
    except MediaError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(500, "processing failed") from exc
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    return _job_response(request, job_id, job)


@app.get("/highlights/{job_id}/source")
def get_source(request: Request, job_id: str):
    try:
        job_dir, _ = _load_job(job_id)
        path = job_dir / INPUT_NAME
        total = path.stat().st_size
        if not path.is_file():
            raise OSError
    except (_JobNotFound, OSError):
        raise HTTPException(404, "not found") from None

    headers = {"Accept-Ranges": "bytes"}
    requested = request.headers.get("range")
    if requested is None:
        headers["Content-Length"] = str(total)
        return StreamingResponse(
            _file_chunks(path, 0, total), media_type="video/mp4", headers=headers
        )
    selected = _byte_range(requested, total)
    if selected is None:
        return Response(
            status_code=416,
            headers={**headers, "Content-Range": f"bytes */{total}"},
        )
    start, end = selected
    headers.update({
        "Content-Range": f"bytes {start}-{end}/{total}",
        "Content-Length": str(end - start + 1),
    })
    return StreamingResponse(
        _file_chunks(path, start, end - start + 1), status_code=206,
        media_type="video/mp4", headers=headers,
    )


@app.put("/highlights/{job_id}/segments")
def put_segments(request: Request, job_id: str, edits: SegmentEdits):
    try:
        job_dir, job = _load_job(job_id)
    except _JobNotFound:
        raise HTTPException(404, "not found") from None
    duration = job["duration"]
    assert isinstance(duration, (int, float))
    if any(not (0 <= item.start < item.end <= duration) for item in edits.segments):
        raise HTTPException(422, "invalid segment bounds")
    input_path = job_dir / INPUT_NAME
    if not input_path.is_file():
        raise HTTPException(404, "not found")
    version = job["version"]
    assert isinstance(version, int)
    next_version = version + 1
    suffix = f"_v{next_version}"
    segments = [
        Segment(
            item.start,
            item.end,
            None,
            item.reason or "manual",
            event=item.event or "other",
        )
        for item in edits.segments
    ]
    clips_dir = job_dir / CLIPS_DIR
    manifest_path = clips_dir / "highlights.json"
    try:
        previous_manifest = manifest_path.read_bytes()
    except OSError:
        previous_manifest = None
    try:
        export.export_clips(
            input_path, segments, clips_dir, version_suffix=suffix
        )
        entries = json.loads(manifest_path.read_text(encoding="utf-8"))
        new_job = {**job, "version": next_version, "segments": entries}
        _validate_job(new_job)
        _write_job(job_dir / JOB_FILE, new_job)
    except Exception as exc:
        for path in clips_dir.glob(f"clip_*{suffix}.mp4"):
            path.unlink(missing_ok=True)
        if previous_manifest is None:
            manifest_path.unlink(missing_ok=True)
        else:
            manifest_path.write_bytes(previous_manifest)
        if isinstance(exc, MediaError):
            raise HTTPException(500, "processing failed") from exc
        raise
    current_files = {entry["file"] for entry in entries}
    for entry in job["segments"]:
        if entry["file"] not in current_files:
            (clips_dir / entry["file"]).unlink(missing_ok=True)
    return _job_response(request, job_id, new_job)


@app.get("/highlights/{job_id}/clips/{name}", name="get_clip")
def get_clip(job_id: str, name: str) -> FileResponse:
    try:
        job_dir = _job_dir(job_id)
        if (job_dir / JOB_FILE).exists():
            _, job = _load_job(job_id)
            entries = job["segments"]
        else:
            if (job_dir / INPUT_NAME).exists():
                raise _JobNotFound
            entries = _manifest(job_id)
        clips_dir = job_dir / CLIPS_DIR
        if name not in {entry["file"] for entry in entries}:
            raise _JobNotFound
        path = clips_dir / name
        if not path.is_file():
            raise _JobNotFound
    except (_JobNotFound, OSError, KeyError, TypeError):
        raise HTTPException(404, "not found") from None
    return FileResponse(path, media_type="video/mp4")
