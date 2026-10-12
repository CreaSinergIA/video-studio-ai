# Actualizar Video Studio AI

Las nuevas versiones se publican en https://github.com/CreaSinergIA/video-studio-ai/releases.

**Actualizar no toca tus datos.** Tus proyectos, videos, planes, animaciones, exportaciones, ajustes y tu clave de API viven fuera de la carpeta del programa:
- la carpeta de proyectos que elegiste;
- la carpeta de la aplicación: `~/Library/Application Support/VideoStudioAI-Community` (macOS) o `%LOCALAPPDATA%\VideoStudioAI-Community` (Windows), con la base de datos, los modelos, el motor de render y las herramientas;
- la clave, en el llavero del sistema.

Al arrancar una versión nueva, si la base de datos necesita cambios, la aplicación crea antes una **copia de seguridad verificada** (`backups/pre-migracion-…`). Si quieres, crea además una copia manual en *Ajustes → Datos y respaldos* antes de actualizar.

## Con Claude Code (lo más sencillo)
Abre Claude Code en la carpeta de Video Studio AI y pídele:

> Actualiza Video Studio AI a la última versión siguiendo docs/UPDATING.md

## Si lo descargaste con `git clone`
macOS:
```bash
cd video-studio-ai
./videostudio stop
git pull --ff-only
./videostudio install --yes --no-model
```
Windows (PowerShell, en la carpeta del programa):
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\videostudio.ps1 stop
git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\videostudio.ps1 install --yes --no-model
```
El instalador solo vuelve a hacer lo que cambió (dependencias nuevas, compilación del panel) y abre el panel al terminar. `--no-model` evita preguntar por modelos que ya tienes.

Si `git pull` dice que hay cambios locales, es que se modificó algún archivo del programa. Guárdalos con `git stash` (o descarta los cambios si no los necesitas) y repite.

## Si lo descargaste como ZIP
1. Cierra Video Studio AI (*Ajustes → Acerca de → Cerrar*, o el acceso «Cerrar Video Studio AI»).
2. Descarga el ZIP de la nueva versión desde la página de *Releases* y descomprímelo en una carpeta nueva.
3. Ejecuta el instalador de la carpeta nueva («Instalar Video Studio AI.command» en macOS, «Instalar Video Studio AI.cmd» en Windows). Reutiliza tus datos y vuelve a crear los accesos directos apuntando a la carpeta nueva.
4. Cuando compruebes que todo funciona, borra la carpeta antigua del programa (**no** la carpeta de la aplicación ni la de tus proyectos).

## Volver a la versión anterior
- Con Git: `git checkout v<versión-anterior>` y vuelve a ejecutar el instalador.
- Con ZIP: usa la carpeta antigua.
- Si la versión nueva migró la base de datos, restaura la copia `pre-migracion-…` en *Ajustes → Datos y respaldos*.

## Para Claude Code: pasos de actualización
1. Detecta el sistema operativo y si la carpeta es un clon de Git (`git rev-parse --is-inside-work-tree`).
2. Cierra el panel con `stop`.
3. Con Git: `git fetch --tags` y `git pull --ff-only`. Si hay cambios locales, **no los descartes sin preguntar**.
4. Sin Git: explica el procedimiento del ZIP; no borres carpetas de la persona.
5. Ejecuta `install --yes --no-model` (en Windows, con `-ExecutionPolicy Bypass`).
6. Informa de la versión instalada (`status`) y de la dirección del panel.
7. Nunca borres la carpeta de la aplicación, la de proyectos ni las credenciales.
