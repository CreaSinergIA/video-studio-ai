#Requires -Version 5.1
<#
  Video Studio AI - Community Edition: lanzador para Windows 10/11 (x64).

    .\videostudio.ps1 install    Instalador guiado (requisitos, dependencias, motor, modelo, accesos)
    .\videostudio.ps1 start      Inicia el panel (o reutiliza el que ya está en marcha) y lo abre
    .\videostudio.ps1 stop       Cierra el panel sin dejar procesos en segundo plano
    .\videostudio.ps1 restart | status | open | logs [-f] | doctor | check

  Lo normal es usar los archivos de doble clic: "Instalar Video Studio AI.cmd" y
  "Video Studio AI.cmd", o los accesos directos que crea el instalador.

  Opciones del instalador: --yes (acepta lo recomendado), --no-model, --model <id>,
  --no-browser-engine, --no-shortcut, --no-start, --cuda (solo con GPU NVIDIA).
  Nada se instala de forma global ni se cambia el PATH del sistema: las herramientas
  portátiles viven en %LOCALAPPDATA%\VideoStudioAI-Community\tools.
#>
param(
  [Parameter(Position = 0)][string]$Command = "start",
  [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest = @()
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest es muy lento con barra de progreso
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$Renderer = Join-Path $Root "renderer"
$Py = Join-Path $Backend ".venv\Scripts\python.exe"
if ($env:VSA_HOME) { $DataHome = $env:VSA_HOME } else { $DataHome = Join-Path $env:LOCALAPPDATA "VideoStudioAI-Community" }
$Tools = Join-Path $DataHome "tools"
$UvDir = Join-Path $Tools "uv"

# Versión fijada de uv (gestor de Python de Astral) y huella SHA-256 de su publicación.
$UvVersion = "0.12.18"
$UvAssets = @{
  "AMD64" = @("uv-x86_64-pc-windows-msvc.zip", "cae6a3bc25239f83dffb467a4b180508d9da23986c04639ebfa44e43e6a84bff")
}

$env:PATH = "$UvDir;$env:PATH"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools "python"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

function Write-Ok($t) { Write-Host "  [ok] $t" -ForegroundColor Green }
function Write-Info($t) { Write-Host "  >  $t" -ForegroundColor Cyan }
function Write-Fail($t) { Write-Host "  [x] $t" -ForegroundColor Red; exit 1 }

function Test-Flag($name) {
  foreach ($a in $Rest) { if ($a -eq $name -or ($name -eq "--yes" -and $a -eq "-y")) { return $true } }
  return $false
}

function Confirm-Step($question) {
  if ((Test-Flag "--yes") -or [Console]::IsInputRedirected) { Write-Info "$question -> sí"; return $true }
  $a = Read-Host "  ? $question [S/n]"
  return ($a -eq "" -or $a -match "^[sSyY]")
}

function Test-Platform {
  $arch = $env:PROCESSOR_ARCHITECTURE
  if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }
  if ($arch -ne "AMD64") {
    Write-Fail "Este equipo es Windows $arch. Video Studio AI necesita Windows x64 (el motor de render de Remotion solo existe para x64)."
  }
  $build = [Environment]::OSVersion.Version.Build
  if ($build -lt 17763) { Write-Fail "Se necesita Windows 10 versión 1809 o posterior (compilación $build)." }
  # Rutas largas: node_modules tiene rutas profundas. Avisar si el repositorio está muy anidado.
  $long = $false
  try { $long = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -ErrorAction Stop).LongPathsEnabled -eq 1 } catch { }
  if (-not $long -and $Root.Length -gt 80) {
    Write-Host "  !  La carpeta del proyecto tiene una ruta larga ($($Root.Length) caracteres) y Windows no tiene activadas las rutas largas." -ForegroundColor Yellow
    Write-Host "     Si la instalación falla, mueve la carpeta a una ruta corta (p. ej. C:\VideoStudioAI)." -ForegroundColor Yellow
  }
}

function Find-Uv {
  $cmd = Get-Command uv -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  $local = Join-Path $UvDir "uv.exe"
  if (Test-Path $local) { return $local }
  return $null
}

