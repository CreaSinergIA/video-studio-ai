"""Tareas de la Fase 5: modificar una escena con Claude y previsualizar versiones de escena.

- ``scene_revise``: UNA solicitud a Claude con el contexto mínimo de la escena (intervención,
  dirección actual, vecinas, transcripción del tramo, encuadre y 2 fotogramas). No se vuelve a
  analizar el video. El resultado es una versión candidata; nada del plan aprobado cambia.
- ``scene_preview``: vistas previas reales (mismo compositor que la exportación) de dos o más
  versiones de una escena en la MISMA ventana, para compararlas en paralelo.
"""

from __future__ import annotations

from typing import Any, cast

from app.db import session_scope
from app.domain.edit_config import StyleId
from app.domain.edit_plan import PlanIntervention
from app.jobs.animation_jobs import compose_window, render_missing
from app.jobs.plan_jobs import Caller, _frame_blocks
from app.jobs.runner import JobContext, JobError, job_handler
from app.models import PlanningSession, Project, SceneVersion, new_id, utcnow
from app.services import animation_direction as adir
from app.services import animations as anim
from app.services import app_settings, plan_context, planning, render_engine, scenes
from app.services.plan_context import PlanInputError
from app.services.plan_validation import Validator
from app.services.planning import PlanError
from app.services.storage import StorageError, to_rel
from app.services.storage_manager import storage_manager

PREVIEW_MARGIN = 1.0


def _session_close(sid: str, status: str, summary: str = "", error: str | None = None) -> None:
    with session_scope() as s:
        row = s.get(PlanningSession, sid)
        if row is not None:
            row.status, row.summary, row.error = status, summary[:2000], error
            row.finished_at = utcnow()


def _window(ivs: list[dict[str, Any]], duration: float) -> tuple[float, float]:
    t0 = max(0.0, min(float(i["start"]) for i in ivs) - PREVIEW_MARGIN)
    t1 = min(duration, max(float(i["end"]) for i in ivs) + PREVIEW_MARGIN)
    return t0, t1


def _preview_versions(
    ctx: JobContext,
    ap: anim.Approved,
    dirs: dict[str, dict[str, Any]],
    iid: str,
    rows: list[tuple[str, dict[str, Any], dict[str, Any] | None]],
    lo: float,
    hi: float,
) -> dict[str, dict[str, Any]]:
    """Renderiza la vista previa de cada versión (id, intervención, dirección) en la ventana
    común. Devuelve {id de versión: {file_rel, window, key}}."""
    t0, t1 = _window([iv for _, iv, _ in rows], float(ap.asset.duration or 0))
    out: dict[str, dict[str, Any]] = {}
    span = (hi - lo) / max(1, len(rows))
    for n, (vid, iv, direction) in enumerate(rows):
        ctx.stage(f"Vista previa {n + 1} de {len(rows)}", lo + span * n, lo + span * (n + 1))
        compiled = anim.compile_all(ap, "preview", dirs, overrides={iid: (iv, direction)})
        own = next((c for c in compiled if c["iv"]["id"] == iid), None)
        # Lo que se ve en la ventana: la escena y las vecinas que coincidan (contenido real).
        visible = [
            c for c in compiled if float(c["iv"]["start"]) < t1 and float(c["iv"]["end"]) > t0
        ]
        files = render_missing(ctx, ap, visible)
        missing = [c["iv"]["id"] for c in visible if c["iv"]["id"] not in files]
        if missing:
            raise JobError(f"No se pudo renderizar la animación de {', '.join(missing)}.")
        path, key = compose_window(ctx, ap, visible, files, t0, t1, f"scene-{iid}")
        out[vid] = {
            "file_rel": to_rel(ap.root, path),
            "window": [t0, t1],
            "key": key,
            "region": (own or {}).get("spec", {}).get("region"),
            "mode": (own or {}).get("spec", {}).get("mode"),
        }
    return out


VISIBLE_CHANGE = 0.01  # por debajo de esta fracción de la región, el cambio es casi imperceptible


