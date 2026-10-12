"""Adaptadores de plataforma (macOS / Windows / Linux).

Puntos de variación entre sistemas reunidos en un solo sitio: rutas de datos, procesos,
codificación por hardware, motores de transcripción y diagnóstico del entorno. Los motores de
Windows aún no están implementados: se detectan y se informan como pendientes.
"""

from app.platform.detect import PlatformInfo, detect

__all__ = ["PlatformInfo", "detect"]