function Install-Uv {
  $asset = $UvAssets["AMD64"]
  $name = $asset[0]; $sha = $asset[1]
  $url = "https://github.com/astral-sh/uv/releases/download/$UvVersion/$name"
  Write-Info "uv no está instalado. Se descargará uv $UvVersion (gestor de Python de Astral, ~18 MB)"
  Write-Info "en $UvDir, verificando su huella SHA-256. No se instala nada en el sistema."
  if (-not (Confirm-Step "¿Descargar uv portátil?")) { Write-Fail "uv es necesario para preparar Python." }
  $tmp = Join-Path ([IO.Path]::GetTempPath()) ("vsa-uv-" + [Guid]::NewGuid().ToString("N"))
  New-Item -ItemType Directory -Path $tmp | Out-Null
  try {
    $zip = Join-Path $tmp $name
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    $got = (Get-FileHash -Algorithm SHA256 -Path $zip).Hash.ToLower()
    if ($got -ne $sha) { Write-Fail "La huella de uv no coincide; descarga descartada." }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
    Get-ChildItem -Path $tmp -Recurse -Include "uv.exe", "uvx.exe" | Copy-Item -Destination $UvDir -Force
  } finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
  }
  Write-Ok "uv $UvVersion instalado en $UvDir"
}

function Initialize-Python([bool]$WithDev = $false) {
  $uv = Find-Uv
  if (-not $uv) { Install-Uv; $uv = Find-Uv }
  if (-not $uv) { Write-Fail "No se encontró uv." }
  $env:VSA_UV = $uv
  $syncArgs = @("sync", "--frozen", "--quiet")
  if (-not $WithDev) { $syncArgs += "--no-dev" }
  if ((Test-Flag "--cuda") -or (Test-Path (Join-Path $DataHome "cuda.enabled"))) { $syncArgs += @("--extra", "cuda") }
  Write-Info "Preparando Python 3.12 y las dependencias del backend (uv sync)..."
  Push-Location $Backend
  try {
    & $uv @syncArgs
    if ($LASTEXITCODE -ne 0) { Write-Fail "uv sync falló. Revisa tu conexión y vuelve a ejecutar el instalador." }
  } finally { Pop-Location }
  Write-Ok "Backend listo (backend\.venv)"
}

function Test-Installed {
  $state = Join-Path $DataHome "install-state.json"
  if (-not (Test-Path $Py) -or -not (Test-Path $state)) { return $false }
  return (Select-String -Path $state -Pattern '"completed_at"' -Quiet)
}

function Invoke-Install {
  Write-Host "Video Studio AI - Community Edition · instalación" -ForegroundColor White
  Test-Platform
  Initialize-Python
  Push-Location $Backend
  try { & $Py -m app.installer @Rest; $code = $LASTEXITCODE } finally { Pop-Location }
  exit $code
}

function Invoke-Launcher($cmd) {
  if (-not (Test-Installed)) {
    Write-Host "Video Studio AI aún no está instalado en este equipo: se ejecuta el instalador." -ForegroundColor White
    Invoke-Install
  }
  Push-Location $Backend
  try { & $Py -m app.launcher $cmd @Rest; $code = $LASTEXITCODE } finally { Pop-Location }
  exit $code
}

function Invoke-Check {
  if (-not (Test-Installed)) { Invoke-Install }
  Initialize-Python $true
  Push-Location $Backend
  try {
    $nodeDir = & $Py -c "from app.services.render_engine import find_node; n=find_node(); print(n.parent if n else '')"
    if ($nodeDir) { $env:PATH = "$nodeDir;$env:PATH" }
    $models = $env:VSA_TEST_MODELS_DIR
    if (-not $models) { $models = Join-Path $DataHome "models" }
    $env:VSA_TEST_MODELS_DIR = $models
    & .venv\Scripts\ruff.exe check app tests run.py migrations; if ($LASTEXITCODE -ne 0) { exit 1 }
    & .venv\Scripts\mypy.exe app; if ($LASTEXITCODE -ne 0) { exit 1 }
    & .venv\Scripts\pytest.exe -q -o addopts= -rs; if ($LASTEXITCODE -ne 0) { exit 1 }
  } finally { Pop-Location }
  Push-Location $Frontend
  try {
    $dist = Join-Path ([IO.Path]::GetTempPath()) "vsa-check-dist"
    npm run typecheck; if ($LASTEXITCODE -ne 0) { exit 1 }
    npm run lint; if ($LASTEXITCODE -ne 0) { exit 1 }
    npx vite build --outDir $dist --emptyOutDir --logLevel error; if ($LASTEXITCODE -ne 0) { exit 1 }
  } finally { Pop-Location }
  Push-Location $Renderer
  try { npx tsc --noEmit; if ($LASTEXITCODE -ne 0) { exit 1 } } finally { Pop-Location }
  Write-Ok "Todas las validaciones superadas"
}

switch ($Command) {
  { $_ -in @("install", "setup") } { Invoke-Install }
  { $_ -in @("start", "stop", "restart", "status", "open", "logs", "doctor") } { Invoke-Launcher $Command }
  "check" { Invoke-Check }
  default { Get-Help $MyInvocation.MyCommand.Path; exit 1 }
}
