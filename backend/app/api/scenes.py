"""API de escenas (Fase 5): versiones, modificación con Claude, comparación y aplicación."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.jobs.runner import create_job, runner
from app.models import Job, MediaAsset, PlanningSession, Project, new_id
from app.services import animations as anim
from app.services import (
    app_settings,
    claude_budget,
    claude_client,
    planning,
    render_cache,
    render_engine,
    scenes,
)
from app.services import projects as project_service
from app.services.planning import PlanError
from app.services.storage import StorageError, resolve_inside
from app.services.storage_manager import storage_manager

router = APIRouter(tags=["escenas"])


def _project(session: Session, project_id: str) -> tuple[Project, MediaAsset]:
    project = project_service.get_project(session, project_id)
    asset = next((a for a in project.assets if a.role == "source"), None)
    if asset is None:
        raise StorageError("no_source", "El proyecto todavía no tiene video.", 409)
    return project, asset


def _url(project_id: str, iid: str, number: int) -> str:
    return f"/api/projects/{project_id}/scenes/{iid}/versions/{number}/preview/file"


def scene_out(session: Session, project: Project, iid: str) -> dict[str, Any]:
    ap = anim.load_approved(session, project.id)
    with planning.project_lock(project.id):
        in_use = scenes.ensure_in_use(session, ap, iid)
        session.commit()
    iv = scenes.approved_scene(ap, iid)
    rows = scenes.versions(session, ap.plan_id, iid)
    # Dependencias de cada versión frente a la versión aprobada ACTUAL (se recalculan si el plan
    # cambió desde que se calcularon; las propuestas recién creadas ya las traen).
    pending = [
        r for r in rows if r.id != in_use.id and (r.impact or {}).get("plan_version") != ap.version
    ]
    if pending:
        dirs = anim.directions(session, ap)
        for r in pending:
            r.impact = {
                **scenes.impact(ap, dirs, iid, dict(r.intervention), r.direction),
                "plan_version": ap.version,
            }
        session.commit()
    job = scenes.busy_job(session, project.id)
    prefs = app_settings.get_claude(session)
    return {
        "intervention_id": iid,
        "plan_version": ap.version,
        "start": iv["start"],
        "end": iv["end"],
        "type": iv["type"],
        "goal": iv.get("goal"),
        "in_use": in_use.number,
        "versions": [
            scenes.version_out(
                r,
                in_use,
                _url(project.id, iid, r.number) if r.preview.get("file_rel") else None,
            )
            for r in reversed(rows)
        ],
        "job": project_service.job_out(job).model_dump(mode="json") if job else None,
        "budget": {
            **claude_budget.status(session, prefs),
            "estimate": claude_budget.estimate(prefs, "scene_revise").as_dict(),
        },
    }


@router.get("/projects/{project_id}/scenes/{iid}")
def get_scene(project_id: str, iid: str, session: Session = Depends(get_session)):
    project, _ = _project(session, project_id)
    return scene_out(session, project, iid)


class ReviseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=3, max_length=1000)
    # Versión sobre la que se pide el cambio (por defecto, la que está en uso).
    base_number: int | None = None
    confirm_budget: bool = False


def _guard(session: Session, project: Project) -> None:
    if scenes.busy_job(session, project.id) is not None:
        raise PlanError(
            "busy",
            "Hay una tarea de Claude o de animaciones en curso en este proyecto; espera a que "
            "termine o cancélala.",
        )


@router.post("/projects/{project_id}/scenes/{iid}/revise", status_code=202)
def revise_scene(
    project_id: str, iid: str, body: ReviseBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    with planning.project_lock(project.id):
        _guard(session, project)
        ap = anim.load_approved(session, project.id)
        in_use = scenes.ensure_in_use(session, ap, iid)
        base = (
            scenes.get_version(session, ap.plan_id, iid, body.base_number)
            if body.base_number
            else in_use
        )
        dup = scenes.duplicate_of(session, base, body.instruction, ap.version)
        if dup is not None:
            # Misma petición sobre la misma versión: se reutiliza el resultado (sin solicitud).
            session.commit()
            return {"reused": True, "version": dup.number, "job": None}
        prefs = app_settings.get_claude(session)
        if prefs.transport == "claude_code" and claude_client.find_cli(prefs) is None:
            raise PlanError("not_connected", "Claude no está conectado. Revisa Ajustes → Claude.")
        budget = claude_budget.preflight(
            session, prefs, claude_budget.estimate(prefs, "scene_revise"), body.confirm_budget
        )
        row = PlanningSession(
            id=new_id("pls"),
            project_id=project.id,
            plan_id=ap.plan_id,
            operation="scene_revise",
            instruction=body.instruction,
            scope=[iid],
            status="queued",
        )
        session.add(row)
        session.flush()
        job = create_job(
            session,
            "scene_revise",
            project_id=project.id,
            asset_id=asset.id,
            payload={
                "session_id": row.id,
                "intervention_id": iid,
                "instruction": body.instruction,
                "base_number": base.number,
                "budget": budget,
            },
        )
        session.commit()
    runner.wake()
    return {"reused": False, "version": None, "job": {"id": job.id}}


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Versiones a comparar (se renderizan en la misma ventana). Por defecto: esta y la en uso.
    compare_with: int | None = None


@router.post("/projects/{project_id}/scenes/{iid}/versions/{number}/preview", status_code=202)
def preview_version(
    project_id: str,
    iid: str,
    number: int,
    body: PreviewBody,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    with planning.project_lock(project.id):
        _guard(session, project)
        ap = anim.load_approved(session, project.id)
        in_use = scenes.ensure_in_use(session, ap, iid)
        scenes.get_version(session, ap.plan_id, iid, number)
        if not render_engine.status()["ready"]:
            raise PlanError(
                "engine_missing",
                "El motor de animaciones no está listo. Revisa Ajustes → Motor de animaciones.",
            )
        other = body.compare_with or in_use.number
        numbers = sorted({number, other})
        job = create_job(
            session,
            "scene_preview",
            project_id=project.id,
            asset_id=asset.id,
            payload={"intervention_id": iid, "numbers": numbers},
        )
        session.commit()
    runner.wake()
    return {"job": {"id": job.id}}


class ApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False


@router.post("/projects/{project_id}/scenes/{iid}/versions/{number}/apply")
def apply_version(
    project_id: str,
    iid: str,
    number: int,
    body: ApplyBody,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Aprueba esta versión de la escena: nueva versión inmutable del plan con solo esta escena
    cambiada, y generación de los clips que falten (solo lo que cambia; sin Claude)."""
    project, asset = _project(session, project_id)
    if not body.confirm:
        raise PlanError("confirm_required", "Confirma que quieres usar esta versión.", 409)
    with planning.project_lock(project.id):
        _guard(session, project)
        ap = anim.load_approved(session, project.id)
        scenes.ensure_in_use(session, ap, iid)
        row = scenes.get_version(session, ap.plan_id, iid, number)
        if row.applied_plan_version == ap.version:
            raise PlanError("already_in_use", "Esa versión ya es la que está en uso.", 409)
        if row.status == "discarded":
            row.status = "candidate"
        root = storage_manager.require_location(project.storage)
        new_number, info = scenes.apply_version(session, ap, row, root)
        job = create_job(
            session,
            "animations_prepare",
            project_id=project.id,
            asset_id=asset.id,
            payload={"use_claude": False, "only": None, "plan_version": new_number},
        )
        session.commit()
    planning_snapshot(session, project)
    runner.wake()
    return {"plan_version": new_number, "job": {"id": job.id}, **info}


