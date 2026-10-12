"""Almacenamiento de archivos audiovisuales (normalmente en un disco externo).

Garantías:
- Nunca se crean carpetas padre de una raíz inexistente: si el disco no está montado, una
  ruta como ``/Volumes/MiDisco/VideoStudio`` NO se recrea en el disco del sistema.
- La raíz se identifica con un marcador ``.videostudio.json`` (id estable). Si el marcador no
  existe o no coincide, la raíz se considera no disponible.
- Toda ruta relativa se resuelve y se comprueba que quede dentro de la raíz.
- Las escrituras de metadatos son atómicas (archivo temporal + fsync + ``os.replace``).
- Solo se borran carpetas de proyecto que contienen su propio manifiesto con el id esperado.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import secrets
import shutil
import stat
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

log = logging.getLogger(__name__)

MARKER_NAME = ".videostudio.json"
LAYOUT_VERSION = 1
PROJECTS_DIR = "projects"
CACHE_DIR = "cache"
UPLOADS_DIR = f"{CACHE_DIR}/uploads"
TRASH_DIR = f"{CACHE_DIR}/trash"
PROJECT_MANIFEST = "project.json"
# Subcarpetas por proyecto. Las de fases futuras se crean ya para fijar el contrato de rutas.
PROJECT_SUBDIRS = (
    "originals",  # copias inmutables de los videos importados
    "frames",  # miniaturas, tira de fotogramas (y en Fase 2 fotogramas de análisis)
    "analysis",  # forma de onda (Fase 1); escenas y audio (Fase 2)
    "transcripts",  # Fase 2
    "plans",  # Fase 3 (plan de trabajo y contratos aprobados para la Fase 4)
    "animations",  # Fase 4 (código y renders de animaciones)
    "previews",  # proxies de reproducción (Fase 1) y previsualizaciones (Fase 4)
    "exports",  # Fase 5
)
# Margen de seguridad para no llenar el disco por completo.
MIN_FREE_MARGIN_BYTES = 512 * 1024 * 1024


class StorageError(Exception):
    """Error de almacenamiento con código estable para el frontend."""

    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Utilidades de rutas y nombres
# ---------------------------------------------------------------------------


def normalize_user_path(raw: str) -> Path:
    raw = (raw or "").strip()
    if not raw:
        raise StorageError("path_invalid", "Indica una ruta.", 422)
    if "\x00" in raw:
        raise StorageError("path_invalid", "La ruta contiene caracteres no válidos.", 422)
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise StorageError(
            "path_invalid", "La ruta debe ser absoluta (p. ej. /Volumes/… o D:\\…).", 422
        )
    # abspath normaliza «..» sin seguir enlaces ni exigir que exista.
    return Path(os.path.abspath(path))


def resolve_inside(root: Path, rel: str) -> Path:
    """Une ``rel`` a ``root`` impidiendo path traversal y rutas absolutas."""
    if not rel or "\x00" in rel:
        raise StorageError("path_invalid", "Ruta relativa no válida.", 400)
    pure = PurePosixPath(rel)
    if pure.is_absolute() or any(part in ("..", "") for part in pure.parts):
        raise StorageError("path_invalid", "Ruta relativa no permitida.", 400)
    root_resolved = root.resolve()
    candidate = (root_resolved / Path(*pure.parts)).resolve()
    if not candidate.is_relative_to(root_resolved):
        raise StorageError("path_invalid", "La ruta sale del almacenamiento.", 400)
    return candidate


_UNSAFE_CHARS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


def sanitize_filename(name: str, max_length: int = 150) -> str:
    """Nombre de archivo seguro y portable, conservando la extensión."""
    name = unicodedata.normalize("NFC", os.path.basename(name.replace("\\", "/")))
    name = _UNSAFE_CHARS.sub("_", name).strip().strip(".")
    if not name:
        name = "video"
    stem, ext = os.path.splitext(name)
    ext = ext.lower()[:10]
    stem = stem[: max(1, max_length - len(ext))].rstrip() or "video"
    return f"{stem}{ext}"


def slugify(text: str, max_length: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_length].strip("-") or "proyecto"


def to_rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


# ---------------------------------------------------------------------------
# Escritura atómica
# ---------------------------------------------------------------------------


def _fsync_dir(directory: Path) -> None:
    if sys.platform == "win32":  # pragma: no cover
        return
    with contextlib.suppress(OSError):
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    # Sin crear carpetas: si el destino desapareció (disco desconectado o proyecto borrado)
    # la escritura debe fallar en lugar de recrear rutas.
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()


def atomic_write_json(path: Path, payload: Any) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    atomic_write_bytes(path, data)


def read_json(path: Path) -> Any | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Estado e inspección de raíces
# ---------------------------------------------------------------------------


def _windows_external_drive(path: Path) -> str | None:
    """Windows: unidad distinta de la del sistema (``D:``, ``E:``…), típica de discos externos."""
    drive = path.drive.upper()
    system = os.environ.get("SYSTEMDRIVE", "C:").upper()
    return drive if drive and drive != system and not drive.startswith("\\\\") else None


def _volume_hint(path: Path) -> str | None:
    """Nombre del volumen si la ruta está en un punto de montaje típico de discos externos."""
    if sys.platform == "win32":
        return _windows_external_drive(path)
    parts = path.parts
    if sys.platform == "darwin" and len(parts) >= 3 and parts[1] == "Volumes":
        return parts[2]
    if len(parts) >= 4 and parts[1] == "media":
        return parts[3]
    if len(parts) >= 3 and parts[1] in ("mnt", "media"):
        return parts[2]
    return None


def _volume_root(path: Path) -> Path | None:
    hint = _volume_hint(path)
    if hint is None:
        return None
    if sys.platform == "win32":
        return Path(path.anchor)
    parts = path.parts
    idx = parts.index(hint)
    return Path(*parts[: idx + 1])


def _mount_point(path: Path) -> Path:
    current = path
    while not current.exists():
        current = current.parent
    current = current.resolve()
    while not os.path.ismount(current) and current != current.parent:
        current = current.parent
    return current


def is_external_path(path: Path) -> bool:
    volume_root = _volume_root(path)
    if volume_root is None:
        return False
    with contextlib.suppress(OSError):
        return _mount_point(path) != Path("/") and os.path.ismount(_mount_point(path))
    return False


def disk_usage(path: Path) -> tuple[int, int]:
    usage = shutil.disk_usage(path)
    return usage.free, usage.total


def _probe_writable(directory: Path) -> bool:
    probe = directory / f".vsa-write-test-{secrets.token_hex(4)}"
    try:
        with open(probe, "wb") as fh:
            fh.write(b"ok")
            fh.flush()
            os.fsync(fh.fileno())
        probe.unlink()
        return True
    except OSError:
        with contextlib.suppress(OSError):
            probe.unlink()
        return False


def read_marker(root: Path) -> dict[str, Any] | None:
    data = read_json(root / MARKER_NAME)
    if isinstance(data, dict) and isinstance(data.get("storage_id"), str):
        return data
    return None


@dataclass
class StorageStatus:
    configured: bool
    available: bool
    path: str | None = None
    storage_id: str | None = None
    code: str | None = None
    message: str | None = None
    writable: bool = False
    free_bytes: int | None = None
    total_bytes: int | None = None
    volume_name: str | None = None
    is_external: bool = False
    checked_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_root(root: Path, expected_id: str | None, write_test: bool = False) -> StorageStatus:
    """Estado de una raíz configurada. No crea nada en disco."""
    status = StorageStatus(
        configured=True,
        available=False,
        path=str(root),
        storage_id=expected_id,
        volume_name=_volume_hint(root),
    )
    volume_root = _volume_root(root)
    if volume_root is not None and not volume_root.exists():
        status.code = "volume_disconnected"
        status.message = (
            f"El disco «{status.volume_name}» no está conectado. Conéctalo para acceder a los "
            "videos; los proyectos y ajustes siguen a salvo."
        )
        return status
    if not root.exists():
        status.code = "path_missing"
        status.message = f"La carpeta de almacenamiento no existe: {root}"
        return status
    if not root.is_dir():
        status.code = "not_a_directory"
        status.message = "La ruta de almacenamiento no es una carpeta."
        return status
    marker = read_marker(root)
    if marker is None:
        status.code = "marker_missing"
        status.message = (
            "La carpeta existe pero no contiene el marcador de Video Studio "
            f"({MARKER_NAME}). ¿Es la carpeta correcta?"
        )
        return status
    if expected_id is not None and marker.get("storage_id") != expected_id:
        status.code = "marker_mismatch"
        status.message = "La carpeta pertenece a otro almacenamiento de Video Studio."
        return status
    status.storage_id = marker["storage_id"]
    status.is_external = is_external_path(root)
    try:
        status.free_bytes, status.total_bytes = disk_usage(root)
    except OSError as exc:
        status.code = "io_error"
        status.message = f"No se pudo leer el disco: {exc.strerror or exc}"
        return status
    status.writable = _probe_writable(root) if write_test else os.access(root, os.W_OK)
    if not status.writable:
        status.code = "not_writable"
        status.message = "No hay permisos de escritura en la carpeta de almacenamiento."
        return status
    status.available = True
    return status


@dataclass
class CandidateReport:
    path: str
    exists: bool
    parent_exists: bool
    is_dir: bool
    writable: bool
    has_marker: bool
    storage_id: str | None
    project_count: int
    is_empty: bool
    free_bytes: int | None
    total_bytes: int | None
    volume_name: str | None
    is_external: bool
    can_use: bool
    warnings: list[str]
    errors: list[str]
    suggested_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _visible_entries(directory: Path) -> list[str]:
    try:
        return [
            name
            for name in os.listdir(directory)
            if not name.startswith(".")
            and name not in ("$RECYCLE.BIN", "System Volume Information")
        ]
    except OSError:
        return []


def inspect_candidate(raw_path: str) -> CandidateReport:
    path = normalize_user_path(raw_path)
    warnings: list[str] = []
    errors: list[str] = []
    exists = path.exists()
    parent_exists = path.parent.exists()
    is_dir = path.is_dir()
    volume_name = _volume_hint(path)
    volume_root = _volume_root(path)
    marker = read_marker(path) if is_dir else None
    project_count = 0
    if marker:
        projects_dir = path / PROJECTS_DIR
        if projects_dir.is_dir():
            project_count = sum(
                1 for p in projects_dir.iterdir() if (p / PROJECT_MANIFEST).is_file()
            )
    entries = _visible_entries(path) if is_dir else []
    is_empty = is_dir and not entries
    target_for_checks = path if exists else path.parent
    free = total = None
    writable = False
    suggested: str | None = None

    if volume_root is not None and not volume_root.exists():
        errors.append(f"El disco «{volume_name}» no está conectado.")
    elif exists and not is_dir:
        errors.append("La ruta apunta a un archivo, no a una carpeta.")
    elif not exists and not parent_exists:
        errors.append(
            "Ni la carpeta ni su carpeta superior existen. Por seguridad solo se crea el "
            "último nivel de la ruta."
        )
    else:
        try:
            free, total = disk_usage(target_for_checks)
        except OSError as exc:
            errors.append(f"No se pudo leer el disco: {exc.strerror or exc}")
        writable = _probe_writable(target_for_checks) if not errors else False
        if not errors and not writable:
            errors.append("No hay permisos de escritura en esta ubicación.")
    if not errors:
        if marker is None and is_dir and not is_empty:
            suggested = str(path / "VideoStudio")
            warnings.append(
                "La carpeta ya contiene otros archivos. Se recomienda usar una subcarpeta "
                "dedicada (p. ej. «VideoStudio») para no mezclar archivos."
            )
        if volume_root is None and sys.platform in ("darwin", "win32"):
            warnings.append(
                "La ruta está en el disco del sistema, no en un disco externo. Funciona, pero los "
                "videos ocuparán espacio interno."
            )
        if free is not None and free < 10 * 1024**3:
            warnings.append("Queda poco espacio libre (menos de 10 GB).")
    return CandidateReport(
        path=str(path),
        exists=exists,
        parent_exists=parent_exists,
        is_dir=is_dir,
        writable=writable,
        has_marker=marker is not None,
        storage_id=marker.get("storage_id") if marker else None,
        project_count=project_count,
        is_empty=is_empty,
        free_bytes=free,
        total_bytes=total,
        volume_name=volume_name,
        is_external=bool(volume_root and volume_root.exists() and is_external_path(path)),
        can_use=not errors,
        warnings=warnings,
        errors=errors,
        suggested_path=suggested,
    )


def initialize_root(raw_path: str) -> tuple[Path, dict[str, Any]]:
    """Prepara una raíz (crea solo el último nivel) y devuelve (ruta, marcador)."""
    report = inspect_candidate(raw_path)
    if not report.can_use:
        raise StorageError("path_unusable", " ".join(report.errors), 422)
    root = Path(report.path)
    if not root.exists():
        root.mkdir()  # sin parents=True a propósito
    marker = read_marker(root)
    if marker is None:
        marker = {
            "app": "video-studio-ai",
            "storage_id": f"stg_{secrets.token_hex(8)}",
            "layout_version": LAYOUT_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "note": "Carpeta gestionada por Video Studio AI. No borres este archivo.",
        }
        atomic_write_json(root / MARKER_NAME, marker)
    for rel in (PROJECTS_DIR, CACHE_DIR, UPLOADS_DIR):
        (root / rel).mkdir(exist_ok=True)
    return root, marker


def ensure_project_dirs(project_dir: Path) -> None:
    project_dir.mkdir(exist_ok=True)
    for sub in PROJECT_SUBDIRS:
        (project_dir / sub).mkdir(exist_ok=True)


def require_space(root: Path, needed_bytes: int) -> None:
    free, _ = disk_usage(root)
    if needed_bytes + MIN_FREE_MARGIN_BYTES > free:
        raise StorageError(
            "insufficient_space",
            f"Espacio insuficiente: se necesitan {_fmt_bytes(needed_bytes)} y quedan "
            f"{_fmt_bytes(free)} libres (se reservan {_fmt_bytes(MIN_FREE_MARGIN_BYTES)}).",
            507,
        )


def _fmt_bytes(n: int) -> str:
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{n} B"  # pragma: no cover


def rmtree_tolerant(path: Path, attempts: int = 3) -> bool:
    """``rmtree`` que tolera archivos que desaparecen durante el borrado.

    En volúmenes exFAT/FAT, macOS guarda los atributos extendidos en archivos AppleDouble
    (``._nombre``) y los elimina por su cuenta al borrar el archivo principal: ``rmtree``
    los ve en el listado y falla con FileNotFoundError al intentar borrarlos.
    """

    def onexc(func: Any, failed: str, exc: BaseException) -> None:
        if isinstance(exc, FileNotFoundError):
            return
        # Windows no borra archivos de solo lectura (los originales importados lo son): se
        # quita el atributo y se reintenta. En macOS/Linux el permiso del directorio basta.
        if isinstance(exc, PermissionError) and sys.platform == "win32":
            os.chmod(failed, stat.S_IWRITE | stat.S_IREAD)
            func(failed)
            return
        raise exc

    for _ in range(attempts):
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(path, onexc=onexc)
        if not path.exists():
            return True
        time.sleep(0.1)
    return not path.exists()


def stage_project_delete(root: Path, dir_rel: str, project_id: str) -> Path | None:
    """Aparta la carpeta de un proyecto para borrarla, solo si es inequívocamente suya.

    Mueve la carpeta (``os.rename``, misma unidad: atómico) a ``cache/trash/`` y devuelve la
    ruta apartada; el borrado físico se hace después con :func:`purge_staged`, fuera de la
    transacción de base de datos. Si algo interrumpe el borrado, la papelera se vacía al
    arrancar: nunca queda un proyecto a medio borrar dentro de ``projects/``.

    Devuelve None si la carpeta ya no existe. Lanza StorageError si algo no cuadra (nunca
    toca archivos ajenos).
    """
    if (root / dir_rel).is_symlink():
        raise StorageError("unsafe_delete", "La carpeta es un enlace simbólico.", 409)
    target = resolve_inside(root, dir_rel)
    projects_root = (root / PROJECTS_DIR).resolve()
    if target.parent != projects_root:
        raise StorageError("unsafe_delete", "La carpeta no está en projects/.", 409)
    if not target.exists():
        return None
    manifest = read_json(target / PROJECT_MANIFEST)
    if not isinstance(manifest, dict) or manifest.get("project_id") != project_id:
        raise StorageError(
            "unsafe_delete",
            "La carpeta no contiene el manifiesto de este proyecto; no se borra por seguridad.",
            409,
        )
    trash = root / TRASH_DIR
    trash.mkdir(exist_ok=True)
    staged = trash / f"{target.name}.{secrets.token_hex(4)}"
    os.rename(target, staged)
    _fsync_dir(projects_root)
    with contextlib.suppress(OSError):
        (projects_root / f"._{target.name}").unlink()
    return staged


def unstage_project_delete(staged: Path, root: Path, dir_rel: str) -> None:
    """Deshace :func:`stage_project_delete` (p. ej. si la base de datos no pudo confirmar)."""
    os.rename(staged, resolve_inside(root, dir_rel))


def purge_staged(staged: Path) -> None:
    if not rmtree_tolerant(staged):
        log.warning("No se pudo vaciar %s; se reintentará al arrancar", staged)


def remove_project_dir(root: Path, dir_rel: str, project_id: str) -> bool:
    """Aparta y borra la carpeta de un proyecto (ver :func:`stage_project_delete`)."""
    staged = stage_project_delete(root, dir_rel, project_id)
    if staged is None:
        return False
    purge_staged(staged)
    return True


def cleanup_trash(root: Path) -> int:
    """Termina borrados interrumpidos (contenido de cache/trash)."""
    trash = root / TRASH_DIR
    if not trash.is_dir():
        return 0
    removed = 0
    for entry in trash.iterdir():
        if entry.name.startswith("._"):
            with contextlib.suppress(OSError):
                entry.unlink()
            continue
        if entry.is_dir() and not entry.is_symlink():
            removed += int(rmtree_tolerant(entry))
        else:
            with contextlib.suppress(OSError):
                entry.unlink()
                removed += 1
    return removed


def cleanup_stale_uploads(root: Path, max_age_seconds: int = 6 * 3600) -> int:
    """Elimina subidas incompletas antiguas (``*.partial``) de cache/uploads."""
    uploads = root / UPLOADS_DIR
    if not uploads.is_dir():
        return 0
    removed = 0
    now = time.time()
    for entry in uploads.iterdir():
        name = entry.name
        if name.startswith("._"):
            # Archivos AppleDouble que macOS crea en volúmenes exFAT.
            with contextlib.suppress(OSError):
                entry.unlink()
            continue
        if not name.endswith(".partial"):
            continue
        with contextlib.suppress(OSError):
            if now - entry.stat().st_mtime > max_age_seconds:
                entry.unlink()
                removed += 1
    if removed:
        log.info("Eliminadas %d subidas incompletas en %s", removed, uploads)
    return removed
