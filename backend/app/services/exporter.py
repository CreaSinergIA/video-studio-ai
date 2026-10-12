"""Exportación de video con subtítulos integrados (FFmpeg).

Proceso:
1. Pista de subtítulos (``subtitles.build_track``) a la resolución de salida.
2. Render de los *estados que cambian* (no de cada fotograma) a PNG RGBA en el disco interno.
3. Secuencia de imágenes con duraciones (demuxer ``concat``) superpuesta con ``overlay``.
4. Codificación con progreso real (``-progress``), salida temporal + renombrado atómico.

Fidelidad: se respeta la rotación (FFmpeg autorrota al decodificar), la relación de aspecto,
el FPS original (``-fps_mode passthrough`` conserva incluso FPS variable), las etiquetas de
color, los metadatos y el audio original (copia sin recodificar cuando el contenedor lo admite).
H.264 no admite HDR sin mapeo de tonos (no disponible: el FFmpeg instalado no trae zscale),
así que para fuentes HDR solo se permite HEVC 10 bits o ProRes.
"""

from __future__ import annotations

import contextlib
import itertools
import logging
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.domain.edit_config import ExportSettings, SubtitleSettings
from app.models import MediaAsset
from app.services import subtitles
from app.services.media_probe import HDR_TRANSFERS
from app.services.media_tools import available_encoders, run_ffmpeg

log = logging.getLogger(__name__)

MP4_AUDIO = {"aac", "mp3", "alac", "ac3", "eac3", "opus", "flac"}
MOV_AUDIO = {"aac", "mp3", "alac", "pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le"}


class ExportError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class ExportPlan:
    width: int
    height: int
    fps: str
    container: str
    video_codec: str
    encoder: str
    video_args: list[str]
    pix_fmt: str
    audio_args: list[str]
    color_args: list[str]
    estimated_bytes: int
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "container": self.container,
            "video_codec": self.video_codec,
            "encoder": self.encoder,
            "pix_fmt": self.pix_fmt,
            "estimated_bytes": self.estimated_bytes,
            "warnings": self.warnings,
        }


def _even(x: float) -> int:
    return max(2, round(x / 2) * 2)


def target_size(asset: MediaAsset, resolution: str) -> tuple[int, int]:
    w, h = asset.display_width, asset.display_height
    short = min(w, h)
    if resolution == "original":
        return _even(w), _even(h)
    goal = 1080 if resolution == "1080p" else 2160
    if short < goal:
        raise ExportError(
            "upscale_not_allowed",
            f"El original mide {w}×{h}: no se puede exportar a {resolution} sin reescalar hacia "
            "arriba (perdería nitidez). Usa «Original».",
        )
    factor = goal / short
    return _even(w * factor), _even(h * factor)


