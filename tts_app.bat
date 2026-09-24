@echo off
title TTS App
cd /d "%~dp0"

if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0launcher.py"
    exit /b 0
)
if exist "%~dp0venv\Scripts\pythonw.exe" (
    start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0launcher.py"
    exit /b 0
)

start "" pythonw "%~dp0launcher.py" 2>nul || start "" python "%~dp0launcher.py"
exit /b 0
