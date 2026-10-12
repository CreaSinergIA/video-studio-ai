# Requisitos mínimos

| | macOS | Windows |
|---|---|---|
| Sistema | macOS 14 (Sonoma) o posterior, **Apple Silicon** (M1 o superior) | Windows 10 (1809+) u 11, **x64** |
| Validado en | Mac con Apple M4 y la versión actual de macOS | **pendiente** de validar en un PC real |
| Memoria | 8 GB (16 GB recomendados para 4K) | 8 GB (16 GB recomendados para 4K) |
| Disco del sistema | ~6 GB libres para la aplicación, dependencias y un modelo | ~6 GB libres |
| Proyectos | el espacio que necesiten tus videos, en la carpeta que elijas (puede ser un disco externo) | igual (otra unidad, p. ej. `D:\`, también sirve) |
| GPU | no hace falta (la transcripción usa Metal en Apple Silicon) | **no hace falta**; con NVIDIA y el complemento CUDA (opcional) la transcripción es más rápida |
| Conexión | para instalar y para usar Claude; el resto funciona sin conexión | igual |
| Navegador | Safari, Chrome, Edge, Firefox u Opera actuales | Edge, Chrome, Firefox u Opera actuales |

**No compatibles por ahora:**
- **Mac con procesador Intel:** una dependencia del motor de transcripción (onnxruntime) ya no publica versiones para Mac Intel.
- **Windows en ARM:** el motor de render de Remotion solo existe para Windows x64.
- **Linux:** puede funcionar, pero no está validado ni documentado.

## Qué se instala (solo si falta) y dónde
Todo en la carpeta de datos de la aplicación (`~/Library/Application Support/VideoStudioAI-Community` en macOS, `%LOCALAPPDATA%\VideoStudioAI-Community` en Windows) o dentro del propio repositorio. Nada global, sin permisos de administrador.

| Componente | Versión | Tamaño aprox. | Origen |
|---|---|---|---|
| uv (gestor de Python) | 0.12.18 | 17–20 MB | GitHub de Astral (SHA-256 fijado) |
| Python | 3.12 | ~40 MB | descargado por uv |
| Dependencias de Python | fijadas en `backend/uv.lock` | ~0,9 GB | PyPI |
| Node.js | 24.21.0 LTS (si no tienes Node ≥ 20.19) | 38–53 MB | nodejs.org (SHA-256 fijado) |
| Dependencias del panel y de Remotion | fijadas en `package-lock.json` | ~0,5 GB | npm |
| FFmpeg | 9.0.2 (si no tienes uno adecuado) | 57 MB (macOS) / 115 MB (Windows) | compilaciones enlazadas desde ffmpeg.org (SHA-256 fijado) |
| Navegador de render | Chrome Headless Shell 157 | 104–126 MB | Google «Chrome for Testing» (SHA-256 fijado) |
| Modelo de transcripción | Whisper large-v3-turbo (o uno ligero) | 0,5–1,6 GB | Hugging Face, revisión fijada y SHA-256 por archivo |
| Complemento CUDA (opcional, Windows con NVIDIA) | CUDA 12 + cuDNN 9 | ~1,5 GB | PyPI (NVIDIA) |

## Rendimiento orientativo
Medido en un Mac con Apple M4 (16 GB), con videos sintéticos de 9 segundos:
- transcripción con MLX (large-v3-turbo): varias veces más rápida que el tiempo real;
- flujo completo por estilo (importar, transcribir, plan, 3 animaciones, vista previa y exportación): 25–35 s.

En Windows con CPU, la transcripción con faster-whisper depende mucho del procesador; el modelo ligero «small» es 3–4 veces más rápido que large-v3-turbo. Las cifras de Windows se publicarán tras validarlo.
