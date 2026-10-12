"""Traducción de errores de dominio a respuestas JSON uniformes ``{code, message, details}``."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.services.asr_models import ModelError
from app.services.claude_client import ClaudeError
from app.services.exporter import ExportError
from app.services.imports import DuplicateError
from app.services.media_probe import MediaValidationError
from app.services.plan_context import PlanInputError
from app.services.planning import PlanError
from app.services.presets import PresetError
from app.services.projects import ProjectError
from app.services.render_engine import EngineError
from app.services.storage import StorageError
from app.services.transcripts import TranscriptError

log = logging.getLogger(__name__)


def _body(code: str, message: str, details: dict | None = None) -> dict:
    return {"code": code, "message": message, "details": details}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StorageError)
    async def storage_error(_: Request, exc: StorageError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(ProjectError)
    async def project_error(_: Request, exc: ProjectError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(PresetError)
    async def preset_error(_: Request, exc: PresetError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(TranscriptError)
    async def transcript_error(_: Request, exc: TranscriptError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(ModelError)
    async def model_error(_: Request, exc: ModelError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(EngineError)
    async def engine_error(_: Request, exc: EngineError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(PlanError)
    async def plan_error(_: Request, exc: PlanError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(PlanInputError)
    async def plan_input_error(_: Request, exc: PlanInputError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=409)

    @app.exception_handler(ClaudeError)
    async def claude_error(_: Request, exc: ClaudeError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=502)

    @app.exception_handler(ExportError)
    async def export_error(_: Request, exc: ExportError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status_code)

    @app.exception_handler(MediaValidationError)
    async def media_error(_: Request, exc: MediaValidationError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=422)

    @app.exception_handler(DuplicateError)
    async def duplicate_error(_: Request, exc: DuplicateError) -> JSONResponse:
        names = ", ".join(f"«{d.project_name}»" for d in exc.duplicates)
        return JSONResponse(
            _body(
                "duplicate",
                f"Este video ya está importado en {names}.",
                {"duplicates": [d.model_dump(mode="json") for d in exc.duplicates]},
            ),
            status_code=409,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        first = errors[0] if errors else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        message = (
            f"Dato no válido en «{loc}»: {first.get('msg', '')}" if loc else "Datos no válidos."
        )
        return JSONResponse(
            _body(
                "validation_error",
                message,
                {"errors": [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in errors]},
            ),
            status_code=422,
        )

    @app.exception_handler(OSError)
    async def os_error(_: Request, exc: OSError) -> JSONResponse:
        log.exception("Error de E/S")
        return JSONResponse(
            _body(
                "io_error",
                f"Error de disco: {exc.strerror or exc}. "
                "Comprueba que el almacenamiento esté conectado.",
            ),
            status_code=503,
        )
