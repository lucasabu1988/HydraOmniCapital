@echo off
REM TASK-364 — remove the "HYDRA daily" scheduled task.
schtasks /Delete /TN "HYDRA daily" /F
exit /b %errorlevel%
