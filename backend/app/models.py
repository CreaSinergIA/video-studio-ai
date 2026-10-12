"""Modelo de datos persistente (SQLite vía SQLAlchemy 2).

Rutas de archivos: siempre *relativas* a la raíz del almacenamiento al que pertenece el
proyecto (``StorageLocation``). Así el almacenamiento puede montarse en otra ruta u otra
máquina sin reescribir la base de datos.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # base32 Crockford en minúsculas


def new_id(prefix: str) -> str:
    token = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    return f"{prefix}_{token}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class UTCDateTime(TypeDecorator[datetime]):
    """Guarda fechas en UTC (SQLite no conserva zona horaria) y las devuelve con tzinfo."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: UTCDateTime(),
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }


class StorageLocation(Base):
    """Raíz de almacenamiento registrada (identificada por el marcador ``.videostudio.json``)."""

    __tablename__ = "storage_locations"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    path: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(default=None)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Preset(Base):
    __tablename__ = "presets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    style_id: Mapped[str] = mapped_column(String(40))
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    storage_id: Mapped[str] = mapped_column(ForeignKey("storage_locations.id"), index=True)
    dir_rel: Mapped[str] = mapped_column(Text)
    preset_id: Mapped[str | None] = mapped_column(
        ForeignKey("presets.id", ondelete="SET NULL"), default=None
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    editor_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)
    last_opened_at: Mapped[datetime | None] = mapped_column(default=None)

    storage: Mapped[StorageLocation] = relationship()
    assets: Mapped[list[MediaAsset]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="MediaAsset.created_at",
    )


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), default="source")
    status: Mapped[str] = mapped_column(String(20), default="processing")
    error: Mapped[str | None] = mapped_column(Text, default=None)

    original_filename: Mapped[str] = mapped_column(Text)
    file_rel: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    quick_hash: Mapped[str] = mapped_column(String(64), index=True)

    container: Mapped[str] = mapped_column(String(10))
    format_name: Mapped[str] = mapped_column(String(80))
    major_brand: Mapped[str | None] = mapped_column(String(10), default=None)
    duration: Mapped[float] = mapped_column(Float)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    display_width: Mapped[int] = mapped_column(Integer)
    display_height: Mapped[int] = mapped_column(Integer)
    rotation: Mapped[int] = mapped_column(Integer, default=0)
    orientation: Mapped[str] = mapped_column(String(12))
    fps: Mapped[float] = mapped_column(Float)
    fps_num: Mapped[int] = mapped_column(Integer)
    fps_den: Mapped[int] = mapped_column(Integer)
    video_codec: Mapped[str] = mapped_column(String(40))
    video_profile: Mapped[str | None] = mapped_column(String(80), default=None)
    pix_fmt: Mapped[str | None] = mapped_column(String(40), default=None)
    bit_depth: Mapped[int | None] = mapped_column(Integer, default=None)
    color_transfer: Mapped[str | None] = mapped_column(String(40), default=None)
    bit_rate: Mapped[int | None] = mapped_column(Integer, default=None)
    frame_count: Mapped[int | None] = mapped_column(Integer, default=None)
    has_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    audio_tracks: Mapped[list[Any]] = mapped_column(JSON, default=list)
    creation_time: Mapped[str | None] = mapped_column(String(40), default=None)
    probe: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    browser_playable: Mapped[bool] = mapped_column(Boolean, default=True)
    thumbnail_rel: Mapped[str | None] = mapped_column(Text, default=None)
    filmstrip_rel: Mapped[str | None] = mapped_column(Text, default=None)
    filmstrip_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    waveform_rel: Mapped[str | None] = mapped_column(Text, default=None)
    proxy_rel: Mapped[str | None] = mapped_column(Text, default=None)
    verified_at: Mapped[datetime | None] = mapped_column(default=None)

    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    project: Mapped[Project] = relationship(back_populates="assets")


