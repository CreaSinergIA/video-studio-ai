# Video Studio AI — Community Edition

Editor de video local con IA, gratuito:
- importa un video vertical u horizontal;
- lo transcribe **en tu equipo**;
- Claude propone un plan de edición que tú revisas y apruebas;
- genera *motion graphics* por código, subtítulos y efectos de sonido;
- exporta el resultado **sin marcas de agua**.

Incluye tres estilos: **Motion Tech**, **Minimal Motion** y **Creative Explainer**.

*Created by Gabo.*

> **Estado: versión preliminar, aún no publicada.**
> - **macOS (Apple Silicon):** validado (instalación nueva, flujo completo y pruebas automáticas).
> - **Windows 10/11 x64:** implementado y probado con simulaciones; **pendiente de validar en un PC Windows real** ([docs/WINDOWS-VALIDATION.md](docs/WINDOWS-VALIDATION.md)).
> - **Licencia del código:** se decidirá al publicar ([docs/LICENSING.md](docs/LICENSING.md)).

## Instalar

### Con Claude Code (recomendado)
Abre esta carpeta con Claude Code y pídele: *«Instala Video Studio AI»*. Seguirá [CLAUDE.md](CLAUDE.md): te explicará qué va a descargar, te pedirá confirmación y abrirá el panel al terminar.

### A mano
| | macOS | Windows |
|---|---|---|
| Instalar | doble clic en **Instalar Video Studio AI.command** (o `./videostudio install`) | doble clic en **Instalar Video Studio AI.cmd** |
| Abrir | app **Video Studio AI** de `~/Applications`, **Video Studio AI.command** o `./videostudio start` | acceso directo **Video Studio AI** del Escritorio o del menú Inicio, o **Video Studio AI.cmd** |
| Cerrar | `./videostudio stop` o Ajustes → Acerca de → Cerrar | **Cerrar Video Studio AI** (menú Inicio) o Ajustes → Acerca de → Cerrar |

El instalador comprueba el equipo y **solo descarga lo que falte**, siempre con versión y huella SHA-256 fijadas y tras pedir confirmación: uv y Python 3.12, Node.js LTS, FFmpeg, las dependencias del panel y de Remotion, el navegador de render y un modelo de transcripción. **No instala nada de forma global, no pide permisos de administrador y no cambia el PATH del sistema.** Si se interrumpe, vuelve a ejecutarlo: continúa donde se quedó.

Guías detalladas: [macOS](docs/INSTALL-macOS.md) · [Windows](docs/INSTALL-Windows.md) · [requisitos](docs/REQUIREMENTS.md).

## Primera ejecución
Un asistente te guía por:
1. la carpeta donde guardar tus proyectos;
2. las comprobaciones del equipo (FFmpeg, Remotion, transcripción), con botones para descargar lo que falte;
3. tu conexión con Claude (opcional).

Todo se puede completar o cambiar después desde **Ajustes**. Ver [docs/FIRST-RUN.md](docs/FIRST-RUN.md).

## Claude: tu propia clave de API
- Video Studio AI es gratuito, pero **Claude no**: el uso se factura en **tu** cuenta de Anthropic (Consola de Claude, https://platform.claude.com), por tokens.
- **Una suscripción Claude Pro o Max no incluye el uso de la API.**
- La clave se guarda en el llavero del sistema (macOS: Llavero; Windows: Administrador de credenciales). Puedes comprobarla **sin coste**, cambiarla o eliminarla desde el panel.
- Antes de cada operación ves cuántas solicitudes necesita; hay un límite diario configurable y un tope por operación.
- Sin clave puedes importar, transcribir, subtitular y exportar.

Detalles, precios y límites: [docs/CLAUDE.md](docs/CLAUDE.md).

## Tus datos
- Todo se procesa y se guarda en tu equipo. Nada se envía a servidores de Video Studio AI (no existen).
- A Claude solo llegan la transcripción, datos de escenas y unos pocos fotogramas reducidos, y solo cuando tú lo pides. **Nunca** el archivo de video.
- El panel solo escucha en `127.0.0.1` y exige un token de sesión: otros programas o cuentas del equipo no pueden usarlo.
- Los datos viven en la carpeta que elijas para los proyectos y en la carpeta de la aplicación:
  - macOS: `~/Library/Application Support/VideoStudioAI-Community`
  - Windows: `%LOCALAPPDATA%\VideoStudioAI-Community`

## Licencias de terceros
- **Remotion** (motor de animaciones) se instala como dependencia independiente y conserva su licencia: gratuita para personas, organizaciones sin ánimo de lucro y empresas de hasta 3 personas; las organizaciones mayores necesitan su propia licencia (https://www.remotion.pro/license).
- **FFmpeg**, los modelos Whisper y el navegador de render se descargan de sus fuentes; no se redistribuyen en este repositorio.
- Detalle: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Problemas
[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) · diagnóstico: `./videostudio doctor` (macOS) o `videostudio.ps1 doctor` (Windows).

## Desarrollo
```bash
./videostudio check                    # lint, tipos, pruebas del backend, compilación
cd frontend && npm run e2e             # pruebas E2E con medios sintéticos (Claude simulado)
backend/.venv/bin/python scripts/smoke_e2e.py   # flujo completo en un entorno aislado
git config core.hooksPath .githooks    # comprobación de privacidad antes de cada commit
```
Arquitectura: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Plataformas: [docs/PLATFORMS.md](docs/PLATFORMS.md) · Seguridad: [docs/SECURITY.md](docs/SECURITY.md) · Privacidad de la distribución: [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md).
