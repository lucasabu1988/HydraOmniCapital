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
    import backup_env
    root = backup_env.backup_root()
    dest = str(root) if root is not None else str(ROOT.parent / "hydra_backups")
    try:
        from core.history import backup_history
        path = backup_history(dest, history_dir=str(ROOT / "history"))
    except Exception as e:
        print(f"[WARN] history backup failed: {e}")
        return
    if path:
        print(f"[OK] history backed up -> {path}")
        if root is None:
            print("     (same disk as the repo; set HYDRA_BACKUP_DIR to a synced/external folder)")
            print("     v9 state/ also needs HYDRA_BACKUP_DIR for an off-disk copy (TASK-346)")


# --------------------------------------------------------------------------- the backup seam

def live_source_roots() -> tuple:
    """The tree this entry point is AUTHORISED to publish off disk (TASK-392/394).

    The backup service copies a file only if it resolves under one of these roots. This is the
    whole of the provenance policy and it is deliberately a function, not a heuristic: the
    rejected branch tried to recognise temporary LOCATIONS instead, and a fixture under a custom
    `--basetemp` was copied anyway. Here a fixture that nobody declared is simply not authorised,
    so a test that forgets to declare its root publishes NOTHING rather than publishing into the
    operator's real backup root. Tests that do want to exercise a publication monkeypatch this.
    """
    return (ROOT.resolve(),)


def build_backup_context(date: str, profile: str = "sheet_only"):
    """ENTRY POINT: one of the three places allowed to resolve HYDRA_BACKUP_DIR (backup_env).

    Returns a BackupContext or None. One context per execution, so the state, both sheets and the
    journal all carry the same run_id — that is what makes them a verifiable generation rather
    than four files that happen to share a directory.
    """
    import backup_env
    from backup_service import ExecutionMode
    try:
        return backup_env.context_from_env(
            date=date, profile=profile, allowed_source_roots=live_source_roots(),
            mode=ExecutionMode.LIVE,
        )
    except Exception as e:
        print(f"[backup] context unavailable: {e}")
        return None


def record_run_status(state_path, status: str, detail: str | None = None,
                      today: str | None = None):
    """Leave a machine-readable marker next to the state saying how the run ended.

    A printed traceback is not a record. Best-effort: if this write fails the caller still returns
    non-zero, so a run is never reported complete on the strength of a print alone.
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


def finalize_run(v9_out: dict, note: str | None = None) -> tuple[bool, str | None]:
    """Write the journal locally, then publish the COMPLETE generation exactly once.

    Order is the fix for defect 4 of the rejected branch: there, `append_from_v9` copied the
    journal off disk through `journal.save_record`'s ambient env read, `copy_state_off_disk` had
    already copied the state, and the verification ran last — so a rejection could not undo what
    had been overwritten. Here nothing is off disk until every role of the run exists locally,
    and then the whole set is published in one indivisible operation under one run_id.

    Returns (ok, detail). ok=False makes the daily run INCOMPLETE and non-zero.
    """
    from journal import append_from_v9

    jpath = Path(append_from_v9(v9_out, note=note))
    print(f"[journal] {jpath}")

    ctx = v9_out.get("backup_context")
    if ctx is None:
        import backup_env
        return True, backup_env.unset_message()

    files = [Path(p) for p in (v9_out.get("backup_files") or [])] + [jpath]
    md = jpath.parent / "JOURNAL.md"
    if md.exists():
        files.append(md)

    from backup_service import BackupRefused, publish_generation, verify_generation
    try:
        result = publish_generation(ctx.with_profile("daily_v9"), files)
    except BackupRefused as e:
        return False, f"backup refused ({e.code}): {e.message}"
    bad = [f for f in verify_generation(result["generation_dir"], require_profile="daily_v9")
           if f.level == "ERROR"]
    if bad:
        return False, "published generation did not verify: " + "; ".join(
            f"{f.code} {f.message}" for f in bad)
    print(f"[backup] generation {result['run_id']} -> {result['generation_dir']} "
          f"({len(result['names'])} file(s), all roles present)")
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
        # The context is built HERE, before the CLI knows which bar it will run on; run() re-keys
        # the same run_id to the real trading date. publish_backup=False because this entry point
        # owns publication: the journal does not exist yet and a generation is published whole.
        ctx = build_backup_context(datetime.now().strftime("%Y-%m-%d"))
        try:
            from portfolio_v9 import run as run_v9
            v9_out = run_v9(capital=args.v9_capital, force=args.force,
                            backup_context=ctx, publish_backup=False)
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
            # A journal that does not land, or a generation missing one of its required roles,
            # makes the run INCOMPLETE. Printing the exception and finishing 0 let a run complete
            # having recorded nothing.
            ok, detail = False, None
            try:
                ok, detail = finalize_run(v9_out, note=args.note)
            except Exception as je:
                ok, detail = False, f"journal write failed: {je}"
            if ok:
                if detail:
                    print(f"[journal] WARN {detail}")
                record_run_status(v9_out.get("state_path"), "complete", detail, v9_out.get("today"))
            else:
                print(f"[journal] INCOMPLETE — {detail}")
                record_run_status(v9_out.get("state_path"), "incomplete", detail,
                                  v9_out.get("today"))
                if exit_code == 0:
                    exit_code = 1

    if exit_code != 0:
        print(f"\n[Note] Screener exited with code {exit_code}. Check output above.")
        return exit_code

    print("Daily ritual complete. Go trade (or at least look at the pretty table in TradingView).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
