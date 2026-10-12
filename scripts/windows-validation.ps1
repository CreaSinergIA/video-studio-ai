#Requires -Version 5.1
<#
  Video Studio AI - Community Edition: validación en un equipo Windows REAL.

  Ejecutar en PowerShell desde la raíz del repositorio:
      powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows-validation.ps1

  Qué hace (todo en una carpeta de datos AISLADA; no toca una instalación existente):
    1. Datos del equipo (Windows, CPU, memoria, GPU).
    2. Instalación nueva con el instalador real (--yes, modelo ligero fw-small, sin accesos directos).
    3. Diagnóstico (doctor).
    4. Validaciones del proyecto (lint, tipos, pruebas del backend, compilación del panel).
    5. Prueba de punta a punta (scripts\smoke_e2e.py): arranque, token, primera configuración,
       transcripción real con faster-whisper, Claude con API SIMULADA (sin cargos), los 3 estilos
       con Remotion real, vista previa, regeneración de escena, exportación, reinicio y cierre.
    6. Comprobaciones manuales guiadas (ventanas, accesos directos, llavero, selector de carpetas).
  Al final deja un informe en %TEMP%\vsa-validation-<fecha>\ para enviarlo al mantenedor.

  Opciones: -SkipCheck (omite el paso 4), -SkipManual (omite el paso 6), -WithCuda (complemento NVIDIA).
#>
param([switch]$SkipCheck, [switch]$SkipManual, [switch]$WithCuda)
$ErrorActionPreference = "Continue"
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Out = Join-Path $env:TEMP "vsa-validation-$Stamp"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
$env:VSA_HOME = Join-Path $Out "home"
$env:VSA_NO_BROWSER = "1"
$Results = [ordered]@{}

function Step($name, [scriptblock]$body) {
  Write-Host "`n== $name" -ForegroundColor White
  $t = Get-Date
  try {
    & $body
    $ok = ($LASTEXITCODE -eq 0 -or $null -eq $LASTEXITCODE)
  } catch { Write-Host $_ -ForegroundColor Red; $ok = $false }
  $Results[$name] = [ordered]@{ ok = $ok; seconds = [int]((Get-Date) - $t).TotalSeconds }
  if ($ok) { Write-Host "   [ok] $name" -ForegroundColor Green } else { Write-Host "   [x] $name" -ForegroundColor Red }
}

Step "1. Datos del equipo" {
  $os = Get-CimInstance Win32_OperatingSystem
  $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
  $gpu = Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }
  $info = [ordered]@{
    windows = "$($os.Caption) $($os.Version) (compilación $($os.BuildNumber))"
    arquitectura = $env:PROCESSOR_ARCHITECTURE
    cpu = $cpu.Name
    nucleos = $cpu.NumberOfCores
    memoria_gb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
    gpu = $gpu
    rutas_largas = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled
    repositorio = $Root
  }
  $info | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Out "equipo.json")
  $info | Format-List | Out-String | Write-Host
  $global:LASTEXITCODE = 0
}

$installArgs = @("install", "--yes", "--no-shortcut", "--no-start", "--model", "fw-small")
if ($WithCuda) { $installArgs += "--cuda" }
Step "2. Instalación nueva" {
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "videostudio.ps1") @installArgs 2>&1 |
    Tee-Object -FilePath (Join-Path $Out "instalacion.log")
}

Step "3. Diagnóstico" {
  & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "videostudio.ps1") doctor 2>&1 |
    Tee-Object -FilePath (Join-Path $Out "diagnostico.log")
}

if (-not $SkipCheck) {
  Step "4. Validaciones del proyecto (pruebas automáticas)" {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Root "videostudio.ps1") check 2>&1 |
      Tee-Object -FilePath (Join-Path $Out "check.log")
  }
}

Step "5. Prueba de punta a punta" {
  $py = Join-Path $Root "backend\.venv\Scripts\python.exe"
  $env:VSA_MODELS_DIR = Join-Path $env:VSA_HOME "models"
  & $py (Join-Path $Root "scripts\smoke_e2e.py") --model fw-small --models-dir $env:VSA_MODELS_DIR `
    --engines-dir (Join-Path $env:VSA_HOME "engines") --report (Join-Path $Out "smoke.json") 2>&1 |
    Tee-Object -FilePath (Join-Path $Out "smoke.log")
  Remove-Item Env:\VSA_MODELS_DIR -ErrorAction SilentlyContinue
}

if (-not $SkipManual) {
  Step "6. Comprobaciones manuales" {
    $answers = [ordered]@{}
    $vs = Join-Path $Root "videostudio.ps1"
    Remove-Item Env:\VSA_NO_BROWSER -ErrorAction SilentlyContinue
    & powershell -NoProfile -ExecutionPolicy Bypass -File $vs start | Out-Host
    $answers["panel_se_abre_en_el_navegador"] = Read-Host "¿Se abrió el panel en el navegador sin errores? (s/n)"
    $answers["asistente_primera_configuracion"] = Read-Host "¿Aparece «Primera configuración» y puedes avanzar por los pasos? (s/n)"
    $answers["selector_de_carpetas"] = Read-Host "En el paso 1, ¿«Elegir en el Explorador» abre el selector de carpetas de Windows? (s/n)"
    $answers["clave_en_credenciales"] = Read-Host "Guarda una clave de prueba (sk-ant-test-0123456789abcdef). ¿Aparece «VideoStudioAI-Community» en Panel de control > Administrador de credenciales > Credenciales de Windows? (s/n)"
    $answers["mostrar_en_explorador"] = Read-Host "En un proyecto, ¿«Mostrar en el Explorador» abre la carpeta? (s/n)"
    & powershell -NoProfile -ExecutionPolicy Bypass -File $vs start | Out-Host
    $answers["segunda_apertura_reutiliza"] = Read-Host "Al lanzar de nuevo, ¿dice «Ya está en marcha» y no abre otro servidor? (s/n)"
    & powershell -NoProfile -ExecutionPolicy Bypass -File $vs stop | Out-Host
    $left = Get-Process -Name python, node, ffmpeg, "chrome-headless-shell" -ErrorAction SilentlyContinue |
      Where-Object { $_.Path -and ($_.Path -like "$Root*" -or $_.Path -like "$($env:VSA_HOME)*") }
    $answers["procesos_tras_cerrar"] = @($left | ForEach-Object { "$($_.Name) $($_.Id)" })
    $answers | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $Out "manual.json")
    $global:LASTEXITCODE = 0
  }
}

Copy-Item -Recurse -Force (Join-Path $env:VSA_HOME "logs") (Join-Path $Out "logs") -ErrorAction SilentlyContinue
Copy-Item -Force (Join-Path $env:VSA_HOME "install-state.json") $Out -ErrorAction SilentlyContinue
$Results | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $Out "resumen.json")
Write-Host "`nInforme en: $Out" -ForegroundColor Cyan
Write-Host "Envía esa carpeta (sin claves reales) al mantenedor. No contiene videos personales." -ForegroundColor Cyan
