"""Motor de render de animaciones (Fase 4): Remotion en un proceso Node aislado.

- **Navegador de render**: Chrome Headless Shell oficial de Google («Chrome for Testing»),
  versión fijada a la que prueba Remotion 4.0.534. Se descarga solo cuando el usuario lo pide,
  se verifica (tamaño y MD5 publicados por Google, firma de código de Apple) y se instala en
  la carpeta de datos de la app. Los renders usan esa ruta exacta (`browserExecutable`), así que
  Remotion nunca descarga nada por su cuenta.
- **Paquete**: el código de las composiciones (`renderer/src`) se empaqueta una vez por huella
  del código y se reutiliza.
- **Render**: proceso Node con entorno mínimo (sin credenciales), sin red propia, con límite de
  memoria, tiempo máximo y cancelación del grupo de procesos. Solo recibe especificaciones JSON
  validadas, nunca código.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import logging
import ntpath
import os
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.platform import processes, tools
from app.platform.detect import detect
from app.services.media_tools import Cancelled

log = logging.getLogger(__name__)

REPO_DIR = Path(__file__).resolve().parents[3]
RENDERER_DIR = REPO_DIR / "renderer"
FONTS_DIR = Path(__file__).resolve().parents[1] / "resources" / "fonts"

REMOTION_VERSION = "4.0.534"
_CFT = "https://storage.googleapis.com/chrome-for-testing-public/157.0.8080.0"
# Por plataforma: tamaño y MD5 publicados por Google (cabecera x-goog-hash) y SHA-256 fijado
# (calculado al preparar esta versión; el MD5 coincide con el de Google).
BROWSERS: dict[str, dict[str, Any]] = {
    "mac-arm64": {
        "url": f"{_CFT}/mac-arm64/chrome-headless-shell-mac-arm64.zip",
        "size": 103_864_219,
        "md5_b64": "+fkyl3YdZLGBlWo7N14QWA==",
        "sha256": "8cd31d4bc5f7ea0930940292f1972c68f4296b01fbcb4fa709841a8f60eba95d",
        "folder": "chrome-headless-shell-mac-arm64",
        "executable": "chrome-headless-shell-mac-arm64/chrome-headless-shell",
    },
    "mac-x64": {
        "url": f"{_CFT}/mac-x64/chrome-headless-shell-mac-x64.zip",
        "size": 109_113_968,
        "md5_b64": "rGlRi5SZXJgnvyV+jyWdtA==",
        "sha256": "b4a3f7e8aed11e7814fdaf49ddadab0ec3e0c7527f0ffeed5b208d7a856ebf6a",
        "folder": "chrome-headless-shell-mac-x64",
        "executable": "chrome-headless-shell-mac-x64/chrome-headless-shell",
    },
    "win64": {
        "url": f"{_CFT}/win64/chrome-headless-shell-win64.zip",
        "size": 125_915_690,
        "md5_b64": "ezp50AgeVIxN+wNbiW38MA==",
        "sha256": "ad0fe78fbe0783035fd71f81cd876a2e81962a40ac7de6b4f7afcbeb00901c11",
        "folder": "chrome-headless-shell-win64",
        "executable": "chrome-headless-shell-win64/chrome-headless-shell.exe",
    },
}


def _browser_platform() -> str | None:
    info = detect()
    if info.os == "macos":
        return "mac-arm64" if info.arch == "arm64" else "mac-x64"
    if info.os == "windows" and info.arch == "x86_64":
        return "win64"
    return None


_KEY = _browser_platform()
BROWSER: dict[str, Any] = {
    "name": "Chrome Headless Shell (Chrome for Testing)",
    "version": "157.0.8080.0",
    "platform": _KEY,
    **(BROWSERS[_KEY] if _KEY else {"url": None, "size": 0, "executable": "-"}),
}
RENDER_FONTS = [
    "Inter-Variable.ttf",
    "Montserrat-Variable.ttf",
    "JetBrainsMono-Variable.ttf",
    "Caveat-Variable.ttf",
    "Poppins-Medium.ttf",
    "Poppins-SemiBold.ttf",
    "Poppins-Bold.ttf",
    "Poppins-ExtraBold.ttf",
    "BebasNeue-Regular.ttf",
]


class EngineError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def engines_dir() -> Path:
    d = get_settings().home / "engines"
    d.mkdir(parents=True, exist_ok=True)
    return d


def browser_dir() -> Path:
    return engines_dir() / "chrome-headless-shell" / BROWSER["version"]


def browser_executable() -> Path | None:
    exe = browser_dir() / BROWSER["executable"]
    manifest = browser_dir() / "vsa-browser.json"
    return exe if exe.is_file() and manifest.is_file() else None


def find_node() -> Path | None:
    """Node.js: copia portátil del instalador, ``VSA_NODE``, el PATH o instalaciones típicas.
    Solo se acepta una versión compatible (``tools.NODE_MIN``)."""
    cands: list[Path] = []
    if os.environ.get("VSA_NODE"):
        cands.append(Path(os.environ["VSA_NODE"]))
    portable = tools.installed_executable(get_settings().home, "node")
    if portable is not None:
        cands.append(portable)
    found = shutil.which("node")
    if found:
        cands.append(Path(found))
    if os.environ.get("VSA_IGNORE_SYSTEM_TOOLS") == "1":  # simula un equipo limpio
        return next((c for c in cands if c.is_file() and tools.node_is_suitable(c)), None)
    nvm = Path.home() / ".nvm" / "versions" / "node"
    if nvm.is_dir():
        cands += sorted(
            nvm.glob("v*/bin/node"),
            key=lambda p: [int(x) for x in p.parts[-3][1:].split(".") if x.isdigit()],
            reverse=True,
        )
    if os.name == "nt":
        program_files = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        cands.append(Path(program_files) / "nodejs" / "node.exe")
    else:
        cands += [Path("/opt/homebrew/bin/node"), Path("/usr/local/bin/node")]
    for c in cands:
        if c.is_file() and os.access(c, os.X_OK) and tools.node_is_suitable(c):
            return c
    return None


def _codesign_ok(path: Path) -> bool:
    try:
        out = subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(path)],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0


def status() -> dict[str, Any]:
    """Estado local del motor (no descarga ni ejecuta renders)."""
    node = find_node()
    node_version = None
    if node:
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            node_version = subprocess.run(
                [str(node), "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            ).stdout.strip()
    pkg = RENDERER_DIR / "node_modules" / "@remotion" / "renderer" / "package.json"
    remotion = None
    if pkg.is_file():
        with contextlib.suppress(OSError, ValueError):
            remotion = json.loads(pkg.read_text(encoding="utf-8")).get("version")
    exe = browser_executable()
    manifest: dict[str, Any] = {}
    if exe:
        with contextlib.suppress(OSError, ValueError):
            manifest = json.loads((browser_dir() / "vsa-browser.json").read_text(encoding="utf-8"))
    ready = bool(node and remotion == REMOTION_VERSION and exe)
    return {
        "ready": ready,
        "node": {"path": str(node) if node else None, "version": node_version},
        "remotion": {"installed": remotion, "expected": REMOTION_VERSION, "dir": str(RENDERER_DIR)},
        "browser": {
            "installed": exe is not None,
            "name": BROWSER["name"],
            "version": BROWSER["version"],
            "download_bytes": BROWSER["size"],
            "source": BROWSER["url"],
            "path": str(exe) if exe else None,
            "sha256": manifest.get("sha256"),
            "codesign": manifest.get("codesign"),
            "installed_at": manifest.get("installed_at"),
        },
        "license": (
            "Remotion tiene licencia propia: es gratuito para personas, organizaciones sin ánimo "
            "de lucro y empresas de hasta 3 personas; las organizaciones mayores necesitan su "
            "propia licencia de Remotion (remotion.pro/license). Cada usuario es responsable de "
            "cumplir sus condiciones."
        ),
    }


def install_browser(
    on_progress: Callable[[float], None], cancel: threading.Event
) -> dict[str, Any]:
    """Descarga explícita y verificada del navegador de render."""
    if browser_executable() is not None:
        return {"already_installed": True}
    if not BROWSER.get("url"):
        raise EngineError(
            "browser_unsupported",
            "No hay un navegador de render preparado para este sistema (Windows x64 o macOS).",
        )
    target = browser_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="browser-", dir=engines_dir()))
    try:
        zpath = work / "browser.zip"
        md5 = hashlib.md5()
        sha = hashlib.sha256()
        got = 0
        req = urllib.request.Request(BROWSER["url"], headers={"User-Agent": "VideoStudioAI"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(zpath, "wb") as fh:
            length = int(resp.headers.get("Content-Length") or 0)
            if length and length != BROWSER["size"]:
                raise EngineError(
                    "browser_size", f"Tamaño inesperado del navegador: {length} bytes."
                )
            while True:
                if cancel.is_set():
                    raise Cancelled()
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                fh.write(chunk)
                md5.update(chunk)
                sha.update(chunk)
                got += len(chunk)
                on_progress(min(0.9, got / BROWSER["size"] * 0.9))
        if got != BROWSER["size"]:
            raise EngineError("browser_size", "La descarga del navegador está incompleta.")
        if base64.b64encode(md5.digest()).decode() != BROWSER["md5_b64"]:
            raise EngineError(
                "browser_hash",
                "La huella MD5 del navegador no coincide con la publicada por Google.",
            )
        if sha.hexdigest() != BROWSER["sha256"]:
            raise EngineError(
                "browser_hash", "La huella SHA-256 del navegador no coincide con la esperada."
            )
        unpack = work / "unpacked"
        macos = detect().os == "macos"
        if macos:
            # ditto conserva enlaces simbólicos y la firma de código del paquete.
            subprocess.run(["ditto", "-x", "-k", str(zpath), str(unpack)], check=True, timeout=300)
        else:
            unpack.mkdir()
            tools.safe_extract(zpath, unpack)
        exe = unpack / BROWSER["executable"]
        if not exe.is_file():
            raise EngineError(
                "browser_layout", "El archivo descargado no contiene el ejecutable esperado."
            )
        # macOS: además de las huellas, la firma de código de Google. En Windows el ejecutable
        # se verifica por su SHA-256 fijado (ya comprobado arriba).
        if macos and not _codesign_ok(exe):
            raise EngineError("browser_codesign", "La firma de código del navegador no es válida.")
        on_progress(0.97)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        shutil.move(str(unpack / BROWSER["folder"]), str(target / BROWSER["folder"]))
        manifest = {
            "name": BROWSER["name"],
            "version": BROWSER["version"],
            "url": BROWSER["url"],
            "size": got,
            "md5_b64": BROWSER["md5_b64"],
            "sha256": sha.hexdigest(),
            "codesign": "válida (codesign --verify --deep --strict)" if macos else None,
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        (target / "vsa-browser.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        on_progress(1.0)
        return manifest
    finally:
        shutil.rmtree(work, ignore_errors=True)


def delete_browser() -> None:
    shutil.rmtree(browser_dir(), ignore_errors=True)


# ---------------------------------------------------------------------------
# Paquete de composiciones
# ---------------------------------------------------------------------------


def source_hash() -> str:
    h = hashlib.sha256()
    files = [*sorted((RENDERER_DIR / "src").rglob("*")), RENDERER_DIR / "package-lock.json"]
    for f in files:
        if f.is_file():
            h.update(f.relative_to(RENDERER_DIR).as_posix().encode())
            h.update(f.read_bytes())
    for name in RENDER_FONTS:
        h.update(name.encode())
        h.update(hashlib.sha256((FONTS_DIR / name).read_bytes()).digest())
    return h.hexdigest()[:16]


def _env(node: Path, windows: bool | None = None) -> dict[str, str]:
    # Entorno mínimo: sin claves, tokens ni variables de Claude/Anthropic.
    if windows if windows is not None else os.name == "nt":
        # Windows necesita estas variables para crear procesos, temporales y el navegador.
        keep = {
            "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE",
            "HOMEPATH", "LOCALAPPDATA", "APPDATA", "PROGRAMDATA", "COMSPEC", "PATHEXT",
            "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "USERNAME", "LANG",
        }  # fmt: skip
        env = {k: v for k, v in os.environ.items() if k.upper() in keep}
        system32 = ntpath.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32")
        env["PATH"] = ";".join([str(node.parent), system32])
    else:
        keep = {"HOME", "TMPDIR", "LANG", "LC_ALL", "USER"}
        env = {k: v for k, v in os.environ.items() if k in keep}
        env["PATH"] = os.pathsep.join([str(node.parent), "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    env["NODE_OPTIONS"] = "--max-old-space-size=3072"
    env["REMOTION_DISABLE_TELEMETRY"] = "1"
    return env


def ensure_bundle(cancel: threading.Event | None = None) -> Path:
    """Empaqueta las composiciones (una vez por huella del código)."""
    node = find_node()
    if node is None:
        raise EngineError("node_missing", "No se encontró Node.js en este equipo.")
    cache = get_settings().home / "cache" / "remotion"
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"bundle-{source_hash()}"
    if (out / "index.html").is_file():
        return out
    public = cache / "public"
    (public / "fonts").mkdir(parents=True, exist_ok=True)
    for name in RENDER_FONTS:
        shutil.copy2(FONTS_DIR / name, public / "fonts" / name)
    for old in cache.glob("bundle-*"):
        if old != out:
            shutil.rmtree(old, ignore_errors=True)
    events = _run_node(
        node,
        ["bundle", "src/index.ts", str(public), str(out)],
        timeout=600,
        cancel=cancel,
    )
    if not (out / "index.html").is_file():
        detail = next((e.get("message") for e in events if e.get("type") == "fatal"), "sin detalle")
        raise EngineError("bundle_failed", f"No se pudo preparar el motor de animaciones: {detail}")
    return out


@dataclass
class ClipJob:
    key: str
    spec: dict[str, Any]
    out: Path


def render_clips(
    clips: Iterable[ClipJob],
    *,
    on_event: Callable[[dict[str, Any]], None],
    cancel: threading.Event | None = None,
    timeout: float = 3600,
    concurrency: int | None = None,
) -> list[dict[str, Any]]:
    """Renderiza clips con transparencia (ProRes 4444). Devuelve los eventos emitidos."""
    node = find_node()
    exe = browser_executable()
    if node is None:
        raise EngineError("node_missing", "No se encontró Node.js en este equipo.")
    if exe is None:
        raise EngineError(
            "browser_missing",
            "Falta el navegador de render. Instálalo en Ajustes → Motor de animaciones.",
        )
    bundle = ensure_bundle(cancel)
    clips = list(clips)
    work = Path(tempfile.mkdtemp(prefix="render-", dir=get_settings().home / "cache"))
    try:
        job = {
            "serveUrl": str(bundle),
            "browserExecutable": str(exe),
            "concurrency": concurrency,
            "clips": [{"key": c.key, "spec": c.spec, "out": str(c.out)} for c in clips],
        }
        path = work / "job.json"
        path.write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        return _run_node(
            node, ["render", str(path)], timeout=timeout, cancel=cancel, on_event=on_event
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
        # Si el proceso terminó a la fuerza (cancelación, límite de tiempo), no quedan parciales.
        for c in clips:
            Path(f"{c.out}.partial.mov").unlink(missing_ok=True)


def _run_node(
    node: Path,
    args: list[str],
    *,
    timeout: float,
    cancel: threading.Event | None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    proc = subprocess.Popen(
        [str(node), "scripts/render.mjs", *args],
        cwd=RENDERER_DIR,
        env=_env(node),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        **processes.group_kwargs(),
    )
    processes.track(proc)
    tree = processes.TreeWatcher(proc)
    started = time.monotonic()
    killed: dict[str, str] = {}
    events: list[dict[str, Any]] = []
    tail: list[str] = []

    def _kill(reason: str) -> None:
        killed.setdefault("reason", reason)
        tree.snapshot()  # incluir lo que se haya lanzado justo antes de cancelar
        processes.terminate_tree(proc, grace=5)

    def _watch() -> None:
        ticks = 0
        while proc.poll() is None:
            if ticks % 3 == 0:
                tree.snapshot()  # el navegador de Remotion crea su propio grupo de procesos
            ticks += 1
            if cancel is not None and cancel.is_set():
                _kill("cancelled")
                return
            if time.monotonic() - started > timeout:
                _kill("timeout")
                return
            time.sleep(0.2)

    def _drain() -> None:
        assert proc.stderr is not None
        for line in proc.stderr:
            tail.append(line.rstrip())
            del tail[:-30]

    threading.Thread(target=_watch, daemon=True).start()
    threading.Thread(target=_drain, daemon=True).start()
    assert proc.stdout is not None
    for line in proc.stdout:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        events.append(ev)
        if on_event:
            on_event(ev)
    proc.wait()
    # Sea cual sea el final (normal, cancelado, error o tiempo agotado), no queda ningún
    # descendiente vivo: en particular, el navegador de render.
    tree.reap()
    processes.untrack(proc)
    if killed.get("reason") == "cancelled":
        raise Cancelled()
    if killed.get("reason") == "timeout":
        raise EngineError(
            "render_timeout", f"El render superó el tiempo máximo ({int(timeout)} s)."
        )
    if proc.returncode not in (0, None):
        fatal = next((e.get("message") for e in events if e.get("type") == "fatal"), None)
        detail = fatal or " ".join(tail[-3:])[:400] or f"código {proc.returncode}"
        raise EngineError("render_failed", f"El motor de render falló: {detail}")
    return events
