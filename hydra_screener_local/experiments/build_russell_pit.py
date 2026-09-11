"""TASK-403 - the Russell PIT panel: everything except the data, which costs 630 USD.

This is the most important open financial question in HYDRA: production trades ~3000 names
(S&P 500 + Nasdaq-100 + Dow + Russell 1000 + Russell 2000, two thirds mid/small) while every
number we can defend is measured on S&P 500 point-in-time. TASK-326 established that no free
source gives honest historical Russell membership WITH delisted prices, and TASK-334 picked the
product that does: Norgate Data US Stocks Platinum, 630 USD/year (Silver and Gold omit delisted
names and historical constituents - that is the trap).

So this module is the half that does not need the subscription: the builder, the guards and the
validation, written against the API documented in TASK-334 and verified end to end against a fake
client in `test_build_russell_pit.py`. Without `norgatedata` installed it prints what to buy and
exits 0. It never invents membership, never falls back to a current-list screen, and refuses to
write a cache that would reintroduce survivorship bias by the back door.

    python experiments/build_russell_pit.py --dry-run     # validate, write nothing
    python experiments/build_russell_pit.py              # build _sweep_cache_russell/

The first real run may need `NorgateClient` adjusted: the wrapper is deliberately three functions
wide so that the fix is one place, and the fake in the test documents the contract it expects.

Guards, each one earned by a defect this repo already paid for:
  * delisted names must be present, or the panel is a survivorship screen (TASK-326).
  * a suffixed delisted symbol is NEVER stripped onto a live ticker (TASK-325).
  * cell coverage is measured and printed with the panel, never assumed (the `close_raw` trap:
    83.6% of cells, and the 538 missing names were exactly the delisted ones).
  * strict mode is the default: a panel that fails a guard is not written at all.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

RUSSELL_CACHE = os.path.join(HERE, "_sweep_cache_russell")
INDEXES = ("Russell 1000", "Russell 2000")
WATCHLIST = "Russell 3000 Current & Past"
MIN_CELL_COVERAGE = 0.80          # priced member-cells / member-cells
MIN_DELISTED_SHARE = 0.20         # delisted names / all names; a Russell panel 2005-2026 has many
PURCHASE_NOTE = (
    "norgatedata is not installed. TASK-403 needs Norgate Data US Stocks Platinum "
    "(630 USD/year, approved by Lucas 2026-09-06, not yet bought): it is the only listed-price "
    "product with historical Russell membership, delisted prices, suffixed entity symbols and a "
    "Python API. Silver and Gold do NOT include delisted names or historical constituents. "
    "After buying: install the Windows updater, then `pip install norgatedata`."
)


class NorgateClient:
    """Three functions wide on purpose. `impl` is the `norgatedata` module or a fake."""

    def __init__(self, impl=None):
        if impl is None:
            impl = self._import()
        self.impl = impl

    @staticmethod
    def _import():
        try:
            import norgatedata  # noqa: F401
        except ImportError as e:
            raise RuntimeError(PURCHASE_NOTE) from e
        return norgatedata

    def symbols(self, watchlist: str = WATCHLIST) -> list[str]:
        return list(self.impl.watchlist_symbols(watchlist))

    def membership(self, symbol: str, index_name: str) -> pd.Series:
        """Boolean series indexed by date: was `symbol` in `index_name` that day."""
        s = self.impl.index_constituent_timeseries(symbol, index_name, format="pandas-dataframe")
        if isinstance(s, pd.DataFrame):
            col = "Index Constituent" if "Index Constituent" in s.columns else s.columns[-1]
            s = s[col]
        return pd.Series(s).astype(bool)

    def prices(self, symbol: str) -> pd.DataFrame:
        """Columns Open/Close/Volume plus an adjusted close, indexed by date."""
        df = self.impl.price_timeseries(symbol, format="pandas-dataframe")
        return pd.DataFrame(df)


def is_delisted_symbol(symbol: str) -> bool:
    """Norgate marks a dead entity with a -YYYYMM suffix, e.g. AABA-201910."""
    if "-" not in symbol:
        return False
    tail = symbol.rsplit("-", 1)[-1]
    return tail.isdigit() and len(tail) == 6


def assert_no_suffix_collision(symbols) -> None:
    """TASK-325: never strip a delisted suffix onto a live ticker. Stripping AABA-201910 to AABA
    silently glues a dead company's history onto whatever trades under that ticker today."""
    live = {s for s in symbols if not is_delisted_symbol(s)}
    collisions = sorted({s for s in symbols
                         if is_delisted_symbol(s) and s.rsplit("-", 1)[0] in live})
    if collisions:
        raise ValueError(
            "delisted symbols whose stripped form is a live ticker: "
            f"{collisions[:10]}{'...' if len(collisions) > 10 else ''}. "
            "Keep the suffix (TASK-325); do not merge them."
        )


