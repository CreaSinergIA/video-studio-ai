"""Estilos de edición registrados (ver ``base.py``).

La Community Edition incluye solo los tres estilos gratuitos. Paquetes de estilos adicionales
(p. ej. bibliotecas privadas) se cargan ÚNICAMENTE si se indican de forma explícita en la
variable ``VSA_STYLE_PACKAGES`` (módulos Python importables, separados por comas); nunca se
exploran carpetas ni se descubren paquetes automáticamente. Cada paquete registra sus estilos
con ``register()`` al importarse, y su parte visual debe añadirse al registro del
renderizador (``renderer/src/styles/registry.ts``) en la compilación de esa edición.
"""

import importlib
import logging
import os

from app.styles import creative_explainer, minimal_motion, motion_tech  # noqa: F401  (registro)
from app.styles.base import REGISTRY, StyleDefinition, get, register

BUILTIN = ("motion_tech", "minimal_motion", "creative_explainer")
log = logging.getLogger(__name__)


def load_extra_packages(raw: str | None = None) -> list[str]:
    """Importa los paquetes de estilos indicados explícitamente. Devuelve los cargados."""
    loaded = []
    for name in [
        p.strip()
        for p in (raw if raw is not None else os.environ.get("VSA_STYLE_PACKAGES", "")).split(",")
        if p.strip()
    ]:
        try:
            importlib.import_module(name)
            loaded.append(name)
        except Exception:  # un paquete externo nunca impide arrancar el editor
            log.exception("No se pudo cargar el paquete de estilos %s", name)
    return loaded


load_extra_packages()

__all__ = ["BUILTIN", "REGISTRY", "StyleDefinition", "get", "load_extra_packages", "register"]
