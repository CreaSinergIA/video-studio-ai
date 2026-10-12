"""Paquete de análisis para la Fase 3 (Claude Opus como director creativo).

Contiene solo datos medidos y estructurados —qué se dice, cuándo se dice y qué se ve en cada
momento— sin ninguna interpretación creativa. Se guarda en ``analysis/bundle.json`` del
proyecto y se sirve por la API. Los fotogramas se referencian por ruta relativa a la raíz del
almacenamiento y por URL de la API, con su tiempo de presentación real.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Analysis, AnalysisFrame, MediaAsset, Project, utcnow
from app.services import transcripts as transcript_service
from app.services.storage import atomic_write_json, resolve_inside

log = logging.getLogger(__name__)

BUNDLE_VERSION = 1


def active_visual(session: Session, asset_id: str) -> Analysis | None:
    return session.scalar(
        select(Analysis)
        .where(Analysis.asset_id == asset_id, Analysis.kind == "visual")
        .where(Analysis.is_active.is_(True))
        .order_by(Analysis.created_at.desc())
    )


def frames_for(session: Session, analysis_id: str | None, asset_id: str) -> list[AnalysisFrame]:
    query = select(AnalysisFrame).where(AnalysisFrame.asset_id == asset_id)
    if analysis_id:
        query = query.where(
            (AnalysisFrame.analysis_id == analysis_id) | (AnalysisFrame.reason == "on_demand")
        )
    return list(session.scalars(query.order_by(AnalysisFrame.t)))


def frame_ref(f: AnalysisFrame) -> dict[str, Any]:
    return {
        "id": f.id,
        "t": f.t,
        "reason": f.reason,
        "scene_index": f.scene_index,
        "file": f.file_rel,
        "url": f"/api/frames/{f.id}/image",
        "width": f.width,
        "height": f.height,
        "faces": f.faces,
        "metrics": f.metrics,
    }


def build_bundle(session: Session, asset: MediaAsset) -> dict[str, Any]:
    transcript = transcript_service.active_for_asset(session, asset.id)
    analysis = active_visual(session, asset.id)
    frames = frames_for(session, analysis.id if analysis else None, asset.id)
    scenes = (analysis.result.get("scenes") if analysis else None) or []
    by_scene: dict[int, list[str]] = {}
    for f in frames:
        if f.scene_index is not None:
            by_scene.setdefault(f.scene_index, []).append(f.id)
    segments_out = []
    for seg in transcript.segments if transcript else []:
        overlapping = [
            sc["index"] for sc in scenes if sc["start"] < seg["end"] and sc["end"] > seg["start"]
        ]
        segments_out.append(
            {
                "id": seg["id"],
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
                "language": seg.get("language"),
                "scene_indices": overlapping,
                "frame_ids": [fid for i in overlapping for fid in by_scene.get(i, [])],
                "needs_timing_review": seg.get("needs_timing_review", False),
                "words": [
                    {
                        "text": w["text"],
                        "start": w["start"],
                        "end": w["end"],
                        "timing": w.get("timing"),
                        "probability": w.get("probability"),
                    }
                    for w in seg["words"]
                ],
            }
        )
    voice = (transcript.stats or {}).get("voice") if transcript else None
    return {
        "bundle_version": BUNDLE_VERSION,
        "generated_at": utcnow().isoformat(),
        "video": {
            "asset_id": asset.id,
            "file": asset.file_rel,
            "duration": asset.duration,
            "width": asset.display_width,
            "height": asset.display_height,
            "orientation": asset.orientation,
            "fps": asset.fps,
            "has_audio": asset.has_audio,
            "video_codec": asset.video_codec,
            "is_hdr": asset.color_transfer in ("arib-std-b67", "smpte2084"),
        },
        "transcript": None
        if transcript is None
        else {
            "id": transcript.id,
            "kind": transcript.kind,
            "status": transcript.status,
            "engine": transcript.engine,
            "model": transcript.model,
            "language": transcript.language,
            "timing_sources": transcript_service.TIMING_LABELS,
        },
        "voice_activity": voice,
        "segments": segments_out,
        "scenes": [{**sc, "frame_ids": by_scene.get(sc["index"], [])} for sc in scenes],
        "transitions": (analysis.result.get("transitions") if analysis else None) or [],
        "static_intervals": (analysis.result.get("static_intervals") if analysis else None) or [],
        "frames": [frame_ref(f) for f in frames],
        "notes": [
            "Rostros: detección (YuNet), no identifica quién habla.",
            "Las palabras con timing «estimated» no están medidas; revisar antes de usarlas.",
        ],
    }


def write_bundle(session: Session, asset: MediaAsset, root: Path) -> None:
    try:
        project = session.get(Project, asset.project_id)
        if project is None:
            return
        target = resolve_inside(root, project.dir_rel) / "analysis" / "bundle.json"
        atomic_write_json(target, build_bundle(session, asset))
    except OSError as exc:
        log.warning("No se pudo escribir el paquete de análisis: %s", exc)
