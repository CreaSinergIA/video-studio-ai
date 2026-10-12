# Instrucciones para Claude Code: instalar, abrir y actualizar Video Studio AI

Si la persona te pide **instalar**, **abrir**, **actualizar** o **arreglar** Video Studio AI — Community Edition, sigue este archivo. Todo es local y gratuito: no hay cuentas, servidores ni pagos de Video Studio AI.

## Reglas
- **Pide permiso antes de descargar.** Explica qué va a descargar el instalador (solo lo que falte; versiones y huellas SHA-256 fijadas): uv y Python 3.12, Node.js LTS, FFmpeg, las dependencias del panel y de Remotion, el navegador de render (~105–125 MB) y un modelo de transcripción (0,5–1,6 GB). Con su «sí», ejecuta el instalador con `--yes` (tú no puedes responder a sus preguntas interactivas).
- **Nada global ni con administrador:** no uses `sudo`, `brew install`, `winget`, `choco`, `npm -g` ni `pip install` fuera del proyecto, y no cambies el PATH ni la política de ejecución del sistema. El instalador lo guarda todo en la carpeta de la aplicación.
- **Credenciales:** nunca pidas, leas, escribas ni muestres claves de API, tokens o cookies. La clave de Anthropic es **opcional** y la persona la pega en el panel (*primera configuración* o *Ajustes → Claude*). No uses tu propia sesión de Claude ni la de la persona para alimentar el panel.
- **No hagas solicitudes de pago a Claude** desde el panel (botones «Probar conexión», «Planificar») en nombre de la persona.
- **Rutas:** instala en la carpeta donde la persona te indique o en una ruta corta de su usuario (macOS: `~/video-studio-ai`; Windows: `C:\VideoStudioAI` o `%USERPROFILE%\VideoStudioAI`). Nunca en discos externos ni en carpetas sincronizadas (iCloud, OneDrive).
- No modifiques el código para «hacer que funcione» sin explicarlo antes.

## Instalación paso a paso
1. **Obtén el código** (si aún no estás dentro del repositorio):
   `git clone https://github.com/CreaSinergIA/video-studio-ai.git` (o la ruta corta acordada) y entra en la carpeta. Si no hay Git, pide a la persona que descargue el ZIP de la página del repositorio y lo descomprima.
2. **Reconoce el sistema:**
   - macOS con Apple Silicon (`uname -sm` → `Darwin arm64`): compatible y validado.
   - macOS Intel (`Darwin x86_64`): **no compatible**; explícalo y detente.
   - Windows x64: compatible (pendiente de validación en hardware real; avísalo).
   - Windows en ARM: **no compatible**; explícalo y detente.
   - Lee `docs/INSTALL-macOS.md` o `docs/INSTALL-Windows.md` y `docs/REQUIREMENTS.md` si necesitas detalles.
3. **Explica lo que se descargará y pide permiso** (ver *Reglas*).
4. **Ejecuta el instalador** (comprueba los requisitos, instala dependencias, prepara datos, base de datos, navegador de render, modelo y acceso directo, y abre el panel):
   - macOS: `./videostudio install --yes`
   - Windows (PowerShell): `powershell -NoProfile -ExecutionPolicy Bypass -File .\videostudio.ps1 install --yes`
   - Opciones: `--no-model` (descargar el modelo después, desde el panel), `--model large-v3-turbo-q4` (Mac, ligero) o `--model fw-small` (Windows, ligero), `--no-shortcut`, `--no-start`, `--cuda` (solo Windows con GPU NVIDIA y permiso de la persona).
   - La instalación puede tardar 5–20 minutos según la conexión. Muestra el progreso con mensajes breves.
5. **Primera configuración:** al terminar se abre el navegador en el asistente (carpeta de proyectos, comprobaciones del equipo, clave de Claude opcional). Dile a la persona que lo complete allí; tú no escribes la clave.
6. **Informa del resultado:** la dirección local que muestra el instalador (normalmente `http://127.0.0.1:8775`, u otro puerto si estaba ocupado) y cómo volver a abrirlo:
   - macOS: app **Video Studio AI** en `~/Applications`, **Video Studio AI.command** o `./videostudio start`;
   - Windows: acceso directo **Video Studio AI** (Escritorio / menú Inicio) o **Video Studio AI.cmd**.

## Si algo falla
- Lee el mensaje del instalador: indica el paso que falló y cómo resolverlo. Volver a ejecutar el instalador continúa donde se quedó.
- Diagnóstico: `./videostudio doctor` (Windows: `videostudio.ps1 doctor`). Registro: `logs`.
- Consulta `docs/TROUBLESHOOTING.md` y explica la solución en lenguaje sencillo.
- Problemas habituales: sin conexión (repetir), ruta demasiado larga en Windows (mover a `C:\VideoStudioAI`), SmartScreen o Gatekeeper al hacer doble clic (usar la terminal), puerto ocupado (el lanzador elige otro solo).
- Si el navegador muestra «Abre Video Studio AI desde su lanzador», ejecuta `start` u `open`.

## Uso diario
`start` (abrir o reutilizar), `stop` (cerrar sin dejar procesos), `restart`, `status`, `open`, `logs`, `doctor`. Ver `docs/LAUNCHING.md`.

## Actualizar
Sigue `docs/UPDATING.md`: `stop` → `git pull --ff-only` → `install --yes --no-model`. Nunca borres la carpeta de la aplicación, la de proyectos ni las credenciales.

## Qué funciona sin clave de Claude
Importar, transcribir en local, revisar la transcripción, subtítulos y su estilo, presets, ajustes de audio y exportar. El **plan de edición** y las **animaciones dirigidas por Claude** necesitan la clave de API de la persona (se factura en su cuenta de Anthropic; **no** está incluida en Claude Pro ni Max). Detalles: `docs/CLAUDE.md`.

## Desarrollo
`./videostudio check` (lint, tipos, pruebas, compilación) · `cd frontend && npm run e2e` · `backend/.venv/bin/python scripts/smoke_e2e.py` · `git config core.hooksPath .githooks` (comprobación de privacidad antes de cada commit). Arquitectura: `docs/ARCHITECTURE.md`.
