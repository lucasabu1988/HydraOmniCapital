"""
Complemento de backtest_gate_replay.py: replay de los dias del selloff (4-10 jun 2026),
cuando el screener NO corrio. Compara que recomendaria el criterio VIEJO (gate off)
vs el NUEVO (gate on) el mismo dia con los mismos datos, y el retorno real posterior.

Aqui es donde vive el falso positivo que motivo SPEC 4.7: el momentum de 90d sigue
rankeando arriba a las acciones recien desplomadas; el criterio viejo las recomienda,
el gate las veta.
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

DATA_START = "2025-04-01"
DATA_END = "2026-06-12"
CACHE = os.path.join("data_cache", f"gate_replay_{DATA_START}_{DATA_END}.pkl")
CRASH_DAYS = ["2026-06-04", "2026-06-05", "2026-06-09", "2026-06-10"]
UNIVERSE_XLSX = os.path.join("output", "hydra_screener_full_20260601.xlsx")


def fwd(closes, tickers, asof_ts, horizon=None):
    idx = closes.index.get_loc(asof_ts)
    exit_idx = len(closes.index) - 1 if horizon is None else min(idx + horizon, len(closes.index) - 1)
    exit_ts = closes.index[exit_idx]
    rets = {}
    for t in tickers:
        if t in closes.columns:
            e0, e1 = closes[t].iloc[idx], closes[t].iloc[exit_idx]
            if pd.notna(e0) and pd.notna(e1) and e0 > 0:
                rets[t] = (e1 / e0 - 1) * 100
    return exit_ts, rets


def stats(rets):
    if not rets:
        return "(sin datos)"
    v = np.array(list(rets.values()))
    return f"avg {v.mean():+6.2f}%  med {np.median(v):+6.2f}%  WR {(v > 0).mean() * 100:4.0f}%  n={len(v)}"


def run_with_gate(prices_pt, spy_pt, vols_pt, gate_on):
    prev = S.ENABLE_DOWNTREND_GATE
    S.ENABLE_DOWNTREND_GATE = gate_on
    try:
        return S.generate_daily_candidates(prices_pt, spy_pt, vols_pt)
    finally:
        S.ENABLE_DOWNTREND_GATE = prev


def main():
    with open(CACHE, "rb") as f:
        closes, vols = pickle.load(f)
    spy_full = closes["SPY"].dropna()
    tickers = pd.read_excel(UNIVERSE_XLSX)["ticker"].dropna().unique().tolist()
    cols = [t for t in tickers if t in closes.columns]

    for day in CRASH_DAYS:
        asof_ts = pd.Timestamp(day)
        if asof_ts not in closes.index:
            print(f"[skip] {day} no es dia de trading")
            continue
        prices_pt = closes.loc[:asof_ts, cols].dropna(axis=1, how="all")
        vols_pt = vols.loc[:asof_ts, prices_pt.columns]
        spy_pt = spy_full.loc[:asof_ts]

        old = run_with_gate(prices_pt, spy_pt, vols_pt, gate_on=False)
        new = run_with_gate(prices_pt, spy_pt, vols_pt, gate_on=True)

        old_rec = old.loc[old["recommended"] == True, "ticker"].tolist()  # noqa: E712
        new_rec = new.loc[new["recommended"] == True, "ticker"].tolist()  # noqa: E712
        vetoed = new.loc[new["reason"].astype(str).str.startswith("Vetado"), "ticker"]
        vetoed = [t for t in vetoed if t in old_rec]

        exit_ts, rets = fwd(closes, list(set(old_rec + new_rec)), asof_ts, None)
        ndays = closes.index.get_loc(exit_ts) - closes.index.get_loc(asof_ts)

        print("\n" + "=" * 78)
        print(f"AS-OF {day}  ->  {exit_ts.date()} ({ndays}d trading)   "
              f"regimen: {new.iloc[0].get('regime_type', '?')}")
        print("=" * 78)
        sub = lambda names: {t: rets[t] for t in names if t in rets}
        print(f"  VIEJO (sin gate): {len(old_rec):2d} recomendadas   {stats(sub(old_rec))}")
        print(f"  NUEVO (con gate): {len(new_rec):2d} recomendadas   {stats(sub(new_rec))}")
        if vetoed:
            vr = sub(vetoed)
            print(f"  Vetadas que el viejo SI recomendaba ({len(vetoed)}):  {stats(vr)}")
            worst = sorted(vr.items(), key=lambda kv: kv[1])[:8]
            print("    " + "  ".join(f"{t} {r:+.1f}%" for t, r in worst))


if __name__ == "__main__":
    main()
