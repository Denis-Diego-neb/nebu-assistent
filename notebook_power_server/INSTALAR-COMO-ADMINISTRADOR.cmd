@echo off
title Instalador Nebula Power
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process powershell.exe -Verb RunAs -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','%~dp0instalar_no_notebook.ps1'"
echo.
echo O instalador foi aberto com permissao de administrador.
echo Feche esta janela; acompanhe a janela elevada do PowerShell.
pause >nul
