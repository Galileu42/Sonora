@echo off
setlocal
cd /d "%~dp0"
if not exist ".pronto" (
    call "%~dp0Preparar.cmd"
    if errorlevel 1 exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Criar_Atalhos.ps1"
if errorlevel 1 (
    echo Houve um erro ao criar os atalhos.
    pause
    exit /b 1
)
echo Atalhos criados na area de trabalho e no menu Iniciar.
pause
