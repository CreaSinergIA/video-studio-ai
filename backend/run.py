"""Arranca el servidor local (solo 127.0.0.1).

Uso normal: el lanzador (``./videostudio start`` en macOS, ``Video Studio AI.cmd`` en
Windows), que se ocupa de la instancia única, el puerto y el navegador. Este archivo:

- impide dos servidores sobre la misma carpeta de datos (bloqueo exclusivo);
- en Windows, asocia el servidor a un Job Object para que ningún proceso hijo quede huérfano;
- sale con un código distinto si el puerto está ocupado (3) o ya hay otra instancia (4).
"""

from __future__ import annotations

import socket
import sys

import uvicorn

from app import lifecycle
from app.config import get_settings
from app.platform import processes

EXIT_PORT_BUSY = 3
EXIT_ALREADY_RUNNING = 4


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Igual que uvicorn: en POSIX se ignoran las conexiones en TIME_WAIT de un servidor
        # anterior. En Windows SO_REUSEADDR permitiría compartir el puerto: no se usa.
        if sys.platform != "win32":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def main() -> int:
    # Salida en UTF-8 aunque la consola de Windows use otra página de códigos.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    settings = get_settings()
    if not lifecycle.acquire_lock(settings.home):
        print(f"Ya hay un servidor de Video Studio AI usando {settings.home}.", file=sys.stderr)
        return EXIT_ALREADY_RUNNING
    if not _port_free(settings.host, settings.port):
        print(f"El puerto {settings.port} está ocupado por otro programa.", file=sys.stderr)
        return EXIT_PORT_BUSY
    processes.bind_children_to_lifetime()
    config = uvicorn.Config(
        "app.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=False,
        timeout_graceful_shutdown=10,
    )
    server = uvicorn.Server(config)
    lifecycle.SERVER = server
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
