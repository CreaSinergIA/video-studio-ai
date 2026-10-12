"""Salud, información del entorno y preferencias generales."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app import db
from app.config import APP_VERSION, get_settings
from app.db import get_session
from app.domain.preferences import GeneralPreferences
from app.jobs.runner import runner
from app.schemas import SettingsOut
from app.services import app_settings, data_safety, system_info
from app.services import presets as preset_service
from app.services.projects import ProjectError

router = APIRouter(tags=["sistema"])


@router.get("/health")
def health():
    return {
        "ok": True,
        "version": APP_VERSION,
        "environment": data_safety.STATE.get("environment", "user"),
        "db_integrity": data_safety.STATE.get("db_integrity", "ok"),
    }


def _backup_out(b: data_safety.Backup) -> dict[str, Any]:
    return {"name": b.name, "kind": b.kind, "size": b.size, "created_at": b.created_at.isoformat()}


@router.get("/system/backups")
def list_backups():
    settings = get_settings()
    return {
        "items": [_backup_out(b) for b in data_safety.list_backups(settings.home)],
        "directory": str(data_safety.backups_dir(settings.home)),
        "integrity": data_safety.STATE.get("db_integrity", "ok"),
    }


@router.post("/system/backups", status_code=201)
def create_backup():
    settings = get_settings()
    return _backup_out(data_safety.create_backup(settings.db_path, settings.home, "manual"))


class RestoreBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = False


@router.post("/system/backups/{name}/restore")
def restore_backup(name: str, body: RestoreBody):
    """Restaura una copia (con confirmación explícita). Antes guarda el estado actual en una
    copia «antes-de-restaurar», así que la operación se puede deshacer."""
    settings = get_settings()
    if not body.confirm:
        raise ProjectError("confirm_required", "Confirma la restauración.", 409)
    try:
        path = data_safety.resolve_backup(settings.home, name)
    except FileNotFoundError:
        raise ProjectError("not_found", "Esa copia de seguridad no existe.", 404) from None
    with runner.paused() as idle:
        # El despachador queda detenido durante la restauración: no se reclama ninguna tarea.
        if not idle or not runner.wait_idle(timeout=0.1):
            raise ProjectError(
                "busy",
                "Hay tareas en curso. Espera a que terminen o cancélalas antes de restaurar.",
                409,
            )
        before = data_safety.create_backup(settings.db_path, settings.home, "antes-de-restaurar")
        db.get_engine().dispose()
        data_safety.restore_into(settings.db_path, path)
        db.init_engine(settings.database_url)
        db.run_migrations(settings.database_url)
        stale = runner.fail_stale_after_restore()
        data_safety.STATE["db_integrity"] = db.check_integrity()
    return {"restored": name, "previous_state": before.name, "stale_jobs": stale}


@router.get("/system/info")
def info(request: Request):
    return system_info.collect(get_settings(), getattr(request.app.state, "log_file", None))


@router.get("/settings", response_model=SettingsOut)
def get_app_settings(session: Session = Depends(get_session)):
    return SettingsOut(general=app_settings.get_general(session))


@router.put("/settings/general", response_model=SettingsOut)
def put_general(body: GeneralPreferences, session: Session = Depends(get_session)):
    if body.default_preset_id:
        preset_service.get_preset(session, body.default_preset_id)
    app_settings.save_general(session, body)
    session.commit()
    return SettingsOut(general=body)
