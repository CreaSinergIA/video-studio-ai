"""Preferencias generales de la aplicación y estado del editor por proyecto."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GeneralPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: Literal["dark", "light", "system"] = "dark"
    library_view: Literal["grid", "list"] = "grid"
    library_sort: Literal["recent", "created", "name", "duration"] = "recent"
    autoplay_on_open: bool = False
    loop_playback: bool = False
    remember_playback_position: bool = True
    default_volume: float = Field(0.8, ge=0, le=1)
    # Proxy H.264 de reproducción: "auto" solo cuando el códec no es reproducible en navegador.
    playback_proxy: Literal["auto", "always", "never"] = "auto"
    reduce_motion: Literal["system", "on", "off"] = "system"
    default_preset_id: str | None = None


class EditorState(BaseModel):
    """Estado del reproductor guardado por proyecto."""

    model_config = ConfigDict(extra="ignore")

    position: float = Field(0, ge=0)
    volume: float = Field(0.8, ge=0, le=1)
    muted: bool = False
    settings_tab: str = "style"


TranscriptionModelId = Literal["large-v3-turbo", "large-v3-turbo-q4"]
TranscriptionLanguage = Literal["auto", "es", "en", "pt", "fr", "it", "de", "ca"]


class AnalysisPreferences(BaseModel):
    """Parámetros del análisis audiovisual (Fase 2). Cambiarlos invalida la caché afectada."""

    model_config = ConfigDict(extra="forbid")

    transcription_model: TranscriptionModelId = "large-v3-turbo"
    language: TranscriptionLanguage = "auto"
    # Sensibilidad de corte: puntuación mínima (0–1) de cambio estructural entre fotogramas.
    scene_threshold: float = Field(0.38, ge=0.1, le=0.9)
    min_scene_seconds: float = Field(0.6, ge=0.2, le=5)
    static_min_seconds: float = Field(2.0, ge=0.5, le=30)
    frame_interval_seconds: float = Field(8.0, ge=1, le=120)
    max_frames: int = Field(150, ge=10, le=1000)
    detect_faces: bool = True


ClaudeModelId = Literal["claude-opus-5-5"]
ClaudeEffort = Literal["low", "medium", "high"]


class ClaudePreferences(BaseModel):
    """Conexión con Claude (Fase 3). Independiente del modelo con el que se desarrolla la app."""

    model_config = ConfigDict(extra="forbid")

    # claude_code: CLI de Claude Code instalado y con sesión del usuario (plan de suscripción).
    # api: Messages API con clave guardada en el llavero de macOS (facturación por tokens).
    # Community Edition: clave de API propia del usuario (mecanismo autorizado por Anthropic
    # para aplicaciones de terceros). «claude_code» solo existe para pruebas con un CLI simulado.
    transport: Literal["claude_code", "api"] = "api"
    model: ClaudeModelId = "claude-opus-5-5"
    effort: ClaudeEffort = "medium"
    cli_path: str | None = None  # None: detección automática
    timeout_seconds: int = Field(600, ge=60, le=1800)
    # Tope por solicitud sobre la *estimación* de Claude Code (protección ante desbordes).
    max_budget_usd_per_call: float = Field(3.0, ge=0.2, le=20)
    # Fotogramas máximos por solicitud (se eligen los más informativos).
    max_frames: int = Field(12, ge=2, le=24)
    # Control de solicitudes (Fase 5): límite autorizado en 24 h (ventana móvil; superarlo exige
    # confirmación explícita por operación), reintentos por errores transitorios y tope duro de
    # solicitudes de una misma operación (incluidos los reintentos).
    daily_request_limit: int = Field(30, ge=1, le=500)
    max_retries: int = Field(2, ge=0, le=4)
    max_requests_per_operation: int = Field(12, ge=1, le=40)
