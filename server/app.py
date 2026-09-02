from __future__ import annotations

import atexit
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

try:
    from .separation import StemPaths, generate_synthetic_mix, phase_cancel_wav, separate_with_demucs, separator_available
except ImportError:
    from separation import StemPaths, generate_synthetic_mix, phase_cancel_wav, separate_with_demucs, separator_available


ALLOWED_SUFFIXES = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}
MAX_UPLOAD_BYTES = int(os.getenv("KARAOKE_MAX_UPLOAD_MB", "200")) * 1024 * 1024
RUNTIME_ROOT = Path(tempfile.mkdtemp(prefix="karaoke-engine-api-"))


@dataclass
class Job:
    root: Path
    source_name: str
    stems: StemPaths


JOBS: dict[str, Job] = {}


def _cleanup_runtime() -> None:
    shutil.rmtree(RUNTIME_ROOT, ignore_errors=True)


atexit.register(_cleanup_runtime)

app = FastAPI(title="Karaoke Engine API", version="1.0.0")

origins = [
    value.strip()
    for value in os.getenv(
        "KARAOKE_CORS_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if value.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


def _job_response(job_id: str, job: Job) -> dict[str, object]:
    return {
        "job_id": job_id,
        "source_name": job.source_name,
        "engine": job.stems.engine,
        "instrumental_url": f"/api/jobs/{job_id}/instrumental",
        "vocals_url": f"/api/jobs/{job_id}/vocals",
    }


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    total = 0
    with destination.open("wb") as out:
        while chunk := await upload.read(1024 * 1024):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="audio file is too large")
            out.write(chunk)


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"status": "ok", "separator": separator_available()}


@app.post("/api/separate")
async def separate(file: UploadFile = File(...)) -> dict[str, object]:
    source_name = file.filename or "audio"
    suffix = Path(source_name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail=f"unsupported audio type: {suffix or 'unknown'}")

    job_id = uuid.uuid4().hex
    job_root = RUNTIME_ROOT / job_id
    job_root.mkdir(parents=True, exist_ok=False)
    input_path = job_root / f"input{suffix}"

    try:
        await _save_upload(file, input_path)
        stems = await run_in_threadpool(separate_with_demucs, input_path, job_root)
    except HTTPException:
        shutil.rmtree(job_root, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(job_root, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"separation failed: {exc}") from exc
    finally:
        await file.close()

    job = Job(root=job_root, source_name=source_name, stems=stems)
    JOBS[job_id] = job
    return _job_response(job_id, job)


@app.post("/api/debug/synthetic")
async def debug_synthetic() -> dict[str, object]:
    """End-to-end API debug without a real sample.mp3 or model download."""
    job_id = uuid.uuid4().hex
    job_root = RUNTIME_ROOT / job_id
    job_root.mkdir(parents=True, exist_ok=False)
    synthetic_path = job_root / "synthetic-mix.wav"

    try:
        await run_in_threadpool(generate_synthetic_mix, synthetic_path)
        stems = await run_in_threadpool(phase_cancel_wav, synthetic_path, job_root / "debug-stems")
    except Exception as exc:
        shutil.rmtree(job_root, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"synthetic debug failed: {exc}") from exc

    job = Job(root=job_root, source_name="synthetic-mix.wav", stems=stems)
    JOBS[job_id] = job
    return _job_response(job_id, job)


def _require_job(job_id: str) -> Job:
    job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found or already cleaned up")
    return job


@app.get("/api/jobs/{job_id}/instrumental")
def instrumental(job_id: str) -> FileResponse:
    job = _require_job(job_id)
    return FileResponse(job.stems.instrumental, media_type="audio/wav", filename="instrumental.wav")


@app.get("/api/jobs/{job_id}/vocals")
def vocals(job_id: str) -> FileResponse:
    job = _require_job(job_id)
    return FileResponse(job.stems.vocals, media_type="audio/wav", filename="vocals.wav")


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str) -> dict[str, bool]:
    job = JOBS.pop(job_id, None)
    if job is not None:
        shutil.rmtree(job.root, ignore_errors=True)
    return {"deleted": job is not None}
