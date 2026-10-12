"""Esquema de la configuración de edición (presets y ajustes por proyecto).

Es el *contrato* que consumirán las fases futuras (subtítulos en Fase 2, plan creativo de
Claude en Fase 3, animaciones en Fase 4 y exportación en Fase 5). En Fase 1 solo se
valida, persiste y edita: ningún motor audiovisual lo usa todavía.

Versionado: ``schema_version`` permite migrar configuraciones guardadas en el futuro.
"""

from __future__ import annotations

import re
from typing import Annotated, Final, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

CONFIG_SCHEMA_VERSION: Final = 2  # v2 (Fase 2): subtítulos con modo y número de líneas

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _hex_color(value: str) -> str:
    if not _HEX.match(value):
        raise ValueError("Color inválido: use formato hexadecimal #RRGGBB")
    return value.upper()


HexColor = Annotated[str, AfterValidator(_hex_color)]

StyleId = Literal["motion_tech", "minimal_motion", "creative_explainer"]
Level = Literal["low", "medium", "high"]
Pace = Literal["slow", "medium", "fast"]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Parámetros específicos de cada estilo
# ---------------------------------------------------------------------------


class MotionTechParams(_Model):
    accent_color: HexColor = "#22D3EE"
    secondary_color: HexColor = "#A78BFA"
    grid_overlay: bool = True
    hud_density: Level = "medium"
    glow: int = Field(60, ge=0, le=100)
    data_callouts: bool = True
    transition: Literal["glitch", "scan", "slide"] = "scan"


class MinimalMotionParams(_Model):
    accent_color: HexColor = "#F5F0E8"
    background_tone: Literal["dark", "neutral", "light"] = "dark"
    whitespace: Literal["airy", "balanced"] = "airy"
    type_scale: Literal["small", "medium", "large"] = "large"
    easing: Literal["smooth", "spring"] = "smooth"
    transition: Literal["fade", "mask", "slide"] = "mask"


class CreativeExplainerParams(_Model):
    accent_color: HexColor = "#FF7A59"
    palette: Literal["vibrant", "pastel", "paper"] = "vibrant"
    stroke: Literal["hand_drawn", "clean"] = "hand_drawn"
    icon_style: Literal["doodle", "flat"] = "doodle"
    paper_texture: bool = True
    draw_on_speed: Pace = "medium"


class StyleSettings(_Model):
    """Estilo activo + parámetros de *todos* los estilos (cambiar de estilo no pierde ajustes)."""

    id: StyleId = "motion_tech"
    motion_tech: MotionTechParams = Field(default_factory=MotionTechParams)
    minimal_motion: MinimalMotionParams = Field(default_factory=MinimalMotionParams)
    creative_explainer: CreativeExplainerParams = Field(default_factory=CreativeExplainerParams)


# ---------------------------------------------------------------------------
# Subtítulos, animaciones, audio y exportación
# ---------------------------------------------------------------------------

SubtitleFont = Literal[
    "Inter", "Montserrat", "Poppins", "Bebas Neue", "Anton", "DM Serif Display", "JetBrains Mono"
]
SubtitleAnimation = Literal[
    "none", "fade", "pop", "slide_up", "karaoke", "word_by_word", "typewriter"
]


class SubtitleSettings(_Model):
    enabled: bool = True
    font_family: SubtitleFont = "Montserrat"
    font_weight: Literal[400, 500, 600, 700, 800, 900] = 800
    # Tamaño en px de referencia para un lado corto de 1080 px; se escala con el video.
    font_size: int = Field(64, ge=24, le=160)
    uppercase: bool = False
    text_color: HexColor = "#FFFFFF"
    highlight_color: HexColor = "#FACC15"
    outline_enabled: bool = True
    outline_color: HexColor = "#000000"
    outline_width: int = Field(4, ge=0, le=16)
    shadow_enabled: bool = True
    shadow_color: HexColor = "#000000"
    shadow_blur: int = Field(12, ge=0, le=40)
    position: Literal["top", "middle", "bottom"] = "bottom"
    # Si está activo, la posición final depende de la orientación (vertical: tercio inferior
    # elevado para evitar la interfaz de redes; horizontal: parte inferior clásica).
    auto_position: bool = True
    margin_percent: int = Field(12, ge=0, le=40)
    # Fase 5: «platform» mantiene los subtítulos dentro de la zona libre de la interfaz de la
    # red social de destino (Destino → plataforma), sin tapar ojos ni boca. Desactivado por
    # defecto: solo se aplica si el usuario lo elige (no cambia proyectos existentes).
    safe_area: Literal["none", "platform"] = "none"
    max_words_per_line: int = Field(4, ge=1, le=10)
    animation: SubtitleAnimation = "pop"
    # Fase 2. «classic»: bloques/frases con transición discreta. «dynamic»: sincronizado por
    # palabra con resaltado de la palabra activa.
    mode: Literal["classic", "dynamic"] = "dynamic"
    max_lines: int = Field(2, ge=1, le=3)


class AnimationSettings(_Model):
    enabled: bool = True
    intensity: Level = "medium"
    placement: Literal["discrete", "balanced", "fullscreen"] = "balanced"
    pace: Pace = "medium"


class AudioSettings(_Model):
    sfx_enabled: bool = True
    sfx_volume: int = Field(70, ge=0, le=100)
    # Fase 4.1: presencia de los efectos respecto a la voz medida (suave / equilibrada / intensa).
    sfx_intensity: Literal["soft", "balanced", "strong"] = "balanced"
    # Decisión de producto: Video Studio AI no añade música de fondo.
    background_music: Literal[False] = False


