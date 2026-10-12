"""Lanzador de Video Studio AI (macOS, Windows y Linux).

Lo invocan los lanzadores del sistema (``videostudio`` en macOS/Linux y ``videostudio.ps1`` /
``Video Studio AI.cmd`` en Windows), así que el usuario nunca necesita escribir comandos::

    python -m app.launcher start [--no-browser]   # inicia (o reutiliza) y abre el panel
    python -m app.launcher stop                   # cierre ordenado, sin procesos huérfanos
    python -m app.launcher restart | status | open | logs [-f] | doctor

- **Instancia única:** si ya hay un servidor de esta carpeta de datos, se reutiliza.
- **Puerto ocupado:** si el 8775 lo usa otro programa, se elige el siguiente libre
  (8776–8799) y se recuerda en ``run/instance.json``.
- **Cierre:** primero ordenado (la cola cancela render, transcripción y FFmpeg); si no
  responde, se termina el árbol completo de procesos.
- Solo escucha en 127.0.0.1 y abre el panel con el token de sesión (``app/session.py``).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

from app import edition, lifecycle, session
from app.config import APP_NAME, APP_VERSION, get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
PORT_RANGE = range(edition.DEFAULT_PORT, edition.DEFAULT_PORT + 25)
START_TIMEOUT = 120.0


def _out(symbol: str, text: str) -> None:
    print(f"  {symbol} {text}", flush=True)


def ok(text: str) -> None:
    _out("✓", text)


def info(text: str) -> None:
    _out("›", text)


def fail(text: str, code: int = 1) -> int:
    print(f"  ✗ {text}", file=sys.stderr, flush=True)
    return code


# ---------------------------------------------------------------------------
# Estado de la instancia
# ---------------------------------------------------------------------------


def home() -> Path:
    return get_settings().home


def log_file() -> Path:
    return home() / "logs" / "server.out"


def health(port: int, timeout: float = 2.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data if isinstance(data, dict) else None
    except (OSError, ValueError, urllib.error.URLError):
        return None


def read_instance() -> dict[str, Any] | None:
    try:
        data = json.loads(lifecycle.instance_file(home()).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def pid_alive(pid: int) -> bool:
    try:
        import psutil

        return bool(psutil.pid_exists(pid)) and psutil.Process(pid).status() != "zombie"
    except Exception:
        return False


def running() -> dict[str, Any] | None:
    """La instancia de ESTA carpeta de datos, si está en marcha y responde."""
    inst = read_instance()
    if not inst:
        return None
    port = int(inst.get("port") or 0)
    h = health(port) if port else None
    if h and h.get("instance") == lifecycle.instance_id(home()):
        return inst
    if not pid_alive(int(inst.get("pid") or 0)):
        with contextlib.suppress(OSError):
            lifecycle.instance_file(home()).unlink()
    return None


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Igual que uvicorn: en POSIX se ignoran las conexiones en TIME_WAIT de un servidor
        # anterior. En Windows SO_REUSEADDR permitiría compartir el puerto: no se usa.
        if sys.platform != "win32":
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def choose_port(preferred: int) -> int | None:
    candidates = [preferred, *[p for p in PORT_RANGE if p != preferred]]
    return next((p for p in candidates if port_free(p)), None)


def panel_url(port: int, path: str = "/") -> str:
    token = session.read_token(home())
    base = f"http://127.0.0.1:{port}"
    return f"{base}/open?t={token}" if token else f"{base}{path}"


def open_browser(port: int) -> None:
    if os.environ.get("VSA_NO_BROWSER") == "1":
        return
    url = panel_url(port)
    if sys.platform == "win32":
        with contextlib.suppress(OSError):
            os.startfile(url)  # type: ignore[attr-defined]
            return
    if sys.platform == "darwin" and shutil.which("open"):
        subprocess.run(["open", url], check=False)
        return
    webbrowser.open(url)


# ---------------------------------------------------------------------------
# Órdenes
# ---------------------------------------------------------------------------


def _spawn(port: int) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "VSA_PORT": str(port),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    log = log_file()
    log.parent.mkdir(parents=True, exist_ok=True)
    out = open(log, "ab")  # noqa: SIM115 (lo hereda el proceso hijo)
    out.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} inicio en el puerto {port}\n".encode())
    out.flush()
    cmd = [sys.executable, "run.py"]
    kwargs: dict[str, Any] = {
        "cwd": BACKEND_DIR,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": out,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        detached = 0x00000008  # DETACHED_PROCESS: sin consola, sobrevive al lanzador
        group = 0x00000200  # CREATE_NEW_PROCESS_GROUP
        breakaway = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB (si la consola usa un Job)
        try:
            return subprocess.Popen(cmd, creationflags=detached | group | breakaway, **kwargs)
        except OSError:
            return subprocess.Popen(cmd, creationflags=detached | group, **kwargs)
    return subprocess.Popen(cmd, start_new_session=True, **kwargs)


def cmd_start(no_browser: bool = False) -> int:
    print(f"{APP_NAME} — {edition.EDITION_NAME} {APP_VERSION}", flush=True)
    inst = running()
    if inst:
        ok(f"Ya está en marcha (PID {inst['pid']}) → http://127.0.0.1:{inst['port']}")
        if not no_browser:
            open_browser(int(inst["port"]))
        return 0
    preferred = int(os.environ.get("VSA_PORT") or edition.DEFAULT_PORT)
    port = choose_port(preferred)
    if port is None:
        return fail(
            f"No hay ningún puerto libre entre {PORT_RANGE.start} y {PORT_RANGE.stop - 1}. "
            "Cierra otros programas o usa VSA_PORT=<puerto>."
        )
    if port != preferred:
        info(f"El puerto {preferred} está ocupado por otro programa; se usará el {port}.")
    info(f"Iniciando en http://127.0.0.1:{port} (solo accesible desde este equipo)…")
    proc = _spawn(port)
    deadline = time.monotonic() + START_TIMEOUT
    expected = lifecycle.instance_id(home())
    while time.monotonic() < deadline:
        h = health(port, timeout=1.0)
        if h and h.get("instance") == expected:
            ok(f"Panel listo → http://127.0.0.1:{port}")
            if not no_browser:
                open_browser(port)
            return 0
        code = proc.poll()
        if code is not None:
            if code == 4:  # otra instancia ganó la carrera: se reutiliza
                time.sleep(1)
                inst = running()
                if inst:
                    ok(f"Ya está en marcha → http://127.0.0.1:{inst['port']}")
                    if not no_browser:
                        open_browser(int(inst["port"]))
                    return 0
            _tail(20, sys.stderr)
            return fail(f"El servidor no pudo arrancar (código {code}). Registro: {log_file()}")
        time.sleep(0.4)
    _tail(20, sys.stderr)
    return fail(f"El servidor tarda demasiado en responder. Registro: {log_file()}")


def _terminate_pid_tree(pid: int, timeout: float = 10) -> None:
    import psutil

    try:
        root = psutil.Process(pid)
    except psutil.Error:
        return
    procs = [*root.children(recursive=True), root]
    for p in procs:
        with contextlib.suppress(psutil.Error):
            p.terminate()
    _, alive = psutil.wait_procs(procs, timeout=timeout)
    for p in alive:
        with contextlib.suppress(psutil.Error):
            p.kill()


def cmd_stop() -> int:
    inst = read_instance()
    if not inst or not pid_alive(int(inst.get("pid") or 0)):
        with contextlib.suppress(OSError):
            lifecycle.instance_file(home()).unlink()
        ok("No estaba en marcha")
        return 0
    pid, port = int(inst["pid"]), int(inst["port"])
    info(f"Deteniendo (PID {pid})…")
    token = session.read_token(home()) or ""
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/system/shutdown",
        method="POST",
        headers={"x-vsa-client": "1", session.HEADER: token},
    )
    with contextlib.suppress(OSError, urllib.error.URLError):
        urllib.request.urlopen(req, timeout=5).read()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and pid_alive(pid):
        time.sleep(0.3)
    if pid_alive(pid):
        info("No respondió a tiempo: se termina con sus procesos hijos.")
        _terminate_pid_tree(pid)
    with contextlib.suppress(OSError):
        lifecycle.instance_file(home()).unlink()
    ok("Detenido")
    return 0


def cmd_status() -> int:
    inst = running()
    if inst:
        ok(f"En marcha (PID {inst['pid']}, versión {inst.get('version')}) → {inst['url']}")
    else:
        info("Detenido")
    info(f"Datos: {home()}")
    return 0


def cmd_open() -> int:
    inst = running()
    if not inst:
        return cmd_start()
    open_browser(int(inst["port"]))
    return 0


def _tail(lines: int, stream: Any = None) -> None:
    stream = stream or sys.stdout
    with contextlib.suppress(OSError):
        content = log_file().read_text(encoding="utf-8", errors="replace").splitlines()
        for line in content[-lines:]:
            print(line, file=stream)


def cmd_logs(follow: bool) -> int:
    _tail(60)
    if not follow:
        return 0
    path = log_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    with open(path, encoding="utf-8", errors="replace") as fh:
        fh.seek(0, os.SEEK_END)
        try:
            while True:
                line = fh.readline()
                if line:
                    print(line, end="", flush=True)
                else:
                    time.sleep(0.5)
        except KeyboardInterrupt:
            return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="videostudio", description=APP_NAME)
    sub = parser.add_subparsers(dest="command")
    start = sub.add_parser("start")
    start.add_argument("--no-browser", action="store_true")
    sub.add_parser("stop")
    restart = sub.add_parser("restart")
    restart.add_argument("--no-browser", action="store_true")
    sub.add_parser("status")
    sub.add_parser("open")
    logs = sub.add_parser("logs")
    logs.add_argument("-f", "--follow", action="store_true")
    sub.add_parser("doctor")
    args = parser.parse_args(argv)
    command = args.command or "start"
    if command == "start":
        return cmd_start(args.no_browser)
    if command == "stop":
        return cmd_stop()
    if command == "restart":
        cmd_stop()
        return cmd_start(args.no_browser)
    if command == "status":
        return cmd_status()
    if command == "open":
        return cmd_open()
    if command == "logs":
        return cmd_logs(args.follow)
    if command == "doctor":
        from app.installer import doctor

        return doctor()
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
