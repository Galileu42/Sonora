@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    call "%~dp0Preparar.cmd"
    if errorlevel 1 exit /b 1
    exit /b 0
)
".venv\Scripts\python.exe" -m pip install --upgrade "yt-dlp[default]"
if errorlevel 1 (
    echo Falha ao atualizar. Confira a conexao e tente novamente.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m yt_dlp --version
pause
