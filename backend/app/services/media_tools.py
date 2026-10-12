"""Derivados de medios con FFmpeg: miniatura, tira de fotogramas, forma de onda y proxy.

Todo se escribe primero en un archivo temporal junto al destino y se mueve con
``os.replace`` al terminar: un corte (disco desconectado, cierre) nunca deja un derivado
a medias con el nombre definitivo. El original solo se *lee*.
"""

from __future__ import annotations

import array
import collections
import contextlib
import logging
import math
import os
import secrets
import subprocess
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services.storage import atomic_write_json

log = logging.getLogger(__name__)

ProgressFn = Callable[[float], None]


class FFmpegError(Exception):
    pass


class Cancelled(Exception):
    pass


def _tmp_sibling(path: Path, suffix: str | None = None) -> Path:
    suffix = suffix if suffix is not None else path.suffix
    return path.with_name(f".{path.stem}.{secrets.token_hex(4)}.tmp{suffix}")


def _finalize(tmp: Path, dest: Path) -> None:
    os.replace(tmp, dest)


def run_ffmpeg(
    ffmpeg: str,
    args: list[str],
    *,
    duration: float | None = None,
    on_progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> None:
    """Ejecuta FFmpeg leyendo ``-progress`` para informar avance real y permitir cancelar."""
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-loglevel",
        "error",
        "-progress",
        "pipe:1",
        "-nostats",
        *args,
    ]
    log.debug("ffmpeg %s", " ".join(cmd))
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError as exc:
        raise FFmpegError("No se encontró FFmpeg. Instálalo con «brew install ffmpeg».") from exc
    stderr_tail: collections.deque[str] = collections.deque(maxlen=20)

    def _drain_stderr() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            stderr_tail.append(line.rstrip())

    drain = threading.Thread(target=_drain_stderr, daemon=True)
    drain.start()
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.terminate()
                break
            if on_progress and duration and line.startswith("out_time_us="):
                with contextlib.suppress(ValueError):
                    seconds = int(line.split("=", 1)[1]) / 1_000_000
                    on_progress(max(0.0, min(1.0, seconds / duration)))
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        drain.join(timeout=2)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if proc.returncode != 0:
        detail = stderr_tail[-1] if stderr_tail else f"código {proc.returncode}"
        raise FFmpegError(f"FFmpeg falló: {detail}")


# ---------------------------------------------------------------------------
# Capacidades de FFmpeg
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def available_encoders(ffmpeg: str) -> frozenset[str]:
    try:
        out = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=15
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return frozenset()
    names = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[0]) == 6 and parts[0][0] in "VAS":
            names.add(parts[1])
    return frozenset(names)


@lru_cache(maxsize=4)
def binary_version(binary: str) -> str | None:
    try:
        out = subprocess.run([binary, "-version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = out.stdout.splitlines()[0] if out.stdout else ""
    parts = first.split()
    return parts[2] if len(parts) >= 3 else first or None


# ---------------------------------------------------------------------------
# Derivados
# ---------------------------------------------------------------------------

_FIT_960 = "scale=w='if(gte(iw,ih),min(960,iw),-2)':h='if(gte(iw,ih),-2,min(960,ih))'"


def make_thumbnail(ffmpeg: str, src: Path, dest: Path, duration: float) -> None:
    """Fotograma representativo: el filtro ``thumbnail`` elige el más característico de un
    lote cercano al 15 % del video (evita negros iniciales)."""
    start = min(max(duration * 0.15, 0.0), max(duration - 0.5, 0.0))
    tmp = _tmp_sibling(dest)
    try:
        run_ffmpeg(
            ffmpeg,
            [
                "-ss",
                f"{start:.3f}",
                "-i",
                str(src),
                "-an",
                "-sn",
                "-vf",
                f"thumbnail=n=48,{_FIT_960}",
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(tmp),
            ],
        )
        if not tmp.exists() or tmp.stat().st_size == 0:
            # Videos muy cortos: tomar el primer fotograma.
            run_ffmpeg(
                ffmpeg,
                [
                    "-i",
                    str(src),
                    "-an",
                    "-sn",
                    "-vf",
                    _FIT_960,
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(tmp),
                ],
            )
        _finalize(tmp, dest)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


@dataclass
class FilmstripMeta:
    count: int
    tile_width: int
    tile_height: int
    interval: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "tile_width": self.tile_width,
            "tile_height": self.tile_height,
            "interval": self.interval,
        }


def filmstrip_count(duration: float) -> int:
    return max(12, min(60, math.ceil(duration)))


def _grab_frame(ffmpeg: str, src: Path, t: float, height: int) -> bytes:
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{t:.3f}",
            "-i",
            str(src),
            "-an",
            "-sn",
            "-frames:v",
            "1",
            "-vf",
            f"scale=-2:{height}",
            "-f",
            "image2pipe",
            "-c:v",
            "mjpeg",
            "-q:v",
            "4",
            "-",
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else b""


def make_filmstrip(
    ffmpeg: str,
    src: Path,
    dest: Path,
    duration: float,
    display_width: int,
    display_height: int,
    *,
    tile_height: int = 120,
    on_progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> FilmstripMeta:
    """Sprite horizontal con N fotogramas centrados en intervalos iguales (búsqueda precisa
    por fotograma: no depende de la distancia entre keyframes)."""
    count = filmstrip_count(duration)
    interval = duration / count
    times = [min((k + 0.5) * interval, max(duration - 0.05, 0)) for k in range(count)]
    frames: list[bytes] = [b""] * count
    done = 0
    lock = threading.Lock()

    def work(k: int) -> None:
        nonlocal done
        if cancel is not None and cancel.is_set():
            return
        frames[k] = _grab_frame(ffmpeg, src, times[k], tile_height)
        with lock:
            done += 1
            if on_progress:
                on_progress(done / count)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(work, range(count)))
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    # Rellenar huecos (búsquedas fallidas cerca del final) con el fotograma vecino.
    last = next((f for f in frames if f), b"")
    if not last:
        raise FFmpegError("No se pudieron extraer fotogramas para la línea de tiempo.")
    for k in range(count):
        if frames[k]:
            last = frames[k]
        else:
            frames[k] = last
    tmp = _tmp_sibling(dest)
    try:
        proc = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "image2pipe",
                "-c:v",
                "mjpeg",
                "-i",
                "-",
                "-vf",
                f"tile={count}x1",
                "-frames:v",
                "1",
                "-q:v",
                "4",
                str(tmp),
            ],
            input=b"".join(frames),
            capture_output=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            raise FFmpegError(
                "No se pudo componer la tira de fotogramas: "
                + proc.stderr.decode("utf-8", "replace").strip()[-200:]
            )
        _finalize(tmp, dest)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
    tile_width = max(2, round(display_width * tile_height / display_height / 2) * 2)
    return FilmstripMeta(
        count=count, tile_width=tile_width, tile_height=tile_height, interval=round(interval, 4)
    )


