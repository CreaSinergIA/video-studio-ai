"""Procesos hijos que se pueden terminar con todo su árbol (render, Claude Code de pruebas).

- POSIX (macOS/Linux): nueva sesión y señales al grupo (SIGTERM y, si no sale, SIGKILL).
- Windows: nuevo grupo de procesos y ``taskkill /T`` (árbol completo). Implementado pero aún
  no validado en Windows.
"""

from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import sys
from typing import Any

WINDOWS = sys.platform == "win32"


def group_kwargs() -> dict[str, Any]:
    """Argumentos de ``subprocess.Popen`` para poder terminar el árbol completo."""
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]
    return {"start_new_session": True}


def terminate_tree(proc: subprocess.Popen[Any], grace: float = 5.0) -> None:
    """Termina el proceso y sus hijos: primero con amabilidad y, si no sale, a la fuerza."""
    if WINDOWS:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T"], capture_output=True, timeout=10
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=grace)
        if proc.poll() is None:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                )
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGTERM)
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=grace)
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)
