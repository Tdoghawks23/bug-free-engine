"""FastAPI web app (plan task 10).

Single-user local tool: no auth, no Redis/Celery. A single-worker
``ThreadPoolExecutor`` serializes processing jobs (extraction/rendering is
CPU/memory heavy, and running two at once on one machine buys nothing but
contention), backed by an in-process job registry dict guarded by a lock.
Job metadata is mirrored to ``jobs/<uuid>/meta.json`` on every state/stage
change so a completed job can still be looked up (and its artifacts
downloaded) after a server restart -- the registry rebuilds a job lazily
from that file on a lookup miss rather than replaying anything.

Run: ``uvicorn remediate.app:app --reload``
"""

from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .extractors.docx import DocxExtractionError
from .extractors.pdf import PdfExtractionError
from .pipeline import ProgressCallback, UnsupportedFileError, remediate_file

# Repo root: src/remediate/app.py -> src/remediate -> src -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
JOBS_ROOT = _REPO_ROOT / "jobs"
_STATIC_DIR = Path(__file__).resolve().parent / "static"

_SUPPORTED_EXTENSIONS = {".pdf", ".docx"}
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # 500MB, generous per task 10 spec
_UPLOAD_CHUNK_SIZE = 1024 * 1024  # stream to disk in 1MB chunks -- never buffer the whole file

# artifact key (URL path segment) -> (filename inside jobs/<id>/output/,
# content type, suffix appended to the sanitized original filename stem
# for the download's Content-Disposition filename). Fixed allowlist --
# the artifact string from the URL is only ever used as a dict key, never
# joined into a filesystem path, so path traversal in this segment can't
# reach the filesystem.
_ARTIFACT_MAP: dict[str, tuple[str, str, str]] = {
    "pdf": ("upload.pdf", "application/pdf", ".pdf"),
    "html": ("upload.html", "text/html; charset=utf-8", ".html"),
    "report.html": ("report.html", "text/html; charset=utf-8", "-report.html"),
    "report.json": ("report.json", "application/json", "-report.json"),
}

_REGISTRY: dict[str, "JobRecord"] = {}
_REGISTRY_LOCK = threading.Lock()
_EXECUTOR = ThreadPoolExecutor(max_workers=1)


@dataclass
class JobRecord:
    job_id: str
    state: str  # "queued" | "processing" | "done" | "error"
    stage: str
    pct: float
    original_filename: str
    created_at: str
    error: str | None = None
    summary: dict[str, int] | None = None

    def to_status_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.job_id,
            "state": self.state,
            "stage": self.stage,
            "pct": self.pct,
            "error": self.error,
        }
        if self.state == "done":
            data["summary"] = self.summary
            data["downloads"] = {
                artifact: f"/jobs/{self.job_id}/download/{artifact}" for artifact in _ARTIFACT_MAP
            }
        return data


def _meta_path(job_id: str) -> Path:
    return JOBS_ROOT / job_id / "meta.json"


def _persist(job_id: str) -> None:
    with _REGISTRY_LOCK:
        rec = _REGISTRY.get(job_id)
    if rec is None:
        return
    _meta_path(job_id).write_text(json.dumps(asdict(rec), indent=2), encoding="utf-8")


def _update_job(job_id: str, **fields: Any) -> None:
    with _REGISTRY_LOCK:
        rec = _REGISTRY.get(job_id)
        if rec is None:
            return
        for key, value in fields.items():
            setattr(rec, key, value)


def _lookup_job(job_id: str) -> JobRecord | None:
    with _REGISTRY_LOCK:
        rec = _REGISTRY.get(job_id)
    if rec is not None:
        return rec
    # Lazily rebuild from disk (e.g. after a server restart) rather than
    # keeping any persistent registry of our own.
    meta_path = _meta_path(job_id)
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text())
        rec = JobRecord(**data)
    except (json.JSONDecodeError, TypeError, OSError):
        return None
    with _REGISTRY_LOCK:
        _REGISTRY.setdefault(job_id, rec)
        rec = _REGISTRY[job_id]
    return rec


_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._ -]+")


