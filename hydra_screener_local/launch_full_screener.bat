@echo off
cd /d "C:\Users\caslu\Desktop\NuevoProyecto\hydra_screener_local"

REM Full HYDRA run (UNIVERSE=all by default in the script) + automatic hybrid layer:
REM - Updates pine/watchlist.txt (ready for TradingView Pine dashboard)
REM - Sends summary (if DISCORD_WEBHOOK_URL is set in the environment)
REM - Writes pine/hydra_last_summary.json + .txt

"C:\Users\caslu\Desktop\NuevoProyecto\.venv\Scripts\python.exe" run_real_full_sp500.py

echo.
echo [Hybrid] If you want Discord notifications, set the env var before running:
echo   set DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
echo   launch_full_screener.bat
echo.
echo Artifacts for Pine/TradingView:
echo   pine\watchlist.txt
echo   pine\hydra_last_summary.txt
echo   pine\hydra_last_summary.json
pause
