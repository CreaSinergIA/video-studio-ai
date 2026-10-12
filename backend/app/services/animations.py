"""Animaciones del plan aprobado (Fase 4): contexto, especificaciones, caché y composición.

Solo se animan intervenciones ACEPTADAS de la versión APROBADA del plan; las de «conservar
original» o «sin intervención» se respetan sin generar nada. Los tiempos vienen del contrato y
de la transcripción con la que se aprobó (no de la transcripción actual), para que cambios
posteriores no alteren en silencio lo aprobado.
"""

from __future__ import annotations

import functools
import hashlib
import itertools
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import styles
from app.config import get_settings
from app.domain.edit_config import EditConfig
from app.models import AnimationDirection, MediaAsset, Project, Transcript, new_id
from app.services import (
    animation_spec,
    compositor,
    exporter,
    layout_engine,
    planning,
    render_engine,
    subtitles,
)
from app.services import sfx as sfx_lib
from app.services.layout_engine import Zone
from app.services.planning import PlanError
from app.services.storage import resolve_inside
from app.services.storage_manager import storage_manager

PASSIVE = {"keep_original", "no_intervention"}


@dataclass
class Approved:
    project: Project
    asset: MediaAsset
    root: Path
    project_dir: Path
    plan_id: str
    version: int
    contract: dict[str, Any]
    config: EditConfig
    style: str
    segments: list[dict[str, Any]]
    clock: animation_spec.WordClock
    scenes: list[dict[str, Any]]

    @property
    def interventions(self) -> list[dict[str, Any]]:
        return list(self.contract.get("interventions") or [])

    def animated(self) -> list[dict[str, Any]]:
        return [i for i in self.interventions if i["type"] not in PASSIVE]


def load_approved(session: Session, project_id: str, version: int | None = None) -> Approved:
    from app.services import analysis_bundle
    from app.services.projects import _source

    plan = planning.get_plan(session, project_id)
    if plan is None or plan.approved_version is None:
        raise PlanError(
            "not_approved", "Primero aprueba el plan de edición (pestaña Plan IA).", 409
        )
    number = version or plan.approved_version
    v = planning.get_version(session, plan, number)
    if not v.immutable:
        raise PlanError("not_approved", f"La versión {number} del plan no está aprobada.", 409)
    project = session.get(Project, project_id)
    assert project is not None
    asset = _source(project)
    if asset is None:
        raise PlanError("no_source", "El proyecto no tiene video.", 409)
    root = storage_manager.require_location(project.storage)
    contract = planning.build_contract(project, asset, plan, v, planning.doc_of(v))
    # Configuración vigente al aprobar (estilo, preset, subtítulos, efectos).
    config = EditConfig.model_validate(contract["config"])
    t = session.get(Transcript, v.transcript_id) if v.transcript_id else None
    segments = list(t.segments) if t else []
    visual = analysis_bundle.active_visual(session, asset.id)
    scenes = list(visual.result.get("scenes", [])) if visual else []
    return Approved(
        project=project,
        asset=asset,
        root=root,
        project_dir=resolve_inside(root, project.dir_rel),
        plan_id=plan.id,
        version=number,
        contract=contract,
        config=config,
        style=contract["style"],
        segments=segments,
        clock=animation_spec.WordClock(segments),
        scenes=scenes,
    )


def subtitle_settings(ap: Approved) -> Any:
    """Subtítulos aprobados con la preferencia de entrega ACTUAL de zona segura (como la
    plataforma de destino): así la vista previa del panel y la exportación coinciden."""
    return ap.config.subtitles.model_copy(
        update={"safe_area": current_config(ap).subtitles.safe_area}
    )


