"""Integración con el sistema operativo: selectores nativos y «Mostrar en Finder».

El navegador no expone rutas reales de archivos; como el backend corre en la misma máquina,
puede abrir el selector nativo de macOS (AppleScript). En otros sistemas se devuelve
``supported=False`` y el panel usa el explorador integrado o el arrastre de archivos.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_DIALOG_TIMEOUT = 15 * 60


def native_dialogs_supported() -> bool:
    return sys.platform == "darwin"


def _osascript(lines: list[str]) -> str | None:
    args = ["osascript"]
    for line in lines:
        args += ["-e", line]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=_DIALOG_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Selector nativo no disponible: %s", exc)
        return None
    if proc.returncode != 0:
        # -128 = el usuario canceló
        if "-128" not in proc.stderr:
            log.warning("osascript falló: %s", proc.stderr.strip())
        return None
    return proc.stdout.strip()


def _as_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def pick_folder(prompt: str, start: str | None = None) -> str | None:
    location = ""
    if start and Path(start).is_dir():
        location = f" default location (POSIX file {_as_string(start)})"
    out = _osascript(
        [
            "activate",
            f"set chosen to choose folder with prompt {_as_string(prompt)}{location}",
            "POSIX path of chosen",
        ]
    )
    return out.rstrip("/") or None if out else None


def pick_video_files(prompt: str) -> list[str]:
    out = _osascript(
        [
            "activate",
            "set chosen to choose file with prompt "
            f'{_as_string(prompt)} of type {{"public.mpeg-4", "com.apple.quicktime-movie"}} '
            "with multiple selections allowed",
            'set out to ""',
            "repeat with f in chosen",
            "set out to out & POSIX path of f & linefeed",
            "end repeat",
            "out",
        ]
    )
    if not out:
        return []
    return [line for line in out.splitlines() if line.strip()]


def reveal_in_file_manager(path: Path) -> bool:
    try:
        if sys.platform == "darwin":
            subprocess.run(["open", "-R", str(path)], check=True, timeout=10)
        elif sys.platform.startswith("linux"):
            subprocess.run(["xdg-open", str(path.parent)], check=True, timeout=10)
        else:
            return False
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("No se pudo mostrar %s: %s", path, exc)
        return False
