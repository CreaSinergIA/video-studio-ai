# Instalación en macOS

Requisitos: Mac con Apple Silicon y macOS 14 o posterior ([REQUIREMENTS.md](REQUIREMENTS.md)). No hace falta Homebrew, Xcode ni permisos de administrador.

## 1. Descargar el proyecto
- Con Git: `git clone https://github.com/CreaSinergIA/video-studio-ai.git`
- O descarga el ZIP desde https://github.com/CreaSinergIA/video-studio-ai (botón «Code → Download ZIP») y descomprímelo. Guárdalo en una carpeta de tu disco interno (por ejemplo `~/Developer` o `~/Aplicaciones`), no en un disco externo ni en una carpeta sincronizada con iCloud.

## 2. Instalar
**Opción A — doble clic:** abre la carpeta en Finder y haz doble clic en **Instalar Video Studio AI.command**.
- La primera vez, macOS puede bloquearlo porque se descargó de internet: clic derecho → **Abrir** → **Abrir**, o *Ajustes del Sistema → Privacidad y seguridad → Abrir igualmente*.

**Opción B — Terminal:**
```bash
cd video-studio-ai
./videostudio install
```

**Opción C — Claude Code:** pídele «Instala Video Studio AI» (ver [CLAUDE.md](../CLAUDE.md)).

El instalador muestra cada paso y pregunta antes de descargar:

| Paso | Qué hace |
|---|---|
| uv y Python | Si no tienes uv, descarga uv 0.12.18 a la carpeta de datos (SHA-256 verificado). uv prepara Python 3.12 y las dependencias en `backend/.venv`. |
| 1. Requisitos | Sistema, memoria y disco. |
| 2. FFmpeg | Usa el tuyo si sirve (por ejemplo, el de Homebrew). Si no, descarga FFmpeg 9.0.2 portátil (firmado por su autor; se comprueba la firma y la huella). |
| 3. Node.js | Usa el tuyo si es ≥ 20.19. Si no, descarga Node.js 24 LTS portátil. |
| 4. Dependencias | `npm ci` del panel y del motor de animaciones (Remotion), con versiones fijadas. |
| 5. Panel | Compila la interfaz. |
| 6. Datos | Crea la carpeta de datos (solo legible por tu usuario), una base de datos vacía y el token de sesión. |
| 7. Navegador de render | Descarga Chrome Headless Shell 157 (~104 MB), verificado por tamaño, MD5, SHA-256 y firma de código de Google. |
| 8. Modelo | Descarga Whisper large-v3-turbo (1,6 GB) para transcribir con MLX. |
| 9. Acceso directo | Crea `~/Applications/Video Studio AI.app` (puedes arrastrarlo al Dock). |
| 10. Verificación | Diagnóstico final y apertura del panel en el navegador. |

Opciones: `--yes` (acepta lo recomendado), `--no-model`, `--model large-v3-turbo-q4` (modelo ligero de 0,46 GB), `--no-browser-engine`, `--no-shortcut`, `--no-start`.

Si la instalación se interrumpe (sin conexión, cierre de la ventana…), vuelve a ejecutarla: continúa donde se quedó. El estado está en `install-state.json` de la carpeta de datos.

## 3. Abrir el editor
- App **Video Studio AI** de `~/Applications` (o del Dock), o
- doble clic en **Video Studio AI.command**, o
- `./videostudio start`.

Se abre `http://127.0.0.1:8775` en tu navegador predeterminado. Ver [LAUNCHING.md](LAUNCHING.md).

## Permisos de macOS
- **Discos externos y carpetas protegidas** (Escritorio, Documentos, Descargas): la primera vez que el editor acceda, macOS puede preguntar si permites el acceso a «python3». Acepta para poder guardar proyectos allí. Se gestiona en *Ajustes del Sistema → Privacidad y seguridad → Archivos y carpetas*.
- **Llavero:** la clave de API se guarda en tu llavero de inicio de sesión (servicio «VideoStudioAI-Community»).
- No se necesitan permisos de accesibilidad, grabación de pantalla ni de administrador.

## Desinstalar
1. `./videostudio stop`
2. Borra la carpeta del proyecto, `~/Applications/Video Studio AI.app` y la carpeta de datos `~/Library/Application Support/VideoStudioAI-Community` (contiene la base de datos de tus proyectos: haz una copia antes si la quieres conservar).
3. Opcional: borra la clave en *Acceso a Llaveros* (busca «VideoStudioAI-Community»).
4. Tus videos y exportaciones siguen en la carpeta de proyectos que elegiste; bórrala solo si ya no los quieres.