class Job(Base):
    """Tarea de la cola local (ingesta, proxy, verificación… y en el futuro análisis/render)."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True, default="queued")
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )
    asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), default=None
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    stage: Mapped[str | None] = mapped_column(String(200), default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


# ---------------------------------------------------------------------------
# Fase 2 — transcripciones, análisis, fotogramas y exportaciones
# ---------------------------------------------------------------------------


class Transcript(Base):
    """Versión de una transcripción.

    ``kind="asr"`` es el resultado del reconocimiento (inmutable); ``kind="edited"`` es la
    versión corregida por el usuario (deriva de una ``asr`` mediante ``parent_id``). Solo una
    versión por recurso está activa. ``segments`` guarda segmentos con sus palabras y tiempos.
    """

    __tablename__ = "transcripts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(10), default="asr")
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("transcripts.id", ondelete="SET NULL"), default=None
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default="ready")
    engine: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    language: Mapped[str | None] = mapped_column(String(10), default=None)
    params_hash: Mapped[str] = mapped_column(String(64), index=True)
    segments: Mapped[list[Any]] = mapped_column(JSON, default=list)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class Analysis(Base):
    """Resultado de un análisis (``kind="visual"``: escenas, intervalos estáticos, rostros)."""

    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(20))
    params_hash: Mapped[str] = mapped_column(String(64), index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AnalysisFrame(Base):
    """Fotograma extraído (selectivo). ``t`` es el tiempo de presentación real del fotograma."""

    __tablename__ = "analysis_frames"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    asset_id: Mapped[str] = mapped_column(
        ForeignKey("media_assets.id", ondelete="CASCADE"), index=True
    )
    analysis_id: Mapped[str | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True, default=None
    )
    t: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String(20))
    scene_index: Mapped[int | None] = mapped_column(Integer, default=None)
    file_rel: Mapped[str] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    faces: Mapped[list[Any] | None] = mapped_column(JSON, default=None)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class Export(Base):
    """Exportación de video (archivo independiente en ``exports/`` del proyecto)."""

    __tablename__ = "exports"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    transcript_id: Mapped[str | None] = mapped_column(
        ForeignKey("transcripts.id", ondelete="SET NULL"), default=None
    )
    job_id: Mapped[str | None] = mapped_column(String(40), default=None)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    file_rel: Mapped[str | None] = mapped_column(Text, default=None)
    size_bytes: Mapped[int | None] = mapped_column(Integer, default=None)
    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    duration: Mapped[float | None] = mapped_column(Float, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


# ---------------------------------------------------------------------------
# Fase 3 — planificación de edición con Claude
# ---------------------------------------------------------------------------


class EditPlan(Base):
    """Plan de edición de un proyecto (uno por proyecto y recurso).

    El contenido vive en ``EditPlanVersion`` (instantáneas inmutables). ``current_version``
    es la versión de trabajo (deshacer/rehacer mueven el puntero sin borrar nada);
    ``approved_version`` apunta a la última versión aprobada, que nunca se modifica.
    """

    __tablename__ = "edit_plans"
    __table_args__ = (UniqueConstraint("project_id", name="uq_edit_plans_project"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    asset_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    status_history: Mapped[list[Any]] = mapped_column(JSON, default=list)
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    approved_version: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class EditPlanVersion(Base):
    """Instantánea completa y validada de un plan (documento ``PlanDocument``)."""

    __tablename__ = "edit_plan_versions"
    __table_args__ = (UniqueConstraint("plan_id", "number", name="uq_plan_versions_number"),)

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("edit_plans.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    parent_number: Mapped[int | None] = mapped_column(Integer, default=None)
    # generated | revision | alternative | manual | approval | refresh
    kind: Mapped[str] = mapped_column(String(20))
    summary: Mapped[str] = mapped_column(Text, default="")
    instruction: Mapped[str | None] = mapped_column(Text, default=None)
    document: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Base sobre la que se planificó (para detectar partes obsoletas).
    transcript_id: Mapped[str | None] = mapped_column(String(40), default=None)
    transcript_fingerprint: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    analysis_id: Mapped[str | None] = mapped_column(String(40), default=None)
    asset_fingerprint: Mapped[str | None] = mapped_column(String(64), default=None)
    config_hash: Mapped[str | None] = mapped_column(String(64), default=None)
    model: Mapped[str | None] = mapped_column(String(60), default=None)
    effort: Mapped[str | None] = mapped_column(String(10), default=None)
    immutable: Mapped[bool] = mapped_column(Boolean, default=False)
    session_id: Mapped[str | None] = mapped_column(String(40), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class PlanningSession(Base):
    """Una operación de IA solicitada por el usuario (generar, corregir, alternativa)."""

    __tablename__ = "planning_sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[str | None] = mapped_column(String(40), default=None)
    job_id: Mapped[str | None] = mapped_column(String(40), default=None)
    operation: Mapped[str] = mapped_column(String(20))  # generate | revise | alternative
    instruction: Mapped[str | None] = mapped_column(Text, default=None)
    scope: Mapped[list[Any]] = mapped_column(JSON, default=list)  # ids de intervenciones
    status: Mapped[str] = mapped_column(String(20), default="queued")
    strategy: Mapped[str | None] = mapped_column(String(20), default=None)  # single | hierarchical
    result_version: Mapped[int | None] = mapped_column(Integer, default=None)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)


class ClaudeCall(Base):
    """Registro de cada solicitud a Claude: qué se envió (resumen), consumo y resultado."""

    __tablename__ = "claude_calls"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True, default=None
    )
    session_id: Mapped[str | None] = mapped_column(String(40), index=True, default=None)
    step: Mapped[str] = mapped_column(String(30))  # test | full | global | segment | revision…
    transport: Mapped[str] = mapped_column(String(20))  # claude_code | api
    model: Mapped[str] = mapped_column(String(60))
    model_reported: Mapped[str | None] = mapped_column(String(60), default=None)
    effort: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20))  # ok | error | cancelled | invalid
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    output_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    cache_creation_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, default=None)
    duration_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    # Estimación que reporta Claude Code (precio de lista); no es un cargo.
    cost_estimate_usd: Mapped[float | None] = mapped_column(Float, default=None)
    billing: Mapped[str] = mapped_column(String(20))  # subscription | api
    rate_limit: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    sent: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # resumen de lo enviado
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


# ---------------------------------------------------------------------------
# Fase 4 — animaciones del plan aprobado
# ---------------------------------------------------------------------------


class AnimationDirection(Base):
    """Dirección declarativa de Claude para una intervención aprobada (reutilizable)."""

    __tablename__ = "animation_directions"
    __table_args__ = (
        UniqueConstraint("plan_id", "plan_version", "intervention_id", name="uq_anim_direction"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("edit_plans.id", ondelete="CASCADE"), index=True
    )
    plan_version: Mapped[int] = mapped_column(Integer)
    intervention_id: Mapped[str] = mapped_column(String(40))
    direction: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(20), default="claude")  # claude | compiler
    model: Mapped[str | None] = mapped_column(String(60), default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class AnimationRender(Base):
    """Clip de animación renderizado (ProRes 4444 con transparencia) para una intervención.

    ``purpose``: «final» (tamaño de exportación) o «preview» (resolución reducida). La caché se
    reutiliza por ``spec_hash`` (misma especificación + mismo motor = mismo clip).
    """

    __tablename__ = "animation_renders"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("edit_plans.id", ondelete="CASCADE"), index=True
    )
    plan_version: Mapped[int] = mapped_column(Integer)
    intervention_id: Mapped[str] = mapped_column(String(40), index=True)
    purpose: Mapped[str] = mapped_column(String(10), default="final")
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    fps: Mapped[float] = mapped_column(Float)
    spec_hash: Mapped[str] = mapped_column(String(64), index=True)
    spec: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # pip, sfx, cámara, notas
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending | rendering | ready | failed
    file_rel: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    render_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    size_bytes: Mapped[int | None] = mapped_column(Integer, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class AnimationPreview(Base):
    """Vista previa compuesta de una intervención (tramo del video con su animación)."""

    __tablename__ = "animation_previews"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("edit_plans.id", ondelete="CASCADE"), index=True
    )
    plan_version: Mapped[int] = mapped_column(Integer)
    intervention_id: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    window_start: Mapped[float] = mapped_column(Float)
    window_end: Mapped[float] = mapped_column(Float)
    key: Mapped[str] = mapped_column(String(64))
    file_rel: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class SceneVersion(Base):
    """Versiones de UNA escena (intervención animada) del plan aprobado (Fase 5).

    La número 1 es la escena tal como se aprobó. Cada modificación pedida a Claude o cada
    recuperación crea otra versión (candidata); al aprobarla se crea una nueva versión
    inmutable del plan con solo esa escena cambiada. Las versiones nunca se sobrescriben.
    """

    __tablename__ = "scene_versions"
    __table_args__ = (
        UniqueConstraint("plan_id", "intervention_id", "number", name="uq_scene_ver"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    plan_id: Mapped[str] = mapped_column(
        ForeignKey("edit_plans.id", ondelete="CASCADE"), index=True
    )
    intervention_id: Mapped[str] = mapped_column(String(40), index=True)
    number: Mapped[int] = mapped_column(Integer)
    parent_number: Mapped[int | None] = mapped_column(Integer, default=None)
    # approved: tal como estaba en una versión aprobada del plan · claude: modificación pedida ·
    # restored: copia de una versión anterior
    source: Mapped[str] = mapped_column(String(20), default="approved")
    base_plan_version: Mapped[int] = mapped_column(Integer)
    intervention: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    direction: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    instruction: Mapped[str | None] = mapped_column(Text, default=None)
    summary: Mapped[str] = mapped_column(Text, default="")
    changes: Mapped[list[str]] = mapped_column(JSON, default=list)
    # candidate: propuesta pendiente · applied: en uso en una versión aprobada · discarded
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    applied_plan_version: Mapped[int | None] = mapped_column(Integer, default=None)
    session_id: Mapped[str | None] = mapped_column(String(40), default=None)
    request_key: Mapped[str | None] = mapped_column(String(64), default=None, index=True)
    impact: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    preview: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
