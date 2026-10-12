"""Catálogo de estilos y CRUD de presets."""

from __future__ import annotations

from typing import get_args

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.edit_config import STYLE_CATALOG, EditConfig, SubtitleAnimation, SubtitleFont
from app.models import Preset
from app.schemas import CatalogOut, PresetCreate, PresetDuplicate, PresetOut, PresetUpdate
from app.services import app_settings
from app.services import presets as preset_service

router = APIRouter(tags=["presets"])

_ANIMATION_LABELS = {
    "none": "Sin animación",
    "fade": "Fundido",
    "pop": "Pop (escala)",
    "slide_up": "Deslizar hacia arriba",
    "karaoke": "Karaoke (resaltado progresivo)",
    "word_by_word": "Palabra a palabra",
    "typewriter": "Máquina de escribir",
}


@router.get("/catalog", response_model=CatalogOut)
def catalog():
    return CatalogOut(
        styles=STYLE_CATALOG,
        subtitle_fonts=list(get_args(SubtitleFont)),
        subtitle_animations=[
            {"id": a, "label": _ANIMATION_LABELS.get(a, a)} for a in get_args(SubtitleAnimation)
        ],
        default_config=EditConfig(),
    )


def _out(session: Session, preset: Preset) -> PresetOut:
    default_id = preset_service.default_preset(session).id
    return PresetOut(
        id=preset.id,
        name=preset.name,
        description=preset.description,
        style_id=preset.style_id,
        is_builtin=preset.is_builtin,
        is_default=preset.id == default_id,
        config=preset_service.preset_config(preset),
        created_at=preset.created_at,
        updated_at=preset.updated_at,
    )


@router.get("/presets", response_model=list[PresetOut])
def list_presets(session: Session = Depends(get_session)):
    return [_out(session, p) for p in preset_service.list_presets(session)]


@router.post("/presets", response_model=PresetOut, status_code=201)
def create_preset(body: PresetCreate, session: Session = Depends(get_session)):
    preset = preset_service.create_preset(session, body.name, body.description, body.config)
    session.commit()
    return _out(session, preset)


@router.get("/presets/{preset_id}", response_model=PresetOut)
def get_preset(preset_id: str, session: Session = Depends(get_session)):
    return _out(session, preset_service.get_preset(session, preset_id))


@router.patch("/presets/{preset_id}", response_model=PresetOut)
def update_preset(preset_id: str, body: PresetUpdate, session: Session = Depends(get_session)):
    changes = {k: getattr(body, k) for k in body.model_fields_set}
    preset = preset_service.update_preset(session, preset_id, changes)
    session.commit()
    return _out(session, preset)


@router.post("/presets/{preset_id}/duplicate", response_model=PresetOut, status_code=201)
def duplicate_preset(
    preset_id: str, body: PresetDuplicate, session: Session = Depends(get_session)
):
    preset = preset_service.duplicate_preset(session, preset_id, body.name)
    session.commit()
    return _out(session, preset)


@router.post("/presets/{preset_id}/default", response_model=PresetOut)
def make_default(preset_id: str, session: Session = Depends(get_session)):
    preset = preset_service.get_preset(session, preset_id)
    prefs = app_settings.get_general(session)
    prefs.default_preset_id = preset.id
    app_settings.save_general(session, prefs)
    session.commit()
    return _out(session, preset)


@router.delete("/presets/{preset_id}", status_code=204)
def delete_preset(preset_id: str, session: Session = Depends(get_session)):
    preset_service.delete_preset(session, preset_id)
    session.commit()
