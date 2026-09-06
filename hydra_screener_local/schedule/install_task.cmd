@echo off
REM TASK-364 — register the "HYDRA daily" scheduled task (Mon-Fri 16:45 local) for the current user.
REM Substitutes __SCHEDULE_DIR__ in hydra_daily.xml with this folder and writes the XML as UTF-16
REM (the encoding the template declares), then imports it with schtasks.
setlocal EnableExtensions
set "SCHED=%~dp0"
if not exist "%SCHED%hydra.env" (
    echo [install] WARNING: %SCHED%hydra.env not found. Copy hydra.env.example and fill it in first.
)
set "TMPXML=%TEMP%\hydra_daily_task.xml"
powershell -NoProfile -Command ^
  "$t = Get-Content -Raw -Encoding UTF8 '%SCHED%hydra_daily.xml';" ^
  "$t = $t -replace '__SCHEDULE_DIR__', [regex]::Escape('%SCHED%') -replace '\\\\', '\';" ^
  "Set-Content -Path '%TMPXML%' -Value $t -Encoding Unicode"
if errorlevel 1 exit /b 1
schtasks /Create /TN "HYDRA daily" /XML "%TMPXML%" /F
set "RC=%errorlevel%"
del "%TMPXML%" >nul 2>&1
if "%RC%"=="0" (
    echo [install] "HYDRA daily" registered: Mon-Fri 16:45 local, runs %SCHED%run_daily.cmd
    schtasks /Query /TN "HYDRA daily" /FO LIST | findstr /i "Next Status"
) else (
    echo [install] schtasks failed with %RC%
)
exit /b %RC%
