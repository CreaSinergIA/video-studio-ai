# Seguridad

Video Studio AI es una aplicación **local**: un servidor en tu equipo y un panel en tu navegador. Este documento resume el modelo de amenazas, lo que está protegido y lo que queda pendiente.

## Modelo de amenazas
**Se protege contra:**
- páginas web abiertas en el mismo navegador;
- otros equipos de la red;
- otros programas y otras cuentas del mismo equipo que intenten usar la API local;
- archivos de video o de proyecto manipulados o desmesurados;
- procesos colgados o huérfanos;
- fugas de la clave de API.

**No se protege contra** programas que ya se ejecutan **con tu misma cuenta**: pueden leer tus archivos (incluido el token de sesión) igual que la aplicación.

## Protecciones
| Área | Protección |
|---|---|
| Red | El servidor escucha solo en `127.0.0.1`. El servidor interno de Remotion (puertos 3000–3100) también se limita a la interfaz local. |
| **API local (CE Fase 2)** | Todas las rutas `/api/*` (salvo `/api/health`, que solo identifica la instancia) exigen un **token de sesión**. Se genera por instalación en `run/session.token` (permisos 0600; en Windows, carpeta privada de la cuenta). El lanzador abre `/open?t=…`; el servidor lo cambia por una cookie **HttpOnly** y **SameSite=Strict** y redirige para quitarlo de la barra de direcciones. Los scripts pueden usar la cabecera `X-VSA-Token`. |
| Navegador | Hosts permitidos (anti *DNS rebinding*), cabecera `X-VSA-Client` en las peticiones que modifican datos (CSRF), `X-Frame-Options: DENY`, `frame-ancestors 'none'`, `nosniff`, `no-referrer`. La documentación interactiva (`/api/docs`, con recursos de un CDN) está **desactivada** salvo `VSA_API_DOCS=1`. |
| Instancia | Bloqueo exclusivo de la carpeta de datos: nunca hay dos servidores sobre la misma base de datos. |
| Archivos | Todas las rutas del almacenamiento se resuelven dentro de su raíz (`resolve_inside`). Los originales se guardan en solo lectura y nunca se modifican. Las descargas (zip/tar) rechazan rutas que salgan de su carpeta. |
| Videos importados | Solo `.mp4` y `.mov`, con la firma real del contenedor comprobada. `ffprobe` solo abre archivos locales con el demuxer MP4/MOV. **Límites (CE Fase 2):** resolución máxima 8K, duración máxima 3 h y 240 fps (configurables). |
| Textos editables | **Topes de longitud (CE Fase 2)** en objetivo, descripción, justificación y nota de cada intervención, además de los límites de las propuestas de Claude y de las instrucciones. |
| Proyectos adoptados | Los datos técnicos del video se vuelven a medir en el archivo: `project.json` no es de confianza. Los valores que llegan a FFmpeg se validan de nuevo. |
| **FFmpeg (CE Fase 2)** | Vigilante en cada ejecución: si deja de avanzar 5 minutos (`VSA_FFMPEG_STALL_SECONDS`) o supera el tiempo máximo (30× la duración del video, mínimo 1 h; `VSA_FFMPEG_MAX_SECONDS`), se detiene con todo su árbol. Cancelación inmediata. |
| **Procesos (CE Fase 2)** | Siempre con lista de argumentos, nunca a través de una shell. Al terminar o cancelar un render se cierran **todos** sus descendientes, también los que se separan de su grupo (el navegador de Remotion). Los hijos se registran: tras un cierre abrupto, el siguiente arranque cierra los que quedaran vivos. En Windows, un *Job Object* cierra todo si el servidor muere. |
| Render | No recibe código, solo especificaciones validadas. Su entorno no contiene secretos (en Windows, solo las variables de sistema necesarias). |
| Claude | La clave se guarda en el llavero del sistema (Llavero de macOS; **Administrador de credenciales de Windows**, CE Fase 2), nunca en el navegador, la base de datos ni los registros. Esta edición no busca ni ejecuta el CLI de Claude Code. Las pruebas usan un almacén de credenciales y una API simulados: nunca tocan el llavero real ni hacen solicitudes de pago. |
| Diálogos nativos | AppleScript con los textos y rutas como argumentos (`on run argv`), **sin interpolar** (CE Fase 2). Windows: parámetros de PowerShell con nombre. |
| Descargas | Versión y huella **SHA-256 fijadas** para uv, Node.js, FFmpeg, el navegador de render (más MD5 de Google y firma de código en macOS) y cada archivo de los modelos. FFmpeg de macOS: firma de Developer ID con equipo fijado. Lo que no coincide se descarta. |
| Instalador | Sin `sudo`, sin administrador, sin cambiar el PATH ni la política de ejecución del sistema. Pide confirmación antes de cada descarga. |
| Dependencias | `npm audit` (panel y motor) y `pip-audit` (backend) sin vulnerabilidades conocidas en la última revisión. |

## Pendiente (documentado, no bloqueante)
- **Llavero en macOS:** el elemento se crea con la herramienta `security`, así que otro proceso del mismo usuario puede leerlo con ella. Se puede restringir con una lista de acceso específica cuando haya un ejecutable firmado.
- **Navegador de render:** no tiene identificador de equipo de firma (no se puede fijar el firmante) y se ejecuta con `--no-sandbox`, como hace Remotion, solo sobre contenido generado por la propia aplicación.
- **Token en el historial del navegador:** la URL `/open?t=…` puede quedar en el historial local del navegador. Solo sirve en este equipo y para esta instalación; borrar `run/session.token` genera uno nuevo.
- **Windows:** todas las protecciones anteriores están implementadas, pero su comportamiento en Windows real está pendiente de validar.

## Informar de un problema
Mientras el proyecto no se publique no hay canal público. Cuando se publique, se habilitará un canal privado de avisos de seguridad.
