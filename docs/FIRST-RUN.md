# Primera configuración

La primera vez que abres Video Studio AI aparece un asistente de cuatro pasos. Todo es opcional y se puede completar o cambiar después desde **Ajustes**. Para repetirlo: *Ajustes → Acerca de → Repetir la primera configuración*.

## 1. Proyectos
Elige la carpeta donde se guardarán tus proyectos (copias de los videos, transcripciones, planes, animaciones y exportaciones). Recomendaciones:
- una carpeta **dedicada** (por ejemplo `VideoStudio`), no una con otros archivos;
- puede estar en un disco externo (`/Volumes/MiDisco/VideoStudio` en macOS, `D:\VideoStudio` en Windows);
- los originales se copian y nunca se modifican.

Puedes escribir la ruta, usar el explorador integrado o el selector del sistema (Finder / Explorador). Si eliges una carpeta que ya contiene proyectos de Video Studio AI (por ejemplo, tras reinstalar), se recuperan.

## 2. Equipo
Comprueba, sin modificar nada:
- **Sistema, memoria y disco.**
- **FFmpeg** (y sus codificadores).
- **Node.js y Remotion**, y si falta el **navegador de render**: botón para descargarlo (~104–126 MB, verificado).
- **Transcripción local:** motor disponible (MLX en Mac con Apple Silicon, faster-whisper en Windows) y si falta el **modelo**: botón para descargar el recomendado. Otros modelos en *Ajustes → Transcripción*.

Si FFmpeg falta, vuelve a ejecutar el instalador: descarga una copia portátil verificada.

## 3. Claude (opcional)
- Pega **tu** clave de API de Anthropic (créala en https://platform.claude.com/settings/keys).
- Se guarda en el llavero del sistema y se comprueba **sin coste** con la API de modelos de Anthropic (no se envía ninguna solicitud al modelo).
- Verás el precio de lista de Claude Opus 5.5 y el aviso de que una suscripción Claude Pro/Max **no** cubre la API.
- Sin clave puedes importar, transcribir, subtitular y exportar; el plan de edición y la dirección de animaciones necesitan Claude.

## 4. Listo
Resumen de lo que queda pendiente (si algo falta) y botón **Ir al editor**.

## Dónde quedan tus datos
- Carpeta de proyectos: la que elijas.
- Carpeta de la aplicación (base de datos, modelos, motor, registros, herramientas portátiles):
  - macOS: `~/Library/Application Support/VideoStudioAI-Community`
  - Windows: `%LOCALAPPDATA%\VideoStudioAI-Community`

No se precarga ningún proyecto, plan, video ni dato de otra instalación.
