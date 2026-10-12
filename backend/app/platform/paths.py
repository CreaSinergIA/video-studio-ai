"""Rutas de datos de la aplicación por sistema operativo."""

from __future__ import annotations

import os
from pathlib import Path

from app.edition import DATA_DIR_NAME
from app.platform.detect import os_id


def default_data_dir() -> Path:
    """Directorio de datos de esta edición (siempre en el disco del sistema).

    - macOS: ``~/Library/Application Support/<edición>``
    - Windows: ``%LOCALAPPDATA%\\<edición>`` (datos locales, no se sincronizan con el perfil)
    - Linux: ``$XDG_DATA_HOME/<edición>`` o ``~/.local/share/<edición>``
    """
    system = os_id()
    if system == "macos":
        return Path.home() / "Library" / "Application Support" / DATA_DIR_NAME
    if system == "windows":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / DATA_DIR_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / DATA_DIR_NAME.lower()
