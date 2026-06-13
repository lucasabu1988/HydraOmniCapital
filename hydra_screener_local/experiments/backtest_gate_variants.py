"""
Compara variantes del Downtrend Veto Gate (SPEC 4.7) en los dias del selloff jun-2026.

Principio propuesto (Lucas, 2026-06-12): "el veto no puede ser en positivo, solo en
negativo" — una accion con retorno reciente positivo no puede ser vetada.

Variantes:
  V0 actual : veto si dist20dH < -8  OR  ret10d < -5          (OR puro, vigente)
  V1 ret<0  : veto si (dist20dH < -8 OR ret10d < -5) AND ret10d < 0
  V2 AND    : veto si dist20dH < -8 AND ret10d < -5

Metodo: pipeline actual con gate OFF para obtener el ranking/recommended pre-gate,
luego cada variante se aplica como mascara sobre las columnas ret_5d_10d /
dist_20d_high del output. Retornos forward al ultimo cierre disponible.
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import core.signals as S  # noqa: E402
from config import GATE_MAX_DIST_TO_HIGH_PCT as DIST_TH  # noqa: E402  (-8.0)
from config import GATE_MIN_RET_SHORT_PCT as RET_TH  # noqa: E402  (-5.0)

DATA_START = "2025-04-01"
DATA_END = "2026-06-12"
CACHE = os.path.join("data_cache", f"gate_replay_{DATA_START}_{DATA_END}.pkl")
DAYS = ["2026-05-29", "2026-06-01", "2026-06-04", "2026-06-05", "2026-06-09", "2026-06-10"]
UNIVERSE_XLSX = os.path.join("output", "hydra_screener_full_20260601.xlsx")

VARIANTS = {
    "V0 actual (OR)": lambda d, r: (d < DIST_TH) | (r < RET_TH),
    "V1 solo-negativo": lambda d, r: ((d < DIST_TH) | (r < RET_TH)) & (r < 0),
    "V2 AND estricto": lambda d, r: (d < DIST_TH) & (r < RET_TH),
}


def fwd(closes, tickers, asof_ts):
    idx = closes.index.get_loc(asof_ts)
    exit_ts = closes.index[-1]
    rets = {}
    for t in tickers:
        if t in closes.columns:
            e0, e1 = closes[t].iloc[idx], closes[t].iloc[-1]
            if pd.notna(e0) and pd.notna(e1) and e0 > 0:
                rets[t] = (e1 / e0 - 1) * 100
    return exit_ts, rets


def stats(rets):
    if not rets:
        return "avg     --    WR  --   n=0 "
    v = np.array(list(rets.values()))
    return f"avg {v.mean():+6.2f}%  WR {(v > 0).mean() * 100:4.0f}%  n={len(v):2d}"


def main():
    with open(CACHE, "rb") as f:
        closes, vols = pickle.load(f)
    spy_full = closes["SPY"].dropna()
    tickers = pd.read_excel(UNIVERSE_XLSX)["ticker"].dropna().unique().tolist()
    cols = [t for t in tickers if t in closes.columns]

    S.ENABLE_DOWNTREND_GATE = False  # ranking puro; las variantes se aplican aparte

    for day in DAYS:
        asof_ts = pd.Timestamp(day)
        if asof_ts not in closes.index:
            print(f"[skip] {day}")
            continue
        prices_pt = closes.loc[:asof_ts, cols].dropna(axis=1, how="all")
        vols_pt = vols.loc[:asof_ts, prices_pt.columns]
        cands = S.generate_daily_candidates(prices_pt, spy_full.loc[:asof_ts], vols_pt)

        rec = cands[cands["recommended"] == True].copy()  # noqa: E712
        d = pd.to_numeric(rec["dist_20d_high"], errors="coerce")
        r = pd.to_numeric(rec["ret_5d_10d"], errors="coerce")

        exit_ts, rets = fwd(closes, rec["ticker"].tolist(), asof_ts)
        ndays = len(closes.loc[asof_ts:]) - 1
        sub = lambda names: {t: rets[t] for t in names if t in rets}

        print("\n" + "=" * 84)
        print(f"AS-OF {day} -> {exit_ts.date()} ({ndays}d)   pre-gate recommended: {len(rec)}")
        print("=" * 84)
        print(f"  sin gate            {stats(sub(rec['ticker']))}")
        for name, mask_fn in VARIANTS.items():
            mask = mask_fn(d, r).fillna(False)
            vetoed = rec.loc[mask, "ticker"].tolist()
            kept = rec.loc[~mask, "ticker"].tolist()
            line = f"  {name:<18}  {stats(sub(kept))}   vetadas {len(vetoed)}: {stats(sub(vetoed))}"
            print(line)
            if vetoed:
                vr = sorted(sub(vetoed).items(), key=lambda kv: kv[1])
                print("      " + "  ".join(f"{t} {x:+.1f}%" for t, x in vr))


if __name__ == "__main__":
    main()
