"""Presets de edición: tres integrados (uno por estilo, solo lectura) + presets del usuario."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.edit_config import (
    STYLE_CATALOG,
    EditConfig,
    StyleId,
    default_config_for_style,
)
from app.models import Preset, new_id
from app.services import app_settings

BUILTIN_IDS: dict[StyleId, str] = {
    "motion_tech": "builtin_motion_tech",
    "minimal_motion": "builtin_minimal_motion",
    "creative_explainer": "builtin_creative_explainer",
}
FALLBACK_PRESET_ID = BUILTIN_IDS["motion_tech"]


class PresetError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def seed_builtin_presets(session: Session) -> None:
    """Crea o actualiza los presets integrados (idempotente)."""
    for style in STYLE_CATALOG:
        preset_id = BUILTIN_IDS[style.id]
        config = default_config_for_style(style.id).model_dump(mode="json")
        row = session.get(Preset, preset_id)
        if row is None:
            session.add(
                Preset(
                    id=preset_id,
                    name=style.name,
                    description=f"Preset base de {style.name}: {style.tagline.lower()}.",
                    style_id=style.id,
                    is_builtin=True,
                    config=config,
                )
            )
        elif row.config != config:
            row.config = config


def list_presets(session: Session) -> list[Preset]:
    return list(
        session.scalars(select(Preset).order_by(Preset.is_builtin.desc(), Preset.created_at))
    )


def get_preset(session: Session, preset_id: str) -> Preset:
    preset = session.get(Preset, preset_id)
    if preset is None:
        raise PresetError("preset_not_found", "El preset no existe.", 404)
    return preset


def preset_config(preset: Preset) -> EditConfig:
    return EditConfig.model_validate(preset.config)


def default_preset(session: Session) -> Preset:
    prefs = app_settings.get_general(session)
    if prefs.default_preset_id:
        preset = session.get(Preset, prefs.default_preset_id)
        if preset is not None:
            return preset
    return get_preset(session, FALLBACK_PRESET_ID)


def _check_name(session: Session, name: str, exclude_id: str | None = None) -> str:
    name = name.strip()
    if not name:
        raise PresetError("invalid_name", "El nombre no puede estar vacío.", 422)
    query = select(Preset.id).where(Preset.name == name)
    if exclude_id:
        query = query.where(Preset.id != exclude_id)
    if session.scalar(query) is not None:
        raise PresetError("duplicate_name", f"Ya existe un preset llamado «{name}».")
    return name


def create_preset(session: Session, name: str, description: str, config: EditConfig) -> Preset:
    preset = Preset(
        id=new_id("pst"),
        name=_check_name(session, name),
        description=description.strip(),
        style_id=config.style.id,
        is_builtin=False,
        config=config.model_dump(mode="json"),
    )
    session.add(preset)
    session.flush()
    return preset


def update_preset(session: Session, preset_id: str, changes: dict[str, Any]) -> Preset:
    preset = get_preset(session, preset_id)
    if preset.is_builtin:
        raise PresetError(
            "builtin_readonly", "Los presets integrados no se modifican. Duplica uno para editarlo."
        )
    if "name" in changes and changes["name"] is not None:
        preset.name = _check_name(session, changes["name"], exclude_id=preset.id)
    if "description" in changes and changes["description"] is not None:
        preset.description = str(changes["description"]).strip()
    if "config" in changes and changes["config"] is not None:
        config: EditConfig = changes["config"]
        preset.config = config.model_dump(mode="json")
        preset.style_id = config.style.id
    session.flush()
    return preset


def duplicate_preset(session: Session, preset_id: str, name: str | None = None) -> Preset:
    source = get_preset(session, preset_id)
    base = name or f"{source.name} (copia)"
    candidate, n = base, 2
    while session.scalar(select(Preset.id).where(Preset.name == candidate)) is not None:
        candidate = f"{base} {n}"
        n += 1
    return create_preset(session, candidate, source.description, preset_config(source))


def delete_preset(session: Session, preset_id: str) -> None:
    preset = get_preset(session, preset_id)
    if preset.is_builtin:
        raise PresetError("builtin_readonly", "Los presets integrados no se pueden eliminar.")
    prefs = app_settings.get_general(session)
    if prefs.default_preset_id == preset_id:
        prefs.default_preset_id = None
        app_settings.save_general(session, prefs)
    session.delete(preset)
