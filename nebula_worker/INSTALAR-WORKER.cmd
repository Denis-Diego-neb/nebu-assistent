@echo off
title Instalador Nebula MCP Worker
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-NoExit','-File','%~dp0instalar_worker.ps1'"
echo.
echo O instalador foi aberto com permissao de administrador.
echo Acompanhe a janela elevada do PowerShell.
pause >nul
