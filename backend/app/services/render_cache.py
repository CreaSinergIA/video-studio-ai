"""Caché de render de un proyecto (Fase 5): medición y limpieza segura.

Solo se consideran los archivos REGENERABLES del motor de animaciones: clips ProRes
(``animations/clips/*.mov``, nombrados por contenido) y vistas previas compuestas
(``previews/animations/*.mp4``). Originales, planes, transcripciones y exportaciones nunca se
tocan. «Sin uso» = no lo referencia la versión aprobada actual del plan (renders y vistas
previas) ni una versión de escena en uso o propuesta. Lo borrado se vuelve a generar si hace
falta (sin solicitudes a Claude: la dirección está en la base de datos).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnimationPreview, AnimationRender, Project, SceneVersion
from app.services import planning
from app.services.storage import resolve_inside
from app.services.storage_manager import storage_manager

_CLIP = re.compile(r"^[0-9a-f]{32}\.mov$")
_PREVIEW = re.compile(r"^[\w\-]+\.mp4$")


def _dirs(project: Project) -> tuple[Path, Path, Path]:
    root = storage_manager.require_location(project.storage)
    pdir = resolve_inside(root, project.dir_rel)
    return root, pdir / "animations" / "clips", pdir / "previews" / "animations"


def _in_use(session: Session, project: Project, root: Path) -> set[Path]:
    plan = planning.get_plan(session, project.id)
    keep: set[Path] = set()
    if plan is None:
        return keep
    if plan.approved_version is not None:
        for r in session.scalars(
            select(AnimationRender).where(
                AnimationRender.plan_id == plan.id,
                AnimationRender.plan_version == plan.approved_version,
            )
        ):
            if r.file_rel:
                keep.add(resolve_inside(root, r.file_rel).resolve())
        for pv in session.scalars(
            select(AnimationPreview).where(
                AnimationPreview.plan_id == plan.id,
                AnimationPreview.plan_version == plan.approved_version,
            )
        ):
            if pv.file_rel:
                keep.add(resolve_inside(root, pv.file_rel).resolve())
    for sv in session.scalars(
        select(SceneVersion).where(
            SceneVersion.plan_id == plan.id, SceneVersion.status.in_(("applied", "candidate"))
        )
    ):
        rel = (sv.preview or {}).get("file_rel")
        if rel:
            keep.add(resolve_inside(root, rel).resolve())
    return keep


def _scan(directory: Path, pattern: re.Pattern[str]) -> list[Path]:
    if not directory.is_dir():
        return []
    return [p for p in directory.iterdir() if p.is_file() and pattern.match(p.name)]


def usage(session: Session, project: Project) -> dict[str, Any]:
    root, clips_dir, prev_dir = _dirs(project)
    keep = _in_use(session, project, root)
    out: dict[str, Any] = {}
    for name, files in (
        ("clips", _scan(clips_dir, _CLIP)),
        ("previews", _scan(prev_dir, _PREVIEW)),
    ):
        unused = [p for p in files if p.resolve() not in keep]
        out[name] = {
            "count": len(files),
            "bytes": sum(p.stat().st_size for p in files),
            "unused_count": len(unused),
            "unused_bytes": sum(p.stat().st_size for p in unused),
        }
    out["unused_bytes"] = out["clips"]["unused_bytes"] + out["previews"]["unused_bytes"]
    out["bytes"] = out["clips"]["bytes"] + out["previews"]["bytes"]
    return out


def clean(session: Session, project: Project) -> dict[str, Any]:
    """Borra solo lo regenerable que no está en uso. Devuelve lo liberado."""
    root, clips_dir, prev_dir = _dirs(project)
    keep = _in_use(session, project, root)
    freed = removed = 0
    for directory, pattern in ((clips_dir, _CLIP), (prev_dir, _PREVIEW)):
        for p in _scan(directory, pattern):
            if p.resolve() in keep:
                continue
            size = p.stat().st_size
            try:
                p.unlink()
            except OSError:
                continue
            freed += size
            removed += 1
    return {"removed": removed, "freed_bytes": freed, **usage(session, project)}
