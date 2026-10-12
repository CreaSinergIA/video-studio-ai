"""Consulta, cancelación y reintento de tareas."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db import get_session
from app.jobs.runner import ACTIVE_STATUSES, REGISTRY, create_job, runner
from app.models import Job, utcnow
from app.schemas import JobOut
from app.services import projects as project_service
from app.services.storage import StorageError

router = APIRouter(prefix="/jobs", tags=["tareas"])


@router.get("", response_model=list[JobOut])
def list_jobs(
    project_id: str | None = None,
    recent_seconds: int = Query(default=30, ge=0, le=86400),
    session: Session = Depends(get_session),
):
    """Tareas activas + las terminadas en los últimos ``recent_seconds`` segundos."""
    since = utcnow() - timedelta(seconds=recent_seconds)
    query = select(Job).where(or_(Job.status.in_(ACTIVE_STATUSES), Job.finished_at >= since))
    if project_id:
        query = query.where(Job.project_id == project_id)
    jobs = session.scalars(query.order_by(Job.created_at.desc()).limit(100)).all()
    return [project_service.job_out(j) for j in jobs]


def _job(session: Session, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise StorageError("job_not_found", "La tarea no existe.", 404)
    return job


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, session: Session = Depends(get_session)):
    return project_service.job_out(_job(session, job_id))


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, session: Session = Depends(get_session)):
    job = _job(session, job_id)
    if job.status in ACTIVE_STATUSES:
        runner.cancel(job_id)
    session.expire_all()
    return project_service.job_out(_job(session, job_id))


@router.post("/{job_id}/retry", response_model=JobOut, status_code=202)
def retry_job(job_id: str, session: Session = Depends(get_session)):
    job = _job(session, job_id)
    if job.status not in ("failed", "cancelled"):
        raise StorageError(
            "not_retryable", "Solo se pueden reintentar tareas fallidas o canceladas."
        )
    if job.kind not in REGISTRY:
        raise StorageError("not_retryable", "Tipo de tarea desconocido.")
    new_job = create_job(
        session, job.kind, project_id=job.project_id, asset_id=job.asset_id, payload=job.payload
    )
    if job.asset_id and job.kind == "ingest" and job.project_id:
        from app.models import MediaAsset

        asset = session.get(MediaAsset, job.asset_id)
        if asset is not None:
            asset.status, asset.error = "processing", None
    session.commit()
    runner.wake()
    return project_service.job_out(new_job)