def plan_export(asset: MediaAsset, settings: ExportSettings) -> ExportPlan:
    ffmpeg = get_settings().ffmpeg
    encoders = available_encoders(ffmpeg)
    width, height = target_size(asset, settings.resolution)
    hdr = asset.color_transfer in HDR_TRANSFERS
    ten_bit = (asset.bit_depth or 8) > 8
    warnings: list[str] = []
    fmt = settings.format
    if hdr and fmt == "mp4_h264":
        raise ExportError(
            "hdr_requires_hevc",
            "El original es HDR. H.264 no puede conservarlo y la conversión a SDR sin mapeo de "
            "tonos cambiaría mucho los colores. Elige MP4 · HEVC (10 bits) o MOV · ProRes.",
        )
    hardware = settings.encoder == "hardware"
    crf_hi = settings.quality == "max"
    if fmt == "mp4_h264":
        container, vcodec = "mp4", "h264"
        if hardware and "h264_videotoolbox" in encoders:
            enc = "h264_videotoolbox"
            vargs = ["-c:v", enc, "-q:v", "85" if crf_hi else "80", "-profile:v", "high"]
        else:
            enc = "libx264"
            vargs = [
                "-c:v",
                enc,
                "-preset",
                "slower" if crf_hi else "slow",
                "-crf",
                "14" if crf_hi else "17",
                "-profile:v",
                "high",
            ]
        pix = "yuv420p"
    elif fmt == "mp4_hevc":
        container, vcodec = "mp4", "hevc"
        pix = "yuv420p10le" if (hdr or ten_bit) else "yuv420p"
        if hardware and "hevc_videotoolbox" in encoders:
            enc = "hevc_videotoolbox"
            vargs = [
                "-c:v",
                enc,
                "-q:v",
                "88" if crf_hi else "80",
                "-tag:v",
                "hvc1",
                "-profile:v",
                "main10" if pix.endswith("10le") else "main",
            ]
        else:
            enc = "libx265"
            vargs = [
                "-c:v",
                enc,
                "-preset",
                "slow" if crf_hi else "medium",
                "-crf",
                "15" if crf_hi else "19",
                "-tag:v",
                "hvc1",
                "-x265-params",
                "log-level=error",
            ]
    else:
        container, vcodec = "mov", "prores"
        pix = "yuv422p10le"
        if hardware and "prores_videotoolbox" in encoders:
            enc = "prores_videotoolbox"
            vargs = ["-c:v", enc, "-profile:v", "3" if crf_hi else "2"]
        else:
            enc = "prores_ks"
            vargs = ["-c:v", enc, "-profile:v", "3" if crf_hi else "2", "-vendor", "apl0"]
    if hardware and enc in ("libx264", "libx265", "prores_ks"):
        warnings.append(
            "La aceleración por hardware no está disponible; se usa el codificador software."
        )
    color: list[str] = []
    probe_stream: dict[str, Any] = next(
        (s for s in (asset.probe or {}).get("streams", []) if s.get("codec_type") == "video"),
        {},
    )
    for key, flag in (
        ("color_primaries", "-color_primaries"),
        ("color_transfer", "-color_trc"),
        ("color_space", "-colorspace"),
        ("color_range", "-color_range"),
    ):
        value = probe_stream.get(key)
        if value and value != "unknown":
            color += [flag, str(value)]
    if hdr:
        warnings.append(
            "Fuente HDR: se conserva la curva y la gama de color originales en 10 bits. Los "
            "subtítulos se integran con su color tal cual (pueden verse más brillantes en "
            "pantallas HDR)."
        )
    # Audio: copiar si el contenedor admite todas las pistas; si no, AAC 320 kb/s.
    tracks = list(asset.audio_tracks or []) if asset.has_audio else []
    if not tracks:
        aargs = ["-an"]
    else:
        allowed = MP4_AUDIO if container == "mp4" else MOV_AUDIO
        if all(t.get("codec") in allowed for t in tracks):
            aargs = ["-map", "0:a?", "-c:a", "copy"]
        else:
            aargs = ["-map", "0:a?", "-c:a", "aac", "-b:a", "320k"]
            warnings.append(
                "El audio original se recodifica a AAC 320 kb/s "
                "(el contenedor no admite su formato)."
            )
    fps = "original" if settings.fps == "original" else str(settings.fps)
    # Estimación prudente de tamaño (para comprobar espacio libre).
    src_rate = asset.bit_rate or 20_000_000
    area = (width * height) / max(1, asset.display_width * asset.display_height)
    factor = 6.0 if vcodec == "prores" else 1.3
    estimated = int(src_rate / 8 * asset.duration * max(0.3, area) * factor) + 20 * 1024**2
    return ExportPlan(
        width=width,
        height=height,
        fps=fps,
        container=container,
        video_codec=vcodec,
        encoder=enc,
        video_args=vargs,
        pix_fmt=pix,
        audio_args=aargs,
        color_args=color,
        estimated_bytes=estimated,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Superposición de subtítulos
# ---------------------------------------------------------------------------


def render_overlay(
    track: dict[str, Any],
    out_dir: Path,
    fps: float,
    duration: float,
    on_progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> Path | None:
    """Genera las imágenes de los estados y la lista ``concat``. None si no hay subtítulos."""
    from app.services.media_tools import Cancelled

    if not track["enabled"] or not track["blocks"]:
        return None
    times = [t for t in subtitles.change_times(track, fps) if t < duration] + [duration]
    times = sorted(set([0.0, *times]))
    entries: list[tuple[str, float]] = []
    jobs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for a, b in itertools.pairwise(times):
        if b - a < 1e-4:
            continue
        block = subtitles.block_at(track, a + 1e-6)
        state = subtitles.state_at(track, block, a + 1e-6) if block else None
        key = subtitles.state_key(block, state)
        if block is not None and state is not None:
            jobs.setdefault(key, (block, state))
        entries.append((key, b - a))
    empty = out_dir / "empty.png"
    from PIL import Image

    Image.new("RGBA", (track["width"], track["height"]), (0, 0, 0, 0)).save(empty, compress_level=1)
    keys = list(jobs)
    done = 0
    lock = threading.Lock()

    def work(key: str) -> None:
        nonlocal done
        if cancel is not None and cancel.is_set():
            return
        block, state = jobs[key]
        subtitles.render_state(track, block, state).save(out_dir / f"{key}.png", compress_level=1)
        with lock:
            done += 1
            if on_progress:
                on_progress(done / max(1, len(keys)))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(work, keys))
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    lines = ["ffconcat version 1.0"]
    # «framerate 1000»: base de tiempo de 1 ms por imagen. Sin ella, el lector de imágenes usa
    # 1/25 s y los cambios de palabra se redondean a pasos de 40 ms.
    for key, dur in entries:
        name = "empty.png" if key == "empty" else f"{key}.png"
        lines += [f"file '{name}'", "option framerate 1000", f"duration {dur:.6f}"]
    last = "empty.png" if entries[-1][0] == "empty" else f"{entries[-1][0]}.png"
    lines += [f"file '{last}'", "option framerate 1000"]
    listing = out_dir / "overlay.ffconcat"
    listing.write_text("\n".join(lines) + "\n")
    return listing


def encode(
    src: Path,
    dest_tmp: Path,
    plan: ExportPlan,
    overlay: Path | None,
    duration: float,
    *,
    on_progress: Callable[[float], None] | None = None,
    cancel: threading.Event | None = None,
) -> None:
    ffmpeg = get_settings().ffmpeg
    base = []
    if plan.fps != "original":
        base.append(f"fps={plan.fps}")
    base.append(f"scale={plan.width}:{plan.height}:flags=lanczos")
    base.append(f"format={plan.pix_fmt}")
    args = ["-i", str(src)]
    if overlay is not None:
        args += ["-f", "concat", "-safe", "0", "-i", str(overlay)]
        fc = (
            f"[0:v]{','.join(base)}[base];[1:v]format=rgba[sub];"
            f"[base][sub]overlay=0:0:eof_action=pass:format=auto,format={plan.pix_fmt}[v]"
        )
    else:
        fc = f"[0:v]{','.join(base)}[v]"
    args += [
        "-filter_complex",
        fc,
        "-map",
        "[v]",
        *plan.audio_args,
        *plan.video_args,
        "-pix_fmt",
        plan.pix_fmt,
        *plan.color_args,
        "-map_metadata",
        "0",
        "-movflags",
        "+faststart",
    ]
    if plan.fps == "original":
        args += ["-fps_mode", "passthrough"]
    args.append(str(dest_tmp))
    run_ffmpeg(ffmpeg, args, duration=duration, on_progress=on_progress, cancel=cancel)


def cleanup_stale(root: Path | None) -> int:
    """Al arrancar (sin tareas activas): borra exportaciones a medias y temporales de trabajo
    que un cierre o un fallo dejaron atrás."""
    removed = 0
    work = get_settings().home / "cache" / "work"
    if work.is_dir():
        for entry in work.iterdir():
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    if root is not None and (root / "projects").is_dir():
        for partial in (root / "projects").glob("*/exports/.*.partial.*"):
            with contextlib.suppress(OSError):
                partial.unlink()
                removed += 1
    return removed


def require_work_space(track: dict[str, Any], work: Path) -> None:
    """Comprueba espacio en el disco interno para las imágenes de subtítulos (estimación
    prudente: ~2 bytes por píxel del área ocupada por estado, PNG casi vacío fuera)."""
    from app.services.storage import StorageError, disk_usage

    states = sum(1 + sum(len(line["words"]) for line in b["lines"]) * 7 for b in track["blocks"])
    per_image = int(track["width"] * track["height"] * 0.05) + 20_000
    needed = states * per_image
    free, _ = disk_usage(work)
    if needed + 512 * 1024**2 > free:
        raise StorageError(
            "insufficient_space",
            f"No hay espacio en el disco interno para preparar los subtítulos "
            f"(~{needed / 1024**3:.1f} GB).",
            507,
        )


def temp_dir() -> Path:
    base = get_settings().home / "cache" / "work"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="export-", dir=base))


