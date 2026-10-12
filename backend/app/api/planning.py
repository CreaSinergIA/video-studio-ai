"""API de la Fase 3: conexión con Claude y planificación de la edición."""

from __future__ import annotations

import subprocess
import sys
import time
from typing import Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db import get_session
from app.domain.edit_config import StyleId
from app.domain.edit_plan import INTERVENTION_LABELS, PLAN_STATUS_LABELS
from app.domain.preferences import ClaudePreferences
from app.jobs.runner import create_job, runner
from app.models import EditPlan, MediaAsset, PlanningSession, Project, new_id, utcnow
from app.services import (
    analysis_bundle,
    app_settings,
    claude_budget,
    claude_client,
    plan_context,
    planning,
)
from app.services import projects as project_service
from app.services.plan_context import PlanInputError
from app.services.plan_validation import Validator, approval_problems
from app.services.planning import PlanError
from app.services.storage import StorageError, resolve_inside
from app.services.storage_manager import storage_manager

router = APIRouter(tags=["planificación"])


# ---------------------------------------------------------------------------
# Conexión con Claude
# ---------------------------------------------------------------------------


@router.get("/claude/settings", response_model=ClaudePreferences)
def get_claude_settings(session: Session = Depends(get_session)):
    return app_settings.get_claude(session)


@router.put("/claude/settings", response_model=ClaudePreferences)
def put_claude_settings(body: ClaudePreferences, session: Session = Depends(get_session)):
    return app_settings.save_claude(session, body)


@router.get("/claude/status")
def claude_status(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Estado local (sin enviar nada al modelo) + resultado de la última prueba real."""
    prefs = app_settings.get_claude(session)
    last = app_settings.get_claude_status(session)
    out: dict[str, Any] = {
        "transport": prefs.transport,
        "model": prefs.model,
        "effort": prefs.effort,
        "last_check": last or None,
        "api_key_saved": claude_client.keychain_has_key() if sys.platform == "darwin" else False,
    }
    if prefs.transport == "claude_code":
        cli = claude_client.cli_status(prefs)
        out["cli"] = cli
        out["ready"] = bool(
            cli.get("installed")
            and cli.get("logged_in")
            and cli.get("api_provider") in (None, "firstParty")
        )
        out["billing"] = "subscription"
    else:
        out["cli"] = None
        out["ready"] = out["api_key_saved"]
        out["billing"] = "api"
    # «Conectado» solo si además la última prueba real con esta configuración fue correcta.
    out["verified"] = bool(
        out["ready"]
        and last
        and last.get("ok")
        and last.get("transport") == prefs.transport
        and last.get("model") == prefs.model
    )
    return out


class _TestSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    reply: str = Field(max_length=200)


@router.post("/claude/test")
def claude_test(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Solicitud real mínima: comprueba autenticación, modelo y esfuerzo (consume muy poco)."""
    prefs = app_settings.get_claude(session)
    started = time.monotonic()
    status: dict[str, Any] = {
        "checked_at": utcnow().isoformat(),
        "transport": prefs.transport,
        "model": prefs.model,
        "effort": prefs.effort,
    }
    base = {
        "step": "test",
        "transport": prefs.transport,
        "model": prefs.model,
        "effort": prefs.effort,
        "billing": "api" if prefs.transport == "api" else "subscription",
        "sent": {"content": "mensaje de prueba sin datos del usuario", "frame_count": 0},
    }
    test_prefs = prefs.model_copy(update={"timeout_seconds": 90, "max_budget_usd_per_call": 0.5})
    try:
        result = claude_client.run(
            test_prefs,
            "Responde solo con el JSON pedido.",
            [
                claude_client.text_block(
                    "Prueba de conexión de Video Studio AI: responde ok=true y reply='listo'."
                )
            ],
            _TestSchema.model_json_schema(),
        )
    except claude_client.ClaudeError as exc:
        status.update(ok=False, error=exc.message, code=exc.code)
        planning.record_call(
            session,
            status="error",
            error=f"{exc.code}: {exc.message}",
            duration_ms=int((time.monotonic() - started) * 1000),
            **base,
        )
        app_settings.save_claude_status(session, status)
        return status
    status.update(
        ok=result.model_reported == prefs.model and bool(result.data.get("ok")),
        model_reported=result.model_reported,
        duration_ms=result.duration_ms,
        billing=result.billing,
        rate_limit=result.rate_limit,
        cost_estimate_usd=result.cost_estimate_usd,
        usage=result.usage,
        cli_version=result.extra.get("cli_version"),
    )
    if result.model_reported != prefs.model:
        status["error"] = f"Respondió otro modelo: {result.model_reported}"
    planning.record_call(
        session,
        status="ok" if status["ok"] else "invalid",
        model_reported=result.model_reported,
        duration_ms=result.duration_ms,
        cost_estimate_usd=result.cost_estimate_usd,
        rate_limit=result.rate_limit,
        **result.usage,
        **{**base, "billing": result.billing},
    )
    app_settings.save_claude_status(session, status)
    return status


class ApiKeyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=20, max_length=300, pattern=r"^sk-ant-[A-Za-z0-9_\-]+$")