def planning_snapshot(session: Session, project: Project) -> None:
    plan = planning.get_plan(session, project.id)
    if plan is None:
        return
    try:
        root = storage_manager.require_location(project.storage)
    except StorageError:
        return
    planning.write_snapshot(
        root, project, plan, planning.get_version(session, plan, plan.current_version)
    )


@router.post("/projects/{project_id}/scenes/{iid}/versions/{number}/discard")
def discard_version(
    project_id: str, iid: str, number: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    project, _ = _project(session, project_id)
    ap = anim.load_approved(session, project.id)
    row = scenes.get_version(session, ap.plan_id, iid, number)
    if row.status != "candidate":
        raise PlanError("not_candidate", "Solo se pueden descartar propuestas no aplicadas.", 409)
    row.status = "discarded"
    session.commit()
    return scene_out(session, project, iid)


@router.get("/projects/{project_id}/scenes/{iid}/versions/{number}/preview/file")
def preview_file(
    project_id: str, iid: str, number: int, session: Session = Depends(get_session)
) -> FileResponse:
    project, _ = _project(session, project_id)
    plan = planning.require_plan(session, project.id)
    row = scenes.get_version(session, plan.id, iid, number)
    rel = row.preview.get("file_rel")
    if not rel:
        raise PlanError("not_found", "Esta versión aún no tiene vista previa.", 404)
    root = storage_manager.require_location(project.storage)
    path = resolve_inside(root, rel)
    if not path.is_file():
        raise PlanError("not_found", "El archivo de la vista previa ya no existe.", 404)
    return FileResponse(path, media_type="video/mp4")


@router.get("/projects/{project_id}/render-cache")
def render_cache_usage(project_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    project, _ = _project(session, project_id)
    return render_cache.usage(session, project)


class CleanBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False


@router.post("/projects/{project_id}/render-cache/clean")
def render_cache_clean(
    project_id: str, body: CleanBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    """Libera espacio: borra clips y vistas previas regenerables que no usa la versión
    aprobada actual (nunca originales, planes ni exportaciones)."""
    project, _ = _project(session, project_id)
    if not body.confirm:
        raise PlanError("confirm_required", "Confirma la limpieza.", 409)
    with planning.project_lock(project.id):
        _guard(session, project)
        exporting = session.scalar(
            select(Job.id).where(
                Job.project_id == project.id,
                Job.kind == "export",
                Job.status.in_(("queued", "running")),
            )
        )
        if exporting:
            raise PlanError("busy", "Hay una exportación en curso; libera la caché cuando termine.")
        return render_cache.clean(session, project)
