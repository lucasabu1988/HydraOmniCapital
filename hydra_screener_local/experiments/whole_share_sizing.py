"""TASK-407 - what whole shares cost, measured, before anyone touches the sizing rule.

The engine sizes orders in dollars and presumes fractional `est_units`; TASK-353 added whole
shares as a DISPLAY column only. The first live sheet showed why that gap matters: SNDK, LITE
and QQQ did not fit even one share of their dollar amount. The question is not "is capital
lost" - unbought dollars stay in cash and earn the T-bill - but **how far the executable book
drifts from the simulated one**, and how that drift shrinks as the book grows.

So: the same engine, the same panel, twice. Once as today (fractional), once with every priced
order floored to a whole number of shares at its own `est_price`
(`engine_backtest.floor_orders_to_whole_shares`), which is what the instruction sheet asks of
Lucas in practice. Fractional sizing is linear in the book, so it is run once and compared
against each capital level.

    python experiments/whole_share_sizing.py                          # in-sample, 3 capitals
    python experiments/whole_share_sizing.py --oos --capital 100000   # PIT panel, the live book

Read the two panels in the right order. On the PIT panel the effect almost vanishes at $100k
(-0.04 pp/yr, 0.19% tracking error), but that average is diluted twice: the median share price
across the panel is 21.36 in 2005-2015 against 74.66 in 2020-2026, and the book itself compounds
about 4x over the run, so orders are large against share prices for most of the sample. The
in-sample 2020-2026 numbers (-1.06 pp, 1.00% tracking error, a third of priced orders rounding to
zero at $100k) are measured at today's price level and are the ones that describe the live book.

Changing the sizing rule is rule 6. This script measures; it decides nothing.
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

import engine_backtest as EB  # noqa: E402
import metrics as M  # noqa: E402
import redesign_lab as L  # noqa: E402
import sleeve_lab as S  # noqa: E402

DEFAULT_CAPITALS = (25_000.0, 100_000.0, 1_000_000.0)


def tracking_error(a: pd.Series, b: pd.Series, step: int = EB.STEP) -> float:
    """Annualised standard deviation of the step-return difference, in percent."""
    ra = a.pct_change().dropna()
    rb = b.pct_change().dropna()
    common = ra.index.intersection(rb.index)
    if len(common) < 2:
        return float("nan")
    d = ra.loc[common] - rb.loc[common]
    return float(d.std() * np.sqrt(M.periods_per_year(step)) * 100)


def compare(P, capitals) -> dict:
    """Fractional once (it is linear in the book), then one whole-share run per capital."""
    print("fractional run (scale-invariant, once)...", flush=True)
    frac, frac_counts = EB.drive_engine(P, capital=float(capitals[0]))
    rf = M.step_risk_free(P.IRX, frac.index)
    base = M.stats(frac.pct_change().dropna(), "fractional (today)", EB.STEP, rf=rf)
    base.update(cash_share_pct=frac_counts["cash_share"], turnover_pct=frac_counts["turnover"])
    rows = [base]
    detail = []
    for cap in capitals:
        print(f"whole-share run at {cap:,.0f}...", flush=True)
        whole, counts = EB.drive_engine(P, capital=float(cap), whole_shares=True)
        s = M.stats(whole.pct_change().dropna(), f"whole shares @ {cap:,.0f}", EB.STEP,
                    rf=M.step_risk_free(P.IRX, whole.index))
        s.update(
            cash_share_pct=counts["cash_share"],
            turnover_pct=counts["turnover"],
            orders_rounded=counts["rounded_orders"],
            orders_that_became_zero=counts["rounded_to_zero"],
            zero_share_of_rounded_pct=round(
                100.0 * counts["rounded_to_zero"] / counts["rounded_orders"], 2)
            if counts["rounded_orders"] else 0.0,
            # cumulative over every renewal, NOT a one-off loss: the dollars stay in cash
            unspent_dollars_total=counts["unspent_dollars"],
            unspent_pct_of_book_per_renewal=round(
                100.0 * counts["unspent_dollars"] / float(cap) / max(int(s["cycles"]), 1), 2),
            d_ann_net_pp=round(s["ann_net"] - base["ann_net"], 2),
            d_maxdd_pp=round(s["maxdd_net"] - base["maxdd_net"], 2),
            d_sharpe_excess=(round(s["sharpe_excess"] - base["sharpe_excess"], 3)
                             if s["sharpe_excess"] is not None
                             and base["sharpe_excess"] is not None else None),
            tracking_error_ann_pct=round(tracking_error(whole, frac), 2),
        )
        rows.append(s)
        detail.append(dict(capital=float(cap), counts={
            k: v for k, v in counts.items()
            if k not in ("write_off_names", "hold_no_price_names", "not_filled_names",
                         "interest_by_year", "replayed")}))
    return dict(rows=rows, detail=detail)


def main(argv=None):
    ap = argparse.ArgumentParser(description="TASK-407: fractional vs whole-share sizing")
    ap.add_argument("--oos", action="store_true", help="PIT panel 2004-26 instead of in-sample")
    ap.add_argument("--capital", type=float, action="append",
                    help="starting book; repeatable (default 25k / 100k / 1M)")
    ap.add_argument("--sectors", choices=("pit", "live"), default="pit")
    args = ap.parse_args(argv)

    cache = os.path.join(HERE, "_sweep_cache_oos" if args.oos else "_sweep_cache", "close.pkl")
    if not os.path.exists(cache):
        print("SKIP:", cache, "missing")
        return 0
    capitals = tuple(args.capital) if args.capital else DEFAULT_CAPITALS
    print(f"loading {'OOS PIT' if args.oos else 'in-sample'} panel...", flush=True)
    P = L.load_panel(oos=args.oos, sectors=args.sectors)
    P.ETF = S.load_etfs(P.close.index)
    print("  close", P.close.shape, str(P.close.index[0].date()), "->",
          str(P.close.index[-1].date()), flush=True)

    out = compare(P, capitals)
    rows = out["rows"]
    print("", flush=True)
    cols = ["config", "cycles", "ann_net", "ratio_net_vol", "sharpe_excess", "maxdd_net",
            "cash_share_pct",
            "turnover_pct", "orders_rounded", "orders_that_became_zero",
            "zero_share_of_rounded_pct", "unspent_dollars_total",
            "unspent_pct_of_book_per_renewal",
            "d_ann_net_pp", "d_maxdd_pp", "d_sharpe_excess", "tracking_error_ann_pct"]
    df = pd.DataFrame(rows)
    print(df[[c for c in cols if c in df.columns]].to_string(index=False), flush=True)
    print("", flush=True)
    print("Read it as tracking error, not as lost capital: unbought dollars stay in cash and "
          "earn the T-bill in the book.", flush=True)

    scratch = os.path.join(HERE, "_lab_scratch",
                           "task407_oos.json" if args.oos else "task407.json")
    os.makedirs(os.path.dirname(scratch), exist_ok=True)
    with open(scratch, "w", encoding="utf-8") as f:
        json.dump(dict(oos=bool(args.oos), capitals=list(capitals), rows=rows,
                       detail=out["detail"],
                       note="measurement only; sizing unchanged (rule 6)"),
                  f, indent=2, default=str)
    print("wrote", scratch, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
