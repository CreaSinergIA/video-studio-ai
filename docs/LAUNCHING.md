# Iniciar, reabrir y cerrar el panel

Video Studio AI es un servidor local con un panel en tu navegador. No necesitas Claude Code ni la terminal para usarlo cada día.

| | macOS | Windows |
|---|---|---|
| Abrir | app **Video Studio AI** (`~/Applications`, Dock) · **Video Studio AI.command** · `./videostudio start` | acceso **Video Studio AI** (Escritorio / menú Inicio) · **Video Studio AI.cmd** · `videostudio.ps1 start` |
| Cerrar | *Ajustes → Acerca de → Cerrar* · `./videostudio stop` | **Cerrar Video Studio AI** (menú Inicio) · *Ajustes → Acerca de → Cerrar* · `videostudio.ps1 stop` |
| Reiniciar | `./videostudio restart` | `videostudio.ps1 restart` |
| Estado | `./videostudio status` | `videostudio.ps1 status` |
| Registro | `./videostudio logs -f` | `videostudio.ps1 logs -f` |
| Diagnóstico | `./videostudio doctor` | `videostudio.ps1 doctor` |

(En Windows, desde PowerShell: `powershell -NoProfile -ExecutionPolicy Bypass -File .\videostudio.ps1 <orden>`.)

## Cómo se comporta
- **Solo local:** escucha únicamente en `127.0.0.1`. Nadie de tu red puede conectarse.
- **Una sola instancia:** si ya está en marcha, abrirlo de nuevo solo abre otra pestaña del navegador. Un bloqueo impide dos servidores sobre la misma carpeta de datos.
- **Puerto ocupado:** si el 8775 lo usa otro programa, se elige el siguiente libre (8776–8799) y se indica en pantalla.
- **Sesión:** el lanzador abre `http://127.0.0.1:<puerto>/open?t=…`; el servidor cambia ese token por una cookie segura y te lleva al panel. Si abres la dirección a mano sin cookie, el panel te pide abrirlo desde el lanzador. La cookie dura 30 días.
- **Cierre ordenado:** se cancelan las tareas en curso (render, transcripción, FFmpeg) y no queda ningún proceso en segundo plano. Si el servidor no respondiera, el lanzador termina su árbol de procesos.
- **Sin procesos huérfanos tras un cierre abrupto:** en Windows, un *Job Object* hace que el sistema cierre los procesos hijos si el servidor muere. En macOS, el servidor registra sus procesos hijos y, al volver a arrancar, cierra los que hubieran quedado vivos.
- **Tus proyectos se conservan** entre reinicios: viven en la base de datos de la aplicación y en tu carpeta de proyectos.
- **Archivo de instancia:** `run/instance.json` (PID, puerto, versión) en la carpeta de datos.

## Variables útiles (avanzado)
| Variable | Uso |
|---|---|
| `VSA_PORT` | puerto preferido |
| `VSA_HOME` | otra carpeta de datos (por ejemplo, para pruebas aisladas) |
| `VSA_NO_BROWSER=1` | no abrir el navegador |
| `VSA_ASR_DEVICE=cpu` | forzar la CPU en faster-whisper |
| `VSA_FFMPEG_STALL_SECONDS`, `VSA_FFMPEG_MAX_SECONDS` | vigilante de FFmpeg (bloqueo y tiempo máximo) |
| `VSA_MAX_DURATION_SECONDS` | duración máxima de un video importado (3 h por defecto) |
