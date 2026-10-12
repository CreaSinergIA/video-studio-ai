"""Logs de diagnóstico: consola + archivo rotativo en el directorio de datos."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s — %(message)s"


def configure_logging(logs_dir: Path, level: int = logging.INFO) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "videostudio.log"
    root = logging.getLogger()
    # Idempotente: evita duplicar handlers si la app se crea varias veces (tests, recarga).
    for handler in list(root.handlers):
        if getattr(handler, "_vsa", False):
            root.removeHandler(handler)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    stream_handler = logging.StreamHandler()
    handlers: tuple[logging.Handler, ...] = (file_handler, stream_handler)
    for handler in handlers:
        handler.setFormatter(logging.Formatter(_FORMAT))
        setattr(handler, "_vsa", True)  # noqa: B010 (marca para reconfigurar sin duplicar)
        root.addHandler(handler)
    root.setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    return log_file
