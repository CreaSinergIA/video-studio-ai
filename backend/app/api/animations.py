"""API de la Fase 4: motor de animaciones, generación, vistas previas y efectos."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.jobs.runner import ACTIVE_STATUSES, create_job, runner
from app.models import AnimationPreview, AnimationRender, Job, MediaAsset, Project
from app.services import animations as anim
from app.services import app_settings, claude_budget, layout_engine, planning, render_engine, sfx
from app.services import projects as project_service
from app.services.planning import PlanError
from app.services.storage import StorageError, resolve_inside
from app.services.storage_manager import storage_manager

router = APIRouter(tags=["animaciones"])
ANIM_JOBS = ("animations_prepare", "animation_preview", "scene_revise", "scene_preview")


# --- motor -------------------------------------------------------------------


@router.get("/animations/engine")
def engine_status(session: Session = Depends(get_session)) -> dict[str, Any]:
    st = render_engine.status()
    job = session.scalar(
        select(Job).where(Job.kind == "engine_install", Job.status.in_(ACTIVE_STATUSES))
    )
    st["job"] = project_service.job_out(job).model_dump(mode="json") if job else None
    return st


@router.post("/animations/engine/install", status_code=202)
def engine_install(session: Session = Depends(get_session)) -> dict[str, Any]:
    if render_engine.browser_executable() is not None:
        return {"already_installed": True}
    running = session.scalar(
        select(Job).where(Job.kind == "engine_install", Job.status.in_(ACTIVE_STATUSES))
    )
    if running is not None:
        return {"job": project_service.job_out(running).model_dump(mode="json")}
    job = create_job(session, "engine_install")
    session.commit()
    runner.wake()
    return {"job": project_service.job_out(job).model_dump(mode="json")}


@router.get("/animations/safe-zones")
def safe_zones() -> list[dict[str, Any]]:
    """Perfiles de zonas seguras por red social (para las guías del panel)."""
    return [layout_engine.platform_payload(p) for p in layout_engine.PLATFORM_NAMES]


@router.get("/projects/{project_id}/animations/layout")
def animations_layout(project_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    """Encuadre previsto de las animaciones del plan aprobado, sin renderizar: regiones,
    zonas protegidas y avisos, para revisarlo antes de generar."""
    project, asset = _project(session, project_id)
    plan = planning.get_plan(session, project.id)
    if plan is None or plan.approved_version is None:
        return {"approved_version": None, "items": [], "warnings": []}
    try:
        ap = anim.load_approved(session, project.id)
    except PlanError:
        return {"approved_version": plan.approved_version, "items": [], "warnings": []}
    config = anim.current_config(ap)
    w, h = asset.display_width, asset.display_height
    zones = layout_engine.ui_zones(config.delivery.platform, w, h)
    band = anim.subtitle_band(ap)
    compiled = anim.compile_all(ap, "preview", anim.directions(session, ap), size=(w, h, 30.0))
    warnings = []
    if band and zones:
        # Solo cuentan las zonas con contenido de la interfaz (no los márgenes laterales finos).
        hit = [
            z
            for z in layout_engine.overlaps(layout_engine.subtitle_zone(band)[0].rect(), zones)
            if z.w > 0.1
        ]
        if hit:
            warnings.append({
                "code": "subtitles_under_ui",
                "message": (
                    "Los subtítulos quedan en la zona de la interfaz ("
                    + "; ".join(z.label for z in hit)
                    + "). Súbelos en Edición → Subtítulos (posición) si van a publicarse ahí."
                ),
            })  # fmt: skip
    if not zones and config.delivery.platform != "none" and h <= w * 1.1:
        warnings.append({
            "code": "horizontal",
            "message": (
                "Video horizontal: las zonas de Reels y TikTok solo se aplican a videos "
                "verticales."
            ),
        })  # fmt: skip
    return {
        "approved_version": ap.version,
        "platform": layout_engine.platform_payload(config.delivery.platform),
        "applies": bool(zones),
        "subtitle_band": list(band) if band else None,
        "warnings": warnings,
        "items": [
            {
                "intervention_id": c["iv"]["id"],
                "start": c["iv"]["start"],
                "end": c["iv"]["end"],
                "type": c["iv"]["type"],
                "mode": c["spec"]["mode"],
                "template": c["spec"]["template"],
                "region": c["spec"]["region"],
                "pip": c["spec"].get("pip"),
                "faces": c["iv"].get("protected_regions") or [],
                "warnings": c.get("warnings", []),
            }
            for c in compiled
        ],
    }


@router.get("/animations/sfx")
def sfx_catalog() -> list[dict[str, Any]]:
    return sfx.catalog()


@router.get("/animations/sfx/{kind}")
def sfx_file(kind: str):
    if kind not in sfx.KINDS:
        raise StorageError("not_found", "Efecto desconocido.", 404)
    return FileResponse(sfx.path_for(kind), media_type="audio/wav")


# --- animaciones del proyecto ----------------------------------------------------


def _project(session: Session, project_id: str) -> tuple[Project, MediaAsset]:
    project = project_service.get_project(session, project_id)
    asset = next((a for a in project.assets if a.role == "source"), None)
    if asset is None:
        raise StorageError("no_source", "El proyecto todavía no tiene video.", 409)
    return project, asset


def _active(session: Session, project_id: str) -> Job | None:
    return session.scalar(
        select(Job).where(
            Job.project_id == project_id, Job.kind.in_(ANIM_JOBS), Job.status.in_(ACTIVE_STATUSES)
        )
    )


@router.get("/projects/{project_id}/animations")
def animations_state(project_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    project, _ = _project(session, project_id)
    plan = planning.get_plan(session, project.id)
    job = _active(session, project.id)
    exporting = (
        session.scalar(
            select(Job).where(
                Job.project_id == project.id, Job.kind == "export", Job.status.in_(ACTIVE_STATUSES)
            )
        )
        is not None
    )
    out: dict[str, Any] = {
        "approved_version": plan.approved_version if plan else None,
        "engine_ready": render_engine.status()["ready"],
        "job": project_service.job_out(job).model_dump(mode="json") if job else None,
        # Una exportación con animaciones también genera las que falten.
        "exporting": exporting,
        "items": [],
        "summary": {},
    }
    if plan is None or plan.approved_version is None:
        return out
    v = planning.get_version(session, plan, plan.approved_version)
    doc = planning.doc_of(v)
    renders = {
        r.intervention_id: r
        for r in session.scalars(
            select(AnimationRender).where(
                AnimationRender.plan_id == plan.id,
                AnimationRender.plan_version == plan.approved_version,
                AnimationRender.purpose == "final",
            )
        )
    }
    previews: dict[str, AnimationPreview] = {}
    for prev in session.scalars(
        select(AnimationPreview)
        .where(
            AnimationPreview.plan_id == plan.id,
            AnimationPreview.plan_version == plan.approved_version,
        )
        .order_by(AnimationPreview.created_at)
    ):
        previews[prev.intervention_id] = prev
    running_preview = None
    if job is not None and job.kind == "animation_preview":
        running_preview = (job.payload or {}).get("intervention_id")
    counts = {"ready": 0, "failed": 0, "pending": 0, "rendering": 0, "kept": 0}
    for i in doc.interventions:
        if i.status != "accepted":
            continue
        if i.type in anim.PASSIVE:
            status = "kept"
        else:
            r = renders.get(i.id)
            status = r.status if r else "pending"
            if (
                status == "rendering"
                and not exporting
                and (job is None or job.kind != "animations_prepare")
            ):
                status = "pending"  # quedó a medias por un cierre: se volverá a generar
        counts[status] = counts.get(status, 0) + 1
        r = renders.get(i.id)
        pv = previews.get(i.id)
        out["items"].append({
            "intervention_id": i.id,
            "type": i.type,
            "start": i.start,
            "end": i.end,
            "goal": i.goal,
            "status": status,
            "template": (r.extra or {}).get("template") if r else None,
            "direction": (r.extra or {}).get("direction") if r else None,
            "notes": (r.extra or {}).get("notes", []) if r else [],
            "warnings": (r.extra or {}).get("warnings", []) if r else [],
            "reused": bool((r.extra or {}).get("reused")) if r else False,
            "error": r.error if r else None,
            "render_ms": r.render_ms if r else None,
            "size": [r.width, r.height, r.fps] if r else None,
            "preview": {
                "id": pv.id,
                "url": f"/api/animations/previews/{pv.id}/file",
                "window": [pv.window_start, pv.window_end],
            } if pv else None,
            "preview_running": running_preview == i.id,
        })  # fmt: skip
    out["summary"] = counts
    return out


class PrepareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    use_claude: bool = True
    only: list[str] | None = None
    confirm_budget: bool = False


def _launch(
    session: Session, project: Project, asset: MediaAsset, kind: str, payload: dict[str, Any]
) -> dict[str, Any]:
    with planning.project_lock(project.id):
        if _active(session, project.id) is not None:
            raise PlanError(
                "animations_busy",
                "Ya hay una generación o vista previa en curso para este proyecto.",
            )
        plan = planning.get_plan(session, project.id)
        if plan is None or plan.approved_version is None:
            raise PlanError("not_approved", "Primero aprueba el plan de edición (pestaña Plan IA).")
        if not render_engine.status()["ready"]:
            raise PlanError(
                "engine_missing",
                "El motor de animaciones no está listo. Revisa Ajustes → Motor de animaciones.",
            )
        storage_manager.require_location(project.storage)
        job = create_job(
            session,
            kind,
            project_id=project.id,
            asset_id=asset.id,
            payload={**payload, "plan_version": plan.approved_version},
        )
        session.commit()
    runner.wake()
    return {"job": project_service.job_out(job).model_dump(mode="json")}


@router.post("/projects/{project_id}/animations/prepare", status_code=202)
def prepare(
    project_id: str, body: PrepareBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    payload: dict[str, Any] = {"use_claude": body.use_claude, "only": body.only}
    if body.use_claude:
        # Presupuesto: un lote por cada 10 animaciones sin dirección (tras reutilizar la de
        # versiones idénticas del plan, que no cuesta solicitudes).
        try:
            ap = anim.load_approved(session, project.id)
        except PlanError:
            ap = None
        if ap is not None:
            anim.reuse_directions(session, ap)
            session.commit()
            have = anim.directions(session, ap)
            only = set(body.only or [])
            missing = [
                i["id"]
                for i in ap.animated()
                if i["id"] not in have and (not only or i["id"] in only)
            ]
            if missing:
                prefs = app_settings.get_claude(session)
                payload["budget"] = claude_budget.preflight(
                    session,
                    prefs,
                    claude_budget.estimate(
                        prefs, "animate", claude_budget.animate_units(len(missing))
                    ),
                    body.confirm_budget,
                )
    return _launch(session, project, asset, "animations_prepare", payload)


@router.post("/projects/{project_id}/animations/{iid}/preview", status_code=202)
def preview(project_id: str, iid: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    plan = planning.get_plan(session, project.id)
    if plan is not None and plan.approved_version is not None:
        doc = planning.doc_of(planning.get_version(session, plan, plan.approved_version))
        if not any(
            i.id == iid and i.status == "accepted" and i.type not in anim.PASSIVE
            for i in doc.interventions
        ):
            raise PlanError(
                "not_animated",
                "Esa intervención no tiene animación en el plan aprobado.",
                404,
            )
    return _launch(session, project, asset, "animation_preview", {"intervention_id": iid})


@router.get("/animations/previews/{preview_id}/file")
def preview_file(preview_id: str, session: Session = Depends(get_session, scope="function")):
    pv = session.get(AnimationPreview, preview_id)
    if pv is None or not pv.file_rel:
        raise StorageError("not_found", "Vista previa no encontrada.", 404)
    project = session.get(Project, pv.project_id)
    assert project is not None
    root = storage_manager.require_location(project.storage)
    path = resolve_inside(root, pv.file_rel)
    if not path.is_file():
        raise StorageError("not_found", "El archivo de la vista previa ya no existe.", 404)
    return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "no-cache"})
