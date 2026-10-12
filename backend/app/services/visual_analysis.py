"""Análisis visual local: escenas, transiciones, intervalos estáticos, fotogramas y rostros.

Decodificación: FFmpeg entrega fotogramas reducidos (lado largo 128 px) por tubería con su
tiempo de presentación real (``showinfo``); nunca se guardan todos los fotogramas.

Métricas entre fotogramas consecutivos:
- ``d_struct``: diferencia media de la luminancia normalizada (z-score por fotograma). Es
  insensible a cambios globales de brillo/contraste → un cambio de iluminación no es un corte.
- ``d_hist``: distancia de Bhattacharyya entre histogramas HSV (16×4×4).
Un **corte** exige ambas por encima de umbral y un pico claro respecto a su vecindad (±1 s),
lo que descarta el movimiento de cámara sostenido. Una **transición gradual** (fundido o
disolución) se acepta solo si el fotograma central es una mezcla lineal de los extremos
(residuo bajo), algo que un paneo o un movimiento no cumplen.
"""

from __future__ import annotations

import array
import bisect
import contextlib
import hashlib
import json
import logging
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app import limits
from app.domain.preferences import AnalysisPreferences
from app.platform import processes
from app.services.media_tools import Cancelled, FFmpegError, Watchdog

log = logging.getLogger(__name__)

PIPELINE_VERSION = "visual-2"  # cambiarla invalida la caché de análisis visual
ANALYSIS_LONG_SIDE = 128
FRAME_LONG_SIDE = 768
YUNET_PATH = (
    Path(__file__).resolve().parents[1]
    / "resources"
    / "models"
    / ("face_detection_yunet_2023mar.onnx")
)
_PTS = re.compile(r"pts_time:\s*(-?[0-9.]+)")


def params_hash(sha256: str, prefs: AnalysisPreferences) -> str:
    key = {
        "sha": sha256,
        "v": PIPELINE_VERSION,
        "scene_threshold": prefs.scene_threshold,
        "min_scene_seconds": prefs.min_scene_seconds,
        "static_min_seconds": prefs.static_min_seconds,
        "frame_interval_seconds": prefs.frame_interval_seconds,
        "max_frames": prefs.max_frames,
        "detect_faces": prefs.detect_faces,
    }
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()


def _analysis_size(width: int, height: int) -> tuple[int, int]:
    scale = ANALYSIS_LONG_SIDE / max(width, height)
    w = max(16, round(width * scale / 2) * 2)
    h = max(16, round(height * scale / 2) * 2)
    return w, h


@dataclass
class FrameStats:
    # Arrays compactos (4–8 bytes por valor) en lugar de listas de floats de Python.
    times: Any = field(default_factory=lambda: array.array("d"))
    d_struct: Any = field(default_factory=lambda: array.array("f"))
    d_hist: Any = field(default_factory=lambda: array.array("f"))
    luma: Any = field(default_factory=lambda: array.array("f"))
    contrast: Any = field(default_factory=lambda: array.array("f"))
    colorfulness: Any = field(default_factory=lambda: array.array("f"))
    # Pequeñas copias en escala de grises para validar transiciones graduales.
    thumbs: list[np.ndarray] = field(default_factory=list)


def _colorfulness(rgb: np.ndarray) -> float:
    r, g, b = (rgb[..., i].astype(np.float32) for i in range(3))
    rg, yb = r - g, 0.5 * (r + g) - b
    return float(
        np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    )


