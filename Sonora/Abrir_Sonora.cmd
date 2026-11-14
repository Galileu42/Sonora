@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" goto preparar
if not exist ".pronto" goto preparar
goto abrir
:preparar
call "%~dp0Preparar.cmd"
if errorlevel 1 exit /b 1
:abrir
if not exist ".atalhos-v2" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Criar_Atalhos.ps1"
    if errorlevel 1 (
        echo Houve um erro ao criar os atalhos. O app ainda pode abrir.
        echo Use Criar_Atalhos.cmd para tentar novamente.
        pause
    )
)
start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0sonora.py"
