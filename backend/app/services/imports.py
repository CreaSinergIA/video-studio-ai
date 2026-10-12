"""Importación de videos: validación, duplicados y alta del recurso en el proyecto.

Flujo común (subida desde el navegador o copia desde una ruta local):
1. Los bytes se escriben en ``cache/uploads/<id>.partial`` calculando SHA-256 en streaming.
2. ffprobe valida el formato *real* (no solo la extensión).
3. Se comprueban duplicados por SHA-256.
4. ``os.replace`` mueve el archivo a ``projects/<p>/originals/`` (misma unidad: atómico).
5. Se registra el recurso y se encola la tarea de ingesta (miniatura, tira, onda, proxy).
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.jobs.runner import create_job
from app.models import Job, MediaAsset, Project, StorageLocation, new_id
from app.schemas import DuplicateOut
from app.services import projects as project_service
from app.services.media_probe import (
    MediaValidationError,
    extension_container,
    probe_file,
)
from app.services.storage import (
    UPLOADS_DIR,
    StorageError,
    resolve_inside,
    rmtree_tolerant,
    sanitize_filename,
    to_rel,
)

log = logging.getLogger(__name__)

QUICK_HASH_CHUNK = 4 * 1024 * 1024
COPY_CHUNK = 8 * 1024 * 1024


class DuplicateError(Exception):
    def __init__(self, duplicates: list[DuplicateOut]) -> None:
        super().__init__("Duplicado")
        self.duplicates = duplicates


def quick_hash_file(path: Path) -> str:
    """Huella rápida: sha256(«tamaño:» + primeros 4 MB + últimos 4 MB). El navegador calcula
    exactamente lo mismo antes de subir para detectar duplicados sin transferir el archivo."""
    size = path.stat().st_size
    digest = hashlib.sha256(f"{size}:".encode())
    with open(path, "rb") as fh:
        digest.update(fh.read(min(QUICK_HASH_CHUNK, size)))
        fh.seek(max(0, size - QUICK_HASH_CHUNK))
        digest.update(fh.read(QUICK_HASH_CHUNK))
    return digest.hexdigest()


def find_duplicates(
    session: Session, *, sha256: str | None = None, quick_hash: str | None = None
) -> list[DuplicateOut]:
    query = select(MediaAsset, Project).join(Project, MediaAsset.project_id == Project.id)
    if sha256:
        query = query.where(MediaAsset.sha256 == sha256)
    elif quick_hash:
        query = query.where(MediaAsset.quick_hash == quick_hash)
    else:
        return []
    return [
        DuplicateOut(
            project_id=project.id,
            project_name=project.name,
            asset_id=asset.id,
            original_filename=asset.original_filename,
            created_at=asset.created_at,
        )
        for asset, project in session.execute(query).all()
    ]


def new_partial_path(root: Path) -> Path:
    uploads = root / UPLOADS_DIR
    uploads.mkdir(exist_ok=True)  # cache/ existe en una raíz válida; nunca crear padres
    return uploads / f"{new_id('upl')}.partial"


def _unique_destination(directory: Path, filename: str) -> Path:
    candidate = directory / filename
    stem, ext = os.path.splitext(filename)
    n = 2
    while candidate.exists():
        candidate = directory / f"{stem} ({n}){ext}"
        n += 1
    return candidate


def _make_read_only(path: Path) -> None:
    # Protección adicional del original (en exFAT los permisos pueden no persistir).
    with contextlib.suppress(OSError):
        path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)


@dataclass
class ImportOutcome:
    project: Project
    asset: MediaAsset
    job: Job


def resolve_target_project(
    session: Session, project_id: str | None, location: StorageLocation
) -> Project | None:
    if project_id is None:
        return None
    project = project_service.get_project(session, project_id)
    if project.storage_id != location.id:
        raise project_service.ProjectError(
            "storage_mismatch",
            "El proyecto pertenece a otro almacenamiento; actívalo para importar en él.",
        )
    if any(a.role == "source" for a in project.assets):
        raise project_service.ProjectError(
            "source_exists", "Este proyecto ya tiene un video de origen."
        )
    return project


def finalize_import(
    session: Session,
    *,
    location: StorageLocation,
    root: Path,
    partial: Path,
    filename: str,
    sha256: str,
    project_id: str | None,
    project_name: str | None,
    allow_duplicate: bool,
) -> ImportOutcome:
    """Valida y registra un archivo ya copiado en ``partial``. Si algo falla, borra el parcial."""
    settings = get_settings()
    created_dir: Path | None = None
    dest: Path | None = None
    try:
        if extension_container(filename) is None:
            raise MediaValidationError(
                "unsupported_extension", "Extensión no admitida. Usa archivos .mp4 o .mov."
            )
        info = probe_file(settings.ffprobe, partial, filename)
        if not allow_duplicate:
            duplicates = find_duplicates(session, sha256=sha256)
            if duplicates:
                raise DuplicateError(duplicates)
        project = resolve_target_project(session, project_id, location)
        if project is None:
            default_name = os.path.splitext(os.path.basename(filename))[0] or "Proyecto"
            project, root = project_service.create_project(session, project_name or default_name)
            created_dir = resolve_inside(root, project.dir_rel)
        project_dir = resolve_inside(root, project.dir_rel)
        originals = project_dir / "originals"
        originals.mkdir(exist_ok=True)  # nunca crear carpetas padre
        dest = _unique_destination(originals, sanitize_filename(filename))
        quick = quick_hash_file(partial)
        os.replace(partial, dest)
        _make_read_only(dest)
        asset = MediaAsset(
            id=new_id("ast"),
            project_id=project.id,
            role="source",
            status="processing",
            original_filename=os.path.basename(filename),
            file_rel=to_rel(root, dest),
            size_bytes=dest.stat().st_size,
            sha256=sha256,
            quick_hash=quick,
            container=info.container,
            format_name=info.format_name,
            major_brand=info.major_brand,
            duration=info.duration,
            width=info.width,
            height=info.height,
            display_width=info.display_width,
            display_height=info.display_height,
            rotation=info.rotation,
            orientation=info.orientation,
            fps=info.fps,
            fps_num=info.fps_num,
            fps_den=info.fps_den,
            video_codec=info.video_codec,
            video_profile=info.video_profile,
            pix_fmt=info.pix_fmt,
            bit_depth=info.bit_depth,
            color_transfer=info.color_transfer,
            bit_rate=info.bit_rate,
            frame_count=info.frame_count,
            has_audio=info.has_audio,
            audio_tracks=[t.__dict__ for t in info.audio_tracks],
            creation_time=info.creation_time,
            probe=info.raw,
            browser_playable=info.browser_playable,
        )
        session.add(asset)
        session.flush()
        session.refresh(project)
        job = create_job(session, "ingest", project_id=project.id, asset_id=asset.id)
        # Confirmar aquí: si falla, se deshacen también los archivos (nada queda huérfano).
        session.commit()
    except BaseException:
        session.rollback()
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
        if dest is not None and dest.exists():
            with contextlib.suppress(OSError):
                dest.chmod(stat.S_IRUSR | stat.S_IWUSR)
                dest.unlink()
        if created_dir is not None:
            rmtree_tolerant(created_dir)
        raise
    project_service.sync_manifest(project)
    log.info(
        "Importado %s → %s (%s, %dx%d, %.2fs, %s)",
        filename,
        asset.file_rel,
        info.video_codec,
        info.display_width,
        info.display_height,
        info.duration,
        info.orientation,
    )
    return ImportOutcome(project=project, asset=asset, job=job)


def copy_with_hash(
    source: Path,
    dest: Path,
    *,
    on_progress=None,
    cancel=None,
) -> str:
    """Copia por bloques calculando SHA-256 (nunca carga el archivo completo en memoria)."""
    total = source.stat().st_size or 1
    digest = hashlib.sha256()
    copied = 0
    with open(source, "rb") as src, open(dest, "wb") as out:
        while True:
            if cancel is not None and cancel.is_set():
                from app.services.media_tools import Cancelled

                raise Cancelled()
            block = src.read(COPY_CHUNK)
            if not block:
                break
            digest.update(block)
            out.write(block)
            copied += len(block)
            if on_progress:
                on_progress(copied / total)
        out.flush()
        os.fsync(out.fileno())
    if copied != source.stat().st_size:
        raise StorageError("copy_incomplete", "La copia quedó incompleta; se descartó.", 500)
    return digest.hexdigest()
