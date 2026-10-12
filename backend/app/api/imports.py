"""Importación: comprobación previa, subida en streaming e importación desde ruta local."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
from pathlib import Path
from typing import BinaryIO

from fastapi import APIRouter, Depends, Query, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session
from starlette.requests import ClientDisconnect

from app.config import get_settings
from app.db import get_session, session_scope
from app.jobs.runner import create_job, runner
from app.models import StorageLocation
from app.schemas import (
    ImportCheckRequest,
    ImportCheckResult,
    ImportFromPath,
    ImportFromPathResult,
    ImportResult,
    PickedFiles,
)
from app.services import app_settings, native
from app.services import imports as import_service
from app.services import projects as project_service
from app.services.media_probe import (
    MediaValidationError,
    extension_container,
    looks_like_iso_bmff,
    probe_file,
)
from app.services.storage import StorageError, disk_usage, normalize_user_path, require_space
from app.services.storage_manager import storage_manager

log = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["importación"])

_WRITE_BATCH = 4 * 1024 * 1024


def _require_extension(filename: str) -> None:
    if extension_container(filename) is None:
        raise MediaValidationError(
            "unsupported_extension",
            f"«{os.path.basename(filename)}» no es compatible. "
            "Solo se admiten archivos .mp4 y .mov.",
        )


@router.post("/check", response_model=ImportCheckResult)
def check_import(body: ImportCheckRequest, session: Session = Depends(get_session)):
    errors: list[str] = []
    extension_ok = extension_container(body.filename) is not None
    if not extension_ok:
        errors.append("Solo se admiten archivos .mp4 y .mov.")
    free = None
    space_ok = False
    status = storage_manager.active_status(session, fresh=True)
    if not status.available:
        errors.append(status.message or "El almacenamiento no está disponible.")
    else:
        free, _ = disk_usage(Path(status.path or "/"))
        try:
            require_space(Path(status.path or "/"), body.size_bytes)
            space_ok = True
        except StorageError as exc:
            errors.append(exc.message)
    if body.project_id:
        try:
            location = session.get(StorageLocation, status.storage_id or "")
            if location is not None:
                import_service.resolve_target_project(session, body.project_id, location)
        except project_service.ProjectError as exc:
            errors.append(exc.message)
    duplicates = (
        import_service.find_duplicates(session, quick_hash=body.quick_hash)
        if body.quick_hash
        else []
    )
    return ImportCheckResult(
        ok=not errors,
        extension_ok=extension_ok,
        space_ok=space_ok,
        free_bytes=free,
        duplicates=duplicates,
        errors=errors,
    )


@router.post("/upload", response_model=ImportResult, status_code=201)
async def upload(
    request: Request,
    filename: str = Query(min_length=1, max_length=500),
    project_id: str | None = Query(default=None),
    project_name: str | None = Query(default=None, max_length=200),
    allow_duplicate: bool = Query(default=False),
):
    """Recibe el archivo como cuerpo binario (no multipart) y lo escribe por bloques."""
    _require_extension(filename)
    declared = request.headers.get("content-length")
    if declared is None or not declared.isdigit():
        raise StorageError("length_required", "Falta el tamaño del archivo (Content-Length).", 411)
    expected_size = int(declared)
    if expected_size == 0:
        raise MediaValidationError("empty_file", "El archivo está vacío.")

    def prepare() -> tuple[str, Path, Path]:
        with session_scope() as s:
            location, root = storage_manager.require_active(s)
            if project_id:
                import_service.resolve_target_project(s, project_id, location)
            require_space(root, expected_size)
            return location.id, root, import_service.new_partial_path(root)

    storage_id, root, partial = await run_in_threadpool(prepare)
    digest = hashlib.sha256()
    written = 0
    fh: BinaryIO = await run_in_threadpool(open, partial, "wb")

    def write(data: bytes) -> None:
        digest.update(data)
        fh.write(data)

    try:
        buffer = bytearray()
        header_checked = False
        async for chunk in request.stream():
            if not chunk:
                continue
            buffer += chunk
            if not header_checked and len(buffer) >= 12:
                if not looks_like_iso_bmff(bytes(buffer[:12])):
                    raise MediaValidationError(
                        "not_mp4_mov",
                        "El contenido no es un MP4/MOV real (la extensión no coincide con el "
                        "formato del archivo).",
                    )
                header_checked = True
            if len(buffer) >= _WRITE_BATCH:
                data = bytes(buffer)
                buffer.clear()
                written += len(data)
                await run_in_threadpool(write, data)
        if buffer:
            data = bytes(buffer)
            written += len(data)
            await run_in_threadpool(write, data)

        def close() -> None:
            fh.flush()
            os.fsync(fh.fileno())
            fh.close()

        await run_in_threadpool(close)
        if not header_checked:
            raise MediaValidationError("not_mp4_mov", "El archivo es demasiado pequeño.")
        if written != expected_size:
            raise StorageError(
                "upload_incomplete",
                f"Subida incompleta ({written} de {expected_size} bytes). Inténtalo de nuevo.",
                400,
            )
    except ClientDisconnect:
        log.warning("Subida de %s cancelada por el cliente (%d bytes)", filename, written)
        _discard(fh, partial)
        raise StorageError("upload_cancelled", "Subida cancelada.", 499) from None
    except BaseException:
        _discard(fh, partial)
        raise

    def finalize() -> ImportResult:
        with session_scope() as s:
            location = s.get(StorageLocation, storage_id)
            assert location is not None
            outcome = import_service.finalize_import(
                s,
                location=location,
                root=root,
                partial=partial,
                filename=filename,
                sha256=digest.hexdigest(),
                project_id=project_id,
                project_name=project_name,
                allow_duplicate=allow_duplicate,
            )
            s.flush()
            prefs = app_settings.get_general(s)
            summary = project_service.project_summary(outcome.project, True, outcome.job, prefs)
            return ImportResult(
                project=summary,
                asset=project_service.asset_out(outcome.asset, True, prefs),
                job=project_service.job_out(outcome.job),
            )

    result = await run_in_threadpool(finalize)
    runner.wake()
    return result


def _discard(fh: BinaryIO, partial: Path) -> None:
    with contextlib.suppress(Exception):
        fh.close()
    with contextlib.suppress(FileNotFoundError):
        partial.unlink()


@router.post("/from-path", response_model=ImportFromPathResult, status_code=202)
def import_from_path(body: ImportFromPath, session: Session = Depends(get_session)):
    """Importa un archivo local por su ruta (selector nativo). La copia es una tarea."""
    source = normalize_user_path(body.path)
    if not source.is_file():
        raise StorageError("path_missing", f"No se encuentra el archivo: {source}", 404)
    _require_extension(source.name)
    probe_file(get_settings().ffprobe, source)  # validación temprana (solo lectura)
    location, root = storage_manager.require_active(session)
    if body.project_id:
        import_service.resolve_target_project(session, body.project_id, location)
    require_space(root, source.stat().st_size)
    if not body.allow_duplicate:
        duplicates = import_service.find_duplicates(
            session, quick_hash=import_service.quick_hash_file(source)
        )
        if duplicates:
            return ImportFromPathResult(job=None, duplicates=duplicates)
    job = create_job(
        session,
        "import_file",
        project_id=body.project_id,
        payload={
            "source_path": str(source),
            "storage_id": location.id,
            "project_id": body.project_id,
            "allow_duplicate": body.allow_duplicate,
            "filename": source.name,
        },
    )
    session.commit()
    runner.wake()
    return ImportFromPathResult(job=project_service.job_out(job), duplicates=[])


@router.post("/pick-files", response_model=PickedFiles)
def pick_files():
    if not native.native_dialogs_supported():
        return PickedFiles(paths=[], supported=False)
    return PickedFiles(paths=native.pick_video_files("Elige uno o varios videos (MP4 o MOV)"))