def decode_stats(
    ffmpeg: str,
    src: Path,
    width: int,
    height: int,
    duration: float,
    *,
    on_progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> FrameStats:
    """Recorre el video una vez a baja resolución calculando las métricas por fotograma."""
    w, h = _analysis_size(width, height)
    args = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "info"]
    if sys.platform == "darwin":
        args += ["-hwaccel", "videotoolbox"]
    args += [
        "-i",
        str(src),
        "-an",
        "-sn",
        "-dn",
        "-fps_mode",
        "passthrough",
        "-vf",
        f"scale={w}:{h}:flags=area,format=rgb24,showinfo",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-",
    ]
    proc = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **processes.group_kwargs()
    )
    processes.track(proc)
    watchdog = Watchdog(
        proc,
        cancel=cancel,
        max_seconds=limits.ffmpeg_max_seconds(duration),
        stall_seconds=limits.FFMPEG_STALL_SECONDS,
    )
    times: list[float] = []
    tail: list[str] = []

    def _read_stderr() -> None:
        assert proc.stderr is not None
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace")
            m = _PTS.search(line) if "showinfo" in line else None
            if m:
                times.append(float(m.group(1)))
            else:
                tail.append(line.rstrip())
                del tail[:-20]

    reader = threading.Thread(target=_read_stderr, daemon=True)
    reader.start()
    st = FrameStats()
    frame_bytes = w * h * 3
    prev_norm: np.ndarray | None = None
    prev_hist: np.ndarray | None = None
    idx = 0
    assert proc.stdout is not None
    try:
        while True:
            if cancel is not None and cancel.is_set():
                processes.terminate_tree(proc, grace=2)
                raise Cancelled()
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            watchdog.tick()
            rgb = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
            mean, std = float(gray.mean()), float(gray.std())
            norm = (gray - mean) / (std + 6.0)
            hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
            hist = cv2.calcHist([hsv], [0, 1, 2], None, [16, 4, 4], [0, 180, 0, 256, 0, 256])
            hist = cv2.normalize(hist, hist, alpha=1, norm_type=cv2.NORM_L1).flatten()
            if prev_norm is None or prev_hist is None:
                st.d_struct.append(0.0)
                st.d_hist.append(0.0)
            else:
                st.d_struct.append(float(np.mean(np.abs(norm - prev_norm))) / 2.0)
                st.d_hist.append(float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA)))
            st.luma.append(mean)
            st.contrast.append(std)
            st.colorfulness.append(_colorfulness(rgb))
            # 20×20 uint8: ~400 B por fotograma (≈86 MB para 1 h a 60 fps).
            st.thumbs.append(
                cv2.resize(gray, (20, 20), interpolation=cv2.INTER_AREA).astype(np.uint8)
            )
            prev_norm, prev_hist = norm, hist
            idx += 1
            if on_progress and idx % 30 == 0 and times and duration:
                on_progress(min(0.99, times[-1] / duration))
        proc.wait()
    finally:
        watchdog.stop()
        if proc.poll() is None:
            processes.terminate_tree(proc, grace=2)
            proc.wait()
        processes.untrack(proc)
        reader.join(timeout=5)
    watchdog.raise_if_stopped()
    if proc.returncode not in (0, None) and idx == 0:
        raise FFmpegError("No se pudo decodificar el video: " + (tail[-1] if tail else ""))
    # showinfo y los fotogramas salen en el mismo orden; por seguridad se igualan longitudes.
    n = min(idx, len(times))
    st.times = array.array("d", times[:n])
    for name in ("d_struct", "d_hist", "luma", "contrast", "colorfulness", "thumbs"):
        setattr(st, name, getattr(st, name)[:n])
    return st


# ---------------------------------------------------------------------------
# Escenas y transiciones
# ---------------------------------------------------------------------------


def _structure_corr(a: np.ndarray, b: np.ndarray) -> float | None:
    """Correlación de estructura (z-score) entre dos miniaturas; None si alguna es plana."""
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    sa, sb = float(a.std()), float(b.std())
    if sa < 4 or sb < 4:
        return None
    return float(np.mean(((a - a.mean()) / sa) * ((b - b.mean()) / sb)))


def detect_cuts(st: FrameStats, threshold: float) -> list[tuple[int, float]]:
    """Índices de fotograma donde empieza una escena por corte, con su puntuación."""
    n = len(st.times)
    if n < 3:
        return []
    ds = np.array(st.d_struct)
    dh = np.array(st.d_hist)
    score = 0.5 * np.clip(ds / 0.6, 0, 1) + 0.5 * np.clip(dh / 0.6, 0, 1)
    fps = (n - 1) / max(1e-6, st.times[-1] - st.times[0]) if n > 1 else 30
    win = max(3, round(fps))
    cuts: list[tuple[int, float]] = []
    for i in range(1, n):
        if score[i] < threshold or ds[i] < 0.12 or dh[i] < 0.08:
            continue
        lo, hi = max(1, i - win), min(n, i + win + 1)
        neighbors = np.concatenate([score[lo:i], score[i + 1 : hi]])
        local = float(np.median(neighbors)) if len(neighbors) else 0.0
        # Pico claro: muy por encima de la actividad de alrededor (descarta movimiento).
        if not (score[i] >= max(2.5 * local, local + 0.15) and score[i] == score[lo:hi].max()):
            continue
        # Destello/transitorio: si poco después vuelve la misma imagen que antes, no es corte.
        j = min(n - 1, i + max(2, round(0.25 * fps)))
        corr = _structure_corr(st.thumbs[i - 1], st.thumbs[j])
        if corr is not None and corr > 0.85:
            continue
        cuts.append((i, float(score[i])))
    return cuts


