"""Configuración de proceso (variables de entorno) y rutas de datos de la aplicación.

La configuración de *usuario* (almacenamiento, preferencias, presets) vive en SQLite;
aquí solo está lo que debe conocerse antes de abrir la base de datos.
"""

from __future__ import annotations

import ipaddress
import os
import shutil
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app import edition
from app.platform import paths

APP_NAME = "Video Studio AI"
APP_VERSION = "0.6.0"

DEFAULT_PORT = edition.DEFAULT_PORT


def _default_home() -> Path:
    """Directorio de datos propio de esta edición según la plataforma (ver app.platform)."""
    return paths.default_data_dir()


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Settings:
    home: Path
    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    frontend_dist: Path | None = None
    dev_origins: tuple[str, ...] = ()
    extra_allowed_hosts: tuple[str, ...] = field(default_factory=tuple)
    max_concurrent_jobs: int = 2
    models_dir_override: Path | None = None

    @property
    def db_path(self) -> Path:
        return self.home / "app.db"

    @property
    def models_dir(self) -> Path:
        """Modelos locales (disco interno por defecto; ``VSA_MODELS_DIR`` para compartirlos)."""
        return self.models_dir_override or self.home / "models"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def allowed_hosts(self) -> list[str]:
        return ["127.0.0.1", "localhost", "::1", "[::1]", *self.extra_allowed_hosts]


def _resolve_binary(name: str, env_var: str, home: Path | None = None) -> str:
    explicit = os.environ.get(env_var)
    if explicit:
        return explicit
    # Copia portátil instalada por el instalador (versión fijada y verificada).
    if home is not None:
        from app.platform import tools

        portable = tools.installed_executable(home, "ffmpeg", name)
        if portable is not None:
            return str(portable)
    found = shutil.which(name)
    if found:
        return found
    # Homebrew en Apple Silicon no siempre está en el PATH de procesos lanzados desde Finder.
    for candidate in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}", f"/usr/bin/{name}"):
        if Path(candidate).exists():
            return candidate
    return name


def load_settings() -> Settings:
    home = Path(os.environ.get("VSA_HOME") or _default_home()).expanduser()
    host = os.environ.get("VSA_HOST", "127.0.0.1")
    if not _is_loopback(host):
        raise RuntimeError(
            f"VSA_HOST={host!r} no es una dirección local. Video Studio AI solo escucha en "
            "localhost; para un VPS use un proxy inverso con autenticación delante."
        )
    dist_env = os.environ.get("VSA_FRONTEND_DIST")
    default_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    frontend_dist = Path(dist_env) if dist_env else default_dist
    origins = tuple(
        o.strip()
        # Vacío por defecto: el panel se sirve desde el mismo origen (y en desarrollo Vite usa
        # un proxy), así que no hace falta CORS. Solo se abre si se pide explícitamente.
        for o in os.environ.get("VSA_DEV_ORIGINS", "").split(",")
        if o.strip()
    )
    extra_hosts = tuple(
        h.strip() for h in os.environ.get("VSA_EXTRA_HOSTS", "").split(",") if h.strip()
    )
    return Settings(
        home=home,
        host=host,
        port=int(os.environ.get("VSA_PORT", DEFAULT_PORT)),
        ffmpeg=_resolve_binary("ffmpeg", "VSA_FFMPEG", home),
        ffprobe=_resolve_binary("ffprobe", "VSA_FFPROBE", home),
        frontend_dist=frontend_dist,
        dev_origins=origins,
        extra_allowed_hosts=extra_hosts,
        max_concurrent_jobs=max(1, int(os.environ.get("VSA_MAX_JOBS", 2))),
        models_dir_override=Path(os.environ["VSA_MODELS_DIR"]).expanduser()
        if os.environ.get("VSA_MODELS_DIR")
        else None,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
