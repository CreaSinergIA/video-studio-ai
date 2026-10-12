"""Modelos Pydantic de entrada/salida de la API (contrato con el frontend)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.edit_config import EditConfig, StyleDefinition
from app.domain.preferences import EditorState, GeneralPreferences

ProjectStatus = Literal["empty", "importing", "processing", "ready", "error", "unavailable"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


# --- Medios -----------------------------------------------------------------


class AudioTrackOut(BaseModel):
    index: int
    codec: str
    channels: int | None = None
    channel_layout: str | None = None
    sample_rate: int | None = None
    bit_rate: int | None = None
    language: str | None = None
    title: str | None = None


class FilmstripOut(BaseModel):
    url: str
    count: int
    tile_width: int
    tile_height: int
    interval: float


class AssetOut(ApiModel):
    id: str
    project_id: str
    role: str
    status: str
    error: str | None
    original_filename: str
    file_rel: str
    size_bytes: int
    sha256: str
    container: str
    format_name: str
    major_brand: str | None
    duration: float
    width: int
    height: int
    display_width: int
    display_height: int
    rotation: int
    orientation: str
    fps: float
    fps_num: int
    fps_den: int
    video_codec: str
    video_profile: str | None
    pix_fmt: str | None
    bit_depth: int | None
    color_transfer: str | None
    is_hdr: bool
    bit_rate: int | None
    frame_count: int | None
    has_audio: bool
    audio_tracks: list[AudioTrackOut]
    creation_time: str | None
    browser_playable: bool
    playback: Literal["original", "proxy", "unavailable"]
    stream_url: str | None
    original_url: str
    proxy_ready: bool
    thumbnail_url: str | None
    filmstrip: FilmstripOut | None
    waveform_url: str | None
    verified_at: datetime | None
    created_at: datetime


# --- Proyectos --------------------------------------------------------------


class ProjectSummary(BaseModel):
    id: str
    name: str
    status: ProjectStatus
    storage_id: str
    storage_available: bool
    dir_rel: str
    preset_id: str | None
    style_id: str
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None
    source: AssetOut | None
    active_job: JobOut | None


class ProjectDetail(ProjectSummary):
    config: EditConfig
    editor_state: EditorState
    storage_path: str | None
    storage_message: str | None
    assets: list[AssetOut]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    preset_id: str | None = None


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: EditConfig | None = None
    editor_state: EditorState | None = None


class ApplyPreset(BaseModel):
    preset_id: str


class DeleteProjectResult(BaseModel):
    deleted: bool
    files_removed: bool
    message: str


# --- Tareas -----------------------------------------------------------------


class JobOut(ApiModel):
    id: str
    kind: str
    label: str
    status: JobStatus
    project_id: str | None
    asset_id: str | None
    progress: float
    stage: str | None
    error: str | None
    result: dict[str, Any] | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# --- Importación ------------------------------------------------------------


class ImportCheckRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=500)
    size_bytes: int = Field(ge=0)
    quick_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    project_id: str | None = None


class DuplicateOut(BaseModel):
    project_id: str
    project_name: str
    asset_id: str
    original_filename: str
    created_at: datetime


class ImportCheckResult(BaseModel):
    ok: bool
    extension_ok: bool
    space_ok: bool
    free_bytes: int | None
    duplicates: list[DuplicateOut]
    errors: list[str]


class ImportResult(BaseModel):
    project: ProjectSummary
    asset: AssetOut
    job: JobOut | None


class ImportFromPath(BaseModel):
    path: str = Field(min_length=1, max_length=4096)
    project_id: str | None = None
    allow_duplicate: bool = False


class ImportFromPathResult(BaseModel):
    job: JobOut | None
    duplicates: list[DuplicateOut]


class PickedFiles(BaseModel):
    paths: list[str]
    supported: bool = True


# --- Presets y estilos ------------------------------------------------------


class PresetOut(ApiModel):
    id: str
    name: str
    description: str
    style_id: str
    is_builtin: bool
    is_default: bool
    config: EditConfig
    created_at: datetime
    updated_at: datetime


class PresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    config: EditConfig


class PresetUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    config: EditConfig | None = None


class PresetDuplicate(BaseModel):
    name: str | None = Field(default=None, max_length=120)


class CatalogOut(BaseModel):
    styles: list[StyleDefinition]
    subtitle_fonts: list[str]
    subtitle_animations: list[dict[str, str]]
    default_config: EditConfig


# --- Ajustes y almacenamiento -----------------------------------------------


class SettingsOut(BaseModel):
    general: GeneralPreferences


class StorageStatusOut(BaseModel):
    configured: bool
    available: bool
    path: str | None
    storage_id: str | None
    code: str | None
    message: str | None
    writable: bool
    free_bytes: int | None
    total_bytes: int | None
    volume_name: str | None
    is_external: bool
    checked_at: str


class StoragePathIn(BaseModel):
    path: str = Field(min_length=1, max_length=4096)


class StorageCandidateOut(BaseModel):
    path: str
    exists: bool
    parent_exists: bool
    is_dir: bool
    writable: bool
    has_marker: bool
    storage_id: str | None
    project_count: int
    is_empty: bool
    free_bytes: int | None
    total_bytes: int | None
    volume_name: str | None
    is_external: bool
    can_use: bool
    warnings: list[str]
    errors: list[str]
    suggested_path: str | None


class StorageConfigureResult(BaseModel):
    status: StorageStatusOut
    adopted_projects: int


class StorageLocationOut(BaseModel):
    id: str
    path: str
    active: bool
    available: bool
    message: str | None
    project_count: int
    last_seen_at: datetime | None


class BrowseEntry(BaseModel):
    name: str
    path: str
    is_storage: bool


class BrowseResult(BaseModel):
    path: str
    parent: str | None
    entries: list[BrowseEntry]
    shortcuts: list[BrowseEntry]


class PickedFolder(BaseModel):
    path: str | None
    supported: bool = True


ProjectSummary.model_rebuild()
ProjectDetail.model_rebuild()
