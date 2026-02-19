@echo off
REM COMPASS v8.2 - Live Trading Startup Script
REM ============================================

echo =======================================
echo  OMNICAPITAL v8.2 COMPASS - STARTING
echo =======================================
echo.

REM Set working directory
cd /d "%~dp0"

REM Create required directories
if not exist "logs" mkdir logs
if not exist "state" mkdir state
if not exist "data_cache" mkdir data_cache

REM Check for kill switch
if exist "STOP_TRADING" (
    echo [WARNING] STOP_TRADING file found. Remove it to start trading.
    pause
    exit /b 1
)

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found in PATH
    pause
    exit /b 1
)

REM Start trading
echo Starting COMPASS v8.2 live trading...
echo Log: logs\compass_live_%date:~-4%%date:~3,2%%date:~0,2%.log
echo.

python omnicapital_live.py 2>&1

echo.
echo Trading stopped.
pause
