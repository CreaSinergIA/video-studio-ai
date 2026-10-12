"""Cola de tareas local.

- El estado vive en la tabla ``jobs`` (sobrevive a reinicios).
- Un hilo despachador toma tareas ``queued`` y las ejecuta en un pool (``max_workers``).
- Los tipos de tarea se registran con ``@job_handler``. Fases futuras (transcripción,
  análisis, render…) añaden aquí sus manejadores sin tocar el resto del sistema.
- Al arrancar, las tareas que quedaron ``running`` por un cierre se reencolan si su tipo es
  idempotente (``resumable``) o se marcan como fallidas.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import session_scope
from app.models import Job, new_id, utcnow
from app.services.media_tools import Cancelled

log = logging.getLogger(__name__)

ACTIVE_STATUSES = ("queued", "running")


class JobError(Exception):
    """Error esperado de una tarea: su mensaje se muestra tal cual al usuario."""


@dataclass
class JobContext:
    job_id: str
    kind: str
    project_id: str | None
    asset_id: str | None
    payload: dict[str, Any]
    cancel_event: threading.Event
    _last_write: float = 0.0
    _range: tuple[float, float] = (0.0, 1.0)
    _stage: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def stage(self, label: str, start: float, end: float) -> None:
        """Inicia una etapa que ocupa el tramo [start, end] del progreso total."""
        self._range = (start, end)
        self._stage = label
        self._write(start, force=True)

    def progress(self, fraction: float) -> None:
        """Avance dentro de la etapa actual (0–1)."""
        start, end = self._range
        self._write(start + (end - start) * max(0.0, min(1.0, fraction)))

    @property
    def shutting_down(self) -> bool:
        return runner._stop.is_set()

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise Cancelled()

    def _write(self, value: float, force: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            if not force and now - self._last_write < 0.4:
                return
            self._last_write = now
        try:
            with session_scope() as s:
                s.execute(
                    update(Job)
                    .where(Job.id == self.job_id)
                    .values(progress=round(value, 4), stage=self._stage)
                )
        except Exception:  # el progreso nunca debe tumbar la tarea
            log.exception("No se pudo guardar el progreso de %s", self.job_id)


Handler = Callable[[JobContext], dict[str, Any] | None]


@dataclass(frozen=True)
class JobKind:
    name: str
    label: str
    handler: Handler
    resumable: bool
    # Tareas intensivas (transcripción, análisis, exportación): solo una a la vez para no
    # competir por CPU/GPU/memoria; las ligeras siguen ejecutándose en paralelo.
    heavy: bool = False
    # Se llama si la tarea termina sin ejecutarse su manejador (cancelada en cola o
    # interrumpida por un cierre), para dejar coherentes los registros que dependen de ella.
    on_abort: Callable[[dict[str, Any], str, str], None] | None = None


REGISTRY: dict[str, JobKind] = {}


def job_handler(
    name: str,
    *,
    label: str,
    resumable: bool = False,
    heavy: bool = False,
    on_abort: Callable[[dict[str, Any], str, str], None] | None = None,
) -> Callable[[Handler], Handler]:
    def decorator(fn: Handler) -> Handler:
        REGISTRY[name] = JobKind(
            name=name,
            label=label,
            handler=fn,
            resumable=resumable,
            heavy=heavy,
            on_abort=on_abort,
        )
        return fn

    return decorator


def create_job(
    session: Session,
    kind: str,
    *,
    project_id: str | None = None,
    asset_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Job:
    """Añade una tarea a la sesión. Llamar a ``runner.wake()`` tras el commit."""
    if kind not in REGISTRY:
        raise ValueError(f"Tipo de tarea desconocido: {kind}")
    job = Job(
        id=new_id("job"),
        kind=kind,
        status="queued",
        project_id=project_id,
        asset_id=asset_id,
        payload=payload or {},
    )
    session.add(job)
    session.flush()
    return job


class JobRunner:
    def __init__(self, max_workers: int = 2) -> None:
        self.max_workers = max_workers
        self._pool: ThreadPoolExecutor | None = None
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._running: dict[str, threading.Event] = {}
        self._running_kinds: dict[str, str] = {}
        self._lock = threading.Lock()

    # -- ciclo de vida -------------------------------------------------------

    def start(self) -> None:
        self._recover()
        self._stop.clear()
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="job")
        self._thread = threading.Thread(target=self._loop, name="job-dispatcher", daemon=True)
        self._thread.start()
        log.info("Cola de tareas iniciada (%d en paralelo)", self.max_workers)

    def stop(self, timeout: float = 10) -> None:
        self._stop.set()
        self._wake.set()
        # Primero el despachador (ya no reclama tareas), después interrumpir las activas.
        if self._thread:
            self._thread.join(timeout=timeout)
        with self._lock:
            for event in self._running.values():
                event.set()
        if self._pool:
            self._pool.shutdown(wait=True, cancel_futures=True)
        self._pool = None
        self._thread = None

    def wake(self) -> None:
        self._wake.set()

    def is_running(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._running

    def cancel(self, job_id: str) -> bool:
        # Bajo el mismo candado que el despachador: la tarea o está registrada como activa
        # o sigue en cola (nunca en el hueco entre reclamarla y registrarla).
        with self._lock:
            event = self._running.get(job_id)
            if event is not None:
                event.set()
                return True
            with session_scope() as s:
                result = s.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == "queued")
                    .values(status="cancelled", finished_at=utcnow(), stage="Cancelada")
                )
                cancelled = bool(result.rowcount)  # type: ignore[attr-defined]
                job = s.get(Job, job_id) if cancelled else None
                kind = REGISTRY.get(job.kind) if job else None
                payload = dict(job.payload or {}) if job else {}
        if kind is not None and kind.on_abort is not None:
            _safe_abort(kind, payload, "cancelled", "Cancelada antes de empezar.")
        return cancelled

    def cancel_for_project(self, project_id: str) -> None:
        with session_scope() as s:
            ids = s.scalars(
                select(Job.id).where(Job.project_id == project_id, Job.status.in_(ACTIVE_STATUSES))
            ).all()
        for job_id in ids:
            self.cancel(job_id)
        # Esperar a que las tareas en curso suelten sus archivos antes de borrar nada.
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and any(self.is_running(j) for j in ids):
            time.sleep(0.05)

    def wait_idle(self, timeout: float = 60) -> bool:
        """Espera a que no haya tareas activas (útil en pruebas)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with session_scope() as s:
                active = s.scalar(select(Job.id).where(Job.status.in_(ACTIVE_STATUSES)).limit(1))
            if active is None:
                return True
            time.sleep(0.1)
        return False

    @contextlib.contextmanager
    def paused(self) -> Iterator[bool]:
        """Bloquea el despacho de tareas mientras dura el bloque. Devuelve si no había tareas en
        ejecución en este proceso (necesario para restaurar la base en caliente)."""
        with self._lock:
            yield not self._running

    def fail_stale_after_restore(self) -> int:
        """Tras restaurar una copia: las tareas que figuraban en curso o en cola en la copia ya
        no existen en este proceso; se marcan como fallidas (nunca se ejecutan sin pedirlo)."""
        n = 0
        with session_scope() as s:
            for job in s.scalars(select(Job).where(Job.status.in_(ACTIVE_STATUSES))).all():
                job.status = "failed"
                job.error = "Interrumpida: se restauró una copia de seguridad. Puedes reintentarla."
                job.finished_at = utcnow()
                n += 1
        return n

    # -- interno -------------------------------------------------------------

    def _recover(self) -> None:
        aborted: list[tuple[JobKind, dict[str, Any], str]] = []
        with session_scope() as s:
            for job in s.scalars(select(Job).where(Job.status == "running")).all():
                kind = REGISTRY.get(job.kind)
                if kind and kind.resumable:
                    job.status = "queued"
                    job.progress = 0.0
                    job.stage = "Reanudada tras reinicio"
                    job.started_at = None
                else:
                    job.status = "failed"
                    job.error = "Interrumpida por el cierre de la aplicación. Puedes reintentarla."
                    job.finished_at = utcnow()
                    if kind is not None and kind.on_abort is not None:
                        aborted.append((kind, dict(job.payload or {}), job.error))
                log.warning("Tarea %s (%s) recuperada como %s", job.id, job.kind, job.status)
        for kind, payload, message in aborted:
            _safe_abort(kind, payload, "failed", message)

    def _claim_next(self, heavy_busy: bool = False) -> tuple[str, str] | None:
        with session_scope() as s:
            candidates = s.execute(
                select(Job.id, Job.kind)
                .where(Job.status == "queued")
                .order_by(Job.created_at)
                .limit(25)
            ).all()
            for job_id, kind in candidates:
                spec = REGISTRY.get(kind)
                if heavy_busy and spec is not None and spec.heavy:
                    continue
                claimed = s.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == "queued")
                    .values(status="running", started_at=utcnow(), progress=0.0)
                )
                if claimed.rowcount:  # type: ignore[attr-defined]
                    return job_id, kind
        return None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                with self._lock:
                    free = self.max_workers - len(self._running)
                    heavy_busy = any(
                        REGISTRY[k].heavy for k in self._running_kinds.values() if k in REGISTRY
                    )
                    claimed = self._claim_next(heavy_busy) if free > 0 and self._pool else None
                    if claimed is not None:
                        job_id, kind = claimed
                        event = threading.Event()
                        self._running[job_id] = event
                        self._running_kinds[job_id] = kind
                if claimed is not None and self._pool is not None:
                    self._pool.submit(self._execute, claimed[0], event)
                    continue
            except Exception:
                log.exception("Error en el despachador de tareas")
            self._wake.wait(timeout=1.0)
            self._wake.clear()

    def _execute(self, job_id: str, cancel_event: threading.Event) -> None:
        try:
            with session_scope() as s:
                job = s.get(Job, job_id)
                if job is None:
                    return
                ctx = JobContext(
                    job_id=job.id,
                    kind=job.kind,
                    project_id=job.project_id,
                    asset_id=job.asset_id,
                    payload=dict(job.payload or {}),
                    cancel_event=cancel_event,
                )
            kind = REGISTRY.get(ctx.kind)
            status, error, result = "succeeded", None, None
            if kind is None:
                status, error = "failed", f"Tipo de tarea desconocido: {ctx.kind}"
            else:
                log.info("Tarea %s (%s) iniciada", job_id, ctx.kind)
                try:
                    result = kind.handler(ctx)
                except Cancelled:
                    # Interrumpida por el cierre de la app: las tareas idempotentes se reanudan.
                    status = "queued" if self._stop.is_set() and kind.resumable else "cancelled"
                except JobError as exc:
                    status, error = "failed", str(exc)
                except Exception as exc:
                    log.exception("Tarea %s (%s) falló", job_id, ctx.kind)
                    status, error = "failed", _friendly_error(exc)
            with session_scope() as s:
                job = s.get(Job, job_id)
                if job is not None:
                    job.status = status
                    job.error = error
                    job.result = result
                    job.finished_at = None if status == "queued" else utcnow()
                    if status == "queued":
                        job.progress, job.started_at = 0.0, None
                        job.stage = "Se reanudará al iniciar"
                    if status == "succeeded":
                        job.progress = 1.0
                        job.stage = "Completada"
                    elif status == "cancelled":
                        job.stage = "Cancelada"
            log.info(
                "Tarea %s (%s) terminó: %s%s",
                job_id,
                ctx.kind,
                status,
                f" — {error}" if error else "",
            )
        finally:
            with self._lock:
                self._running.pop(job_id, None)
                self._running_kinds.pop(job_id, None)
            self._wake.set()


def _safe_abort(kind: JobKind, payload: dict[str, Any], status: str, message: str) -> None:
    try:
        assert kind.on_abort is not None
        kind.on_abort(payload, status, message)
    except Exception:
        log.exception("Error al cerrar los registros de la tarea %s", kind.name)


def _friendly_error(exc: Exception) -> str:
    from app.services.storage import StorageError

    if isinstance(exc, StorageError):
        return exc.message
    if isinstance(exc, OSError):
        return f"Error de disco: {exc.strerror or exc}. ¿Se desconectó el almacenamiento?"
    return f"Error inesperado: {exc}"


runner = JobRunner()
