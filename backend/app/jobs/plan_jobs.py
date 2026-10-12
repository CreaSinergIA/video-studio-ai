"""Tareas de la Fase 3: planificación de la edición con Claude.

- ``plan_generate``: plan completo. Videos cortos en una solicitud; videos largos por tramos
  (comprensión global → tramos con contexto local → consolidación y validación).
- ``plan_revise``: corrección en lenguaje natural o alternativa, limitada al ámbito pedido.

Cada solicitud se registra en ``claude_calls`` (resumen de lo enviado, consumo, duración,
errores y reintentos). La cancelación termina el proceso de Claude de inmediato.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError

from app.db import session_scope
from app.domain.edit_plan import (
    PlanDocument,
    PlanIntervention,
    ProposalPlan,
    ProposalRevision,
    ProposalSegment,
    ProposalUnderstandingOnly,
)
from app.domain.preferences import ClaudePreferences
from app.jobs.runner import JobContext, JobError, job_handler
from app.models import AnalysisFrame, PlanningSession, Project, utcnow
from app.services import (
    app_settings,
    claude_client,
    plan_context,
    plan_prompts,
    plan_styles,
    planning,
)
from app.services.claude_client import ClaudeError, ClaudeResult, image_block, text_block
from app.services.media_tools import Cancelled
from app.services.plan_context import PlanInputError, PlanInputs
from app.services.plan_validation import Validator
from app.services.storage_manager import storage_manager

log = logging.getLogger(__name__)

RETRY_DELAYS = (5.0, 20.0, 45.0, 90.0)  # se usan los primeros `max_retries`


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def _session_update(sid: str, **values: Any) -> None:
    with session_scope() as s:
        row = s.get(PlanningSession, sid)
        if row is not None:
            for k, v in values.items():
                setattr(row, k, v)


def _abort(payload: dict[str, Any], status: str, message: str) -> None:
    sid = payload.get("session_id")
    if sid:
        _session_update(sid, status=status, error=message, finished_at=utcnow())
    _restore_plan_status(payload)


def _restore_plan_status(payload: dict[str, Any]) -> None:
    """Si la operación no terminó, el plan vuelve al estado que tenía antes de pedirla."""
    project_id, prev, transient = (
        payload.get("project_id"),
        payload.get("prev_status"),
        payload.get("transient_status"),
    )
    if not project_id or not prev:
        return
    with session_scope() as s:
        plan = planning.get_plan(s, project_id)
        if plan is not None and plan.status == transient and plan.status != prev:
            planning.set_status(plan, prev, "La solicitud a Claude no se completó")


def _coerce[T: BaseModel](model: type[T], data: dict[str, Any]) -> T:
    """Valida la respuesta; recorta textos/listas demasiado largos (corrección controlada)."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        fixed = False
        for err in exc.errors():
            if err["type"] not in ("string_too_long", "too_long"):
                continue
            node: Any = data
            for key in err["loc"][:-1]:
                node = node[key]
            last = err["loc"][-1]
            limit = (err.get("ctx") or {}).get("max_length")
            if limit is not None and isinstance(node[last], (str, list)):
                node[last] = node[last][:limit]
                fixed = True
        if not fixed:
            raise
        return model.model_validate(data)


def _with_feedback(blocks: list[dict[str, Any]], error: str) -> list[dict[str, Any]]:
    """Repite la solicitud indicando el error de validación (texto neutralizado)."""
    note = (
        "<error_validacion>\n" + plan_context.untrusted(error) + "\n</error_validacion>\n"
        "La respuesta anterior no cumplía el esquema. Devuélvela de nuevo corregida."
    )
    return [
        *[b for b in blocks if not b.get("text", "").startswith("<error_validacion>")],
        text_block(note),
    ]


def _dedupe(items: list[PlanIntervention]) -> list[PlanIntervention]:
    """Quita duplicados entre tramos: mismo tipo y solapadas en más de la mitad."""
    out: list[PlanIntervention] = []
    for item in sorted(items, key=lambda i: (i.start, i.end)):
        dup = next(
            (
                o
                for o in out
                if o.type == item.type
                and min(o.end, item.end) - max(o.start, item.start)
                > 0.5 * min(o.end - o.start, item.end - item.start)
            ),
            None,
        )
        if dup is None:
            out.append(item)
    return out


