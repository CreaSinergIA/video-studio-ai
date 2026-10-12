"""Almacenamiento: estado, validación, configuración, explorador de carpetas y selector nativo."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.jobs.runner import runner
from app.models import Project, StorageLocation
from app.schemas import (
    BrowseEntry,
    BrowseResult,
    PickedFolder,
    StorageCandidateOut,
    StorageConfigureResult,
    StorageLocationOut,
    StoragePathIn,
    StorageStatusOut,
)
from app.services import native
from app.services import projects as project_service
from app.services.storage import MARKER_NAME, StorageError, inspect_candidate, normalize_user_path
from app.services.storage_manager import storage_manager

router = APIRouter(prefix="/storage", tags=["almacenamiento"])

_HIDDEN = {"$RECYCLE.BIN", "System Volume Information", "Library", "node_modules"}


@router.get("/status", response_model=StorageStatusOut)
def storage_status(fresh: bool = False, session: Session = Depends(get_session)):
    return storage_manager.active_status(session, fresh=fresh).to_dict()


@router.post("/validate", response_model=StorageCandidateOut)
def validate_storage(body: StoragePathIn):
    return inspect_candidate(body.path).to_dict()


@router.post("/configure", response_model=StorageConfigureResult)
def configure_storage(body: StoragePathIn, session: Session = Depends(get_session)):
    location, root = storage_manager.configure(session, body.path)
    adopted = project_service.adopt_manifests(session, location, root)
    session.commit()
    runner.wake()
    status = storage_manager.active_status(session, fresh=True)
    return {"status": status.to_dict(), "adopted_projects": adopted}


@router.get("/locations", response_model=list[StorageLocationOut])
def list_locations(session: Session = Depends(get_session)):
    active = storage_manager.active_location(session)
    counts = dict(
        session.execute(select(Project.storage_id, func.count()).group_by(Project.storage_id)).all()
    )
    out = []
    for location in session.scalars(select(StorageLocation).order_by(StorageLocation.created_at)):
        status = storage_manager.status_for(location)
        out.append(
            StorageLocationOut(
                id=location.id,
                path=location.path,
                active=active is not None and active.id == location.id,
                available=status.available,
                message=status.message,
                project_count=counts.get(location.id, 0),
                last_seen_at=location.last_seen_at,
            )
        )
    return out


def _shortcuts() -> list[BrowseEntry]:
    items: list[BrowseEntry] = []
    volumes = Path("/Volumes")
    if sys.platform == "darwin" and volumes.is_dir():
        for entry in sorted(volumes.iterdir()):
            if entry.name.startswith(".") or entry.is_symlink() or entry.name == "Recovery":
                continue
            items.append(
                BrowseEntry(name=f"Disco · {entry.name}", path=str(entry), is_storage=False)
            )
    for base in (Path("/media") / os.environ.get("USER", ""), Path("/mnt")):
        if sys.platform.startswith("linux") and base.is_dir():
            for entry in sorted(base.iterdir()):
                items.append(
                    BrowseEntry(name=f"Disco · {entry.name}", path=str(entry), is_storage=False)
                )
    home = Path.home()
    for name, path in (
        ("Inicio", home),
        ("Películas", home / "Movies"),
        ("Documentos", home / "Documents"),
    ):
        if path.is_dir():
            items.append(BrowseEntry(name=name, path=str(path), is_storage=False))
    return items


@router.get("/browse", response_model=BrowseResult)
def browse(path: str | None = Query(default=None, max_length=4096)):
    """Lista subcarpetas (solo carpetas) para elegir el almacenamiento desde el panel."""
    target = (
        normalize_user_path(path)
        if path
        else (Path("/Volumes") if sys.platform == "darwin" else Path.home())
    )
    if not target.is_dir():
        raise StorageError("path_missing", "La carpeta no existe o no está conectada.", 404)
    entries: list[BrowseEntry] = []
    try:
        names = sorted(os.listdir(target), key=str.lower)
    except PermissionError as exc:
        raise StorageError("permission_denied", "Sin permiso para leer esta carpeta.", 403) from exc
    for name in names:
        if name.startswith(".") or name in _HIDDEN:
            continue
        child = target / name
        try:
            # En /Volumes: «Macintosh HD» es un enlace a / y «Recovery» es del sistema.
            if target == Path("/Volumes") and (child.is_symlink() or name == "Recovery"):
                continue
            if not child.is_dir():
                continue
        except OSError:
            continue
        entries.append(
            BrowseEntry(name=name, path=str(child), is_storage=(child / MARKER_NAME).is_file())
        )
    parent = str(target.parent) if target.parent != target else None
    return BrowseResult(path=str(target), parent=parent, entries=entries, shortcuts=_shortcuts())


@router.post("/pick-folder", response_model=PickedFolder)
def pick_folder(session: Session = Depends(get_session)):
    if not native.native_dialogs_supported():
        return PickedFolder(path=None, supported=False)
    current = storage_manager.active_location(session)
    start = current.path if current else ("/Volumes" if sys.platform == "darwin" else None)
    session.close()  # el diálogo puede tardar: no retener la conexión
    chosen = native.pick_folder("Elige la carpeta de almacenamiento de Video Studio AI", start)
    return PickedFolder(path=chosen, supported=True)
