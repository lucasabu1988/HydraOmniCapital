"""TASK-406 companion - build the dollar-ADV panel that fill_cost_report.py asks for.

`fill_cost_report.py --adv-pickle PATH` wants a date x ticker DataFrame of DOLLAR volume and,
for each fill, takes the last value on or before the execution date. Nobody had built that panel,
so its `adv_bucket` column came out empty. This is the builder, and nothing more: it reads a lab
cache (`close.pkl`, `volume.pkl`) and writes `adv_usd.pkl` next to them.

The definition is not a new one. It is the same line the redesign lab already runs as `P.ADV_USD`
(`experiments/redesign_lab.py`): `(close * volume).rolling(20).mean()`. Two definitions of ADV in
one repo would be a bug waiting to be quoted, so this script matches that one and takes the window
from the CLI instead of hardcoding a second constant.

What the number is NOT:

  * NOT a point-in-time liquidity estimate for the production universe. These caches are S&P 500
    PIT (1209 tickers); production trades a Russell-heavy universe of ~3000 names, so a live
    ticker can simply be absent. `--report-tickers` exists to measure that gap, not to hide it.
  * NOT dividend/split-naive: `close.pkl` is the ADJUSTED close, so a pre-split dollar volume is
    stated in today's share terms. For an ORDER$ / ADV$ ratio that is harmless (both legs are
    dollars) but it is not the tape's dollar volume for that day.
  * NOT zero-filled. A zero or missing raw volume becomes NaN, never 0.0 - a zero ADV would
    divide into `order$ / ADV` as an infinity and quietly land in the ">20%" bucket.

    python experiments/build_adv_panel.py
    python experiments/build_adv_panel.py --window 20 --out experiments/_sweep_cache_oos/adv_usd.pkl
    python experiments/build_adv_panel.py --report-tickers SPY,QQQ,SLAB
    python experiments/build_adv_panel.py --report-live-pending      # the 30 pending v9 orders
"""
from __future__ import annotations

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

DEFAULT_CACHE = os.path.join(HERE, "_sweep_cache_oos")
DEFAULT_BASENAME = "adv_usd.pkl"
DEFAULT_WINDOW = 20          # matches P.ADV_USD in redesign_lab.py; do not fork the definition
LIVE_STATE = os.path.join(ROOT, "state", "portfolio_v9.json")


class EmptyPanel(RuntimeError):
    """Raised instead of writing a pickle that would silently give every fill a NaN bucket."""


