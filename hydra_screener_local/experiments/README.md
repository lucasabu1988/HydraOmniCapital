# Experimental / One-off Scripts

This folder contains various analysis, backtest, logging, and exploration scripts that are **not** part of the core daily flow.

## Core daily commands (use these)
- `python screener.py` or `launch_full_screener.bat` (full run + auto hybrid artifacts for Pine)
- `python run_real_full_sp500.py` (full multi-index "all" runs)
- `python analyze_history.py --export-excel` (performance review + Excel)
- `python track_performance.py` (forward win-rate)

After any of the above, the hybrid artifacts are ready:
  pine/watchlist.txt + full pine/hydra_last_summary.json → paste both into the Pine indicator for exact Rec? + values.

## Scripts here (moved for clutter reduction)
- analysis_experiments.py (temporary/ad-hoc research)
- backfill_from_live.py (data backfill experiments)
- backtest_screener_top5_hold5d.py (exact 5/5 backtest using current logic)
- comparison_table.py (ad-hoc comparisons)
- run_real_headless.py (plain-text variant of full runs)
- test_screener_logic.py (additional logic tests; run via run_all_tests.py)

Core utilities (stay in root for easy access):
- daily.py (recommended one-command daily ritual)
- run_all_tests.py (one-command test runner)
- clean_artifacts.py (safe cleanup of generated output/, backtest/ temps, data_cache/, __pycache__ etc.)

Nota: La mayoría de artefactos ya están cubiertos por .gitignore en el nivel del proyecto padre.

These experiment scripts are useful for deep dives/backtests but not needed for daily "run → TV dashboard" use.

If something here becomes core, promote it with docs and main CLI integration.
