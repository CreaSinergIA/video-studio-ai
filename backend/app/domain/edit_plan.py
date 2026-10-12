"""Contrato del plan de edición (Fase 3) que consumirá el motor de animaciones (Fase 4).

Dos niveles:

- ``Proposal*``: lo que **Claude** puede proponer (esquema JSON que se le envía). No incluye
  ids, estados ni historial: eso lo asigna el backend.
- ``Plan*``: el documento persistido y validado. Cada intervención tiene id estable, estado
  de aprobación, tiempos calculados a partir de palabras medidas cuando hay anclaje, zonas
  protegidas medidas y la separación entre hechos observados e inferencias del modelo.

El vocabulario (tipos de intervención, elementos, movimientos, transiciones) es cerrado para
que la Fase 4 pueda traducirlo a componentes reales (Remotion, GSAP, SVG) sin interpretar
texto libre; las descripciones libres completan, no sustituyen, a los campos estructurados.
"""

from __future__ import annotations

from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.edit_config import StyleId

PLAN_SCHEMA_VERSION: Final = 1

InterventionType = Literal[
    "keep_original",  # conservar el video original tal cual
    "overlay_motion",  # motion graphics superpuestos al video
    "fullscreen_animation",  # animación a pantalla completa (sustituye la imagen un tramo)
    "diagram",  # diagrama explicativo (superpuesto o a pantalla completa)
    "kinetic_typography",  # tipografía cinética
    "screen_highlight",  # resaltado de una zona de una grabación de pantalla
    "transition",  # transición visual entre bloques
    "no_intervention",  # tramo donde explícitamente no conviene intervenir
]
INTERVENTION_LABELS: Final[dict[str, str]] = {
    "keep_original": "Conservar original",
    "overlay_motion": "Motion graphics superpuestos",
    "fullscreen_animation": "Animación a pantalla completa",
    "diagram": "Diagrama explicativo",
    "kinetic_typography": "Tipografía cinética",
    "screen_highlight": "Resaltado de pantalla",
    "transition": "Transición visual",
    "no_intervention": "Sin intervención",
}
# Tipos que no añaden nada visible (no compiten por el encuadre).
PASSIVE_TYPES: Final = frozenset({"keep_original", "no_intervention"})
# Tipos que ocupan todo el encuadre (no pueden solaparse entre sí).
FULLSCREEN_TYPES: Final = frozenset({"fullscreen_animation"})

