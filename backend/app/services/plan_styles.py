"""Reglas de cada estilo de edición: vocabulario permitido y criterios de dirección.

Se usan dos veces: para orientar a Claude (prompt) y para validar sus propuestas (backend).
La diferencia entre estilos no es de color: cambian los tipos de elementos, el movimiento,
el ritmo, la composición, la tipografía y las transiciones. Los parámetros individuales del
preset (densidad de HUD, easing, trazo, paleta…) afinan cada regla.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.edit_config import EditConfig


@dataclass(frozen=True)
class StyleRules:
    id: str
    name: str
    brief: str
    preferred_types: tuple[str, ...]
    elements: frozenset[str]
    entries: frozenset[str]
    exits: frozenset[str]
    easings: frozenset[str]
    transitions: frozenset[str]
    default_entry: str
    default_exit: str
    default_easing: str
    composition: str
    typography: str
    rhythm: str
    avoid: str
    # Sustitutos cuando Claude propone un elemento ajeno al estilo.
    element_fallback: dict[str, str]


_COMMON_ELEMENTS = {"headline", "label", "keyword", "highlight_box", "arrow", "shape", "list"}

RULES: dict[str, StyleRules] = {
    "motion_tech": StyleRules(
        id="motion_tech",
        name="Motion Tech",
        brief=(
            "Motion graphics tecnológicos: interfaces tipo HUD, diagramas de nodos y "
            "conexiones, lecturas de datos, retículas y contadores. Precisión y energía."
        ),
        preferred_types=("overlay_motion", "diagram", "screen_highlight", "kinetic_typography"),
        elements=frozenset(
            _COMMON_ELEMENTS
            | {
                "hud_panel",
                "data_readout",
                "diagram_node",
                "connector",
                "grid",
                "number_counter",
                "chart",
                "timeline",
                "spotlight",
                "underline",
                "particles",
                "icon",
                "background",
            }
        ),
        entries=frozenset(
            {
                "scan_reveal",
                "glitch",
                "stagger",
                "draw_on",
                "type_on",
                "scale",
                "slide",
                "cut",
                "fade",
                "none",
            }
        ),
        exits=frozenset({"scan_out", "glitch", "fade", "cut", "slide", "scale", "none"}),
        easings=frozenset({"exponential", "linear", "smooth"}),
        transitions=frozenset({"scan", "glitch", "slide", "cut", "zoom", "whip", "none"}),
        default_entry="scan_reveal",
        default_exit="scan_out",
        default_easing="exponential",
        composition=(
            "Retícula modular, anclas en esquinas y bordes, paneles con profundidad; los "
            "diagramas se construyen nodo a nodo con conectores que se trazan."
        ),
        typography="Grotesca geométrica para titulares y monoespaciada para datos/etiquetas.",
        rhythm="Ágil: intervenciones breves (1,5–5 s) y frecuentes, sincronizadas con conceptos clave.",
        avoid="Ilustraciones dibujadas a mano, personajes cartoon, texturas de papel.",
        element_fallback={"character": "icon", "illustration": "diagram_node"},
    ),
    "minimal_motion": StyleRules(
        id="minimal_motion",
        name="Minimal Motion",
        brief=(
            "Tipografía cinética y composiciones limpias con mucho espacio negativo. Una sola "
            "idea por plano; nada se mueve sin motivo."
        ),
        preferred_types=("kinetic_typography", "overlay_motion", "transition", "diagram"),
        elements=frozenset(
            _COMMON_ELEMENTS | {"underline", "timeline", "background", "number_counter"}
        ),
        entries=frozenset(
            {"mask_reveal", "fade", "slide", "type_on", "stagger", "scale", "cut", "none"}
        ),
        exits=frozenset({"mask_out", "fade", "slide", "cut", "none"}),
        easings=frozenset({"smooth", "spring"}),
        transitions=frozenset({"fade", "mask", "slide", "cut", "none"}),
        default_entry="mask_reveal",
        default_exit="fade",
        default_easing="smooth",
        composition=(
            "Asimetría equilibrada, márgenes amplios, un único foco; geometría simple (líneas, "
            "rectángulos, círculos) como apoyo, nunca decoración recargada."
        ),
        typography="Sans neutra de gran tamaño con contraste de pesos; palabras clave aisladas.",
        rhythm="Pausado: pocas intervenciones, más largas (3–7 s), que dejan respirar la voz.",
        avoid="HUD, glitch, partículas, retículas densas, personajes, exceso de iconos.",
        element_fallback={
            "hud_panel": "label",
            "data_readout": "number_counter",
            "grid": "shape",
            "particles": "shape",
            "diagram_node": "shape",
            "connector": "arrow",
            "chart": "number_counter",
            "character": "keyword",
            "illustration": "shape",
            "icon": "shape",
            "spotlight": "highlight_box",
        },
    ),
    "creative_explainer": StyleRules(
        id="creative_explainer",
        name="Creative Explainer",
        brief=(
            "Ilustraciones y figuras vectoriales que se dibujan en pantalla para explicar "
            "conceptos: metáforas visuales, flechas, iconos, esquemas y personajes sencillos."
        ),
        preferred_types=("diagram", "fullscreen_animation", "overlay_motion", "kinetic_typography"),
        elements=frozenset(
            _COMMON_ELEMENTS
            | {
                "illustration",
                "character",
                "icon",
                "diagram_node",
                "connector",
                "underline",
                "timeline",
                "chart",
                "number_counter",
                "background",
                "spotlight",
            }
        ),
        entries=frozenset(
            {
                "draw_on",
                "pop",
                "morph",
                "stagger",
                "scale",
                "slide",
                "type_on",
                "fade",
                "cut",
                "none",
            }
        ),
        exits=frozenset({"morph", "scale", "fade", "slide", "cut", "none"}),
        easings=frozenset({"spring", "bounce", "smooth"}),
        transitions=frozenset(
            {"draw_wipe", "morph", "whip", "slide", "cut", "fade", "zoom", "none"}
        ),
        default_entry="draw_on",
        default_exit="morph",
        default_easing="spring",
        composition=(
            "Escenas ilustradas centradas en el concepto con anotaciones alrededor; el presentador "
            "puede quedar en un lateral o en picture-in-picture mientras se dibuja la idea."
        ),
        typography="Redondeada y amable, rótulos tipo pizarra o escritos a mano.",
        rhythm="Medio: sigue la explicación paso a paso; cada paso de la idea añade un trazo.",
        avoid="HUD, lecturas de datos técnicas, glitch, estética fría de interfaz.",
        element_fallback={
            "hud_panel": "illustration",
            "data_readout": "number_counter",
            "grid": "background",
            "particles": "shape",
        },
    ),
}

# Intervenciones visibles por minuto orientativas según la intensidad configurada.
DENSITY_PER_MINUTE = {"low": 4, "medium": 7, "high": 10}


def style_params(config: EditConfig) -> dict[str, Any]:
    style = config.style
    return getattr(style, style.id).model_dump(mode="json")


def adjusted(rules: StyleRules, config: EditConfig) -> dict[str, Any]:
    """Reglas efectivas para este proyecto (estilo + parámetros del preset)."""
    params = style_params(config)
    entries = set(rules.entries)
    easings = set(rules.easings)
    transitions = set(rules.transitions)
    notes: list[str] = []
    if rules.id == "minimal_motion":
        easings = {params.get("easing", "smooth")} | {"smooth"}
        notes.append(
            f"Easing preferido: {params.get('easing')}; transición: {params.get('transition')}."
        )
        notes.append(
            f"Escala tipográfica {params.get('type_scale')}, espacio {params.get('whitespace')}, fondo {params.get('background_tone')}."
        )
    elif rules.id == "motion_tech":
        if not params.get("grid_overlay", True):
            notes.append("El usuario desactivó las retículas: no usar elementos «grid».")
        if not params.get("data_callouts", True):
            notes.append("El usuario desactivó las lecturas de datos: no usar «data_readout».")
        notes.append(
            f"Densidad de HUD {params.get('hud_density')}, brillo {params.get('glow')} %, transición preferida {params.get('transition')}."
        )
    else:
        notes.append(
            f"Paleta {params.get('palette')}, trazo {params.get('stroke')}, iconos {params.get('icon_style')}, "
            f"textura de papel {'sí' if params.get('paper_texture') else 'no'}, velocidad de dibujo {params.get('draw_on_speed')}."
        )
    elements = set(rules.elements)
    if rules.id == "motion_tech":
        if not params.get("grid_overlay", True):
            elements.discard("grid")
        if not params.get("data_callouts", True):
            elements.discard("data_readout")
    anim = config.animations
    return {
        "rules": rules,
        "params": params,
        "elements": sorted(elements),
        "entries": sorted(entries),
        "exits": sorted(rules.exits),
        "easings": sorted(easings),
        "transitions": sorted(transitions),
        "notes": notes,
        "density_per_minute": DENSITY_PER_MINUTE[anim.intensity],
        "animations": anim.model_dump(mode="json"),
        "sfx": config.audio.model_dump(mode="json"),
        "subtitles": {
            "enabled": config.subtitles.enabled,
            "mode": config.subtitles.mode,
            "position": "auto" if config.subtitles.auto_position else config.subtitles.position,
        },
    }
