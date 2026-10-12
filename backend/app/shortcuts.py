"""Accesos directos para abrir el editor sin terminal ni Claude Code.

- **macOS:** una pequeña aplicación ``~/Applications/Video Studio AI.app`` que ejecuta el
  lanzador del repositorio (se puede arrastrar al Dock).
- **Windows:** accesos ``Video Studio AI`` en el Escritorio y en el menú Inicio, y
  ``Cerrar Video Studio AI`` en el menú Inicio. Ejecutan ``videostudio.ps1`` sin ventana.

Solo se crean con la confirmación del usuario y se pueden borrar sin efectos secundarios.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
NAME = "Video Studio AI"
BUNDLE_ID = "community.videostudioai.launcher"


def _mac_app() -> Path:
    return Path.home() / "Applications" / f"{NAME}.app"


def _win_locations() -> list[Path]:
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    start_menu = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / NAME
    desktop = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
    return [desktop, start_menu]


def describe() -> str | None:
    if sys.platform == "darwin":
        return str(_mac_app())
    if sys.platform == "win32":
        return " y ".join(str(p) for p in _win_locations())
    return None


def create() -> list[Path]:
    if sys.platform == "darwin":
        return [_create_mac()]
    if sys.platform == "win32":
        return _create_windows()
    return []


def _create_mac() -> Path:
    app = _mac_app()
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    launcher = REPO_DIR / "videostudio"
    script = macos / "VideoStudioAI"
    # Rutas citadas con printf %q: un repositorio en una ruta con espacios funciona igual.
    quoted = subprocess.run(
        ["/bin/bash", "-c", 'printf "%q" "$1"', "_", str(launcher)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    script.write_text(
        "#!/bin/bash\n"
        "# Acceso directo de Video Studio AI — Community Edition (creado por el instalador).\n"
        f"exec {quoted} start >/dev/null 2>&1\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    info = {
        "CFBundleName": NAME,
        "CFBundleDisplayName": NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "VideoStudioAI",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "LSUIElement": True,  # sin icono permanente en el Dock: solo abre el navegador
    }
    with open(app / "Contents" / "Info.plist", "wb") as fh:
        plistlib.dump(info, fh)
    return app


_PS_SHORTCUT = r"""
param([string]$Link, [string]$Target, [string]$Arguments, [string]$WorkDir, [string]$Description)
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($Link)
$s.TargetPath = $Target
$s.Arguments = $Arguments
$s.WorkingDirectory = $WorkDir
$s.Description = $Description
$s.WindowStyle = 7
$s.Save()
"""


def _create_windows() -> list[Path]:
    powershell = (
        Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    ps1 = REPO_DIR / "videostudio.ps1"
    created: list[Path] = []
    with tempfile.TemporaryDirectory() as tmp:
        helper = Path(tmp) / "shortcut.ps1"
        helper.write_text(_PS_SHORTCUT, encoding="utf-8-sig")
        desktop, start_menu = _win_locations()
        start_menu.mkdir(parents=True, exist_ok=True)
        items = [
            (desktop / f"{NAME}.lnk", "start", "Abre Video Studio AI"),
            (start_menu / f"{NAME}.lnk", "start", "Abre Video Studio AI"),
            (start_menu / f"Cerrar {NAME}.lnk", "stop", "Cierra Video Studio AI"),
        ]
        for link, command, description in items:
            if not link.parent.is_dir():
                continue
            args = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{ps1}" {command}'
            subprocess.run(
                [
                    str(powershell),
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(helper),
                    "-Link",
                    str(link),
                    "-Target",
                    str(powershell),
                    "-Arguments",
                    args,
                    "-WorkDir",
                    str(REPO_DIR),
                    "-Description",
                    description,
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            created.append(link)
    return created


def remove() -> list[Path]:
    removed: list[Path] = []
    if sys.platform == "darwin" and _mac_app().exists():
        import shutil

        shutil.rmtree(_mac_app())
        removed.append(_mac_app())
    elif sys.platform == "win32":
        desktop, start_menu = _win_locations()
        for link in (
            desktop / f"{NAME}.lnk",
            start_menu / f"{NAME}.lnk",
            start_menu / f"Cerrar {NAME}.lnk",
        ):
            if link.exists():
                link.unlink()
                removed.append(link)
    return removed