def _measure_change(
    ap: anim.Approved, previews: dict[str, dict[str, Any]], cand_id: str
) -> float | None:
    """Fracción de la región de la escena que cambia de forma visible entre la propuesta y la
    versión en uso (misma ventana). Se muestra siempre: un cambio pedido que apenas se ve (p.
    ej. texto más grande en una franja que no lo permite) no debe presentarse como hecho."""
    if len(previews) != 2 or cand_id not in previews:
        return None
    other = next(v for k, v in previews.items() if k != cand_id)
    mine = previews[cand_id]
    regions = [r for r in (mine.get("region"), other.get("region")) if r]
    if not regions or "fullscreen" in (mine.get("mode"), other.get("mode")):
        region = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    else:
        x0 = min(r["x"] for r in regions)
        y0 = min(r["y"] for r in regions)
        x1 = max(r["x"] + r["w"] for r in regions)
        y1 = max(r["y"] + r["h"] for r in regions)
        region = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
    from app.services.storage import resolve_inside

    return scenes.visual_change(
        resolve_inside(ap.root, mine["file_rel"]),
        resolve_inside(ap.root, other["file_rel"]),
        region,
    )


def _abort(payload: dict[str, Any], status: str, message: str) -> None:
    sid = payload.get("session_id")
    if sid:
        _session_close(sid, status, error=message)


@job_handler(
    "scene_revise", label="Modificando la animación con Claude", heavy=True, on_abort=_abort
)
def scene_revise(ctx: JobContext) -> dict[str, Any]:
    p = ctx.payload
    sid: str = p["session_id"]
    iid: str = p["intervention_id"]
    instruction: str = p["instruction"]
    try:
        return _revise(ctx, sid, iid, instruction, int(p["base_number"]))
    except Exception as exc:
        from app.services.media_tools import Cancelled

        _session_close(
            sid, "cancelled" if isinstance(exc, Cancelled) else "failed", error=str(exc)[:500]
        )
        raise


