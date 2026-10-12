"""Tareas de medios de la Fase 1."""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.db import session_scope
from app.jobs.runner import JobContext, JobError, job_handler
from app.models import MediaAsset, Project, StorageLocation, utcnow
from app.services import app_settings, media_tools
from app.services import imports as import_service
from app.services import projects as project_service
from app.services.storage import (
    PROJECT_MANIFEST,
    PROJECT_SUBDIRS,
    StorageError,
    require_space,
    resolve_inside,
)
from app.services.storage_manager import storage_manager

log = logging.getLogger(__name__)


def _load(ctx: JobContext) -> tuple[MediaAsset, Path, Path]:
    """Devuelve (recurso, raíz, ruta del original) validando el almacenamiento."""
    with session_scope() as s:
        asset = s.get(MediaAsset, ctx.asset_id) if ctx.asset_id else None
        if asset is None:
            raise JobError("El recurso ya no existe (¿se eliminó el proyecto?).")
        location = asset.project.storage
        root = storage_manager.require_location(location)
        src = resolve_inside(root, asset.file_rel)
        s.expunge(asset)
    if not src.is_file():
        raise JobError(f"No se encuentra el archivo original: {asset.file_rel}")
    project_dir = src.parents[1]
    if not (project_dir / PROJECT_MANIFEST).is_file():
        raise JobError("La carpeta del proyecto ya no está en el almacenamiento.")
    for sub in PROJECT_SUBDIRS:  # proyectos re-adoptados pueden no tenerlas todas
        (project_dir / sub).mkdir(exist_ok=True)
    return asset, root, src


def _update_asset(asset_id: str, **values: Any) -> None:
    with session_scope() as s:
        asset = s.get(MediaAsset, asset_id)
        if asset is None:
            raise JobError("El recurso ya no existe (¿se eliminó el proyecto?).")
        for key, value in values.items():
            setattr(asset, key, value)


def _sync_manifest(project_id: str) -> None:
    with session_scope() as s:
        project = s.get(Project, project_id)
        if project is not None:
            project_service.sync_manifest(project)


