# Video Studio AI — Community Edition

Editor de video local con IA:
- importa un video vertical u horizontal;
- lo transcribe en tu equipo;
- deja que Claude proponga un plan de edición que tú apruebas;
- genera *motion graphics* por código, subtítulos y efectos de sonido;
- exporta el resultado **sin marcas de agua**.

*Created by Gabo.*

> **Estado: versión preliminar, aún no publicada.**
> - **Validado:** macOS con Apple Silicon.
> - **Windows:** en preparación (ver [docs/PLATFORMS.md](docs/PLATFORMS.md)); todavía no está validado.
> - **Licencia del código:** pendiente ([docs/LICENSING.md](docs/LICENSING.md)).

## Qué incluye
- **Edición:** panel completo con biblioteca, editor, línea de tiempo, subtítulos personalizables y zonas seguras de Instagram Reels y TikTok.
- **Transcripción local** con Whisper: MLX en Apple Silicon. El motor para Windows/Linux está pendiente.
- **Plan de edición con Claude Opus 5.5**, que revisas y apruebas, con regeneración de escenas individuales y versiones.
- **Animaciones** programáticas con Remotion, en **tres estilos gratuitos:** Motion Tech, Minimal Motion y Creative Explainer.
- **Efectos de sonido** sintetizados localmente y exportación MP4/MOV.
- **Proyectos:** gestión de proyectos, copias de seguridad verificadas y recuperación.

## Antes de instalar: costes y licencias de terceros
- **Claude:** necesitas **tu propia clave de API de Anthropic**. El editor es gratuito, pero el uso de Claude se factura en tu cuenta de Anthropic según su tarifa y sus límites ([docs/CLAUDE.md](docs/CLAUDE.md)).
- **Remotion:** tiene licencia propia (no es open source). Es gratuito para personas, organizaciones sin ánimo de lucro y empresas de hasta 3 personas. **Las organizaciones de 4 o más personas necesitan su propia licencia de Remotion**: https://www.remotion.pro/license
- **FFmpeg:** lo instalas tú (no se incluye).
- **Descargas en la primera ejecución:** los modelos de transcripción y el navegador de render se descargan de sus fuentes oficiales, con verificación.
- **Detalle de terceros:** [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Requisitos (macOS)
- Mac con Apple Silicon. Validado en un Mac con M4 y la versión actual de macOS; las versiones mínimas aún no se han establecido. Mac Intel: no validado (no tendría transcripción local).
- Python 3.12 con [uv](https://docs.astral.sh/uv/), Node.js (validado con la 24) y FFmpeg (`brew install ffmpeg`).

## Uso rápido (macOS)
```bash
./videostudio setup   # dependencias locales del proyecto (sin instalaciones globales)
./videostudio start   # abre el panel en http://127.0.0.1:8775
```
En la primera ejecución:
1. Elige la carpeta de almacenamiento de tus proyectos.
2. Descarga el modelo de transcripción (Ajustes → Transcripción).
3. Instala el motor de animaciones (Ajustes → Animaciones).
4. Guarda tu clave de API (Ajustes → Claude).

Tus datos son solo tuyos y viven en dos sitios:
- `~/Library/Application Support/VideoStudioAI-Community`;
- la carpeta de almacenamiento que elijas.

## Desarrollo
```bash
./videostudio check   # lint, tipos, pruebas, build
cd frontend && npm run e2e
git config core.hooksPath .githooks   # comprobación de privacidad antes de cada commit
```
- **Arquitectura:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
- **Seguridad:** [docs/SECURITY.md](docs/SECURITY.md).
- **Privacidad de la distribución:** [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md).
