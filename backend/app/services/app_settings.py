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
    try:
        return AnalysisPreferences.model_validate(_get(session, ANALYSIS_KEY))
    except ValueError:
        return AnalysisPreferences()


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
