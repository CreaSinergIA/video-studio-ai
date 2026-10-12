"""Proyectos: creación, manifiestos en disco, estado calculado, borrado seguro y re-adopción."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import get_settings
from app.domain.edit_config import EditConfig
from app.domain.preferences import EditorState, GeneralPreferences
from app.jobs.runner import ACTIVE_STATUSES, REGISTRY, create_job
from app.models import Job, MediaAsset, Preset, Project, StorageLocation, new_id, utcnow
from app.schemas import AssetOut, FilmstripOut, JobOut, ProjectDetail, ProjectSummary
from app.services import presets as preset_service
from app.services.media_probe import HDR_TRANSFERS, MediaValidationError, probe_file
from app.services.storage import (
    PROJECT_MANIFEST,
    PROJECTS_DIR,
    StorageError,
    atomic_write_json,
    ensure_project_dirs,
    purge_staged,
    read_json,
    resolve_inside,
    slugify,
    stage_project_delete,
    unstage_project_delete,
)
from app.services.storage_manager import storage_manager

log = logging.getLogger(__name__)

MANIFEST_VERSION = 1
# Columnas de MediaAsset que se copian al manifiesto (todo menos el volcado bruto de ffprobe).
_ASSET_FIELDS = (
    "id",
    "role",
    "original_filename",
    "file_rel",
    "size_bytes",
    "sha256",
    "quick_hash",
    "container",
    "format_name",
    "major_brand",
    "duration",
    "width",
    "height",
    "display_width",
    "display_height",
    "rotation",
    "orientation",
    "fps",
    "fps_num",
    "fps_den",
    "video_codec",
    "video_profile",
    "pix_fmt",
    "bit_depth",
    "color_transfer",
    "bit_rate",
    "frame_count",
    "has_audio",
    "audio_tracks",
    "creation_time",
    "browser_playable",
)


class ProjectError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Serialización
# ---------------------------------------------------------------------------


def _version_tag(value: datetime | None) -> str:
    return str(int(value.timestamp())) if value else "0"


def job_out(job: Job) -> JobOut:
    kind = REGISTRY.get(job.kind)
    return JobOut(
        id=job.id,
        kind=job.kind,
        label=kind.label if kind else job.kind,
        status=job.status,
        project_id=job.project_id,
        asset_id=job.asset_id,
        progress=job.progress,
        stage=job.stage,
        error=job.error,
        result=job.result,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


def asset_out(asset: MediaAsset, storage_available: bool, prefs: GeneralPreferences) -> AssetOut:
    base = f"/api/media/{asset.id}"
    v = _version_tag(asset.updated_at)
    proxy_ready = bool(asset.proxy_rel)
    if not storage_available:
        playback, stream_url = "unavailable", None
    elif proxy_ready and (not asset.browser_playable or prefs.playback_proxy == "always"):
        playback, stream_url = "proxy", f"{base}/proxy?v={v}"
    elif asset.browser_playable or prefs.playback_proxy == "never":
        playback, stream_url = "original", f"{base}/original"
    else:
        playback, stream_url = "unavailable", None
    filmstrip = None
    if asset.filmstrip_rel and asset.filmstrip_meta:
        filmstrip = FilmstripOut(url=f"{base}/filmstrip?v={v}", **asset.filmstrip_meta)
    return AssetOut(
        id=asset.id,
        project_id=asset.project_id,
        role=asset.role,
        status=asset.status,
        error=asset.error,
        original_filename=asset.original_filename,
        file_rel=asset.file_rel,
        size_bytes=asset.size_bytes,
        sha256=asset.sha256,
        container=asset.container,
        format_name=asset.format_name,
        major_brand=asset.major_brand,
        duration=asset.duration,
        width=asset.width,
        height=asset.height,
        display_width=asset.display_width,
        display_height=asset.display_height,
        rotation=asset.rotation,
        orientation=asset.orientation,
        fps=asset.fps,
        fps_num=asset.fps_num,
        fps_den=asset.fps_den,
        video_codec=asset.video_codec,
        video_profile=asset.video_profile,
        pix_fmt=asset.pix_fmt,
        bit_depth=asset.bit_depth,
        color_transfer=asset.color_transfer,
        is_hdr=asset.color_transfer in HDR_TRANSFERS,
        bit_rate=asset.bit_rate,
        frame_count=asset.frame_count,
        has_audio=asset.has_audio,
        audio_tracks=asset.audio_tracks or [],
        creation_time=asset.creation_time,
        browser_playable=asset.browser_playable,
        playback=playback,
        stream_url=stream_url,
        original_url=f"{base}/original",
        proxy_ready=proxy_ready,
        thumbnail_url=f"{base}/thumbnail?v={v}" if asset.thumbnail_rel else None,
        filmstrip=filmstrip,
        waveform_url=f"{base}/waveform?v={v}" if asset.waveform_rel else None,
        verified_at=asset.verified_at,
        created_at=asset.created_at,
    )


def _source(project: Project) -> MediaAsset | None:
    return next((a for a in project.assets if a.role == "source"), None)


def _status(project: Project, available: bool, active_job: Job | None) -> str:
    if not available:
        return "unavailable"
    source = _source(project)
    if source is None:
        return "importing" if active_job is not None else "empty"
    if source.status == "error":
        return "error"
    if source.status != "ready":
        return "processing"
    return "ready"


def active_jobs_by_project(session: Session, project_ids: list[str]) -> dict[str, Job]:
    if not project_ids:
        return {}
    jobs = session.scalars(
        select(Job)
        .where(Job.project_id.in_(project_ids), Job.status.in_(ACTIVE_STATUSES))
        .order_by(Job.created_at)
    ).all()
    result: dict[str, Job] = {}
    for job in jobs:
        # Prioriza la tarea en ejecución sobre las encoladas.
        current = result.get(job.project_id or "")
        if current is None or (job.status == "running" and current.status != "running"):
            result[job.project_id or ""] = job
    return result


def _availability(session: Session, project: Project) -> tuple[bool, str | None]:
    location = project.storage
    status = storage_manager.status_for(location)
    return status.available, status.message


def project_summary(
    project: Project,
    available: bool,
    active_job: Job | None,
    prefs: GeneralPreferences,
) -> ProjectSummary:
    source = _source(project)
    config = project.config or {}
    return ProjectSummary(
        id=project.id,
        name=project.name,
        status=_status(project, available, active_job),
        storage_id=project.storage_id,
        storage_available=available,
        dir_rel=project.dir_rel,
        preset_id=project.preset_id,
        style_id=(config.get("style") or {}).get("id", "motion_tech"),
        created_at=project.created_at,
        updated_at=project.updated_at,
        last_opened_at=project.last_opened_at,
        source=asset_out(source, available, prefs) if source else None,
        active_job=job_out(active_job) if active_job else None,
    )


def project_detail(session: Session, project: Project, prefs: GeneralPreferences) -> ProjectDetail:
    available, message = _availability(session, project)
    active = active_jobs_by_project(session, [project.id]).get(project.id)
    summary = project_summary(project, available, active, prefs)
    return ProjectDetail(
        **summary.model_dump(),
        config=EditConfig.model_validate(project.config),
        editor_state=EditorState.model_validate(project.editor_state or {}),
        storage_path=project.storage.path,
        storage_message=None if available else message,
        assets=[asset_out(a, available, prefs) for a in project.assets],
    )


def list_projects(session: Session, prefs: GeneralPreferences) -> list[ProjectSummary]:
    projects = session.scalars(
        select(Project).options(selectinload(Project.assets), selectinload(Project.storage))
    ).all()
    jobs = active_jobs_by_project(session, [p.id for p in projects])
    availability: dict[str, bool] = {}
    out = []
    for project in projects:
        if project.storage_id not in availability:
            availability[project.storage_id] = storage_manager.status_for(project.storage).available
        out.append(
            project_summary(project, availability[project.storage_id], jobs.get(project.id), prefs)
        )
    return out


# ---------------------------------------------------------------------------
# Manifiesto en disco
# ---------------------------------------------------------------------------


def manifest_payload(project: Project) -> dict[str, Any]:
    return {
        "format_version": MANIFEST_VERSION,
        "app": "video-studio-ai",
        "project_id": project.id,
        "name": project.name,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": utcnow().isoformat(),
        "preset_id": project.preset_id,
        "config": project.config,
        "assets": [
            {
                **{field: getattr(a, field) for field in _ASSET_FIELDS},
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in project.assets
        ],
    }


def write_manifest(root: Path, project: Project) -> None:
    project_dir = resolve_inside(root, project.dir_rel)
    atomic_write_json(project_dir / PROJECT_MANIFEST, manifest_payload(project))


def sync_manifest(project: Project) -> bool:
    """Escribe el manifiesto si el almacenamiento está disponible (si no, se hará después)."""
    try:
        root = storage_manager.require_location(project.storage)
        write_manifest(root, project)
        return True
    except (StorageError, OSError) as exc:
        log.warning("Manifiesto de %s no actualizado: %s", project.id, exc)
        return False


# ---------------------------------------------------------------------------
# Operaciones
# ---------------------------------------------------------------------------


def get_project(session: Session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise ProjectError("project_not_found", "El proyecto no existe.", 404)
    return project


def create_project(
    session: Session, name: str, preset_id: str | None = None
) -> tuple[Project, Path]:
    name = name.strip()
    if not name:
        raise ProjectError("invalid_name", "El nombre no puede estar vacío.", 422)
    location, root = storage_manager.require_active(session)
    preset: Preset = (
        preset_service.get_preset(session, preset_id)
        if preset_id
        else preset_service.default_preset(session)
    )
    project_id = new_id("prj")
    dir_rel = f"{PROJECTS_DIR}/{utcnow():%Y-%m-%d}_{slugify(name)}_{project_id[-6:]}"
    project_dir = resolve_inside(root, dir_rel)
    ensure_project_dirs(project_dir)
    project = Project(
        id=project_id,
        name=name,
        storage_id=location.id,
        dir_rel=dir_rel,
        preset_id=preset.id,
        config=preset_service.preset_config(preset).model_dump(mode="json"),
        editor_state={},
    )
    project.storage = location
    session.add(project)
    session.flush()
    write_manifest(root, project)
    return project, root


def rename_project(session: Session, project: Project, name: str) -> None:
    name = name.strip()
    if not name:
        raise ProjectError("invalid_name", "El nombre no puede estar vacío.", 422)
    project.name = name
    session.flush()
    sync_manifest(project)


def update_config(session: Session, project: Project, config: EditConfig) -> None:
    project.config = config.model_dump(mode="json")
    session.flush()
    sync_manifest(project)


def apply_preset(session: Session, project: Project, preset_id: str) -> None:
    preset = preset_service.get_preset(session, preset_id)
    project.preset_id = preset.id
    project.config = preset_service.preset_config(preset).model_dump(mode="json")
    session.flush()
    sync_manifest(project)


def delete_project(session: Session, project: Project, keep_files: bool) -> tuple[bool, str]:
    """Elimina el proyecto. Si el almacenamiento no está disponible, solo se permite quitarlo
    de la biblioteca de forma explícita (``keep_files``); nunca se deja nada a medias.

    Orden: aparta la carpeta (rename atómico) → confirma la base de datos → borra los archivos
    fuera de la transacción (sin bloquear SQLite). Si la confirmación falla, la carpeta vuelve
    a su sitio.
    """
    from app.jobs.runner import runner

    runner.cancel_for_project(project.id)
    root = None if keep_files else storage_manager.require_location(project.storage)
    dir_rel, pid = project.dir_rel, project.id
    session.delete(project)
    session.flush()
    staged = stage_project_delete(root, dir_rel, pid) if root is not None else None
    try:
        session.commit()
    except Exception:
        if staged is not None and root is not None:
            unstage_project_delete(staged, root, dir_rel)
        raise
    if staged is not None:
        purge_staged(staged)
    if staged is not None:
        message = "Proyecto y archivos eliminados."
    elif keep_files:
        message = "Proyecto quitado de la biblioteca. Sus archivos siguen en el almacenamiento."
    else:
        message = "Proyecto eliminado (su carpeta ya no existía)."
    return staged is not None, message


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def adopt_manifests(session: Session, location: StorageLocation, root: Path) -> int:
    """Registra en la base de datos los proyectos que existan en el almacenamiento pero no en
    la biblioteca (reinstalación, otra máquina, base de datos perdida)."""
    projects_dir = root / PROJECTS_DIR
    if not projects_dir.is_dir():
        return 0
    adopted = 0
    for entry in sorted(projects_dir.iterdir()):
        if entry.name.startswith((".", "._")) or not entry.is_dir():
            continue
        manifest = read_json(entry / PROJECT_MANIFEST)
        if not isinstance(manifest, dict) or manifest.get("app") != "video-studio-ai":
            continue
        project_id = manifest.get("project_id")
        if not isinstance(project_id, str) or session.get(Project, project_id) is not None:
            continue
        try:
            config = EditConfig.model_validate(manifest.get("config") or {})
        except ValueError:
            config = EditConfig()
        preset_id = manifest.get("preset_id")
        if preset_id and session.get(Preset, preset_id) is None:
            preset_id = None
        project = Project(
            id=project_id,
            name=str(manifest.get("name") or entry.name)[:200],
            storage_id=location.id,
            dir_rel=f"{PROJECTS_DIR}/{entry.name}",
            preset_id=preset_id,
            config=config.model_dump(mode="json"),
            editor_state={},
        )
        session.add(project)
        session.flush()
        for raw in manifest.get("assets") or []:
            try:
                fields = {f: raw[f] for f in _ASSET_FIELDS if f in raw}
                file_path = resolve_inside(root, fields["file_rel"])
                if not file_path.is_file() or session.get(MediaAsset, fields["id"]) is not None:
                    continue
                # El manifiesto es un archivo editable: los datos técnicos se vuelven a medir en
                # el propio video (llegan a filtros de FFmpeg) y el manifiesto solo aporta la
                # identidad del recurso.
                info = probe_file(
                    get_settings().ffprobe, file_path, str(fields.get("original_filename") or "")
                )
                fields = {
                    "id": str(fields["id"]),
                    "role": str(fields.get("role") or "source"),
                    "original_filename": str(fields.get("original_filename") or file_path.name),
                    "file_rel": str(fields["file_rel"]),
                    "size_bytes": file_path.stat().st_size,
                    "sha256": _text(fields.get("sha256")),
                    "quick_hash": _text(fields.get("quick_hash")),
                    **info.asset_fields(),
                }
                asset = MediaAsset(**fields, project_id=project.id, status="processing")
                session.add(asset)
                session.flush()
                create_job(session, "ingest", project_id=project.id, asset_id=asset.id)
            except (KeyError, TypeError, ValueError, StorageError, MediaValidationError) as exc:
                log.warning("Recurso del manifiesto %s ignorado: %s", entry.name, exc)
        adopted += 1
        log.info("Proyecto adoptado desde el almacenamiento: %s (%s)", project.name, project.id)
    return adopted
