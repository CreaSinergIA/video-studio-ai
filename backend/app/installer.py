"""Instalador guiado de Video Studio AI — Community Edition (macOS y Windows).

Lo ejecutan ``./videostudio install`` (macOS) o ``Instalar Video Studio AI.cmd`` (Windows)
después de preparar Python con uv. Cada paso es **idempotente**: si la instalación se corta,
volver a ejecutarla continúa donde se quedó (estado en ``<datos>/install-state.json``).

Pasos:
 1. Requisitos del equipo (sistema, memoria, disco).
 2. FFmpeg: el del sistema si es adecuado; si no, copia portátil verificada (con confirmación).
 3. Node.js: el del sistema si es ≥ 20.19; si no, Node LTS portátil (con confirmación).
 4. Dependencias del panel y del motor de animaciones (npm ci, versiones fijadas).
 5. Compilación del panel.
 6. Carpeta de datos, base de datos vacía, token de sesión y permisos.
 7. Navegador de render de Remotion (descarga verificada, con confirmación).
 8. Modelo de transcripción recomendado para el equipo (con confirmación).
 9. Acceso directo para abrir el editor (con confirmación).
10. Verificación final e inicio del panel.

Nada se instala de forma global ni se cambia el PATH del sistema: las herramientas portátiles
viven en la carpeta de datos. Opciones (útiles para Claude Code, que no puede responder a
preguntas interactivas): ``--yes`` acepta todo lo recomendado; ``--no-model``,
``--model <id>``, ``--no-browser-engine``, ``--no-shortcut``, ``--no-start``, ``--cuda``.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app import edition
from app.config import APP_NAME, APP_VERSION, get_settings
from app.platform import detect, tools
from app.services import setup_checks

REPO_DIR = Path(__file__).resolve().parents[2]
FRONTEND = REPO_DIR / "frontend"
RENDERER = REPO_DIR / "renderer"

ASSUME_YES = False


class InstallError(Exception):
    pass


# ---------------------------------------------------------------------------
# Salida y preguntas
# ---------------------------------------------------------------------------


def title(text: str) -> None:
    print(f"\n\033[1m{text}\033[0m", flush=True)


def ok(text: str) -> None:
    print(f"  \033[32m✓\033[0m {text}", flush=True)


def info(text: str) -> None:
    print(f"  \033[36m›\033[0m {text}", flush=True)


def warn(text: str) -> None:
    print(f"  \033[33m!\033[0m {text}", flush=True)


def err(text: str) -> None:
    print(f"  \033[31m✗\033[0m {text}", file=sys.stderr, flush=True)


def confirm(question: str, default: bool = True) -> bool:
    """Pide confirmación. Con ``--yes`` acepta la opción recomendada (``default``)."""
    if ASSUME_YES:
        info(f"{question} → {'sí' if default else 'no'} (--yes)")
        return default
    if not sys.stdin or not sys.stdin.isatty():
        info(f"{question} → {'sí' if default else 'no'} (sin terminal interactiva)")
        return default
    suffix = "[S/n]" if default else "[s/N]"
    while True:
        answer = input(f"  ? {question} {suffix} ").strip().lower()
        if not answer:
            return default
        if answer in ("s", "si", "sí", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


class Progress:
    """Barra de progreso sencilla en una línea."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.last = -1

    def __call__(self, fraction: float, stage: str = "") -> None:
        pct = int(fraction * 100)
        if pct == self.last:
            return
        self.last = pct
        bar = "█" * (pct // 5) + "·" * (20 - pct // 5)
        print(f"\r  {bar} {pct:3d} % {stage or self.label}"[:110].ljust(110), end="", flush=True)
        if pct >= 100:
            print(flush=True)


# ---------------------------------------------------------------------------
# Estado (recuperación ante instalaciones incompletas)
# ---------------------------------------------------------------------------


def state_path() -> Path:
    return get_settings().home / "install-state.json"


def load_state() -> dict[str, Any]:
    with contextlib.suppress(OSError, ValueError):
        data = json.loads(state_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    return {"steps": {}}


def save_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def run_step(state: dict[str, Any], key: str, label: str, fn: Callable[[], str | None]) -> None:
    title(label)
    previous = state["steps"].get(key, {})
    if previous.get("status") == "failed":
        info(f"La ejecución anterior falló aquí ({previous.get('error', '')}); se reintenta.")
    state["steps"][key] = {"status": "running", "started_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_state(state)
    try:
        result = fn()
    except KeyboardInterrupt:
        state["steps"][key] = {"status": "failed", "error": "interrumpido"}
        save_state(state)
        raise
    except Exception as exc:
        message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
        state["steps"][key] = {"status": "failed", "error": message}
        save_state(state)
        raise InstallError(f"{label}: {message}") from exc
    state["steps"][key] = {
        "status": "done",
        "result": result or "",
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(state)


# ---------------------------------------------------------------------------
# Pasos
# ---------------------------------------------------------------------------


def step_requirements() -> str:
    home = get_settings().home
    problems = 0
    for check in (setup_checks.platform_check(), setup_checks.resources_check(home)):
        if check.status == "ok":
            ok(f"{check.label}: {check.detail}")
        elif check.status == "warning":
            warn(f"{check.label}: {check.detail}. {check.fix}")
        else:
            err(f"{check.label}: {check.detail}. {check.fix}")
            problems += 1
    ok(f"Python {sys.version.split()[0]} (entorno local en backend/.venv)")
    if problems:
        raise InstallError("El equipo no cumple los requisitos mínimos.")
    return "ok"


def step_ffmpeg() -> str:
    check = setup_checks.ffmpeg_check()
    if check.status == "ok":
        ok(check.detail)
        return check.detail
    warn(f"{check.detail} {check.fix}")
    spec = tools.spec_for("ffmpeg")
    if spec is None:
        raise InstallError(
            "No hay una copia portátil de FFmpeg para este sistema. Instálalo manualmente "
            "(https://ffmpeg.org/download.html) y vuelve a ejecutar el instalador."
        )
    size = sum(d.size for d in spec.downloads) / 1e6
    print(
        f"    Se descargará FFmpeg {spec.version} ({size:.0f} MB, {spec.license}) desde su "
        "proveedor oficial enlazado en ffmpeg.org,\n    se verificará su huella SHA-256 y se "
        f"guardará solo en {tools.tools_root(get_settings().home)}.",
        flush=True,
    )
    if not confirm("¿Descargar FFmpeg portátil?"):
        raise InstallError("FFmpeg es imprescindible. Instálalo y vuelve a ejecutar el instalador.")
    path = tools.install(get_settings().home, "ffmpeg", Progress("FFmpeg"))
    get_settings.cache_clear()
    ok(f"FFmpeg {spec.version} portátil verificado: {path}")
    return str(path)


def step_node() -> str:
    check = setup_checks.node_check()
    if check.status == "ok":
        ok(check.detail)
        return check.detail
    warn(f"{check.detail} {check.fix}")
    spec = tools.spec_for("node")
    if spec is None:
        raise InstallError(
            "Instala Node.js 22 o 24 LTS (https://nodejs.org) y vuelve a ejecutar el instalador."
        )
    size = sum(d.size for d in spec.downloads) / 1e6
    print(
        f"    Se descargará Node.js {spec.version} LTS ({size:.0f} MB) desde nodejs.org, se "
        "verificará su huella SHA-256\n    y se guardará solo en la carpeta de datos (no "
        "cambia el Node.js del sistema).",
        flush=True,
    )
    if not confirm("¿Descargar Node.js portátil?"):
        raise InstallError("Node.js es imprescindible para el panel y las animaciones.")
    path = tools.install(get_settings().home, "node", Progress("Node.js"))
    ok(f"Node.js {spec.version} portátil verificado: {path}")
    return str(path)


def _node() -> Path:
    from app.services import render_engine

    node = render_engine.find_node()
    if node is None:
        raise InstallError("No se encontró Node.js.")
    return node


def _npm_cli(node: Path) -> Path:
    real = node.resolve()
    candidates = [
        real.parent / "node_modules" / "npm" / "bin" / "npm-cli.js",  # Windows
        real.parent.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js",  # POSIX
    ]
    for c in candidates:
        if c.is_file():
            return c
    npm = shutil.which("npm")
    if npm:
        real_npm = Path(npm).resolve()
        for c in (
            real_npm.parent / "node_modules" / "npm" / "bin" / "npm-cli.js",
            real_npm.parent.parent / "lib" / "node_modules" / "npm" / "bin" / "npm-cli.js",
            real_npm if real_npm.suffix == ".js" else Path("-"),
        ):
            if c.is_file():
                return c
    raise InstallError(f"No se encontró npm junto a {node}.")


def _node_env(node: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(node.parent), env.get("PATH", "")])
    env["npm_config_fund"] = "false"
    env["npm_config_audit"] = "false"
    env["npm_config_update_notifier"] = "false"
    # Remotion no descarga su propio navegador: el editor usa el suyo, verificado.
    env["REMOTION_SKIP_BROWSER_DOWNLOAD"] = "1"
    env["PUPPETEER_SKIP_DOWNLOAD"] = "1"
    return env


def npm(directory: Path, *args: str) -> None:
    node = _node()
    cmd = [str(node), str(_npm_cli(node)), *args]
    info(f"npm {' '.join(args)} en {directory.name}/")
    proc = subprocess.run(
        cmd, cwd=directory, env=_node_env(node), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )  # fmt: skip
    if proc.returncode != 0:
        tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-15:])
        raise InstallError(f"npm {' '.join(args)} falló en {directory.name}/:\n{tail}")


def step_node_modules() -> str:
    for directory in (FRONTEND, RENDERER):
        if setup_checks.node_modules_current(directory):
            ok(f"{directory.name}/node_modules al día")
            continue
        npm(directory, "ci", "--loglevel=error", "--no-fund", "--no-audit")
        (directory / "node_modules" / ".vsa-lock").write_text(
            setup_checks.lock_hash(directory), encoding="utf-8"
        )
        ok(f"{directory.name}: dependencias instaladas (versiones fijadas en package-lock.json)")
    return "ok"


def _newest_mtime(paths: list[Path]) -> float:
    newest = 0.0
    for p in paths:
        if p.is_file():
            newest = max(newest, p.stat().st_mtime)
        elif p.is_dir():
            for f in p.rglob("*"):
                if f.is_file():
                    newest = max(newest, f.stat().st_mtime)
    return newest


def panel_needs_build(dist: Path) -> bool:
    index = dist / "index.html"
    if not index.is_file():
        return True
    sources = [
        FRONTEND / "src",
        FRONTEND / "index.html",
        FRONTEND / "package.json",
        FRONTEND / "package-lock.json",
        FRONTEND / "vite.config.ts",
    ]
    return _newest_mtime(sources) > index.stat().st_mtime


def step_build() -> str:
    dist = FRONTEND / "dist"
    if not panel_needs_build(dist):
        ok("El panel ya está compilado")
        return "ok"
    npm(FRONTEND, "run", "build", "--silent")
    ok("Panel compilado")
    return "ok"


def step_data() -> str:
    from app import db, session
    from app.services import data_safety
    from app.services import presets as preset_service

    settings = get_settings()
    home = settings.home
    home.mkdir(parents=True, exist_ok=True)
    for sub in ("logs", "run", "models", "engines", "backups", "cache"):
        (home / sub).mkdir(exist_ok=True)
    # Permisos: la carpeta de datos (base, registros, token) solo es legible por el usuario.
    # En Windows, %LOCALAPPDATA% ya es privada de la cuenta.
    if os.name != "nt":
        home.chmod(0o700)
    kind = data_safety.ensure_environment(home, APP_VERSION)
    db.init_engine(settings.database_url)
    db.run_migrations(settings.database_url)
    integrity = db.check_integrity()
    if integrity != "ok":
        raise InstallError(f"La base de datos no supera la comprobación de integridad: {integrity}")
    with db.session_scope() as s:
        preset_service.seed_builtin_presets(s)
    session.ensure_token(home)
    ok(f"Datos en {home} (entorno {kind}); base de datos lista")
    return str(home)


def _run_with_progress(
    label: str, fn: Callable[[Callable[..., None], threading.Event], Any]
) -> Any:
    progress = Progress(label)
    cancel = threading.Event()
    try:
        return fn(progress, cancel)
    except KeyboardInterrupt:
        cancel.set()
        raise


def step_browser(enabled: bool) -> str:
    from app.services import render_engine

    st = render_engine.status()["browser"]
    if st["installed"]:
        ok(f"Navegador de render {st['version']} ya instalado")
        return "installed"
    if not render_engine.BROWSER.get("url"):
        warn("No hay navegador de render para este sistema: las animaciones no funcionarán.")
        return "unsupported"
    print(
        f"    Remotion necesita Chrome Headless Shell {st['version']} "
        f"(~{st['download_bytes'] / 1e6:.0f} MB, de Google). Se verifica por tamaño, MD5 y "
        "SHA-256.",
        flush=True,
    )
    if not enabled or not confirm("¿Descargar el navegador de render ahora?"):
        warn("Omitido: podrás instalarlo en Ajustes → Animaciones.")
        return "skipped"
    _run_with_progress(
        "Navegador de render",
        lambda p, c: render_engine.install_browser(lambda f: p(f, "Navegador de render"), c),
    )
    ok("Navegador de render instalado y verificado")
    return "installed"


def step_model(enabled: bool, model_id: str | None) -> str:
    from app.platform import transcription
    from app.services import asr_models

    engine = transcription.active()
    if engine is None:
        raise InstallError("No hay ningún motor de transcripción disponible en este equipo.")
    ok(f"Motor de transcripción: {engine.name} ({engine.reason})")
    chosen = model_id or asr_models.default_model_id()
    spec = asr_models.require_usable(chosen)
    if asr_models.is_installed(chosen):
        ok(f"Modelo «{spec.name}» ya instalado")
        return chosen
    label = "Modelo elegido" if model_id else "Modelo recomendado"
    size = f"{spec.size_bytes / 1e9:.1f}".replace(".", ",")
    print(
        f"    {label}: {spec.name} ({size} GB, {spec.repo}@{spec.revision[:10]}).\n"
        f"    {spec.description}",
        flush=True,
    )
    if not enabled or not confirm(f"¿Descargar «{spec.name}» ahora?"):
        warn("Omitido: podrás descargarlo en Ajustes → Transcripción.")
        return "skipped"
    _run_with_progress(
        spec.name,
        lambda p, c: asr_models.download(chosen, lambda f, s: p(f, s), c),
    )
    ok(f"Modelo «{spec.name}» descargado y verificado")
    return chosen


def step_cuda() -> str:
    """Opcional (Windows/Linux con NVIDIA): bibliotecas CUDA para faster-whisper (~1,5 GB)."""
    info_ = detect()
    if info_.os == "macos":
        return "no aplica"
    if not info_.nvidia_gpu:
        warn("No se detectó una GPU NVIDIA: la transcripción usará la CPU (no hace falta GPU).")
        return "sin NVIDIA"
    if not confirm(
        f"GPU {info_.nvidia_gpu} detectada. ¿Descargar las bibliotecas CUDA (~1,5 GB) para "
        "acelerar la transcripción?",
        default=False,
    ):
        return "omitido"
    uv = os.environ.get("VSA_UV") or shutil.which("uv")
    if not uv:
        raise InstallError("No se encontró uv para instalar el complemento CUDA.")
    proc = subprocess.run(
        [uv, "sync", "--frozen", "--no-dev", "--extra", "cuda"], cwd=REPO_DIR / "backend"
    )
    if proc.returncode != 0:
        raise InstallError("No se pudieron instalar las bibliotecas CUDA.")
    # El lanzador conserva el complemento en las siguientes sincronizaciones.
    (get_settings().home / "cuda.enabled").write_text("1", encoding="utf-8")
    ok("Bibliotecas CUDA instaladas (si fallan al cargar, se usa la CPU automáticamente)")
    return "instalado"


def step_shortcut(enabled: bool) -> str:
    from app import shortcuts

    if not enabled:
        return "omitido"
    where = shortcuts.describe()
    if not where:
        return "no disponible"
    if not confirm(f"¿Crear un acceso directo para abrir el editor ({where})?"):
        return "omitido"
    created = shortcuts.create()
    for path in created:
        ok(f"Acceso directo: {path}")
    return ", ".join(str(p) for p in created)


def doctor() -> int:
    title(f"Diagnóstico de {APP_NAME} — {edition.EDITION_NAME} {APP_VERSION}")
    worst = 0
    for check in setup_checks.all_checks():
        line = f"{check.label}: {check.detail}" + (f" — {check.fix}" if check.fix else "")
        if check.status == "ok":
            ok(line)
        elif check.status in ("warning", "missing"):
            warn(line)
            worst = max(worst, 0)
        else:
            err(line)
            worst = 1
    info(f"Datos: {get_settings().home}")
    return worst


def main(argv: list[str] | None = None) -> int:
    global ASSUME_YES
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="videostudio install")
    parser.add_argument("--yes", "-y", action="store_true", help="acepta lo recomendado")
    parser.add_argument("--no-model", action="store_true")
    parser.add_argument("--model", default=None)
    parser.add_argument("--no-browser-engine", action="store_true")
    parser.add_argument("--no-shortcut", action="store_true")
    parser.add_argument("--no-start", action="store_true")
    parser.add_argument("--cuda", action="store_true")
    args = parser.parse_args(argv)
    ASSUME_YES = args.yes

    print(f"\033[1m{APP_NAME} — {edition.EDITION_NAME} {APP_VERSION}\033[0m")
    print("Instalación local. Nada se publica ni se envía a ningún servidor de Video Studio AI.")
    state = load_state()
    state["version"] = APP_VERSION
    try:
        run_step(state, "requirements", "1. Requisitos del equipo", step_requirements)
        run_step(state, "ffmpeg", "2. FFmpeg", step_ffmpeg)
        run_step(state, "node", "3. Node.js", step_node)
        run_step(state, "node_modules", "4. Dependencias del panel y del motor", step_node_modules)
        run_step(state, "build", "5. Compilación del panel", step_build)
        run_step(state, "data", "6. Carpeta de datos y base de datos", step_data)
        run_step(
            state,
            "browser",
            "7. Navegador de render (Remotion)",
            lambda: step_browser(not args.no_browser_engine),
        )
        run_step(
            state,
            "model",
            "8. Modelo de transcripción",
            lambda: step_model(not args.no_model, args.model),
        )
        if args.cuda:
            run_step(state, "cuda", "8b. Aceleración NVIDIA (opcional)", step_cuda)
        run_step(
            state, "shortcut", "9. Acceso directo", lambda: step_shortcut(not args.no_shortcut)
        )
    except InstallError as exc:
        err(str(exc))
        print(
            "\n  La instalación no terminó. Corrige lo indicado y vuelve a ejecutarla: "
            "continuará donde se quedó.",
            file=sys.stderr,
        )
        return 2
    except KeyboardInterrupt:
        err("Instalación interrumpida. Vuelve a ejecutarla para continuar.")
        return 130
    state["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    save_state(state)
    title("10. Verificación")
    doctor()
    if args.no_start:
        ok("Instalación completa. Abre el editor con el acceso directo o el lanzador.")
        return 0
    from app import launcher

    return launcher.cmd_start()


if __name__ == "__main__":
    sys.exit(main())
