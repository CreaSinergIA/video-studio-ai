"""Proyectos: biblioteca, detalle, renombrar, ajustes, presets y eliminación."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.jobs.runner import runner
from app.models import utcnow
from app.schemas import (
    ApplyPreset,
    DeleteProjectResult,
    ProjectCreate,
    ProjectDetail,
    ProjectSummary,
    ProjectUpdate,
)
from app.services import app_settings
from app.services import projects as project_service

router = APIRouter(prefix="/projects", tags=["proyectos"])


def _detail(session: Session, project_id: str) -> ProjectDetail:
    project = project_service.get_project(session, project_id)
    return project_service.project_detail(session, project, app_settings.get_general(session))


@router.get("", response_model=list[ProjectSummary])
def list_projects(session: Session = Depends(get_session)):
    return project_service.list_projects(session, app_settings.get_general(session))


@router.post("", response_model=ProjectDetail, status_code=201)
def create_project(body: ProjectCreate, session: Session = Depends(get_session)):
    project, _ = project_service.create_project(session, body.name, body.preset_id)
    session.commit()
    return _detail(session, project.id)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, session: Session = Depends(get_session)):
    return _detail(session, project_id)


@router.post("/{project_id}/open", response_model=ProjectDetail)
def open_project(project_id: str, session: Session = Depends(get_session)):
    project = project_service.get_project(session, project_id)
    project.last_opened_at = utcnow()
    session.commit()
    project_service.sync_manifest(project)
    return _detail(session, project_id)


@router.patch("/{project_id}", response_model=ProjectDetail)
def update_project(project_id: str, body: ProjectUpdate, session: Session = Depends(get_session)):
    project = project_service.get_project(session, project_id)
    if body.name is not None:
        project_service.rename_project(session, project, body.name)
    if body.config is not None:
        project_service.update_config(session, project, body.config)
    if body.editor_state is not None:
        project.editor_state = body.editor_state.model_dump(mode="json")
    session.commit()
    return _detail(session, project_id)


@router.post("/{project_id}/apply-preset", response_model=ProjectDetail)
def apply_preset(project_id: str, body: ApplyPreset, session: Session = Depends(get_session)):
    project = project_service.get_project(session, project_id)
    project_service.apply_preset(session, project, body.preset_id)
    session.commit()
    return _detail(session, project_id)


@router.delete("/{project_id}", response_model=DeleteProjectResult)
def delete_project(
    project_id: str,
    keep_files: bool = Query(default=False, description="Solo quitar de la biblioteca"),
    session: Session = Depends(get_session),
):
    project = project_service.get_project(session, project_id)
    files_removed, message = project_service.delete_project(session, project, keep_files)
    session.commit()
    runner.wake()
    return DeleteProjectResult(deleted=True, files_removed=files_removed, message=message)
