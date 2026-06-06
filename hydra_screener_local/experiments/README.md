# Experimental / One-off Scripts

This folder contains various analysis, backtest, logging, and exploration scripts that are **not** part of the core daily flow.

## Core daily commands (use these)
- `python screener.py` or `launch_full_screener.bat` (full run + auto hybrid artifacts for Pine)
- `python run_real_full_sp500.py` (full multi-index "all" runs)
- `python analyze_history.py --export-excel` (performance review + Excel)
- `python track_performance.py` (forward win-rate)

After any of the above, the hybrid artifacts are ready:
  pine/watchlist.txt + full pine/hydra_last_summary.json → paste both into the Pine indicator for exact Rec? + values.

## Scripts here / moved
- backtest_screener_top5_hold5d.py (exact 5/5 backtest)
- log_cycle_positions.py (dynamic PnL tracker for cycles, including the exact hybrid recommended lists sent to TV)
- analysis_experiments.py, comparison_table.py (ad-hoc research)
- run_real_headless.py (plain output variant)

These are useful for deep dives but not needed for daily "run → TV dashboard" use.

If something here becomes core, promote it with docs and main CLI integration.
