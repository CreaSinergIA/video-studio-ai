# Seguridad

Video Studio AI es una aplicación **local**: un servidor en tu equipo y un panel en tu navegador. Este documento resume el modelo de amenazas, lo que está protegido y lo que queda pendiente.

## Modelo de amenazas
**Se protege contra:**
- páginas web abiertas en el mismo navegador;
- otros equipos de la red;
- archivos de video o de proyecto manipulados;
- fugas de la clave de API.

**No se protege contra** programas que ya se ejecutan con tu usuario en el mismo equipo: pueden leer tus archivos igual que la aplicación.

## Protecciones actuales
| Área | Protección |
|---|---|
| Red | El servidor escucha solo en `127.0.0.1`. El servidor interno de Remotion (puertos 3000–3100) también se limita a la interfaz local. |
| Navegador | Los hosts permitidos impiden el *DNS rebinding*. Las peticiones que modifican datos exigen la cabecera `X-VSA-Client` (CSRF). `X-Frame-Options: DENY` y `frame-ancestors 'none'` impiden incrustar el panel en otra página. Además, `nosniff` y `no-referrer`. |
| Archivos | Todas las rutas del almacenamiento se resuelven dentro de su raíz (`resolve_inside`). Los originales se guardan en solo lectura y nunca se modifican. |
| Videos importados | Solo `.mp4` y `.mov`, con la firma real del contenedor comprobada (subida y ruta local). `ffprobe` solo abre archivos locales con el demuxer MP4/MOV (`-protocol_whitelist file`, `-format_whitelist`). |
| Proyectos adoptados | Al recuperar proyectos desde el almacenamiento, los datos técnicos del video se vuelven a medir en el propio archivo: `project.json` es editable y no se confía en él. Los valores que llegan a los filtros de FFmpeg se validan de nuevo al componer. |
| Procesos | Siempre con lista de argumentos, nunca a través de una shell. El render no recibe código, solo especificaciones validadas. Su entorno no contiene secretos. |
| Claude | La clave se guarda en el llavero del sistema y nunca en el navegador, la base de datos ni los registros. Esta edición no busca ni ejecuta el CLI de Claude Code: la ruta configurable no puede usarse para lanzar programas. |
| Descargas | Los modelos se descargan con revisión fijada. El navegador de render se verifica por tamaño, MD5 publicado por Google, **SHA-256 fijado** y `codesign --verify --strict`. |
| Dependencias | `npm audit` (panel y motor) y `pip-audit` (backend), sin vulnerabilidades conocidas en la última revisión. |

## Pendiente (documentado, no bloqueante)
- **Token de sesión en la API local.** Otro usuario del mismo equipo, u otro programa, puede llamar a `127.0.0.1:8775`. Se propone un token por arranque, entregado al panel mediante una cookie `HttpOnly`.
- **Límites de recursos.** No hay tope de resolución ni de duración, y FFmpeg no tiene tiempo máximo global (sí cancelación). Se propone limitar a 8K, a una duración razonable y añadir un vigilante de inactividad.
- **Tamaño de los textos editables:** limitar la longitud por intervención.
- **Llavero en macOS.** El elemento se crea con la herramienta `security`, así que otro proceso del mismo usuario puede leerlo con ella. Se propone una lista de acceso específica de la aplicación cuando haya un ejecutable firmado.
- **Llavero en Windows:** pendiente (Administrador de credenciales). Hoy responde con un error claro.
- **Navegador de render:**
  - no tiene identificador de equipo de firma, así que no se puede fijar el firmante;
  - se ejecuta con `--no-sandbox`, como hace Remotion, solo sobre contenido generado por la propia aplicación.
- **`/api/docs`:** la documentación interactiva carga sus recursos desde un CDN. Se puede desactivar en la versión empaquetada.
- **Selector de carpetas en macOS:** AppleScript construido con escapes. Pasar a `argv` como en el inicio de sesión.

## Informar de un problema
Mientras el proyecto no se publique no hay canal público. Cuando se publique, se habilitará un canal privado de avisos de seguridad.
