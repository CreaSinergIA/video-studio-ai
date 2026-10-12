"""Detección de capacidades del equipo (sin efectos secundarios)."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any


@dataclass(frozen=True)
class PlatformInfo:
    os: str  # macos | windows | linux
    arch: str  # arm64 | x86_64 | …
    apple_silicon: bool
    nvidia_gpu: str | None  # nombre de la GPU NVIDIA si nvidia-smi responde
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def os_id() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    return "linux"


def _nvidia() -> str | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=5, check=True,
        ).stdout.strip()  # fmt: skip
    except (subprocess.SubprocessError, OSError):
        return None
    return out.splitlines()[0] if out else None


@lru_cache(maxsize=1)
def detect() -> PlatformInfo:
    arch = platform.machine().lower()
    arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(arch, arch)
    os_ = os_id()
    notes: list[str] = []
    if os_ == "windows":
        notes.append(
            "Windows: adaptaciones implementadas (faster-whisper, Administrador de credenciales, "
            "lanzador, navegador de render win64); la validación en un equipo Windows real está "
            "pendiente."
        )
    return PlatformInfo(
        os=os_,
        arch=arch,
        apple_silicon=os_ == "macos" and arch == "arm64",
        nvidia_gpu=_nvidia(),
        notes=notes,
    )
