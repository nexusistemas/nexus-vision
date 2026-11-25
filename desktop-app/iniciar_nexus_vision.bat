@echo off
title Nexus Vision — NexuSistemas Tecnologia
cd /d "%~dp0.."
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "desktop-app\main.py"
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "desktop-app\main.py"
) else (
    python "desktop-app\main.py"
)
