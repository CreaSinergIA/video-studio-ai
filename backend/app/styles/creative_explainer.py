"""Creative Explainer: ilustración a mano, iconos y personajes sobre papel."""

from __future__ import annotations

from app.domain.edit_config import EditConfig
from app.styles.base import StyleDefinition, register


def _palette(config: EditConfig) -> dict[str, str]:
    prm = config.style.creative_explainer
    base = {
        "bg": "#FFF8EC",
        "surface": "#FFE9C7",
        "text": "#2D3142",
        "muted": "#8D8A84",
        "accent": prm.accent_color,
        "secondary": "#4F9D9A",
        "highlight": "#FFD166",
    }
    if prm.palette == "pastel":
        base.update(surface="#F3E8FF", highlight="#FDE68A", secondary="#93C5FD")
    elif prm.palette == "paper":
        base.update(bg="#F4EFE6", surface="#E9E1D3", highlight="#F2C14E", secondary="#6B8F71")
    return base


def _default(itype: str, k: set[str], n_items: int) -> str:
    if itype == "transition":
        return "exp.transition"
    if itype == "screen_highlight":
        return "exp.highlight"
    if "character" in k:
        return "exp.character"
    if "list" in k:
        return "exp.checklist"
    if k & {"diagram_node", "connector", "arrow"} or itype == "diagram":
        return "exp.sketch"
    return "exp.icons"


STYLE = register(
    StyleDefinition(
        id="creative_explainer",
        name="Creative Explainer",
        templates={
            "exp.sketch": "esquema dibujado a mano: cajas/óvalos con icono y rótulo, flechas",
            "exp.icons": "secuencia de iconos dibujados con rótulo y flechas (metáfora visual)",
            "exp.character": "personaje sencillo con bocadillo que dice el contenido",
            "exp.checklist": "lista con casillas dibujadas que se marcan o se tachan",
            "exp.highlight": "círculo de rotulador sobre una zona real con flecha y rótulo",
            "exp.transition": "hoja de papel que barre el encuadre con trazo de rotulador",
        },
        palette=_palette,
        default_template=_default,
        # Sus transiciones propias son las mejor valoradas: sin enlace entre superposiciones.
        chain_overlays=False,
        pip_shape="circle",
        # Fase 5: con interfaz social, recuadro algo menor para dejar más alto al boceto.
        fullscreen_pip_max_with_ui=0.18,
        fullscreen_gap_with_ui=0.025,
    )
)
