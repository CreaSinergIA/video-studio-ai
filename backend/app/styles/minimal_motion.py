"""Minimal Motion: tipografía cinética editorial y geometría sobria."""

from __future__ import annotations

from app.domain.edit_config import EditConfig
from app.styles.base import StyleDefinition, register


def _palette(config: EditConfig) -> dict[str, str]:
    prm = config.style.minimal_motion
    tone = prm.background_tone
    if tone == "light":
        return {
            "bg": "#F5F0E8",
            "surface": "#FBF8F3",
            "text": "#141416",
            "muted": "#7A746C",
            "accent": "#141416",
            "secondary": "#8A847B",
            "highlight": "#141416",
        }
    if tone == "neutral":
        return {
            "bg": "#2A2826",
            "surface": "#33302D",
            "text": "#F5F0E8",
            "muted": "#A39C92",
            "accent": prm.accent_color,
            "secondary": "#B8AFA3",
            "highlight": "#FFFFFF",
        }
    return {
        "bg": "#0E0E10",
        "surface": "#141416",
        "text": "#F5F0E8",
        "muted": "#8A847B",
        "accent": prm.accent_color,
        "secondary": "#B8AFA3",
        "highlight": "#FFFFFF",
    }


def _default(itype: str, k: set[str], n_items: int) -> str:
    if itype == "transition":
        return "min.transition"
    if itype == "screen_highlight":
        return "min.highlight"
    if "number_counter" in k:
        return "min.number"
    if "list" in k:
        return "min.list"
    if itype == "diagram" or k & {"diagram_node", "timeline", "arrow"}:
        return "min.steps" if n_items != 2 else "min.compare"
    return "min.statement"


STYLE = register(
    StyleDefinition(
        id="minimal_motion",
        name="Minimal Motion",
        templates={
            "min.statement": "frases grandes que emergen palabra a palabra; contraste de pesos y subrayado",
            "min.list": "lista sobria numerada con reglas finas",
            "min.compare": "comparación en dos columnas (lo negado se atenúa y se tacha)",
            "min.number": "cifra grande fina con arco que se completa y leyenda",
            "min.steps": "pasos unidos por una línea fina con puntos que se activan",
            "min.highlight": "contorno redondeado fino sobre una zona real y leyenda",
            "min.transition": "lámina limpia que cruza el encuadre (máscara) o fundido",
        },
        palette=_palette,
        default_template=_default,
        chain_overlays=True,
    )
)