def _sanitize_filename_stem(name: str) -> str:
    stem = Path(name).stem or "document"
    stem = _FILENAME_SAFE_RE.sub("_", stem).strip(" .")
    return stem or "document"


def _process_job(job_id: str, input_path: Path, outdir: Path) -> None:
    _update_job(job_id, state="processing", stage="extracting", pct=0.0)
    _persist(job_id)

    last_stage = {"value": "extracting"}

    def progress_cb(stage: str, pct: float) -> None:
        _update_job(job_id, stage=stage, pct=pct)
        # Persisting on every callback would mean hundreds of disk writes
        # for a large multi-page PDF (task 9); only persist when the
        # coarse stage actually changes, plus unconditionally at the end.
        if stage != last_stage["value"]:
            last_stage["value"] = stage
            _persist(job_id)

    progress_callback: ProgressCallback = progress_cb

    try:
        result = remediate_file(input_path, outdir, progress_callback=progress_callback)
    except (DocxExtractionError, PdfExtractionError, UnsupportedFileError) as exc:
        _update_job(job_id, state="error", stage="error", pct=1.0, error=str(exc))
        _persist(job_id)
        return
    except Exception as exc:  # pragma: no cover - defensive: never leave a job stuck
        _update_job(
            job_id,
            state="error",
            stage="error",
            pct=1.0,
            error=f"Internal error while processing this document: {exc}",
        )
        _persist(job_id)
        return

    report_data = json.loads(result.report_json_path.read_text(encoding="utf-8"))
    _update_job(job_id, state="done", stage="done", pct=1.0, summary=report_data.get("summary"))
    _persist(job_id)


def _validated_uuid(job_id: str) -> str:
    try:
        return str(uuid.UUID(job_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Job not found.")


app = FastAPI(title="ADA Document Remediation")
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.post("/jobs")
async def create_job(file: UploadFile) -> dict[str, str]:
    original_name = file.filename or "upload"
    suffix = Path(original_name).suffix.lower()
    if suffix not in _SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{suffix or original_name}'. "
                f"Only {', '.join(sorted(_SUPPORTED_EXTENSIONS))} are accepted."
            ),
        )

    job_id = str(uuid.uuid4())
    job_dir = JOBS_ROOT / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    upload_path = job_dir / f"upload{suffix}"

    total_bytes = 0
    try:
        with upload_path.open("wb") as out:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > _MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"File exceeds the maximum upload size of "
                            f"{_MAX_UPLOAD_BYTES // (1024 * 1024)}MB."
                        ),
                    )
                out.write(chunk)
    except HTTPException:
        _rmtree_quiet(job_dir)
        raise
    finally:
        await file.close()

    if total_bytes == 0:
        _rmtree_quiet(job_dir)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    rec = JobRecord(
        job_id=job_id,
        state="queued",
        stage="queued",
        pct=0.0,
        original_filename=original_name,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    with _REGISTRY_LOCK:
        _REGISTRY[job_id] = rec
    _persist(job_id)

    outdir = job_dir / "output"
    _EXECUTOR.submit(_process_job, job_id, upload_path, outdir)

    return {"id": job_id}


def _rmtree_quiet(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


@app.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict[str, Any]:
    job_id = _validated_uuid(job_id)
    rec = _lookup_job(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return rec.to_status_dict()


@app.get("/jobs/{job_id}/download/{artifact}")
async def download_artifact(job_id: str, artifact: str) -> FileResponse:
    job_id = _validated_uuid(job_id)
    rec = _lookup_job(job_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    if artifact not in _ARTIFACT_MAP:
        raise HTTPException(status_code=404, detail="Unknown artifact.")
    if rec.state != "done":
        raise HTTPException(status_code=404, detail="Artifact not available yet.")

    stored_name, content_type, download_suffix = _ARTIFACT_MAP[artifact]
    file_path = JOBS_ROOT / job_id / "output" / stored_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Artifact not found.")

    download_name = _sanitize_filename_stem(rec.original_filename) + download_suffix
    return FileResponse(path=file_path, media_type=content_type, filename=download_name)


__all__ = ["app", "JOBS_ROOT"]
