"""API de la Fase 2: análisis, transcripción, subtítulos, fotogramas, exportación y modelos."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.domain.edit_config import EditConfig, ExportSettings
from app.domain.preferences import AnalysisPreferences
from app.jobs.runner import ACTIVE_STATUSES, create_job, runner
from app.models import AnalysisFrame, Export, Job, MediaAsset, Project, Transcript, new_id
from app.services import analysis_bundle, app_settings, asr_models, exporter, native, subtitles
from app.services import projects as project_service
from app.services import transcripts as transcript_service
from app.services.storage import StorageError, resolve_inside, slugify, to_rel
from app.services.storage_manager import storage_manager
from app.services.visual_analysis import extract_frame

router = APIRouter(tags=["análisis"])


# --- utilidades ------------------------------------------------------------


def _source(session: Session, project_id: str) -> tuple[Project, MediaAsset]:
    project = project_service.get_project(session, project_id)
    asset = next((a for a in project.assets if a.role == "source"), None)
    if asset is None:
        raise StorageError("no_source", "El proyecto todavía no tiene video.", 409)
    return project, asset


def _active_job(session: Session, asset_id: str, kind: str) -> Job | None:
    return session.scalar(
        select(Job).where(
            Job.asset_id == asset_id, Job.kind == kind, Job.status.in_(ACTIVE_STATUSES)
        )
    )


def transcript_out(t: Transcript | None) -> dict[str, Any] | None:
    if t is None:
        return None
    return {
        "id": t.id,
        "asset_id": t.asset_id,
        "kind": t.kind,
        "parent_id": t.parent_id,
        "is_active": t.is_active,
        "status": t.status,
        "engine": t.engine,
        "model": t.model,
        "language": t.language,
        "stats": t.stats,
        "segments": t.segments,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def frame_out(f: AnalysisFrame) -> dict[str, Any]:
    return analysis_bundle.frame_ref(f)


# --- lanzar análisis --------------------------------------------------------


class AnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcribe: bool = True
    visual: bool = True
    transcription_model: str | None = None
    language: str | None = None


@router.post("/projects/{project_id}/analyze", status_code=202)
def analyze(project_id: str, body: AnalyzeRequest, session: Session = Depends(get_session)):
    _, asset = _source(session, project_id)
    storage_manager.require_location(asset.project.storage)
    prefs = app_settings.get_analysis(session)
    model_id = body.transcription_model or prefs.transcription_model
    jobs: list[Job] = []
    if body.transcribe:
        if asset.has_audio:
            if not asr_models.platform_supported():
                raise StorageError(
                    "asr_unsupported",
                    "La transcripción local con MLX requiere un Mac con Apple Silicon.",
                    501,
                )
            asr_models.installed_path(model_id)
        existing = _active_job(session, asset.id, "transcribe")
        payload: dict[str, Any] = {"transcription_model": model_id}
        if body.language:
            payload["language"] = body.language
        jobs.append(
            existing
            or create_job(
                session, "transcribe", project_id=project_id, asset_id=asset.id, payload=payload
            )
        )
    if body.visual:
        existing = _active_job(session, asset.id, "analyze_visual")
        jobs.append(
            existing
            or create_job(session, "analyze_visual", project_id=project_id, asset_id=asset.id)
        )
    session.commit()
    runner.wake()
    return {"jobs": [project_service.job_out(j) for j in jobs]}


@router.get("/projects/{project_id}/analysis")
def analysis_state(project_id: str, session: Session = Depends(get_session)):
    """Estado completo del análisis del proyecto (transcripción, escenas, fotogramas)."""
    _, asset = _source(session, project_id)
    transcript = transcript_service.active_for_asset(session, asset.id)
    visual = analysis_bundle.active_visual(session, asset.id)
    frames = analysis_bundle.frames_for(session, visual.id if visual else None, asset.id)
    return {
        "asset_id": asset.id,
        "transcript": transcript_out(transcript),
        "versions": [
            {
                "id": t.id,
                "kind": t.kind,
                "model": t.model,
                "language": t.language,
                "status": t.status,
                "is_active": t.is_active,
                "created_at": t.created_at,
                "parent_id": t.parent_id,
            }
            for t in transcript_service.versions_for_asset(session, asset.id)
        ],
        "visual": None
        if visual is None
        else {
            "id": visual.id,
            "params": visual.params,
            "created_at": visual.created_at,
            **visual.result,
        },
        "frames": [frame_out(f) for f in frames],
        "timing_labels": transcript_service.TIMING_LABELS,
    }


@router.get("/projects/{project_id}/bundle")
def bundle(project_id: str, session: Session = Depends(get_session)):
    """Paquete estructurado para la Fase 3 (sin interpretación creativa)."""
    _, asset = _source(session, project_id)
    return analysis_bundle.build_bundle(session, asset)


# --- transcripciones -----------------------------------------------------------


class SegmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(default=None, max_length=5000)
    reviewed: bool | None = None


class WordTime(BaseModel):
    id: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class SegmentTimes(BaseModel):
    words: list[WordTime] = Field(min_length=1)


class RealignRequest(BaseModel):
    segment_ids: list[str] = Field(min_length=1, max_length=500)


def _transcript(session: Session, transcript_id: str) -> Transcript:
    return transcript_service.get_transcript(session, transcript_id)


def _refresh_outputs(session: Session, t: Transcript) -> None:
    """Tras editar: copia JSON de la versión y paquete de la Fase 3 al día (si hay disco)."""
    from app.services.transcription import write_snapshot

    asset = session.get(MediaAsset, t.asset_id)
    if asset is None:
        return
    try:
        root = storage_manager.require_location(asset.project.storage)
    except StorageError:
        return
    write_snapshot(root, asset, t)
    analysis_bundle.write_bundle(session, asset, root)


@router.get("/transcripts/{transcript_id}")
def get_transcript(transcript_id: str, session: Session = Depends(get_session)):
    return transcript_out(_transcript(session, transcript_id))


@router.patch("/transcripts/{transcript_id}/segments/{segment_id}")
def patch_segment(
    transcript_id: str,
    segment_id: str,
    body: SegmentPatch,
    session: Session = Depends(get_session),
):
    t = _transcript(session, transcript_id)
    if body.text is not None:
        t = transcript_service.update_segment_text(session, t, segment_id, body.text)
    if body.reviewed is not None:
        t = transcript_service.set_reviewed(session, t, segment_id, body.reviewed)
    session.commit()
    _refresh_outputs(session, t)
    return transcript_out(t)


@router.put("/transcripts/{transcript_id}/segments/{segment_id}/times")
def put_times(
    transcript_id: str,
    segment_id: str,
    body: SegmentTimes,
    session: Session = Depends(get_session),
):
    t = _transcript(session, transcript_id)
    duration = transcript_service.media_duration(session, t)
    t = transcript_service.update_word_times(
        session, t, segment_id, [w.model_dump() for w in body.words], duration
    )
    session.commit()
    _refresh_outputs(session, t)
    return transcript_out(t)


@router.post("/transcripts/{transcript_id}/realign", status_code=202)
def realign(transcript_id: str, body: RealignRequest, session: Session = Depends(get_session)):
    t = _transcript(session, transcript_id)
    asset = session.get(MediaAsset, t.asset_id)
    assert asset is not None
    storage_manager.require_location(asset.project.storage)
    edited = transcript_service.editable(session, t)
    job = create_job(
        session,
        "align_segments",
        project_id=asset.project_id,
        asset_id=asset.id,
        payload={"transcript_id": edited.id, "segment_ids": body.segment_ids},
    )
    session.commit()
    runner.wake()
    return {"job": project_service.job_out(job), "transcript_id": edited.id}


@router.post("/transcripts/{transcript_id}/activate")
def activate(transcript_id: str, session: Session = Depends(get_session)):
    t = _transcript(session, transcript_id)
    transcript_service.activate(session, t)
    session.commit()
    _refresh_outputs(session, t)
    return transcript_out(t)


@router.get("/transcripts/{transcript_id}/export")
def export_text(
    transcript_id: str,
    format: Literal["txt", "srt", "vtt"] = Query(default="srt"),
    session: Session = Depends(get_session),
):
    t = _transcript(session, transcript_id)
    asset = session.get(MediaAsset, t.asset_id)
    project = session.get(Project, asset.project_id) if asset else None
    body = {
        "txt": transcript_service.to_txt,
        "srt": transcript_service.to_srt,
        "vtt": transcript_service.to_vtt,
    }[format](t.segments)
    media = {"txt": "text/plain", "srt": "application/x-subrip", "vtt": "text/vtt"}[format]
    name = f"{slugify(project.name if project else 'transcripcion', 60)}.{format}"
    return Response(
        content=body.encode("utf-8"),
        media_type=f"{media}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


# --- subtítulos -----------------------------------------------------------------


@router.get("/projects/{project_id}/subtitles/track")
def subtitle_track(project_id: str, session: Session = Depends(get_session)):
    """Pista calculada con la configuración actual del proyecto (vista previa del panel)."""
    project, asset = _source(session, project_id)
    config = EditConfig.model_validate(project.config)
    transcript = transcript_service.active_for_asset(session, asset.id)
    visual = analysis_bundle.active_visual(session, asset.id)
    scenes = (visual.result.get("scenes") if visual else None) or []
    track = subtitles.build_track(
        transcript.segments if transcript else [],
        config.subtitles,
        asset.display_width,
        asset.display_height,
        scenes,
        config.delivery.platform,
    )
    track["transcript_id"] = transcript.id if transcript else None
    return track


@router.get("/fonts")
def fonts():
    return subtitles.font_faces()


@router.get("/fonts/{name}")
def font_file(name: str):
    allowed = {f["file"] for f in subtitles.font_faces()}
    if name not in allowed:
        raise StorageError("font_not_found", "Tipografía no disponible.", 404)
    return FileResponse(
        subtitles.FONTS_DIR / name,
        media_type="font/ttf",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# --- fotogramas -------------------------------------------------------------------


class FrameRequest(BaseModel):
    t: float = Field(ge=0)


@router.post("/projects/{project_id}/frames", status_code=201)
def capture_frame(project_id: str, body: FrameRequest, session: Session = Depends(get_session)):
    """Extrae bajo demanda el fotograma en ``t`` (con caché: el mismo instante no se repite)."""
    project, asset = _source(session, project_id)
    root = storage_manager.require_location(project.storage)
    t = min(body.t, max(0.0, asset.duration - 0.01))
    existing = session.scalar(
        select(AnalysisFrame).where(
            AnalysisFrame.asset_id == asset.id,
            AnalysisFrame.reason == "on_demand",
            AnalysisFrame.t.between(t - 0.0005, t + 0.0005),
        )
    )
    if existing is not None:
        return frame_out(existing)
    frames_dir = resolve_inside(root, project.dir_rel) / "frames"
    target_dir = frames_dir / "on_demand"
    target_dir.mkdir(exist_ok=True)
    dest = target_dir / f"f_{round(t * 1000):08d}_on_demand.jpg"
    w, h = extract_frame(get_settings().ffmpeg, resolve_inside(root, asset.file_rel), t, dest)
    from app.services.visual_analysis import FaceDetector

    faces = FaceDetector().detect(dest)
    frame = AnalysisFrame(
        id=new_id("frm"),
        asset_id=asset.id,
        analysis_id=None,
        t=round(t, 6),
        reason="on_demand",
        scene_index=None,
        file_rel=to_rel(root, dest),
        width=w,
        height=h,
        faces=faces,
        metrics={},
    )
    session.add(frame)
    session.commit()
    return frame_out(frame)


@router.get("/frames/{frame_id}/image")
def frame_image(frame_id: str, session: Session = Depends(get_session, scope="function")):
    frame = session.get(AnalysisFrame, frame_id)
    if frame is None:
        raise StorageError("frame_not_found", "El fotograma no existe.", 404)
    asset = session.get(MediaAsset, frame.asset_id)
    assert asset is not None
    root = storage_manager.require_location(asset.project.storage)
    path = resolve_inside(root, frame.file_rel)
    if not path.is_file():
        raise StorageError("file_missing", "El archivo del fotograma no está en el disco.", 404)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


@router.delete("/frames/{frame_id}", status_code=204)
def delete_frame(frame_id: str, session: Session = Depends(get_session)):
    frame = session.get(AnalysisFrame, frame_id)
    if frame is None or frame.reason != "on_demand":
        raise StorageError("frame_not_found", "Solo se pueden borrar capturas manuales.", 404)
    asset = session.get(MediaAsset, frame.asset_id)
    assert asset is not None
    root = storage_manager.require_location(asset.project.storage)
    path = resolve_inside(root, frame.file_rel)
    path.unlink(missing_ok=True)
    session.delete(frame)
    session.commit()


# --- exportaciones --------------------------------------------------------------


def export_out(e: Export, job: Job | None = None) -> dict[str, Any]:
    return {
        "id": e.id,
        "project_id": e.project_id,
        "status": e.status,
        "settings": e.settings,
        "file_rel": e.file_rel,
        "file_name": e.file_rel.rsplit("/", 1)[-1] if e.file_rel else None,
        "size_bytes": e.size_bytes,
        "width": e.width,
        "height": e.height,
        "duration": e.duration,
        "error": e.error,
        "job_id": e.job_id,
        "job": project_service.job_out(job) if job else None,
        "created_at": e.created_at,
        "finished_at": e.finished_at,
        "url": f"/api/exports/{e.id}/file" if e.status == "succeeded" else None,
    }


class ExportRequest(BaseModel):
    settings: ExportSettings | None = None
    # Fase 4: incluir las animaciones, efectos y tratamiento de subtítulos del plan aprobado.
    with_animations: bool = False


@router.post("/projects/{project_id}/exports/plan")
def plan(project_id: str, body: ExportRequest, session: Session = Depends(get_session)):
    project, asset = _source(session, project_id)
    config = EditConfig.model_validate(project.config)
    settings = body.settings or config.export
    try:
        p = exporter.plan_export(asset, settings)
    except exporter.ExportError as exc:
        return {"ok": False, "error": exc.message, "code": exc.code}
    transcript = transcript_service.active_for_asset(session, asset.id)
    return {
        "ok": True,
        "plan": p.to_dict(),
        "subtitles": bool(config.subtitles.enabled and transcript and transcript.segments),
    }


@router.post("/projects/{project_id}/exports", status_code=202)
def create_export(project_id: str, body: ExportRequest, session: Session = Depends(get_session)):
    project, asset = _source(session, project_id)
    storage_manager.require_location(project.storage)
    if body.settings is not None:
        config = EditConfig.model_validate(project.config)
        config.export = body.settings
        project_service.update_config(session, project, config)
    config = EditConfig.model_validate(project.config)
    try:
        exporter.plan_export(asset, config.export)
    except exporter.ExportError as exc:
        raise StorageError(exc.code, exc.message, 422) from exc
    exp = Export(
        id=new_id("exp"),
        project_id=project.id,
        asset_id=asset.id,
        status="queued",
        settings={**config.export.model_dump(mode="json"), "with_animations": body.with_animations},
    )
    session.add(exp)
    session.flush()
    job = create_job(
        session, "export", project_id=project.id, asset_id=asset.id, payload={"export_id": exp.id}
    )
    exp.job_id = job.id
    session.commit()
    runner.wake()
    return export_out(exp, job)


@router.get("/projects/{project_id}/exports")
def list_exports(project_id: str, session: Session = Depends(get_session)):
    project_service.get_project(session, project_id)
    rows = session.scalars(
        select(Export).where(Export.project_id == project_id).order_by(Export.created_at.desc())
    ).all()
    jobs = {
        j.id: j
        for j in session.scalars(
            select(Job).where(Job.id.in_([e.job_id for e in rows if e.job_id]))
        )
    }
    return [export_out(e, jobs.get(e.job_id or "")) for e in rows]


def _export(session: Session, export_id: str) -> Export:
    e = session.get(Export, export_id)
    if e is None:
        raise StorageError("export_not_found", "La exportación no existe.", 404)
    return e


def _export_path(session: Session, e: Export) -> Path:
    if not e.file_rel:
        raise StorageError("not_ready", "La exportación aún no está lista.", 409)
    project = session.get(Project, e.project_id)
    assert project is not None
    root = storage_manager.require_location(project.storage)
    path = resolve_inside(root, e.file_rel)
    if not path.is_file():
        raise StorageError("file_missing", "El archivo exportado ya no está en el disco.", 404)
    return path


@router.get("/exports/{export_id}/file")
def export_file(
    export_id: str,
    download: bool = False,
    session: Session = Depends(get_session, scope="function"),
):
    e = _export(session, export_id)
    path = _export_path(session, e)
    media = "video/quicktime" if path.suffix == ".mov" else "video/mp4"
    return FileResponse(
        path,
        media_type=media,
        filename=path.name,
        content_disposition_type="attachment" if download else "inline",
    )


@router.post("/exports/{export_id}/reveal")
def reveal_export(export_id: str, session: Session = Depends(get_session)):
    e = _export(session, export_id)
    return {"ok": native.reveal_in_file_manager(_export_path(session, e))}


@router.post("/exports/{export_id}/open")
def open_export(export_id: str, session: Session = Depends(get_session)):
    """Abre el archivo con la aplicación predeterminada del sistema (p. ej. QuickTime)."""
    e = _export(session, export_id)
    path = _export_path(session, e)
    cmd = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    try:
        subprocess.run(cmd, check=True, timeout=10)
        return {"ok": True}
    except (OSError, subprocess.SubprocessError):
        return {"ok": False}


@router.delete("/exports/{export_id}", status_code=204)
def delete_export(export_id: str, session: Session = Depends(get_session)):
    e = _export(session, export_id)
    if e.job_id:
        job = session.get(Job, e.job_id)
        if job is not None and job.status in ACTIVE_STATUSES:
            raise StorageError("export_running", "Cancela la exportación antes de borrarla.")
    if e.file_rel:
        project = session.get(Project, e.project_id)
        assert project is not None
        root = storage_manager.require_location(project.storage)
        path = resolve_inside(root, e.file_rel)
        if path.parent.name != "exports":
            raise StorageError("unsafe_delete", "Ruta de exportación inesperada.")
        path.unlink(missing_ok=True)
    session.delete(e)
    session.commit()


# --- modelos y preferencias -------------------------------------------------------


@router.get("/asr/models")
def list_models(session: Session = Depends(get_session)):
    downloading = {
        (j.payload or {}).get("model_id"): project_service.job_out(j)
        for j in session.scalars(
            select(Job).where(Job.kind == "download_model", Job.status.in_(ACTIVE_STATUSES))
        )
    }
    return {
        "supported": asr_models.platform_supported(),
        "models": [
            {**asr_models.describe(mid), "job": downloading.get(mid)} for mid in asr_models.CATALOG
        ],
    }


@router.post("/asr/models/{model_id}/download", status_code=202)
def download_model(model_id: str, session: Session = Depends(get_session)):
    asr_models.get_spec(model_id)
    existing = session.scalar(
        select(Job).where(Job.kind == "download_model", Job.status.in_(ACTIVE_STATUSES))
    )
    if existing is not None and (existing.payload or {}).get("model_id") == model_id:
        return project_service.job_out(existing)
    job = create_job(session, "download_model", payload={"model_id": model_id})
    session.commit()
    runner.wake()
    return project_service.job_out(job)


@router.delete("/asr/models/{model_id}", status_code=204)
def delete_model(model_id: str, session: Session = Depends(get_session)):
    busy = session.scalar(
        select(Job.id).where(
            Job.kind.in_(("transcribe", "align_segments", "download_model")),
            Job.status.in_(ACTIVE_STATUSES),
        )
    )
    if busy is not None:
        raise StorageError(
            "model_in_use", "Hay una transcripción o descarga en curso; espera a que termine."
        )
    asr_models.delete(model_id)


@router.get("/settings/analysis", response_model=AnalysisPreferences)
def get_analysis_settings(session: Session = Depends(get_session)):
    return app_settings.get_analysis(session)


@router.put("/settings/analysis", response_model=AnalysisPreferences)
def put_analysis_settings(body: AnalysisPreferences, session: Session = Depends(get_session)):
    app_settings.save_analysis(session, body)
    session.commit()
    return body
