"""Herramientas portátiles (Node.js y FFmpeg) instaladas en la carpeta de datos de la edición.

Se usan solo si el equipo no tiene ya una versión adecuada. Nada se instala de forma global ni
se modifica el PATH del sistema: todo vive en ``<datos>/tools`` y se borra con la carpeta.

Cada descarga tiene versión y huella SHA-256 fijadas; se verifica antes de extraer. Fuentes:

- **Node.js** 24 LTS: nodejs.org (huellas de ``SHASUMS256.txt``).
- **FFmpeg** 9.0.2:
  - macOS: compilaciones estáticas de Martin Riedl (enlazadas desde ffmpeg.org), firmadas con
    su Developer ID; se comprueba la firma y el equipo.
  - Windows x64: compilación «essentials» de Gyan Doshi (enlazada desde ffmpeg.org), versión
    publicada en su repositorio de GitHub.

FFmpeg se descarga del proveedor en el equipo del usuario; este proyecto no lo redistribuye
(GPL: ver THIRD_PARTY_NOTICES.md).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.platform.detect import detect

NODE_VERSION = "24.21.0"
NODE_MIN = (20, 19)  # Vite 8 y Remotion 4
FFMPEG_VERSION = "9.0.2"
MAC_FFMPEG_TEAM = "KU3N25YGLU"  # Developer ID de Martin Riedl


@dataclass(frozen=True)
class Download:
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ToolSpec:
    name: str
    version: str
    downloads: tuple[Download, ...]
    # Rutas relativas a la carpeta de la herramienta.
    executables: dict[str, str]
    license: str


def _platform_key() -> str:
    info = detect()
    return f"{info.os}-{info.arch}"


_NODE = "https://nodejs.org/dist/v24.21.0"
_MR = "https://ffmpeg.martin-riedl.de/download/macos"
_GYAN = "https://github.com/GyanD/codexffmpeg/releases/download/9.0.2"

CATALOG: dict[str, dict[str, ToolSpec]] = {
    "node": {
        "macos-arm64": ToolSpec(
            "node",
            NODE_VERSION,
            (
                Download(
                    f"{_NODE}/node-v24.21.0-darwin-arm64.tar.gz",
                    52909993,
                    "bed7eea5325e1108f32ce5228ddd6a5f0f08a499ee42aa7442aea583702f6057",
                ),
            ),
            {"node": "node-v24.21.0-darwin-arm64/bin/node"},
            "MIT",
        ),
        "macos-x86_64": ToolSpec(
            "node",
            NODE_VERSION,
            (
                Download(
                    f"{_NODE}/node-v24.21.0-darwin-x64.tar.gz",
                    54203979,
                    "1462cb3b3046b815cf8ea436d3da450ec1a9f11dac7e5a46b0ada5305d7e8097",
                ),
            ),
            {"node": "node-v24.21.0-darwin-x64/bin/node"},
            "MIT",
        ),
        "windows-x86_64": ToolSpec(
            "node",
            NODE_VERSION,
            (
                Download(
                    f"{_NODE}/node-v24.21.0-win-x64.zip",
                    37618919,
                    "158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541",
                ),
            ),
            {"node": "node-v24.21.0-win-x64/node.exe"},
            "MIT",
        ),
    },
    "ffmpeg": {
        "macos-arm64": ToolSpec(
            "ffmpeg",
            FFMPEG_VERSION,
            (
                Download(
                    f"{_MR}/arm64/1789931890_9.0.2/ffmpeg.zip",
                    28395699,
                    "c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924",
                ),
                Download(
                    f"{_MR}/arm64/1789931890_9.0.2/ffprobe.zip",
                    28317701,
                    "fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6",
                ),
            ),
            {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"},
            "GPL-3.0 (compilación con libx264/libx265)",
        ),
        "macos-x86_64": ToolSpec(
            "ffmpeg",
            FFMPEG_VERSION,
            (
                Download(
                    f"{_MR}/amd64/1789931006_9.0.2/ffmpeg.zip",
                    33816391,
                    "7c6b4125b191cbf773832dc51f424cf2b6bb7da43007d1e066f95909e47cacd4",
                ),
                Download(
                    f"{_MR}/amd64/1789931006_9.0.2/ffprobe.zip",
                    33719233,
                    "2322438ed2f6319a691291b247d09c69dcaa3a982460d1f269a7e1af335cfdfd",
                ),
            ),
            {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe"},
            "GPL-3.0 (compilación con libx264/libx265)",
        ),
        "windows-x86_64": ToolSpec(
            "ffmpeg",
            FFMPEG_VERSION,
            (
                Download(
                    f"{_GYAN}/ffmpeg-9.0.2-essentials_build.zip",
                    114768076,
                    "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba",
                ),
            ),
            {
                "ffmpeg": "ffmpeg-9.0.2-essentials_build/bin/ffmpeg.exe",
                "ffprobe": "ffmpeg-9.0.2-essentials_build/bin/ffprobe.exe",
            },
            "GPL-3.0 (compilación «essentials» de Gyan Doshi)",
        ),
    },
}


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def tools_root(home: Path) -> Path:
    return home / "tools"


def spec_for(name: str) -> ToolSpec | None:
    return CATALOG.get(name, {}).get(_platform_key())


def tool_dir(home: Path, name: str) -> Path | None:
    spec = spec_for(name)
    return tools_root(home) / f"{name}-{spec.version}" if spec else None


def installed_executable(home: Path, name: str, exe: str | None = None) -> Path | None:
    """Ejecutable portátil ya instalado y verificado (``None`` si no está)."""
    spec = spec_for(name)
    directory = tool_dir(home, name)
    if spec is None or directory is None or not (directory / "vsa-tool.json").is_file():
        return None
    path = directory / spec.executables[exe or name]
    return path if path.is_file() else None


def node_version(node: str | Path) -> tuple[int, int, int] | None:
    try:
        out = subprocess.run(
            [str(node), "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        ).stdout.strip()
        major, minor, patch = (int(x) for x in out.lstrip("v").split(".")[:3])
        return major, minor, patch
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


_SUITABLE: dict[tuple[str, float], bool] = {}


def node_is_suitable(node: str | Path) -> bool:
    """Versión de Node compatible (con caché por ruta y fecha del ejecutable)."""
    path = Path(node)
    try:
        key = (str(path.resolve()), path.stat().st_mtime)
    except OSError:
        return False
    if key not in _SUITABLE:
        version = node_version(path)
        _SUITABLE[key] = version is not None and version[:2] >= NODE_MIN
    return _SUITABLE[key]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(4 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def _fetch(d: Download, dest: Path, on_bytes: Callable[[int], None] | None = None) -> None:
    req = urllib.request.Request(d.url, headers={"User-Agent": "VideoStudioAI-Community"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
        while block := resp.read(1024 * 1024):
            out.write(block)
            if on_bytes:
                on_bytes(len(block))
    if d.size and dest.stat().st_size != d.size:
        raise ToolError("size", f"Descarga incompleta: {d.url}")
    if _sha256(dest) != d.sha256:
        raise ToolError("checksum", f"La huella SHA-256 no coincide: {d.url}. Descarga descartada.")


def safe_extract(archive: Path, target: Path) -> None:
    """Extrae sin permitir rutas que salgan de ``target`` (zip/tar maliciosos)."""
    root = target.resolve()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                dest = (target / member.filename).resolve()
                if not dest.is_relative_to(root):
                    raise ToolError("archive", f"Ruta no permitida en {archive.name}")
                zf.extract(member, target)
                # zipfile no conserva los permisos POSIX: se restauran (ejecutables).
                mode = (member.external_attr >> 16) & 0o777
                if mode and os.name != "nt":
                    os.chmod(dest, mode)
    else:
        with tarfile.open(archive) as tf:
            tf.extractall(target, filter="data")


def _verify_mac_signature(path: Path) -> None:
    try:
        out = subprocess.run(
            ["codesign", "-dv", "--verbose=2", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        ok = (
            subprocess.run(
                ["codesign", "--verify", "--strict", str(path)], capture_output=True, timeout=60
            ).returncode
            == 0
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ToolError("codesign", f"No se pudo comprobar la firma de {path.name}") from exc
    if not ok or f"TeamIdentifier={MAC_FFMPEG_TEAM}" not in out.stderr:
        raise ToolError("codesign", f"La firma de {path.name} no es la esperada.")


def install(home: Path, name: str, on_progress: Callable[[float, str], None] | None = None) -> Path:
    """Descarga, verifica e instala una herramienta portátil. Idempotente."""
    spec = spec_for(name)
    directory = tool_dir(home, name)
    if spec is None or directory is None:
        raise ToolError(
            "unsupported",
            f"No hay una descarga de {name} preparada para este sistema ({_platform_key()}).",
        )
    existing = installed_executable(home, name)
    if existing is not None:
        return existing
    tools_root(home).mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{name}-", dir=tools_root(home)))
    try:
        total = sum(d.size for d in spec.downloads) or 0
        done = 0

        def bump(n: int) -> None:
            nonlocal done
            done += n
            if on_progress and total:
                on_progress(min(0.95, done / total), f"Descargando {name}")

        staging = work / "out"
        staging.mkdir()
        for i, d in enumerate(spec.downloads):
            archive = work / f"{i}-{d.url.rsplit('/', 1)[-1]}"
            _fetch(d, archive, bump)
            safe_extract(archive, staging)
        for rel in spec.executables.values():
            exe = staging / rel
            if not exe.is_file():
                raise ToolError("layout", f"La descarga de {name} no contiene {rel}.")
            if os.name != "nt":
                exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            if name == "ffmpeg" and detect().os == "macos":
                _verify_mac_signature(exe)
        manifest: dict[str, Any] = {
            "name": name,
            "version": spec.version,
            "downloads": [{"url": d.url, "sha256": d.sha256} for d in spec.downloads],
            "license": spec.license,
            "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        (staging / "vsa-tool.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if directory.exists():
            shutil.rmtree(directory, onexc=_force_remove)
        os.replace(staging, directory)
        if on_progress:
            on_progress(1.0, f"{name} {spec.version} instalado")
        exe_path = installed_executable(home, name)
        assert exe_path is not None
        return exe_path
    finally:
        shutil.rmtree(work, onexc=_force_remove)


def _force_remove(func: Callable[..., Any], path: str, _exc: BaseException) -> None:
    """En Windows los archivos de solo lectura no se pueden borrar sin quitar el atributo."""
    with contextlib.suppress(OSError):
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        func(path)


def remove(home: Path, name: str) -> None:
    directory = tool_dir(home, name)
    if directory and directory.exists():
        shutil.rmtree(directory, onexc=_force_remove)


def describe(home: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in CATALOG:
        spec = spec_for(name)
        exe = installed_executable(home, name)
        out[name] = {
            "available_for_platform": spec is not None,
            "version": spec.version if spec else None,
            "installed": exe is not None,
            "path": str(exe) if exe else None,
        }
    return out
