@echo off
REM TASK-364 — scheduled HYDRA daily ritual (unattended). Never places orders.
REM Loads schedule\hydra.env (KEY=VALUE lines), runs daily.py --v9 --unattended, logs to logs\daily_<yyyymmdd>.log.
setlocal EnableExtensions
set "SCHED=%~dp0"
set "REPO=%SCHED%.."
pushd "%REPO%" || exit /b 3

if exist "%SCHED%hydra.env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%a in ("%SCHED%hydra.env") do (
        if not "%%a"=="" set "%%a=%%b"
    )
) else (
    echo [run_daily] schedule\hydra.env not found; using the current environment
)
if "%PYTHON%"=="" set "PYTHON=python"

if not exist logs mkdir logs
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd"') do set "STAMP=%%i"
set "LOG=logs\daily_%STAMP%.log"

echo ===== %date% %time% run_daily start ===== >> "%LOG%"
"%PYTHON%" daily.py --v9 --unattended >> "%LOG%" 2>&1
set "RC=%errorlevel%"
echo ===== %date% %time% run_daily exit %RC% ===== >> "%LOG%"
popd
exit /b %RC%
