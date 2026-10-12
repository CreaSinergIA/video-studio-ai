"""Tareas de la Fase 4: dirección de animaciones, render de clips, vistas previas y exportación.

- ``animations_prepare``: (opcional) Claude dirige cada animación aprobada con el lenguaje
  declarativo; se compilan las especificaciones y se renderizan los clips que falten (caché por
  huella: lo ya renderizado se reutiliza). Estado por intervención: pendiente, generando,
  disponible o error (con el motivo).
- ``animation_preview``: vista previa compuesta de una intervención (tramo ±1 s, 540p) con el
  mismo compositor que la exportación.
- ``engine_install``: descarga explícita y verificada del navegador de render.
- La exportación con animaciones se integra en la tarea ``export`` existente.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.db import session_scope
from app.jobs.runner import JobContext, JobError, job_handler
from app.models import (
    AnimationDirection,
    AnimationPreview,
    AnimationRender,
    PlanningSession,
    new_id,
    utcnow,
)
from app.services import animation_direction as adir
from app.services import animations as anim
from app.services import app_settings, compositor, exporter, render_engine
from app.services.media_probe import HDR_TRANSFERS
from app.services.media_tools import Cancelled, FFmpegError
from app.services.planning import PlanError
from app.services.storage import resolve_inside, to_rel

log = logging.getLogger(__name__)
BATCH = 10


def _upsert_render(
    s: Any,
    ap: anim.Approved,
    iv_id: str,
    purpose: str,
    c: dict[str, Any],
    w: int,
    h: int,
    fps: float,
) -> AnimationRender:
    row = s.scalar(
        select(AnimationRender).where(
            AnimationRender.plan_id == ap.plan_id,
            AnimationRender.plan_version == ap.version,
            AnimationRender.intervention_id == iv_id,
            AnimationRender.purpose == purpose,
        )
    )
    if row is None:
        row = AnimationRender(
            id=new_id("anr"),
            project_id=ap.project.id,
            plan_id=ap.plan_id,
            plan_version=ap.version,
            intervention_id=iv_id,
            purpose=purpose,
            width=w,
            height=h,
            fps=fps,
            spec_hash=c["hash"],
        )
        s.add(row)
    row.width, row.height, row.fps = w, h, fps
    row.spec_hash, row.spec = c["hash"], c["spec"]
    row.extra = {
        "notes": c["notes"],
        "pip_src": c["pip_src"],
        "direction": c["direction"],
        "template": c["spec"]["template"],
        "warnings": c.get("warnings", []),
        "region": c["spec"]["region"],
        "mode": c["spec"]["mode"],
    }
    return row


def ensure_clips(
    ctx: JobContext,
    ap: anim.Approved,
    purpose: str,
    compiled: list[dict[str, Any]],
    lo: float,
    hi: float,
    size: tuple[int, int, float] | None = None,
) -> dict[str, Path]:
    """Renderiza los clips que falten (reutiliza la caché). Devuelve {intervención: archivo}."""
    w, h, fps = size or anim.render_size(ap, purpose)
    files: dict[str, Path] = {}
    pending: list[render_engine.ClipJob] = []
    with session_scope() as s:
        for c in compiled:
            iv_id = c["iv"]["id"]
            hit = anim.cached_clip(ap, c["hash"], c["spec"])
            row = _upsert_render(s, ap, iv_id, purpose, c, w, h, fps)
            if hit is not None:
                row.status, row.file_rel, row.error = "ready", to_rel(ap.root, hit), None
                row.extra = {**row.extra, "reused": True}
                files[iv_id] = hit
            else:
                row.status, row.error = "rendering", None
                pending.append(
                    render_engine.ClipJob(iv_id, c["spec"], anim.clip_path(ap, c["hash"]))
                )
    if not pending:
        ctx.progress(1.0)
        return files
    frames = {p.key: max(1, p.spec["durationInFrames"]) for p in pending}
    total = sum(frames.values())
    done: dict[str, float] = {}

    def on_event(ev: dict[str, Any]) -> None:
        k = ev.get("key")
        if ev.get("type") == "progress" and k:
            done[k] = float(ev.get("progress") or 0)
            ctx.progress(sum(frames[x] * done.get(x, 0) for x in frames) / total)
        elif ev.get("type") in ("done", "error") and k:
            with session_scope() as s:
                row = s.scalar(
                    select(AnimationRender).where(
                        AnimationRender.plan_id == ap.plan_id,
                        AnimationRender.plan_version == ap.version,
                        AnimationRender.intervention_id == k,
                        AnimationRender.purpose == purpose,
                    )
                )
                if row is None:
                    return
                if ev["type"] == "done":
                    path = next(p.out for p in pending if p.key == k)
                    row.status, row.file_rel, row.error = "ready", to_rel(ap.root, path), None
                    row.render_ms, row.size_bytes = int(ev.get("ms") or 0), path.stat().st_size
                    files[k] = path
                else:
                    row.status, row.error = "failed", str(ev.get("message"))[:1000]

    try:
        render_engine.render_clips(
            pending,
            on_event=on_event,
            cancel=ctx.cancel_event,
            timeout=max(600.0, total / fps * 40),
        )
    except Cancelled:
        _mark(
            ap,
            purpose,
            [p.key for p in pending if p.key not in files],
            "pending",
            "Generación cancelada.",
        )
        raise
    except render_engine.EngineError as exc:
        _mark(ap, purpose, [p.key for p in pending if p.key not in files], "failed", exc.message)
        raise JobError(exc.message) from exc
    return files


def _mark(ap: anim.Approved, purpose: str, ids: list[str], status: str, error: str) -> None:
    with session_scope() as s:
        for row in s.scalars(
            select(AnimationRender).where(
                AnimationRender.plan_id == ap.plan_id,
                AnimationRender.plan_version == ap.version,
                AnimationRender.purpose == purpose,
                AnimationRender.intervention_id.in_(ids),
            )
        ):
            row.status, row.error = status, error


def _direct_with_claude(ctx: JobContext, ap: anim.Approved, ids: list[str]) -> list[str]:
    """Pide a Claude la dirección de las animaciones que no la tengan. Devuelve avisos."""
    from app.jobs.plan_jobs import Caller

    warnings: list[str] = []
    with session_scope() as s:
        prefs = app_settings.get_claude(s)
        sess = PlanningSession(
            id=new_id("pls"),
            project_id=ap.project.id,
            plan_id=ap.plan_id,
            operation="animate",
            scope=ids,
            status="running",
        )
        s.add(sess)
        sid = sess.id
    call = Caller(ctx, prefs, sid, ap.project.id, system=adir.SYSTEM)
    by_id = {iv["id"]: iv for iv in ap.animated()}
    batches = [ids[i : i + BATCH] for i in range(0, len(ids), BATCH)]
    got = 0
    status = "failed"
    try:
        got = _direct_batches(ctx, ap, call, prefs, by_id, batches, warnings)
        status = "succeeded" if got else "failed"
    except Cancelled:
        status = "cancelled"
        raise
    finally:
        # La sesión siempre se cierra (también al cancelar o fallar): nunca queda «en curso».
        with session_scope() as s:
            row = s.get(PlanningSession, sid)
            if row is not None:
                row.status = status
                row.summary = f"Claude dirigió {got} de {len(ids)} animaciones."
                row.error = " ".join(warnings) or None
                row.finished_at = utcnow()
    return warnings


def _direct_batches(
    ctx: JobContext,
    ap: anim.Approved,
    call: Any,
    prefs: Any,
    by_id: dict[str, dict[str, Any]],
    batches: list[list[str]],
    warnings: list[str],
) -> int:
    got = 0
    for n, batch in enumerate(batches):
        ctx.check_cancelled()
        blocks = adir.build_blocks(
            ap.style, ap.contract.get("direction") or {}, [by_id[i] for i in batch], ap.clock
        )
        sent = {
            "interventions": batch,
            "frame_count": 0,
            "text_chars": len(blocks[0]["text"]),
            "video_file_sent": False,
            "content": (
                "intervenciones aprobadas, transcripción del tramo con ids de palabra y "
                "catálogo de plantillas"
            ),
        }
        try:
            res = call(f"animation {n + 1}/{len(batches)}", blocks, adir.DirResponse, sent)
        except JobError as exc:
            warnings.append(
                f"Claude no pudo dirigir {len(batch)} animación(es): {exc}. "
                "Se usa el compilador determinista."
            )
            continue
        seen: set[str] = set()
        with session_scope() as s:
            for a in res.animations:
                # Solo ids del lote y una dirección por intervención (si Claude repite un id,
                # se queda la primera).
                if a.id not in batch or a.id in seen:
                    continue
                seen.add(a.id)
                s.add(
                    AnimationDirection(
                        id=new_id("ad"),
                        plan_id=ap.plan_id,
                        plan_version=ap.version,
                        intervention_id=a.id,
                        direction=adir.to_direction_dict(a),
                        source="claude",
                        model=call.last.model_reported if call.last else prefs.model,
                    )
                )
                got += 1
        ctx.progress((n + 1) / len(batches))
    return got


@job_handler("animations_prepare", label="Generando animaciones", heavy=True)
def animations_prepare(ctx: JobContext) -> dict[str, Any]:
    use_claude = bool(ctx.payload.get("use_claude", True))
    only = set(ctx.payload.get("only") or []) or None
    ctx.stage("Preparando el plan aprobado", 0.0, 0.05)
    try:
        with session_scope() as s:
            ap = anim.load_approved(s, ctx.project_id or "", ctx.payload.get("plan_version"))
            reused = anim.reuse_directions(s, ap)
        with session_scope() as s:
            dirs = anim.directions(s, ap)
    except PlanError as exc:
        raise JobError(exc.message) from exc
    warnings: list[str] = []
    if reused:
        warnings.append(
            f"Se reutilizó la dirección de Claude de {reused} animación(es) sin cambios de otra "
            "versión del plan (sin nuevas solicitudes)."
        )
    missing = [
        iv["id"] for iv in ap.animated() if iv["id"] not in dirs and (not only or iv["id"] in only)
    ]
    if use_claude and missing:
        ctx.stage("Claude dirige las animaciones", 0.05, 0.3)
        warnings += _direct_with_claude(ctx, ap, missing)
        with session_scope() as s:
            dirs = anim.directions(s, ap)
    ctx.stage("Preparando el motor de render", 0.3, 0.33)
    try:
        render_engine.ensure_bundle(ctx.cancel_event)
    except render_engine.EngineError as exc:
        raise JobError(exc.message) from exc
    compiled = anim.compile_all(ap, "final", dirs, only)
    ctx.stage(f"Renderizando {len(compiled)} animaciones", 0.33, 1.0)
    files = ensure_clips(ctx, ap, "final", compiled, 0.33, 1.0)
    failed = [c["iv"]["id"] for c in compiled if c["iv"]["id"] not in files]
    return {
        "plan_version": ap.version,
        "ready": len(files),
        "failed": failed,
        "kept": len(ap.interventions) - len(ap.animated()),
        "warnings": warnings,
    }


@job_handler("animation_preview", label="Vista previa de animación", heavy=True)
def animation_preview(ctx: JobContext) -> dict[str, Any]:
    iv_id = ctx.payload["intervention_id"]
    ctx.stage("Preparando", 0.0, 0.05)
    try:
        with session_scope() as s:
            ap = anim.load_approved(s, ctx.project_id or "", ctx.payload.get("plan_version"))
            dirs = anim.directions(s, ap)
    except PlanError as exc:
        raise JobError(exc.message) from exc
    compiled = anim.compile_all(ap, "preview", dirs, {iv_id})
    if not compiled:
        raise JobError("Esta intervención no tiene animación (se conserva el video original).")
    c = compiled[0]
    iv = c["iv"]
    t0 = max(0.0, float(iv["start"]) - 1.0)
    t1 = min(float(ap.asset.duration or iv["end"]), float(iv["end"]) + 1.0)
    ctx.stage("Renderizando la animación", 0.05, 0.75)
    files = ensure_clips(ctx, ap, "preview", compiled, 0.05, 0.75)
    if iv_id not in files:
        raise JobError(
            "No se pudo renderizar la animación de esta intervención (ver el error en la lista)."
        )
    ctx.stage("Componiendo sobre el video", 0.75, 1.0)
    out, key = compose_window(ctx, ap, compiled, files, t0, t1, iv_id)
    with session_scope() as s:
        s.add(
            AnimationPreview(
                id=new_id("anp"),
                project_id=ap.project.id,
                plan_id=ap.plan_id,
                plan_version=ap.version,
                intervention_id=iv_id,
                status="ready",
                window_start=t0,
                window_end=t1,
                key=key,
                file_rel=to_rel(ap.root, out),
            )
        )
    return {"intervention_id": iv_id, "file": to_rel(ap.root, out), "window": [t0, t1]}


def compose_window(
    ctx: JobContext,
    ap: anim.Approved,
    compiled: list[dict[str, Any]],
    files: dict[str, Path],
    t0: float,
    t1: float,
    name: str,
) -> tuple[Path, str]:
    """Vista previa de un tramo (540p) con el mismo compositor que la exportación: video,
    animaciones, subtítulos tratados y efectos. El archivo se nombra por contenido, así que una
    vista previa ya hecha se reutiliza y nunca se sobrescribe otra distinta."""
    plan = compositor.preview_plan(ap.asset.display_width, ap.asset.display_height)
    key = hashlib.sha256(
        json.dumps(
            [
                sorted(c["hash"] for c in compiled),
                t0,
                t1,
                anim.subtitle_settings(ap).model_dump(mode="json"),
                anim.current_config(ap).delivery.platform,
                anim.current_config(ap).audio.model_dump(mode="json"),
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()[:24]
    out_dir = ap.project_dir / "previews" / "animations"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{name}-{key}.mp4"
    if out.is_file():
        return out, key
    src = resolve_inside(ap.root, ap.asset.file_rel)
    work = exporter.temp_dir()
    try:
        overlay = None
        track = anim.treated_track(ap, plan.width, plan.height)
        if track is not None:
            # Solo los bloques de la ventana: no se dibujan los subtítulos de todo el video.
            track = {
                **track,
                "blocks": [b for b in track["blocks"] if b["end"] >= t0 and b["start"] <= t1],
            }
            if track["blocks"]:
                exporter.require_work_space(track, work)
                overlay = exporter.render_overlay(
                    track, work, 30.0, float(ap.asset.duration), None, ctx.cancel_event
                )
        comp = anim.composition(ap, compiled, files, plan.width, plan.height)
        tmp = out.with_suffix(".partial.mp4")
        compositor.compose(
            src,
            tmp,
            plan,
            comp,
            overlay,
            float(ap.asset.duration),
            window=(t0, t1),
            preview=True,
            on_progress=ctx.progress,
            cancel=ctx.cancel_event,
        )
        tmp.replace(out)
    except FFmpegError as exc:
        raise JobError(f"No se pudo componer la vista previa: {exc}") from exc
    finally:
        exporter.cleanup(work)
    return out, key


def render_missing(
    ctx: JobContext, ap: anim.Approved, compiled: list[dict[str, Any]]
) -> dict[str, Path]:
    """Renderiza (sin registrar estado por intervención) los clips que falten en la caché.
    Para versiones candidatas: no deben alterar el estado de las animaciones aprobadas."""
    files: dict[str, Path] = {}
    pending: list[render_engine.ClipJob] = []
    for c in compiled:
        hit = anim.cached_clip(ap, c["hash"], c["spec"])
        if hit is not None:
            files[c["iv"]["id"]] = hit
        else:
            pending.append(
                render_engine.ClipJob(c["iv"]["id"], c["spec"], anim.clip_path(ap, c["hash"]))
            )
    if not pending:
        return files
    frames = {p.key: max(1, p.spec["durationInFrames"]) for p in pending}
    total = sum(frames.values())
    done: dict[str, float] = {}

    def on_event(ev: dict[str, Any]) -> None:
        k = ev.get("key")
        if ev.get("type") == "progress" and k:
            done[k] = float(ev.get("progress") or 0)
            ctx.progress(sum(frames[x] * done.get(x, 0) for x in frames) / total)
        elif ev.get("type") == "done" and k:
            files[k] = next(p.out for p in pending if p.key == k)

    try:
        render_engine.render_clips(
            pending, on_event=on_event, cancel=ctx.cancel_event, timeout=max(600.0, total)
        )
    except render_engine.EngineError as exc:
        raise JobError(exc.message) from exc
    return files


@job_handler("engine_install", label="Instalando el navegador de render")
def engine_install(ctx: JobContext) -> dict[str, Any]:
    ctx.stage("Descargando y verificando", 0.0, 1.0)
    try:
        return render_engine.install_browser(ctx.progress, ctx.cancel_event)
    except render_engine.EngineError as exc:
        raise JobError(exc.message) from exc


def export_with_animations(
    ctx: JobContext,
    src: Path,
    partial: Path,
    plan: exporter.ExportPlan,
    duration: float,
    audio_tracks: int,
    work: Path,
) -> dict[str, Any]:
    """Exportación completa: original + animaciones + subtítulos + efectos (llamada desde la
    tarea «export»). Renderiza las animaciones que falten con el tamaño de salida."""
    try:
        with session_scope() as s:
            ap = anim.load_approved(s, ctx.project_id or "")
            dirs = anim.directions(s, ap)
    except PlanError as exc:
        raise JobError(exc.message) from exc
    if ap.asset.color_transfer in HDR_TRANSFERS:
        # Las animaciones se generan en SDR (BT.709); superponerlas sin conversión alteraría su
        # color en un video HDR. En la V1 se informa en vez de degradar el video en silencio.
        raise JobError(
            "Este video es HDR y las animaciones se generan en SDR (BT.709): sus colores no "
            "serían fieles. Exporta sin animaciones para conservar el HDR (la composición con "
            "animaciones en HDR no está disponible en esta versión)."
        )
    # Los clips se diseñan para el encuadre y los fps reales de esta exportación.
    fps = float(plan.fps) if plan.fps != "original" else float(ap.asset.fps or 30.0)
    size = (plan.width, plan.height, min(60.0, fps))
    compiled = anim.compile_all(ap, "final", dirs, size=size)
    ctx.stage("Renderizando animaciones", 0.0, 0.5)
    started = time.monotonic()
    render_engine.ensure_bundle(ctx.cancel_event)
    files = ensure_clips(ctx, ap, "final", compiled, 0.0, 0.5, size=size)
    missing = [c["iv"]["id"] for c in compiled if c["iv"]["id"] not in files]
    if missing:
        raise JobError(
            f"No se pudieron generar {len(missing)} animación(es) ({', '.join(missing)}). "
            "Revisa el error en Plan IA → Animaciones y reinténtalo; no se exporta un video "
            "incompleto."
        )
    ctx.stage("Preparando subtítulos", 0.5, 0.6)
    overlay = None
    track = anim.treated_track(ap, plan.width, plan.height)
    if track is not None:
        fps = float(plan.fps) if plan.fps != "original" else (ap.asset.fps or 30.0)
        exporter.require_work_space(track, work)
        overlay = exporter.render_overlay(
            track, work, min(fps, 30.0), duration, ctx.progress, ctx.cancel_event
        )
    ctx.stage("Componiendo y codificando", 0.6, 1.0)
    comp = anim.composition(ap, compiled, files, plan.width, plan.height)
    compositor.compose(
        src,
        partial,
        plan,
        comp,
        overlay,
        duration,
        audio_tracks=audio_tracks,
        on_progress=ctx.progress,
        cancel=ctx.cancel_event,
    )
    return {
        "plan_version": ap.version,
        "animations": len(files),
        "kept": len(ap.interventions) - len(ap.animated()),
        "sfx": len(comp.sfx) if comp.sfx_volume > 0 else 0,
        "render_seconds": round(time.monotonic() - started, 1),
        "subtitles": track is not None,
    }