def detect_gradual(
    st: FrameStats, cuts: list[tuple[int, float]], threshold: float
) -> list[dict[str, Any]]:
    """Fundidos/disoluciones: cambio grande entre extremos de una ventana sin corte dentro y
    fotograma central explicable como mezcla lineal de ambos extremos."""
    n = len(st.times)
    if n < 10:
        return []
    fps = (n - 1) / max(1e-6, st.times[-1] - st.times[0])
    k = max(3, round(0.4 * fps))
    cut_idx = {i for i, _ in cuts}
    thumbs = st.thumbs
    found: list[dict[str, Any]] = []
    i = k
    while i < n - k:
        a, b, m = i - k, i + k, i
        if any(c in cut_idx for c in range(a + 1, b + 1)):
            i += k
            continue
        A, B, M = (thumbs[x].astype(np.float32) for x in (a, b, m))
        diff = B - A
        denom = float(np.sum(diff * diff))
        span = float(np.mean(np.abs(diff))) / 255.0
        if denom <= 1e-6 or span < max(0.12, threshold * 0.35):
            i += max(1, k // 3)
            continue
        alpha = float(np.sum((M - A) * diff) / denom)
        residual = float(np.mean(np.abs(M - (A + alpha * diff)))) / max(
            1e-6, float(np.mean(np.abs(diff)))
        )
        # Un cambio de iluminación también es una «mezcla lineal»: se exige que los extremos
        # tengan estructura distinta (o que uno sea plano, como en un fundido a negro).
        corr = _structure_corr(A, B)
        if 0.2 < alpha < 0.8 and residual < 0.3 and (corr is None or corr < 0.6):
            dark = min(st.luma[a : b + 1]) < 16
            found.append(
                {
                    "start_index": a,
                    "end_index": b,
                    "center_index": m,
                    "kind": "fade" if dark else "dissolve",
                    "residual": round(residual, 3),
                }
            )
            i = b + k
        else:
            i += max(1, k // 3)
    merged: list[dict[str, Any]] = []
    for g in found:
        if merged and g["start_index"] - merged[-1]["end_index"] <= k:
            prev = merged[-1]
            prev["end_index"] = g["end_index"]
            prev["center_index"] = (prev["start_index"] + g["end_index"]) // 2
            if g["kind"] == "fade":
                prev["kind"] = "fade"
        else:
            merged.append(dict(g))
    return merged


def static_intervals(st: FrameStats, min_seconds: float) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    start = None
    for i, (ds, dh) in enumerate(zip(st.d_struct, st.d_hist, strict=True)):
        still = ds < 0.02 and dh < 0.03
        if still and start is None:
            start = i
        elif not still and start is not None:
            if st.times[i - 1] - st.times[start] >= min_seconds:
                out.append((st.times[start], st.times[i - 1]))
            start = None
    if start is not None and st.times and st.times[-1] - st.times[start] >= min_seconds:
        out.append((st.times[start], st.times[-1]))
    return out


def build_scenes(
    st: FrameStats,
    duration: float,
    prefs: AnalysisPreferences,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cuts = detect_cuts(st, prefs.scene_threshold)
    gradual = detect_gradual(st, cuts, prefs.scene_threshold)
    n_frames = len(st.times)
    fps = (n_frames - 1) / max(1e-6, st.times[-1] - st.times[0]) if n_frames > 1 else 30
    k = max(2, round(0.3 * fps))

    def cut_kind(i: int) -> str:
        around = st.luma[max(0, i - k) : min(n_frames, i + k + 1)]
        return "fade" if around and min(around) < 20 else "cut"

    boundaries: list[tuple[int, str, float]] = [(i, cut_kind(i), s) for i, s in cuts]
    boundaries += [(g["center_index"], g["kind"], 0.5) for g in gradual]
    boundaries.sort()
    # Duración mínima de escena: si dos límites están demasiado cerca, se queda el más fuerte.
    kept: list[tuple[int, str, float]] = []
    for b in boundaries:
        if kept and st.times[b[0]] - st.times[kept[-1][0]] < prefs.min_scene_seconds:
            if b[2] > kept[-1][2]:
                kept[-1] = b
            continue
        if st.times[b[0]] - (st.times[0] if st.times else 0) < prefs.min_scene_seconds:
            continue
        kept.append(b)
    starts = [(0, "start")] + [(i, kind) for i, kind, _ in kept]
    statics = static_intervals(st, prefs.static_min_seconds)
    scenes = []
    for n, (i, kind) in enumerate(starts):
        j = starts[n + 1][0] if n + 1 < len(starts) else len(st.times)
        t0 = 0.0 if n == 0 else st.times[i]
        t1 = st.times[j] if j < len(st.times) else duration
        sl = slice(i, max(i + 1, j))
        ds = np.array(st.d_struct[sl][1:] or [0.0])
        motion = float(np.mean(ds))
        static_s = sum(max(0.0, min(b, t1) - max(a, t0)) for a, b in statics if b > t0 and a < t1)
        luma = float(np.mean(st.luma[sl])) if st.luma else 0.0
        scenes.append(
            {
                "index": n,
                "start": round(t0, 3),
                "end": round(t1, 3),
                "duration": round(t1 - t0, 3),
                "transition_in": kind,
                "first_frame_index": i,
                "last_frame_index": max(i, j - 1),
                "metrics": {
                    "brightness": round(luma / 255, 3),
                    "contrast": round(float(np.mean(st.contrast[sl])) / 128, 3),
                    "colorfulness": round(float(np.mean(st.colorfulness[sl])), 1),
                    "motion": round(motion, 4),
                    "static_ratio": round(static_s / max(1e-6, t1 - t0), 3),
                },
                "labels": {
                    "brightness": "dark" if luma < 50 else "bright" if luma > 190 else "normal",
                    # «static» solo con quietud medida (≥ 80 % del tiempo sin cambios).
                    "motion": (
                        "static"
                        if static_s / max(1e-6, t1 - t0) >= 0.8
                        else "low"
                        if motion < 0.03
                        else "medium"
                        if motion < 0.1
                        else "high"
                    ),
                    "faces": "unknown",
                },
            }
        )
    transitions = [
        {
            "kind": g["kind"],
            "start": round(st.times[g["start_index"]], 3),
            "end": round(st.times[g["end_index"]], 3),
            "residual": g["residual"],
        }
        for g in gradual
        if any(g["center_index"] == i for i, _, _ in kept)
    ]
    for i, _kind, score in kept:
        if _kind in ("cut", "fade") and not any(g["center_index"] == i for g in gradual):
            transitions.append(
                {
                    "kind": _kind,
                    "start": round(st.times[i], 3),
                    "end": round(st.times[i], 3),
                    "score": round(score, 3),
                }
            )
    transitions.sort(key=lambda x: x["start"])
    return scenes, transitions


# ---------------------------------------------------------------------------
# Fotogramas selectivos
# ---------------------------------------------------------------------------


def plan_frames(
    st: FrameStats, scenes: list[dict[str, Any]], prefs: AnalysisPreferences
) -> list[dict[str, Any]]:
    """Elige fotogramas (tiempos reales de presentación): inicio, centro y final de cada escena
    y muestras a intervalos en escenas largas, con un máximo total."""
    times = st.times
    if not times:
        return []

    def nearest(t: float, lo: int, hi: int) -> int:
        lo = max(0, lo)
        hi = min(len(times) - 1, hi)
        k = bisect.bisect_left(times, t, lo, hi + 1)
        if k > hi:
            return hi
        if k > lo and abs(times[k - 1] - t) <= abs(times[k] - t):
            return k - 1
        return k

    interval = prefs.frame_interval_seconds
    for _ in range(8):
        plan: list[dict[str, Any]] = []
        for sc in scenes:
            a, b = sc["first_frame_index"], sc["last_frame_index"]
            picks: dict[int, str] = {}
            # Inicio desplazado ligeramente para evitar el primer fotograma de una disolución.
            start_idx = min(b, a + (2 if sc["transition_in"] in ("dissolve", "fade") else 0))
            picks[start_idx] = "scene_start"
            if sc["duration"] >= 1.0:
                picks.setdefault(nearest((sc["start"] + sc["end"]) / 2, a, b), "scene_mid")
            if sc["duration"] >= 2.0:
                picks.setdefault(max(a, b - 1), "scene_end")
            t = sc["start"] + interval
            while t < sc["end"] - interval / 2:
                picks.setdefault(nearest(t, a, b), "interval")
                t += interval
            for idx, reason in picks.items():
                plan.append(
                    {
                        "t": times[idx],
                        "frame_index": idx,
                        "reason": reason,
                        "scene_index": sc["index"],
                    }
                )
        if len(plan) <= prefs.max_frames:
            break
        interval *= 1.6
    # Si aún hay demasiadas escenas, conservar la mitad de cada una (prioridad) hasta el máximo.
    plan.sort(key=lambda p: (p["reason"] != "scene_mid", p["t"]))
    plan = sorted(plan[: prefs.max_frames], key=lambda p: p["t"])
    return plan


def extract_frame(ffmpeg: str, src: Path, t: float, dest: Path) -> tuple[int, int]:
    """Extrae el fotograma con tiempo de presentación ``t`` (búsqueda precisa)."""
    fit = (
        f"scale=w='if(gte(iw,ih),min({FRAME_LONG_SIDE},iw),-2)'"
        f":h='if(gte(iw,ih),-2,min({FRAME_LONG_SIDE},ih))'"
    )
    tmp = dest.with_name(f".{dest.stem}.tmp.jpg")
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            f"{max(0.0, t - 0.001):.6f}",
            "-i",
            str(src),
            "-an",
            "-sn",
            "-frames:v",
            "1",
            "-vf",
            fit,
            "-q:v",
            "3",
            str(tmp),
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0 or not tmp.exists():
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise FFmpegError(
            "No se pudo extraer el fotograma: "
            + proc.stderr.decode("utf-8", "replace").strip()[-200:]
        )
    img = cv2.imread(str(tmp))
    tmp.replace(dest)
    if img is None:
        return 0, 0
    return int(img.shape[1]), int(img.shape[0])


# ---------------------------------------------------------------------------
# Rostros
# ---------------------------------------------------------------------------


class FaceDetector:
    """YuNet (OpenCV Zoo, MIT). Devuelve cajas y puntos (ojos, nariz, comisuras) normalizados."""

    def __init__(self, score_threshold: float = 0.8) -> None:
        self.detector = cv2.FaceDetectorYN.create(
            str(YUNET_PATH), "", (320, 320), score_threshold, 0.3, 50
        )

    def detect(self, image_path: Path) -> list[dict[str, Any]]:
        img = cv2.imread(str(image_path))
        if img is None:
            return []
        h, w = img.shape[:2]
        self.detector.setInputSize((w, h))
        _, faces = self.detector.detect(img)
        out = []
        for f in faces if faces is not None else []:
            x, y, bw, bh = (float(v) for v in f[:4])
            pts = [float(v) for v in f[4:14]]

            def p(i: int, pts: list[float] = pts) -> list[float]:
                return [round(pts[2 * i] / w, 4), round(pts[2 * i + 1] / h, 4)]

            out.append(
                {
                    "box": [
                        round(max(0, x) / w, 4),
                        round(max(0, y) / h, 4),
                        round(min(bw, w - x) / w, 4),
                        round(min(bh, h - y) / h, 4),
                    ],
                    "score": round(float(f[14]), 3),
                    "right_eye": p(0),
                    "left_eye": p(1),
                    "nose": p(2),
                    "mouth_right": p(3),
                    "mouth_left": p(4),
                }
            )
        return sorted(out, key=lambda d: -d["box"][2] * d["box"][3])


def summarize_faces(frames: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumen por escena a partir de los fotogramas analizados (medido, no inferido)."""
    checked = [f for f in frames if f.get("faces") is not None]
    if not checked:
        return {"status": "unknown"}
    with_faces = [f for f in checked if f["faces"]]
    max_faces = max((len(f["faces"]) for f in checked), default=0)
    boxes = [face["box"] for f in with_faces for face in f["faces"]]
    union = None
    if boxes:
        x0 = min(b[0] for b in boxes)
        y0 = min(b[1] for b in boxes)
        x1 = max(b[0] + b[2] for b in boxes)
        y1 = max(b[1] + b[3] for b in boxes)
        union = [round(x0, 4), round(y0, 4), round(x1 - x0, 4), round(y1 - y0, 4)]
    mouths = [
        max(face["mouth_left"][1], face["mouth_right"][1])
        for f in with_faces
        for face in f["faces"]
    ]
    eyes = [
        min(face["left_eye"][1], face["right_eye"][1]) for f in with_faces for face in f["faces"]
    ]
    return {
        "status": "none" if not with_faces else "single" if max_faces == 1 else "multiple",
        "frames_checked": len(checked),
        "frames_with_faces": len(with_faces),
        "max_faces": max_faces,
        "union_box": union,
        "lowest_mouth_y": round(max(mouths), 4) if mouths else None,
        "highest_eye_y": round(min(eyes), 4) if eyes else None,
        "largest_face_area": round(max((b[2] * b[3] for b in boxes), default=0.0), 4),
    }


def run_parallel(items: list[Any], fn: Callable[[Any], Any], workers: int = 4) -> list[Any]:
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))
