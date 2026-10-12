"""Catálogo y gestión de modelos locales de transcripción (MLX Whisper).

- Los modelos se descargan **solo** por acción explícita del usuario (botón en Ajustes).
- Fuente: Hugging Face (organización ``mlx-community``), revisión fijada por commit.
- Cada archivo se verifica con su SHA-256 publicado; si no coincide, se descarta.
- Se guardan en el disco interno (``<VSA_HOME>/models/asr/<id>``): la carga es rápida y no
  dependen de que el disco externo esté conectado. Después funcionan sin conexión.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import shutil
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)

HF_BASE = "https://huggingface.co"
MANIFEST = "vsa-model.json"


@dataclass(frozen=True)
class ModelFile:
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    description: str
    repo: str
    revision: str
    files: tuple[ModelFile, ...]
    recommended: bool = False

    @property
    def size_bytes(self) -> int:
        return sum(f.size for f in self.files)


# Medidas propias en Apple M4 (ver Obsidian → Pruebas y Validaciones · Fase 2).
CATALOG: dict[str, ModelSpec] = {
    "large-v3-turbo": ModelSpec(
        id="large-v3-turbo",
        name="Whisper large-v3-turbo",
        description=(
            "Recomendado. Máxima precisión probada en español e inglés; ~7× más rápido que el "
            "tiempo real en Apple M4. Usa ~1,5–2 GB de memoria durante la transcripción."
        ),
        repo="mlx-community/whisper-large-v3-turbo",
        revision="a4aaeec0636e6fef84abdcbe3544cb2bf7e9f6fb",
        files=(
            ModelFile(
                "config.json",
                268,
                "b34fc29e4e11e0a25e812775dd67f4dd16fc2c8eb43d28ae25ff7d660ecb6379",
            ),
            ModelFile(
                "weights.safetensors",
                1613977612,
                "951ed3fc1203e6a62467abb2144a96ce7eafca8fa77e3704fdb8635ff3e7f8a6",
            ),
        ),
        recommended=True,
    ),
    "large-v3-turbo-q4": ModelSpec(
        id="large-v3-turbo-q4",
        name="Whisper large-v3-turbo (4 bits)",
        description=(
            "Ligero: un tercio del tamaño y menos memoria (~0,8 GB). En nuestras pruebas igualó "
            "la precisión del modelo completo; puede fallar más en audio difícil."
        ),
        repo="mlx-community/whisper-large-v3-turbo-q4",
        revision="660c343bbf4e52ac257f0b7d952e5388e6f93bef",
        files=(
            ModelFile(
                "config.json",
                341,
                "538e24557b8f9bc504700add5e7bbe32087c2353001ff563e64772ad4398671a",
            ),
            ModelFile(
                "weights.npz",
                463664664,
                "862bbc832b05f3f4ec19dd632b701d61a6d3f5c7906360a10d72a79870642a80",
            ),
        ),
    ),
}


class ModelError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def models_root() -> Path:
    return get_settings().models_dir / "asr"


def model_dir(model_id: str) -> Path:
    return models_root() / model_id


def get_spec(model_id: str) -> ModelSpec:
    spec = CATALOG.get(model_id)
    if spec is None:
        raise ModelError("model_unknown", f"Modelo desconocido: {model_id}", 404)
    return spec


def platform_supported() -> bool:
    import platform
    import sys

    return sys.platform == "darwin" and platform.machine() == "arm64"


def is_installed(model_id: str) -> bool:
    spec = get_spec(model_id)
    directory = model_dir(model_id)
    manifest = directory / MANIFEST
    if not manifest.is_file():
        return False
    return all(
        (directory / f.name).is_file() and (directory / f.name).stat().st_size == f.size
        for f in spec.files
    )


def installed_path(model_id: str) -> Path:
    if not is_installed(model_id):
        spec = get_spec(model_id)
        raise ModelError(
            "model_missing",
            f"El modelo «{spec.name}» no está instalado. Descárgalo en Ajustes → Transcripción.",
        )
    return model_dir(model_id)


def describe(model_id: str) -> dict[str, Any]:
    spec = get_spec(model_id)
    manifest: dict[str, Any] = {}
    with contextlib.suppress(OSError, ValueError):
        manifest = json.loads((model_dir(model_id) / MANIFEST).read_text())
    return {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "repo": spec.repo,
        "revision": spec.revision,
        "size_bytes": spec.size_bytes,
        "recommended": spec.recommended,
        "installed": is_installed(model_id),
        "downloaded_at": manifest.get("downloaded_at"),
        "path": str(model_dir(model_id)),
        "source_url": f"{HF_BASE}/{spec.repo}/tree/{spec.revision}",
    }


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def download(
    model_id: str,
    on_progress: Callable[[float, str], None] | None = None,
    cancel: Event | None = None,
) -> Path:
    """Descarga y verifica un modelo. Escribe en una carpeta temporal y la publica al final."""
    from app.services.media_tools import Cancelled
    from app.services.storage import disk_usage

    spec = get_spec(model_id)
    root = models_root()
    root.mkdir(parents=True, exist_ok=True)  # disco interno (directorio de datos de la app)
    free, _ = disk_usage(root)
    if spec.size_bytes + 1024**3 > free:
        raise ModelError(
            "insufficient_space",
            f"Se necesitan {spec.size_bytes / 1e9:.1f} GB (+1 GB de margen) en el disco interno.",
            507,
        )
    staging = root / f".{model_id}.download"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    total = spec.size_bytes
    done = 0
    try:
        for f in spec.files:
            url = f"{HF_BASE}/{spec.repo}/resolve/{spec.revision}/{f.name}"
            dest = staging / f.name
            digest = hashlib.sha256()
            req = urllib.request.Request(url, headers={"User-Agent": "VideoStudioAI/0.2"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    block = resp.read(4 * 1024 * 1024)
                    if not block:
                        break
                    out.write(block)
                    digest.update(block)
                    done += len(block)
                    if on_progress:
                        on_progress(min(0.99, done / total), f"Descargando {f.name}")
            if digest.hexdigest() != f.sha256 or dest.stat().st_size != f.size:
                raise ModelError(
                    "checksum_mismatch",
                    f"La huella de {f.name} no coincide con la publicada; descarga descartada.",
                    502,
                )
        manifest = {
            "id": spec.id,
            "repo": spec.repo,
            "revision": spec.revision,
            "files": [{"name": f.name, "size": f.size, "sha256": f.sha256} for f in spec.files],
            "downloaded_at": datetime.now(UTC).isoformat(),
            "verified": True,
        }
        (staging / MANIFEST).write_text(json.dumps(manifest, indent=2))
        final = model_dir(model_id)
        shutil.rmtree(final, ignore_errors=True)
        os.replace(staging, final)
        log.info("Modelo %s descargado y verificado en %s", model_id, final)
        if on_progress:
            on_progress(1.0, "Modelo verificado")
        return final
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def verify(model_id: str) -> bool:
    spec = get_spec(model_id)
    directory = installed_path(model_id)
    return all(_sha256(directory / f.name) == f.sha256 for f in spec.files)


def delete(model_id: str) -> None:
    get_spec(model_id)
    shutil.rmtree(model_dir(model_id), ignore_errors=True)
