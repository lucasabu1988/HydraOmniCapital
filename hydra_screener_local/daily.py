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
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
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


def record_run_status(state_path, status: str, detail: str | None = None,
                      today: str | None = None):
    """Leave a machine-readable marker next to the state saying how the run ended.

    TASK-ASTRA-12: a printed traceback is not a record. Best-effort — if this write fails the
    caller still returns non-zero, so the run is never reported as complete on a print alone.
    """
    if not state_path:
        return None
    try:
        path = Path(state_path).parent / "run_status.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "date": today or datetime.now().strftime("%Y-%m-%d"),
            "status": status,
            "detail": detail,
            "recorded_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)
        return path
    except OSError as e:
        print(f"[run] could not record status: {e}")
        return None


def finalize_journal(v9_out: dict, note: str | None = None) -> tuple[bool, str | None]:
    """Persist the journal, put it in the off-disk copy, and verify that copy is complete.

    Returns (ok, detail). Raising is the caller's cue that nothing was recorded. The journal is
    written after the sheet, so `copy_state_off_disk` cannot have contained it; calling it again
    here is what puts the journal (and JOURNAL.md) under the same backup manifest and lets
    `verify_backup` say whether the run is actually recoverable (TASK-ASTRA-12).
    """
    from journal import append_from_v9

    jpath = Path(append_from_v9(v9_out, note=note))
    print(f"[journal] {jpath}")
    today = str(v9_out.get("today") or datetime.now().strftime("%Y-%m-%d"))
    if not os.environ.get("HYDRA_BACKUP_DIR"):
        return True, "no HYDRA_BACKUP_DIR: journal is on the same disk as the book"
    from portfolio_v9 import copy_state_off_disk
    extra = [jpath]
    md = jpath.parent / "JOURNAL.md"
    if md.exists():
        extra.append(md)
    dest = copy_state_off_disk(today, extra, silent=True)
    if dest is None:
        return False, "off-disk copy of the journal did not run"
    from verify_state import verify_backup
    bad = [f for f in verify_backup(dest) if f.level == "ERROR"]
    if bad:
        return False, "backup incomplete: " + "; ".join(f"{f.code} {f.message}" for f in bad)
    return True, None


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


def main(argv=None):
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
            # A journal that does not land, or a backup missing one of its required roles, makes
            # the run INCOMPLETE. Printing the exception and finishing 0 let a run complete having
            # recorded nothing (TASK-ASTRA-12).
            ok, detail = False, None
            try:
                ok, detail = finalize_journal(v9_out, note=args.note)
            except Exception as je:
                ok, detail = False, f"journal write failed: {je}"
            if ok:
                if detail:
                    print(f"[journal] WARN {detail}")
                record_run_status(v9_out.get("state_path"), "complete", detail, v9_out.get("today"))
            else:
                print(f"[journal] INCOMPLETE — {detail}")
                record_run_status(v9_out.get("state_path"), "incomplete", detail, v9_out.get("today"))
                if exit_code == 0:
                    exit_code = 1

    if exit_code != 0:
        print(f"\n[Note] Screener exited with code {exit_code}. Check output above.")
        return exit_code

    print("Daily ritual complete. Go trade (or at least look at the pretty table in TradingView).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