def subtitle_band(ap: Approved) -> tuple[float, float] | None:
    if not ap.config.subtitles.enabled or not ap.segments:
        return None
    try:
        track = subtitles.build_track(
            ap.segments,
            subtitle_settings(ap),
            ap.asset.display_width,
            ap.asset.display_height,
            ap.scenes,
            current_config(ap).delivery.platform,
        )
    except Exception:
        return None
    h = float(track["height"]) or 1.0
    blocks = track["blocks"]
    if not blocks:
        return None
    return (min(b["top"] for b in blocks) / h, max(b["top"] + b["height"] for b in blocks) / h)


def current_config(ap: Approved) -> EditConfig:
    """Configuración ACTUAL del proyecto (exportación, audio y plataforma de destino): son
    preferencias de entrega, no decisiones creativas del plan aprobado."""
    try:
        return EditConfig.model_validate(ap.project.config or {})
    except ValueError:
        return ap.config


def render_size(ap: Approved, purpose: str) -> tuple[int, int, float]:
    asset = ap.asset
    if purpose == "preview":
        pp = compositor.preview_plan(asset.display_width, asset.display_height)
        return pp.width, pp.height, 30.0
    # Ajustes de exportación ACTUALES del proyecto (los mismos que propone el diálogo de
    # exportación), para que los clips generados antes se reutilicen al exportar.
    export = current_config(ap).export
    try:
        w, h = exporter.target_size(asset, export.resolution)
    except exporter.ExportError:
        w, h = exporter.target_size(asset, "original")
    fps = float(export.fps) if export.fps != "original" else float(asset.fps or 30.0)
    return w, h, min(60.0, fps)


def directions(session: Session, ap: Approved) -> dict[str, dict[str, Any]]:
    """Dirección de cada animación de la versión aprobada. Si falta alguna que ya existía para
    la misma intervención sin cambios en otra versión, se reutiliza antes (sin solicitudes):
    así la vista previa, las escenas y la exportación usan la misma dirección que «Generar»."""
    have = _stored_directions(session, ap)
    if any(iv["id"] not in have for iv in ap.animated()):
        # En un punto de guardado: si otra petición insertó lo mismo a la vez (restricción
        # única), se descarta solo este intento y se leen las filas ya guardadas.
        try:
            with session.begin_nested():
                reuse_directions(session, ap)
        except IntegrityError:
            pass
        have = _stored_directions(session, ap)
    return have


def _stored_directions(session: Session, ap: Approved) -> dict[str, dict[str, Any]]:
    rows = session.scalars(
        select(AnimationDirection).where(
            AnimationDirection.plan_id == ap.plan_id, AnimationDirection.plan_version == ap.version
        )
    )
    return {r.intervention_id: r.direction for r in rows}


_FINGERPRINT_KEYS = (
    "type", "start", "end", "goal", "visual_description", "composition", "elements", "motion",
    "transitions", "sfx", "intensity", "subtitles", "avoid_face",
)  # fmt: skip


def _fingerprint(iv: dict[str, Any]) -> str:
    return json.dumps({k: iv.get(k) for k in _FINGERPRINT_KEYS}, sort_keys=True, ensure_ascii=False)


