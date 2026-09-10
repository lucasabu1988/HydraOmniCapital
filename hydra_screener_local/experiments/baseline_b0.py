"""B0 — the frozen scientific baseline every new hypothesis is compared against.

B0 = commit `e29599e` (main, 2026-09-10, after the consolidation: ASTRA-05/06 in the lab,
corrected runner), the caches on disk today, the OOS S&P 500 point-in-time panel with delistings
(TASK-350), sectors `fixed` (the same mode `engine_backtest.py --oos` uses), same dates, executable
accounting (`run_exec`, costs included). It is run ONCE and frozen in
`experiments/_lab_scratch/b0.json`; the numbers are copied into `.comms/hypotheses.md`.

Rows:
  * `T20`       the stock sleeve as production ranks it (mom12_7 / vol63, hold 20, 4 tranches, voltarget)
  * `PROD`      the legacy single-portfolio config, for continuity with older tables
  * `engine`    the production 50/50 engine row, read from the scratch `engine_backtest.py --oos`
                wrote at the same commit (the canonical run), not recomputed here

`ann_net` is a geometric annualised NET return (CAGR), which is the deciding metric Lucas set:
a candidate is APPROVED for the sleeve when its CAGR exceeds B0's T20 by more than +1.00 pp, and
for production when the 50/50 engine's CAGR exceeds B0's engine row by more than +1.00 pp.
Only measures; rule 6 intact.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # TASK-380: cp1252 consoles

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import metrics as M  # noqa: E402
import redesign_lab as L  # noqa: E402

CONFIGS = ("T20", "T20_cy", "PROD")
ENGINE_SCRATCH = os.path.join(HERE, "_lab_scratch", "task350.json")


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def engine_row() -> dict | None:
    """The 50/50 engine row from the canonical `engine_backtest.py --oos` scratch, if present."""
    if not os.path.exists(ENGINE_SCRATCH):
        return None
    with open(ENGINE_SCRATCH, encoding="utf-8") as fh:
        blob = json.load(fh)
    rows = blob.get("rows") if isinstance(blob, dict) else None
    if isinstance(rows, list):
        for r in rows:
            if str(r.get("config", "")).startswith("engine production"):
                return r
    return blob if isinstance(blob, dict) and "ann_net" in blob else None


def run(P, configs=CONFIGS, extra: dict | None = None) -> dict:
    """One published row per config, on the SAME convention as the engine row: metrics.stats on
    the per-step NET return with the config's step (hold // tranches = 5 bars for T20) and the
    ^IRX risk-free leg, so `ann_net` is a CAGR and `sharpe_excess` subtracts the T-bill. (The
    lab's own `stats(df, hold)` annualises with `hold`, which is right for a single-portfolio
    run and wrong for a 4-tranche book stepping every 5 bars.)"""
    out = {}
    for name in configs:
        cfg = dict(L.CONFIGS[name])
        if extra:
            cfg.update(extra)
        df = L.run_exec(P, cfg)
        step = int(L.step_of(cfg))
        net = df["net"].dropna()
        rf = M.step_risk_free(P.IRX, net.index, forward=True, step=step)
        row = M.stats(net, name, step, rf=rf)
        row.update(hold=int(dict(L.BASE, **cfg)["hold"]), step=step,
                   turnover=round(float(df["turnover"].mean() * 100), 1) if "turnover" in df else None,
                   exposure=round(float(df["expo"].mean() * 100), 0) if "expo" in df else None,
                   avg_n=round(float(df["n"].mean()), 1) if "n" in df else None,
                   distinct=round(float(df["distinct"].mean()), 1) if "distinct" in df else None)
        out[name] = row
        print(f"  {name:8} cycles {row['cycles']}  ann_net {row['ann_net']}  net/vol {row.get('ratio_net_vol')}  "
              f"sharpe_excess {row.get('sharpe_excess')}  maxDD {row['maxdd_net']}  turnover {row.get('turnover')}", flush=True)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="B0: the frozen baseline (T20, PROD sleeves + the canonical engine row)")
    ap.add_argument("--sectors", choices=L.SECTOR_MODES, default="fixed")
    ap.add_argument("--json", default=os.path.join(HERE, "_lab_scratch", "b0.json"))
    ap.add_argument("--force", action="store_true", help="overwrite an existing B0 (it is meant to be run once)")
    args = ap.parse_args(argv)
    if os.path.exists(args.json) and not args.force:
        print(f"B0 already frozen at {args.json}; pass --force to recompute (and say why in the register)")
        return 1
    cache = os.path.join(HERE, "_sweep_cache_oos", "close.pkl")
    if not os.path.exists(cache):
        print("SKIP:", cache, "missing")
        return 0
    print("loading OOS PIT panel...", flush=True)
    P = L.load_panel(oos=True, sectors=args.sectors)
    print("  close", P.close.shape, str(P.close.index[0].date()), "->", str(P.close.index[-1].date()), flush=True)
    rows = run(P)
    result = {
        "commit": _commit(), "sectors": args.sectors,
        "panel": {"first": str(P.close.index[0].date()), "last": str(P.close.index[-1].date()),
                  "names": int(P.close.shape[1]), "bars": int(P.close.shape[0]),
                  "pit_meta": getattr(P, "PIT_META", None), "sector_source": getattr(P, "SECTOR_SOURCE", None),
                  "eligibility_currency": getattr(P, "ELIG_CURRENCY", None)},
        "sleeves": rows,
        "engine": engine_row(),
        "deciding_metric": "ann_net (geometric annualised net return, %); approve if candidate - B0 > +1.00 pp",
    }
    os.makedirs(os.path.dirname(args.json), exist_ok=True)
    with open(args.json, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, default=str)
    print("wrote", args.json, flush=True)
    if result["engine"]:
        e = result["engine"]
        print(f"  engine   cycles {e.get('cycles')}  ann_net {e.get('ann_net')}  sharpe_excess {e.get('sharpe_excess')}  "
              f"maxDD {e.get('maxdd_net')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
