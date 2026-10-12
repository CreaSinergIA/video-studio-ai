# Avisos de terceros

Video Studio AI — Community Edition se apoya en componentes de terceros que **conservan sus propias licencias**. La licencia **MIT** del código original de este proyecto ([LICENSE](LICENSE)) **no** se aplica a ninguno de ellos ni los sustituye.

El inventario completo de dependencias, directas y transitivas, está en `docs/licenses/DEPENDENCIES.md`.

## Componentes que requieren atención especial

### Remotion (motor de animaciones) — licencia propia, no es open source
- **Paquetes:** `remotion`, `@remotion/renderer`, `@remotion/bundler`, `@remotion/cli` y relacionados (4.0.x). Se instalan con `npm` desde el registro oficial; **no** se incluyen en este repositorio.
- **Licencia:** Remotion License (*source-available*, no aprobada por OSI). https://github.com/remotion-dev/remotion/blob/main/LICENSE.md
- **Uso gratuito:** personas, organizaciones sin ánimo de lucro, empresas con hasta 3 personas y evaluación.
- **Organizaciones de 4 o más personas:** necesitan **su propia licencia de empresa de Remotion** para usar este editor. https://www.remotion.pro/license
- Usar Video Studio AI no concede ningún derecho sobre Remotion.

### Navegador de render (Chrome for Testing / chrome-headless-shell)
Lo usa Remotion para dibujar las animaciones. **No se incluye**: se descarga desde la fuente oficial de Google (versión 157, para macOS y Windows x64) cuando el usuario lo pide, con verificación de tamaño, MD5 y SHA-256 (y firma de código en macOS). Sujeto a los términos de Google.

### FFmpeg
- **No se incluye en este repositorio.** Video Studio AI ejecuta el `ffmpeg` y el `ffprobe` del equipo.
- Si no hay uno adecuado, el instalador **descarga en el equipo del usuario**, con su confirmación, una compilación portátil de su proveedor (enlazado desde https://ffmpeg.org/download.html), con versión y SHA-256 fijados:
  - macOS: compilaciones estáticas de Martin Riedl (https://ffmpeg.martin-riedl.de), firmadas con su Developer ID;
  - Windows x64: compilación «essentials» de Gyan Doshi (https://www.gyan.dev/ffmpeg/builds/, publicada en https://github.com/GyanD/codexffmpeg).
- Ambas son compilaciones **GPL** (incluyen libx264/libx265); el código fuente está disponible en ffmpeg.org y en los sitios de esos proveedores. Los posibles requisitos de patentes de los códecs (H.264, HEVC y AAC) dependen del uso. https://ffmpeg.org/legal.html
- `opencv-python-headless` y `av` (PyAV, que instala faster-whisper) incluyen sus propias bibliotecas de FFmpeg desde PyPI.

### Node.js y uv (herramientas descargadas por el instalador)
- **Node.js** 24 LTS (MIT y licencias de sus componentes, https://github.com/nodejs/node/blob/main/LICENSE): solo si el equipo no tiene una versión adecuada; desde nodejs.org, SHA-256 fijado.
- **uv** (MIT o Apache-2.0, Astral): solo si el equipo no lo tiene; desde su publicación en GitHub, SHA-256 fijado. uv descarga Python 3.12 (licencia PSF) de las compilaciones *python-build-standalone*.
- Se guardan en la carpeta de datos de la aplicación; no se redistribuyen en este repositorio.

### Modelos de transcripción (Whisper)
- Código y pesos de OpenAI Whisper: **MIT**. https://github.com/openai/whisper
- Se **descargan** desde Hugging Face en una revisión fijada, con SHA-256 por archivo; no se redistribuyen aquí:
  - Apple Silicon (MLX): `mlx-community/whisper-large-v3-turbo` y `-q4`. Sus fichas **no declaran licencia**; son conversiones de pesos MIT.
  - Windows/Linux (faster-whisper): `mobiuslabsgmbh/faster-whisper-large-v3-turbo` (MIT) y `Systran/faster-whisper-small` (MIT).

### Motor de transcripción para Windows/Linux
- **faster-whisper** (MIT, SYSTRAN) y **CTranslate2** (MIT, OpenNMT), instalados desde PyPI. Las ruedas de CTranslate2 para x86-64 incluyen bibliotecas de Intel (oneDNN, Apache-2.0; MKL según sus términos).
- **onnxruntime** (MIT, Microsoft) y **av** (PyAV, BSD-3-Clause, con bibliotecas de FFmpeg), dependencias de faster-whisper.
- **Complemento opcional CUDA** (solo con `--cuda`, Windows/Linux con GPU NVIDIA): `nvidia-cublas-cu12` y `nvidia-cudnn-cu12`, sujetos a la licencia de NVIDIA, descargados de PyPI por el propio usuario.

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
| MIT | React, Vite, Tailwind CSS, Radix UI, TanStack Query, sonner, rough.js, FastAPI, SQLAlchemy, Alembic, Pydantic, Pillow (MIT-CMU), anthropic, mlx, mlx-whisper, tiktoken, faster-whisper, ctranslate2, onnxruntime, keyring |
| ISC | Lucide (con partes MIT derivadas de Feather) |
| BSD | uvicorn, numpy (y licencias compatibles), psutil, av (PyAV), protobuf, varios paquetes de npm |
| Apache-2.0 | opencv-python-headless, huggingface-hub, tokenizers, flatbuffers, regex (con CNRI-Python) |
| MPL-2.0 (copyleft por archivo) | mediabunny (lo usa Remotion), lightningcss (compilación), certifi, tqdm, pathspec. Se usan sin modificar y se instalan con su gestor de paquetes |
| CC-BY-4.0 | caniuse-lite (datos de compatibilidad de navegadores, herramientas de compilación), © Alexis Deveria |
| PSF-2.0 | typing_extensions |
| Unlicense | memfs, fs-monkey |

Este documento es informativo y no es asesoramiento legal.
