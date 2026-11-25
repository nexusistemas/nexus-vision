@echo off
chcp 65001 >nul
title Nexus Vision — Publicador Oficial de Atualizacoes (NexuSistemas)
setlocal

set "PROJECT_ROOT=%~dp0"
set "PS_SCRIPT=%PROJECT_ROOT%scripts\release_manager.ps1"

if not exist "%PS_SCRIPT%" (
    echo.
    echo [ERRO] Script auxiliar nao encontrado em:
    echo   "%PS_SCRIPT%"
    echo.
    pause
    exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%PS_SCRIPT%" -ProjectRoot "%PROJECT_ROOT%."
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo ========================================================================
    echo   PUBLICACAO INTERROMPIDA COM ERRO ^(Codigo: %EXIT_CODE%^)
    echo   Nenhuma release quebrada foi publicada. Verifique a mensagem acima.
    echo ========================================================================
)

echo.
pause
exit /b %EXIT_CODE%
