"""Información del entorno local y estado de las capacidades (presentes y futuras)."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from typing import Any

from app import edition
from app.config import APP_VERSION, Settings
from app.db import check_integrity
from app.platform import detect
from app.platform.encoders import diagnose as encoder_diagnose
from app.platform.transcription import engines as transcription_engines
from app.services import asr_models
from app.services.media_tools import available_encoders, binary_version
from app.services.native import native_dialogs_supported


def _total_memory() -> int | None:
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
            )
            return int(out.stdout.strip())
        if hasattr(os, "sysconf"):
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


def _cpu_name() -> str:
    if sys.platform == "darwin":
        try:
            out = subprocess.run(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return platform.processor() or platform.machine()


def _os_name() -> str:
    if sys.platform == "darwin":
        return f"macOS {platform.mac_ver()[0]}"
    return f"{platform.system()} {platform.release()}"


# Capacidades de fases futuras: se muestran como «No disponible», nunca simuladas.
FUTURE_CAPABILITIES: list[dict[str, Any]] = []


def _engine_ready() -> bool:
    try:
        from app.services import render_engine

        return bool(render_engine.status()["ready"])
    except Exception:
        return False


def collect(settings: Settings, log_file: str | None) -> dict[str, Any]:
    encoders = available_encoders(settings.ffmpeg)
    db_size = settings.db_path.stat().st_size if settings.db_path.exists() else 0
    return {
        "app": {
            "name": edition.PRODUCT_NAME,
            "edition": edition.EDITION_NAME,
            "creator": edition.CREATOR,
            "version": APP_VERSION,
            "phase": 5,
        },
        # Diagnóstico multiplataforma (Community Edition): qué está disponible en este equipo.
        "platform": {
            **detect().as_dict(),
            "transcription_engines": [e.as_dict() for e in transcription_engines()],
            "encoders": encoder_diagnose(encoders),
        },
        "os": _os_name(),
        "arch": platform.machine(),
        "cpu": _cpu_name(),
        "cpu_count": os.cpu_count(),
        "memory_bytes": _total_memory(),
        "python": platform.python_version(),
        "node": _node_version(),
        "ffmpeg": {
            "path": settings.ffmpeg,
            "version": binary_version(settings.ffmpeg),
            "ffprobe_path": settings.ffprobe,
            "ffprobe_version": binary_version(settings.ffprobe),
            "hardware_encoders": sorted(
                e
                for e in encoders
                if "videotoolbox" in e or "nvenc" in e or "vaapi" in e or "qsv" in e
            ),
            "has_libx264": "libx264" in encoders,
        },
        "paths": {
            "app_home": str(settings.home),
            "database": str(settings.db_path),
            "database_bytes": db_size,
            "logs": log_file,
        },
        "database": {"integrity": check_integrity()},
        "server": {"host": settings.host, "port": settings.port},
        "native_dialogs": native_dialogs_supported(),
        "capabilities": [
            {"id": "import", "name": "Importación MP4/MOV", "phase": 1, "available": True},
            {"id": "playback", "name": "Reproducción y proxies", "phase": 1, "available": True},
            {"id": "presets", "name": "Presets y personalización", "phase": 1, "available": True},
            {
                "id": "transcription",
                "name": "Transcripción local (MLX Whisper)",
                "phase": 2,
                "available": asr_models.platform_supported(),
            },
            {
                "id": "visual_analysis",
                "name": "Escenas, fotogramas y rostros",
                "phase": 2,
                "available": True,
            },
            {"id": "subtitles", "name": "Subtítulos sincronizados", "phase": 2, "available": True},
            {
                "id": "export",
                "name": "Exportación subtitulada (FFmpeg)",
                "phase": 2,
                "available": True,
            },
            {
                "id": "creative_director",
                "name": "Director creativo (Claude Opus 5.5)",
                "phase": 3,
                # Disponible si hay un medio de conexión (CLI de Claude Code o clave de API).
                # La conexión real se verifica en Ajustes → Claude.
                "available": _claude_available(),
            },
            {"id": "edit_plan", "name": "Plan de edición aprobable", "phase": 3, "available": True},
            {
                "id": "animations",
                "name": "Animaciones por código (Remotion + SVG)",
                "phase": 4,
                # Requiere el navegador de render (Ajustes → Animaciones).
                "available": _engine_ready(),
            },
            {"id": "sfx", "name": "Efectos de sonido", "phase": 4, "available": True},
            {
                "id": "safe_zones",
                "name": "Zonas seguras de redes sociales",
                "phase": 4,
                "available": True,
            },
            {
                "id": "scenes",
                "name": "Regeneración selectiva y versiones de escena",
                "phase": 5,
                "available": True,
            },
            {
                "id": "backups",
                "name": "Copias de seguridad verificadas",
                "phase": 5,
                "available": True,
            },
            *({**cap, "available": False} for cap in FUTURE_CAPABILITIES),
        ],
    }


def _claude_available() -> bool:
    from app.db import session_scope
    from app.services import app_settings, claude_client

    try:
        with session_scope() as s:
            prefs = app_settings.get_claude(s)
    except RuntimeError:
        return False
    if prefs.transport == "api":
        return claude_client.keychain_has_key()
    return claude_client.find_cli(prefs) is not None


def _node_version() -> str | None:
    node = shutil.which("node")
    if not node:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None
