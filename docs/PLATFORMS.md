# Compatibilidad: macOS y Windows

> **Estado:**
> - **macOS (Apple Silicon):** validado.
> - **macOS Intel:** no validado (no tendría transcripción local).
> - **Windows:** NO validado. La arquitectura está preparada y los componentes que requieren adaptación están identificados.
> - No se afirma compatibilidad con Windows hasta probarla en ese sistema.

El diagnóstico de cada equipo se muestra en **Ajustes → Acerca de** (`app/platform`).

## Matriz de componentes
| Componente | macOS (Apple Silicon) | Windows | Adaptador / estado |
|---|---|---|---|
| Backend (Python 3.12 + FastAPI + SQLite) | ✅ | Previsto (portable) | — |
| Panel (React, navegador local) | ✅ | Previsto (portable) | — |
| Rutas de datos | `~/Library/Application Support/VideoStudioAI-Community` | `%LOCALAPPDATA%\VideoStudioAI-Community` | `app/platform/paths.py` ✅ (sin validar en Windows) |
| Procesos (cancelar render o Claude) | grupo de procesos + señales POSIX ✅ | grupo de procesos + `taskkill /T` | `app/platform/processes.py` (sin validar en Windows) |
| Transcripción local | MLX Whisper ✅ | **faster-whisper** (CPU INT8; CUDA opcional) o **whisper.cpp** (CPU, CUDA o Vulkan) | `app/platform/transcription.py`: motor de Windows **pendiente** |
| Codificación por hardware | VideoToolbox ✅ | NVENC / Quick Sync / AMF detectados, **no usados** hasta validarlos; se usa software (libx264/libx265) | `app/platform/encoders.py` |
| FFmpeg / ffprobe | Homebrew u oficial | Compilación oficial de Windows (p. ej. BtbN LGPL), instalada por el usuario o por el instalador | Detección actual: `VSA_FFMPEG` / PATH |
| Análisis visual (OpenCV + YuNet) | ✅ | Previsto (ruedas oficiales de OpenCV) | — |
| Remotion + navegador de render | ✅ (Chrome for Testing mac-arm64) | Previsto (Chrome for Testing win64) | `services/render_engine.py`: falta la plataforma win64 en la descarga |
| Llavero (clave de API) | `security` de macOS ✅ | Administrador de credenciales de Windows | **Pendiente** (p. ej. `keyring`) |
| Selector de carpetas nativo | AppleScript ✅ | Diálogo de Windows | Pendiente (se puede escribir la ruta a mano) |
| Mostrar en Finder / abrir archivo | `open -R` / `open` ✅ | `explorer /select,` / `os.startfile` | Implementado, sin validar |
| Almacenamiento externo | `/Volumes/…` (exFAT con archivos AppleDouble) ✅ | Letras de unidad (`D:\…`) | `services/storage.py`: detección de volúmenes por revisar |
| Lanzador | `./videostudio` (bash) ✅ | `videostudio.ps1` o `.cmd` | **Pendiente** |
| Puerto local | 8775, solo 127.0.0.1 ✅ | Igual; posible aviso del firewall | — |
| Pruebas E2E | WebKit + Chromium ✅ | Chromium | Los fixtures usan `say` (voces de macOS): alternativa pendiente |

## Recomendaciones para Windows (Fase 2)
1. **Transcripción:**
   - faster-whisper en CPU (INT8) por defecto, que funciona sin GPU.
   - CUDA opcional solo si hay una GPU NVIDIA, con las bibliotecas descargadas aparte.
   - Evaluar whisper.cpp con Vulkan para GPU de cualquier fabricante.
   - **No exigir GPU NVIDIA.**
2. **FFmpeg:** documentar la instalación de una compilación oficial LGPL o GPL. No incluirla sin revisar sus obligaciones de licencia.
3. **Navegador de render:** añadir la plataforma `win64` a la descarga verificada.
4. **Llavero:** Administrador de credenciales de Windows.
5. **Procesos y rutas:** validar `taskkill /T`, rutas largas, permisos y antivirus.
6. **Lanzador y empaquetado:** PowerShell; evaluar un instalador.
7. **Pruebas:** ejecutar el backend, el panel y la E2E con Chromium en Windows 11 (CPU sola y con NVIDIA).
