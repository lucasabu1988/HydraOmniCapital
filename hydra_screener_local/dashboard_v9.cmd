@echo off
rem HYDRA v9 dashboard launcher (Windows). Starts dashboard_v9.py minimised if nothing listens on
rem 127.0.0.1:8765, then opens the page in the default browser. Read-only: the dashboard never
rem writes the state or places orders. Point a desktop shortcut at this file.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "if (-not (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) {" ^
  "  New-Item -ItemType Directory -Force -Path 'state' | Out-Null;" ^
  "  Start-Process -FilePath python -ArgumentList 'dashboard_v9.py' -WorkingDirectory '%~dp0' -WindowStyle Minimized" ^
  "    -RedirectStandardOutput 'state\dashboard.log' -RedirectStandardError 'state\dashboard.err.log';" ^
  "  $t = 0; while ($t -lt 20 -and -not (Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue)) { Start-Sleep -Milliseconds 500; $t++ }" ^
  "}"
start "" http://127.0.0.1:8765/
