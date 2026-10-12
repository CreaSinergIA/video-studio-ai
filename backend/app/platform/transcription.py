"""Motores de transcripción local disponibles según la plataforma.

Implementado: ``mlx-whisper`` (Apple Silicon). Previstos para Windows/Linux (siguiente fase,
aún NO implementados): ``faster-whisper`` (CTranslate2; CPU por defecto, CUDA opcional) y
``whisper.cpp`` (CPU, CUDA o Vulkan). Ninguno exige una GPU NVIDIA.
"""

from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
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


def engines() -> list[Engine]:
    info = detect()
    mlx_ok = info.apple_silicon and importlib.util.find_spec("mlx_whisper") is not None
    return [
        Engine(
            "mlx-whisper",
            "MLX Whisper (Apple Silicon)",
            True,
            mlx_ok,
            "Disponible" if mlx_ok else "Requiere un Mac con Apple Silicon",
        ),
        Engine(
            "faster-whisper",
            "faster-whisper (CPU; CUDA opcional)",
            False,
            False,
            "Pendiente de implementación (Windows/Linux, siguiente fase)",
        ),
        Engine(
            "whisper.cpp",
            "whisper.cpp (CPU, CUDA o Vulkan)",
            False,
            False,
            "Alternativa en evaluación para Windows (siguiente fase)",
        ),
    ]


def active() -> Engine | None:
    return next((e for e in engines() if e.available), None)
