"""Motor SQLite, sesiones y migraciones (Alembic se ejecuta al arrancar)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _set_sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def init_engine(database_url: str) -> Engine:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    event.listen(engine, "connect", _set_sqlite_pragmas)
    _engine = engine
    _session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    return engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Base de datos no inicializada")
    return _engine


def _alembic_config(database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.attributes["configure_logger"] = False
    return cfg


def pending_migrations(database_url: str) -> list[str]:
    """Revisiones aún no aplicadas (vacío si la base está al día o todavía no existe)."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_alembic_config(database_url))
    with get_engine().connect() as conn:
        current = MigrationContext.configure(conn).get_current_heads()
    if not current:
        return []
    return [
        rev.revision
        for rev in script.iterate_revisions("heads", current[0])
        if rev.revision not in current
    ]


def run_migrations(database_url: str) -> None:
    command.upgrade(_alembic_config(database_url), "head")


def check_integrity() -> str:
    with get_engine().connect() as conn:
        return str(conn.execute(text("PRAGMA quick_check")).scalar())


@contextmanager
def session_scope() -> Iterator[Session]:
    """Sesión transaccional para servicios y tareas en segundo plano."""
    if _session_factory is None:
        raise RuntimeError("Base de datos no inicializada")
    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """Dependencia de FastAPI."""
    with session_scope() as session:
        yield session
