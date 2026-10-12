"""Contexto audiovisual para Claude (Fase 3).

Reúne lo que ya midió la Fase 2 (transcripción activa con tiempos por palabra, escenas,
transiciones, silencios, rostros, fotogramas reales) sin reanalizar nada, y lo convierte en
bloques compactos de texto e imagen:

- **Contexto global**: datos del video, escenas, pausas, preferencias y estilo.
- **Contexto local**: la transcripción con ids de palabra y fotogramas de la ventana tratada.
- **Selección de fotogramas** con presupuesto fijo (al menos uno por escena si caben, el resto
  repartido en el tiempo), reducidos a ≤ 768 px.
- **Control de tamaño**: estimación de tokens; los videos largos se dividen en tramos
  (estrategia jerárquica: comprensión global → tramos → consolidación).

Todo el contenido procedente del video (palabras dichas, textos) se marca como **datos no
confiables**; nunca se mezcla con las instrucciones.
"""

from __future__ import annotations

import hashlib
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image
from sqlalchemy.orm import Session

from app.domain.edit_config import EditConfig, StyleId
from app.models import AnalysisFrame, MediaAsset, Project, Transcript
from app.services import analysis_bundle, subtitles
from app.services import transcripts as transcript_service
from app.services.storage import resolve_inside

# Videos más largos que esto (o con más palabras) se planifican por tramos.
HIERARCHICAL_SECONDS = 360.0
HIERARCHICAL_WORDS = 1500
CHUNK_TARGET_SECONDS = 210.0
MAX_IMAGE_SIDE = 768


class PlanInputError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class PlanInputs:
    project: Project
    asset: MediaAsset
    root: Path
    config: EditConfig
    style: StyleId
    transcript: Transcript | None
    analysis_id: str | None
    bundle: dict[str, Any]
    frames: list[AnalysisFrame]
    words: list[dict[str, Any]]  # todas las palabras, ordenadas, con su segmento
    subtitle_zones: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return float(self.asset.duration or 0)

    @property
    def scenes(self) -> list[dict[str, Any]]:
        return list(self.bundle.get("scenes") or [])


# ---------------------------------------------------------------------------
# Huellas (para detectar cambios posteriores sin destruir versiones)
# ---------------------------------------------------------------------------


def transcript_fingerprint(transcript: Transcript | None) -> dict[str, Any]:
    if transcript is None:
        return {"id": None, "segments": {}}
    segs = {}
    for seg in transcript.segments:
        raw = json.dumps(
            [
                seg["text"],
                [(w["id"], round(w["start"], 2), round(w["end"], 2)) for w in seg["words"]],
            ],
            ensure_ascii=False,
        )
        segs[seg["id"]] = hashlib.sha1(raw.encode()).hexdigest()[:16]
    return {"id": transcript.id, "segments": segs}


def asset_fingerprint(asset: MediaAsset) -> str:
    raw = f"{asset.id}|{asset.file_rel}|{asset.size_bytes}|{asset.duration}"
    return hashlib.sha1(raw.encode()).hexdigest()


