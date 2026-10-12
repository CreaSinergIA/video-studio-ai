"""Registro de estilos de edición (Fase 5): todo lo que define un estilo en el motor de
animaciones vive en su módulo de este paquete, no repartido por el compilador.

Para añadir un estilo (ver «Cómo añadir un estilo» en la documentación):
1. Backend: un módulo con su ``StyleDefinition`` registrado aquí; sus parámetros de preset en
   ``domain/edit_config.py`` (``StyleId`` y el modelo de parámetros) y sus reglas de
   planificación para Claude en ``services/plan_styles.py``.
2. Renderizador: sus componentes en ``renderer/src/styles/<estilo>.tsx`` y su entrada en
   ``renderer/src/styles/registry.ts`` (mismas plantillas que aquí; una prueba lo comprueba).
3. Panel: nombre y controles de sus parámetros (``STYLE_META`` y ``ConfigForm``).
El motor (compilador, zonas seguras, caché, compositor, efectos) no se toca.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from app.domain.edit_config import EditConfig


@dataclass(frozen=True)
class StyleDefinition:
    id: str
    name: str
    # Plantillas del estilo → descripción que recibe Claude al dirigir (orden = preferencia).
    templates: dict[str, str]
    # Paleta a partir de los parámetros del preset.
    palette: Callable[[EditConfig], dict[str, str]]
    # Plantilla sin Claude: (tipo de intervención, tipos de elemento, nº de elementos) → id.
    default_template: Callable[[str, set[str], int], str]
    fonts: dict[str, str] = field(
        default_factory=lambda: {
            "display": "VSA Montserrat",
            "body": "VSA Inter",
            "mono": "VSA Mono",
            "hand": "VSA Caveat",
        }
    )
    # Dos superposiciones seguidas comparten contenedor (transición enlazada).
    chain_overlays: bool = False
    # El contenedor entra justo antes del primer concepto dicho (no al inicio del tramo).
    container_leads: bool = True
    # Recuadro de la persona a pantalla completa.
    pip_shape: Literal["circle", "rounded"] = "rounded"
    # Con interfaz social en vertical: tamaño máximo del recuadro y separación con el contenido.
    fullscreen_pip_max_with_ui: float = 0.22
    fullscreen_gap_with_ui: float = 0.04


REGISTRY: dict[str, StyleDefinition] = {}


def register(style: StyleDefinition) -> StyleDefinition:
    if style.id in REGISTRY:
        raise ValueError(f"Estilo duplicado: {style.id}")
    prefixes = {t.split(".")[0] for t in style.templates}
    if len(prefixes) != 1:
        raise ValueError(f"Las plantillas de {style.id} deben compartir prefijo: {prefixes}")
    for kind in ("transition", "highlight"):
        if not any(t.endswith(f".{kind}") for t in style.templates):
            raise ValueError(f"{style.id} necesita una plantilla «.{kind}»")
    REGISTRY[style.id] = style
    return style


def get(style_id: str) -> StyleDefinition:
    try:
        return REGISTRY[style_id]
    except KeyError:
        raise ValueError(f"Estilo desconocido: {style_id}") from None
