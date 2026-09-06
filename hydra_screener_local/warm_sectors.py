"""Fill the GICS sector cache for the whole universe with no time budget (TASK-344).

Saves every 50 successful lookups so a crash does not lose the run.
    python warm_sectors.py
    python warm_sectors.py --universe all
"""
from __future__ import annotations

import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import UNIVERSE  # noqa: E402
from data.sectors import SAVE_EVERY, refresh_sector_cache, _load_cache  # noqa: E402
from data.universe import get_universe  # noqa: E402


def _progress(fetched, need, remaining):
    print(f"  cache: {fetched}/{need} resueltos, {remaining} pendientes", flush=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Warm the HYDRA GICS sector cache (no time budget)")
    p.add_argument("--universe", default=None)
    args = p.parse_args(argv)
    uni = args.universe or os.environ.get("UNIVERSE") or UNIVERSE
    tickers = get_universe(universe=uni)
    before = len((_load_cache().get("sectors") or {}))
    print(f"warm_sectors: universo {uni} ({len(tickers)} tickers), cache {before} ya conocidos")
    print(f"  guardado incremental cada {SAVE_EVERY} aciertos, sin presupuesto de tiempo")
    sectors = refresh_sector_cache(tickers, budget_seconds=None, save_every=SAVE_EVERY, on_progress=_progress)
    after = len(sectors)
    print(f"warm_sectors: cache ahora {after} sectores ( +{after - before} )")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