@job_handler("ingest", label="Preparando video", resumable=True)
def ingest(ctx: JobContext) -> dict[str, Any]:
    """Miniatura, tira de fotogramas, forma de onda y (si hace falta) proxy de reproducción."""
    settings = get_settings()
    asset, root, src = _load(ctx)
    project_dir = resolve_inside(root, asset.file_rel).parents[1]
    with session_scope() as s:
        prefs = app_settings.get_general(s)
    want_proxy = prefs.playback_proxy == "always" or (
        prefs.playback_proxy == "auto" and not asset.browser_playable
    )
    result: dict[str, Any] = {}
    try:
        ctx.stage("Generando miniatura", 0.0, 0.1)
        thumb = project_dir / "frames" / "thumbnail.jpg"
        media_tools.make_thumbnail(settings.ffmpeg, src, thumb, asset.duration)
        _update_asset(asset.id, thumbnail_rel=thumb.relative_to(root.resolve()).as_posix())
        ctx.check_cancelled()

        ctx.stage(
            "Extrayendo fotogramas para la línea de tiempo", 0.1, 0.45 if want_proxy else 0.75
        )
        strip = project_dir / "frames" / "filmstrip.jpg"
        meta = media_tools.make_filmstrip(
            settings.ffmpeg,
            src,
            strip,
            asset.duration,
            asset.display_width,
            asset.display_height,
            on_progress=ctx.progress,
            cancel=ctx.cancel_event,
        )
        _update_asset(
            asset.id,
            filmstrip_rel=strip.relative_to(root.resolve()).as_posix(),
            filmstrip_meta=meta.to_dict(),
        )
        result["filmstrip_frames"] = meta.count

        if asset.has_audio:
            ctx.stage(
                "Analizando forma de onda",
                0.45 if want_proxy else 0.75,
                0.55 if want_proxy else 1.0,
            )
            wave = project_dir / "analysis" / "waveform.json"
            payload = media_tools.make_waveform(
                settings.ffmpeg,
                src,
                wave,
                asset.duration,
                cancel=ctx.cancel_event,
                on_progress=ctx.progress,
            )
            _update_asset(asset.id, waveform_rel=wave.relative_to(root.resolve()).as_posix())
            result["waveform_peaks"] = len(payload["peaks"])

        if want_proxy:
            ctx.stage("Creando proxy de reproducción", 0.55, 1.0)
            proxy = project_dir / "previews" / "proxy.mp4"
            require_space(root, max(asset.size_bytes // 2, 50 * 1024 * 1024))
            encoder = media_tools.make_proxy(
                settings.ffmpeg,
                src,
                proxy,
                asset.duration,
                asset.has_audio,
                on_progress=ctx.progress,
                cancel=ctx.cancel_event,
            )
            _update_asset(asset.id, proxy_rel=proxy.relative_to(root.resolve()).as_posix())
            result["proxy_encoder"] = encoder
        _update_asset(asset.id, status="ready", error=None)
    except media_tools.Cancelled:
        if not ctx.shutting_down:  # al cerrar la app la tarea se reanuda: no es un error
            _update_asset(
                asset.id, status="error", error="Preparación cancelada. Puedes reintentarla."
            )
        raise
    except (media_tools.FFmpegError, StorageError, OSError, JobError) as exc:
        message = exc.message if isinstance(exc, StorageError) else str(exc)
        with contextlib.suppress(JobError):
            _update_asset(asset.id, status="error", error=message)
        raise JobError(message) from exc
    _sync_manifest(asset.project_id)
    return result


@job_handler("proxy", label="Creando proxy de reproducción", resumable=True)
def build_proxy(ctx: JobContext) -> dict[str, Any]:
    settings = get_settings()
    asset, root, src = _load(ctx)
    proxy = resolve_inside(root, asset.file_rel).parents[1] / "previews" / "proxy.mp4"
    ctx.stage("Creando proxy de reproducción", 0.0, 1.0)
    try:
        require_space(root, max(asset.size_bytes // 2, 50 * 1024 * 1024))
        encoder = media_tools.make_proxy(
            settings.ffmpeg,
            src,
            proxy,
            asset.duration,
            asset.has_audio,
            on_progress=ctx.progress,
            cancel=ctx.cancel_event,
        )
    except media_tools.FFmpegError as exc:
        raise JobError(str(exc)) from exc
    _update_asset(asset.id, proxy_rel=proxy.relative_to(root.resolve()).as_posix())
    return {"proxy_encoder": encoder}


@job_handler("verify", label="Verificando integridad del original", resumable=True)
def verify_original(ctx: JobContext) -> dict[str, Any]:
    """Recalcula el SHA-256 del original y lo compara con el registrado al importar."""
    asset, _root, src = _load(ctx)
    ctx.stage("Calculando SHA-256", 0.0, 1.0)
    digest = hashlib.sha256()
    total = src.stat().st_size or 1
    done = 0
    with open(src, "rb") as fh:
        while block := fh.read(import_service.COPY_CHUNK):
            ctx.check_cancelled()
            digest.update(block)
            done += len(block)
            ctx.progress(done / total)
    actual = digest.hexdigest()
    intact = actual == asset.sha256
    if intact:
        _update_asset(asset.id, verified_at=utcnow())
    else:
        log.error("Integridad: %s no coincide (%s != %s)", asset.file_rel, actual, asset.sha256)
        raise JobError(
            "¡El original no coincide con la huella registrada al importarlo! "
            "El archivo pudo modificarse o dañarse fuera de Video Studio."
        )
    return {"intact": True, "sha256": actual}


@job_handler("import_file", label="Importando video")
def import_file(ctx: JobContext) -> dict[str, Any]:
    """Copia un video desde una ruta local (selector nativo) al almacenamiento."""
    source = Path(ctx.payload["source_path"])
    if not source.is_file():
        raise JobError(f"No se encuentra el archivo: {source}")
    with session_scope() as s:
        location = s.get(StorageLocation, ctx.payload["storage_id"])
        if location is None:
            raise JobError("El almacenamiento de destino ya no está registrado.")
        root = storage_manager.require_location(location)
    require_space(root, source.stat().st_size)
    partial = import_service.new_partial_path(root)
    try:
        ctx.stage(f"Copiando {source.name}", 0.0, 0.95)
        sha256 = import_service.copy_with_hash(
            source, partial, on_progress=ctx.progress, cancel=ctx.cancel_event
        )
        ctx.stage("Validando video", 0.95, 1.0)
        with session_scope() as s:
            location = s.get(StorageLocation, ctx.payload["storage_id"])
            assert location is not None
            try:
                outcome = import_service.finalize_import(
                    s,
                    location=location,
                    root=root,
                    partial=partial,
                    filename=source.name,
                    sha256=sha256,
                    project_id=ctx.payload.get("project_id"),
                    project_name=ctx.payload.get("project_name"),
                    allow_duplicate=bool(ctx.payload.get("allow_duplicate")),
                )
            except import_service.DuplicateError as exc:
                names = ", ".join(f"«{d.project_name}»" for d in exc.duplicates)
                raise JobError(f"Este video ya está importado en {names}.") from exc
            except import_service.MediaValidationError as exc:
                raise JobError(exc.message) from exc
            except project_service.ProjectError as exc:
                raise JobError(exc.message) from exc
            result = {"project_id": outcome.project.id, "asset_id": outcome.asset.id}
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(partial)
    from app.jobs.runner import runner

    runner.wake()
    return result
