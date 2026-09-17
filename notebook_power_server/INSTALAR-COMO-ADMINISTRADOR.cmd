@echo off
title Instalador Nebula Power
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_no_notebook.ps1"
echo.
echo Pressione uma tecla para fechar.
pause >nul