def make_waveform(
    ffmpeg: str,
    src: Path,
    dest: Path,
    duration: float,
    *,
    cancel: threading.Event | None = None,
    on_progress: ProgressFn | None = None,
) -> dict[str, Any]:
    """Picos de amplitud (0–1) de la primera pista de audio, calculados en streaming
    (PCM mono 8 kHz por tubería, sin cargar el audio completo en memoria)."""
    sample_rate = 8000
    target_peaks = int(max(200, min(8000, duration * 50)))
    samples_per_peak = max(1, int(duration * sample_rate / target_peaks))
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # stderr se drena en paralelo: si FFmpeg escribe muchos avisos (audio dañado) y nadie lee,
    # ambos procesos se bloquearían.
    stderr_tail: collections.deque[bytes] = collections.deque(maxlen=20)
    assert proc.stderr is not None
    err_stream = proc.stderr

    def _drain() -> None:
        for line in err_stream:
            stderr_tail.append(line)

    drain = threading.Thread(target=_drain, daemon=True)
    drain.start()
    peaks: list[float] = []
    pending = array.array("h")
    chunk_bytes = samples_per_peak * 2 * 256
    total_samples = max(1, int(duration * sample_rate))
    read_samples = 0
    assert proc.stdout is not None
    try:
        while True:
            if cancel is not None and cancel.is_set():
                proc.kill()
                raise Cancelled()
            data = proc.stdout.read(chunk_bytes)
            if not data:
                break
            if len(data) % 2:
                data = data[:-1]
            chunk = array.array("h")
            chunk.frombytes(data)
            if sys.byteorder == "big":  # pragma: no cover
                chunk.byteswap()
            pending.extend(chunk)
            read_samples += len(chunk)
            usable = len(pending) - len(pending) % samples_per_peak
            for i in range(0, usable, samples_per_peak):
                window = pending[i : i + samples_per_peak]
                peaks.append(max(abs(min(window)), abs(max(window))) / 32768)
            del pending[:usable]
            if on_progress:
                on_progress(min(1.0, read_samples / total_samples))
        if pending:
            peaks.append(max(abs(min(pending)), abs(max(pending))) / 32768)
        proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        drain.join(timeout=2)
    stderr = b"".join(stderr_tail).decode("utf-8", "replace")
    if proc.returncode != 0:
        raise FFmpegError(f"No se pudo leer el audio: {stderr.strip()[-200:]}")
    top = max(peaks, default=0.0)
    payload = {
        "version": 1,
        "duration": duration,
        "peaks_per_second": round(len(peaks) / duration, 4) if duration else 0,
        "max_peak": round(top, 4),
        "peaks": [round(p, 3) for p in peaks],
    }
    atomic_write_json(dest, payload)
    return payload


def make_proxy(
    ffmpeg: str,
    src: Path,
    dest: Path,
    duration: float,
    has_audio: bool,
    *,
    on_progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> str:
    """Proxy H.264/AAC reproducible en cualquier navegador (lado largo ≤ 1920 px).
    Usa VideoToolbox en macOS si está disponible; si no, libx264."""
    encoders = available_encoders(ffmpeg)
    fit = (
        "scale=w='if(gte(iw,ih),min(1920,iw),-2)':h='if(gte(iw,ih),-2,min(1920,ih))',format=yuv420p"
    )
    if "h264_videotoolbox" in encoders:
        vcodec = [
            "-c:v",
            "h264_videotoolbox",
            "-b:v",
            "8M",
            "-maxrate",
            "12M",
            "-profile:v",
            "high",
        ]
        encoder = "h264_videotoolbox"
    else:
        vcodec = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high"]
        encoder = "libx264"
    audio = ["-map", "0:a:0", "-c:a", "aac", "-b:a", "192k", "-ac", "2"] if has_audio else ["-an"]
    tmp = _tmp_sibling(dest)
    try:
        run_ffmpeg(
            ffmpeg,
            [
                "-i",
                str(src),
                "-map",
                "0:v:0",
                *audio,
                "-sn",
                "-vf",
                fit,
                *vcodec,
                "-movflags",
                "+faststart",
                str(tmp),
            ],
            duration=duration,
            on_progress=on_progress,
            cancel=cancel,
        )
        _finalize(tmp, dest)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
    return encoder
