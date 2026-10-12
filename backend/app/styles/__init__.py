"""Estilos de edición registrados (ver ``base.py``)."""

from app.styles import creative_explainer, minimal_motion, motion_tech  # noqa: F401  (registro)
from app.styles.base import REGISTRY, StyleDefinition, get, register

__all__ = ["REGISTRY", "StyleDefinition", "get", "register"]
