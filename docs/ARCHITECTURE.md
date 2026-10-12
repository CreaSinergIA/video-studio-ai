# Arquitectura

```
Lanzador (videostudio / videostudio.ps1 → app/launcher.py): instancia única, puerto, token
        │ abre /open?t=… → cookie HttpOnly
Panel (React + Vite) ──HTTP solo 127.0.0.1 (token de sesión + cabecera anti-CSRF)──► API (FastAPI)
                                                                      │
                                      Cola de tareas locales (importar, analizar, planificar,
                                      animar, modificar escenas, exportar)
        ┌──────────────┬───────────────┬───────────────────┬──────────────┬─────────────┐
     FFmpeg/ffprobe  Whisper local   Claude (API del      Remotion +     Compositor
     (sistema o      (MLX en Apple   usuario; clave en    navegador de   FFmpeg
     portátil;       Silicon;        el llavero)          render         (exportación
     vigilante)      faster-whisper  plan · dirección     (ProRes alfa;  verificada)
                     en Windows)     · escenas            árbol vigilado)
        │
  SQLite (directorio de datos de la edición) ◄──► Almacenamiento elegido por el usuario
  proyectos · planes inmutables · versiones         originales · planes JSON · clips ·
  · consumo · copias de seguridad                    exportaciones
```

## Principios
- **Originales intocables:** se copian al almacenamiento y quedan registrados con su SHA-256.
- **Plan aprobado inmutable:** cada cambio crea una versión nueva, también al regenerar una escena.
- **Claude declara, el sistema valida:** esquemas cerrados, tiempos anclados a palabras y vocabulario de cada estilo. Nunca se ejecuta código generado.
- **Caché por contenido:** la huella incluye la especificación y el código del renderizador, así que nunca se reutiliza un clip obsoleto.
- **Mismo compositor** para la vista previa y la exportación.
- **Instalación independiente:** directorio de datos, puerto (8775) y servicio del llavero propios de esta edición (`app/edition.py`). No comparte nada con otras copias de Video Studio AI del mismo equipo.

## Estilos y extensiones
- **Estilos integrados:** los tres estilos gratuitos están registrados en `backend/app/styles/` y `renderer/src/styles/registry.ts`. Una prueba exige que las plantillas coincidan.
- **Paquetes de estilos adicionales:** se cargan **solo** si se indican de forma explícita en la variable `VSA_STYLE_PACKAGES` (módulos Python importables). El editor **nunca** explora carpetas ni descubre paquetes por su cuenta.
- **Parte visual de un paquete:** debe añadirse al registro del renderizador en la compilación de la edición que lo use.
- **Separación del núcleo:** un paquete externo puede mantenerse en otro repositorio, incluso privado, sin modificar el núcleo ni obligar a publicarlo.

## Plataforma
`backend/app/platform/` reúne lo que cambia entre sistemas:
- `paths.py`: rutas de datos;
- `processes.py`: grupos de procesos, terminación del árbol, vigilante de descendientes, registro de hijos y *Job Object* de Windows;
- `transcription.py`: motores (MLX, faster-whisper) y dispositivo (CPU/CUDA);
- `credentials.py`: Llavero de macOS, Administrador de credenciales de Windows, Secret Service de Linux;
- `tools.py`: Node.js y FFmpeg portátiles (versión y SHA-256 fijados);
- `encoders.py`: codificadores por hardware;
- `detect.py`: diagnóstico.

Ver [PLATFORMS.md](PLATFORMS.md).

## Instalación y ciclo de vida
- `app/installer.py`: instalador guiado por pasos idempotentes, con estado en `install-state.json` (se reanuda tras un corte) y confirmación antes de cada descarga (`--yes` para Claude Code).
- `app/launcher.py`: `start | stop | restart | status | open | logs | doctor`, común a macOS y Windows. Los scripts `videostudio` y `videostudio.ps1` solo preparan uv/Python y delegan en él.
- `app/lifecycle.py`: bloqueo de instancia, `run/instance.json` y cierre ordenado (`POST /api/system/shutdown`).
- `app/session.py`: token de sesión de la API local.
- `services/setup_checks.py`: comprobaciones compartidas por el instalador, `doctor` y la primera configuración (`GET /api/setup/status`).
- `app/limits.py`: límites de recursos (resolución, duración, FFmpeg).
