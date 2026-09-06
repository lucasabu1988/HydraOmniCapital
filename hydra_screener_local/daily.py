#!/usr/bin/env python
"""
HYDRA Daily One-Command Ritual

Run this for the full recommended daily experience:
    python daily.py
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


def _main(argv=None, runlog=None):
    parser = argparse.ArgumentParser(description="HYDRA Daily Ritual — one command to rule them all.")
    parser.add_argument("--universe", default="all",
                        help="Universe to use (all, sp500, nasdaq100, etc.). Default: all")
    parser.add_argument("--no-instructions", action="store_true",
                        help="Skip the big TradingView copy-paste instructions (not recommended).")
    parser.add_argument("--skip-screener", action="store_true",
                        help="Only print instructions (assumes you already ran the screener).")
    parser.add_argument("--v9", action="store_true",
                        help="After the screener, run the v9 instruction CLI (50/50 T20+ETF). "
                             "Also runs automatically if ALGO_VERSION is v9.")
    parser.add_argument("--v9-capital", type=float, default=None,
                        help="USD capital for the first v9 run (passed to portfolio_v9.py --capital).")
    parser.add_argument("--force", action="store_true",
                        help="Pass through to portfolio_v9.py: plan even if preflight hard-fails.")
    parser.add_argument("--note", type=str, default=None,
                        help="Free-text observation appended to today's journal entry (never overwritten).")
    parser.add_argument("--unattended", action="store_true",
                        help="Scheduled run (TASK-364): no prompts, exit 0 ok / 1 screener-only failure / "
                             "2 preflight or schema refused to plan / 3 exception; sends a summary or an "
                             "ALERT through utils.notify (HYDRA_NOTIFY transports; file always).")
    parser.add_argument("--portfolio", type=str, default=None,
                        help="Book from portfolios.toml (TASK-365); default = the live book.")

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

    from config import ALGO_VERSION
    v9_status, v9_message, v9_out = None, "", None
    if args.v9 or ALGO_VERSION == "v9":
        print("\n>>> HYDRA v9 instruction CLI...")
        try:
            from portfolio_v9 import run as run_v9
            v9_out = run_v9(capital=args.v9_capital, force=args.force, runlog=runlog,
                            portfolio=args.portfolio)
            v9_status = "ok"
        except SystemExit as e:
            v9_status, v9_message = "refused", str(e)
            print(f"[v9] {e}")
            if exit_code == 0:
                exit_code = 1
            try:
                from journal import append_error
                append_error(str(e), note=args.note, journal_dir=_journal_dir_for(args.portfolio))
            except Exception as je:
                print(f"[journal] skip: {je}")
        except Exception as e:
            v9_status, v9_message = "error", f"{type(e).__name__}: {e}"
            print(f"[v9] failed: {e}")
            if exit_code == 0:
                exit_code = 1
            try:
                from journal import append_error
                append_error(str(e), note=args.note, journal_dir=_journal_dir_for(args.portfolio))
            except Exception as je:
                print(f"[journal] skip: {je}")
        if v9_out is not None and v9_out.get("state") is not None:
            try:
                from journal import append_from_v9
                jpath = append_from_v9(v9_out, note=args.note, journal_dir=v9_out.get("journal_dir"))
                v9_out["journal_path"] = str(jpath)
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

    if args.unattended:
        return _unattended_exit(v9_status, v9_message, v9_out, exit_code, runlog)

    if exit_code != 0:
        print(f"\n[Note] Screener exited with code {exit_code}. Check output above.")
        return exit_code

    print("Daily ritual complete. Go trade (or at least look at the pretty table in TradingView).")
    return 0


def _journal_dir_for(portfolio: str | None):
    """journal/<name>/ for a named book (TASK-365); None keeps journal/ for the live book."""
    if not portfolio:
        return None
    try:
        from core.portfolios import resolve
        return resolve(portfolio, allow_disabled=True).journal_dir
    except Exception:
        return None


def _unattended_exit(v9_status, v9_message, v9_out, screener_exit, runlog) -> int:
    """TASK-364: exit code + notification for a scheduled run. Never places orders; never raises."""
    import utils.notify as NT
    run_id = None
    if runlog is not None:
        try:
            run_id = Path(runlog.directory).name
        except Exception:
            run_id = None
    today = None
    if isinstance(v9_out, dict):
        today = v9_out.get("today")
    title = f"HYDRA v9 {today or ''}".strip()
    if v9_status == "refused":
        rc = 2
        NT.notify("ALERT", f"{title}: refused to plan", f"{v9_message}\nrun: {run_id}\nNo sheet written; check preflight/state.")
    elif v9_status == "error":
        rc = 3
        NT.notify("ALERT", f"{title}: exception", f"{v9_message}\nrun: {run_id}")
    elif v9_status == "ok":
        rc = 1 if screener_exit else 0
        rows = ((v9_out or {}).get("preflight") or {}).get("rows") if isinstance(v9_out, dict) else None
        body = NT.run_summary(v9_out or {}, preflight_rows=rows, run_id=run_id)
        if screener_exit:
            body += f"\nscreener (Pine artefacts) exited {screener_exit}"
        if isinstance(v9_out, dict) and v9_out.get("sector_warning"):
            NT.notify("WARN", f"{title}: DEGRADED", str(v9_out["sector_warning"]))
        NT.notify("INFO", title, body)
    else:
        rc = 1 if screener_exit else 0
        NT.notify("INFO", "HYDRA daily (v9 not run)", f"screener exit {screener_exit}; run: {run_id}")
    print(f"[unattended] exit {rc}")
    return rc


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
