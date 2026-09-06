#!/usr/bin/env python
"""
Live Watcher for HYDRA (D1)

Monitors the history/ directory for new daily runs.
When a new history JSON appears:
- Triggers send_hydra_summary (Discord/Telegram/generic if configured via .env or env vars)
- Optionally refreshes current prices for live PnL
- Prints a status report

Usage:
    python live_watcher.py                  # check once
    python live_watcher.py --interval 60    # poll every 60 seconds
    python live_watcher.py --once --refresh-pnl
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

try:
    from utils.env import load_hydra_env
    load_hydra_env()
except Exception as e:
    print(f"[WARN] .env loader skipped: {e}")

import send_hydra_summary
from generate_pine_watchlist import find_latest_history

HISTORY_DIR = Path("history")
EXCEL_PATH = Path("backtest/portfolio_cycles.xlsx")

def find_latest_history_date():
    try:
        latest_path = find_latest_history(HISTORY_DIR)
        if latest_path and latest_path.exists():
            with open(latest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            date = data.get("date")
            return date, latest_path
    except Exception:
        pass
    return None, None

def trigger_hybrid_layer():
    print("[Watcher] Triggering hybrid sender...")
    try:
        send_hydra_summary.run_sender(top_n=15, silent=True)
        print("[Watcher] Sender completed (webhooks sent if configured).")
    except Exception as e:
        print(f"[Watcher][ERROR] Sender failed: {e}")

def refresh_pnl_if_possible():
    print("[Watcher] Refreshing PnL (if possible)...")
    try:
        from log_cycle_positions import refresh_current_prices
        n = refresh_current_prices(lookback_cycles=10)
        print(f"[Watcher] PnL refresh updated {n} rows.")
    except Exception as e:
        print(f"[Watcher][WARN] PnL refresh skipped: {e}")

def print_status_report(date: str, history_path: Path):
    print("\n" + "=" * 60)
    print(f"HYDRA LIVE STATUS - {datetime.now().isoformat(timespec='seconds')}")
    print(f"Latest run: {date}")
    print(f"History: {history_path}")
    print("Artifacts: pine/watchlist.txt + pine/hydra_last_summary.json")
    if EXCEL_PATH.exists():
        print(f"PnL tracker: {EXCEL_PATH} (run refresh_current_prices.py for live updates)")
    print("Webhooks (if .env configured): triggered via sender")
    print("=" * 60 + "\n")

def main():
    parser = argparse.ArgumentParser(description="HYDRA Live Watcher (monitors history/ for new runs)")
    parser.add_argument("--interval", type=int, default=0, help="Poll interval in seconds (0 = once)")
    parser.add_argument("--refresh-pnl", action="store_true", help="Also refresh PnL")
    parser.add_argument("--once", action="store_true", help="Single check")
    args = parser.parse_args()

    interval = 0 if args.once else args.interval

    print("HYDRA Live Watcher started.")
    if interval > 0:
        print(f"Polling every {interval}s. Press Ctrl+C to stop.")
    else:
        print("Single check mode.")

    last_seen_date = None

    try:
        while True:
            date, path = find_latest_history_date()
            if date and date != last_seen_date:
                print(f"[Watcher] New run detected: {date}")
                trigger_hybrid_layer()
                if args.refresh_pnl:
                    refresh_pnl_if_possible()
                print_status_report(date, path)
                last_seen_date = date
            else:
                if interval <= 0:
                    print("[Watcher] No new run (or first check).")
                    break

            if interval > 0:
                time.sleep(interval)
            else:
                break
    except KeyboardInterrupt:
        print("\n[Watcher] Stopped by user.")
    except Exception as e:
        print(f"[Watcher][FATAL] {e}")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