class ExportSettings(_Model):
    resolution: Literal["original", "1080p", "4k"] = "original"
    fps: Literal["original", 24, 25, 30, 50, 60] = "original"
    format: Literal["mp4_h264", "mp4_hevc", "mov_prores"] = "mp4_h264"
    quality: Literal["high", "max"] = "high"
    # Fase 2: VideoToolbox (hardware) iguala la calidad por tamaño del software y es 4–25×
    # más rápido en Apple Silicon (medido con VMAF en el desarrollo). Sin hardware → software.
    encoder: Literal["hardware", "software"] = "hardware"


class DeliverySettings(_Model):
    # Fase 4.1: red social de destino. Sus zonas de interfaz se protegen al colocar las
    # animaciones (solo en videos verticales). Universal = Instagram Reels + TikTok.
    platform: Literal["universal", "instagram_reels", "tiktok", "none"] = "universal"


class EditConfig(_Model):
    # Las configuraciones v1 (Fase 1) se aceptan: los campos nuevos toman su valor por defecto.
    schema_version: Literal[1, 2] = CONFIG_SCHEMA_VERSION
    style: StyleSettings = Field(default_factory=StyleSettings)
    subtitles: SubtitleSettings = Field(default_factory=SubtitleSettings)
    animations: AnimationSettings = Field(default_factory=AnimationSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    export: ExportSettings = Field(default_factory=ExportSettings)
    delivery: DeliverySettings = Field(default_factory=DeliverySettings)


# ---------------------------------------------------------------------------
# Catálogo de estilos (identidad visual y lenguaje de movimiento)
# ---------------------------------------------------------------------------


class StyleDefinition(BaseModel):
    id: StyleId
    name: str
    tagline: str
    description: str
    palette: list[str]
    typography: str
    motion_language: str
    composition: str
    pacing: str
    best_for: list[str]


STYLE_CATALOG: list[StyleDefinition] = [
    StyleDefinition(
        id="motion_tech",
        name="Motion Tech",
        tagline="Interfaces, datos y conexiones",
        description=(
            "Motion graphics tecnológicos: paneles tipo HUD, diagramas que se conectan, "
            "contadores, líneas de datos y elementos digitales superpuestos con precisión."
        ),
        palette=["#05070D", "#22D3EE", "#A78BFA", "#E2E8F0"],
        typography="Grotesca geométrica + monoespaciada para datos y etiquetas",
        motion_language=(
            "Movimientos rápidos y precisos con easing exponencial; revelados por escaneo, "
            "trazos de conexión y micro-glitches en transiciones."
        ),
        composition="Retículas modulares, anclas en esquinas, capas con profundidad y brillo",
        pacing="Ágil: cortes frecuentes y llamadas de atención cada pocas frases",
        best_for=["Tecnología", "IA y software", "Producto", "Datos y negocio"],
    ),
    StyleDefinition(
        id="minimal_motion",
        name="Minimal Motion",
        tagline="Tipografía cinética y calma",
        description=(
            "Animaciones suaves y elegantes: tipografía cinética, mucho espacio negativo, "
            "composiciones limpias y transiciones con máscaras."
        ),
        palette=["#0E0E10", "#F5F0E8", "#B8AFA3", "#6B6B70"],
        typography="Sans neutra de gran tamaño con contraste de pesos",
        motion_language=(
            "Easing suave (ease-in-out) o con muelle sutil; revelados por máscara, fundidos y "
            "desplazamientos cortos. Nada se mueve sin motivo."
        ),
        composition="Asimetría equilibrada, un solo foco por plano, márgenes amplios",
        pacing="Pausado: deja respirar las ideas y enfatiza palabras clave",
        best_for=["Marca personal", "Reflexiones", "Lifestyle", "Contenido premium"],
    ),
    StyleDefinition(
        id="creative_explainer",
        name="Creative Explainer",
        tagline="Ilustración que explica",
        description=(
            "Ilustraciones, dibujos y elementos vectoriales que se trazan en pantalla para "
            "explicar conceptos: flechas, iconos, esquemas y metáforas visuales."
        ),
        palette=["#FFF8EC", "#FF7A59", "#FFD166", "#2D3142"],
        typography="Redondeada y amable, con rótulos tipo pizarra",
        motion_language=(
            "Trazos que se dibujan (draw-on), rebotes orgánicos, elementos que entran con "
            "personalidad y se transforman entre sí."
        ),
        composition="Escenas ilustradas centradas en el concepto, con anotaciones alrededor",
        pacing="Medio: sigue el hilo de la explicación paso a paso",
        best_for=["Educación", "Tutoriales", "Explicaciones", "Storytelling"],
    ),
]


def default_config_for_style(style_id: StyleId) -> EditConfig:
    """Configuración base coherente con el carácter de cada estilo."""
    config = EditConfig(style=StyleSettings(id=style_id))
    if style_id == "motion_tech":
        config.subtitles.font_family = "Montserrat"
        config.subtitles.animation = "pop"
        config.subtitles.highlight_color = "#22D3EE"
        config.animations.pace = "fast"
        config.animations.intensity = "high"
    elif style_id == "minimal_motion":
        config.subtitles.font_family = "Inter"
        config.subtitles.font_weight = 600
        config.subtitles.outline_enabled = False
        config.subtitles.animation = "fade"
        config.subtitles.mode = "classic"
        config.subtitles.highlight_color = "#F5F0E8"
        config.animations.pace = "slow"
        config.animations.intensity = "low"
        config.animations.placement = "discrete"
        config.audio.sfx_volume = 45
    else:
        config.subtitles.font_family = "Poppins"
        config.subtitles.animation = "word_by_word"
        config.subtitles.highlight_color = "#FF7A59"
        config.animations.placement = "fullscreen"
    return config
