# HYDRA Hybrid Flow (Python + TradingView)

This document describes the complete hybrid architecture:

- **Python side** (heavy lifter): full universe scan (SP500+Nasdaq+Russell ~2500+ tickers), full HYDRA scoring per SPEC, persistence (history + backtest + tracking), dynamic recommended list.
- **Pine Script side** (lightweight on TV): per-symbol scoring + nice dashboard table for a user watchlist. Accurate visuals, strict filter, regime, pillars, special modes.
- **Integration layer**: automatic generation of the watchlist string + rich daily summary (with optional Discord webhook).

## Daily Workflow

1. Run the screener (full universe recommended):
   ```bash
   python screener.py
   # or via .bat
   launch_full_screener.bat
   ```

   At the end of `screener.py` (see integration points), it automatically:
   - Calls `generate_pine_watchlist.run_feeder(...)` → updates `pine/watchlist.txt`
   - Calls `send_hydra_summary.run_sender(...)` → prints rich summary + writes `pine/hydra_last_summary.json` and `.txt`
   - If `DISCORD_WEBHOOK_URL` env var is set, sends the summary to Discord.

2. (Optional but recommended) Review the artifacts:
   - `pine/watchlist.txt` — ready to paste
   - `pine/hydra_last_summary.txt` — human readable
   - `pine/hydra_last_summary.json` — for bots/other tools

3. In TradingView:
   - Edit the indicator `HYDRA_Screener [Hybrid v1.2]` (from `pine/HYDRA_Screener.pine`)
   - Paste the content of `pine/watchlist.txt` into the **"Watchlist Symbols (comma separated - paste from Python)"** input.
   - Apply the script to any chart (ideally one from your watchlist, or as a separate "dashboard" chart).
   - The table will show the ranked list with full HYDRA details (composite, momentum, regime, special modes, strict flag, COMPASS multiplier, etc.).
   - Set alerts on the script (e.g. "HYDRA: Strict + Strong Composite") and forward them via TradingView webhooks if desired.

4. Optional: use the summary for alerts
   - The `send_hydra_summary.py` can send to Discord.
   - You can extend it for Telegram, email, or your own bot.
   - The JSON artifact can be consumed by other automation.

## Environment variables for integration

- `DISCORD_WEBHOOK_URL` — if set, `send_hydra_summary.py` will post the daily summary to this channel.

Example (PowerShell):
```powershell
$env:DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."
python screener.py
```

## Files involved in the hybrid layer

- `generate_pine_watchlist.py` — the feeder (can be called standalone or via `run_feeder()`)
- `send_hydra_summary.py` — the summary/notifier (callable via `run_sender()`)
- `screener.py` — main entry; now calls the above automatically at the end of a run (see lines ~157-170)
- `pine/HYDRA_Screener.pine` — the TV side (table + scoring)
- `pine/watchlist.txt` + `pine/hydra_last_summary.*` — artifacts produced daily
- `HYDRA_ALGORITHM_SPEC.md` — the single source of truth for the scoring logic (used by both sides)

## Why this architecture?

- Full 2500+ ticker scan + heavy computation (sector control, full history backtesting, strict volume logic, etc.) is not feasible inside Pine Script due to `security()` limits and execution time.
- Pine is excellent for beautiful per-symbol visuals, tables, and alerts on a focused watchlist.
- The feeder + sender close the loop automatically every day.

See also the main README.md and the SPEC for scoring details.

Happy hunting!
