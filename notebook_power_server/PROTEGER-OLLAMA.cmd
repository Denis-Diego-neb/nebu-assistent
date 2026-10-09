@echo off
title Proteger o Ollama do notebook
fltmc >nul 2>&1
if errorlevel 1 (
    powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0proteger_ollama.ps1"
echo.
echo Pressione uma tecla para fechar.
pause >nul
