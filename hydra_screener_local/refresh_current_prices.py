#!/usr/bin/env python
"""
Refresh Current Prices for Dynamic PnL Tracking

This script makes the portfolio_cycles.xlsx "live":
- Fetches the latest market close prices for all (or recent) tickers in the tracker.
- Updates the `current_price` column.
- The existing Excel formulas for `pnl_pct` and `pnl_usd` will recalculate automatically when you open the file in Excel.
- Also refreshes the cycle-level PnL snapshots in Cycle_Summaries.

Usage examples:
    python refresh_current_prices.py                  # refresh everything (all cycles)
    python refresh_current_prices.py --lookback 10    # only last 10 cycles (much faster)
    python refresh_current_prices.py --dry-run        # preview what would be updated, no changes
    python refresh_current_prices.py --backup         # create a timestamped backup before modifying

After running, just open backtest/portfolio_cycles.xlsx — the PnL columns are formulas and will update live.

This is especially useful after a live screener run that logged the exact recommended list sent to Pine/TV.
"""

import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path

# Import the real implementation (keeps logic in one place)
try:
    from log_cycle_positions import refresh_current_prices as _do_refresh, EXCEL_PATH as DEFAULT_EXCEL
except ImportError:
    print("ERROR: Could not import from log_cycle_positions.py")
    print("Make sure you run this from the hydra_screener_local directory.")
    raise

def main():
    parser = argparse.ArgumentParser(
        description="Refresh current market prices in portfolio_cycles.xlsx so PnL formulas update live."
    )
    parser.add_argument(
        "--lookback", type=int, default=None, metavar="N",
        help="Only refresh the most recent N cycles (faster for large history). Default: all cycles."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be updated without writing any changes."
    )
    parser.add_argument(
        "--backup", action="store_true",
        help="Create a timestamped backup of the Excel file before modifying it."
    )
    parser.add_argument(
        "--file", type=str, default=None, metavar="PATH",
        help=f"Path to the cycles Excel file (default: {DEFAULT_EXCEL})"
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Reduce output (only show final count)."
    )

    args = parser.parse_args()

    excel_path = args.file or DEFAULT_EXCEL

    if args.backup and os.path.exists(excel_path) and not args.dry_run:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{excel_path}.backup_{ts}"
        shutil.copy2(excel_path, backup_path)
        if not args.quiet:
            print(f"[backup] Created: {backup_path}")

    if args.dry_run:
        if not args.quiet:
            print("[dry-run] Would call refresh with the following parameters:")
            print(f"  excel_path     = {excel_path}")
            print(f"  lookback_cycles= {args.lookback}")
            print("  (No changes will be written)")
        # We still call it but it won't save in dry-run mode? 
        # For simplicity we just describe — the real function always saves.
        # Alternative: temporarily monkey patch save, but better to just inform.
        print("\nDry-run mode: the actual refresh function would now run and save.")
        print("Re-run without --dry-run to apply updates.")
        return 0

    if not args.quiet:
        print(f"[refresh] Starting price refresh for: {excel_path}")
        if args.lookback:
            print(f"[refresh] Limiting to last {args.lookback} cycles...")

    try:
        updated = _do_refresh(
            lookback_cycles=args.lookback,
            excel_path=excel_path
        )
        if not args.quiet:
            print(f"\n[refresh] Done. {updated} position rows received fresh current prices.")
            print("Open the Excel file — the PnL % and PnL $ columns are formulas and will recalculate automatically.")
        return 0
    except Exception as e:
        print(f"[ERROR] Refresh failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