def config_hash(config: EditConfig, style: str) -> str:
    raw = json.dumps({"style": style, "config": config.model_dump(mode="json")}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Reunir datos
# ---------------------------------------------------------------------------


def gather(session: Session, project: Project, root: Path, style: StyleId | None) -> PlanInputs:
    from app.services.projects import _source  # evita import circular

    asset = _source(project)
    if asset is None:
        raise PlanInputError("no_source", "El proyecto no tiene video.")
    transcript = transcript_service.active_for_asset(session, asset.id)
    visual = analysis_bundle.active_visual(session, asset.id)
    if visual is None:
        raise PlanInputError(
            "not_analyzed",
            "Primero analiza el video (transcripción, escenas y fotogramas): la planificación "
            "usa esos resultados.",
        )
    if transcript is None and asset.has_audio:
        raise PlanInputError(
            "no_transcript",
            "Falta la transcripción del video. Pulsa «Analizar video» para generarla.",
        )
    config = EditConfig.model_validate(project.config)
    bundle = analysis_bundle.build_bundle(session, asset)
    frames = analysis_bundle.frames_for(session, visual.id, asset.id)
    words: list[dict[str, Any]] = []
    for seg in transcript.segments if transcript else []:
        for w in seg["words"]:
            words.append({**w, "segment_id": seg["id"]})
    words.sort(key=lambda w: w["start"])
    inputs = PlanInputs(
        project=project,
        asset=asset,
        root=root,
        config=config,
        style=style or config.style.id,
        transcript=transcript,
        analysis_id=visual.id,
        bundle=bundle,
        frames=frames,
        words=words,
    )
    inputs.subtitle_zones = _subtitle_zones(inputs)
    return inputs


def _subtitle_zones(inputs: PlanInputs) -> list[dict[str, Any]]:
    """Franjas que ocuparán los subtítulos (medidas con el motor real de la Fase 2)."""
    if inputs.transcript is None or not inputs.config.subtitles.enabled:
        return []
    try:
        track = subtitles.build_track(
            inputs.transcript.segments,
            inputs.config.subtitles,
            inputs.asset.display_width,
            inputs.asset.display_height,
            inputs.scenes,
            inputs.config.delivery.platform,
        )
    except Exception:  # los subtítulos nunca deben impedir planificar
        return []
    h = float(track["height"]) or 1.0
    return [
        {
            "start": b["start"],
            "end": b["end"],
            "y": round(b["top"] / h, 4),
            "h": round(b["height"] / h, 4),
        }
        for b in track["blocks"]
    ]


# ---------------------------------------------------------------------------
# Selección de fotogramas
# ---------------------------------------------------------------------------


def select_frames(
    frames: list[AnalysisFrame],
    scenes: list[dict[str, Any]],
    budget: int,
    window: tuple[float, float] | None = None,
) -> list[AnalysisFrame]:
    lo, hi = window or (float("-inf"), float("inf"))
    pool = [f for f in frames if lo <= f.t <= hi]
    if len(pool) <= budget:
        return pool
    chosen: dict[str, AnalysisFrame] = {}
    in_window = [s for s in scenes if s["end"] > lo and s["start"] < hi]
    # 1) Un fotograma por escena (el más centrado), priorizando las escenas más largas.
    for sc in sorted(in_window, key=lambda s: -(s["end"] - s["start"])):
        if len(chosen) >= budget:
            break
        mid = (max(sc["start"], lo) + min(sc["end"], hi)) / 2
        cands = [f for f in pool if f.scene_index == sc["index"]]
        if cands:
            best = min(cands, key=lambda f: abs(f.t - mid))
            chosen[best.id] = best
    # 2) Resto: el más alejado (en el tiempo) de los ya elegidos, para cubrir todo el tramo.
    while len(chosen) < budget:
        remaining = [f for f in pool if f.id not in chosen]
        if not remaining:
            break
        times = [c.t for c in chosen.values()]
        best = max(remaining, key=lambda f: min((abs(f.t - t) for t in times), default=1e9))
        chosen[best.id] = best
    return sorted(chosen.values(), key=lambda f: f.t)


def frame_jpeg(inputs: PlanInputs, frame: AnalysisFrame) -> bytes:
    path = resolve_inside(inputs.root, frame.file_rel)
    with Image.open(path) as src:
        im = src.convert("RGB")
    if max(im.size) > MAX_IMAGE_SIDE:
        im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Texto
# ---------------------------------------------------------------------------


def untrusted(text: str) -> str:
    """Neutraliza delimitadores para que el contenido no pueda cerrar las etiquetas de datos."""
    return text.replace("<", "‹").replace(">", "›")


def _r(x: float) -> str:
    return f"{x:.2f}"


def video_facts(inputs: PlanInputs) -> str:
    a = inputs.asset
    t = inputs.transcript
    lines = [
        f"duración: {_r(inputs.duration)} s",
        f"resolución: {a.display_width}x{a.display_height} ({a.orientation})",
        f"fps: {a.fps}",
        f"audio: {'sí' if a.has_audio else 'no'}",
        f"idioma: {t.language if t else 'sin transcripción'}",
        "transcripción: "
        + (
            "no disponible"
            if t is None
            else "corregida por el usuario"
            if t.kind == "edited"
            else "automática"
        ),
    ]
    zones = inputs.subtitle_zones
    if zones:
        top = min(z["y"] for z in zones)
        bottom = max(z["y"] + z["h"] for z in zones)
        lines.append(
            f"subtítulos: ocupan la franja horizontal y={top:.2f}–{bottom:.2f} (normalizado) "
            "cuando hay voz"
        )
    return "\n".join(lines)


def scenes_text(inputs: PlanInputs, window: tuple[float, float] | None = None) -> str:
    lo, hi = window or (0.0, inputs.duration)
    out = []
    for sc in inputs.scenes:
        if sc["end"] <= lo or sc["start"] >= hi:
            continue
        faces = sc.get("faces") or {}
        face_txt = faces.get("status", "unknown")
        if faces.get("union_box"):
            x, y, w, h = faces["union_box"]
            face_txt += f" caja_rostros=[x={x:.2f},y={y:.2f},w={w:.2f},h={h:.2f}]"
        labels = sc.get("labels") or {}
        m = sc.get("metrics") or {}
        out.append(
            f"escena {sc['index']}: {_r(sc['start'])}–{_r(sc['end'])} s"
            f" · entrada={sc.get('transition_in')} · brillo={labels.get('brightness')}"
            f" · movimiento={labels.get('motion')}"
            f" (estático {m.get('static_ratio', 0):.0%}) · rostros={face_txt}"
        )
    trans = [
        f"{t['kind']} {_r(t['start'])}–{_r(t['end'])} s"
        for t in inputs.bundle.get("transitions") or []
        if lo <= t["start"] <= hi
    ]
    if trans:
        out.append("transiciones detectadas: " + "; ".join(trans))
    static = [
        f"{_r(s[0])}–{_r(s[1])}"
        for s in inputs.bundle.get("static_intervals") or []
        if s[1] > lo and s[0] < hi
    ]
    if static:
        out.append("intervalos estáticos (s): " + ", ".join(static[:40]))
    voice = inputs.bundle.get("voice_activity") or {}
    pauses = [
        f"{_r(a)}–{_r(b)}" for a, b in voice.get("silences") or [] if b - a >= 0.3 and lo <= a <= hi
    ]
    if pauses:
        out.append("pausas de voz ≥0,3 s: " + ", ".join(pauses[:60]))
    return "\n".join(out)


def transcript_text(
    inputs: PlanInputs, window: tuple[float, float] | None = None, words: bool = True
) -> str:
    if inputs.transcript is None:
        return "(sin voz)"
    lo, hi = window or (0.0, inputs.duration)
    out = []
    for seg in inputs.transcript.segments:
        if seg["end"] <= lo or seg["start"] >= hi:
            continue
        head = f"[{seg['id']} {_r(seg['start'])}–{_r(seg['end'])}]"
        if words:
            body = " ".join(
                f"{w['id']}@{_r(w['start'])} {untrusted(w['text'])}" for w in seg["words"]
            )
        else:
            body = untrusted(seg["text"])
        out.append(f"{head} {body}")
    return "\n".join(out)


def frames_intro(frames: list[AnalysisFrame]) -> str:
    out = []
    for f in frames:
        faces = ""
        if f.faces:
            boxes = [
                f"[x={b['box'][0]:.2f},y={b['box'][1]:.2f},w={b['box'][2]:.2f},h={b['box'][3]:.2f}]"
                for b in f.faces
            ]
            faces = " rostros=" + ",".join(boxes)
        elif f.faces is not None:
            faces = " rostros=ninguno"
        out.append(f"{f.id}: t={_r(f.t)} s, escena {f.scene_index}{faces}")
    return "\n".join(out)


def estimate_tokens(text: str, frames: list[AnalysisFrame]) -> int:
    images = sum(
        min(1600, int(min(f.width, MAX_IMAGE_SIDE) * min(f.height, MAX_IMAGE_SIDE) / 750))
        for f in frames
    )
    return int(len(text) / 3.2) + images


def needs_hierarchy(inputs: PlanInputs) -> bool:
    return inputs.duration > HIERARCHICAL_SECONDS or len(inputs.words) > HIERARCHICAL_WORDS


def chunk_windows(inputs: PlanInputs) -> list[tuple[float, float]]:
    """Tramos de ~3,5 min que terminan en un corte de escena o una pausa de voz."""
    d = inputs.duration
    if d <= CHUNK_TARGET_SECONDS * 1.4:
        return [(0.0, d)]
    voice = inputs.bundle.get("voice_activity") or {}
    boundaries = sorted(
        {round(sc["start"], 3) for sc in inputs.scenes if sc["start"] > 0}
        | {round((a + b) / 2, 3) for a, b in voice.get("silences") or []}
        | (
            {round(seg["end"], 3) for seg in inputs.transcript.segments}
            if inputs.transcript
            else set()
        )
    )
    windows = []
    start = 0.0
    while d - start > CHUNK_TARGET_SECONDS * 1.4:
        target = start + CHUNK_TARGET_SECONDS
        cands = [
            b
            for b in boundaries
            if start + CHUNK_TARGET_SECONDS * 0.6 <= b <= start + CHUNK_TARGET_SECONDS * 1.4
        ]
        cut = min(cands, key=lambda b: abs(b - target)) if cands else target
        windows.append((start, cut))
        start = cut
    windows.append((start, d))
    return windows
