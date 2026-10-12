# Instalación en Windows

> **Estado:** todas las adaptaciones para Windows están implementadas y probadas con simulaciones en macOS, pero **todavía no se han validado en un PC con Windows real**. Si lo instalas, el kit de [WINDOWS-VALIDATION.md](WINDOWS-VALIDATION.md) ayuda a confirmar que todo funciona.

Requisitos: Windows 10 (1809+) u 11 de **64 bits (x64)**, 8 GB de memoria, ~6 GB libres ([REQUIREMENTS.md](REQUIREMENTS.md)). **No hace falta** WSL, Docker, Python, una GPU NVIDIA ni permisos de administrador.

## 1. Descargar el proyecto
- Con Git: `git clone <url-del-repositorio> C:\VideoStudioAI`
- O descarga el ZIP desde GitHub: clic derecho → **Extraer todo** a una carpeta corta, por ejemplo `C:\VideoStudioAI` o `C:\Users\<tú>\VideoStudioAI`.

Usa una **ruta corta**: las dependencias de Node tienen rutas profundas y Windows limita las rutas a 260 caracteres si no están activadas las rutas largas. Evita carpetas sincronizadas con OneDrive.

## 2. Instalar
**Opción A — doble clic:** abre la carpeta y haz doble clic en **Instalar Video Studio AI.cmd**.
- Si aparece *Windows protegió su PC* (SmartScreen), pulsa **Más información → Ejecutar de todas formas**. Es un script de texto que puedes revisar con el Bloc de notas.

**Opción B — PowerShell:**
```powershell
cd C:\VideoStudioAI
powershell -NoProfile -ExecutionPolicy Bypass -File .\videostudio.ps1 install
```
`-ExecutionPolicy Bypass` solo afecta a esa ejecución; no cambia la configuración de Windows.

**Opción C — Claude Code:** pídele «Instala Video Studio AI» (ver [CLAUDE.md](../CLAUDE.md)).

Pasos del instalador (pregunta antes de cada descarga):

| Paso | Qué hace |
|---|---|
| uv y Python | Descarga uv 0.12.18 a `%LOCALAPPDATA%\VideoStudioAI-Community\tools\uv` (SHA-256 verificado). uv prepara Python 3.12 y las dependencias en `backend\.venv`. |
| 1. Requisitos | Windows x64, compilación, memoria, disco y rutas largas. |
| 2. FFmpeg | Usa el tuyo si sirve. Si no, descarga FFmpeg 9.0.2 «essentials» (compilación de Gyan Doshi enlazada desde ffmpeg.org, 115 MB, SHA-256 verificado). |
| 3. Node.js | Usa el tuyo si es ≥ 20.19. Si no, descarga Node.js 24 LTS portátil (zip oficial de nodejs.org). |
| 4. Dependencias | `npm ci` del panel y de Remotion (incluye su compositor para Windows x64). |
| 5. Panel | Compila la interfaz. |
| 6. Datos | Carpeta de datos privada de tu cuenta, base de datos vacía y token de sesión. |
| 7. Navegador de render | Chrome Headless Shell 157 para Windows (~126 MB), verificado por tamaño, MD5 y SHA-256. |
| 8. Modelo | Whisper large-v3-turbo para **faster-whisper** (1,6 GB). En equipos modestos elige el ligero: `--model fw-small` (0,5 GB). |
| 8b. NVIDIA (opcional) | Con `--cuda` y una GPU NVIDIA: bibliotecas CUDA 12/cuDNN 9 (~1,5 GB). Si fallan al cargar, se usa la CPU. |
| 9. Accesos directos | «Video Studio AI» en el Escritorio y el menú Inicio, y «Cerrar Video Studio AI» en el menú Inicio. |
| 10. Verificación | Diagnóstico final y apertura del panel en el navegador. |

Opciones: `--yes`, `--no-model`, `--model fw-small`, `--no-browser-engine`, `--no-shortcut`, `--no-start`, `--cuda`.

Si la instalación se interrumpe, vuelve a ejecutarla: continúa donde se quedó.

## 3. Abrir el editor
- Acceso directo **Video Studio AI** (Escritorio o menú Inicio), o
- doble clic en **Video Studio AI.cmd**, o
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\videostudio.ps1 start`.

Se abre `http://127.0.0.1:8775` en tu navegador predeterminado. El servidor funciona en segundo plano, sin ventana. Para cerrarlo: **Cerrar Video Studio AI** del menú Inicio o *Ajustes → Acerca de → Cerrar Video Studio AI*. Ver [LAUNCHING.md](LAUNCHING.md).

## Detalles de Windows
- **Transcripción:** faster-whisper (CTranslate2) en la CPU con INT8. Con GPU NVIDIA y el complemento CUDA se usa la GPU automáticamente. No usa MLX ni requiere WSL.
- **Clave de API:** se guarda en el **Administrador de credenciales de Windows** (Credenciales de Windows → «VideoStudioAI-Community»), cifrada para tu cuenta.
- **Exportación:** codificadores por software (libx264/libx265). NVENC, Quick Sync y AMF se detectan pero no se usan hasta validarlos.
- **Cortafuegos:** el servidor solo escucha en `127.0.0.1`, así que Windows no debería pedir permiso de red.
- **Antivirus:** algunos antivirus analizan los archivos de `node_modules` y los modelos durante la instalación y la ralentizan; no hace falta desactivarlo.
- **Discos externos:** puedes guardar los proyectos en otra unidad (`D:\Videos\VideoStudio`). Si la desconectas, el editor lo detecta y no crea carpetas en su lugar.

## Desinstalar
1. **Cerrar Video Studio AI** (menú Inicio).
2. Borra la carpeta del proyecto, los accesos directos y `%LOCALAPPDATA%\VideoStudioAI-Community` (contiene la base de datos de tus proyectos).
3. Opcional: borra la credencial «VideoStudioAI-Community» en el Administrador de credenciales.
4. Tus videos y exportaciones siguen en la carpeta de proyectos que elegiste.
