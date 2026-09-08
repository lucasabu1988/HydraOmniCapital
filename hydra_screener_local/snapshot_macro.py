"""Record today's Buffett indicator. Phase 1: it observes, it never decides.

    python snapshot_macro.py                 # fetch, record one vintage, print where it sits
    python snapshot_macro.py --dry-run       # fetch and print, write nothing
    python snapshot_macro.py --offline       # only what our own snapshots already say
    python snapshot_macro.py --date 2026-09-08   # stamp the vintage with this date

Named after `snapshot_universe.py`, and like it this is a sidecar: nothing in the live path
imports it, so running it cannot change an order. Wiring the reading into the run log and the
instruction-sheet header is TASK-414, after the settle is verified.

Two series are printed side by side and they are not interchangeable:

  * **revised** - the whole history as FRED reads it today. Good for context, never a
    point-in-time input: GDP is revised for years, so using it as of 2008 is look-ahead.
  * **ours** - the snapshots this script appends, one per run. This is the only series with
    honest vintages, and it starts today with a length of one.

The percentile is expanding (known-up-to-t only) and comes with the number that decides whether
any rule could ever be built on it: how many independent EPISODES the series contains. The gate
is pre-declared at 5 in `core/valuation.py` and on today's data it is not met.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.valuation import describe, enough_episodes_to_decide  # noqa: E402
from data.macro import (  # noqa: E402
    DEFINITION, SNAPSHOT_PATH, append_snapshot, fetch_buffett, load_snapshots, pit_series,
)


PANEL_START = "2004-01-01"          # where experiments/_sweep_cache_oos/close.pkl begins


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Phase 1: record the Buffett indicator, decide nothing")
    ap.add_argument("--dry-run", action="store_true", help="fetch and print, write no snapshot")
    ap.add_argument("--offline", action="store_true", help="no network; report our snapshots only")
    ap.add_argument("--date", default=None, help="YYYY-MM-DD to stamp the vintage with (default: today)")
    ap.add_argument("--force", action="store_true", help="overwrite today's snapshot if it differs")
    ap.add_argument("--json", action="store_true", help="print the record as JSON")
    args = ap.parse_args(argv)

    observed_at = args.date or str(date.today())
    print(DEFINITION, flush=True)

    reading = None if args.offline else fetch_buffett()
    if reading is None and not args.offline:
        print("FRED unavailable; nothing recorded. Our own snapshots below, if any.", flush=True)

    if reading:
        hist = reading["history"]
        d = describe(hist)
        print(f"\nrevised history (NOT point-in-time): {reading['n_quarters']} quarters "
              f"{reading['first_obs_date']} -> {reading['latest_obs_date']}", flush=True)
        print(f"  latest value {reading['latest_value']}  "
              f"percentile among everything known then {d['percentile_as_known']}  "
              f"(min {d['min']}, median {d['median']}, max {d['max']})", flush=True)
        full = enough_episodes_to_decide(hist)
        panel = enough_episodes_to_decide(hist, window_start=PANEL_START)
        print(f"  episodes above the 80th percentile: {full['episodes']} since "
              f"{reading['first_obs_date'][:4]}, but only {panel['episodes']} overlap the "
              f"{PANEL_START[:4]}+ window where a price panel exists", flush=True)
        print(f"  the gate that matters is the second one -> {panel['verdict']}", flush=True)
        if not args.dry_run:
            res = append_snapshot(reading, observed_at)
            print(f"\nsnapshot {observed_at}: {res['reason']} "
                  f"({res['snapshots']} in {os.path.relpath(SNAPSHOT_PATH)})", flush=True)

    ours = pit_series()
    print(f"\nour own vintages: {len(ours)} snapshot(s)", flush=True)
    if ours:
        od = describe(ours)
        print(f"  {min(ours)} -> {max(ours)}, latest {od['value']}, "
              f"percentile-as-known {od['percentile_as_known']} "
              f"(None until there are 8 of them - by design)", flush=True)
    if args.json:
        print(json.dumps({
            "observed_at": observed_at,
            "revised": describe(reading["history"]) if reading else None,
            "ours": describe(ours) if ours else None,
            "snapshots": len(load_snapshots()),
        }, indent=2), flush=True)
    print("\nPhase 1: this number changes no order. Phase 2 is H-008 in .comms/hypotheses.md and "
          "has to pass the episode gate first.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