def cleanup(path: Path) -> None:
    with contextlib.suppress(OSError):
        shutil.rmtree(path, ignore_errors=True)


def probe_output(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            get_settings().ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    import json

    try:
        return json.loads(proc.stdout or "{}")
    except ValueError:
        return {}


def _luma(path: Path, t: float) -> float | None:
    """Luminancia media (0–1) del fotograma en ``t`` (miniatura de 32×32 en gris)."""
    proc = subprocess.run(
        [get_settings().ffmpeg, "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path),
         "-frames:v", "1", "-vf", "scale=32:32,format=gray", "-f", "rawvideo", "-"],
        capture_output=True, timeout=60, check=False,
    )  # fmt: skip
    data = proc.stdout
    if len(data) != 32 * 32:
        return None
    return sum(data) / (len(data) * 255)


def verify_output(
    final: Path,
    src: Path,
    *,
    width: int,
    height: int,
    duration: float,
    fps: float,
    expect_audio: bool,
    samples: int = 12,
) -> dict[str, Any]:
    """Comprobación del archivo exportado (Fase 5): duración, tamaño y orientación, audio y
    ausencia de fotogramas negros inesperados (muestreo frente al original). Devuelve
    ``{"ok", "errors", "warnings", ...}``: los errores invalidan la exportación."""
    info = probe_output(final)
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    got = float(info.get("format", {}).get("duration") or 0)
    errors: list[str] = []
    warnings: list[str] = []
    if v is None:
        errors.append("El archivo no contiene video.")
    else:
        if (int(v.get("width") or 0), int(v.get("height") or 0)) != (width, height):
            errors.append(f"Tamaño {v.get('width')}×{v.get('height')} en vez de {width}×{height}.")
    tolerance = max(0.12, 2.5 / max(1.0, fps))
    if abs(got - duration) > tolerance:
        errors.append(f"Duración {got:.2f} s en vez de {duration:.2f} s.")
    if expect_audio and not has_audio:
        errors.append("Falta la pista de audio.")
    black: list[float] = []
    if v is not None and duration > 0:
        for k in range(samples):
            t = duration * (k + 0.5) / samples
            out_l, src_l = _luma(final, t), _luma(src, t)
            if out_l is not None and src_l is not None and out_l < 0.02 and src_l > 0.06:
                black.append(round(t, 2))
    if black:
        warnings.append(
            "Fotogramas negros donde el original tiene imagen: "
            + ", ".join(f"{t:.1f} s" for t in black)
        )
    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "duration": round(got, 3),
        "expected_duration": round(duration, 3),
        "audio": has_audio,
        "black_samples": black,
        "samples": samples,
    }


def subtitle_settings_for(config: dict[str, Any]) -> SubtitleSettings:
    from app.domain.edit_config import EditConfig

    return EditConfig.model_validate(config).subtitles
