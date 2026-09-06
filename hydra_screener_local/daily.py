#!/usr/bin/env python
"""
HYDRA Daily One-Command Ritual

Run this for the full recommended daily experience:
    python daily.py
    python daily.py --refresh-pnl          # also update live PnL in the Excel tracker
    python daily.py --universe sp500       # smaller/faster run

What it does:
1. Runs the full screener (with hybrid artifacts generation for Pine/TV).
2. Prints extremely clear, copy-paste ready instructions for TradingView.
3. (Optional) Refreshes current prices in portfolio_cycles.xlsx so PnL formulas are live.

After this script finishes you only need to:
- Open TradingView
- Paste two things into the HYDRA_Screener indicator
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Consolas/pipes Windows usan cp1252 por defecto y rompen con flechas/emojis UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent

def run_screener(universe: str = "all") -> int:
    """Run the main screener. Returns the exit code."""
    env = os.environ.copy()
    # Let the user override universe via env if they want, but prefer the flag
    if universe:
        env["UNIVERSE"] = universe

    print(">>> Running full HYDRA screener (this may take a while for UNIVERSE=all)...\n")
    try:
        # Run via the existing entrypoint so all its prints, hybrid calls, cycle logging etc. happen
        result = subprocess.run(
            [sys.executable, str(ROOT / "screener.py")],
            env=env,
            cwd=ROOT,
        )
        return result.returncode
    except KeyboardInterrupt:
        print("\n[Interrupted]")
        return 130
    except Exception as e:
        print(f"[ERROR] Failed to run screener: {e}")
        return 1


def print_tv_instructions():
    """The single most important output of the daily ritual."""
    watchlist_file = ROOT / "pine" / "watchlist.txt"
    summary_json = ROOT / "pine" / "hydra_last_summary.json"
    summary_txt = ROOT / "pine" / "hydra_last_summary.txt"

    print("\n" + "=" * 70)
    print("===  COPY-PASTE THESE TWO THINGS INTO TRADINGVIEW  ===")
    print("=" * 70)

    print("\n1. Watchlist (paste into the 'Watchlist Symbols' input of HYDRA_Screener):")
    if watchlist_file.exists():
        content = watchlist_file.read_text(encoding="utf-8").strip()
        print(f"   {content}")
        print(f"   (from {watchlist_file.relative_to(ROOT)})")
    else:
        print("   (file not found — did the screener run successfully?)")

    print("\n2. Full JSON (RECOMMENDED for exact Rec? + Python values):")
    print(f"   Open this file and paste its ENTIRE contents into the")
    print(f"   'Optional: paste FULL content of pine/hydra_last_summary.json' input:")
    print(f"   {summary_json.relative_to(ROOT)}")

    if summary_txt.exists():
        print(f"\n   (Human-readable version also available: {summary_txt.relative_to(ROOT)})")

    print("\nAfter pasting both:")
    print("   • The table will show Python's exact recommended tickers with correct 'Rec?' flags.")
    print("   • Ranks, composites, strict, and special modes come from the full SPEC run.")
    print("   • Set alerts on the script (e.g. Strict + High Composite).")

    print("\n" + "=" * 70)
    print("Optional next step for live PnL tracking:")
    print("   python refresh_current_prices.py --lookback 5")
    print("=" * 70 + "\n")


def backup_history_after_run():
    """history/ lives on one disk and is the only record of what was recommended. Copy it out.

    Destination: HYDRA_BACKUP_DIR if set, else ../hydra_backups next to the repo. The default is
    on the same disk, which protects against a bad `rm`, not against the disk dying - set the
    env var to a synced or external folder.
    """
    dest = os.environ.get("HYDRA_BACKUP_DIR") or str(ROOT.parent / "hydra_backups")
    try:
        from core.history import backup_history
        path = backup_history(dest, history_dir=str(ROOT / "history"))
    except Exception as e:
        print(f"[WARN] history backup failed: {e}")
        return
    if path:
        print(f"[OK] history backed up -> {path}")
        if not os.environ.get("HYDRA_BACKUP_DIR"):
            print("     (same disk as the repo; set HYDRA_BACKUP_DIR to a synced/external folder)")
            print("     v9 state/ also needs HYDRA_BACKUP_DIR for an off-disk copy (TASK-346)")


def maybe_refresh_pnl(do_refresh: bool):
    if not do_refresh:
        return
    print(">>> Refreshing current prices for live PnL (portfolio_cycles.xlsx)...\n")
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "refresh_current_prices.py"), "--lookback", "10"],
            cwd=ROOT,
        )
        if result.returncode != 0:
            print("[WARN] PnL refresh had issues (you can run it manually later).")
    except Exception as e:
        print(f"[WARN] Could not run refresher: {e}")


def _main(argv=None, runlog=None):
    parser = argparse.ArgumentParser(description="HYDRA Daily Ritual — one command to rule them all.")
    parser.add_argument("--universe", default="all",
                        help="Universe to use (all, sp500, nasdaq100, etc.). Default: all")
    parser.add_argument("--refresh-pnl", "--pnl", action="store_true",
                        help="Also run the price refresher at the end for live PnL in Excel.")
    parser.add_argument("--no-instructions", action="store_true",
                        help="Skip the big TradingView copy-paste instructions (not recommended).")
    parser.add_argument("--skip-screener", action="store_true",
                        help="Only print instructions + optional refresh (assumes you already ran the screener).")
    parser.add_argument("--v9", action="store_true",
                        help="After the screener, run the v9 instruction CLI (50/50 T20+ETF). "
                             "Also runs automatically if ALGO_VERSION is v9.")
    parser.add_argument("--v9-capital", type=float, default=None,
                        help="USD capital for the first v9 run (passed to portfolio_v9.py --capital).")
    parser.add_argument("--force", action="store_true",
                        help="Pass through to portfolio_v9.py: plan even if preflight hard-fails.")
    parser.add_argument("--note", type=str, default=None,
                        help="Free-text observation appended to today's journal entry (never overwritten).")

    args = parser.parse_args(argv)

    print("HYDRA DAILY RITUAL")
    print("==================\n")

    exit_code = 0
    if not args.skip_screener:
        exit_code = run_screener(args.universe)
        if exit_code == 0:
            backup_history_after_run()

    if not args.no_instructions:
        print_tv_instructions()

    if args.refresh_pnl:
        maybe_refresh_pnl(True)

    from config import ALGO_VERSION
    if args.v9 or ALGO_VERSION == "v9":
        print("\n>>> HYDRA v9 instruction CLI...")
        v9_out = None
        try:
            from portfolio_v9 import run as run_v9
            v9_out = run_v9(capital=args.v9_capital, force=args.force, runlog=runlog)
        except SystemExit as e:
            print(f"[v9] {e}")
            if exit_code == 0:
                exit_code = 1
            try:
                from journal import append_error
                append_error(str(e), note=args.note)
            except Exception as je:
                print(f"[journal] skip: {je}")
        except Exception as e:
            print(f"[v9] failed: {e}")
            if exit_code == 0:
                exit_code = 1
            try:
                from journal import append_error
                append_error(str(e), note=args.note)
            except Exception as je:
                print(f"[journal] skip: {je}")
        if v9_out is not None and v9_out.get("state") is not None:
            try:
                from journal import append_from_v9
                jpath = append_from_v9(v9_out, note=args.note)
                print(f"[journal] {jpath}")
            except Exception as je:
                print(f"[journal] skip: {je}")

        # PIT snapshots (TASK-362): only after a real run (prices present), never in dry tests.
        if v9_out is not None and v9_out.get("prices") is not None:
            try:
                from snapshot_universe import snapshot_after_run
                for path in snapshot_after_run(args.universe):
                    print(f"[pit] {path}")
            except Exception as pe:
                print(f"[pit] skip: {pe}")

    if exit_code != 0:
        print(f"\n[Note] Screener exited with code {exit_code}. Check output above.")
        return exit_code

    print("Daily ritual complete. Go trade (or at least look at the pretty table in TradingView).")
    return 0


def main(argv=None):
    """Run manifest around the ritual (TASK-359): runs/<stamp>_daily/manifest.json + log.txt."""
    try:
        from utils.runlog import start_run
        ctx = start_run("daily", argv=list(argv) if argv is not None else None)
    except Exception as e:  # the manifest must never stop the ritual
        print(f"[runlog] disabled: {e}")
        return _main(argv)
    rc = 1
    try:
        with ctx:
            rc = _main(argv, runlog=ctx)
            ctx.finish(exit_status=int(rc or 0))
    finally:
        try:
            ctx.close_log()
        except Exception:
            pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