ElementKind = Literal[
    "headline",
    "label",
    "keyword",
    "number_counter",
    "icon",
    "illustration",
    "character",
    "diagram_node",
    "connector",
    "arrow",
    "chart",
    "timeline",
    "list",
    "hud_panel",
    "data_readout",
    "grid",
    "shape",
    "highlight_box",
    "spotlight",
    "underline",
    "background",
    "particles",
]
Layout = Literal[
    "fullscreen",
    "overlay_top",
    "overlay_bottom",
    "overlay_left",
    "overlay_right",
    "overlay_corner",
    "around_subject",
    "split_screen",
    "picture_in_picture",
    "center",
]
Background = Literal["original_video", "dimmed_video", "blurred_video", "style_background"]
Entry = Literal[
    "none",
    "cut",
    "fade",
    "pop",
    "scale",
    "slide",
    "mask_reveal",
    "scan_reveal",
    "draw_on",
    "type_on",
    "stagger",
    "glitch",
    "morph",
]
Exit = Literal["none", "cut", "fade", "scale", "slide", "mask_out", "scan_out", "glitch", "morph"]
Easing = Literal["linear", "smooth", "exponential", "spring", "bounce"]
Camera = Literal["none", "slow_push_in", "punch_in", "pull_out", "pan", "reframe"]
TransitionKind = Literal[
    "none", "cut", "fade", "mask", "slide", "scan", "glitch", "whip", "morph", "draw_wipe", "zoom"
]
SfxKind = Literal[
    "whoosh", "pop", "click", "swoosh", "ding", "typing", "glitch", "riser", "impact", "paper"
]
Level = Literal["low", "medium", "high"]
SubtitleTreatment = Literal["keep", "hide", "move_top", "move_bottom", "integrate"]
SceneKind = Literal[
    "talking_head",
    "screen_recording",
    "app_demo",
    "no_face",
    "b_roll",
    "transition_pause",
    "other",
]
Policy = Literal["open", "light", "preserve"]
InterventionStatus = Literal["proposed", "accepted", "rejected", "needs_changes"]
PlanStatus = Literal["draft", "in_review", "approved", "rejected", "needs_changes"]
PLAN_STATUS_LABELS: Final[dict[str, str]] = {
    "draft": "Borrador",
    "in_review": "En revisión",
    "approved": "Aprobado",
    "rejected": "Rechazado",
    "needs_changes": "Requiere corrección",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Piezas comunes
# ---------------------------------------------------------------------------


class Region(_Strict):
    """Rectángulo normalizado (0–1) respecto al encuadre."""

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class Element(_Strict):
    kind: ElementKind
    description: str = Field(max_length=400)
    # Texto que aparecería en pantalla (si lo hay). Debe salir de lo que se dice.
    text: str | None = Field(default=None, max_length=120)
    role: Literal["primary", "secondary", "decoration"] = "primary"


class Composition(_Strict):
    layout: Layout
    background: Background
    region: Region | None = None  # zona ocupada (si no es pantalla completa)
    notes: str = Field(default="", max_length=400)


class Motion(_Strict):
    entry: Entry
    exit: Exit
    easing: Easing
    camera: Camera = "none"  # tratamiento del video original (zoom/reencuadre)
    emphasis: str = Field(default="", max_length=300)  # beats internos sincronizados con la voz
    entry_seconds: float = Field(default=0.4, ge=0, le=3)
    exit_seconds: float = Field(default=0.3, ge=0, le=3)


class Transitions(_Strict):
    into: TransitionKind = "none"
    out: TransitionKind = "none"


class SoundCue(_Strict):
    kind: SfxKind
    at: float = Field(ge=0)  # segundos absolutos del video
    description: str = Field(default="", max_length=200)


class Evidence(_Strict):
    observed: list[str] = Field(default_factory=list, max_length=8)
    inferred: list[str] = Field(default_factory=list, max_length=8)


# ---------------------------------------------------------------------------
# Lo que propone Claude
# ---------------------------------------------------------------------------


class ProposalIntervention(_Strict):
    # Anclaje a palabras medidas (ids de la transcripción). Si existen, mandan sobre los
    # segundos: el backend calcula el tiempo exacto a partir de las palabras.
    anchor_from_word: str | None = None
    anchor_to_word: str | None = None
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    segment_ids: list[str] = Field(default_factory=list, max_length=12)
    scene_indices: list[int] = Field(default_factory=list, max_length=12)
    frame_ids: list[str] = Field(default_factory=list, max_length=6)
    type: InterventionType
    goal: str = Field(max_length=400)
    visual_description: str = Field(max_length=1200)
    composition: Composition
    elements: list[Element] = Field(default_factory=list, max_length=12)
    motion: Motion
    transitions: Transitions
    sfx: list[SoundCue] = Field(default_factory=list, max_length=6)
    intensity: Level
    avoid_face: bool = True
    subtitles: SubtitleTreatment = "keep"
    rationale: str = Field(max_length=800)
    evidence: Evidence
    confidence: Level = "medium"


class StructurePart(_Strict):
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    label: str = Field(max_length=120)
    purpose: str = Field(max_length=300)


class SceneReading(_Strict):
    scene_index: int = Field(ge=0)
    kind: SceneKind
    policy: Policy  # open: se puede animar; light: intervenir poco; preserve: no tapar
    observed: str = Field(max_length=400)


class Understanding(_Strict):
    summary: str = Field(max_length=1500)
    topic: str = Field(max_length=200)
    intent: str = Field(max_length=400)
    audience: str = Field(max_length=200)
    tone: str = Field(max_length=200)
    content_kind: Literal[
        "talking_head", "screen_recording", "app_demo", "mixed", "b_roll", "other"
    ]
    structure: list[StructurePart] = Field(default_factory=list, max_length=20)
    scenes: list[SceneReading] = Field(default_factory=list, max_length=200)
    observed_facts: list[str] = Field(default_factory=list, max_length=12)
    inferences: list[str] = Field(default_factory=list, max_length=12)


class Direction(_Strict):
    concept: str = Field(max_length=600)
    visual_language: str = Field(max_length=600)
    pacing: str = Field(max_length=400)
    typography: str = Field(max_length=300)
    color_usage: str = Field(max_length=300)
    density: str = Field(max_length=300)


class ProposalPlan(_Strict):
    understanding: Understanding
    direction: Direction
    interventions: list[ProposalIntervention] = Field(max_length=200)


class ProposalUnderstandingOnly(_Strict):
    """Primera pasada de videos largos: comprensión global sin intervenciones."""

    understanding: Understanding
    direction: Direction


class ProposalSegment(_Strict):
    """Pasada por tramo en videos largos: solo intervenciones del tramo."""

    interventions: list[ProposalIntervention] = Field(max_length=80)


class ProposalRevision(_Strict):
    """Respuesta a una instrucción del usuario: solo las intervenciones afectadas.

    ``replace`` sustituye intervenciones existentes por id (mismo id), ``remove`` las
    elimina y ``add`` añade nuevas. Nada más del plan puede cambiar.
    """

    summary: str = Field(max_length=600)
    replace: list[RevisedIntervention] = Field(default_factory=list, max_length=40)
    remove: list[str] = Field(default_factory=list, max_length=40)
    add: list[ProposalIntervention] = Field(default_factory=list, max_length=20)


class RevisedIntervention(ProposalIntervention):
    id: str


ProposalRevision.model_rebuild()


# ---------------------------------------------------------------------------
# Documento persistido
# ---------------------------------------------------------------------------


class StatusEvent(_Strict):
    status: str
    at: str
    note: str = ""


class PlanIntervention(_Strict):
    id: str
    start: float
    end: float
    anchor_from_word: str | None = None
    anchor_to_word: str | None = None
    timing: Literal["word_anchored", "model_seconds", "repaired"]
    segment_ids: list[str] = Field(default_factory=list)
    # Topes de longitud (Community Edition): mismos límites que las propuestas de Claude, para
    # que una edición manual o un plan importado no puedan crecer sin control.
    transcript_excerpt: str = Field(default="", max_length=20000)
    scene_indices: list[int] = Field(default_factory=list)
    frame_ids: list[str] = Field(default_factory=list)
    type: InterventionType
    goal: str = Field(max_length=400)
    visual_description: str = Field(max_length=1200)
    style: StyleId
    composition: Composition
    elements: list[Element] = Field(default_factory=list)
    motion: Motion
    transitions: Transitions
    sfx: list[SoundCue] = Field(default_factory=list)
    intensity: Level
    avoid_face: bool = True
    # Zonas que no se deben tapar, medidas (rostros detectados en los fotogramas del tramo).
    protected_regions: list[Region] = Field(default_factory=list)
    subtitles: SubtitleTreatment = "keep"
    rationale: str = Field(max_length=800)
    evidence: Evidence
    confidence: Level = "medium"
    status: InterventionStatus = "proposed"
    status_history: list[StatusEvent] = Field(default_factory=list)
    user_note: str = Field(default="", max_length=1000)
    origin: Literal["generated", "revised", "alternative", "manual"] = "generated"
    revision: int = 1
    warnings: list[str] = Field(default_factory=list)
    # Huella de lo que se usó para proponerla: segmentos (id → huella) y análisis visual.
    # Permite saber, intervención a intervención, si quedó desfasada.
    basis_segments: dict[str, str] = Field(default_factory=dict)
    basis_analysis: str | None = None
    # Marcado cuando la transcripción o el análisis cambiaron después de proponerla.
    stale: bool = False
    stale_reason: str = ""

    @property
    def duration(self) -> float:
        return round(self.end - self.start, 3)


class PlanDocument(_Strict):
    schema_version: int = PLAN_SCHEMA_VERSION
    style: StyleId
    understanding: Understanding
    direction: Direction
    interventions: list[PlanIntervention] = Field(default_factory=list)
    # Correcciones automáticas y avisos de la validación (visibles para el usuario).
    validation: dict[str, Any] = Field(default_factory=dict)
