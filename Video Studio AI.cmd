@echo off
rem Video Studio AI - Community Edition: abre el editor (lo instala la primera vez).
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0videostudio.ps1" start
if errorlevel 1 (
  echo.
  echo No se pudo abrir Video Studio AI. Revisa los mensajes de arriba.
  pause
)
