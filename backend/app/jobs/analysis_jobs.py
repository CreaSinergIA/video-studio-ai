"""Tareas de la Fase 2: transcripción, análisis visual, realineado, exportación y modelos."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from app.config import get_settings
from app.db import session_scope
from app.domain.edit_config import EditConfig
from app.domain.preferences import AnalysisPreferences
from app.jobs.media_jobs import _load
from app.jobs.runner import JobContext, JobError, job_handler
from app.models import Analysis, AnalysisFrame, Export, MediaAsset, Project, new_id, utcnow
from app.services import (
    analysis_bundle,
    app_settings,
    asr_models,
    audio,
    exporter,
    subtitles,
    transcription,
    visual_analysis,
)
from app.services import transcripts as transcript_service
from app.services.media_tools import Cancelled, FFmpegError
from app.services.storage import (
    StorageError,
    require_space,
    resolve_inside,
    rmtree_tolerant,
    sanitize_filename,
    slugify,
    to_rel,
)

log = logging.getLogger(__name__)


def _prefs(ctx: JobContext) -> AnalysisPreferences:
    with session_scope() as s:
        prefs = app_settings.get_analysis(s)
    overrides = {k: v for k, v in ctx.payload.items() if k in ("transcription_model", "language")}
    return prefs.model_copy(update=overrides) if overrides else prefs


def _bundle(asset_id: str, root: Path) -> None:
    with session_scope() as s:
        asset = s.get(MediaAsset, asset_id)
        if asset is not None:
            analysis_bundle.write_bundle(s, asset, root)


@job_handler("transcribe", label="Transcribiendo audio", resumable=True, heavy=True)
def transcribe(ctx: JobContext) -> dict[str, Any]:
    asset, root, _src = _load(ctx)
    prefs = _prefs(ctx)
    try:
        result = transcription.transcribe_asset(
            asset,
            root,
            prefs,
            on_stage=ctx.stage,
            on_progress=ctx.progress,
            cancel=ctx.cancel_event,
        )
    except asr_models.ModelError as exc:
        raise JobError(exc.message) from exc
    except (transcription.TranscriptionError, audio.AudioError) as exc:
        raise JobError(str(exc)) from exc
    _bundle(asset.id, root)
    return result


@job_handler("analyze_visual", label="Analizando escenas y fotogramas", resumable=True, heavy=True)
def analyze_visual(ctx: JobContext) -> dict[str, Any]:
    settings = get_settings()
    asset, root, src = _load(ctx)
    prefs = _prefs(ctx)
    phash = visual_analysis.params_hash(asset.sha256, prefs)
    with session_scope() as s:
        cached = s.scalar(
            select(Analysis).where(
                Analysis.asset_id == asset.id,
                Analysis.kind == "visual",
                Analysis.params_hash == phash,
            )
        )
        if cached is not None:
            frames = s.scalars(
                select(AnalysisFrame).where(AnalysisFrame.analysis_id == cached.id)
            ).all()
            if all(resolve_inside(root, f.file_rel).is_file() for f in frames):
                s.execute(
                    update(Analysis)
                    .where(Analysis.asset_id == asset.id, Analysis.kind == "visual")
                    .values(is_active=False)
                )
                cached.is_active = True
                return {"analysis_id": cached.id, "reused": True}
    frames_dir: Path | None = None
    try:
        ctx.stage("Recorriendo el video (cortes, transiciones, movimiento)", 0.0, 0.55)
        st = visual_analysis.decode_stats(
            settings.ffmpeg,
            src,
            asset.display_width,
            asset.display_height,
            asset.duration,
            on_progress=ctx.progress,
            cancel=ctx.cancel_event,
        )
        if not st.times:
            raise JobError("No se pudo decodificar ningún fotograma del video.")
        scenes, transitions = visual_analysis.build_scenes(st, asset.duration, prefs)
        statics = visual_analysis.static_intervals(st, prefs.static_min_seconds)
        plan = visual_analysis.plan_frames(st, scenes, prefs)
        analysis_id = new_id("ana")
        project_dir = src.parents[1]
        frames_dir = project_dir / "frames" / "analysis" / analysis_id
        frames_dir.parent.mkdir(exist_ok=True)
        frames_dir.mkdir()
        require_space(root, len(plan) * 2 * 1024 * 1024)
        ctx.stage(f"Extrayendo {len(plan)} fotogramas representativos", 0.55, 0.85)
        done = {"n": 0}

        def extract(p: dict[str, Any]) -> dict[str, Any]:
            ctx.check_cancelled()
            name = f"f_{round(p['t'] * 1000):08d}_{p['reason']}.jpg"
            dest = frames_dir / name
            w, h = visual_analysis.extract_frame(settings.ffmpeg, src, p["t"], dest)
            done["n"] += 1
            ctx.progress(done["n"] / max(1, len(plan)))
            return {**p, "file": dest, "width": w, "height": h}

        extracted = visual_analysis.run_parallel(plan, extract)
        faces_enabled = prefs.detect_faces
        if faces_enabled:
            ctx.stage("Detectando rostros", 0.85, 0.97)
            detector = visual_analysis.FaceDetector()
            for i, e in enumerate(extracted):
                ctx.check_cancelled()
                e["faces"] = detector.detect(e["file"])
                ctx.progress((i + 1) / max(1, len(extracted)))
        for sc in scenes:
            sc_frames = [
                {"faces": e.get("faces") if faces_enabled else None}
                for e in extracted
                if e["scene_index"] == sc["index"]
            ]
            summary = visual_analysis.summarize_faces(sc_frames)
            sc["faces"] = summary
            sc["labels"]["faces"] = summary["status"]
            sc.pop("first_frame_index", None)
            sc.pop("last_frame_index", None)
        ctx.stage("Guardando resultados", 0.97, 1.0)
        result = {
            "version": visual_analysis.PIPELINE_VERSION,
            "duration": asset.duration,
            "frames_analyzed": len(st.times),
            "scenes": scenes,
            "transitions": transitions,
            "static_intervals": [[round(a, 3), round(b, 3)] for a, b in statics],
            "frames_extracted": len(extracted),
            "faces_enabled": faces_enabled,
        }
        with session_scope() as s:
            old_ids = s.scalars(
                select(Analysis.id).where(Analysis.asset_id == asset.id, Analysis.kind == "visual")
            ).all()
            s.execute(
                update(Analysis)
                .where(Analysis.asset_id == asset.id, Analysis.kind == "visual")
                .values(is_active=False)
            )
            s.add(
                Analysis(
                    id=analysis_id,
                    asset_id=asset.id,
                    kind="visual",
                    params_hash=phash,
                    params=prefs.model_dump(mode="json"),
                    result=result,
                    is_active=True,
                )
            )
            s.flush()
            for e in extracted:
                s.add(
                    AnalysisFrame(
                        id=new_id("frm"),
                        asset_id=asset.id,
                        analysis_id=analysis_id,
                        t=round(e["t"], 6),
                        reason=e["reason"],
                        scene_index=e["scene_index"],
                        file_rel=to_rel(root, e["file"]),
                        width=e["width"],
                        height=e["height"],
                        faces=e.get("faces") if faces_enabled else None,
                        metrics={"frame_index": e["frame_index"]},
                    )
                )
            # Los análisis anteriores conservan su resultado (historial), pero sus fotogramas se
            # eliminan: en exFAT cada archivo ocupa al menos 1 MB.
            for old in old_ids:
                old_frames = s.scalars(
                    select(AnalysisFrame).where(AnalysisFrame.analysis_id == old)
                ).all()
                for f in old_frames:
                    with contextlib.suppress(OSError, StorageError):
                        resolve_inside(root, f.file_rel).unlink()
                    s.delete(f)
                with contextlib.suppress(OSError):
                    rmtree_tolerant(frames_dir.parent / old)
    except BaseException:
        # Cualquier fallo (también del detector de rostros) no deja fotogramas huérfanos.
        if frames_dir is not None:
            rmtree_tolerant(frames_dir)
        raise
    _bundle(asset.id, root)
    return {
        "analysis_id": analysis_id,
        "reused": False,
        "scenes": len(scenes),
        "frames": len(extracted),
    }


@job_handler("align_segments", label="Realineando texto corregido con el audio", heavy=True)
def align_segments(ctx: JobContext) -> dict[str, Any]:
    settings = get_settings()
    asset, root, src = _load(ctx)
    prefs = _prefs(ctx)
    tid, seg_ids = ctx.payload["transcript_id"], set(ctx.payload["segment_ids"])
    with session_scope() as s:
        t = transcript_service.get_transcript(s, tid)
        items = [
            {
                "id": seg["id"],
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "language": seg.get("language") or t.language,
            }
            for seg in t.segments
            if seg["id"] in seg_ids
        ]
        model_id = t.model if t.model in asr_models.CATALOG else prefs.transcription_model
    if not items:
        raise JobError("No hay segmentos que realinear.")
    too_long = [it["id"] for it in items if it["end"] - it["start"] > 29.0]
    if too_long:
        raise JobError(
            "Un segmento dura más de 29 s y no cabe en una ventana de alineación de Whisper. "
            "Ajusta sus tiempos a mano."
        )
    try:
        spec = asr_models.require_usable(model_id)
        model_path = asr_models.installed_path(model_id)
    except asr_models.ModelError as exc:
        raise JobError(exc.message) from exc
    tmp = transcription.work_dir()
    try:
        ctx.stage("Extrayendo audio", 0.0, 0.15)
        wav = tmp / "audio.wav"
        audio.extract_audio(settings.ffmpeg, src, wav, ctx.cancel_event)
        db = audio.energy_envelope(wav)
        ctx.stage("Alineando palabras con el audio", 0.15, 0.95)
        result = transcription.run_worker(
            {
                "mode": "align",
                "engine": spec.engine,
                "wav": str(wav),
                "model_dir": str(model_path),
                "segments": items,
                "out": str(tmp / "result.json"),
            },
            ctx.progress,
            ctx.cancel_event,
        )
    except (transcription.TranscriptionError, audio.AudioError) as exc:
        raise JobError(str(exc)) from exc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    aligned: dict[str, list[dict[str, Any]]] = {}
    for seg in result["segments"]:
        words = seg["words"]
        audio.refine_word_times(words, db)
        aligned[seg["id"]] = words
    with session_scope() as s:
        t = transcript_service.get_transcript(s, tid)
        expected = {it["id"]: it["text"] for it in items}
        t, skipped = transcript_service.apply_alignment(s, t, aligned, expected)
        s.flush()
        transcription.write_snapshot(root, asset, t)
    _bundle(asset.id, root)
    if skipped and len(skipped) == len(aligned):
        raise JobError("El texto cambió mientras se realineaba; no se aplicó. Vuelve a realinear.")
    return {"segments": len(aligned) - len(skipped), "skipped_edited": skipped}


def _abort_export(payload: dict[str, Any], status: str, message: str) -> None:
    if payload.get("export_id"):
        _finish_export(payload["export_id"], status, error=message, only_if_active=True)


@job_handler("export", label="Exportando video", heavy=True, on_abort=_abort_export)
def export_video(ctx: JobContext) -> dict[str, Any]:
    """Envoltorio: cualquier fallo (también previo a codificar) deja la exportación en un
    estado final coherente (fallida o cancelada), nunca «en cola» indefinidamente."""
    export_id = ctx.payload["export_id"]
    try:
        return _export_video(ctx, export_id)
    except Cancelled:
        _finish_export(export_id, "cancelled", error="Exportación cancelada.", only_if_active=True)
        raise
    except Exception as exc:
        message = exc.message if isinstance(exc, StorageError) else str(exc)
        _finish_export(export_id, "failed", error=message, only_if_active=True)
        raise


def _export_video(ctx: JobContext, export_id: str) -> dict[str, Any]:
    asset, root, src = _load(ctx)
    with session_scope() as s:
        exp = s.get(Export, export_id)
        if exp is None:
            raise JobError("La exportación ya no existe.")
        project = s.get(Project, exp.project_id)
        assert project is not None
        config = EditConfig.model_validate(project.config)
        transcript = transcript_service.active_for_asset(s, asset.id)
        segments = list(transcript.segments) if transcript else []
        analysis = analysis_bundle.active_visual(s, asset.id)
        scenes = list(analysis.result.get("scenes", [])) if analysis else []
        exp.status, exp.transcript_id = "running", transcript.id if transcript else None
        project_name, project_dir_rel = project.name, project.dir_rel
        with_animations = bool((exp.settings or {}).get("with_animations"))
    settings_snapshot = config.export
    try:
        plan = exporter.plan_export(asset, settings_snapshot)
    except exporter.ExportError as exc:
        _finish_export(export_id, "failed", error=exc.message)
        raise JobError(exc.message) from exc
    require_space(root, plan.estimated_bytes)
    exports_dir = resolve_inside(root, project_dir_rel) / "exports"
    exports_dir.mkdir(exist_ok=True)
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    name = sanitize_filename(
        f"{slugify(project_name, 60)}_{plan.width}x{plan.height}_{plan.video_codec}_{stamp}"
        f".{plan.container}"
    )
    final = exports_dir / name
    partial = exports_dir / f".{name}.partial.{plan.container}"
    work = exporter.temp_dir()
    if with_animations:
        return _export_animated(
            ctx, export_id, src, partial, final, plan, asset, root, settings_snapshot, work
        )
    try:
        overlay = None
        with_subs = config.subtitles.enabled and bool(segments)
        if with_subs:
            ctx.stage("Preparando subtítulos", 0.0, 0.15)
            # Misma maquetación que la vista previa (tamaño original) escalada a la salida.
            track = subtitles.scale_track(
                subtitles.build_track(
                    segments,
                    config.subtitles,
                    asset.display_width,
                    asset.display_height,
                    scenes,
                    config.delivery.platform,
                ),
                plan.width,
                plan.height,
            )
            fps = float(plan.fps) if plan.fps != "original" else (asset.fps or 30.0)
            # Pasos de animación a ≤ 30 por segundo: suficiente para «pop»/fundidos y acota el
            # número de imágenes en videos largos.
            exporter.require_work_space(track, work)
            overlay = exporter.render_overlay(
                track, work, min(fps, 30.0), asset.duration, ctx.progress, ctx.cancel_event
            )
        ctx.stage("Codificando video", 0.15 if with_subs else 0.0, 1.0)
        exporter.encode(
            src,
            partial,
            plan,
            overlay,
            asset.duration,
            on_progress=ctx.progress,
            cancel=ctx.cancel_event,
        )
        os.replace(partial, final)
    except Cancelled:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
        _finish_export(export_id, "cancelled", error="Exportación cancelada.")
        raise
    except (FFmpegError, OSError, StorageError) as exc:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
        message = exc.message if isinstance(exc, StorageError) else str(exc)
        _finish_export(export_id, "failed", error=message)
        raise JobError(message) from exc
    finally:
        exporter.cleanup(work)
    return _finalize_export(
        export_id, root, final, settings_snapshot, plan, with_subs, None, src=src, asset=asset
    )


def _export_animated(
    ctx: JobContext,
    export_id: str,
    src: Path,
    partial: Path,
    final: Path,
    plan: Any,
    asset: MediaAsset,
    root: Path,
    settings_snapshot: Any,
    work: Path,
) -> dict[str, Any]:
    """Exportación con las animaciones del plan aprobado (Fase 4)."""
    from app.jobs import animation_jobs

    tracks = len(asset.audio_tracks or []) if asset.has_audio else 0
    try:
        info = animation_jobs.export_with_animations(
            ctx, src, partial, plan, asset.duration, tracks, work
        )
        os.replace(partial, final)
    except Cancelled:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
        _finish_export(export_id, "cancelled", error="Exportación cancelada.")
        raise
    except (JobError, FFmpegError, OSError, StorageError) as exc:
        with contextlib.suppress(FileNotFoundError):
            partial.unlink()
        message = exc.message if isinstance(exc, StorageError) else str(exc)
        _finish_export(export_id, "failed", error=message)
        raise JobError(message) from exc
    finally:
        exporter.cleanup(work)
    return _finalize_export(
        export_id,
        root,
        final,
        settings_snapshot,
        plan,
        bool(info.get("subtitles")),
        info,
        src=src,
        asset=asset,
    )


def _finalize_export(
    export_id: str,
    root: Path,
    final: Path,
    settings_snapshot: Any,
    plan: Any,
    with_subs: bool,
    animation_info: dict[str, Any] | None,
    *,
    src: Path,
    asset: MediaAsset,
) -> dict[str, Any]:
    fps = float(plan.fps) if plan.fps != "original" else float(asset.fps or 30.0)
    check = exporter.verify_output(
        final,
        src,
        width=plan.width,
        height=plan.height,
        duration=float(asset.duration or 0),
        fps=fps,
        expect_audio=bool(asset.has_audio) and "-an" not in plan.audio_args,
    )
    if not check["ok"]:
        # No se entrega como buena, pero tampoco se destruye un render largo: se aparta con otro
        # nombre para revisarlo (clips y subtítulos siguen en caché; «Reintentar» lo repite).
        kept = final.with_name(f"{final.stem}.no-verificado{final.suffix}")
        with contextlib.suppress(OSError):
            os.replace(final, kept)
        message = (
            "La exportación no superó la verificación: "
            + " ".join(check["errors"])
            + f" Se conserva aparte como «{kept.name}» para revisarla."
        )
        _finish_export(export_id, "failed", error=message)
        raise JobError(message)
    info = exporter.probe_output(final)
    vstream: dict[str, Any] = next(
        (st for st in info.get("streams", []) if st.get("codec_type") == "video"), {}
    )
    _finish_export(
        export_id,
        "succeeded",
        file_rel=to_rel(root, final),
        size_bytes=final.stat().st_size,
        width=vstream.get("width"),
        height=vstream.get("height"),
        duration=float(info.get("format", {}).get("duration") or 0) or None,
        settings={
            **settings_snapshot.model_dump(mode="json"),
            "plan": plan.to_dict(),
            "subtitles": with_subs,
            "with_animations": animation_info is not None,
            "animations": animation_info,
            "verification": check,
        },
    )
    return {
        "export_id": export_id,
        "file": to_rel(root, final),
        "subtitles": with_subs,
        "animations": animation_info,
    }


def _finish_export(
    export_id: str, status: str, *, only_if_active: bool = False, **values: Any
) -> None:
    with session_scope() as s:
        exp = s.get(Export, export_id)
        if exp is None:
            return
        if only_if_active and exp.status not in ("queued", "running"):
            return
        exp.status = status
        exp.finished_at = utcnow()
        for k, v in values.items():
            setattr(exp, k, v)


@job_handler("download_model", label="Descargando modelo de transcripción")
def download_model(ctx: JobContext) -> dict[str, Any]:
    model_id = ctx.payload["model_id"]
    ctx.stage("Descargando y verificando", 0.0, 1.0)

    def progress(value: float, stage: str) -> None:
        ctx.progress(value)

    try:
        path = asr_models.download(model_id, progress, ctx.cancel_event)
    except asr_models.ModelError as exc:
        raise JobError(exc.message) from exc
    except OSError as exc:
        raise JobError(f"Error de red o disco al descargar: {exc}") from exc
    return {"model_id": model_id, "path": str(path)}
