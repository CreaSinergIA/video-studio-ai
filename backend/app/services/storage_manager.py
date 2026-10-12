"""Registro de raíces de almacenamiento y comprobación de disponibilidad (con caché corta)."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import StorageLocation, utcnow
from app.services import app_settings
from app.services.storage import (
    StorageError,
    StorageStatus,
    check_root,
    cleanup_stale_uploads,
    initialize_root,
)

log = logging.getLogger(__name__)

_CACHE_TTL = 2.0


class StorageManager:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, StorageStatus]] = {}
        self._lock = threading.Lock()

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()

    def status_for(self, location: StorageLocation, fresh: bool = False) -> StorageStatus:
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(location.id)
            if cached and not fresh and now - cached[0] < _CACHE_TTL:
                return cached[1]
        status = check_root(Path(location.path), location.id)
        with self._lock:
            self._cache[location.id] = (now, status)
        return status

    def active_location(self, session: Session) -> StorageLocation | None:
        storage_id = app_settings.get_active_storage_id(session)
        return session.get(StorageLocation, storage_id) if storage_id else None

    def active_status(self, session: Session, fresh: bool = False) -> StorageStatus:
        location = self.active_location(session)
        if location is None:
            return StorageStatus(
                configured=False,
                available=False,
                code="not_configured",
                message="Elige dónde guardar los videos para empezar.",
            )
        status = self.status_for(location, fresh=fresh)
        if status.available and (
            location.last_seen_at is None
            or (utcnow() - location.last_seen_at).total_seconds() > 300
        ):
            location.last_seen_at = utcnow()
        return status

    def require_active(self, session: Session) -> tuple[StorageLocation, Path]:
        location = self.active_location(session)
        if location is None:
            raise StorageError(
                "not_configured", "Configura primero la carpeta de almacenamiento.", 409
            )
        return location, self.require_location(location)

    def require_location(self, location: StorageLocation) -> Path:
        status = self.status_for(location)
        if not status.available:
            # Revalidar sin caché antes de rechazar (el disco pudo reconectarse).
            status = self.status_for(location, fresh=True)
        if not status.available:
            raise StorageError(
                status.code or "storage_unavailable",
                status.message or "Almacenamiento no disponible.",
                503,
            )
        return Path(location.path)

    def configure(self, session: Session, raw_path: str) -> tuple[StorageLocation, Path]:
        root, marker = initialize_root(raw_path)
        storage_id = marker["storage_id"]
        location = session.get(StorageLocation, storage_id)
        if location is None:
            location = StorageLocation(id=storage_id, path=str(root))
            session.add(location)
        elif location.path != str(root):
            log.info("Almacenamiento %s movido: %s → %s", storage_id, location.path, root)
            location.path = str(root)
        location.last_seen_at = utcnow()
        app_settings.set_active_storage_id(session, storage_id)
        session.flush()
        self.invalidate()
        cleanup_stale_uploads(root)
        return location, root


storage_manager = StorageManager()
