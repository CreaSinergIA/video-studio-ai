"""Preferencias persistentes (tabla ``app_settings``, un documento JSON por clave)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.preferences import AnalysisPreferences, ClaudePreferences, GeneralPreferences
from app.models import AppSetting

GENERAL_KEY = "general"
STORAGE_KEY = "storage"
ANALYSIS_KEY = "analysis"
CLAUDE_KEY = "claude"
CLAUDE_STATUS_KEY = "claude_status"
SETUP_KEY = "setup"


def _get(session: Session, key: str) -> dict[str, Any]:
    row = session.get(AppSetting, key)
    return dict(row.value) if row else {}


def _put(session: Session, key: str, value: dict[str, Any]) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def get_general(session: Session) -> GeneralPreferences:
    data = _get(session, GENERAL_KEY)
    try:
        return GeneralPreferences.model_validate(data)
    except ValueError:
        # Datos antiguos o corruptos: conservar lo válido campo a campo.
        clean = {}
        defaults = GeneralPreferences()
        for name in GeneralPreferences.model_fields:
            if name in data:
                try:
                    GeneralPreferences.model_validate({name: data[name]})
                    clean[name] = data[name]
                except ValueError:
                    clean[name] = getattr(defaults, name)
        return GeneralPreferences.model_validate(clean)


def save_general(session: Session, prefs: GeneralPreferences) -> GeneralPreferences:
    _put(session, GENERAL_KEY, prefs.model_dump(mode="json"))
    return prefs


def get_active_storage_id(session: Session) -> str | None:
    value = _get(session, STORAGE_KEY).get("active_id")
    return value if isinstance(value, str) else None


def set_active_storage_id(session: Session, storage_id: str) -> None:
    _put(session, STORAGE_KEY, {"active_id": storage_id})


def get_analysis(session: Session) -> AnalysisPreferences:
    from app.services import asr_models

    data = _get(session, ANALYSIS_KEY)
    try:
        prefs = AnalysisPreferences.model_validate(data)
    except ValueError:
        prefs = AnalysisPreferences()
    # Sin elección guardada, o con un modelo de un motor que no existe en este equipo (p. ej.
    # una base de datos traída de otro sistema): el recomendado de esta plataforma.
    spec = asr_models.CATALOG.get(prefs.transcription_model)
    if not data.get("transcription_model") or (
        spec is not None
        and asr_models.platform_supported()
        and not asr_models.engine_available(spec.engine)
    ):
        prefs = prefs.model_copy(update={"transcription_model": asr_models.default_model_id()})
    return prefs


def save_analysis(session: Session, prefs: AnalysisPreferences) -> AnalysisPreferences:
    _put(session, ANALYSIS_KEY, prefs.model_dump(mode="json"))
    return prefs


def get_claude(session: Session) -> ClaudePreferences:
    try:
        return ClaudePreferences.model_validate(_get(session, CLAUDE_KEY))
    except ValueError:
        return ClaudePreferences()


def save_claude(session: Session, prefs: ClaudePreferences) -> ClaudePreferences:
    _put(session, CLAUDE_KEY, prefs.model_dump(mode="json"))
    return prefs


def get_claude_status(session: Session) -> dict[str, Any]:
    """Resultado de la última comprobación real de conexión (sin secretos)."""
    return _get(session, CLAUDE_STATUS_KEY)


def save_claude_status(session: Session, status: dict[str, Any]) -> None:
    _put(session, CLAUDE_STATUS_KEY, status)


def get_setup(session: Session) -> dict[str, Any]:
    """Estado de la primera configuración (``completed_at`` cuando el usuario la cierra)."""
    return _get(session, SETUP_KEY)


def save_setup(session: Session, value: dict[str, Any]) -> None:
    _put(session, SETUP_KEY, value)