@router.put("/claude/api-key", status_code=204)
def put_api_key(body: ApiKeyBody) -> None:
    claude_client.keychain_set(body.key)


@router.delete("/claude/api-key", status_code=204)
def delete_api_key() -> None:
    claude_client.keychain_delete()


@router.post("/claude/login")
def open_login(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Abre Terminal con el inicio de sesión oficial de Claude Code (única acción manual)."""
    prefs = app_settings.get_claude(session)
    cli = claude_client.find_cli(prefs)
    if cli is None:
        raise StorageError("not_installed", "No se encontró Claude Code en este equipo.", 404)
    if sys.platform != "darwin":
        return {"opened": False, "command": f"{cli} auth login"}
    script = [
        "on run argv",
        'tell application "Terminal" to do script '
        '((quoted form of (item 1 of argv)) & " auth login")',
        'tell application "Terminal" to activate',
        "end run",
    ]
    args = [x for line in script for x in ("-e", line)]
    subprocess.run(["osascript", *args, str(cli)], capture_output=True, timeout=10)
    return {"opened": True}


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def _project(session: Session, project_id: str) -> tuple[Project, MediaAsset]:
    project = project_service.get_project(session, project_id)
    asset = next((a for a in project.assets if a.role == "source"), None)
    if asset is None:
        raise StorageError("no_source", "El proyecto todavía no tiene video.", 409)
    return project, asset


def _validator(session: Session, project: Project, style: StyleId) -> Validator | None:
    try:
        root = storage_manager.require_location(project.storage)
        return Validator(plan_context.gather(session, project, root, style))
    except (StorageError, PlanInputError):
        return None


def _snapshot(session: Session, project: Project, plan: EditPlan) -> None:
    try:
        root = storage_manager.require_location(project.storage)
    except StorageError:
        return
    planning.write_snapshot(
        root, project, plan, planning.get_version(session, plan, plan.current_version)
    )


def plan_out(session: Session, project: Project, asset: MediaAsset) -> dict[str, Any]:
    plan = planning.get_plan(session, project.id)
    job = planning.active_job(session, project.id)
    sessions = planning.sessions_for(session, project.id, 15)
    visual = analysis_bundle.active_visual(session, asset.id)
    frames = analysis_bundle.frames_for(session, visual.id if visual else None, asset.id)
    out: dict[str, Any] = {
        "plan": None,
        "job": project_service.job_out(job).model_dump(mode="json") if job else None,
        "sessions": [
            {
                "id": r.id,
                "operation": r.operation,
                "instruction": r.instruction,
                "scope": r.scope,
                "status": r.status,
                "strategy": r.strategy,
                "result_version": r.result_version,
                "summary": r.summary,
                "error": r.error,
                "created_at": r.created_at.isoformat(),
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in sessions
        ],
        "frames": {f.id: analysis_bundle.frame_ref(f) for f in frames},
        "labels": {"types": INTERVENTION_LABELS, "statuses": PLAN_STATUS_LABELS},
        "ready_to_plan": visual is not None,
    }
    if plan is None or plan.current_version == 0:
        return out
    version = planning.get_version(session, plan, plan.current_version)
    doc = planning.doc_of(version)
    stale = planning.staleness(session, version, asset)
    accepted_hit = sorted(
        i.id for i in doc.interventions if i.status == "accepted" and i.id in stale["affected"]
    )
    last = (plan.status_history or [{}])[-1]
    if (
        accepted_hit
        and job is None
        and plan.status in ("in_review", "approved")
        and last.get("stale_key") != accepted_hit
    ):
        # Pedir revisión sin destruir nada: una sola vez por cada cambio detectado.
        what = "el video base" if stale["asset_changed"] else "la transcripción o el análisis"
        planning.set_status(
            plan,
            "needs_changes",
            f"Cambió {what}: {len(accepted_hit)} intervención(es) aceptada(s) a revisar",
        )
        plan.status_history[-1]["stale_key"] = accepted_hit
        flag_modified(plan, "status_history")
        session.commit()
    for i in doc.interventions:
        if i.id in stale["affected"]:
            i.stale, i.stale_reason = True, stale["affected"][i.id]
    children = planning.redo_available(session, plan)
    out["plan"] = {
        "id": plan.id,
        "status": plan.status,
        "status_label": PLAN_STATUS_LABELS.get(plan.status, plan.status),
        "status_history": plan.status_history,
        "current_version": plan.current_version,
        "approved_version": plan.approved_version,
        "version": {
            "number": version.number,
            "parent_number": version.parent_number,
            "kind": version.kind,
            "summary": version.summary,
            "instruction": version.instruction,
            "created_at": version.created_at.isoformat(),
            "model": version.model,
            "effort": version.effort,
            "immutable": version.immutable,
        },
        "document": doc.model_dump(mode="json"),
        "staleness": stale,
        "can_undo": version.parent_number is not None,
        "can_redo": children,
        "approval_problems": approval_problems(doc, set(stale["affected"])),
    }
    return out


@router.get("/projects/{project_id}/plan")
def get_plan(project_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    return plan_out(session, project, asset)


class GenerateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style: StyleId | None = None
    instruction: str | None = Field(default=None, max_length=2000)
    # Confirmación explícita para superar el límite autorizado de solicitudes (solo esta vez).
    confirm_budget: bool = False


class ReviseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str = Field(min_length=2, max_length=2000)
    scope: list[str] = Field(default_factory=list, max_length=50)
    confirm_budget: bool = False


class AlternativeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instruction: str | None = Field(default=None, max_length=2000)
    confirm_budget: bool = False


def _plan_units(session: Session, project: Project, style: StyleId | None) -> int:
    """Solicitudes que necesita generar el plan: 1, o 1 + tramos si el video es largo."""
    try:
        root = storage_manager.require_location(project.storage)
        inputs = plan_context.gather(session, project, root, style)
    except (StorageError, PlanInputError):
        return 1
    if not plan_context.needs_hierarchy(inputs):
        return 1
    return 1 + len(plan_context.chunk_windows(inputs))


def _launch(
    session: Session,
    project: Project,
    asset: MediaAsset,
    kind: str,
    operation: str,
    payload: dict[str, Any],
    instruction: str | None,
    scope: list[str],
    transient: tuple[str, str] | None = None,
    *,
    units: int = 1,
    confirm_budget: bool = False,
) -> dict[str, Any]:
    """Crea la solicitud a Claude bajo el candado del proyecto (nunca dos a la vez).

    ``transient`` = (estado, nota) que adopta el plan mientras Claude trabaja; el estado previo
    viaja en la tarea para restaurarlo si la solicitud falla o se cancela.
    """
    with planning.project_lock(project.id):
        if planning.active_job(session, project.id) is not None:
            raise PlanError(
                "plan_busy",
                "Ya hay una solicitud a Claude en curso para este proyecto; espera a que termine "
                "o cancélala.",
            )
        prefs = app_settings.get_claude(session)
        if prefs.transport == "claude_code" and claude_client.find_cli(prefs) is None:
            raise PlanError(
                "not_connected", "Claude no está conectado. Revisa Ajustes → Claude.", 409
            )
        if analysis_bundle.active_visual(session, asset.id) is None:
            raise PlanError(
                "not_analyzed", "Primero analiza el video (botón «Analizar video»).", 409
            )
        budget = claude_budget.preflight(
            session, prefs, claude_budget.estimate(prefs, operation, units), confirm_budget
        )
        plan = planning.get_plan(session, project.id)
        prev = plan.status if plan is not None and plan.current_version else None
        if transient and plan is not None and prev is not None:
            planning.set_status(plan, transient[0], transient[1])
        row = PlanningSession(
            id=new_id("pls"),
            project_id=project.id,
            operation=operation,
            instruction=instruction,
            scope=scope,
            status="queued",
        )
        session.add(row)
        session.flush()
        job = create_job(
            session,
            kind,
            project_id=project.id,
            asset_id=asset.id,
            payload={
                **payload,
                "session_id": row.id,
                "project_id": project.id,
                "budget": budget,
                "prev_status": prev,
                "transient_status": transient[0] if transient else None,
            },
        )
        row.job_id = job.id
        session.commit()
    runner.wake()
    return {"job": project_service.job_out(job).model_dump(mode="json"), "session_id": row.id}


@router.post("/projects/{project_id}/plan/generate", status_code=202)
def generate(
    project_id: str, body: GenerateBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    return _launch(
        session,
        project,
        asset,
        "plan_generate",
        "generate",
        {"style": body.style, "instruction": body.instruction},
        body.instruction,
        [],
        transient=("draft", "Nueva propuesta solicitada"),
        units=_plan_units(session, project, body.style),
        confirm_budget=body.confirm_budget,
    )


@router.post("/projects/{project_id}/plan/revise", status_code=202)
def revise(
    project_id: str, body: ReviseBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    planning.require_plan(session, project.id)
    return _launch(
        session,
        project,
        asset,
        "plan_revise",
        "revise",
        {"instruction": body.instruction, "scope": body.scope, "mode": "revise"},
        body.instruction,
        body.scope,
        transient=("needs_changes", f"Corrección solicitada: {body.instruction[:200]}"),
        confirm_budget=body.confirm_budget,
    )


@router.post("/projects/{project_id}/plan/interventions/{iid}/alternative", status_code=202)
def alternative(
    project_id: str, iid: str, body: AlternativeBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    planning.require_plan(session, project.id)
    return _launch(
        session,
        project,
        asset,
        "plan_revise",
        "alternative",
        {"instruction": body.instruction or "", "scope": [iid], "mode": "alternative"},
        body.instruction,
        [iid],
        confirm_budget=body.confirm_budget,
    )


class InterventionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["proposed", "accepted", "rejected", "needs_changes"] | None = None
    type: str | None = None
    user_note: str | None = Field(default=None, max_length=1000)


def _guard_idle(session: Session, project_id: str) -> None:
    if planning.active_job(session, project_id) is not None:
        raise PlanError("plan_busy", "Claude está modificando el plan; espera a que termine.")


@router.patch("/projects/{project_id}/plan/interventions/{iid}")
def patch_intervention(
    project_id: str, iid: str, body: InterventionPatch, session: Session = Depends(get_session)
) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    with planning.project_lock(project.id):
        _guard_idle(session, project.id)
        plan = planning.require_plan(session, project.id)
        doc = planning.doc_of(planning.get_version(session, plan, plan.current_version))
        planning.update_intervention(
            session,
            plan,
            _validator(session, project, doc.style),
            iid,
            status=body.status,
            type_=body.type,
            user_note=body.user_note,
        )
        session.commit()
        _snapshot(session, project, plan)
    return plan_out(session, project, asset)


class BulkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["accepted", "rejected"]


@router.post("/projects/{project_id}/plan/bulk")
def bulk(
    project_id: str, body: BulkBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    with planning.project_lock(project.id):
        _guard_idle(session, project.id)
        plan = planning.require_plan(session, project.id)
        doc = planning.doc_of(planning.get_version(session, plan, plan.current_version))
        planning.bulk_status(session, plan, _validator(session, project, doc.style), body.status)
        session.commit()
        _snapshot(session, project, plan)
    return plan_out(session, project, asset)


@router.post("/projects/{project_id}/plan/undo")
def undo(project_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    with planning.project_lock(project.id):
        _guard_idle(session, project.id)
        plan = planning.require_plan(session, project.id)
        planning.undo(session, plan)
        session.commit()
        _snapshot(session, project, plan)
    return plan_out(session, project, asset)


@router.post("/projects/{project_id}/plan/redo")
def redo(project_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    with planning.project_lock(project.id):
        _guard_idle(session, project.id)
        plan = planning.require_plan(session, project.id)
        planning.redo(session, plan)
        session.commit()
        _snapshot(session, project, plan)
    return plan_out(session, project, asset)


@router.post("/projects/{project_id}/plan/versions/{number}/restore")
def restore(
    project_id: str, number: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    with planning.project_lock(project.id):
        _guard_idle(session, project.id)
        plan = planning.require_plan(session, project.id)
        planning.restore(session, plan, number)
        session.commit()
        _snapshot(session, project, plan)
    return plan_out(session, project, asset)


@router.get("/projects/{project_id}/plan/versions")
def versions(project_id: str, session: Session = Depends(get_session)) -> list[dict[str, Any]]:
    project, _ = _project(session, project_id)
    plan = planning.get_plan(session, project.id)
    if plan is None:
        return []
    return [
        {
            "number": v.number,
            "parent_number": v.parent_number,
            "kind": v.kind,
            "summary": v.summary,
            "instruction": v.instruction,
            "created_at": v.created_at.isoformat(),
            "immutable": v.immutable,
            "current": v.number == plan.current_version,
            "approved": v.number == plan.approved_version,
            "interventions": len(v.document.get("interventions") or []),
            "model": v.model,
        }
        for v in planning.list_versions(session, plan)
    ]


@router.get("/projects/{project_id}/plan/versions/{number}")
def version_detail(
    project_id: str, number: int, session: Session = Depends(get_session)
) -> dict[str, Any]:
    project, _ = _project(session, project_id)
    plan = planning.require_plan(session, project.id)
    v = planning.get_version(session, plan, number)
    return {
        "number": v.number,
        "kind": v.kind,
        "summary": v.summary,
        "document": v.document,
        "immutable": v.immutable,
    }


class StatusBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["draft", "in_review", "rejected", "needs_changes"]
    note: str = Field(default="", max_length=500)


@router.post("/projects/{project_id}/plan/status")
def change_status(
    project_id: str, body: StatusBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    with planning.project_lock(project.id):
        _guard_idle(session, project.id)
        plan = planning.require_plan(session, project.id)
        planning.set_status(plan, body.status, body.note or PLAN_STATUS_LABELS[body.status])
        session.commit()
    return plan_out(session, project, asset)


@router.post("/projects/{project_id}/plan/refresh")
def refresh(project_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    with planning.project_lock(project.id):
        _guard_idle(session, project.id)
        plan = planning.require_plan(session, project.id)
        doc = planning.doc_of(planning.get_version(session, plan, plan.current_version))
        root = storage_manager.require_location(project.storage)
        inputs = plan_context.gather(session, project, root, doc.style)
        stale = planning.staleness(
            session, planning.get_version(session, plan, plan.current_version), asset
        )
        planning.refresh_timings(
            session, plan, Validator(inputs), planning.base_of(inputs), stale["affected"]
        )
        session.commit()
        _snapshot(session, project, plan)
    return plan_out(session, project, asset)


class ApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(default="", max_length=500)


@router.post("/projects/{project_id}/plan/approve")
def approve(
    project_id: str, body: ApproveBody, session: Session = Depends(get_session)
) -> dict[str, Any]:
    project, asset = _project(session, project_id)
    with planning.project_lock(project.id):
        _guard_idle(session, project.id)
        plan = planning.require_plan(session, project.id)
        root = storage_manager.require_location(project.storage)
        planning.approve(session, plan, project, asset, root, body.note)
        session.commit()
        _snapshot(session, project, plan)
    return plan_out(session, project, asset)


@router.get("/projects/{project_id}/plan/approved")
def approved_contract(project_id: str, session: Session = Depends(get_session)):
    """Contrato del plan aprobado que consumirá la Fase 4."""
    project, asset = _project(session, project_id)
    plan = planning.get_plan(session, project.id)
    if plan is None or plan.approved_version is None:
        raise PlanError("not_approved", "Este proyecto no tiene un plan aprobado.", 404)
    v = planning.get_version(session, plan, plan.approved_version)
    contract = planning.build_contract(project, asset, plan, v, planning.doc_of(v))
    try:
        root = storage_manager.require_location(project.storage)
        rel = f"{project.dir_rel}/plans/approved_v{v.number}.json"
        contract["file"] = rel if resolve_inside(root, rel).is_file() else None
    except StorageError:
        contract["file"] = None
    return JSONResponse(contract)


@router.get("/projects/{project_id}/usage")
def usage(project_id: str, session: Session = Depends(get_session)) -> dict[str, Any]:
    project, _ = _project(session, project_id)
    return planning.usage_for_project(session, project.id)


@router.get("/claude/budget")
def budget_status(session: Session = Depends(get_session)) -> dict[str, Any]:
    """Solicitudes usadas frente al límite autorizado (24 h) y estimaciones por operación."""
    prefs = app_settings.get_claude(session)
    return {
        **claude_budget.status(session, prefs),
        "estimates": {
            op: claude_budget.estimate(prefs, op).as_dict()
            for op in ("generate", "revise", "alternative", "scene_revise")
        },
    }


@router.get("/claude/usage")
def global_usage(days: int = 30, session: Session = Depends(get_session)) -> dict[str, Any]:
    return claude_budget.global_usage(session, max(1, min(days, 365)))
