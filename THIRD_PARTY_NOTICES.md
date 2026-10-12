# Avisos de terceros

Video Studio AI — Community Edition se apoya en componentes de terceros que **conservan sus propias licencias**. La licencia del código original de este proyecto (ver `docs/LICENSING.md`) **no** se aplica a ninguno de ellos.

El inventario completo de dependencias, directas y transitivas, está en `docs/licenses/DEPENDENCIES.md`.

## Componentes que requieren atención especial

### Remotion (motor de animaciones) — licencia propia, no es open source
- **Paquetes:** `remotion`, `@remotion/renderer`, `@remotion/bundler`, `@remotion/cli` y relacionados (4.0.x). Se instalan con `npm` desde el registro oficial; **no** se incluyen en este repositorio.
- **Licencia:** Remotion License (*source-available*, no aprobada por OSI). https://github.com/remotion-dev/remotion/blob/main/LICENSE.md
- **Uso gratuito:** personas, organizaciones sin ánimo de lucro, empresas con hasta 3 personas y evaluación.
- **Organizaciones de 4 o más personas:** necesitan **su propia licencia de empresa de Remotion** para usar este editor. https://www.remotion.pro/license
- Usar Video Studio AI no concede ningún derecho sobre Remotion.

### Navegador de render (Chrome for Testing / chrome-headless-shell)
Lo usa Remotion para dibujar las animaciones. **No se incluye**: se descarga desde la fuente oficial de Google en la primera instalación, con verificación. Sujeto a los términos de Google.

### FFmpeg
- **No se incluye.** Video Studio AI ejecuta el `ffmpeg` y el `ffprobe` que tú instales.
- Su licencia (LGPL o GPL, según la compilación) y los posibles requisitos de patentes de los códecs (H.264, HEVC y AAC) dependen de la compilación que uses. https://ffmpeg.org/legal.html
- `opencv-python-headless` incluye su propia compilación LGPL de FFmpeg.

### Modelos de transcripción (Whisper)
- Código y pesos de OpenAI Whisper: **MIT**. https://github.com/openai/whisper
- Las conversiones para Apple Silicon (`mlx-community/whisper-large-v3-turbo` y `-q4`) se **descargan** desde Hugging Face en una revisión fijada. Sus fichas **no declaran licencia**; son conversiones de pesos MIT, pero no se redistribuyen aquí.

### Claude (Anthropic)
- Servicio externo.
- **Cuenta:** cada usuario usa **su propia clave de API de Anthropic**, sujeta a las condiciones y tarifas de Anthropic.
- **SDK:** el SDK `anthropic` es MIT.
- **Afiliación:** Video Studio AI no está afiliado a Anthropic.

## Componentes incluidos en este repositorio

### Modelo de detección de rostros YuNet
- **Archivo:** `backend/app/resources/models/face_detection_yunet_2023mar.onnx`
- **Origen:** opencv_zoo.
- **Licencia:** MIT, Copyright (c) 2020 Shiqi Yu. Texto completo en `backend/app/resources/models/LICENSE-face_detection_yunet.txt`.

### Fuentes (SIL Open Font License 1.1)
- **Familias:** Inter, Montserrat, Poppins, Bebas Neue, Anton, DM Serif Display, JetBrains Mono y Caveat.
- **Ubicación:** `backend/app/resources/fonts/`, con su licencia en `backend/app/resources/fonts/licenses/`. En el panel llegan además mediante los paquetes `@fontsource/*`, también OFL 1.1.
- **Condiciones de la OFL:** las fuentes pueden redistribuirse con el software siempre que se mantengan su aviso de copyright y su licencia, y no pueden venderse por separado.

### Efectos de sonido
Se **sintetizan por código** en el propio proyecto. No hay grabaciones de terceros.

## Bibliotecas de código abierto (resumen)
| Licencia | Ejemplos |
|---|---|
| MIT | React, Vite, Tailwind CSS, Radix UI, TanStack Query, sonner, rough.js, FastAPI, SQLAlchemy, Alembic, Pydantic, Pillow (MIT-CMU), anthropic, mlx, mlx-whisper, tiktoken |
| ISC | Lucide (con partes MIT derivadas de Feather) |
| BSD | uvicorn, numpy (y licencias compatibles), varios paquetes de npm |
| Apache-2.0 | opencv-python-headless, huggingface-hub, regex (con CNRI-Python) |
| MPL-2.0 (copyleft por archivo) | mediabunny (lo usa Remotion), lightningcss (compilación), certifi, tqdm, pathspec. Se usan sin modificar y se instalan con su gestor de paquetes |
| CC-BY-4.0 | caniuse-lite (datos de compatibilidad de navegadores, herramientas de compilación), © Alexis Deveria |
| PSF-2.0 | typing_extensions |
| Unlicense | memfs, fs-monkey |

Este documento es informativo y no es asesoramiento legal.
