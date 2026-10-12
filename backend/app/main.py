"""Punto de entrada de la API de Video Studio AI."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from app import db
from app.api import (
    analysis,
    animations,
    imports,
    jobs,
    media,
    planning,
    presets,
    projects,
    scenes,
    storage,
    system,
)
from app.api.errors import install_error_handlers
from app.config import APP_NAME, APP_VERSION, Settings, get_settings
from app.jobs import (  # noqa: F401  (registra los tipos de tarea)
    analysis_jobs,
    animation_jobs,
    media_jobs,
    plan_jobs,
    scene_jobs,
)
from app.jobs.runner import runner
from app.logging_setup import configure_logging
from app.services import data_safety, exporter
from app.services import presets as preset_service
from app.services.storage import cleanup_stale_uploads, cleanup_trash
from app.services.storage_manager import storage_manager

log = logging.getLogger("videostudio")

CLIENT_HEADER = "x-vsa-client"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _startup(settings: Settings) -> str:
    settings.home.mkdir(parents=True, exist_ok=True)
    log_file = configure_logging(settings.logs_dir)
    kind = data_safety.ensure_environment(settings.home, APP_VERSION)
    log.info("%s %s — datos en %s (entorno %s)", APP_NAME, APP_VERSION, settings.home, kind)
    db.init_engine(settings.database_url)
    existed = settings.db_path.is_file() and settings.db_path.stat().st_size > 0
    if existed:
        pending = db.pending_migrations(settings.database_url)
        if pending:
            # Antes de cambiar el esquema, copia verificada de la base tal y como estaba.
            data_safety.create_backup(
                settings.db_path, settings.home, "pre-migracion", "-".join(pending)
            )
    db.run_migrations(settings.database_url)
    integrity = db.check_integrity()
    if integrity != "ok":
        log.error("La base de datos no supera la comprobación de integridad: %s", integrity)
    elif existed:
        try:
            data_safety.auto_backup_if_due(settings.db_path, settings.home)
        except Exception:  # una copia fallida nunca impide arrancar
            log.exception("No se pudo crear la copia de seguridad automática")
    data_safety.STATE.update(environment=kind, db_integrity=integrity)
    with db.session_scope() as session:
        preset_service.seed_builtin_presets(session)
        status = storage_manager.active_status(session, fresh=True)
        if status.available and status.path:
            # Al arrancar no hay subidas en curso: todo *.partial es un resto de un corte.
            cleanup_stale_uploads(Path(status.path), max_age_seconds=0)
            cleanup_trash(Path(status.path))
            exporter.cleanup_stale(Path(status.path))
        elif status.configured:
            log.warning("Almacenamiento no disponible al arrancar: %s", status.message)
    runner.max_workers = settings.max_concurrent_jobs
    runner.start()
    return str(log_file)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.log_file = _startup(settings)
        try:
            yield
        finally:
            runner.stop()
            log.info("Servidor detenido")

    app = FastAPI(
        title=f"{APP_NAME} API",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    # Anti DNS-rebinding: solo se aceptan peticiones dirigidas a localhost.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    if settings.dev_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.dev_origins),
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def require_client_header(request: Request, call_next):
        """Protección CSRF: las peticiones que modifican datos deben llevar una cabecera
        propia, que una web de terceros no puede enviar sin superar CORS."""
        if (
            request.method not in _SAFE_METHODS
            and request.url.path.startswith("/api/")
            and request.headers.get(CLIENT_HEADER) != "1"
        ):
            return JSONResponse(
                {"code": "forbidden", "message": "Petición no autorizada.", "details": None},
                status_code=403,
            )
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """El panel no se puede incrustar en otra página (clickjacking) y el navegador no
        adivina tipos de contenido."""
        response = await call_next(request)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    install_error_handlers(app)
    for router in (
        system.router,
        storage.router,
        projects.router,
        imports.router,
        media.router,
        jobs.router,
        presets.router,
        analysis.router,
        planning.router,
        animations.router,
        scenes.router,
    ):
        app.include_router(router, prefix="/api")

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def api_not_found(rest: str):
        return JSONResponse(
            {"code": "not_found", "message": f"Ruta /api/{rest} inexistente.", "details": None},
            status_code=404,
        )

    _mount_frontend(app, settings.frontend_dist)
    return app


def _mount_frontend(app: FastAPI, dist: Path | None) -> None:
    """Sirve el build del panel (modo normal). En desarrollo lo sirve Vite con proxy."""
    if dist is None or not (dist / "index.html").is_file():

        @app.get("/", include_in_schema=False)
        async def no_frontend():
            return JSONResponse(
                {
                    "message": "El panel no está compilado. Ejecuta ./videostudio start "
                    "(lo compila automáticamente) o npm run build en frontend/."
                },
                status_code=503,
            )

        return

    index = dist / "index.html"
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
