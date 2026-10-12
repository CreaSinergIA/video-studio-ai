"""Identidad de la edición (Community Edition).

Todo lo que distingue esta edición de cualquier otra instalación vive aquí, para que nunca
comparta datos, puerto ni credenciales con otra copia de Video Studio AI en el mismo equipo.
"""

from __future__ import annotations

EDITION = "community"
PRODUCT_NAME = "Video Studio AI"
EDITION_NAME = "Community Edition"
CREATOR = "Created by Gabo"

# Directorio de datos propio (ver ``app.platform.paths``) y puerto local por defecto.
DATA_DIR_NAME = "VideoStudioAI-Community"
DEFAULT_PORT = 8775

# Servicio del llavero del sistema donde se guarda la clave de API del usuario.
KEYCHAIN_SERVICE = "VideoStudioAI-Community"

# Conexión con Claude: cada usuario usa SU PROPIA clave de API de Anthropic (mecanismo
# autorizado para aplicaciones de terceros). El inicio de sesión de Claude.ai (Pro/Max) a
# través de Claude Code no se ofrece en esta edición (ver docs/CLAUDE.md). El transporte por
# CLI solo existe para las pruebas automáticas con un CLI simulado (entorno de pruebas).
ALLOW_CLAUDE_CODE_TRANSPORT = False
