@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$script = '%~dp0instalar.ps1'; $process = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File ""{0}""' -f $script); exit $process.ExitCode"
set "result=%errorlevel%"
if not "%result%"=="0" echo O instalador encontrou um erro. Confira a mensagem acima.
pause
exit /b %result%