def build_membership(client: NorgateClient, symbols, indexes=INDEXES) -> pd.DataFrame:
    """date x symbol boolean: in any of `indexes` that day. Union, because production trades both."""
    cols = {}
    for sym in symbols:
        series = None
        for index_name in indexes:
            try:
                s = client.membership(sym, index_name)
            except Exception:
                continue
            if s is None or not len(s):
                continue
            series = s if series is None else series.reindex(
                series.index.union(s.index)).fillna(False) | s.reindex(
                series.index.union(s.index)).fillna(False)
        if series is not None and bool(series.any()):
            cols[sym] = series.astype(bool)
    if not cols:
        raise ValueError("no membership returned for any symbol: refusing to guess")
    frame = pd.DataFrame(cols).sort_index()
    frame.index = pd.DatetimeIndex(frame.index)
    return frame.fillna(False).astype(bool)


def build_prices(client: NorgateClient, symbols) -> dict:
    """close (adjusted), close_raw (as printed), open, volume - the shapes the lab cache uses."""
    close, raw, opens, volume = {}, {}, {}, {}
    for sym in symbols:
        try:
            df = client.prices(sym)
        except Exception:
            continue
        if df is None or not len(df):
            continue
        df.index = pd.DatetimeIndex(df.index)
        adj_col = next((c for c in ("Adjusted Close", "AdjClose", "Close") if c in df.columns), None)
        if adj_col is None:
            continue
        close[sym] = pd.to_numeric(df[adj_col], errors="coerce")
        if "Close" in df.columns:
            raw[sym] = pd.to_numeric(df["Close"], errors="coerce")
        if "Open" in df.columns:
            opens[sym] = pd.to_numeric(df["Open"], errors="coerce")
        if "Volume" in df.columns:
            volume[sym] = pd.to_numeric(df["Volume"], errors="coerce")
    if not close:
        raise ValueError("no prices returned: refusing to write an empty panel")
    frames = {"close": pd.DataFrame(close).sort_index()}
    for name, d in (("close_raw", raw), ("open", opens), ("volume", volume)):
        frames[name] = pd.DataFrame(d).reindex(frames["close"].index) if d else pd.DataFrame(
            index=frames["close"].index)
    return frames


