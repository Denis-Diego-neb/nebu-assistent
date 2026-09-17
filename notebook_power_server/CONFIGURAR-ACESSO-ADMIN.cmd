@echo off
title Configurar acesso administrativo Nebula
fltmc >nul 2>&1
if errorlevel 1 (
    powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0configurar_openssh.ps1"
echo.
echo Pressione uma tecla para fechar.
pause >nul