def reuse_directions(session: Session, ap: Approved) -> int:
    """Reutiliza la dirección de Claude de otra versión del plan para las intervenciones que
    no han cambiado (mismo id, mismo contenido y misma transcripción). Evita solicitudes
    repetidas al reaprobar o restaurar una versión. Devuelve cuántas se reutilizaron."""
    have = _stored_directions(session, ap)
    want = {iv["id"]: _fingerprint(iv) for iv in ap.animated() if iv["id"] not in have}
    if not want:
        return 0
    plan = planning.get_plan(session, ap.project.id)
    if plan is None:
        return 0
    rows = session.scalars(
        select(AnimationDirection)
        .where(
            AnimationDirection.plan_id == ap.plan_id,
            AnimationDirection.plan_version != ap.version,
            AnimationDirection.intervention_id.in_(list(want)),
        )
        .order_by(AnimationDirection.plan_version.desc())
    )
    transcript = planning.get_version(session, plan, ap.version).transcript_id
    docs: dict[int, Any] = {}
    reused = 0
    for row in rows:
        if row.intervention_id not in want:
            continue
        if row.plan_version not in docs:
            version = planning.get_version(session, plan, row.plan_version)
            docs[row.plan_version] = (version, planning.doc_of(version))
        version, doc = docs[row.plan_version]
        if version.transcript_id != transcript:
            continue
        old = next((i for i in doc.interventions if i.id == row.intervention_id), None)
        if old is None or _fingerprint(old.model_dump(mode="json")) != want[row.intervention_id]:
            continue
        session.add(
            AnimationDirection(
                id=new_id("ad"),
                plan_id=ap.plan_id,
                plan_version=ap.version,
                intervention_id=row.intervention_id,
                direction=row.direction,
                source=row.source,
                model=row.model,
            )
        )
        del want[row.intervention_id]
        reused += 1
    return reused


def spec_hash(spec: dict[str, Any]) -> str:
    # `planVersion` es informativo (no cambia ni un píxel): al volver a aprobar un plan idéntico
    # se reutilizan los clips ya renderizados.
    visual = {k: v for k, v in spec.items() if k != "planVersion"}
    raw = json.dumps(visual, sort_keys=True, ensure_ascii=False) + render_engine.source_hash()
    return hashlib.sha256(raw.encode()).hexdigest()


def activity_map(ap: Approved, t: float) -> np.ndarray | None:
    """Actividad visual (bordes) del fotograma en `t`, en una rejilla de 96×54 (0–1)."""
    src = resolve_inside(ap.root, ap.asset.file_rel)
    try:
        stamp = src.stat().st_mtime_ns
    except OSError:
        return None
    return _activity(str(src), stamp, round(max(0.0, t), 3))


@functools.lru_cache(maxsize=512)
def _activity(path: str, stamp: int, t: float) -> np.ndarray | None:
    # En caché por (archivo, instante): compilar el plan completo varias veces (vista previa,
    # candidatas, exportación) no vuelve a extraer los mismos fotogramas.
    src = Path(path)
    try:
        raw = subprocess.run(
            [get_settings().ffmpeg, "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(src),
             "-frames:v", "1", "-vf", "scale=96:54:flags=area,format=gray", "-f", "rawvideo", "-"],
            check=True, capture_output=True, timeout=30,
        ).stdout  # fmt: skip
    except (subprocess.SubprocessError, OSError):
        return None
    if len(raw) != 96 * 54:
        return None
    g = np.frombuffer(raw, dtype=np.uint8).reshape(54, 96).astype(np.float32) / 255.0
    edges = np.zeros_like(g)
    edges[:, 1:] += np.abs(np.diff(g, axis=1))
    edges[1:, :] += np.abs(np.diff(g, axis=0))
    out = np.asarray(np.clip(edges * 4.0, 0.0, 1.0))
    out.setflags(write=False)  # compartido por la caché: solo lectura
    return out


def declutter(
    spec: dict[str, Any],
    iv: dict[str, Any],
    band: tuple[float, float] | None,
    amap: np.ndarray,
    zones: list[Zone] | None = None,
) -> str | None:
    """Sin rostro que proteger (p. ej. grabación de pantalla): si la región de la animación
    tapa contenido real del fotograma, la mueve a la zona más vacía del mismo tamaño que no
    pise los subtítulos. Devuelve la nota del cambio o None."""
    r = spec["region"]
    rows, cols = amap.shape

    def score(x: float, y: float) -> float:
        x0, x1 = int(x * cols), max(int(x * cols) + 1, int((x + r["w"]) * cols))
        y0, y1 = int(y * rows), max(int(y * rows) + 1, int((y + r["h"]) * rows))
        return float(amap[y0:y1, x0:x1].mean())

    here = score(r["x"], r["y"])
    if here < 0.04:
        return None
    best = (here, r["x"], r["y"])
    steps = [i / 50 for i in range(1, 50)]
    for y in steps:
        if y + r["h"] > 0.98 or (band and y < band[1] and y + r["h"] > band[0]):
            continue
        for x in steps:
            if x + r["w"] > 0.98:
                continue
            if zones and layout_engine.overlaps({**r, "x": x, "y": y}, zones):
                continue  # nunca bajo la interfaz social ni sobre otra animación
            sc = score(x, y)
            if sc < best[0] - 1e-6:
                best = (sc, x, y)
    if best[0] > here * 0.6:
        return None
    spec["region"] = {**r, "x": round(best[1], 4), "y": round(best[2], 4)}
    return (
        f"Desplazada a una zona sin contenido de la pantalla (ocupación {here:.0%} → "
        f"{best[0]:.0%}) para no tapar elementos reales."
    )


