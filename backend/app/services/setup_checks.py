"""Comprobaciones del equipo y de la instalación.

Las usan el instalador (``app.installer``), el diagnóstico (``videostudio doctor``) y la
primera configuración del panel (``GET /api/setup/status``). No modifican nada.
"""

from __future__ import annotations

import contextlib
import json
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.platform import detect, tools

REPO_DIR = Path(__file__).resolve().parents[3]
MIN_FREE_BYTES = 6 * 1024**3  # dependencias, motor de render y un modelo de transcripción
RECOMMENDED_RAM = 8 * 1024**3
REQUIRED_ENCODERS = ("libx264", "aac")


@dataclass
class Check:
    id: str
    label: str
    status: str  # ok | warning | error | missing
    detail: str = ""
    fix: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def total_memory() -> int | None:
    with contextlib.suppress(Exception):
        import psutil

        return int(psutil.virtual_memory().total)
    return None


def platform_check() -> Check:
    info = detect()
    system = f"{platform.system()} {platform.release()} ({info.arch})"
    if info.os == "macos":
        if info.arch == "arm64":
            return Check("platform", "Sistema", "ok", f"macOS con Apple Silicon · {system}")
        return Check(
            "platform",
            "Sistema",
            "warning",
            f"Mac con procesador Intel · {system}",
            "Compatible en principio (transcripción en la CPU), pero no validado.",
        )
    if info.os == "windows":
        if info.arch == "x86_64":
            return Check("platform", "Sistema", "ok", f"Windows x64 · {system}")
        return Check(
            "platform",
            "Sistema",
            "error",
            f"Windows en ARM · {system}",
            "Windows en ARM no es compatible todavía (el motor de render solo existe para x64).",
        )
    return Check(
        "platform", "Sistema", "warning", system, "Linux no está validado; puede funcionar."
    )


def resources_check(home: Path) -> Check:
    ram = total_memory()
    target = home if home.exists() else home.parent
    while not target.exists() and target != target.parent:
        target = target.parent
    free = shutil.disk_usage(target).free
    detail = f"{(ram or 0) / 1024**3:.0f} GB de memoria · {free / 1024**3:.0f} GB libres"
    if free < MIN_FREE_BYTES:
        return Check(
            "resources",
            "Memoria y disco",
            "error",
            detail,
            f"Se necesitan al menos {MIN_FREE_BYTES / 1024**3:.0f} GB libres en el disco del "
            "sistema para dependencias y modelos (los videos van a la carpeta que elijas).",
        )
    if ram is not None and ram < RECOMMENDED_RAM:
        return Check(
            "resources",
            "Memoria y disco",
            "warning",
            detail,
            "Con menos de 8 GB de memoria la transcripción y el render serán lentos; usa el "
            "modelo de transcripción ligero.",
        )
    return Check("resources", "Memoria y disco", "ok", detail)


