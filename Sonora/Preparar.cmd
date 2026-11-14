@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Preparar.ps1"
if errorlevel 1 (
    echo.
    echo Falha na preparacao. Leia a mensagem acima e veja o LEIA-ME.txt.
    pause
    exit /b 1
)
echo.
echo Sonora preparado.
