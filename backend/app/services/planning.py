"""Planes de edición: versiones, estados, correcciones, aprobación y consumo (Fase 3).

- Cada cambio crea una **versión** nueva (instantánea completa); nada se sobrescribe.
  Deshacer/rehacer mueven el puntero ``current_version`` por la cadena de versiones.
- Los **estados** del plan (borrador, en revisión, aprobado, rechazado, requiere corrección)
  guardan su historial. Aprobar crea una versión inmutable y escribe el **contrato** que
  consumirá la Fase 4 (``plans/approved_vN.json`` en la carpeta del proyecto).
- Si cambian la transcripción, el análisis o el video base, se detectan las intervenciones
  afectadas y se pide revisión sin destruir versiones anteriores.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.edit_plan import (
    INTERVENTION_LABELS,
    PASSIVE_TYPES,
    PLAN_SCHEMA_VERSION,
    PLAN_STATUS_LABELS,
    PlanDocument,
    PlanIntervention,
    ProposalIntervention,
    ProposalRevision,
    RevisedIntervention,
    StatusEvent,
)
from app.models import (
    ClaudeCall,
    EditPlan,
    EditPlanVersion,
    Job,
    MediaAsset,
    PlanningSession,
    Project,
    new_id,
    utcnow,
)
from app.services import analysis_bundle
from app.services import transcripts as transcript_service
from app.services.plan_context import (
    PlanInputs,
    asset_fingerprint,
    config_hash,
    transcript_fingerprint,
)
from app.services.plan_validation import Validator, approval_problems
from app.services.storage import atomic_write_json, resolve_inside

CONTRACT_VERSION = 1
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def project_lock(project_id: str) -> threading.Lock:
    """Serializa las escrituras del plan de un proyecto (pestañas o tareas concurrentes)."""
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(project_id, threading.Lock())


PLAN_JOB_KINDS = ("plan_generate", "plan_revise", "scene_revise")


class PlanError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 409,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


# ---------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------


def get_plan(session: Session, project_id: str) -> EditPlan | None:
    return session.scalar(
        select(EditPlan)
        .where(EditPlan.project_id == project_id)
        .order_by(EditPlan.created_at.desc())
    )


def require_plan(session: Session, project_id: str) -> EditPlan:
    plan = get_plan(session, project_id)
    if plan is None or plan.current_version == 0:
        raise PlanError("no_plan", "Este proyecto aún no tiene un plan de edición.", 404)
    return plan


def get_version(session: Session, plan: EditPlan, number: int) -> EditPlanVersion:
    v = session.scalar(
        select(EditPlanVersion).where(
            EditPlanVersion.plan_id == plan.id, EditPlanVersion.number == number
        )
    )
    if v is None:
        raise PlanError("version_not_found", f"No existe la versión {number} del plan.", 404)
    return v


def doc_of(version: EditPlanVersion) -> PlanDocument:
    return PlanDocument.model_validate(version.document)


def active_job(session: Session, project_id: str) -> Job | None:
    return session.scalar(
        select(Job).where(
            Job.project_id == project_id,
            Job.kind.in_(PLAN_JOB_KINDS),
            Job.status.in_(("queued", "running")),
        )
    )


# ---------------------------------------------------------------------------
# Versiones y estados
# ---------------------------------------------------------------------------


def base_of(inputs: PlanInputs) -> dict[str, Any]:
    return {
        "transcript_id": inputs.transcript.id if inputs.transcript else None,
        "transcript_fingerprint": transcript_fingerprint(inputs.transcript),
        "analysis_id": inputs.analysis_id,
        "asset_fingerprint": asset_fingerprint(inputs.asset),
        "config_hash": config_hash(inputs.config, inputs.style),
    }


def ensure_plan(session: Session, project: Project, asset: MediaAsset) -> EditPlan:
    plan = get_plan(session, project.id)
    if plan is None:
        plan = EditPlan(id=new_id("pln"), project_id=project.id, asset_id=asset.id, status="draft")
        plan.status_history = [_event("draft", "Plan creado")]
        session.add(plan)
        session.flush()
    return plan


def _event(status: str, note: str, version: int | None = None) -> dict[str, Any]:
    return {"status": status, "at": utcnow().isoformat(), "note": note, "version": version}


def set_status(plan: EditPlan, status: str, note: str) -> None:
    if status not in PLAN_STATUS_LABELS:
        raise PlanError("invalid_status", f"Estado desconocido: {status}", 422)
    if plan.status == status and not note:
        return
    plan.status = status
    plan.status_history = [*(plan.status_history or []), _event(status, note, plan.current_version)]


def new_version(
    session: Session,
    plan: EditPlan,
    doc: PlanDocument,
    *,
    kind: str,
    summary: str,
    instruction: str | None = None,
    base: dict[str, Any] | None = None,
    session_id: str | None = None,
    model: str | None = None,
    effort: str | None = None,
    immutable: bool = False,
) -> EditPlanVersion:
    parent = get_version(session, plan, plan.current_version) if plan.current_version else None
    if base is None:
        if parent is None:
            raise PlanError("no_base", "Falta la referencia de transcripción y análisis.", 500)
        base = {
            "transcript_id": parent.transcript_id,
            "transcript_fingerprint": parent.transcript_fingerprint,
            "analysis_id": parent.analysis_id,
            "asset_fingerprint": parent.asset_fingerprint,
            "config_hash": parent.config_hash,
        }
    if parent is not None:
        # Intervenciones sin huella propia (planes anteriores): heredan la de su versión.
        old_segs = (parent.transcript_fingerprint or {}).get("segments") or {}
        for i in doc.interventions:
            if not i.basis_segments and i.segment_ids:
                i.basis_segments = {sid: old_segs.get(sid, "") for sid in i.segment_ids}
            if i.basis_analysis is None:
                i.basis_analysis = parent.analysis_id
    number = (
        session.scalar(
            select(func.max(EditPlanVersion.number)).where(EditPlanVersion.plan_id == plan.id)
        )
        or 0
    ) + 1
    version = EditPlanVersion(
        id=new_id("plv"),
        plan_id=plan.id,
        number=number,
        parent_number=parent.number if parent else None,
        kind=kind,
        summary=summary[:2000],
        instruction=instruction,
        document=doc.model_dump(mode="json"),
        model=model or (parent.model if parent else None),
        effort=effort or (parent.effort if parent else None),
        immutable=immutable,
        session_id=session_id,
        **base,
    )
    session.add(version)
    plan.current_version = number
    plan.updated_at = utcnow()
    session.flush()
    return version


def _editable(session: Session, plan: EditPlan) -> tuple[EditPlanVersion, PlanDocument]:
    version = get_version(session, plan, plan.current_version)
    return version, doc_of(version)


def _after_edit(plan: EditPlan, note: str) -> None:
    # Cualquier cambio deja el plan en revisión (la versión aprobada sigue intacta).
    if plan.status != "in_review" or note:
        set_status(plan, "in_review", note)


# ---------------------------------------------------------------------------
# Decisiones del usuario (sin IA)
# ---------------------------------------------------------------------------


def update_intervention(
    session: Session,
    plan: EditPlan,
    validator: Validator | None,
    iid: str,
    *,
    status: str | None = None,
    type_: str | None = None,
    user_note: str | None = None,
) -> EditPlanVersion:
    _, doc = _editable(session, plan)
    target = next((i for i in doc.interventions if i.id == iid), None)
    if target is None:
        raise PlanError(
            "intervention_not_found", "La intervención ya no existe en esta versión.", 404
        )
    changes: list[str] = []
    now = utcnow().isoformat()
    if status is not None and status != target.status:
        if status not in ("proposed", "accepted", "rejected", "needs_changes"):
            raise PlanError("invalid_status", f"Estado desconocido: {status}", 422)
        target.status = status  # type: ignore[assignment]
        target.status_history.append(StatusEvent(status=status, at=now, note=user_note or ""))
        changes.append(
            {
                "accepted": "aceptada",
                "rejected": "rechazada",
                "needs_changes": "requiere corrección",
                "proposed": "pendiente",
            }[status]
        )
    if type_ is not None and type_ != target.type:
        if type_ not in INTERVENTION_LABELS:
            raise PlanError("invalid_type", f"Tipo desconocido: {type_}", 422)
        old = target.type
        target.type = type_  # type: ignore[assignment]
        target.status = "needs_changes"
        target.status_history.append(
            StatusEvent(status="needs_changes", at=now, note=f"Tipo cambiado de {old} a {type_}")
        )
        target.warnings.append(
            f"Tipo cambiado manualmente de «{INTERVENTION_LABELS[old]}» a "
            f"«{INTERVENTION_LABELS[type_]}»: "
            "pide a Claude que adapte el diseño o revísalo antes de aceptar."
        )
        target.origin = "manual"
        changes.append(f"tipo → {INTERVENTION_LABELS[type_]}")
    if user_note is not None and user_note != target.user_note:
        target.user_note = user_note[:1000]
        changes.append("nota")
    if not changes:
        return get_version(session, plan, plan.current_version)
    if validator is not None:
        doc = validator.check(doc)
    summary = f"{iid}: " + ", ".join(changes)
    version = new_version(session, plan, doc, kind="manual", summary=summary)
    _after_edit(plan, "")
    return version


def bulk_status(
    session: Session,
    plan: EditPlan,
    validator: Validator | None,
    status: str,
    only_pending: bool = True,
) -> EditPlanVersion:
    _, doc = _editable(session, plan)
    now = utcnow().isoformat()
    n = 0
    for i in doc.interventions:
        if only_pending and i.status != "proposed":
            continue
        if i.status != status:
            i.status = status  # type: ignore[assignment]
            i.status_history.append(StatusEvent(status=status, at=now, note="en bloque"))
            n += 1
    if n == 0:
        return get_version(session, plan, plan.current_version)
    if validator is not None:
        doc = validator.check(doc)
    version = new_version(
        session, plan, doc, kind="manual", summary=f"{n} intervención(es) marcadas en bloque"
    )
    _after_edit(plan, "")
    return version


def undo(session: Session, plan: EditPlan) -> EditPlanVersion:
    current = get_version(session, plan, plan.current_version)
    if current.parent_number is None:
        raise PlanError("nothing_to_undo", "No hay cambios anteriores que deshacer.")
    plan.current_version = current.parent_number
    _sync_approved(plan)
    plan.status_history = [
        *(plan.status_history or []),
        _event(
            plan.status,
            f"Deshecho: vuelta a la versión {current.parent_number}",
            current.parent_number,
        ),
    ]
    plan.updated_at = utcnow()
    session.flush()
    return get_version(session, plan, plan.current_version)


def _sync_approved(plan: EditPlan) -> None:
    """«Aprobado» solo si la versión de trabajo es la aprobada."""
    current, approved = plan.current_version, plan.approved_version
    if plan.status == "approved" and current != approved:
        set_status(plan, "in_review", f"Versión de trabajo v{current} (aprobada: v{approved})")
    elif approved is not None and current == approved and plan.status != "approved":
        set_status(plan, "approved", f"De vuelta a la versión aprobada v{approved}")


def redo(session: Session, plan: EditPlan) -> EditPlanVersion:
    child = session.scalar(
        select(EditPlanVersion)
        .where(
            EditPlanVersion.plan_id == plan.id,
            EditPlanVersion.parent_number == plan.current_version,
        )
        .order_by(EditPlanVersion.number.desc())
    )
    if child is None:
        raise PlanError("nothing_to_redo", "No hay cambios que rehacer.")
    plan.current_version = child.number
    _sync_approved(plan)
    plan.status_history = [
        *(plan.status_history or []),
        _event(plan.status, f"Rehecho: versión {child.number}", child.number),
    ]
    plan.updated_at = utcnow()
    session.flush()
    return child


def restore(session: Session, plan: EditPlan, number: int) -> EditPlanVersion:
    """Recupera una versión anterior como nueva versión de trabajo (no reescribe la historia)."""
    old = get_version(session, plan, number)
    doc = doc_of(old)
    base = {
        "transcript_id": old.transcript_id,
        "transcript_fingerprint": old.transcript_fingerprint,
        "analysis_id": old.analysis_id,
        "asset_fingerprint": old.asset_fingerprint,
        "config_hash": old.config_hash,
    }
    version = new_version(
        session, plan, doc, kind="manual", summary=f"Restaurada la versión {number}", base=base
    )
    _after_edit(plan, f"Restaurada la versión {number}")
    return version


# ---------------------------------------------------------------------------
# Correcciones de Claude
# ---------------------------------------------------------------------------


def apply_revision(
    validator: Validator,
    doc: PlanDocument,
    rev: ProposalRevision,
    scope: list[str],
    mode: str,
) -> tuple[PlanDocument, list[str]]:
    """Aplica solo los cambios devueltos por Claude dentro del ámbito pedido."""
    notes: list[str] = []
    by_id = {i.id: i for i in doc.interventions}
    scoped = set(scope)
    origin = "alternative" if mode == "alternative" else "revised"

    def allowed(iid: str) -> bool:
        if scoped:
            return iid in scoped
        # Instrucción global: las aceptadas también pueden cambiar si Claude lo decide,
        # pero quedan pendientes de una nueva aceptación.
        return True

    replace = list(rev.replace)
    adds = list(rev.add)
    if mode == "alternative":
        if not replace and adds:
            first = adds.pop(0)
            replace = [RevisedIntervention.model_validate({**first.model_dump(), "id": scope[0]})]
        replace = [r for r in replace if r.id in scoped][:1]
        adds = []
        if not replace:
            raise PlanError(
                "no_alternative", "Claude no devolvió una alternativa para esta intervención.", 502
            )
    for r in replace:
        old = by_id.get(r.id)
        if old is None:
            notes.append(f"Se ignoró un cambio para {r.id}: no existe.")
            continue
        if not allowed(r.id):
            notes.append(f"Se ignoró un cambio para {r.id}: fuera del ámbito pedido.")
            continue
        proposal = r.model_dump(exclude={"id"})
        new = validator.materialize(
            ProposalIntervention.model_validate(proposal), iid=old.id, origin=origin, previous=old
        )
        new.user_note = old.user_note
        by_id[old.id] = new
    for rid in rev.remove:
        old = by_id.get(rid)
        if old is None:
            continue
        if not allowed(rid):
            notes.append(f"No se eliminó {rid}: fuera del ámbito pedido.")
            continue
        del by_id[rid]
    window: tuple[float, float] | None = None
    if scoped:
        refs = [i for i in doc.interventions if i.id in scoped]
        if refs:
            window = (min(i.start for i in refs) - 5.0, max(i.end for i in refs) + 5.0)
    for p in adds:
        new = validator.materialize(p, origin=origin)
        # Se filtra con el tiempo ya validado (anclado), no con los segundos del modelo.
        if window and not (window[0] <= new.start <= window[1]):
            notes.append("Se ignoró una intervención nueva fuera del tramo pedido.")
            continue
        by_id[new.id] = new
    doc.interventions = sorted(by_id.values(), key=lambda i: (i.start, i.end))
    return validator.check(doc), notes


def compact_intervention(i: PlanIntervention, full: bool) -> dict[str, Any]:
    if not full:
        return {
            "id": i.id,
            "start": i.start,
            "end": i.end,
            "type": i.type,
            "status": i.status,
            "goal": i.goal[:140],
        }
    # Solo los campos que Claude puede proponer + id, estado y nota del usuario (contexto).
    fields = set(ProposalIntervention.model_fields) | {"id", "status", "user_note"}
    data = i.model_dump(mode="json", include=fields)
    if data.get("anchor_from_word") is None:
        data.pop("anchor_from_word", None)
        data.pop("anchor_to_word", None)
    return data


# ---------------------------------------------------------------------------
# Obsolescencia
# ---------------------------------------------------------------------------


def staleness(session: Session, version: EditPlanVersion, asset: MediaAsset) -> dict[str, Any]:
    current_t = transcript_service.active_for_asset(session, asset.id)
    current_fp = transcript_fingerprint(current_t)
    visual = analysis_bundle.active_visual(session, asset.id)
    doc = doc_of(version)
    out: dict[str, Any] = {
        "transcript_changed": current_fp["id"] != version.transcript_id
        or current_fp["segments"] != (version.transcript_fingerprint or {}).get("segments"),
        "analysis_changed": (visual.id if visual else None) != version.analysis_id,
        "asset_changed": asset_fingerprint(asset) != version.asset_fingerprint,
        "affected": {},
    }
    old_segs = (version.transcript_fingerprint or {}).get("segments") or {}
    new_segs = current_fp["segments"]
    current_analysis = visual.id if visual else None
    words = {w["id"] for s in (current_t.segments if current_t else []) for w in s["words"]}
    for i in doc.interventions:
        reasons = []
        if out["asset_changed"]:
            reasons.append("El video base cambió.")
        # Cada intervención recuerda la huella de los segmentos en que se basó (si es antigua,
        # se usa la de la versión).
        basis = i.basis_segments or {sid: old_segs.get(sid, "") for sid in i.segment_ids}
        if any(new_segs.get(sid) != fp for sid, fp in basis.items()):
            reasons.append("Cambió el texto o los tiempos de la transcripción en este tramo.")
        for anchor in (i.anchor_from_word, i.anchor_to_word):
            if anchor and anchor not in words:
                reasons.append("La palabra de anclaje ya no existe en la transcripción.")
                break
        analysis_basis = i.basis_analysis or version.analysis_id
        if i.scene_indices and analysis_basis != current_analysis:
            reasons.append("El análisis de escenas se repitió con otros resultados.")
        if reasons:
            out["affected"][i.id] = " ".join(dict.fromkeys(reasons))
    out["stale"] = bool(out["affected"])
    return out


def refresh_timings(
    session: Session,
    plan: EditPlan,
    validator: Validator,
    base: dict[str, Any],
    affected: dict[str, str] | None = None,
) -> EditPlanVersion:
    """Recalcula los tiempos de las intervenciones ancladas con la transcripción actual.

    Solo actualiza tiempos y fragmentos: si el texto cambió, el contenido de la propuesta
    puede haber quedado desfasado, así que esas intervenciones conservan un aviso y, si
    estaban aceptadas, vuelven a «requiere corrección»."""
    _, doc = _editable(session, plan)
    affected = affected or {}
    now = utcnow().isoformat()
    changed = 0
    for i in doc.interventions:
        before = (i.start, i.end, i.transcript_excerpt)
        for note in validator.retime(i):
            if note not in i.warnings:
                i.warnings.append(note)
        if (i.start, i.end, i.transcript_excerpt) != before:
            changed += 1
        i.stale, i.stale_reason = False, ""
        if i.id in affected:
            note = (
                "La transcripción o el análisis cambiaron en este tramo: revisa que el "
                "contenido siga siendo válido."
            )
            if note not in i.warnings:
                i.warnings.append(note)
            if i.status == "accepted":
                i.status = "needs_changes"
                i.status_history.append(
                    StatusEvent(status="needs_changes", at=now, note=affected[i.id])
                )
    doc = validator.check(doc)
    version = new_version(
        session,
        plan,
        doc,
        kind="refresh",
        summary=f"Tiempos recalculados con la transcripción actual ({changed} cambios)",
        base=base,
    )
    _after_edit(plan, "Referencias actualizadas")
    return version


# ---------------------------------------------------------------------------
# Aprobación y contrato para la Fase 4
# ---------------------------------------------------------------------------


def approve(
    session: Session,
    plan: EditPlan,
    project: Project,
    asset: MediaAsset,
    root: Path,
    note: str = "",
) -> EditPlanVersion:
    current = get_version(session, plan, plan.current_version)
    doc = doc_of(current)
    stale = staleness(session, current, asset)
    problems = approval_problems(doc, set(stale["affected"]))
    if problems:
        raise PlanError("not_approvable", "No se puede aprobar todavía: " + " ".join(problems), 422)
    approved = new_version(
        session,
        plan,
        doc,
        kind="approval",
        summary=note or "Plan aprobado",
        immutable=True,
        base={
            "transcript_id": current.transcript_id,
            "transcript_fingerprint": current.transcript_fingerprint,
            "analysis_id": current.analysis_id,
            "asset_fingerprint": current.asset_fingerprint,
            "config_hash": current.config_hash,
        },
    )
    plan.approved_version = approved.number
    set_status(plan, "approved", note or f"Aprobada la versión {approved.number}")
    contract = build_contract(project, asset, plan, approved, doc)
    target = resolve_inside(root, project.dir_rel) / "plans" / f"approved_v{approved.number}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, contract)
    return approved


def build_contract(
    project: Project, asset: MediaAsset, plan: EditPlan, version: EditPlanVersion, doc: PlanDocument
) -> dict[str, Any]:
    accepted = [i for i in doc.interventions if i.status == "accepted"]
    return {
        "contract": "video-studio-ai/edit-plan",
        "contract_version": CONTRACT_VERSION,
        "plan_schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": plan.id,
        "version": version.number,
        "approved_at": version.created_at.isoformat(),
        "project": {"id": project.id, "name": project.name},
        "video": {
            "asset_id": asset.id,
            "file": asset.file_rel,
            "duration": asset.duration,
            "width": asset.display_width,
            "height": asset.display_height,
            "fps": asset.fps,
            "orientation": asset.orientation,
            "fingerprint": version.asset_fingerprint,
        },
        "transcript": {"id": version.transcript_id, "fingerprint": version.transcript_fingerprint},
        "analysis": {"id": version.analysis_id},
        "config": project.config,
        "generated_with": {"model": version.model, "effort": version.effort},
        "style": doc.style,
        "understanding": doc.understanding.model_dump(mode="json"),
        "direction": doc.direction.model_dump(mode="json"),
        "interventions": [
            i.model_dump(mode="json", exclude={"status_history", "warnings"})
            for i in accepted
            if i.type not in PASSIVE_TYPES or i.type == "keep_original"
        ],
        "rejected_ids": [i.id for i in doc.interventions if i.status == "rejected"],
        "notes": [
            "Tiempos en segundos del video original. Coordenadas normalizadas 0–1.",
            "timing=word_anchored: tiempo derivado de palabras medidas por la transcripción.",
            "protected_regions: rostros detectados (no tapar salvo pantalla completa).",
        ],
    }


# ---------------------------------------------------------------------------
# Consumo
# ---------------------------------------------------------------------------


def record_call(session: Session, **values: Any) -> ClaudeCall:
    call = ClaudeCall(id=new_id("cc"), **values)
    session.add(call)
    session.flush()
    return call


def usage_for_project(session: Session, project_id: str) -> dict[str, Any]:
    calls = list(
        session.scalars(
            select(ClaudeCall)
            .where(ClaudeCall.project_id == project_id)
            .order_by(ClaudeCall.created_at)
        )
    )

    def total(attr: str) -> int:
        return sum(getattr(c, attr) or 0 for c in calls)

    estimates = [c.cost_estimate_usd for c in calls if c.cost_estimate_usd is not None]
    return {
        "calls": len(calls),
        "ok": sum(1 for c in calls if c.status == "ok"),
        "errors": sum(1 for c in calls if c.status in ("error", "invalid")),
        "cancelled": sum(1 for c in calls if c.status == "cancelled"),
        "retries": sum(1 for c in calls if c.attempt > 1),
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "cache_creation_tokens": total("cache_creation_tokens"),
        "cache_read_tokens": total("cache_read_tokens"),
        "duration_ms": total("duration_ms"),
        "cost_estimate_usd": round(sum(estimates), 4) if estimates else None,
        "billing": sorted({c.billing for c in calls}),
        "items": [
            {
                "id": c.id,
                "at": c.created_at.isoformat(),
                "step": c.step,
                "model": c.model_reported or c.model,
                "effort": c.effort,
                "status": c.status,
                "attempt": c.attempt,
                "input_tokens": c.input_tokens,
                "output_tokens": c.output_tokens,
                "cache_creation_tokens": c.cache_creation_tokens,
                "cache_read_tokens": c.cache_read_tokens,
                "duration_ms": c.duration_ms,
                "cost_estimate_usd": c.cost_estimate_usd,
                "billing": c.billing,
                "sent": c.sent,
                "error": c.error,
            }
            for c in reversed(calls[-200:])
        ],
    }


def sessions_for(session: Session, project_id: str, limit: int = 30) -> list[PlanningSession]:
    return list(
        session.scalars(
            select(PlanningSession)
            .where(PlanningSession.project_id == project_id)
            .order_by(PlanningSession.created_at.desc())
            .limit(limit)
        )
    )


def doc_json(doc: PlanDocument) -> str:
    return json.dumps(doc.model_dump(mode="json"), ensure_ascii=False)


def write_snapshot(root: Path, project: Project, plan: EditPlan, version: EditPlanVersion) -> None:
    """Copia legible del plan de trabajo en la carpeta del proyecto (portabilidad)."""
    try:
        target = resolve_inside(root, project.dir_rel) / "plans" / "plan.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            target,
            {
                "plan_id": plan.id,
                "status": plan.status,
                "version": version.number,
                "approved_version": plan.approved_version,
                "saved_at": utcnow().isoformat(),
                "document": version.document,
            },
        )
    except OSError:
        pass


def redo_available(session: Session, plan: EditPlan) -> bool:
    return (
        session.scalar(
            select(EditPlanVersion.id).where(
                EditPlanVersion.plan_id == plan.id,
                EditPlanVersion.parent_number == plan.current_version,
            )
        )
        is not None
    )


def list_versions(session: Session, plan: EditPlan) -> list[EditPlanVersion]:
    return list(
        session.scalars(
            select(EditPlanVersion)
            .where(EditPlanVersion.plan_id == plan.id)
            .order_by(EditPlanVersion.number.desc())
        )
    )
