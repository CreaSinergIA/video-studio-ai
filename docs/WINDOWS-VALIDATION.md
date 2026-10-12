# Validación en Windows

> **Estado:** pendiente. Todas las adaptaciones están implementadas y probadas en macOS con simulaciones, pero **ninguna se ha ejecutado todavía en un PC con Windows real**. No se declara compatibilidad con Windows hasta completar esta validación.

## Qué está implementado para Windows
| Área | Implementación | Cómo se probó sin Windows |
|---|---|---|
| Lanzador | `videostudio.ps1` (PowerShell 5.1+), `Video Studio AI.cmd`, `Instalar Video Studio AI.cmd`, `Cerrar Video Studio AI.cmd` | Sintaxis validada con el analizador de PowerShell 7.6; lógica compartida con macOS en `app/launcher.py` (probada) |
| Instalador | `app/installer.py` común; uv, Node.js y FFmpeg portátiles para `windows-x86_64` con SHA-256 fijado | Catálogo y verificación probados; descargas de Windows no ejecutadas |
| Transcripción | faster-whisper (CTranslate2) en CPU INT8; CUDA opcional con vuelta automática a CPU | **Ejecutado de verdad en macOS (CPU)**: transcripción, realineación y flujo completo |
| Credenciales | Administrador de credenciales de Windows vía `keyring` (WinVault) | Adaptador probado con un llavero en memoria |
| Procesos | grupos de procesos, `taskkill /T`, *Job Object* con `KILL_ON_JOB_CLOSE` | `taskkill` y Job Object sin ejecutar (solo Windows) |
| Rutas y unidades | `%LOCALAPPDATA%`, letras de unidad, archivos de solo lectura al borrar, UTF-8 en todos los textos | Lógica probada; comportamiento de NTFS sin ejecutar |
| Navegador de render | Chrome Headless Shell win64 (SHA-256 y MD5 fijados) y entorno mínimo con las variables que necesita Windows | Huellas calculadas; render en Windows sin ejecutar |
| Diálogos nativos | Selector de carpetas y de archivos con Windows Forms; «Mostrar en el Explorador» | Scripts validados sintácticamente |
| Accesos directos | Escritorio y menú Inicio (`WScript.Shell`) | Sin ejecutar |
| Pruebas E2E | Chromium; voz sintética con SAPI en `scripts/smoke_e2e.py` | Sin ejecutar |

## Riesgos conocidos a vigilar
1. **Rutas largas** en `node_modules` si el repositorio está muy anidado (el lanzador avisa).
2. **Antivirus** que bloqueen o ralenticen `chrome-headless-shell.exe`, `ffmpeg.exe` o los modelos.
3. **Compositor de Remotion** (`@remotion/compositor-win32-x64-msvc`): puede necesitar el *Visual C++ Redistributable*.
4. **Diálogo de carpetas** abierto desde un proceso sin ventana: puede aparecer detrás del navegador.
5. **Cierre ordenado:** el servidor arranca con `DETACHED_PROCESS`; el lanzador lo cierra por la API y, si no responde, termina su árbol con `psutil`.
6. **Pruebas automáticas que asumen POSIX** (enlaces simbólicos, permisos): algunas pueden fallar u omitirse en Windows; cada fallo debe revisarse.

## Cómo validar (en un PC con Windows 10/11 x64)
1. Descarga el repositorio en una ruta corta, por ejemplo `C:\VideoStudioAI`.
2. Abre PowerShell en esa carpeta y ejecuta:
   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows-validation.ps1
   ```
   - Usa una carpeta de datos **aislada** en `%TEMP%`; no toca otra instalación.
   - Instala con el instalador real (modelo ligero `fw-small`), ejecuta `doctor`, las validaciones del proyecto (`check`) y la prueba de punta a punta (`scripts\smoke_e2e.py`).
   - Termina con unas comprobaciones manuales guiadas (panel, asistente, selector de carpetas, Administrador de credenciales, «Mostrar en el Explorador», instancia única, procesos tras cerrar).
   - Opciones: `-SkipCheck`, `-SkipManual`, `-WithCuda` (solo con GPU NVIDIA).
3. Entrega la carpeta `%TEMP%\vsa-validation-<fecha>` que indica al final (no contiene claves reales ni videos personales).

Equipos recomendados para la validación:
- Windows 11 x64 con CPU sola (sin GPU dedicada), 8–16 GB;
- opcional: un equipo con GPU NVIDIA para el complemento CUDA;
- opcional: Windows 10 22H2.

## Criterio para declarar Windows compatible
- Instalación nueva completa sin errores.
- `check`: pruebas del backend sin fallos (las omitidas, justificadas).
- `smoke_e2e.py`: todos los pasos correctos (los 3 estilos, transcripción con faster-whisper, exportación, reinicio y cierre sin procesos).
- Comprobaciones manuales afirmativas y sin procesos vivos tras cerrar.
