"""Entrega de medios por ID (nunca por ruta): video con Range, miniatura, tira y onda."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.jobs.runner import ACTIVE_STATUSES, create_job, runner
from app.models import Job, MediaAsset
from app.schemas import JobOut
from app.services import native
from app.services import projects as project_service
from app.services.storage import StorageError, resolve_inside
from app.services.storage_manager import storage_manager

router = APIRouter(prefix="/media", tags=["medios"])

_VIDEO_TYPES = {"mp4": "video/mp4", "mov": "video/quicktime"}


def _asset(session: Session, asset_id: str) -> MediaAsset:
    asset = session.get(MediaAsset, asset_id)
    if asset is None:
        raise StorageError("asset_not_found", "El recurso no existe.", 404)
    return asset


def _file(session: Session, asset: MediaAsset, rel: str | None, label: str) -> Path:
    if not rel:
        raise StorageError("not_ready", f"{label} todavía no está disponible.", 404)
    root = storage_manager.require_location(asset.project.storage)
    path = resolve_inside(root, rel)
    if not path.is_file():
        raise StorageError("file_missing", f"{label}: no se encuentra el archivo en el disco.", 404)
    return path


@router.get("/{asset_id}/original")
def original(asset_id: str, session: Session = Depends(get_session, scope="function")):
    asset = _asset(session, asset_id)
    path = _file(session, asset, asset.file_rel, "El video original")
    media_type = _VIDEO_TYPES.get(asset.container, "application/octet-stream")
    # Safari exige video/mp4 para reproducir contenedores ISO-BMFF con H.264/HEVC.
    if asset.container == "mov" and asset.browser_playable:
        media_type = "video/mp4"
    return FileResponse(
        path,
        media_type=media_type,
        headers={"Cache-Control": "no-cache"},
        content_disposition_type="inline",
    )


@router.get("/{asset_id}/proxy")
def proxy(asset_id: str, session: Session = Depends(get_session, scope="function")):
    asset = _asset(session, asset_id)
    path = _file(session, asset, asset.proxy_rel, "El proxy de reproducción")
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "no-cache"})


@router.get("/{asset_id}/thumbnail")
def thumbnail(asset_id: str, session: Session = Depends(get_session, scope="function")):
    asset = _asset(session, asset_id)
    path = _file(session, asset, asset.thumbnail_rel, "La miniatura")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/{asset_id}/filmstrip")
def filmstrip(asset_id: str, session: Session = Depends(get_session, scope="function")):
    asset = _asset(session, asset_id)
    path = _file(session, asset, asset.filmstrip_rel, "La tira de fotogramas")
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.get("/{asset_id}/waveform")
def waveform(asset_id: str, session: Session = Depends(get_session, scope="function")):
    asset = _asset(session, asset_id)
    path = _file(session, asset, asset.waveform_rel, "La forma de onda")
    return FileResponse(
        path,
        media_type="application/json",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


def _enqueue(session: Session, asset: MediaAsset, kind: str) -> JobOut:
    storage_manager.require_location(asset.project.storage)
    existing = session.scalar(
        select(Job).where(
            Job.asset_id == asset.id, Job.kind == kind, Job.status.in_(ACTIVE_STATUSES)
        )
    )
    if existing is not None:  # doble clic: devolver la tarea que ya está en curso
        return project_service.job_out(existing)
    job = create_job(session, kind, project_id=asset.project_id, asset_id=asset.id)
    session.commit()
    runner.wake()
    return project_service.job_out(job)


@router.post("/{asset_id}/proxy", response_model=JobOut, status_code=202)
def request_proxy(asset_id: str, session: Session = Depends(get_session)):
    return _enqueue(session, _asset(session, asset_id), "proxy")


@router.post("/{asset_id}/verify", response_model=JobOut, status_code=202)
def request_verify(asset_id: str, session: Session = Depends(get_session)):
    return _enqueue(session, _asset(session, asset_id), "verify")


@router.post("/{asset_id}/reprocess", response_model=JobOut, status_code=202)
def request_reprocess(asset_id: str, session: Session = Depends(get_session)):
    asset = _asset(session, asset_id)
    asset.status = "processing"
    asset.error = None
    return _enqueue(session, asset, "ingest")


@router.post("/{asset_id}/reveal")
def reveal(asset_id: str, session: Session = Depends(get_session)):
    asset = _asset(session, asset_id)
    path = _file(session, asset, asset.file_rel, "El video original")
    return {"ok": native.reveal_in_file_manager(path)}