def _revise(
    ctx: JobContext, sid: str, iid: str, instruction: str, base_number: int
) -> dict[str, Any]:
    ctx.stage("Preparando el contexto de la escena", 0.0, 0.05)
    try:
        with session_scope() as s:
            ap = anim.load_approved(s, ctx.project_id or "")
            base = scenes.get_version(s, ap.plan_id, iid, base_number)
            base_iv, base_dir = dict(base.intervention), base.direction
            dirs = anim.directions(s, ap)
            plan = planning.require_plan(s, ap.project.id)
            approved = planning.get_version(s, plan, ap.version)
            stale = planning.staleness(s, approved, ap.asset)
            if iid in stale["affected"]:
                raise JobError(
                    "La transcripción o el análisis de este tramo cambiaron desde la aprobación. "
                    "Actualiza el plan (Plan IA) antes de modificar la escena."
                )
            doc = planning.doc_of(approved)
            old_doc = next((i for i in doc.interventions if i.id == iid), None)
            if old_doc is None:
                raise JobError("La escena ya no existe en el plan aprobado.")
            old = PlanIntervention.model_validate({**old_doc.model_dump(mode="json"), **base_iv})
            project = s.get(Project, ap.project.id)
            assert project is not None
            root = storage_manager.require_location(project.storage)
            inputs = plan_context.gather(s, project, root, cast(StyleId, ap.style))
            prefs = app_settings.get_claude(s)
            parent = scenes.ensure_in_use(s, ap, iid)
            parent_number = parent.number
    except (PlanError, PlanInputError, StorageError) as exc:
        raise JobError(getattr(exc, "message", str(exc))) from exc
    platform = anim.current_config(ap).delivery.platform
    compiled = anim.compile_all(ap, "final", dirs)
    framing = scenes.framing_of(compiled, iid, platform)
    frames = plan_context.select_frames(
        inputs.frames, inputs.scenes, 2, (float(base_iv["start"]), float(base_iv["end"]))
    )
    blocks = [
        *scenes.build_blocks(ap, base_iv, base_dir, framing, instruction),
        *_frame_blocks(inputs, frames),
    ]
    sent = {
        "scene": iid,
        "frames": [f.id for f in frames],
        "frame_count": len(frames),
        "text_chars": len(blocks[0]["text"]),
        "video_file_sent": False,
        "content": (
            "una escena del plan aprobado, su dirección y encuadre, escenas vecinas, "
            "transcripción del tramo y 2 fotogramas reducidos"
        ),
    }
    call = Caller(ctx, prefs, sid, ap.project.id, system=scenes.SYSTEM)
    ctx.stage("Claude modifica la escena", 0.05, 0.45)
    out = call("scene", blocks, scenes.SceneRevisionOut, sent)
    ctx.stage("Validando la nueva versión", 0.45, 0.5)
    try:
        iv, notes = scenes.candidate_intervention(Validator(inputs), old, out.intervention)
    except PlanError as exc:
        raise JobError(exc.message) from exc
    direction = adir.to_direction_dict(out.animation)
    direction["id"] = iid
    from app.services import animation_spec

    if direction.get("template") not in animation_spec.TEMPLATES[ap.style]:
        notes.append(
            f"La plantilla «{direction.get('template')}» no es del estilo: se conserva la anterior."
        )
        direction["template"] = (base_dir or {}).get("template")
    ctx.stage("Analizando dependencias", 0.5, 0.55)
    imp = {**scenes.impact(ap, dirs, iid, iv, direction), "plan_version": ap.version}
    with session_scope() as s:
        row = SceneVersion(
            id=new_id("scv"),
            project_id=ap.project.id,
            plan_id=ap.plan_id,
            intervention_id=iid,
            number=0,
            parent_number=base_number,
            source="claude",
            base_plan_version=ap.version,
            intervention=iv,
            direction=direction,
            instruction=instruction,
            summary=out.summary,
            changes=[*out.changes, *notes][:10],
            status="candidate",
            session_id=sid,
            request_key=scenes.request_key(base, instruction, ap.version),
            impact=imp,
        )
        scenes.add_version(s, row)
        row_id, number = row.id, row.number
    if not render_engine.status()["ready"]:
        # La propuesta ya está guardada (la solicitud no se pierde): la vista previa se podrá
        # generar cuando el motor esté listo.
        _session_close(
            sid,
            "succeeded",
            f"Versión {number} de la escena {iid} (sin vista previa: el motor no está listo).",
        )
        return {"intervention_id": iid, "version": number, "impact": imp, "preview": False}
    ctx.stage("Preparando el motor de render", 0.55, 0.58)
    try:
        render_engine.ensure_bundle(ctx.cancel_event)
    except render_engine.EngineError as exc:
        raise JobError(exc.message) from exc
    with session_scope() as s:
        in_use = scenes.get_version(s, ap.plan_id, iid, parent_number)
        pair = [
            (row_id, iv, direction),
            (in_use.id, dict(in_use.intervention), in_use.direction),
        ]
    previews = _preview_versions(ctx, ap, dirs, iid, pair, 0.58, 1.0)
    change = _measure_change(ap, previews, row_id)
    with session_scope() as s:
        for vid, pv in previews.items():
            r = s.get(SceneVersion, vid)
            if r is not None:
                r.preview = pv
                if vid == row_id and change is not None:
                    r.impact = {**(r.impact or {}), "visual_change": change}
                    if change < VISIBLE_CHANGE:
                        r.changes = [
                            "Atención: el cambio apenas se percibe en este encuadre "
                            f"({change:.1%} de la región). El espacio disponible o la "
                            "plantilla pueden limitar lo pedido; compara las vistas previas o "
                            "prueba otra instrucción.",
                            *(r.changes or []),
                        ]
    _session_close(sid, "succeeded", f"Versión {number} de la escena {iid}: {out.summary}")
    return {"intervention_id": iid, "version": number, "impact": imp}


@job_handler("scene_preview", label="Vista previa de versiones de la escena", heavy=True)
def scene_preview(ctx: JobContext) -> dict[str, Any]:
    iid: str = ctx.payload["intervention_id"]
    numbers: list[int] = [int(n) for n in ctx.payload["numbers"]]
    ctx.stage("Preparando", 0.0, 0.05)
    try:
        with session_scope() as s:
            ap = anim.load_approved(s, ctx.project_id or "")
            dirs = anim.directions(s, ap)
            rows = [scenes.get_version(s, ap.plan_id, iid, n) for n in numbers]
            pair = [(r.id, dict(r.intervention), r.direction) for r in rows]
    except PlanError as exc:
        raise JobError(exc.message) from exc
    try:
        render_engine.ensure_bundle(ctx.cancel_event)
    except render_engine.EngineError as exc:
        raise JobError(exc.message) from exc
    previews = _preview_versions(ctx, ap, dirs, iid, pair, 0.05, 1.0)
    with session_scope() as s:
        for vid, pv in previews.items():
            r = s.get(SceneVersion, vid)
            if r is not None:
                r.preview = pv
    return {"intervention_id": iid, "versions": numbers}