def load_cache(cache_dir: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    close_path = os.path.join(cache_dir, "close.pkl")
    volume_path = os.path.join(cache_dir, "volume.pkl")
    for p in (close_path, volume_path):
        if not os.path.exists(p):
            raise FileNotFoundError(p)
    return pd.read_pickle(close_path), pd.read_pickle(volume_path)


def build_adv(close: pd.DataFrame, volume: pd.DataFrame, window: int = DEFAULT_WINDOW,
              min_periods: int | None = None, keep_zero_volume: bool = False) -> pd.DataFrame:
    """Dollar ADV = (close * volume).rolling(window).mean(), on the common index AND columns.

    The alignment is explicit and inner: a `close * volume` multiply would align on the UNION and
    hand back all-NaN columns for anything present in only one frame, which reads downstream as
    "covered, no data" instead of "not covered".

    `min_periods=None` keeps pandas' fixed-window default (min_periods == window), which is what
    the lab runs. With zero volume mapped to NaN that also means a halted day blanks the following
    `window` bars rather than dragging the mean towards zero - the consumer's lookup walks back to
    the last real value, so a blank is recoverable and a wrong number is not.
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    c, v = close.align(volume, join="inner", axis=0)
    c, v = c.align(v, join="inner", axis=1)
    if c.empty or not len(c.columns):
        raise EmptyPanel(
            f"close and volume share no data: {close.shape} x {volume.shape} -> {c.shape}")
    v = v.astype("float64")
    if not keep_zero_volume:
        v = v.where(v > 0)                      # 0 or negative volume -> NaN, never a 0.0 ADV
    dollar = c.astype("float64") * v
    adv = dollar.rolling(window, min_periods=min_periods).mean()
    if not bool(adv.notna().to_numpy().any()):
        raise EmptyPanel(
            f"panel is entirely NaN ({adv.shape}); window={window} on {len(c)} rows of data")
    return adv


def coverage_report(adv: pd.DataFrame, tickers: list[str]) -> tuple[list[dict], int]:
    """Per-ticker coverage rows plus the count covered. Covered = a column with >=1 real value."""
    rows = []
    covered = 0
    for t in tickers:
        row = dict(ticker=t, covered=False, last_date=None, last_adv=None, n_obs=0)
        if t in adv.columns:
            col = adv[t].dropna()
            row["n_obs"] = int(len(col))
            if len(col):
                row.update(covered=True, last_date=str(col.index[-1].date())
                           if hasattr(col.index[-1], "date") else str(col.index[-1]),
                           last_adv=float(col.iloc[-1]))
                covered += 1
        rows.append(row)
    return rows, covered


def live_pending_tickers(state_path: str = LIVE_STATE) -> list[str]:
    """Tickers of the pending v9 orders. Read-only: this file is the live book."""
    if not os.path.exists(state_path):
        return []
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    out = []
    for order in state.get("pending") or []:
        t = order.get("ticker")
        if t and t not in out:
            out.append(str(t))
    return out


def _fmt_usd(x: float | None) -> str:
    if x is None:
        return "-"
    for unit, scale in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(x) >= scale:
            return f"${x / scale:,.2f}{unit}"
    return f"${x:,.0f}"


def print_coverage(rows: list[dict], covered: int, label: str) -> None:
    print("", flush=True)
    if not rows:
        print(f"{label}: no tickers given", flush=True)
        return
    print(f"{label}: {covered}/{len(rows)} covered "
          f"({100.0 * covered / len(rows):.1f}%)", flush=True)
    for r in rows:
        if r["covered"]:
            print(f"  {r['ticker']:<8} covered   last={r['last_date']} "
                  f"adv={_fmt_usd(r['last_adv'])} n={r['n_obs']}", flush=True)
        else:
            print(f"  {r['ticker']:<8} NOT COVERED", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the dollar-ADV panel for fill_cost_report.py")
    ap.add_argument("--cache", default=DEFAULT_CACHE,
                    help="lab cache directory holding close.pkl and volume.pkl")
    ap.add_argument("--out", default=None,
                    help=f"output pickle (default: <cache>/{DEFAULT_BASENAME})")
    ap.add_argument("--window", type=int, default=DEFAULT_WINDOW,
                    help="rolling window in trading days (20 = P.ADV_USD in redesign_lab.py)")
    ap.add_argument("--min-periods", type=int, default=None,
                    help="rolling min_periods (default: the window, as the lab runs it)")
    ap.add_argument("--keep-zero-volume", action="store_true",
                    help="reproduce the lab byte-for-byte: keep 0-volume days as 0 dollars")
    ap.add_argument("--report-tickers", default=None, help="comma-separated tickers to check")
    ap.add_argument("--report-live-pending", action="store_true",
                    help=f"also check every pending order in {LIVE_STATE} (read-only)")
    ap.add_argument("--dry-run", action="store_true", help="build and report, write nothing")
    args = ap.parse_args(argv)

    try:
        close, volume = load_cache(args.cache)
    except FileNotFoundError as exc:
        print(f"SKIP: {exc} missing (run the lab with --download first)", flush=True)
        return 0
    print(f"cache {args.cache}: close {close.shape}, volume {volume.shape}", flush=True)

    try:
        adv = build_adv(close, volume, window=args.window, min_periods=args.min_periods,
                        keep_zero_volume=args.keep_zero_volume)
    except EmptyPanel as exc:
        print(f"REFUSED to write an empty panel: {exc}", flush=True)
        return 1

    cells = int(adv.notna().to_numpy().sum())
    print(f"panel {adv.shape[0]} dates x {adv.shape[1]} tickers, "
          f"{adv.index[0].date()} -> {adv.index[-1].date()}, "
          f"window={args.window}, {cells:,} non-NaN cells "
          f"({100.0 * cells / adv.size:.1f}% of grid)", flush=True)

    if args.report_tickers:
        want = [t.strip().upper() for t in args.report_tickers.split(",") if t.strip()]
        rows, covered = coverage_report(adv, want)
        print_coverage(rows, covered, "--report-tickers")
    if args.report_live_pending:
        live = live_pending_tickers()
        if not live:
            print("", flush=True)
            print("no pending orders in the live state (or the file is absent)", flush=True)
        else:
            rows, covered = coverage_report(adv, live)
            print_coverage(rows, covered, "live pending orders")
            print(f"  -> coverage {covered}/{len(live)} of the live pending tickers. "
                  f"The cache is S&P 500 PIT; the missing names are NOT all Russell-only: of the 24 uncovered live tickers 7 are ETFs (never index constituents) and one is Canadian. "
                  f"Closing that gap needs a panel built from the production universe "
                  f"(the bar store, TASK-359) or a live volume fetch - not built here.", flush=True)

    out = args.out or os.path.join(args.cache, DEFAULT_BASENAME)
    if args.dry_run:
        print("", flush=True)
        print(f"--dry-run: nothing written (would have been {out})", flush=True)
        return 0
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    adv.to_pickle(out)
    print("", flush=True)
    print(f"wrote {out} ({os.path.getsize(out):,} bytes)", flush=True)
    print(f"use it with: python experiments/fill_cost_report.py --adv-pickle {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
