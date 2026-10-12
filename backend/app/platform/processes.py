"""Procesos hijos que se pueden terminar con todo su árbol y que nunca quedan huérfanos.

- **Terminar el árbol** (render, transcripción, FFmpeg, Claude Code de pruebas):
  - POSIX (macOS/Linux): nueva sesión y señales al grupo (SIGTERM y, si no sale, SIGKILL).
  - Windows: nuevo grupo de procesos y ``taskkill /T`` (árbol completo).
- **Sin huérfanos si el servidor muere de golpe:**
  - Windows: el servidor se asocia a un *Job Object* con ``KILL_ON_JOB_CLOSE``; el sistema
    termina a todos sus descendientes cuando el servidor desaparece, aunque sea a la fuerza.
  - POSIX: cada hijo queda registrado (PID + instante de creación) en ``run/children.json``; al
    arrancar, el servidor termina los que sigan vivos de una ejecución anterior. El instante de
    creación garantiza que nunca se toca un proceso ajeno que reutilizó el PID.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

WINDOWS = sys.platform == "win32"

_registry_path: Path | None = None
_tracked: dict[int, float] = {}
_lock = threading.Lock()


def group_kwargs() -> dict[str, Any]:
    """Argumentos de ``subprocess.Popen`` para poder terminar el árbol completo."""
    if WINDOWS:
        return {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
            | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        }
    return {"start_new_session": True}


def terminate_tree(proc: subprocess.Popen[Any], grace: float = 5.0) -> None:
    """Termina el proceso y sus hijos: primero con amabilidad y, si no sale, a la fuerza."""
    if WINDOWS:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T"],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
            )
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=grace)
        if proc.poll() is None:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
                )
        return
    try:
        pgid = os.getpgid(proc.pid)
    except (ProcessLookupError, PermissionError):
        return
    # Solo se señala el grupo si es propio del hijo (creado con start_new_session).
    if pgid != os.getpgid(0):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, signal.SIGTERM)
    else:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            proc.terminate()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(timeout=grace)
    if proc.poll() is None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            if pgid != os.getpgid(0):
                os.killpg(pgid, signal.SIGKILL)
            else:
                proc.kill()


class TreeWatcher:
    """Recuerda todos los descendientes de un proceso mientras vive y, al terminar, cierra los
    que sigan vivos.

    Hace falta porque algunos hijos se separan del grupo de procesos (el navegador de render
    que lanza Remotion crea su propio grupo): si el proceso padre termina o se cancela, una
    señal al grupo no los alcanza y quedarían huérfanos. ``psutil`` identifica cada proceso por
    PID **y** hora de creación, así que nunca se toca un proceso ajeno que reutilice un PID.
    """

    def __init__(self, proc: subprocess.Popen[Any]) -> None:
        import psutil

        self._psutil = psutil
        self.seen: dict[int, Any] = {}
        try:
            self.root: Any = psutil.Process(proc.pid)
        except psutil.Error:
            self.root = None

    def snapshot(self) -> None:
        if self.root is None:
            return
        try:
            children = self.root.children(recursive=True)
        except self._psutil.Error:
            return
        new = [c for c in children if c.pid not in self.seen]
        for c in new:
            self.seen[c.pid] = c
        if new:
            _register_extra([(c.pid, c.create_time()) for c in new if _safe(c)])

    def reap(self, timeout: float = 3.0) -> int:
        psutil = self._psutil
        alive = [p for p in self.seen.values() if _safe(p) and p.is_running()]
        for p in alive:
            with contextlib.suppress(psutil.Error):
                p.terminate()
        _, rest = psutil.wait_procs(alive, timeout=timeout)
        for p in rest:
            with contextlib.suppress(psutil.Error):
                p.kill()
        _unregister_extra(list(self.seen))
        if alive:
            log.info("Se cerraron %d procesos que habían quedado del render", len(alive))
        return len(alive)


def _safe(p: Any) -> bool:
    try:
        p.create_time()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Registro de hijos (POSIX) y Job Object (Windows)
# ---------------------------------------------------------------------------


def _create_time(pid: int) -> float | None:
    try:
        import psutil

        return float(psutil.Process(pid).create_time())
    except Exception:
        return None


def _save() -> None:
    if _registry_path is None:
        return
    with contextlib.suppress(OSError):
        tmp = _registry_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps([{"pid": p, "created": c} for p, c in _tracked.items()]), encoding="utf-8"
        )
        os.replace(tmp, _registry_path)


def track(proc: subprocess.Popen[Any]) -> None:
    """Registra un hijo de larga duración para poder recogerlo si el servidor muere."""
    created = _create_time(proc.pid)
    if created is None:
        return
    with _lock:
        _tracked[proc.pid] = created
        _save()


def untrack(proc: subprocess.Popen[Any]) -> None:
    with _lock:
        if _tracked.pop(proc.pid, None) is not None:
            _save()


def _register_extra(items: list[tuple[int, float]]) -> None:
    """Nietos (p. ej. el navegador de render) también se registran: si el servidor muere de
    golpe, el siguiente arranque los cierra aunque su proceso padre ya no exista."""
    with _lock:
        for pid, created in items:
            _tracked[pid] = created
        _save()


def _unregister_extra(pids: list[int]) -> None:
    with _lock:
        changed = False
        for pid in pids:
            changed |= _tracked.pop(pid, None) is not None
        if changed:
            _save()


def reap_orphans(run_dir: Path) -> int:
    """Al arrancar: termina los hijos que sobrevivieron a una ejecución anterior (y sus
    descendientes) y empieza un registro nuevo. Devuelve cuántos terminó."""
    global _registry_path
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "children.json"
    killed = 0
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        entries = []
    import psutil

    for entry in entries:
        try:
            p = psutil.Process(int(entry["pid"]))
            # Mismo PID y mismo instante de creación: es nuestro, no un proceso reutilizado.
            if abs(p.create_time() - float(entry["created"])) > 0.01:
                continue
            procs = [*p.children(recursive=True), p]
            for q in procs:
                with contextlib.suppress(psutil.Error):
                    q.terminate()
            _, alive = psutil.wait_procs(procs, timeout=3)
            for q in alive:
                with contextlib.suppress(psutil.Error):
                    q.kill()
            killed += 1
        except (psutil.Error, KeyError, ValueError, TypeError):
            continue
    if killed:
        log.warning("Se terminaron %d procesos huérfanos de una ejecución anterior", killed)
    with _lock:
        _registry_path = path
        _tracked.clear()
        _save()
    return killed


def bind_children_to_lifetime() -> bool:
    """Windows: asocia este proceso a un Job Object que termina a todos sus descendientes
    cuando el servidor se cierra, aunque sea de forma abrupta. No hace nada en POSIX."""
    if not WINDOWS:
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]

        class IoCounters(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_ulonglong)
                for name in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimit),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job_object_limit_kill_on_job_close = 0x2000
        job_object_extended_limit_information = 9
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return False
        info = ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = job_object_limit_kill_on_job_close
        if not kernel32.SetInformationJobObject(
            job, job_object_extended_limit_information, ctypes.byref(info), ctypes.sizeof(info)
        ):
            return False
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
            return False
        # El identificador se conserva abierto mientras viva el proceso: al cerrarse (también
        # por un cierre forzado), Windows termina todos los procesos del trabajo.
        globals()["_JOB_HANDLE"] = job
        return True
    except Exception:
        log.exception("No se pudo crear el Job Object de Windows")
        return False
