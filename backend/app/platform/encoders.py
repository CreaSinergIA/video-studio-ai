"""Codificación por hardware por plataforma.

Validado: VideoToolbox (macOS) y codificadores software (libx264/libx265/prores_ks), que
funcionan en cualquier sistema. Previstos para Windows (detectados, aún NO usados ni validados):
NVENC (NVIDIA), Quick Sync (Intel) y AMF (AMD). Hasta validarlos, en Windows se exporta con los
codificadores software aunque se pida «hardware».
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

VALIDATED = {"h264_videotoolbox", "hevc_videotoolbox", "prores_videotoolbox"}
CANDIDATES = {
    "h264": ["h264_videotoolbox", "h264_nvenc", "h264_qsv", "h264_amf"],
    "hevc": ["hevc_videotoolbox", "hevc_nvenc", "hevc_qsv", "hevc_amf"],
    "prores": ["prores_videotoolbox"],
}


def diagnose(encoders: Iterable[str]) -> dict[str, Any]:
    have = set(encoders)
    return {
        codec: [{"name": n, "present": n in have, "validated": n in VALIDATED} for n in names]
        for codec, names in CANDIDATES.items()
    }
