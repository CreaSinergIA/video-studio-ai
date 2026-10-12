"""Ciclo de vida de la instancia: identificación, archivo de instancia y cierre ordenado.

- ``run/instance.json`` describe la instancia en marcha (PID, puerto, versión). Lo usa el
  lanzador para no arrancar otra copia y para encontrar el puerto real.
- ``run/server.lock`` impide que dos servidores usen la misma carpeta de datos a la vez.
- ``request_shutdown`` detiene uvicorn de forma ordenada (la cola de tareas cancela sus
  procesos hijos antes de salir).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import IO, Any

SERVER: Any = None  # uvicorn.Server cuando se arranca con run.py
_LOCK: IO[str] | None = None


def instance_id(home: Path) -> str:
    """Identificador estable de la instalación (la carpeta de datos), sin revelar la ruta."""
    return hashlib.sha256(str(home.resolve()).encode()).hexdigest()[:16]


def run_dir(home: Path) -> Path:
    return home / "run"


def instance_file(home: Path) -> Path:
    return run_dir(home) / "instance.json"


def acquire_lock(home: Path) -> bool:
    """Bloqueo exclusivo de la carpeta de datos (se libera solo al morir el proceso)."""
    global _LOCK
    run_dir(home).mkdir(parents=True, exist_ok=True)
    fh = open(run_dir(home) / "server.lock", "a+", encoding="utf-8")  # noqa: SIM115
    try:
        if sys.platform == "win32":
            import msvcrt

            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    _LOCK = fh
    return True


def write_instance(home: Path, port: int, version: str) -> None:
    data = {
        "pid": os.getpid(),
        "port": port,
        "url": f"http://127.0.0.1:{port}",
        "version": version,
        "instance": instance_id(home),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    path = instance_file(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def clear_instance(home: Path) -> None:
    with contextlib.suppress(OSError):
        data = json.loads(instance_file(home).read_text(encoding="utf-8"))
        if data.get("pid") == os.getpid():
            instance_file(home).unlink()


def request_shutdown() -> bool:
    if SERVER is None:
        return False
    SERVER.should_exit = True
    return True
