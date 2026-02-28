@echo off
chcp 65001 >nul
title OmniCapital v1.0 - Analisis en Vivo
color 0B

echo.
echo    ================================================================================
echo    ALPHAMAX OMNICAPITAL v1.0 - Analisis de Mercado en Vivo
echo    ================================================================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo    [ERROR] Python no esta instalado
    echo    Por favor instala Python 3.11+ desde https://python.org
    pause
    exit /b 1
)

echo    [OK] Python detectado

:: Crear directorios
if not exist "logs" mkdir logs
if not exist "reports" mkdir reports

:: Obtener fecha y hora para el log
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do (set mytime=%%a%%b)
set LOGFILE=logs\analisis_%mydate%_%mytime%.log

echo.
echo    ================================================================================
echo    INICIANDO ANALISIS DE MERCADO
echo    ================================================================================
echo    Fecha: %date%
echo    Hora: %time%
echo    Log: %LOGFILE%
echo    ================================================================================
echo.

:: Ejecutar analisis
python omnicapital_v1_live.py

:: Verificar resultado
if errorlevel 1 (
    echo.
    echo    ================================================================================
    echo    [ERROR] El analisis fallo
    echo    ================================================================================
    echo    Revisa el log: %LOGFILE%
) else (
    echo.
    echo    ================================================================================
    echo    [OK] ANALISIS COMPLETADO EXITOSAMENTE
    echo    ================================================================================
    echo.
    echo    Resultados guardados en la carpeta 'reports'
)

echo.
pause
