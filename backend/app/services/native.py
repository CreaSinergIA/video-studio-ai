"""Integración con el sistema operativo: selectores nativos y «Mostrar en Finder/Explorador».

El navegador no expone rutas reales de archivos; como el backend corre en la misma máquina,
puede abrir el selector nativo:

- macOS: AppleScript. Los textos y rutas llegan como argumentos (``on run argv``), nunca
  interpolados en el código del script.
- Windows: diálogos de Windows Forms con PowerShell (parámetros con nombre, nunca
  interpolados). Implementado, pendiente de validar en Windows.

En otros sistemas se devuelve ``supported=False`` y el panel usa el explorador integrado.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

_DIALOG_TIMEOUT = 15 * 60


def native_dialogs_supported() -> bool:
    return sys.platform in ("darwin", "win32")


def _osascript(lines: list[str], argv: list[str]) -> str | None:
    args = ["osascript"]
    for line in ["on run argv", *lines, "end run"]:
        args += ["-e", line]
    args += argv
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_DIALOG_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        log.warning("Selector nativo no disponible: %s", exc)
        return None
    if proc.returncode != 0:
        # -128 = el usuario canceló
        if "-128" not in proc.stderr:
            log.warning("osascript falló: %s", proc.stderr.strip())
        return None
    return proc.stdout.strip()


_PS_FOLDER = r"""
param([string]$Prompt, [string]$Start)
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true; ShowInTaskbar = $false }
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = $Prompt
$d.ShowNewFolderButton = $true
if ($Start -and (Test-Path -LiteralPath $Start)) { $d.SelectedPath = $Start }
$ok = [System.Windows.Forms.DialogResult]::OK
if ($d.ShowDialog($owner) -eq $ok) { Write-Output $d.SelectedPath }
"""

_PS_FILES = r"""
param([string]$Prompt)
Add-Type -AssemblyName System.Windows.Forms
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$owner = New-Object System.Windows.Forms.Form -Property @{ TopMost = $true; ShowInTaskbar = $false }
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = $Prompt
$d.Filter = "Videos (*.mp4;*.mov)|*.mp4;*.mov"
$d.Multiselect = $true
$ok = [System.Windows.Forms.DialogResult]::OK
if ($d.ShowDialog($owner) -eq $ok) { $d.FileNames | ForEach-Object { Write-Output $_ } }
"""


def _powershell(script: str, params: list[str]) -> str | None:
    exe = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "WindowsPowerShell"
    exe = exe / "v1.0" / "powershell.exe"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "dialog.ps1"
        path.write_text(script, encoding="utf-8-sig")
        try:
            proc = subprocess.run(
                [str(exe), "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-File", str(path),
                 *params],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=_DIALOG_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )  # fmt: skip
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("Selector nativo no disponible: %s", exc)
            return None
    if proc.returncode != 0:
        log.warning("Selector de Windows falló: %s", proc.stderr.strip()[:300])
        return None
    return proc.stdout.strip()


def pick_folder(prompt: str, start: str | None = None) -> str | None:
    if sys.platform == "win32":
        out = _powershell(_PS_FOLDER, ["-Prompt", prompt, "-Start", start or ""])
        return out or None
    start_dir = start if start and Path(start).is_dir() else ""
    out = _osascript(
        [
            "activate",
            'if (item 2 of argv) is "" then',
            "set chosen to choose folder with prompt (item 1 of argv)",
            "else",
            "set chosen to choose folder with prompt (item 1 of argv) "
            "default location (POSIX file (item 2 of argv))",
            "end if",
            "return POSIX path of chosen",
        ],
        [prompt, start_dir],
    )
    return out.rstrip("/") or None if out else None


def pick_video_files(prompt: str) -> list[str]:
    if sys.platform == "win32":
        out = _powershell(_PS_FILES, ["-Prompt", prompt])
    else:
        out = _osascript(
            [
                "activate",
                "set chosen to choose file with prompt (item 1 of argv) "
                'of type {"public.mpeg-4", "com.apple.quicktime-movie"} '
                "with multiple selections allowed",
                'set out to ""',
                "repeat with f in chosen",
                "set out to out & POSIX path of f & linefeed",
                "end repeat",
                "return out",
            ],
            [prompt],
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
        elif sys.platform == "win32":  # pragma: no cover  (implementado; validar en Windows)
            # explorer.exe devuelve código 1 aunque funcione: no se comprueba el resultado.
            subprocess.run(["explorer", f"/select,{path}"], check=False, timeout=10)
        else:
            return False
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("No se pudo mostrar %s: %s", path, exc)
        return False
