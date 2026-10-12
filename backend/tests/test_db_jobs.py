"""Migraciones, integridad de SQLite y recuperación de la cola de tareas tras un cierre."""

from __future__ import annotations

from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app import db
from app.jobs.runner import JobRunner
from app.models import Base, Job, new_id


def test_migrations_match_models(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'm.db'}"
    db.run_migrations(url)
    engine = create_engine(url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], diff
    tables = set(inspect(engine).get_table_names())
    assert {"projects", "media_assets", "presets", "jobs", "storage_locations"} <= tables


def test_sqlite_pragmas(client) -> None:
    engine = db.get_engine()
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    assert db.check_integrity() == "ok"


def test_runner_recovers_interrupted_jobs(client) -> None:
    from app.jobs.runner import runner

    runner.stop()
    with db.session_scope() as s:
        s.add(Job(id=new_id("job"), kind="import_file", status="running", payload={}))
        s.add(Job(id=new_id("job"), kind="verify", status="running", payload={}))
    fresh = JobRunner()
    fresh._recover()
    with db.session_scope() as s:
        jobs = {j.kind: j for j in s.query(Job).all()}
        assert jobs["import_file"].status == "failed"
        assert "Interrumpida" in (jobs["import_file"].error or "")
        assert jobs["verify"].status == "queued"
    runner.start()


def test_shutdown_requeues_resumable_jobs(client) -> None:
    import time

    from app.jobs.runner import JobContext, create_job, job_handler, runner

    started: list[str] = []

    def slow(ctx: JobContext) -> None:
        started.append(ctx.kind)
        while True:
            ctx.check_cancelled()
            time.sleep(0.02)

    job_handler("test_slow_resumable", label="Prueba", resumable=True)(slow)
    job_handler("test_slow_once", label="Prueba")(slow)
    with db.session_scope() as s:
        a = create_job(s, "test_slow_resumable").id
        b = create_job(s, "test_slow_once").id
    runner.wake()
    deadline = time.monotonic() + 10
    while len(started) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(started) == 2
    runner.stop()
    with db.session_scope() as s:
        assert s.get(Job, a).status == "queued"  # se reanudará al iniciar
        assert s.get(Job, b).status == "cancelled"
        s.query(Job).filter(Job.id.in_([a, b])).delete()
    runner.start()
