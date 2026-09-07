"""Differential driver: two engine versions on the same OOS panel, stop at the first differing order.

    python experiments/engine_diff.py --other C:/path/to/other/hydra_screener_local --steps 200

`--other` is another checkout of hydra_screener_local; its core/portfolio_engine.py is loaded under
a private module name (tranche_book, config and the lab stay THIS tree's). Read-only.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import engine_backtest as EB  # noqa: E402
import redesign_lab as L  # noqa: E402
import sleeve_lab as S  # noqa: E402
from config import V9  # noqa: E402
import core.portfolio_engine as E_MAIN  # noqa: E402


def load_other_engine(other_root: str):
    path = os.path.join(other_root, "core", "portfolio_engine.py")
    spec = importlib.util.spec_from_file_location("other_portfolio_engine", path)
    mod = importlib.util.module_from_spec(spec)
    # the other tree's sleeves package (registry/adapters) must resolve to ITS files when the engine
    # imports `sleeves.registry`; give it priority on sys.path while loading and running
    sys.path.insert(0, other_root)
    for name in [m for m in list(sys.modules) if m == "sleeves" or m.startswith("sleeves.")]:
        del sys.modules[name]
    spec.loader.exec_module(mod)
    return mod


def slim(o):
    keep = ("sleeve", "tranche", "ticker", "side", "dollars", "est_units", "est_price", "close")
    return {k: (round(o[k], 9) if isinstance(o.get(k), float) else o.get(k)) for k in keep if k in o}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--other", required=True)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--sectors", default="live")
    args = ap.parse_args(argv)

    E_OTHER = load_other_engine(os.path.abspath(args.other))
    print("main engine :", E_MAIN.__file__)
    print("other engine:", E_OTHER.__file__)
    P = L.load_panel(oos=True, sectors=args.sectors)
    P.ETF = S.load_etfs(P.close.index)
    idx = P.close.index
    cfg = dict(V9)
    c = dict(L.BASE)
    c.update(L.CONFIGS["T20"])
    sa = E_MAIN.new_state(1.0, str(idx[EB.START].date()), cfg)
    sb = E_OTHER.new_state(1.0, str(idx[EB.START].date()), cfg)
    if json.dumps(sa, sort_keys=True) != json.dumps(sb, sort_keys=True):
        print("new_state differs"); return 1
    prev_t = None
    for i, t in enumerate(range(EB.START, len(idx) - 6, EB.STEP)):
        if i >= args.steps:
            break
        today = str(idx[t].date())
        if sa.get("pending") and prev_t is not None:
            e = prev_t + 1
            fa = E_MAIN.settle(sa, str(idx[e].date()), P.close.iloc[e], P.ETF.iloc[e], cfg)
            fb = E_OTHER.settle(sb, str(idx[e].date()), P.close.iloc[e], P.ETF.iloc[e], cfg)
            if [slim(x) for x in fa] != [slim(x) for x in fb]:
                print(f"FILLS differ at step {i} exec {idx[e].date()}")
                for x, y in zip(fa, fb):
                    if slim(x) != slim(y):
                        print("  main :", slim(x)); print("  other:", slim(y)); break
                return 1
        rk = EB._ranking(P, t, c)
        if rk is None:
            prev_t = t
            continue
        sa, oa = E_MAIN.plan(sa, today, rk, P.close.iloc[: t + 1], P.ETF.iloc[: t + 1], P.IRX, cfg)
        sb, ob = E_OTHER.plan(sb, today, rk, P.close.iloc[: t + 1], P.ETF.iloc[: t + 1], P.IRX, cfg)
        if [slim(x) for x in oa] != [slim(x) for x in ob]:
            print(f"ORDERS differ at step {i} plan {today}: main {len(oa)} orders, other {len(ob)}")
            for x, y in zip(oa, ob):
                if slim(x) != slim(y):
                    print("  main :", slim(x)); print("  other:", slim(y)); break
            ja, jb = json.dumps(sa, sort_keys=True, default=str), json.dumps(sb, sort_keys=True, default=str)
            print("  states equal before orders:", ja == jb)
            return 1
        prev_t = t
        if (i + 1) % 50 == 0:
            print(f"  identical through step {i + 1} ({today})", flush=True)
    print(f"IDENTICAL for {min(args.steps, i + 1)} steps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
