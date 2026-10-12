"""Control de solicitudes a Claude (Fase 5).

- **Estimación previa** de cada operación (cuántas solicitudes necesita y el máximo con
  reintentos).
- **Límite autorizado** de solicitudes en 24 h (ventana móvil, configurable en Ajustes → Claude).
  Si una operación puede superarlo, la API responde ``budget_confirm`` con el detalle y el
  panel pide una confirmación explícita; solo entonces se lanza (la ampliación vale para esa
  operación, no cambia el límite).
- **Tope por operación**: la tarea nunca hace más solicitudes que su máximo estimado (incluidos
  los reintentos), aunque Claude falle repetidamente.

Cada intento que llega a Claude cuenta como una solicitud real (también los fallidos). Con
Claude Code y el plan del usuario no hay cargos por solicitud: se consumen los límites de uso
del plan. La cifra en dólares que informa Claude Code es una estimación a precio de lista, no un
cargo; con la API se factura por tokens.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.preferences import ClaudePreferences
from app.models import ClaudeCall, Job, utcnow
from app.services.planning import PlanError

WINDOW = timedelta(hours=24)
# Pasos que sí llegan a Claude: «cancelled» antes de enviar no consume (se registra igual).
_COUNTED = ("ok", "error", "invalid", "cancelled")


@dataclass(frozen=True)
class Estimate:
    operation: str
    expected: int  # solicitudes si todo va bien
    maximum: int  # tope duro, con reintentos

    def as_dict(self) -> dict[str, Any]:
        return {"operation": self.operation, "expected": self.expected, "maximum": self.maximum}


LABELS = {
    "generate": "Generar el plan",
    "revise": "Corregir el plan",
    "alternative": "Pedir una alternativa",
    "animate": "Dirigir las animaciones",
    "scene_revise": "Modificar una animación",
}


def estimate(prefs: ClaudePreferences, operation: str, units: int = 1) -> Estimate:
    """``units``: solicitudes base (tramos de un plan jerárquico, lotes de animaciones…)."""
    expected = max(1, units)
    # Cada solicitud puede repetirse una vez por respuesta inválida y ``max_retries`` veces por
    # errores transitorios; el tope de la operación acota el total.
    worst = expected * (1 + 1 + prefs.max_retries)
    # El tope por operación es absoluto (lo fija el usuario).
    maximum = min(worst, prefs.max_requests_per_operation)
    return Estimate(operation, expected, maximum)


def animate_units(n_interventions: int, batch: int = 10) -> int:
    return math.ceil(n_interventions / batch) if n_interventions else 0


def used_in_window(session: Session) -> int:
    since = utcnow() - WINDOW
    return int(
        session.scalar(
            select(func.count(ClaudeCall.id)).where(
                ClaudeCall.created_at >= since, ClaudeCall.status.in_(_COUNTED)
            )
        )
        or 0
    )


def reserved(session: Session) -> int:
    """Solicitudes que aún pueden hacer las operaciones en cola o en curso (de cualquier
    proyecto): su máximo autorizado menos lo que ya han registrado."""
    total = 0
    for job in session.scalars(select(Job).where(Job.status.in_(("queued", "running")))):
        budget = (job.payload or {}).get("budget") or {}
        cap = int(budget.get("max_calls") or 0)
        sid = (job.payload or {}).get("session_id")
        if not cap:
            continue
        done = (
            int(
                session.scalar(
                    select(func.count(ClaudeCall.id)).where(ClaudeCall.session_id == sid)
                )
                or 0
            )
            if sid
            else 0
        )
        total += max(0, cap - done)
    return total


def status(session: Session, prefs: ClaudePreferences) -> dict[str, Any]:
    used = used_in_window(session)
    held = reserved(session)
    return {
        "used_24h": used,
        "reserved": held,
        "limit_24h": prefs.daily_request_limit,
        "remaining_24h": max(0, prefs.daily_request_limit - used - held),
        "max_retries": prefs.max_retries,
        "max_requests_per_operation": prefs.max_requests_per_operation,
        "billing": "subscription" if prefs.transport == "claude_code" else "api",
    }


def preflight(
    session: Session, prefs: ClaudePreferences, est: Estimate, confirmed: bool
) -> dict[str, Any]:
    """Comprueba la operación contra el límite autorizado. Devuelve el presupuesto que viaja
    con la tarea (``max_calls``) o lanza ``budget_confirm`` si hace falta confirmación."""
    if est.expected > est.maximum:
        # No se empieza algo que no puede terminar: fallaría a medias tras gastar solicitudes.
        raise PlanError(
            "cap_too_low",
            f"{LABELS.get(est.operation, est.operation)} necesita {est.expected} solicitudes y el "
            f"tope por operación es {prefs.max_requests_per_operation}. Súbelo en Ajustes → "
            "Claude → Control de solicitudes para continuar.",
            409,
            details={"estimate": est.as_dict()},
        )
    st = status(session, prefs)
    over = st["used_24h"] + st["reserved"] + est.maximum > st["limit_24h"]
    if over and not confirmed:
        label = LABELS.get(est.operation, est.operation)
        raise PlanError(
            "budget_confirm",
            f"{label} necesita {est.expected} solicitud(es) a Claude (hasta {est.maximum} con "
            f"reintentos) y llevas {st['used_24h']} de {st['limit_24h']} autorizadas en las "
            "últimas 24 h"
            + (
                f" (más {st['reserved']} reservadas por operaciones en curso)"
                if st["reserved"]
                else ""
            )
            + ". Confirma para continuar solo con esta operación, o amplía el límite en "
            "Ajustes → Claude.",
            409,
            details={**st, "estimate": est.as_dict()},
        )
    return {**est.as_dict(), "max_calls": est.maximum, "confirmed_over_limit": bool(over)}


def global_usage(session: Session, days: int = 30) -> dict[str, Any]:
    """Consumo agregado por día y por operación (todas las solicitudes registradas)."""
    since = utcnow() - timedelta(days=days)
    rows = list(
        session.scalars(
            select(ClaudeCall).where(ClaudeCall.created_at >= since).order_by(ClaudeCall.created_at)
        )
    )
    by_day: dict[str, dict[str, Any]] = {}
    by_step: dict[str, int] = {}
    for c in rows:
        day = c.created_at.date().isoformat()
        d = by_day.setdefault(day, {"day": day, "requests": 0, "errors": 0, "retries": 0})
        d["requests"] += 1
        d["errors"] += c.status in ("error", "invalid")
        d["retries"] += c.attempt > 1
        step = c.step.split(" ")[0]
        by_step[step] = by_step.get(step, 0) + 1
    estimates = [c.cost_estimate_usd for c in rows if c.cost_estimate_usd is not None]
    return {
        "days": days,
        "requests": len(rows),
        "by_day": list(by_day.values()),
        "by_step": by_step,
        "input_tokens": sum(c.input_tokens or 0 for c in rows),
        "output_tokens": sum(c.output_tokens or 0 for c in rows),
        "cost_estimate_usd": round(sum(estimates), 4) if estimates else None,
        "billing": sorted({c.billing for c in rows}),
    }