CHAIN_STYLES = tuple(sid for sid, st in styles.REGISTRY.items() if st.chain_overlays)
CHAIN_GAP = 0.6  # s


def link_sequences(compiled: list[dict[str, Any]], fps: float) -> None:
    """Continuidad (Fase 4.1): dos superposiciones consecutivas del mismo estilo, separadas por
    ≤ 0,6 s, forman una secuencia. El contenedor de la primera no sale y el de la segunda se
    transforma desde la región anterior. Si queda un hueco, la primera se prolonga hasta el
    inicio de la segunda (solo el render; el plan aprobado no cambia). Creative Explainer
    conserva sus transiciones propias (las mejor valoradas)."""
    seq = sorted(compiled, key=lambda c: float(c["iv"]["start"]))
    for a, b in itertools.pairwise(seq):
        sa, sb = a["spec"], b["spec"]
        if sa["style"] not in CHAIN_STYLES or sa["style"] != sb["style"]:
            continue
        if sa["mode"] != "overlay" or sb["mode"] != "overlay":
            continue
        if sa["template"].endswith((".highlight", ".transition")) or sb["template"].endswith(
            (".highlight", ".transition")
        ):
            continue
        gap = float(b["iv"]["start"]) - float(a["iv"]["end"])
        if gap < -0.05 or gap > CHAIN_GAP:
            continue
        if gap > 0.01:
            a["iv"] = {**a["iv"], "end": float(b["iv"]["start"])}
            sa["durationInFrames"] = max(
                sa["durationInFrames"],
                round((float(b["iv"]["start"]) - float(a["iv"]["start"])) * fps),
            )
            a["notes"].append(
                f"Se prolonga {gap:.2f} s para enlazar con la animación siguiente (continuidad)."
            )
        sa["chainOut"] = True
        sb["chainIn"] = dict(sa["region"])
        b["notes"].append("Continúa el contenedor de la animación anterior (transición enlazada).")


VIEWPORT_MARGIN = 0.06  # margen alrededor de la región (fracción del lado menor)


