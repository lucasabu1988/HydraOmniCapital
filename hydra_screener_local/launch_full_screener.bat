@echo off
cd /d "C:\Users\caslu\Desktop\NuevoProyecto\hydra_screener_local"

REM Full HYDRA run (UNIVERSE=all by default in the script) + automatic hybrid layer:
REM - Updates pine/watchlist.txt (ready for TradingView Pine dashboard)
REM - Sends summary (if DISCORD_* / TELEGRAM_* / GENERIC_* set in env or .env)
REM - Writes pine/hydra_last_summary.json + .txt  (for pasting into HYDRA_Screener.pine)

"C:\Users\caslu\Desktop\NuevoProyecto\.venv\Scripts\python.exe" run_real_full_sp500.py

echo.
echo [Hybrid] For notifications: copy .env.example -> .env and fill, or set before:
echo   set DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
echo   launch_full_screener.bat
echo.
echo Artifacts for Pine/TradingView (paste watchlist + optional full json to i_summary_json):
echo   pine\watchlist.txt
echo   pine\hydra_last_summary.txt
echo   pine\hydra_last_summary.json
pause