def _frame_blocks(inputs: PlanInputs, frames: list[AnalysisFrame]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for f in frames:
        try:
            jpeg = plan_context.frame_jpeg(inputs, f)
        except OSError:
            continue
        blocks.append(text_block(f"Fotograma {f.id} (t={f.t:.2f} s, escena {f.scene_index}):"))
        blocks.append(image_block(jpeg))
    return blocks


class Caller:
    """Hace solicitudes a Claude con reintentos acotados y registro de consumo."""

    def __init__(
        self,
        ctx: JobContext,
        prefs: ClaudePreferences,
        sid: str,
        project_id: str,
        system: str | None = None,
    ) -> None:
        self.ctx = ctx
        self.prefs = prefs
        self.sid = sid
        self.project_id = project_id
        # Instrucciones de sistema de la operación (planificación por defecto).
        self.system = system or plan_prompts.SYSTEM
        self.last: ClaudeResult | None = None
        # Tope de solicitudes de esta operación (presupuesto aprobado al lanzarla).
        budget = (ctx.payload or {}).get("budget") or {}
        self.max_calls: int = int(budget.get("max_calls") or prefs.max_requests_per_operation)
        self.calls = 0

    def __call__[M: BaseModel](
        self,
        step: str,
        blocks: list[dict[str, Any]],
        model: type[M],
        sent: dict[str, Any],
        on_event: Callable[[str], None] | None = None,
    ) -> M:
        schema = model.model_json_schema()
        attempt = 0
        transient = 0  # reintentos por errores transitorios (sobrecarga, red, tiempo)
        invalid = 0  # reintentos por respuesta inválida (con el motivo como contexto)
        while True:
            attempt += 1
            self.ctx.check_cancelled()
            if self.calls >= self.max_calls:
                raise JobError(
                    f"Se alcanzó el tope de {self.max_calls} solicitud(es) a Claude de esta "
                    "operación; no se hacen más. Reinténtalo más tarde o revisa Ajustes → Claude."
                )
            self.calls += 1
            started = time.monotonic()
            base = {
                "project_id": self.project_id,
                "session_id": self.sid,
                "step": step,
                "transport": self.prefs.transport,
                "model": self.prefs.model,
                "effort": self.prefs.effort,
                "attempt": attempt,
                "billing": "api" if self.prefs.transport == "api" else "subscription",
                "sent": sent,
            }
            try:
                result = claude_client.run(
                    self.prefs,
                    self.system,
                    blocks,
                    schema,
                    cancel=self.ctx.cancel_event,
                    on_event=on_event,
                )
            except Cancelled:
                with session_scope() as s:
                    planning.record_call(
                        s,
                        status="cancelled",
                        duration_ms=int((time.monotonic() - started) * 1000),
                        **base,
                    )
                raise
            except ClaudeError as exc:
                with session_scope() as s:
                    planning.record_call(
                        s,
                        status="error",
                        error=f"{exc.code}: {exc.message}",
                        duration_ms=int((time.monotonic() - started) * 1000),
                        **base,
                    )
                if exc.code == "invalid_output" and invalid < 1:
                    invalid += 1
                    blocks = _with_feedback(blocks, exc.message)
                    continue
                if exc.retryable and transient < min(self.prefs.max_retries, len(RETRY_DELAYS)):
                    delay = RETRY_DELAYS[transient]
                    transient += 1
                    end = time.monotonic() + delay
                    while time.monotonic() < end:
                        self.ctx.check_cancelled()
                        time.sleep(0.2)
                    continue
                raise JobError(exc.message) from exc
            record = {
                **base,
                "model_reported": result.model_reported,
                "duration_ms": result.duration_ms,
                "cost_estimate_usd": result.cost_estimate_usd,
                "billing": result.billing,
                "rate_limit": result.rate_limit,
                **{k: v for k, v in result.usage.items()},
            }
            if result.model_reported and result.model_reported != self.prefs.model:
                with session_scope() as s:
                    planning.record_call(
                        s,
                        status="invalid",
                        error=f"Modelo inesperado: {result.model_reported}",
                        **record,
                    )
                raise JobError(
                    f"Claude respondió con otro modelo ({result.model_reported}); se descartó."
                )
            try:
                parsed = _coerce(model, result.data)
            except ValidationError as exc:
                with session_scope() as s:
                    planning.record_call(s, status="invalid", error=str(exc)[:1500], **record)
                if invalid < 1:
                    # Una sola repetición, indicando a Claude qué falló.
                    invalid += 1
                    blocks = _with_feedback(blocks, str(exc)[:1200])
                    continue
                raise JobError(
                    "Claude devolvió una propuesta con datos inválidos dos veces; "
                    "inténtalo de nuevo."
                ) from exc
            with session_scope() as s:
                planning.record_call(s, status="ok", **record)
            self.last = result
            return parsed


def _load(ctx: JobContext) -> tuple[ClaudePreferences, PlanInputs, str]:
    style = ctx.payload.get("style")
    with session_scope() as s:
        project = s.get(Project, ctx.project_id)
        if project is None:
            raise JobError("El proyecto ya no existe.")
        try:
            root = storage_manager.require_location(project.storage)
            inputs = plan_context.gather(s, project, root, style)
        except PlanInputError as exc:
            raise JobError(exc.message) from exc
        prefs = app_settings.get_claude(s)
        name = project.name
    return prefs, inputs, name


def _common_blocks(
    inputs: PlanInputs, window: tuple[float, float] | None = None
) -> list[dict[str, Any]]:
    eff = plan_styles.adjusted(plan_styles.RULES[inputs.style], inputs.config)
    facts = plan_context.video_facts(inputs)
    scenes = plan_context.scenes_text(inputs, window)
    return [
        text_block(f"<datos_video>\n{facts}\n{scenes}\n</datos_video>"),
        text_block(plan_prompts.style_section(eff, inputs.style)),
    ]


def _sent(
    inputs: PlanInputs,
    frames: list[AnalysisFrame],
    blocks: list[dict[str, Any]],
    window: tuple[float, float] | None = None,
) -> dict[str, Any]:
    chars = sum(len(b.get("text", "")) for b in blocks if b["type"] == "text")
    return {
        "frames": [f.id for f in frames],
        "frame_count": len(frames),
        "text_chars": chars,
        "estimated_tokens": plan_context.estimate_tokens("x" * chars, frames),
        "window": list(window) if window else None,
        "video_file_sent": False,
        "content": (
            "transcripción, tiempos, escenas, rostros, preferencias y fotogramas JPEG reducidos"
        ),
    }


def _progress(ctx: JobContext) -> Callable[[str], None]:
    def on_event(event: str) -> None:
        ctx.progress(0.15 if event == "connected" else 0.6)

    return on_event


def _user_instruction(text: str | None) -> list[dict[str, Any]]:
    if not text:
        return []
    return [
        text_block(f"<instruccion_usuario>\n{plan_context.untrusted(text)}\n</instruccion_usuario>")
    ]


# ---------------------------------------------------------------------------
# Generación
# ---------------------------------------------------------------------------


@job_handler("plan_generate", label="Planificando edición con IA", on_abort=_abort)
def plan_generate(ctx: JobContext) -> dict[str, Any]:
    sid = ctx.payload["session_id"]
    instruction = ctx.payload.get("instruction")
    _session_update(sid, status="running")
    try:
        return _generate(ctx, sid, instruction)
    except Cancelled:
        _session_update(sid, status="cancelled", finished_at=utcnow(), error="Cancelada")
        _restore_plan_status(ctx.payload)
        raise
    except Exception as exc:
        _session_update(sid, status="failed", finished_at=utcnow(), error=str(exc)[:500])
        _restore_plan_status(ctx.payload)
        raise


def _generate(ctx: JobContext, sid: str, instruction: str | None) -> dict[str, Any]:
    ctx.stage("Preparando el contexto audiovisual", 0.0, 0.05)
    prefs, inputs, _ = _load(ctx)
    validator = Validator(inputs)
    call = Caller(ctx, prefs, sid, inputs.project.id)
    hierarchical = plan_context.needs_hierarchy(inputs)
    _session_update(sid, strategy="hierarchical" if hierarchical else "single")
    if not hierarchical:
        frames = plan_context.select_frames(inputs.frames, inputs.scenes, prefs.max_frames)
        blocks = [
            *_common_blocks(inputs),
            text_block(
                f"<transcripcion>\n{plan_context.transcript_text(inputs)}\n</transcripcion>"
            ),
            text_block("<fotogramas>\n" + plan_context.frames_intro(frames) + "\n</fotogramas>"),
            *_frame_blocks(inputs, frames),
            *_user_instruction(instruction),
            text_block(plan_prompts.TASK_FULL),
        ]
        ctx.stage("Claude analiza el video y diseña el plan", 0.05, 0.92)
        result = call("full", blocks, ProposalPlan, _sent(inputs, frames, blocks), _progress(ctx))
        understanding, direction, proposals = (
            result.understanding,
            result.direction,
            result.interventions,
        )
    else:
        windows = plan_context.chunk_windows(inputs)
        total = len(windows) + 1
        frames = plan_context.select_frames(inputs.frames, inputs.scenes, min(prefs.max_frames, 10))
        blocks = [
            *_common_blocks(inputs),
            text_block(
                "<transcripcion>\n"
                + plan_context.transcript_text(inputs, words=False)
                + "\n</transcripcion>"
            ),
            text_block("<fotogramas>\n" + plan_context.frames_intro(frames) + "\n</fotogramas>"),
            *_frame_blocks(inputs, frames),
            *_user_instruction(instruction),
            text_block(plan_prompts.TASK_GLOBAL),
        ]
        ctx.stage(f"Comprensión global del video (1/{total})", 0.05, 0.05 + 0.85 / total)
        glob = call(
            "global",
            blocks,
            ProposalUnderstandingOnly,
            _sent(inputs, frames, blocks),
            _progress(ctx),
        )
        understanding, direction = glob.understanding, glob.direction
        summary = plan_context.untrusted(
            f"Resumen: {understanding.summary}\nIntención: {understanding.intent}\n"
            f"Tono: {understanding.tone}\nConcepto visual: {direction.concept}\n"
            f"Lenguaje visual: {direction.visual_language}\nRitmo: {direction.pacing}\n"
            f"Tipografía: {direction.typography}\nDensidad: {direction.density}"
        )
        proposals = []
        materialized: list[PlanIntervention] = []
        for n, window in enumerate(windows, start=2):
            a = 0.05 + 0.85 * (n - 1) / total
            ctx.stage(
                f"Tramo {n - 1} de {len(windows)} ({window[0]:.0f}–{window[1]:.0f} s)",
                a,
                a + 0.85 / total,
            )
            wframes = plan_context.select_frames(inputs.frames, inputs.scenes, 6, window)
            prev = plan_context.untrusted(
                "\n".join(
                    f"{p.start:.2f}–{p.end:.2f} {p.type}: {p.goal[:120]}" for p in proposals[-4:]
                )
            )
            blocks = [
                *_common_blocks(inputs, window),
                text_block(
                    "<transcripcion>\n"
                    + plan_context.transcript_text(inputs, window)
                    + "\n</transcripcion>"
                ),
                text_block(
                    "<fotogramas>\n" + plan_context.frames_intro(wframes) + "\n</fotogramas>"
                ),
                *_frame_blocks(inputs, wframes),
                *_user_instruction(instruction),
                text_block(plan_prompts.task_segment(window, n - 1, len(windows), summary, prev)),
            ]
            seg = call(
                f"segment {n - 1}/{len(windows)}",
                blocks,
                ProposalSegment,
                _sent(inputs, wframes, blocks, window),
                _progress(ctx),
            )
            last = n - 1 == len(windows)
            for p in seg.interventions:
                # Ventanas semiabiertas sobre el tiempo ya validado (anclado a palabras).
                item = validator.materialize(p)
                if window[0] <= item.start and (item.start < window[1] or last):
                    proposals.append(p)
                    materialized.append(item)
    ctx.stage("Validando y guardando el plan", 0.92, 1.0)
    interventions = (
        _dedupe(materialized) if hierarchical else [validator.materialize(p) for p in proposals]
    )
    doc = validator.check(
        PlanDocument(
            style=inputs.style,
            understanding=understanding,
            direction=direction,
            interventions=interventions,
        )
    )
    model_used = call.last.model_reported if call.last else prefs.model
    with planning.project_lock(inputs.project.id), session_scope() as s:
        project = s.get(Project, inputs.project.id)
        if project is None:
            raise JobError("El proyecto ya no existe.")
        plan = planning.ensure_plan(s, project, inputs.asset)
        version = planning.new_version(
            s,
            plan,
            doc,
            kind="generated",
            summary=(
                f"Plan generado por Claude: {len(interventions)} intervenciones "
                f"({'por tramos' if hierarchical else 'una pasada'})."
            ),
            instruction=instruction,
            base=planning.base_of(inputs),
            session_id=sid,
            model=model_used,
            effort=prefs.effort,
        )
        planning.set_status(plan, "in_review", f"Propuesta generada (versión {version.number})")
        planning.write_snapshot(inputs.root, project, plan, version)
        row = s.get(PlanningSession, sid)
        if row is not None:
            row.status, row.plan_id, row.result_version = "succeeded", plan.id, version.number
            row.summary, row.finished_at = version.summary, utcnow()
    return {
        "version": version.number,
        "interventions": len(interventions),
        "strategy": "hierarchical" if hierarchical else "single",
    }


# ---------------------------------------------------------------------------
# Correcciones y alternativas
# ---------------------------------------------------------------------------


@job_handler("plan_revise", label="Corrigiendo el plan con IA", on_abort=_abort)
def plan_revise(ctx: JobContext) -> dict[str, Any]:
    sid = ctx.payload["session_id"]
    _session_update(sid, status="running")
    try:
        return _revise(ctx, sid)
    except Cancelled:
        _session_update(sid, status="cancelled", finished_at=utcnow(), error="Cancelada")
        _restore_plan_status(ctx.payload)
        raise
    except Exception as exc:
        _session_update(sid, status="failed", finished_at=utcnow(), error=str(exc)[:500])
        _restore_plan_status(ctx.payload)
        raise


def _revise(ctx: JobContext, sid: str) -> dict[str, Any]:
    instruction: str = ctx.payload.get("instruction") or ""
    scope: list[str] = list(ctx.payload.get("scope") or [])
    mode: str = ctx.payload.get("mode", "revise")
    ctx.stage("Preparando el contexto", 0.0, 0.05)
    with session_scope() as s:
        plan = planning.require_plan(s, ctx.project_id or "")
        base_version = plan.current_version
        doc = planning.doc_of(planning.get_version(s, plan, base_version))
    prefs, inputs, _ = _load(ctx)
    inputs.style = doc.style  # la corrección conserva el estilo del plan
    validator = Validator(inputs)
    by_id = {i.id: i for i in doc.interventions}
    missing = [i for i in scope if i not in by_id]
    if missing:
        raise JobError(
            "Algunas intervenciones ya no existen en el plan actual: " + ", ".join(missing)
        )
    targets = [by_id[i] for i in scope]
    if targets:
        window = (
            max(0.0, min(t.start for t in targets) - 10),
            min(inputs.duration, max(t.end for t in targets) + 10),
        )
    else:
        window = (0.0, inputs.duration)
    frames = plan_context.select_frames(
        inputs.frames,
        inputs.scenes,
        min(6, prefs.max_frames) if targets else prefs.max_frames,
        window,
    )
    plan_json = {
        "direction": doc.direction.model_dump(mode="json"),
        "scenes": [sc.model_dump(mode="json") for sc in doc.understanding.scenes],
        "in_scope": [
            planning.compact_intervention(i, True) for i in (targets or doc.interventions)
        ],
        "others": [
            planning.compact_intervention(i, False)
            for i in doc.interventions
            if targets and i.id not in scope
        ],
    }
    import json as _json

    blocks = [
        *_common_blocks(inputs, window if targets else None),
        text_block(
            f"<transcripcion>\n{plan_context.transcript_text(inputs, window)}\n</transcripcion>"
        ),
        text_block(
            "<plan_actual>\n"
            + plan_context.untrusted(_json.dumps(plan_json, ensure_ascii=False))
            + "\n</plan_actual>"
        ),
        text_block("<fotogramas>\n" + plan_context.frames_intro(frames) + "\n</fotogramas>"),
        *_frame_blocks(inputs, frames),
        text_block(plan_prompts.task_revision(plan_context.untrusted(instruction), scope, mode)),
    ]
    call = Caller(ctx, prefs, sid, inputs.project.id)
    ctx.stage("Claude revisa la propuesta", 0.05, 0.92)
    rev = call(
        "alternative" if mode == "alternative" else "revision",
        blocks,
        ProposalRevision,
        _sent(inputs, frames, blocks, window),
        _progress(ctx),
    )
    ctx.stage("Validando y guardando", 0.92, 1.0)
    with planning.project_lock(ctx.project_id or ""), session_scope() as s:
        plan = planning.require_plan(s, ctx.project_id or "")
        if plan.current_version != base_version:
            raise JobError(
                "El plan cambió mientras Claude trabajaba; vuelve a pedir la corrección."
            )
        new_doc, notes = planning.apply_revision(validator, doc, rev, scope, mode)
        summary = rev.summary + (" " + " ".join(notes) if notes else "")
        version = planning.new_version(
            s,
            plan,
            new_doc,
            kind="alternative" if mode == "alternative" else "revision",
            summary=summary,
            instruction=instruction or None,
            session_id=sid,
            model=call.last.model_reported if call.last else prefs.model,
            effort=prefs.effort,
            base=planning.base_of(inputs),
        )
        planning.set_status(plan, "in_review", f"Corrección aplicada (versión {version.number})")
        project = s.get(Project, inputs.project.id)
        if project is not None:
            planning.write_snapshot(inputs.root, project, plan, version)
        row = s.get(PlanningSession, sid)
        if row is not None:
            row.status, row.plan_id, row.result_version = "succeeded", plan.id, version.number
            row.summary, row.finished_at = summary[:2000], utcnow()
    return {"version": version.number, "changed": len(rev.replace) + len(rev.add) + len(rev.remove)}
