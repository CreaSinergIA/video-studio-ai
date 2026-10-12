"""Motion Tech: interfaz tecnológica (HUD), diagramas y conexiones dinámicas."""

from __future__ import annotations

from app.domain.edit_config import EditConfig
from app.styles.base import StyleDefinition, register


def _palette(config: EditConfig) -> dict[str, str]:
    prm = config.style.motion_tech
    return {
        "bg": "#05070D",
        "surface": "#0B1220",
        "text": "#E2E8F0",
        "muted": "#64748B",
        "accent": prm.accent_color,
        "secondary": prm.secondary_color,
        "highlight": "#F0FDFF",
    }


def _default(itype: str, k: set[str], n_items: int) -> str:
    if itype == "transition":
        return "tech.transition"
    if itype == "screen_highlight":
        return "tech.highlight"
    if "number_counter" in k or ("data_readout" in k and n_items <= 1):
        return "tech.readout"
    if k & {"diagram_node", "connector"}:
        return "tech.nodes"
    if k & {"list", "timeline"}:
        return "tech.pipeline"
    if itype == "kinetic_typography" and not k & {"hud_panel", "data_readout"}:
        return "tech.type"
    return "tech.panel"


STYLE = register(
    StyleDefinition(
        id="motion_tech",
        name="Motion Tech",
        templates={
            "tech.panel": "panel HUD: etiqueta de consola, titular que se descodifica y filas de datos",
            "tech.nodes": "grafo de nodos con icono que se activan y conectores con paquetes de datos",
            "tech.pipeline": "pasos numerados con barra de progreso y checks (flujos, automatizaciones)",
            "tech.readout": "cifra grande que cuenta con etiqueta y medidor segmentado",
            "tech.type": "tipografía cinética que se descodifica; tachado con glitch para lo negado",
            "tech.highlight": "resaltado de una zona real (grabación de pantalla) con corchetes y etiqueta",
            "tech.transition": "transición de escaneo con retícula y cortes RGB",
        },
        palette=_palette,
        default_template=_default,
        chain_overlays=True,
        container_leads=False,  # el título del panel se ve desde el principio
    )
)
