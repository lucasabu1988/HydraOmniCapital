#!/usr/bin/env python
"""
HYDRA daily ritual (v9 production).

    python daily.py
    python daily.py --universe sp500
    python daily.py --v9-capital 100000   # first-run capital

Runs the screener, then the v9 instruction CLI when ALGO_VERSION is v9
(or when --v9 is passed). Pine/TradingView paste instructions are parked;
pass --tv-instructions only if you still need that path.
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
    if universe:
        env["UNIVERSE"] = universe

    print(">>> Running full HYDRA screener (this may take a while for UNIVERSE=all)...\n")
    try:
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
    """Parked hybrid path: copy-paste into TradingView (not the v9 production ritual)."""
    watchlist_file = ROOT / "pine" / "watchlist.txt"
    summary_json = ROOT / "pine" / "hydra_last_summary.json"
    summary_txt = ROOT / "pine" / "hydra_last_summary.txt"

    print("\n" + "=" * 70)
    print("===  (PARKED) COPY-PASTE INTO TRADINGVIEW  ===")
    print("=" * 70)

    print("\n1. Watchlist (paste into the 'Watchlist Symbols' input of HYDRA_Screener):")
    if watchlist_file.exists():
        content = watchlist_file.read_text(encoding="utf-8").strip()
        print(f"   {content}")
        print(f"   (from {watchlist_file.relative_to(ROOT)})")
    else:
        print("   (file not found — did the screener run successfully?)")

    print("\n2. Full JSON:")
    print(f"   Open and paste ENTIRE contents into the Pine JSON input:")
    print(f"   {summary_json.relative_to(ROOT)}")

    if summary_txt.exists():
        print(f"\n   (Human-readable: {summary_txt.relative_to(ROOT)})")

    print("\n" + "=" * 70 + "\n")


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
    print(">>> Refreshing current prices for legacy Excel PnL (portfolio_cycles.xlsx)...\n")
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "refresh_current_prices.py"), "--lookback", "10"],
            cwd=ROOT,
        )
        if result.returncode != 0:
            print("[WARN] PnL refresh had issues (you can run it manually later).")
    except Exception as e:
        print(f"[WARN] Could not run refresher: {e}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="HYDRA daily ritual — screener + v9 instruction sheet."
    )
    parser.add_argument(
        "--universe",
        default="all",
        help="Universe to use (all, sp500, nasdaq100, etc.). Default: all",
    )
    parser.add_argument(
        "--refresh-pnl",
        "--pnl",
        action="store_true",
        help="(Legacy) Also refresh prices in portfolio_cycles.xlsx.",
    )
    parser.add_argument(
        "--tv-instructions",
        action="store_true",
        help="(Parked) Print TradingView paste instructions after the screener.",
    )
    parser.add_argument(
        "--no-instructions",
        action="store_true",
        help=argparse.SUPPRESS,  # legacy alias; TV instructions are off by default
    )
    parser.add_argument(
        "--skip-screener",
        action="store_true",
        help="Skip screener (assumes you already ran it); still runs v9 when enabled.",
    )
    parser.add_argument(
        "--v9",
        action="store_true",
        help="After the screener, run the v9 instruction CLI (50/50 T20+ETF). "
        "Also runs automatically if ALGO_VERSION is v9.",
    )
    parser.add_argument(
        "--v9-capital",
        type=float,
        default=None,
        help="USD capital for the first v9 run (passed to portfolio_v9.py --capital).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Pass through to portfolio_v9.py: plan even if preflight hard-fails.",
    )
    parser.add_argument(
        "--note",
        type=str,
        default=None,
        help="Free-text observation appended to today's journal entry (never overwritten).",
    )

    args = parser.parse_args(argv)

    print("HYDRA DAILY RITUAL (v9)")
    print("=======================\n")

    exit_code = 0
    if not args.skip_screener:
        exit_code = run_screener(args.universe)
        if exit_code == 0:
            backup_history_after_run()

    if args.tv_instructions and not args.no_instructions:
        print_tv_instructions()

    if args.refresh_pnl:
        maybe_refresh_pnl(True)

    from config import ALGO_VERSION

    if args.v9 or ALGO_VERSION == "v9":
        print("\n>>> HYDRA v9 instruction CLI...")
        v9_out = None
        try:
            from portfolio_v9 import run as run_v9

            v9_out = run_v9(capital=args.v9_capital, force=args.force)
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

    if exit_code != 0:
        print(f"\n[Note] Screener exited with code {exit_code}. Check output above.")
        return exit_code

    print("Daily ritual complete. Check state/instructions_*.md (and dashboard_v9 if needed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
