@echo off
rem Video Studio AI - Community Edition: instalador guiado (se puede repetir sin riesgo).
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0videostudio.ps1" install %*
echo.
pause
