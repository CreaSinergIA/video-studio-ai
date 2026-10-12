# Instrucciones para Claude Code: instalar y abrir Video Studio AI

Este archivo lo lee Claude Code al abrir el repositorio. Si la persona te pide **instalar**, **abrir** o **arreglar** Video Studio AI — Community Edition, sigue estos pasos. Todo es local: no hay cuentas, servidores ni pagos de Video Studio AI.

## Reglas
- **Pregunta antes de descargar o instalar.** El instalador descarga (con versión y huella SHA-256 fijadas, solo si faltan) uv, Python 3.12, Node.js LTS, FFmpeg, el navegador de render (~105–125 MB) y un modelo de transcripción (0,5–1,6 GB). Explícaselo y pide confirmación. Con su «sí», ejecuta el instalador con `--yes` (tú no puedes responder a sus preguntas interactivas).
- **Nada global ni con administrador.** No uses `sudo`, `brew install`, `winget`, `choco` ni cambies el PATH o la política de ejecución del sistema. El instalador lo guarda todo en la carpeta de datos de la aplicación.
- **Nunca pidas ni escribas la clave de API de Anthropic.** La persona la pega en el panel (Ajustes → Claude o primera configuración). No la pongas en archivos, variables de entorno, comandos ni en el chat.
- **No hagas solicitudes a Claude en nombre de la persona** (botón «Probar conexión» o generar planes): cuestan dinero en su cuenta.
- No modifiques el código para «hacer que funcione» sin explicarlo antes. Si algo falla, usa `doctor` y `docs/TROUBLESHOOTING.md`.

## macOS
```bash
./videostudio install --yes        # instalación completa y abre el panel
./videostudio install --yes --no-model   # sin descargar el modelo (se puede hacer desde el panel)
./videostudio doctor               # diagnóstico
./videostudio start | stop | status | logs
```
El instalador ofrece crear `~/Applications/Video Studio AI.app` (acceso directo). Con `--yes` lo crea; usa `--no-shortcut` si la persona no lo quiere.

## Windows 10/11 (x64)
Desde PowerShell, en la carpeta del repositorio:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\videostudio.ps1 install --yes
powershell -NoProfile -ExecutionPolicy Bypass -File .\videostudio.ps1 doctor
powershell -NoProfile -ExecutionPolicy Bypass -File .\videostudio.ps1 start   # o stop | status | logs
```
`-ExecutionPolicy Bypass` solo afecta a ese proceso. La persona también puede hacer doble clic en «Instalar Video Studio AI.cmd» y después en «Video Studio AI.cmd» o en el acceso directo del Escritorio.

Con una GPU NVIDIA se puede añadir `--cuda` (~1,5 GB extra) para acelerar la transcripción. Sin ella se usa la CPU: **no hace falta GPU**.

**Estado de Windows:** las adaptaciones están implementadas, pero la validación en un equipo Windows real está pendiente (ver `docs/WINDOWS-VALIDATION.md`). Si encuentras un fallo en Windows, recoge `doctor` y `logs` y explícalo con claridad; no declares que funciona si no lo has comprobado.

## Después de instalar
1. El panel se abre en `http://127.0.0.1:8775` (u otro puerto libre si ese está ocupado) con el asistente de **primera configuración**: carpeta de proyectos, comprobaciones del equipo y clave de Claude (opcional).
2. Para volver a abrirlo: acceso directo o `start`. Si ya está abierto, `start` solo abre otra pestaña.
3. Si el navegador muestra «Abre Video Studio AI desde su lanzador», ejecuta `start` (o `open`): el panel necesita el token de sesión que entrega el lanzador.

## Más información
- Instalación detallada: `docs/INSTALL-macOS.md`, `docs/INSTALL-Windows.md`, `docs/REQUIREMENTS.md`.
- Uso diario: `docs/LAUNCHING.md` · primera configuración: `docs/FIRST-RUN.md` · Claude: `docs/CLAUDE.md`.
- Problemas: `docs/TROUBLESHOOTING.md`.

## Desarrollo
`./videostudio check` (lint, tipos, pruebas, compilación) · `cd frontend && npm run e2e` · `git config core.hooksPath .githooks` (comprobación de privacidad antes de cada commit). Arquitectura en `docs/ARCHITECTURE.md`.
