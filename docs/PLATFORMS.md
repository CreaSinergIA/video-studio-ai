# Compatibilidad: macOS y Windows

> **Estado (CE Fase 2):**
> - **macOS con Apple Silicon:** validado — instalación nueva, pruebas automáticas, E2E y flujo completo de punta a punta.
> - **Windows 10/11 x64:** **implementado; pendiente de validar en un PC real.** No se declara compatible hasta completar [WINDOWS-VALIDATION.md](WINDOWS-VALIDATION.md).
> - **Mac Intel y Windows en ARM:** no compatibles (ver [REQUIREMENTS.md](REQUIREMENTS.md)).
> - **Linux:** sin validar.

El diagnóstico de cada equipo aparece en **Ajustes → Acerca de**, en la primera configuración y con `doctor`.

## Matriz de componentes
| Componente | macOS (Apple Silicon) | Windows x64 | Dónde |
|---|---|---|---|
| Lanzador | `videostudio` (bash), `.command`, app en `~/Applications` ✅ | `videostudio.ps1` (PowerShell 5.1+), `.cmd`, accesos en Escritorio y menú Inicio 🟡 | `app/launcher.py` (común), `app/shortcuts.py` |
| Instalador guiado y reanudable | ✅ | 🟡 | `app/installer.py` (común) |
| Python 3.12 | uv 0.12.18 (portátil si falta) ✅ | uv 0.12.18 (portátil) 🟡 | lanzadores |
| Node.js | el del sistema ≥ 20.19 o 24 LTS portátil ✅ | ídem (zip win-x64) 🟡 | `app/platform/tools.py` |
| FFmpeg / ffprobe | el del sistema o 9.0.2 portátil (Martin Riedl, firmado) ✅ | el del sistema o 9.0.2 «essentials» (Gyan) 🟡 | `app/platform/tools.py`, `config.py` |
| Transcripción | **MLX Whisper** (Metal) ✅ · faster-whisper disponible ✅ | **faster-whisper** CPU INT8; CUDA opcional con vuelta a CPU 🟡 (motor validado en macOS) | `app/platform/transcription.py`, `workers/transcribe_worker.py` |
| Clave de API | Llavero (`security`) ✅ | Administrador de credenciales (`keyring` → WinVault) 🟡 | `app/platform/credentials.py` |
| Remotion + navegador de render | Chrome Headless Shell mac-arm64 ✅ | win64 (SHA-256 fijado), entorno con `SYSTEMROOT`, `TEMP`… 🟡 | `services/render_engine.py` |
| Procesos | grupos POSIX + vigilante del árbol + registro de hijos ✅ | grupos + `taskkill /T` + vigilante del árbol + *Job Object* 🟡 | `app/platform/processes.py` |
| Instancia única, puertos, cierre | ✅ | 🟡 (misma lógica, bloqueo con `msvcrt`) | `app/lifecycle.py`, `app/launcher.py` |
| Rutas de datos | `~/Library/Application Support/VideoStudioAI-Community` ✅ | `%LOCALAPPDATA%\VideoStudioAI-Community` 🟡 | `app/platform/paths.py` |
| Almacenamiento externo | `/Volumes/…` (incluido exFAT) ✅ | letras de unidad (`D:\…`) 🟡 | `services/storage.py` |
| Originales de solo lectura | ✅ | atributo de solo lectura quitado al borrar 🟡 | `services/storage.py` |
| Texto y codificación | UTF-8 ✅ | UTF-8 explícito en archivos y procesos 🟡 | todo el backend |
| Selector de carpetas y archivos | AppleScript (argumentos, sin interpolar) ✅ | Windows Forms (PowerShell) 🟡 | `services/native.py` |
| Mostrar en Finder / Explorador | ✅ | `explorer /select,` 🟡 | `services/native.py` |
| Codificación por hardware | VideoToolbox ✅ | NVENC / Quick Sync / AMF detectados, **no usados**: software (libx264/libx265) | `app/platform/encoders.py` |
| Puerto local | 8775 (o el siguiente libre), solo 127.0.0.1 ✅ | igual 🟡 | — |
| Pruebas E2E | WebKit + Chromium ✅ | Chromium; voz sintética SAPI en `scripts/smoke_e2e.py` 🟡 | `frontend/e2e`, `scripts/` |

✅ validado · 🟡 implementado, pendiente de validar en Windows real

## Decisiones
1. **faster-whisper** en lugar de whisper.cpp para Windows: se instala con las mismas dependencias de Python (sin compilar ni descargar binarios por plataforma), funciona en la CPU con INT8, usa CUDA si existe y ofrece la misma alineación por palabra (DTW sobre la atención cruzada) que MLX. whisper.cpp con Vulkan queda como alternativa futura para GPU AMD/Intel.
2. **Sin WSL ni Docker:** no aportan nada aquí (todo es Python, Node y FFmpeg nativos) y complicarían la instalación.
3. **Herramientas portátiles** en la carpeta de datos en lugar de instaladores globales: no requieren administrador y se eliminan con la carpeta.
4. **Exportación por software en Windows** hasta validar NVENC/Quick Sync/AMF: es más lenta pero funciona en cualquier equipo.
5. **Mac en Apple Silicon sigue con MLX:** es varias veces más rápido que faster-whisper en ese hardware.
