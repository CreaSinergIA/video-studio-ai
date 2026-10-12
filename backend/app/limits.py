"""Límites de recursos de la aplicación (configurables por variables de entorno).

Protegen al equipo de archivos desmesurados o de procesos colgados: un video de 16K o de 20
horas, o un FFmpeg que deja de avanzar, no deben bloquear el editor ni llenar el disco.
"""

from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


# Resolución máxima de un video importado: 8K (7680×4320, o vertical 4320×7680).
MAX_LONG_SIDE = _int("VSA_MAX_LONG_SIDE", 8192)
MAX_PIXELS = _int("VSA_MAX_PIXELS", 7680 * 4320)
# Duración máxima de un video importado (3 horas por defecto).
MAX_DURATION_SECONDS = _int("VSA_MAX_DURATION_SECONDS", 3 * 3600)
MAX_FPS = _int("VSA_MAX_FPS", 240)
# FFmpeg: sin avance durante este tiempo se considera colgado y se detiene.
FFMPEG_STALL_SECONDS = _int("VSA_FFMPEG_STALL_SECONDS", 300)
# FFmpeg: tiempo máximo absoluto. Con duración conocida: 30× la duración (mínimo 1 h), para no
# cortar exportaciones lentas legítimas (4K en CPU modestas); sin ella, 6 h.
FFMPEG_MAX_SECONDS = _int("VSA_FFMPEG_MAX_SECONDS", 6 * 3600)


def ffmpeg_max_seconds(duration: float | None) -> float:
    if os.environ.get("VSA_FFMPEG_MAX_SECONDS"):
        return float(FFMPEG_MAX_SECONDS)
    if duration and duration > 0:
        return max(3600.0, duration * 30)
    return float(FFMPEG_MAX_SECONDS)
