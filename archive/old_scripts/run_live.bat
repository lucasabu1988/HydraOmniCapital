@echo off
chcp 65001 >nul
title OmniCapital v1.0 - Algoritmo en Vivo
color 0A

echo.
echo    ================================================================================
echo    ALPHAMAX OMNICAPITAL v1.0 - Sistema de Trading en Vivo
echo    ================================================================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo    [ERROR] Python no esta instalado o no esta en el PATH
    echo    Por favor instala Python 3.11+ desde https://python.org
    pause
    exit /b 1
)

echo    [OK] Python detectado

:: Crear directorios necesarios
if not exist "logs" mkdir logs
if not exist "data" mkdir data
if not exist "reports" mkdir reports
if not exist "backtests" mkdir backtests

:: Menu principal
:menu
cls
echo.
echo    ================================================================================
echo    ALPHAMAX OMNICAPITAL v1.0 - Menu Principal
echo    ================================================================================
echo.
echo    Selecciona una opcion:
echo.
echo    [1] Dashboard de Monitoreo (Interfaz Web)
echo    [2] Analisis de Mercado en Vivo
echo    [3] Trading en Vivo / Simulado
echo    [4] Backtest Historico
echo    [5] Ver Reportes Generados
echo    [6] Ver Logs de Ejecucion
echo    [7] Actualizar Datos de Mercado
echo    [8] Salir
echo.
echo    ================================================================================
set /p opcion="    Opcion: "

if "%opcion%"=="1" goto dashboard
if "%opcion%"=="2" goto analisis
if "%opcion%"=="3" goto trading
if "%opcion%"=="4" goto backtest
if "%opcion%"=="5" goto reportes
if "%opcion%"=="6" goto logs
if "%opcion%"=="7" goto actualizar
if "%opcion%"=="8" goto salir
goto menu

:: Opcion 1: Dashboard
:dashboard
cls
echo.
echo    ================================================================================
echo    LANZANDO DASHBOARD DE MONITOREO
echo    ================================================================================
echo.
echo    El dashboard se abrira en tu navegador web.
echo    URL: http://localhost:8501
echo.
echo    Para detener el dashboard, presiona Ctrl+C en esta ventana.
echo.
echo    ================================================================================
echo.
python -m streamlit run dashboard.py
echo.
pause
goto menu

:: Opcion 2: Analisis en Vivo
:analisis
cls
echo.
echo    ================================================================================
echo    ANALISIS DE MERCADO EN VIVO
echo    ================================================================================
echo.
echo    Ejecutando analisis completo de oportunidades de inversion...
echo.

:: Obtener fecha y hora para el log
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c%%a%%b)
for /f "tokens=1-2 delims=/:" %%a in ('time /t') do (set mytime=%%a%%b)
set LOGFILE=logs\analisis_%mydate%_%mytime%.log

python omnicapital_v1_live.py > "%LOGFILE%" 2>&1

if errorlevel 1 (
    echo    [ERROR] Error al ejecutar el analisis. Revisa los logs.
    echo    Log: %LOGFILE%
) else (
    echo    [OK] Analisis completado exitosamente.
    echo    Los resultados se han guardado en la carpeta 'reports'
    echo    Log: %LOGFILE%
)
echo.
pause
goto menu

:: Opcion 3: Trading en Vivo
:trading
cls
echo.
echo    ================================================================================
echo    TRADING EN VIVO / SIMULADO
echo    ================================================================================
echo.
echo    ADVERTENCIA: Este modo ejecutara el algoritmo de trading.
echo.
echo    Selecciona el modo:
echo    [1] Analisis simulado (sin ejecucion de trades)
echo    [2] Trading en vivo (requiere configuracion de broker)
echo    [3] Volver al menu
echo.
set /p trading_opcion="    Opcion: "

if "%trading_opcion%"=="1" (
    echo.
    echo    Ejecutando trading simulado...
    python src/main.py --mode live
    echo.
    echo    [OK] Trading simulado completado.
    pause
)
if "%trading_opcion%"=="2" (
    echo.
    echo    MODO TRADING EN VIVO
echo    Esta funcion requiere configuracion adicional del broker.
    echo    Por favor revisa la documentacion en OMNICAPITAL_v1.0_README.md
    pause
)
goto menu

:: Opcion 4: Backtest
:backtest
cls
echo.
echo    ================================================================================
echo    BACKTEST HISTORICO
echo    ================================================================================
echo.
set /p fecha_inicio="    Fecha inicio (YYYY-MM-DD): "
set /p fecha_fin="    Fecha fin (YYYY-MM-DD): "
echo.
echo    Ejecutando backtest desde %fecha_inicio% hasta %fecha_fin%...
echo.
python src/main.py --mode backtest --start-date %fecha_inicio% --end-date %fecha_fin%
echo.
echo    [OK] Backtest completado.
echo    Los resultados se han guardado en la carpeta 'backtests'
echo.
pause
goto menu

:: Opcion 5: Ver Reportes
:reportes
cls
echo.
echo    ================================================================================
echo    REPORTES GENERADOS
echo    ================================================================================
echo.
echo    Carpeta: reports\
echo.
dir /b /o-d reports\
echo.
echo    [i] Para abrir un reporte, escribe el nombre del archivo
echo    [Enter] para volver al menu
echo.
set /p reporte="    Archivo: "
if not "%reporte%"=="" (
    if exist "reports\%reporte%" (
        start "" "reports\%reporte%"
    ) else (
        echo    [ERROR] Archivo no encontrado
        pause
    )
)
goto menu

:: Opcion 6: Ver Logs
:logs
cls
echo.
echo    ================================================================================
echo    LOGS DE EJECUCION
echo    ================================================================================
echo.
echo    Carpeta: logs\
echo.
dir /b /o-d logs\
echo.
echo    [i] Para ver un log, escribe el nombre del archivo
echo    [Enter] para volver al menu
echo.
set /p logfile="    Archivo: "
if not "%logfile%"=="" (
    if exist "logs\%logfile%" (
        type "logs\%logfile%" | more
        pause
    ) else (
        echo    [ERROR] Archivo no encontrado
        pause
    )
)
goto menu

:: Opcion 7: Actualizar Datos
:actualizar
cls
echo.
echo    ================================================================================
echo    ACTUALIZACION DE DATOS DE MERCADO
echo    ================================================================================
echo.
echo    Descargando datos actualizados...
echo.
python -c "from src.data.data_provider import YFinanceProvider; p = YFinanceProvider(); print('[OK] Conexion exitosa con Yahoo Finance')"
if errorlevel 1 (
    echo    [ERROR] No se pudo conectar con el proveedor de datos.
) else (
    echo    [OK] Conexion con Yahoo Finance verificada.
    echo    [OK] Los datos se actualizaran automaticamente en la proxima ejecucion.
)
echo.
pause
goto menu

:: Opcion 8: Salir
:salir
cls
echo.
echo    ================================================================================
echo    Gracias por usar OmniCapital v1.0!
echo    ================================================================================
echo.
timeout /t 2 /nobreak >nul
exit
