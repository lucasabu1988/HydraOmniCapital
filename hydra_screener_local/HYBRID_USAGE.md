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
   - `pine/watchlist.txt` — ready to paste into Pine watchlist input
   - `pine/hydra_last_summary.txt` — human readable (pillars, rationale, top with strict flags)
   - `pine/hydra_last_summary.json` — full machine data (regime, pillars, rationale, top_details with composites/strict/special per ticker). Paste *full* into Pine's i_summary_json input for:
     * global header labels on chart (rationale + pillars + regime)
     * per-row table enrichment (exact Python Comp/Mom/Strict/Special override the local approximations for those symbols)

3. In TradingView:
   - Edit the indicator `HYDRA_Screener [Hybrid v1.2]` (from `pine/HYDRA_Screener.pine`)
   - Paste the content of `pine/watchlist.txt` into the **"Watchlist Symbols (comma separated - paste from Python)"** input.
   - (Recommended for fidelity) Also paste the *full contents* of `pine/hydra_last_summary.json` into the **"Optional: paste FULL content of ... hydra_last_summary.json"** input.
   - Apply the script to any chart (ideally one from your watchlist, or as a separate "dashboard" chart).
   - The table will show the ranked list with **exact Rec? flags** from Python's `recommended_tickers` list (plus composites/strict/specials from top_details). Local calc is only fallback. Global labels include Python regime/pillars/rationale + recommended count.
   - Set alerts on the script (e.g. "HYDRA: Strict + Strong Composite") and forward them via TradingView webhooks if desired.

4. Optional: use the summary for alerts
   - The `send_hydra_summary.py` can send to Discord.
   - You can extend it for Telegram, email, or your own bot.
   - The JSON artifact can be consumed by other automation.

## Environment variables for integration

- `DISCORD_WEBHOOK_URL` (or `HYDRA_DISCORD_WEBHOOK`) — daily summary to Discord.
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (or HYDRA_ variants) — daily summary to Telegram.
- `GENERIC_WEBHOOK_URL` (or `HYDRA_GENERIC_WEBHOOK`) — POST the full JSON summary (for your own bots, n8n, Zapier, etc.).

Example (PowerShell one-off):
```powershell
$env:DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."
$env:TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."
$env:TELEGRAM_CHAT_ID = "-1001234567890"
python screener.py
```

### Using .env for persistent config (recommended)
1. Copy: `cp .env.example .env`
2. Edit `.env`, fill the hook(s) you want (supports the names or HYDRA_ prefixed).
3. Just run normally — the loader (in `utils/env.py`) is called early by `screener.py`, `run_real_*.py`, `analyze_history.py`, `track_performance.py`, and `send_hydra_summary.py`. Supports python-dotenv if installed, otherwise a tiny pure-Python parser. No need to `export` vars each time.
4. `.env` ignored by git.

The sender always saves local artifacts (`pine/hydra_last_summary.json` etc.) even if no webhooks configured.

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