def _ffmpeg_info(binary: str) -> dict[str, Any] | None:
    try:
        version = subprocess.run(
            [binary, "-hide_banner", "-version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        encoders = subprocess.run(
            [binary, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if version.returncode != 0:
        return None
    first = version.stdout.splitlines()[0] if version.stdout else ""
    names = {
        parts[1]
        for line in encoders.stdout.splitlines()
        if len(parts := line.split()) >= 2 and len(parts[0]) == 6
    }
    return {"version": first.replace("ffmpeg version ", "").split(" ")[0], "encoders": names}


def ffmpeg_check() -> Check:
    settings = get_settings()
    path = shutil.which(settings.ffmpeg) or settings.ffmpeg
    probe = shutil.which(settings.ffprobe) or settings.ffprobe
    data = _ffmpeg_info(path) if Path(path).exists() or shutil.which(path) else None
    portable = tools.installed_executable(settings.home, "ffmpeg") is not None
    if data is None or not (Path(probe).exists() or shutil.which(probe)):
        return Check(
            "ffmpeg",
            "FFmpeg",
            "missing",
            "No se encontró FFmpeg/ffprobe.",
            "El instalador puede descargar una copia portátil verificada (sin instalar nada "
            "en el sistema).",
        )
    missing = [e for e in REQUIRED_ENCODERS if e not in data["encoders"]]
    source = "copia portátil" if portable else "del sistema"
    detail = f"{data['version']} ({source}) · {path}"
    if missing:
        return Check(
            "ffmpeg",
            "FFmpeg",
            "error",
            detail,
            f"A esta compilación le faltan codificadores: {', '.join(missing)}. Usa la copia "
            "portátil del instalador.",
            {"path": path, "version": data["version"]},
        )
    hw = sorted(
        e for e in data["encoders"] if e.endswith(("_videotoolbox", "_nvenc", "_qsv", "_amf"))
    )
    return Check(
        "ffmpeg", "FFmpeg", "ok", detail, "", {"path": path, "version": data["version"], "hw": hw}
    )


def node_check() -> Check:
    from app.services import render_engine

    node = render_engine.find_node()
    if node is None:
        return Check(
            "node",
            "Node.js",
            "missing",
            f"No hay Node.js {'.'.join(map(str, tools.NODE_MIN))} o superior.",
            "El instalador puede descargar Node.js LTS portátil (sin instalar nada en el sistema).",
        )
    version = tools.node_version(node)
    return Check(
        "node",
        "Node.js",
        "ok",
        f"v{'.'.join(map(str, version or ()))} · {node}",
        data={"path": str(node)},
    )


def lock_hash(directory: Path) -> str:
    import hashlib

    lock = directory / "package-lock.json"
    return hashlib.sha256(lock.read_bytes()).hexdigest()[:16] if lock.is_file() else ""


def node_modules_current(directory: Path) -> bool:
    marker = directory / "node_modules" / ".vsa-lock"
    with contextlib.suppress(OSError):
        return marker.read_text(encoding="utf-8").strip() == lock_hash(directory)
    return False


def panel_check() -> Check:
    frontend = REPO_DIR / "frontend"
    dist = get_settings().frontend_dist or frontend / "dist"
    if not node_modules_current(frontend) and not (frontend / "node_modules").is_dir():
        return Check("panel", "Panel", "missing", "Dependencias del panel sin instalar.")
    if not (dist / "index.html").is_file():
        return Check("panel", "Panel", "missing", "El panel no está compilado.")
    return Check("panel", "Panel", "ok", f"Compilado en {dist}")


def remotion_check() -> Check:
    from app.services import render_engine

    st = render_engine.status()
    remotion = st["remotion"]
    if remotion["installed"] != remotion["expected"]:
        return Check(
            "remotion",
            "Remotion (animaciones)",
            "missing",
            f"Remotion {remotion['expected']} no está instalado en renderer/.",
            "Lo instala el instalador con npm (dependencia local del proyecto).",
        )
    browser = st["browser"]
    if not browser["installed"]:
        return Check(
            "remotion",
            "Remotion (animaciones)",
            "warning",
            f"Remotion {remotion['installed']} listo · falta el navegador de render "
            f"(~{browser['download_bytes'] / 1e6:.0f} MB).",
            "Instálalo desde el instalador o en Ajustes → Animaciones.",
        )
    return Check(
        "remotion",
        "Remotion (animaciones)",
        "ok",
        f"Remotion {remotion['installed']} · navegador {browser['version']}",
    )


def transcription_check() -> Check:
    from app.platform import transcription
    from app.services import asr_models

    engine = transcription.active()
    if engine is None:
        return Check(
            "transcription",
            "Transcripción local",
            "error",
            "No hay ningún motor de transcripción disponible.",
            "Ejecuta el instalador de nuevo.",
        )
    installed = [m for m in asr_models.available_ids() if asr_models.is_installed(m)]
    if not installed:
        spec = asr_models.get_spec(asr_models.default_model_id())
        return Check(
            "transcription",
            "Transcripción local",
            "warning",
            f"Motor {engine.name} · ningún modelo descargado.",
            f"Descarga «{spec.name}» ({spec.size_bytes / 1e9:.1f} GB) en el instalador o en "
            "Ajustes → Transcripción.",
            {"engine": engine.id},
        )
    names = ", ".join(asr_models.get_spec(m).name for m in installed)
    return Check(
        "transcription",
        "Transcripción local",
        "ok",
        f"{engine.name} · {names}",
        data={"engine": engine.id, "models": installed},
    )


def credentials_check() -> Check:
    from app.services import claude_client

    try:
        saved = claude_client.keychain_has_key()
    except Exception as exc:  # llavero no disponible
        return Check("claude", "Conexión con Claude", "warning", str(exc))
    label = claude_client.keychain_label()
    if not saved:
        return Check(
            "claude",
            "Conexión con Claude",
            "warning",
            f"Sin clave de API (se guardará en {label}).",
            "Configúrala en el panel: Ajustes → Claude. Es opcional para transcribir y editar.",
        )
    return Check("claude", "Conexión con Claude", "ok", f"Clave guardada en {label}.")


def all_checks() -> list[Check]:
    settings = get_settings()
    return [
        platform_check(),
        resources_check(settings.home),
        ffmpeg_check(),
        node_check(),
        panel_check(),
        remotion_check(),
        transcription_check(),
        credentials_check(),
    ]


def summary() -> dict[str, Any]:
    checks = [c.as_dict() for c in all_checks()]
    return {"checks": checks, "ready": all(c["status"] != "error" for c in checks)}


def dump(checks: list[Check]) -> str:
    return json.dumps([c.as_dict() for c in checks], ensure_ascii=False, indent=2)
