"""Motores de transcripción local disponibles según la plataforma.

- ``mlx-whisper``: Apple Silicon (Metal). Motor preferido en esos Mac.
- ``faster-whisper`` (CTranslate2): Windows, Linux y Mac Intel. Funciona en la CPU (INT8) sin
  GPU dedicada; si hay una GPU NVIDIA con las bibliotecas CUDA disponibles se usa sola, y si
  falla se vuelve a la CPU. **Nunca exige NVIDIA.**

``whisper.cpp`` se evaluó como alternativa (CPU, CUDA o Vulkan) y se descartó por ahora: exige
compilar o descargar binarios por plataforma y su alineación por palabra es menos precisa que
la DTW sobre la atención cruzada que ya usan los otros dos motores.

En un Mac con Apple Silicon, ``faster-whisper`` solo se ofrece si se pide expresamente con
``VSA_ASR_ENGINES=faster-whisper`` (sirve para validar en un Mac el motor que usa Windows).
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from app.platform.detect import detect


@dataclass(frozen=True)
class Engine:
    id: str
    name: str
    implemented: bool
    available: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _forced() -> set[str]:
    return {e.strip() for e in os.environ.get("VSA_ASR_ENGINES", "").split(",") if e.strip()}


def engines() -> list[Engine]:
    info = detect()
    forced = _forced()
    mlx_ok = info.apple_silicon and importlib.util.find_spec("mlx_whisper") is not None
    fw_installed = importlib.util.find_spec("faster_whisper") is not None
    if forced:
        mlx_ok = mlx_ok and "mlx-whisper" in forced
    fw_ok = fw_installed and ("faster-whisper" in forced if (forced or mlx_ok) else True)
    if not fw_installed:
        fw_reason = "No instalado (ejecuta el instalador de nuevo)"
    elif fw_ok:
        fw_reason = f"Disponible ({describe_device()})"
    else:
        fw_reason = "Disponible como alternativa; en este Mac se usa MLX (más rápido)"
    return [
        Engine(
            "mlx-whisper",
            "MLX Whisper (Apple Silicon)",
            True,
            mlx_ok,
            "Disponible" if mlx_ok else "Requiere un Mac con Apple Silicon",
        ),
        Engine("faster-whisper", "faster-whisper (CPU; CUDA opcional)", True, fw_ok, fw_reason),
    ]


def active() -> Engine | None:
    return next((e for e in engines() if e.available), None)


@lru_cache(maxsize=1)
def cuda_devices() -> int:
    """GPU CUDA utilizables por CTranslate2 (0 si no hay NVIDIA o faltan sus bibliotecas)."""
    if detect().os == "macos":
        return 0
    try:
        import ctranslate2

        return int(ctranslate2.get_cuda_device_count())
    except Exception:  # sin CUDA o bibliotecas incompletas: CPU
        return 0


def preferred_device() -> tuple[str, str]:
    """Dispositivo y tipo de cálculo para faster-whisper: ``VSA_ASR_DEVICE`` = auto|cpu|cuda."""
    wanted = os.environ.get("VSA_ASR_DEVICE", "auto").lower()
    if wanted == "cuda" or (wanted == "auto" and cuda_devices() > 0):
        return "cuda", "float16"
    return "cpu", "int8"


def describe_device() -> str:
    device, compute = preferred_device()
    if device == "cuda":
        return f"GPU NVIDIA con CUDA, {compute}"
    return f"CPU, {compute}"
