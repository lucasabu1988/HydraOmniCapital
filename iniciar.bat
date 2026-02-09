@echo off
title OmniCapital v1.0

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python no esta instalado
    echo Por favor instala Python 3.11+ desde https://python.org
    pause
    exit /b 1
)

:: Ejecutar launcher
python launcher.py
