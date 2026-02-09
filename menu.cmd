@echo off
title OmniCapital v1.0 - Menu Principal
cls

echo.
echo    ================================================================================
echo    ALPHAMAX OMNICAPITAL v1.0 - Menu Principal
echo    ================================================================================
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    echo    [ERROR] Python no esta instalado
    pause
    exit /b 1
)

:: Crear directorios
if not exist logs mkdir logs
if not exist reports mkdir reports
if not exist backtests mkdir backtests

:menu
cls
echo.
echo    ================================================================================
echo    ALPHAMAX OMNICAPITAL v1.0 - Menu
echo    ================================================================================
echo.
echo    [1] Dashboard Web (http://localhost:8501)
echo    [2] Analisis de Mercado
echo    [3] Trading Simulado
echo    [4] Backtest
echo    [5] Ver Reportes
echo    [6] Salir
echo.
echo    ================================================================================
set /p opcion="    Opcion: "

if "%opcion%"=="1" goto dashboard
if "%opcion%"=="2" goto analisis
if "%opcion%"=="3" goto trading
if "%opcion%"=="4" goto backtest
if "%opcion%"=="5" goto reportes
if "%opcion%"=="6" goto salir
goto menu

:dashboard
cls
echo.
echo    Abriendo dashboard...
echo    Presiona Ctrl+C para detener
echo.
python -m streamlit run dashboard.py
pause
goto menu

:analisis
cls
echo.
echo    Ejecutando analisis de mercado...
echo.
python omnicapital_v1_live.py
echo.
pause
goto menu

:trading
cls
echo.
echo    Ejecutando trading simulado...
echo.
python src/main.py --mode live
echo.
pause
goto menu

:backtest
cls
echo.
set /p inicio="Fecha inicio (YYYY-MM-DD): "
set /p fin="Fecha fin (YYYY-MM-DD): "
echo.
echo    Ejecutando backtest...
python src/main.py --mode backtest --start-date %inicio% --end-date %fin%
echo.
pause
goto menu

:reportes
cls
echo.
echo    Reportes disponibles:
dir reports /b
echo.
pause
goto menu

:salir
exit