def coverage(membership: pd.DataFrame, close: pd.DataFrame, is_delisted=None) -> dict:
    """How much of the panel is real. Priced member-cells / member-cells of the **record**.

    TASK-427: the denominator is every column of `membership`, not `close.columns`. A name
    the provider did not return used to vanish from both sides of the fraction (published
    90.64% vs honest 86.97% on the 2026-09-11 EODHD panel). Norgate is unchanged: there
    `close.columns` and the record coincide.

    `is_delisted` decides which names *in the panel* are dead. It defaults to Norgate's
    `-YYYYMM` suffix; EODHD passes `EodhdClient.is_delisted`. Delisted names that never
    arrived are counted in `names_without_prices` / `missing_member_cells`, not as a
    silent 100% `delisted_with_prices`.
    """
    is_delisted = is_delisted or is_delisted_symbol
    # float, not bool: reindex+fillna on bool is the pandas downcast warning.
    m_full = membership.reindex(index=close.index).astype("float64").fillna(0.0) > 0
    member_cells = int(m_full.to_numpy().sum())
    common = [c for c in m_full.columns if c in close.columns]
    if common:
        m_common = m_full.loc[:, common]
        c_common = close.reindex(index=m_full.index, columns=common)
        priced = int((m_common.to_numpy() & c_common.notna().to_numpy()).sum())
    else:
        priced = 0
    missing = [c for c in m_full.columns if c not in close.columns]
    missing_member_cells = int(m_full.loc[:, missing].to_numpy().sum()) if missing else 0
    names = list(close.columns)
    delisted = [s for s in names if is_delisted(s)]
    with_history = [s for s in delisted if close[s].notna().any()]
    return dict(
        member_cells=member_cells,
        priced_member_cells=priced,
        cell_coverage=round(priced / member_cells, 4) if member_cells else 0.0,
        names=len(names),
        names_requested=int(m_full.shape[1]),
        names_without_prices=len(missing),
        missing_member_cells=int(missing_member_cells),
        delisted_names=len(delisted),
        delisted_share=round(len(delisted) / len(names), 4) if names else 0.0,
        delisted_with_prices=len(with_history),
        first=str(close.index[0].date()) if len(close.index) else None,
        last=str(close.index[-1].date()) if len(close.index) else None,
        members_first_day=int(m_full.iloc[0].sum()) if len(m_full.index) else 0,
        members_last_day=int(m_full.iloc[-1].sum()) if len(m_full.index) else 0,
    )


def validate(cov: dict, *, min_coverage=MIN_CELL_COVERAGE,
             min_delisted=MIN_DELISTED_SHARE) -> list[str]:
    """The reasons this panel must not be written. Empty list = it may be."""
    problems = []
    if cov["member_cells"] == 0:
        problems.append("no member-cells at all: membership did not resolve")
    if cov["cell_coverage"] < min_coverage:
        problems.append(
            f"cell coverage {cov['cell_coverage']:.1%} < {min_coverage:.0%}: too many member-days "
            f"have no price, so eligibility would silently drop real members"
        )
    if cov["delisted_names"] == 0:
        problems.append(
            "no delisted symbols: this is a current-list screen, not a PIT panel (TASK-326)"
        )
    elif cov["delisted_share"] < min_delisted:
        problems.append(
            f"delisted share {cov['delisted_share']:.1%} < {min_delisted:.0%}: a Russell panel "
            f"spanning two decades cannot have this few dead names"
        )
    if cov["delisted_names"] and cov["delisted_with_prices"] < cov["delisted_names"]:
        problems.append(
            f"{cov['delisted_names'] - cov['delisted_with_prices']} delisted symbol(s) have no "
            f"price history: survivorship would come back through the eligibility mask"
        )
    return problems


def write_cache(frames: dict, membership: pd.DataFrame, cov: dict, out_dir=RUSSELL_CACHE) -> str:
    os.makedirs(out_dir, exist_ok=True)
    for name, df in frames.items():
        pd.to_pickle(df, os.path.join(out_dir, f"{name}.pkl"))
    pd.to_pickle(membership, os.path.join(out_dir, "membership.pkl"))
    with open(os.path.join(out_dir, "coverage.json"), "w", encoding="utf-8") as f:
        json.dump(cov, f, indent=2)
    return out_dir


