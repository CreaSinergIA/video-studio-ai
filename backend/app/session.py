"""Protección de la API local con un token de sesión.

El servidor solo escucha en 127.0.0.1, pero cualquier programa u otra cuenta del mismo equipo
podría llamar a la API. Para evitarlo, todas las rutas ``/api/*`` (salvo ``/api/health``)
exigen un token secreto:

- Se genera al instalar o al primer arranque y se guarda en ``<datos>/run/session.token``,
  legible solo por el usuario (permisos 0600 en macOS/Linux; en Windows, la carpeta de datos
  de ``%LOCALAPPDATA%`` ya es privada de la cuenta).
- El lanzador abre el panel en ``/open?token=…``: el servidor comprueba el token, lo guarda en
  una cookie ``HttpOnly`` y ``SameSite=Strict`` (el JavaScript del panel no puede leerla y
  ninguna web de terceros puede enviarla) y redirige a ``/`` para quitarlo de la barra de
  direcciones.
- Scripts y pruebas pueden enviarlo en la cabecera ``X-VSA-Token``.

``VSA_SESSION_TOKEN`` fija el token (pruebas E2E). Borrar el archivo genera uno nuevo en el
siguiente arranque e invalida las sesiones abiertas.
"""

from __future__ import annotations

import contextlib
import hmac
import os
import secrets
from pathlib import Path

COOKIE = "vsa_session"
HEADER = "x-vsa-token"
COOKIE_MAX_AGE = 30 * 24 * 3600
PUBLIC_API = {"/api/health"}


def token_path(home: Path) -> Path:
    return home / "run" / "session.token"


def ensure_token(home: Path) -> str:
    env = os.environ.get("VSA_SESSION_TOKEN")
    if env:
        return env
    path = token_path(home)
    with contextlib.suppress(OSError):
        existing = path.read_text(encoding="utf-8").strip()
        if len(existing) >= 32:
            return existing
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    # Creado directamente con permisos 0600 (sin ventana en la que otro usuario pueda leerlo).
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token)
    return token


def read_token(home: Path) -> str | None:
    env = os.environ.get("VSA_SESSION_TOKEN")
    if env:
        return env
    try:
        return token_path(home).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def matches(candidate: str | None, token: str) -> bool:
    return bool(candidate) and hmac.compare_digest(str(candidate), token)
