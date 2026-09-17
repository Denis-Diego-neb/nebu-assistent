@echo off
title Servidor Cubbleverse Nebula
echo Iniciando Cubbleverse com ate 6 GB de RAM...
echo Para desligar corretamente, digite stop e pressione Enter.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "C:\NebulaMinecraft\Cubbleverse\start_server.ps1"
echo.
echo O servidor foi encerrado.
pause
