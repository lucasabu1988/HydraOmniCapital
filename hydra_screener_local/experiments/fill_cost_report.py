"""TASK-406 - execution cost from real fills, with N on the front page.

The cost model in production is 10 bp per side for stocks and 5 for ETFs, and it comes from
ADV/price assumptions, not from anything HYDRA has executed. This report is the other direction:
take the ledger, compare each confirmed fill against the price the book expected, and tabulate the
difference by the things that should drive it (sleeve, side, order size against ADV, price level).

It refuses to pretend. With fewer than `MIN_N_FOR_CALIBRATION` confirmed fills it prints the table
and says, in the header, that nothing here calibrates a cost model. Thirty orders is plumbing, not
evidence.

    python experiments/fill_cost_report.py                        # the live ledger
    python experiments/fill_cost_report.py --state path/to.json   # any state file
    python experiments/fill_cost_report.py --adv-pickle cache.pkl # add order$/ADV buckets

Which reference price the slippage is measured against matters, and the ledger only sometimes
keeps the right one:

  * `presumed_price` - the settle-day close the engine actually filled at. This is the clean
    reference: fill minus that close is execution slippage and nothing else. It exists only if
    `apply_confirmations` was taught to keep it (the additive half of TASK-406); today it
    overwrites `price` in place, so for older fills the column is absent.
  * `est_price` - the planning-day close, one bar earlier. Falling back to it mixes the overnight
    move with the execution, and the report labels every row with the reference it used so the two
    are never averaged into one number by accident.
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

MIN_N_FOR_CALIBRATION = 50
ADV_BUCKETS = [0.0, 0.5, 1.0, 5.0, 20.0, np.inf]
ADV_LABELS = ["<0.5%", "0.5-1%", "1-5%", "5-20%", ">20%"]
PRICE_BUCKETS = [0.0, 20.0, 50.0, 100.0, 250.0, np.inf]
PRICE_LABELS = ["<20", "20-50", "50-100", "100-250", ">250"]
CONFIRMED = ("confirmed", "confirmed_unplanned")


def load_ledger(state_path: str) -> list[dict]:
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    return list(state.get("ledger") or [])


def reference_price(fill: dict) -> tuple[float | None, str]:
    """(price, which). `presumed_price` is the clean reference; `est_price` mixes in the overnight."""
    for key, label in (("presumed_price", "presumed_close"), ("est_price", "planning_close")):
        raw = fill.get(key)
        try:
            p = float(raw)
        except (TypeError, ValueError):
            continue
        if np.isfinite(p) and p > 0:
            return p, label
    return None, "none"


def slippage_bp(fill: dict) -> dict:
    """Signed against the book: a buy above the reference costs money, a sell below it does too."""
    ref, which = reference_price(fill)
    side = str(fill.get("side") or "")
    try:
        price = float(fill.get("price"))
    except (TypeError, ValueError):
        price = float("nan")
    out = dict(reference=which, reference_price=ref, price=price if np.isfinite(price) else None,
               raw_bp=None, cost_bp=None)
    if ref is None or not np.isfinite(price) or price <= 0:
        return out
    raw = (price / ref - 1.0) * 1e4
    out["raw_bp"] = float(raw)
    out["cost_bp"] = float(raw if side == "buy" else -raw)
    return out


def fee_bp(fill: dict) -> float | None:
    try:
        dollars = abs(float(fill.get("dollars") or 0.0))
        fee = abs(float(fill.get("cost") or 0.0))
    except (TypeError, ValueError):
        return None
    return float(fee / dollars * 1e4) if dollars > 0 else None


def _adv_lookup(adv: pd.DataFrame | None, ticker: str, date: str) -> float | None:
    """Dollar ADV on or before `date`, from a volume*close panel keyed by date x ticker."""
    if adv is None or ticker not in adv.columns:
        return None
    try:
        col = adv[ticker].dropna()
        col = col[col.index <= pd.Timestamp(date)]
    except (TypeError, ValueError):
        return None
    return float(col.iloc[-1]) if len(col) else None


def build_frame(ledger: list[dict], adv: pd.DataFrame | None = None) -> pd.DataFrame:
    rows = []
    for f in ledger:
        s = slippage_bp(f)
        dollars = float(f.get("dollars") or 0.0)
        adv_dollars = _adv_lookup(adv, str(f.get("ticker")), str(f.get("exec_date")))
        rows.append(dict(
            exec_date=f.get("exec_date"),
            sleeve=f.get("sleeve"),
            tranche=f.get("tranche"),
            ticker=f.get("ticker"),
            side=f.get("side"),
            status=f.get("status"),
            units=f.get("units"),
            dollars=dollars,
            modelled_bp=f.get("cost_bp"),
            fee_bp=fee_bp(f),
            adv_dollars=adv_dollars,
            order_pct_of_adv=(100.0 * dollars / adv_dollars) if adv_dollars else None,
            **s,
        ))
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["confirmed"] = df["status"].isin(CONFIRMED)
    # to_numeric first: an all-None column (no ADV panel, no reference) makes pd.cut raise
    df["price_bucket"] = pd.cut(pd.to_numeric(df["reference_price"], errors="coerce"),
                                PRICE_BUCKETS, labels=PRICE_LABELS)
    df["adv_bucket"] = pd.cut(pd.to_numeric(df["order_pct_of_adv"], errors="coerce"),
                              ADV_BUCKETS, labels=ADV_LABELS)
    return df


def _agg(df: pd.DataFrame, by) -> pd.DataFrame:
    g = df.groupby(by, dropna=False, observed=False)["cost_bp"]
    out = pd.DataFrame({
        "n": g.count(),
        "mean_bp": g.mean().round(2),
        "median_bp": g.median().round(2),
        "sd_bp": g.std().round(2),
        "worst_bp": g.max().round(2),
    })
    return out.reset_index()


def summarise(df: pd.DataFrame) -> dict:
    if df.empty:
        return dict(fills=0, confirmed=0, priced=0, enough_for_calibration=False, tables={},
                    references={}, statuses={})
    conf = df[df["confirmed"] & df["cost_bp"].notna()]
    out = dict(
        fills=int(len(df)),
        confirmed=int(df["confirmed"].sum()),
        priced=int(len(conf)),
        statuses=df["status"].value_counts(dropna=False).to_dict(),
        references=conf["reference"].value_counts().to_dict(),
        enough_for_calibration=bool(len(conf) >= MIN_N_FOR_CALIBRATION),
        mean_bp=round(float(conf["cost_bp"].mean()), 2) if len(conf) else None,
        median_bp=round(float(conf["cost_bp"].median()), 2) if len(conf) else None,
        modelled_bp_mean=round(float(conf["modelled_bp"].dropna().mean()), 2)
        if conf["modelled_bp"].notna().any() else None,
        fee_bp_mean=round(float(conf["fee_bp"].dropna().mean()), 2)
        if conf["fee_bp"].notna().any() else None,
        adv_coverage=int(conf["order_pct_of_adv"].notna().sum()),
        tables={},
    )
    if len(conf):
        out["tables"] = {
            "by_sleeve_side": _agg(conf, ["sleeve", "side"]),
            "by_reference": _agg(conf, ["reference"]),
            "by_price_bucket": _agg(conf, ["price_bucket"]),
            "by_adv_bucket": _agg(conf, ["adv_bucket"]),
        }
    return out


def header(s: dict) -> list[str]:
    lines = [
        f"N = {s['priced']} confirmed fills with a usable reference price "
        f"({s['confirmed']} confirmed of {s['fills']} ledger rows).",
    ]
    if not s["enough_for_calibration"]:
        lines.append(
            f"NOT ENOUGH DATA to calibrate a cost model (need {MIN_N_FOR_CALIBRATION}+). "
            f"What follows is the pipeline and a first look, not a replacement for the modelled "
            f"10/5 bp."
        )
    refs = s.get("references") or {}
    if refs.get("planning_close"):
        lines.append(
            f"{refs['planning_close']} row(s) fall back to the planning close, which mixes the "
            f"overnight move into the slippage. Do not average them with the "
            f"{refs.get('presumed_close', 0)} clean row(s)."
        )
    if s.get("priced") and not s.get("adv_coverage"):
        lines.append("No ADV panel given (--adv-pickle), so order$/ADV buckets are empty.")
    return lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="TASK-406: execution cost from real fills")
    ap.add_argument("--state", default=os.path.join(ROOT, "state", "portfolio_v9.json"))
    ap.add_argument("--adv-pickle", default=None,
                    help="pickle of a date x ticker DOLLAR volume panel (close*volume)")
    ap.add_argument("--csv", default=None, help="also write the per-fill frame here")
    args = ap.parse_args(argv)

    if not os.path.exists(args.state):
        print("SKIP:", args.state, "missing")
        return 0
    ledger = load_ledger(args.state)
    adv = pd.read_pickle(args.adv_pickle) if args.adv_pickle else None
    df = build_frame(ledger, adv)
    s = summarise(df)
    for line in header(s):
        print(line, flush=True)
    if df.empty:
        print("ledger is empty: nothing executed yet.", flush=True)
        return 0
    print("", flush=True)
    print("statuses:", s["statuses"], flush=True)
    print(f"mean slippage {s['mean_bp']} bp, median {s['median_bp']} bp, "
          f"modelled {s['modelled_bp_mean']} bp, fees charged {s['fee_bp_mean']} bp", flush=True)
    for name, table in (s.get("tables") or {}).items():
        print("", flush=True)
        print(name, flush=True)
        print(table.to_string(index=False), flush=True)
    if args.csv:
        df.to_csv(args.csv, index=False)
        print("", flush=True)
        print("wrote", args.csv, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
