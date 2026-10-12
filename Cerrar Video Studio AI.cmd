@echo off
rem Video Studio AI - Community Edition: cierra el editor y sus procesos.
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0videostudio.ps1" stop
timeout /t 3 >nul