def viewport(spec: dict[str, Any]) -> dict[str, int] | None:
    """Zona del encuadre que de verdad se dibuja (Fase 5, rendimiento). Una superposición ocupa
    una franja; renderizar solo esa zona (con margen para sombras, brillos y la transformación
    desde la animación anterior) evita capturar millones de píxeles transparentes por
    fotograma. Las coordenadas internas no cambian: el clip se recorta, no se reescala, y el
    compositor lo coloca en su posición exacta. Pantalla completa, transiciones, resaltados y
    primitivas libres (que pueden ocupar cualquier punto) se renderizan completos."""
    if (
        os.environ.get("VSA_RENDER_VIEWPORT", "1") == "0"  # diagnóstico: encuadre completo
        or spec["mode"] != "overlay"
        or spec["template"].endswith((".highlight", ".transition"))
        or spec.get("custom")
        or spec.get("pip")
        # Un fondo atenuado o desenfocado ocupa todo el encuadre: recortarlo dejaría una caja.
        or spec.get("background", "none") != "none"
    ):
        return None
    W, H = int(spec["width"]), int(spec["height"])
    rects = [spec["region"], *([spec["chainIn"]] if spec.get("chainIn") else [])]
    m = VIEWPORT_MARGIN * min(W, H)
    x0 = max(0, int((min(r["x"] for r in rects) * W - m) // 2 * 2))
    y0 = max(0, int((min(r["y"] for r in rects) * H - m) // 2 * 2))
    x1 = min(W, int(-(-(max(r["x"] + r["w"] for r in rects) * W + m) // 2) * 2))
    y1 = min(H, int(-(-(max(r["y"] + r["h"] for r in rects) * H + m) // 2) * 2))
    if (x1 - x0) * (y1 - y0) > 0.7 * W * H:
        return None
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def compile_all(
    ap: Approved,
    purpose: str,
    dirs: dict[str, dict[str, Any]],
    only: set[str] | None = None,
    size: tuple[int, int, float] | None = None,
    overrides: dict[str, tuple[dict[str, Any], dict[str, Any] | None]] | None = None,
) -> list[dict[str, Any]]:
    """Especificaciones de las intervenciones animadas (con notas, efectos y cámara).

    Siempre se compila el plan completo y después se filtra con ``only``: la colocación de una
    animación depende de las simultáneas y de las enlazadas, así que compilarla aislada daría
    otra huella que la exportación no reutilizaría. ``overrides`` sustituye la intervención y
    la dirección de algunas escenas (versiones candidatas) sin tocar el plan aprobado."""
    w, h, fps = size or render_size(ap, purpose)
    if overrides:
        dirs = dict(dirs)
        for iid, (_, d) in overrides.items():
            if d is not None:
                dirs[iid] = d
            else:
                dirs.pop(iid, None)
    band = subtitle_band(ap)
    out = []
    platform = current_config(ap).delivery.platform
    ui = layout_engine.ui_zones(platform, w, h)
    placed: list[tuple[float, float, dict[str, float]]] = []  # (inicio, fin, región) ya colocadas
    pool = [
        overrides[i["id"]][0] if overrides and i["id"] in overrides else i for i in ap.animated()
    ]
    seq = sorted(pool, key=lambda i: float(i["start"]))
    for k, iv in enumerate(seq):
        notes_pre: list[str] = []
        nxt = seq[k + 1] if k + 1 < len(seq) else None
        if nxt is not None and float(iv["start"]) + 1.0 <= float(nxt["start"]) < float(iv["end"]):
            # Dos intervenciones aprobadas se solapan: esta completa su salida justo antes de
            # que entre la siguiente (no se tocan los tiempos del plan, solo el render).
            notes_pre.append(
                f"Termina {float(iv['end']) - float(nxt['start']):.2f} s antes para no "
                "solaparse con la animación siguiente."
            )
            iv = {**iv, "end": float(nxt["start"])}
        compiled, notes = animation_spec.compile_intervention(
            iv,
            plan_version=ap.version,
            style=ap.style,
            config=ap.config,
            clock=ap.clock,
            width=w,
            height=h,
            fps=fps,
            subtitle_band=band,
            direction=dirs.get(iv["id"]),
            ui_zones=ui,
            occupied=[
                Zone(
                    "occ",
                    "Otra animación visible a la vez",
                    r["x"],
                    r["y"],
                    r["w"],
                    r["h"],
                    kind="occupied",
                )
                for a0, b0, r in placed
                if a0 < float(iv["end"]) and b0 > float(iv["start"])
            ],
        )
        spec = compiled["spec"]
        if (
            spec["mode"] == "overlay"
            and not iv.get("protected_regions")
            and not spec["template"].endswith((".highlight", ".transition"))
        ):
            a, b = float(iv["start"]), float(iv["end"])
            # Lo que haya en pantalla en cualquier momento del tramo (inicio, mitad y final).
            maps = [
                m for t in (a + 0.3, (a + b) / 2, b - 0.3) if (m := activity_map(ap, t)) is not None
            ]
            amap = np.maximum.reduce(maps) if maps else None
            others = [
                Zone("occ", "Otra animación", q["x"], q["y"], q["w"], q["h"], kind="occupied")
                for a0, b0, q in placed
                if a0 < float(iv["end"]) and b0 > float(iv["start"])
            ]
            keep_out = ui + layout_engine.subtitle_zone(band) + others
            moved = declutter(spec, iv, band, amap, keep_out) if amap is not None else None
            if moved:
                notes.append(moved)
        if spec["mode"] == "overlay":
            placed.append((float(iv["start"]), float(iv["end"]), dict(spec["region"])))
        spec["chainIn"], spec["chainOut"] = None, False
        out.append(
            {
                "iv": iv,
                "spec": spec,
                "hash": "",
                "notes": notes_pre + notes,
                "pip_src": compiled["pip_src"],
                "warnings": compiled.get("warnings", []),
                "direction": "claude" if dirs.get(iv["id"]) else "compilador",
            }
        )
    link_sequences(out, fps)
    for c in out:
        c["spec"]["viewport"] = viewport(c["spec"])
        c["hash"] = spec_hash(c["spec"])
    if only:
        out = [c for c in out if c["iv"]["id"] in only]
    return out


def clip_path(ap: Approved, h: str) -> Path:
    d = ap.project_dir / "animations" / "clips"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h[:32]}.mov"


def cached_clip(ap: Approved, h: str, spec: dict[str, Any] | None = None) -> Path | None:
    """Clip ya renderizado para este hash (los archivos se nombran por contenido y se escriben
    con renombrado atómico). Con ``spec`` se comprueba además que el archivo no esté dañado
    (tamaño y número de fotogramas); si lo está, se elimina para volver a generarlo."""
    path = clip_path(ap, h)
    if not path.is_file() or path.stat().st_size == 0:
        return None
    if spec is not None and not valid_clip(path, spec):
        path.unlink(missing_ok=True)
        return None
    return path


_CLIP_OK: dict[tuple[str, int, int], bool] = {}


def valid_clip(path: Path, spec: dict[str, Any]) -> bool:
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _CLIP_OK:
        vp = spec.get("viewport")
        want = (int(vp["w"]), int(vp["h"])) if vp else (int(spec["width"]), int(spec["height"]))
        try:
            out = subprocess.run(
                [get_settings().ffprobe, "-v", "error", "-select_streams", "v:0", "-count_packets",
                 "-show_entries", "stream=width,height,nb_read_packets", "-of", "json", str(path)],
                capture_output=True, text=True, timeout=60,
            ).stdout  # fmt: skip
            s0 = (json.loads(out or "{}").get("streams") or [{}])[0]
            frames = int(s0.get("nb_read_packets") or 0)
            ok = (int(s0.get("width") or 0), int(s0.get("height") or 0)) == want and (
                abs(frames - int(spec["durationInFrames"])) <= 1
            )
        except (subprocess.SubprocessError, OSError, ValueError):
            # Si la comprobación misma falla (p. ej. carga del sistema), no se da por dañado
            # ni se recuerda el resultado: solo una discrepancia medida invalida el clip.
            return True
        _CLIP_OK[key] = ok
    return _CLIP_OK[key]


# ---------------------------------------------------------------------------
# Composición
# ---------------------------------------------------------------------------


def treated_track(ap: Approved, width: int, height: int) -> dict[str, Any] | None:
    """Pista de subtítulos con el tratamiento aprobado por tramo (sin tocar los ajustes)."""
    if not ap.config.subtitles.enabled or not ap.segments:
        return None
    track = subtitles.scale_track(
        subtitles.build_track(
            ap.segments,
            subtitle_settings(ap),
            ap.asset.display_width,
            ap.asset.display_height,
            ap.scenes,
            current_config(ap).delivery.platform,
        ),
        width,
        height,
    )
    rules = [
        (i["start"], i["end"], i.get("subtitles", "keep"))
        for i in ap.animated()
        if i.get("subtitles", "keep") != "keep"
    ]
    if not rules:
        return track
    margin = height * 0.06
    blocks = []
    for b in track["blocks"]:
        rule = next(
            (
                r
                for a, e, r in rules
                if min(e, b["end"]) - max(a, b["start"]) > 0.5 * (b["end"] - b["start"])
            ),
            None,
        )
        if rule in ("hide", "integrate"):
            continue
        if rule == "move_top":
            dy = margin - b["top"]
            b = {
                **b,
                "top": margin,
                "lines": [{**ln, "baseline": ln["baseline"] + dy} for ln in b["lines"]],
            }
        elif rule == "move_bottom":
            ny = height - margin - b["height"]
            dy = ny - b["top"]
            b = {
                **b,
                "top": ny,
                "lines": [{**ln, "baseline": ln["baseline"] + dy} for ln in b["lines"]],
            }
        blocks.append(b)
    return {**track, "blocks": blocks}


_SAFE_LAYOUT = re.compile(r"[a-z0-9.]{1,24}")


def composition(
    ap: Approved, compiled: list[dict[str, Any]], files: dict[str, Path], out_w: int, out_h: int
) -> compositor.Composition:
    tracks = ap.asset.audio_tracks or []
    rate = int((tracks[0] or {}).get("sample_rate") or 48000) if tracks else 48000
    if not 8000 <= rate <= 192000:
        rate = 48000
    first = (tracks[0] or {}) if tracks else {}
    # Estos valores se interpolan en el grafo de filtros: solo se aceptan nombres de
    # disposición de canales con caracteres seguros.
    layout = str(first.get("channel_layout") or "").split("(")[0]
    if not _SAFE_LAYOUT.fullmatch(layout):
        layout = {1: "mono", 2: "stereo", 6: "5.1"}.get(int(first.get("channels") or 2), "stereo")
    fps_num = int(ap.asset.fps_num or 30)
    fps_den = int(ap.asset.fps_den or 1)
    if not (0 < fps_num <= 1_000_000 and 0 < fps_den <= 1_000_000):
        fps_num, fps_den = 30, 1
    # Preferencias de audio ACTUALES del proyecto (el usuario puede ajustarlas tras aprobar).
    audio = current_config(ap).audio
    voice = voice_measure(resolve_inside(ap.root, ap.asset.file_rel)) if tracks else (None, None)
    comp = compositor.Composition(
        sfx_volume=audio.sfx_volume if audio.sfx_enabled else 0,
        sfx_intensity=audio.sfx_intensity,
        voice_lufs=voice[0],
        voice_tp=voice[1],
        sample_rate=rate,
        channel_layout=layout,
        fps_rate=f"{fps_num}/{fps_den}",
        duration=float(ap.asset.duration or 0.0),
    )
    faces_center = (0.5, 0.42)
    for c in compiled:
        iv, spec = c["iv"], c["spec"]
        path = files.get(iv["id"])
        if path is None:
            continue
        pip_box = spec.get("pip")
        comp.clips.append(
            compositor.ClipLayer(
                path=path,
                start=float(iv["start"]),
                end=float(iv["end"]),
                mode=spec["mode"],
                pip_src=c.get("pip_src"),
                pip_box=pip_box,
                viewport=spec.get("viewport"),
                frame_size=(int(spec["width"]), int(spec["height"])),
                blur=(iv.get("composition") or {}).get("background") == "blurred_video"
                and spec["mode"] == "overlay",
            )
        )
        cam = (iv.get("motion") or {}).get("camera", "none")
        if cam != "none" and spec["mode"] != "fullscreen":
            regs = iv.get("protected_regions") or []
            if regs:
                r = regs[0]
                faces_center = (r["x"] + r["w"] / 2, r["y"] + r["h"] / 2)
            comp.camera.append(
                compositor.CameraMove(
                    float(iv["start"]), float(iv["end"]), cam, faces_center[0], faces_center[1]
                )
            )
        # Efectos aprobados, alineados al evento visual más cercano (≤ 0,4 s) para que suenen
        # exactamente cuando aparece el elemento. La densidad se controla al final.
        cues = [float(iv["start"]) + it["cue"] / spec["fps"] for it in spec["items"]]
        enter = float(iv["start"]) + animation_spec.entry_start(spec) / spec["fps"]
        for s in iv.get("sfx") or []:
            at = float(s["at"])
            if enter > float(iv["start"]) and at < enter:
                at = enter  # el contenedor entra más tarde: el efecto de entrada lo acompaña
            near = min(cues, key=lambda t: abs(t - at), default=None)
            if near is not None and abs(near - at) <= 0.4:
                at = near
            gain = {"low": -4.0, "medium": 0.0, "high": 2.0}.get(iv.get("intensity", "medium"), 0.0)
            comp.sfx.append(compositor.SfxCue(kind=s["kind"], at=round(at, 3), gain_db=gain))
    comp.sfx = thin_sfx(comp.sfx)
    return comp


SFX_MIN_GAP = 0.25  # s entre dos efectos cualesquiera
SFX_SAME_KIND_GAP = 1.2  # s entre dos efectos del mismo tipo


def thin_sfx(cues: list[compositor.SfxCue]) -> list[compositor.SfxCue]:
    """Evita efectos amontonados o repetitivos: separa los efectos (≥ 0,25 s; ≥ 1,2 s si son
    del mismo tipo) y alterna variantes de cada tipo para que no suenen idénticos."""
    kept: list[compositor.SfxCue] = []
    last_kind: dict[str, float] = {}
    count: dict[str, int] = {}
    for c in sorted(cues, key=lambda c: c.at):
        if kept and c.at - kept[-1].at < SFX_MIN_GAP:
            continue
        if c.kind in last_kind and c.at - last_kind[c.kind] < SFX_SAME_KIND_GAP:
            continue
        c.variant = count.get(c.kind, 0) % sfx_lib.VARIANTS
        count[c.kind] = count.get(c.kind, 0) + 1
        last_kind[c.kind] = c.at
        kept.append(c)
    return kept


_LOUDNESS: dict[tuple[str, int, int], tuple[float | None, float | None]] = {}


def voice_measure(path: Path) -> tuple[float | None, float | None]:
    """(Sonoridad integrada en LUFS, pico verdadero en dBTP) del audio original, medidos una
    vez por archivo: referencia para situar los efectos y para el techo de pico."""
    st = path.stat()
    key = (str(path), st.st_size, int(st.st_mtime))
    if key not in _LOUDNESS:
        try:
            err = subprocess.run(
                [get_settings().ffmpeg, "-nostdin", "-i", str(path), "-vn", "-map", "0:a:0",
                 "-af", "ebur128=peak=true", "-f", "null", "-"],
                capture_output=True, text=True, timeout=300,
            ).stderr  # fmt: skip
            tail = err[err.rfind("Summary:") :]
            value = float(tail.split("I:")[1].split()[0])
            try:
                tp: float | None = float(tail.split("Peak:")[1].split()[0])
            except (IndexError, ValueError):
                tp = None
            _LOUDNESS[key] = (value if value > -70 else None, tp)
        except (subprocess.SubprocessError, OSError, IndexError, ValueError):
            _LOUDNESS[key] = (None, None)
    return _LOUDNESS[key]


def voice_loudness(path: Path) -> float | None:
    return voice_measure(path)[0]