def rewrite_coverage(out_dir=RUSSELL_CACHE, is_delisted=None) -> dict:
    """Recompute coverage.json from the written pkl files. No network (TASK-427)."""
    close = pd.read_pickle(os.path.join(out_dir, "close.pkl"))
    membership = pd.read_pickle(os.path.join(out_dir, "membership.pkl"))
    cov = coverage(membership, close, is_delisted)
    path = os.path.join(out_dir, "coverage.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cov, f, indent=2)
    return cov


def build(client, *, strict=True, dry_run=False, out_dir=RUSSELL_CACHE,
          symbols=None) -> dict:
    """Any client three functions wide: `NorgateClient`, or `EodhdClient` (TASK-403).

    Two hooks are optional, and a client that lacks them behaves exactly as before:
    `is_delisted(symbol)` replaces the suffix rule, and `identity_problems(close)` adds
    provider-specific reasons a panel must not be written (EODHD: a reused ticker is two
    companies in one column).
    """
    syms = list(symbols) if symbols is not None else client.symbols()
    assert_no_suffix_collision(syms)
    membership = build_membership(client, syms)
    frames = build_prices(client, syms)
    cov = coverage(membership, frames["close"], getattr(client, "is_delisted", None))
    problems = validate(cov)
    identity = getattr(client, "identity_problems", None)
    if identity is not None:
        problems = problems + list(identity(frames["close"]))
    out = dict(coverage=cov, problems=problems, written=None, symbols=len(syms))
    if problems and strict:
        return out
    if not dry_run:
        out["written"] = write_cache(frames, membership, cov, out_dir)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TASK-403: build the Russell PIT panel")
    ap.add_argument("--dry-run", action="store_true", help="validate and print, write nothing")
    ap.add_argument("--no-strict", action="store_true",
                    help="write even if a guard fails (say why in the board entry)")
    ap.add_argument("--out", default=RUSSELL_CACHE)
    ap.add_argument("--source", choices=("norgate", "eodhd"), default="eodhd",
                    help="eodhd: membership from the free record, prices from EODHD All World "
                         "(bought 2026-09-11). norgate: needs the 630 USD/yr subscription.")
    ap.add_argument("--membership", default=None,
                    help="eodhd: the dated record CSV (default: the one russell_free_membership.py writes)")
    ap.add_argument("--start", default=None, help="eodhd: first bar to request (default 2005-01-01)")
    ap.add_argument("--end", default=None, help="eodhd: last bar to request (default: today)")
    ap.add_argument("--limit", type=int, default=None,
                    help="build over the first N member names only - a bounded probe, not a panel")
    ap.add_argument("--rewrite-coverage", action="store_true",
                    help="TASK-427: recompute coverage.json from the pkl cache, no EODHD calls")
    args = ap.parse_args(argv)

    if args.rewrite_coverage:
        is_delisted = None
        if args.source == "eodhd":
            from data.providers.eodhd_provider import EODHDProvider
            from eodhd_pit_client import EodhdClient
            try:
                is_delisted = EodhdClient(EODHDProvider()).is_delisted
            except (FileNotFoundError, RuntimeError) as e:
                print("SKIP is_delisted:", e, flush=True)
        cov = rewrite_coverage(args.out, is_delisted)
        print(json.dumps(cov, indent=2), flush=True)
        print("rewrote", os.path.join(args.out, "coverage.json"), flush=True)
        problems = validate(cov)
        if problems:
            print("GUARDS FAILED:", flush=True)
            for p in problems:
                print("  -", p, flush=True)
            return 1 if not args.no_strict else 0
        return 0

    symbols = None
    if args.source == "eodhd":
        from data.providers.eodhd_provider import EODHDProvider
        from eodhd_pit_client import PANEL_START, EodhdClient
        try:
            client = EodhdClient(EODHDProvider(), args.membership,
                                 start=args.start or PANEL_START, end=args.end)
        except (FileNotFoundError, RuntimeError) as e:
            print("SKIP:", e)
            return 0
    else:
        try:
            client = NorgateClient()
        except RuntimeError as e:
            print("SKIP:", e)
            return 0
    if args.limit:
        symbols = client.symbols()[:int(args.limit)]
        print(f"BOUNDED PROBE: {len(symbols)} of {len(client.symbols())} names — the guards below "
              f"judge this subset, not the panel", flush=True)
    out = build(client, strict=not args.no_strict, dry_run=args.dry_run, out_dir=args.out,
                symbols=symbols)
    print(json.dumps(out["coverage"], indent=2), flush=True)
    if out["problems"]:
        print("", flush=True)
        print("PANEL REJECTED:" if not args.no_strict else "GUARDS FAILED (written anyway):",
              flush=True)
        for p in out["problems"]:
            print("  -", p, flush=True)
        if not args.no_strict:
            return 1
    print("wrote", out["written"] if out["written"] else "(nothing: dry run)", flush=True)
    print("Next: the frozen experiment in .comms/prereg-russell-pit-2026-09-08.md - no threshold "
          "moves after seeing the result.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
