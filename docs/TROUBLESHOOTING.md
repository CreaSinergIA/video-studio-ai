# Solución de problemas

Primero, el diagnóstico: `./videostudio doctor` (macOS) o `powershell -NoProfile -ExecutionPolicy Bypass -File .\videostudio.ps1 doctor` (Windows). Muestra qué falta y cómo resolverlo. El registro del servidor: `logs` (o `logs/server.out` en la carpeta de datos).

## Instalación
| Síntoma | Causa probable | Solución |
|---|---|---|
| macOS: «no se puede abrir porque es de un desarrollador no identificado» al hacer doble clic en el `.command` | Archivo descargado de internet | Clic derecho → **Abrir** → **Abrir**, o usa la Terminal: `./videostudio install`. |
| Windows: «Windows protegió su PC» | SmartScreen con archivos descargados | **Más información → Ejecutar de todas formas**. |
| Windows: «la ejecución de scripts está deshabilitada» | Política de PowerShell | Usa los `.cmd` o `powershell -NoProfile -ExecutionPolicy Bypass -File .\videostudio.ps1 …` (no cambia la política del sistema). |
| `uv sync falló` | Sin conexión, proxy o firewall corporativo | Revisa la conexión y vuelve a ejecutar el instalador: continúa donde se quedó. |
| `npm ci falló` en Windows con errores de rutas | Ruta del proyecto demasiado larga | Mueve la carpeta a una ruta corta (`C:\VideoStudioAI`) o activa las rutas largas de Windows. |
| «La huella SHA-256 no coincide» | Descarga corrupta o modificada | Vuelve a ejecutar el instalador. Si se repite, no continúes y avisa: la fuente cambió. |
| «El equipo no cumple los requisitos mínimos» | Windows en ARM, Mac Intel o poco disco | Ver [REQUIREMENTS.md](REQUIREMENTS.md). |
| La instalación se cortó | Cierre de la ventana, reinicio, red | Vuelve a ejecutarla. El estado de cada paso está en `install-state.json` de la carpeta de datos. |

## Arranque
| Síntoma | Solución |
|---|---|
| El navegador muestra «Abre Video Studio AI desde su lanzador» | Abre con el acceso directo o `start`/`open`: el panel necesita el token de sesión. Pasa si abres la dirección a mano, desde otro navegador o tras borrar las cookies. |
| «El puerto 8775 está ocupado» | El lanzador elige otro puerto libre automáticamente y lo indica. Para fijar uno: `VSA_PORT=8790`. |
| «Ya está en marcha» pero no ves el panel | `open` abre otra pestaña. Si no responde: `stop` y `start`. |
| «El servidor no pudo arrancar» | Mira las últimas líneas que muestra el lanzador o `logs`. Un error de base de datos se describe allí; las copias de seguridad están en `backups/` de la carpeta de datos. |
| Queda algo en segundo plano tras cerrar | `stop` termina el árbol completo de procesos. Al arrancar de nuevo, el servidor cierra los procesos que hubieran quedado de un cierre abrupto. |

## Transcripción
| Síntoma | Solución |
|---|---|
| «El modelo … no está instalado» | Descárgalo en *Ajustes → Transcripción* o en la primera configuración. |
| «usa un motor que no está disponible en este equipo» | Pasa al cambiar de sistema con la misma base de datos: elige el modelo recomendado en *Ajustes → Transcripción*. |
| Windows: transcripción lenta | Usa el modelo ligero «Whisper small (faster-whisper)». Con GPU NVIDIA: `install --cuda`. |
| Windows: la GPU NVIDIA no se usa | Comprueba el controlador de NVIDIA. Sin las bibliotecas CUDA (o si fallan), se usa la CPU automáticamente; el registro indica `device: cpu` y el motivo. Forzar CPU: `VSA_ASR_DEVICE=cpu`. |
| Sin palabras en un video con voz | Revisa el idioma en *Ajustes → Transcripción* (o «auto»). Música muy alta o voz muy baja reducen la calidad. |

## Animaciones (Remotion)
| Síntoma | Solución |
|---|---|
| «Falta el navegador de render» | *Ajustes → Animaciones → Descargar navegador de render*. |
| «No se encontró Node.js» | Ejecuta el instalador de nuevo: descarga Node.js portátil si el tuyo es anterior a 20.19. |
| El render falla en Windows con un error de DLL | Instala el *Microsoft Visual C++ Redistributable* (x64) más reciente de Microsoft y vuelve a intentarlo. |

## FFmpeg y exportación
| Síntoma | Solución |
|---|---|
| «No se encontró FFmpeg» | Ejecuta el instalador de nuevo: descarga FFmpeg portátil verificado. |
| «FFmpeg dejó de avanzar … y se detuvo» | Un archivo dañado o un disco desconectado. Comprueba el video y el disco; para videos muy pesados puedes ampliar `VSA_FFMPEG_STALL_SECONDS`. |
| «FFmpeg superó el tiempo máximo» | Exportaciones muy largas en equipos lentos: amplía `VSA_FFMPEG_MAX_SECONDS`. |
| «La resolución … supera el máximo (8K)» / «el máximo admitido es 3 h» | Reduce o divide el video antes de importarlo (o ajusta `VSA_MAX_DURATION_SECONDS`). |

## Claude
| Mensaje | Qué significa |
|---|---|
| «La clave de API no es válida o fue revocada» | Crea otra en https://platform.claude.com/settings/keys y guárdala. |
| «Tu cuenta de Anthropic no tiene saldo o facturación activa» | Añade crédito en https://platform.claude.com/settings/billing. |
| «Se alcanzó el límite de tu cuenta de la API» | Límites por minuto de tu organización: espera y reintenta. Los límites dependen de tu nivel en la Consola. |
| «Tu cuenta no tiene acceso al modelo» | Tu organización no tiene acceso a Claude Opus 5.5. |
| «Sin conexión con la API de Anthropic» | Revisa tu conexión a internet o el proxy. |
| La operación pide confirmación del límite de 24 h | Es el control de solicitudes de Video Studio AI: confirma solo esa operación o sube el límite en *Ajustes → Claude*. |
| «No hay un llavero del sistema disponible» | Windows: el Administrador de credenciales debería estar siempre; vuelve a ejecutar el instalador. Linux: instala GNOME Keyring o KWallet. |

## Datos
- La base de datos está en la carpeta de datos (`app.db`) con copias automáticas en `backups/` (*Ajustes → Datos y respaldos*).
- Si cambias de carpeta de proyectos, los proyectos existentes en la nueva se recuperan automáticamente.
- Para empezar de cero sin perder videos: cierra el editor, mueve la carpeta de datos a otro sitio y abre de nuevo (los proyectos se pueden recuperar eligiendo la misma carpeta de proyectos).

¿Nada de esto? Ejecuta `doctor`, copia su salida y las últimas líneas de `logs` (no contienen tu clave de API) y abre un *issue* cuando el repositorio sea público.
