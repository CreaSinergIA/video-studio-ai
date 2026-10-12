"""Protección de datos (Fase 5): identificación del entorno y copias de seguridad de la base.

Entornos
    Cada directorio de datos (``VSA_HOME``) lleva una marca ``environment.json`` con su tipo:
    ``user`` (la instancia real del usuario) o ``test`` (pruebas). La aplicación se niega a
    arrancar si el tipo pedido (``VSA_ENV``) no coincide con la marca, y un entorno de pruebas
    nunca puede apuntar al directorio de datos del usuario. Así una prueba no puede escribir,
    migrar ni limpiar datos reales por error, y una limpieza de pruebas puede comprobar la marca
    antes de borrar (``assert_disposable``).

Copias de seguridad
    - Antes de aplicar una migración pendiente (``pre-migracion-…``).
    - Automáticas al arrancar si la última tiene más de 20 h (``auto-…``; se conservan 7).
    - Manuales desde Ajustes (``manual-…``) y antes de restaurar (``antes-de-restaurar-…``).
    Se hacen con la API de copia en caliente de SQLite (coherente con WAL) y se verifican con
    ``PRAGMA integrity_check``. Las copias manuales y previas nunca se borran solas.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

MARKER = "environment.json"
EnvKind = Literal["user", "test"]
AUTO_KEEP = 7
AUTO_EVERY_S = 20 * 3600
# Estado del último arranque (entorno e integridad), expuesto en /api/health.
STATE: dict[str, str] = {}
_NAME = re.compile(r"^(auto|manual|pre-migracion|antes-de-restaurar|pre-fase)[\w.\-]*\.db$")


class EnvironmentError_(RuntimeError):
    """El directorio de datos no corresponde al entorno pedido."""


def default_home() -> Path:
    from app.config import _default_home

    return _default_home().expanduser().resolve()


def requested_kind(home: Path) -> EnvKind:
    raw = (os.environ.get("VSA_ENV") or "").strip().lower()
    if raw in ("test", "pruebas"):
        return "test"
    if raw in ("user", "usuario"):
        return "user"
    # Sin indicación: el directorio por defecto es el del usuario; uno explícito se trata como
    # de pruebas solo si ya está marcado así.
    marker = read_marker(home)
    return "test" if marker and marker["kind"] == "test" else "user"


def read_marker(home: Path) -> dict[str, str] | None:
    try:
        data = json.loads((home / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data.get("kind") in ("user", "test"):
        return data
    return None


def ensure_environment(home: Path, version: str) -> EnvKind:
    """Comprueba (y si falta, crea) la marca del entorno. Lanza si hay incoherencia."""
    home = home.expanduser()
    kind = requested_kind(home)
    try:
        is_default = home.resolve() == default_home()
    except OSError:
        is_default = False
    if kind == "test" and is_default:
        raise EnvironmentError_(
            "VSA_ENV=test apunta al directorio de datos del usuario "
            f"({home}). Las pruebas deben usar su propio VSA_HOME."
        )
    marker = read_marker(home)
    if marker and marker["kind"] != kind:
        raise EnvironmentError_(
            f"El directorio de datos {home} está marcado como entorno «{marker['kind']}» y se "
            f"pidió «{kind}». No se arranca para no mezclar datos reales y de prueba."
        )
    if marker is None:
        home.mkdir(parents=True, exist_ok=True)
        (home / MARKER).write_text(
            json.dumps(
                {"kind": kind, "created_at": datetime.now(UTC).isoformat(), "app_version": version},
                indent=1,
            ),
            encoding="utf-8",
        )
    return kind


def assert_disposable(home: Path) -> None:
    """Antes de borrar un directorio de datos de pruebas: debe estar marcado como «test» y no
    ser el del usuario. Lanza si no se puede demostrar que es desechable."""
    home = home.expanduser()
    if home.resolve() == default_home():
        raise EnvironmentError_(f"{home} es el directorio de datos del usuario.")
    marker = read_marker(home)
    if not marker or marker["kind"] != "test":
        raise EnvironmentError_(f"{home} no está marcado como entorno de pruebas; no se borra.")


# ---------------------------------------------------------------------------
# Copias de seguridad
# ---------------------------------------------------------------------------


@dataclass
class Backup:
    name: str
    path: Path
    kind: str
    size: int
    created_at: datetime


def backups_dir(home: Path) -> Path:
    d = home / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def create_backup(db_path: Path, home: Path, kind: str, label: str = "") -> Backup:
    """Copia en caliente y verificada de la base. ``kind``: auto, manual, pre-migracion,
    antes-de-restaurar."""
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    suffix = f"-{re.sub(r'[^0-9A-Za-z_.]+', '-', label)[:40]}" if label else ""
    target = backups_dir(home) / f"{kind}-{_stamp()}{suffix}.db"
    n = 1
    while target.exists():
        n += 1
        target = target.with_name(f"{kind}-{_stamp()}{suffix}-{n}.db")
    tmp = target.with_suffix(".partial")
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)
    try:
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
            ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
    finally:
        src.close()
    if ok != "ok":
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"La copia de seguridad no superó la verificación: {ok}")
    os.replace(tmp, target)
    log.info("Copia de seguridad %s creada", target.name)
    return _info(target)


def _info(path: Path) -> Backup:
    st = path.stat()
    kind = next(
        (k for k in ("pre-migracion", "antes-de-restaurar", "pre-fase", "manual", "auto")
         if path.name.startswith(k)),
        "otra",
    )  # fmt: skip
    return Backup(path.name, path, kind, st.st_size, datetime.fromtimestamp(st.st_mtime, UTC))


def list_backups(home: Path) -> list[Backup]:
    d = backups_dir(home)
    out = [_info(p) for p in d.glob("*.db") if p.is_file()]
    return sorted(out, key=lambda b: b.created_at, reverse=True)


def prune_auto(home: Path, keep: int = AUTO_KEEP) -> int:
    autos = [b for b in list_backups(home) if b.kind == "auto"]
    removed = 0
    for b in autos[keep:]:
        try:
            b.path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def auto_backup_if_due(db_path: Path, home: Path) -> Backup | None:
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return None
    autos = [b for b in list_backups(home) if b.kind == "auto"]
    if autos and time.time() - autos[0].created_at.timestamp() < AUTO_EVERY_S:
        return None
    b = create_backup(db_path, home, "auto")
    prune_auto(home)
    return b


def resolve_backup(home: Path, name: str) -> Path:
    if not _NAME.match(name) or "/" in name:
        raise FileNotFoundError(name)
    path = backups_dir(home) / name
    if not path.is_file():
        raise FileNotFoundError(name)
    return path


def verify(path: Path) -> str:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return str(con.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        con.close()


def restore_into(live_db: Path, backup: Path) -> None:
    """Restaura en caliente (API de copia de SQLite sobre la base en uso). Quien llama debe
    haber detenido las tareas y hacer antes una copia «antes-de-restaurar»."""
    if verify(backup) != "ok":
        raise RuntimeError("La copia elegida está dañada; no se restaura.")
    src = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(live_db, timeout=30)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
