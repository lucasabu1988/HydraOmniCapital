"""
Replay point-in-time de los runs 2026-05-31 y 2026-06-01 con el criterio NUEVO
(fix del termino de proximidad + Downtrend Veto Gate SPEC 4.7, ambos de c1fd022/4094eb5).

Pregunta que responde: las cohortes que salieron -4.5% (5d) / -7.0% (10d) fueron
elegidas SIN el gate. Con el codigo actual y los mismos datos disponibles ese dia,
que se habria recomendado y como habria rendido?

Compara, por dia de run:
  A) OLD  - recommended original (del xlsx full de ese dia, criterio viejo)
  B) GATE - la lista OLD tras aplicar solo el veto (aislando el efecto del gate)
  C) NEW  - recommended del pipeline actual completo (re-rank + gate)
  vs SPY / QQQ / SMH en las mismas ventanas.

Horizontes: +5 dias de trading exactos, y "to-date" (ultimo cierre disponible).
"""
import os
import pickle
import sys

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from core.signals import generate_daily_candidates  # noqa: E402

RUNS = {
    # run_id -> fecha as-of (ultimo cierre disponible cuando corrio el screener)
    "20260531": "2026-05-29",  # corrio domingo 31 -> datos hasta viernes 29
    "20260601": "2026-06-01",  # corrio lunes 1 a las 20:40 -> cierre del 1
}
BENCHMARKS = ["SPY", "QQQ", "SMH"]
DATA_START = "2025-04-01"   # SMA200 de SPY + momentum 90d necesitan ~1 anio
DATA_END = "2026-06-12"     # exclusivo en yf -> ultimo cierre 2026-06-11
CACHE = os.path.join("data_cache", f"gate_replay_{DATA_START}_{DATA_END}.pkl")


def load_universe(run_id):
    df = pd.read_excel(os.path.join("output", f"hydra_screener_full_{run_id}.xlsx"))
    old_rec = df.loc[df["recommended"] == True, "ticker"].tolist()  # noqa: E712
    return df["ticker"].dropna().unique().tolist(), old_rec


def download_all(tickers):
    if os.path.exists(CACHE):
        print(f"[cache] {CACHE}")
        with open(CACHE, "rb") as f:
            return pickle.load(f)
    print(f"[download] {len(tickers)} tickers {DATA_START} -> {DATA_END} ...")
    raw = yf.download(tickers, start=DATA_START, end=DATA_END,
                      auto_adjust=True, progress=False, threads=True)
    closes = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    vols = raw["Volume"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Volume"]]
    closes = closes.dropna(axis=1, how="all").sort_index()
    vols = vols.reindex(columns=closes.columns).sort_index()
    with open(CACHE, "wb") as f:
        pickle.dump((closes, vols), f)
    return closes, vols


def fwd_returns(closes, tickers, asof_ts, horizon):
    """Retorno % entry=cierre as-of -> cierre +horizon dias de trading (o ultimo disponible si horizon=None)."""
    idx = closes.index.get_loc(asof_ts)
    exit_idx = len(closes.index) - 1 if horizon is None else idx + horizon
    if exit_idx >= len(closes.index):
        return None, {}
    exit_ts = closes.index[exit_idx]
    rets = {}
    for t in tickers:
        if t not in closes.columns:
            continue
        e0, e1 = closes[t].iloc[idx], closes[t].iloc[exit_idx]
        if pd.notna(e0) and pd.notna(e1) and e0 > 0:
            rets[t] = (e1 / e0 - 1) * 100
    return exit_ts, rets


def stats(rets):
    if not rets:
        return "  (sin datos)"
    v = np.array(list(rets.values()))
    wr = (v > 0).mean() * 100
    return f"avg {v.mean():+6.2f}%  med {np.median(v):+6.2f}%  WR {wr:4.0f}%  n={len(v)}"


def main():
    universes = {}
    all_tickers = set(BENCHMARKS)
    for run_id in RUNS:
        tickers, old_rec = load_universe(run_id)
        universes[run_id] = (tickers, old_rec)
        all_tickers.update(tickers)

    closes, vols = download_all(sorted(all_tickers))
    spy_full = closes["SPY"].dropna()
    print(f"[data] {closes.shape[1]} tickers x {len(closes)} dias "
          f"(ultimo cierre: {closes.index[-1].date()})")

    for run_id, asof in RUNS.items():
        tickers, old_rec = universes[run_id]
        asof_ts = pd.Timestamp(asof)
        if asof_ts not in closes.index:
            print(f"[ERROR] {asof} no es dia de trading en los datos")
            continue

        # --- replay punto-en-tiempo con el codigo ACTUAL ---
        cols = [t for t in tickers if t in closes.columns]
        prices_pt = closes.loc[:asof_ts, cols].dropna(axis=1, how="all")
        vols_pt = vols.loc[:asof_ts, prices_pt.columns]
        spy_pt = spy_full.loc[:asof_ts]
        cands = generate_daily_candidates(prices_pt, spy_pt, vols_pt)

        new_rec = cands.loc[cands["recommended"] == True, "ticker"].tolist()  # noqa: E712
        by_ticker = cands.set_index("ticker")
        vetoed_old = [t for t in old_rec
                      if t in by_ticker.index
                      and str(by_ticker.at[t, "reason"]).startswith("Vetado")]
        gate_survivors = [t for t in old_rec if t not in vetoed_old]
        entrants = [t for t in new_rec if t not in old_rec]

        print("\n" + "=" * 78)
        print(f"RUN {run_id}  (as-of {asof})   regimen replay: "
              f"{cands.iloc[0].get('regime_type', '?')}  "
              f"modes: {cands.iloc[0].get('special_modes', '') or '(none)'}")
        print("=" * 78)
        print(f"OLD recommended: {len(old_rec)}   vetados por gate: {len(vetoed_old)}"
              f"   NEW recommended: {len(new_rec)} (nuevos vs OLD: {len(entrants)})")

        for label, horizon in (("+5d", 5), ("to-date", None)):
            exit_ts, rets_all = fwd_returns(closes, list(set(old_rec + new_rec + BENCHMARKS)),
                                            asof_ts, horizon)
            if exit_ts is None:
                print(f"\n--- {label}: ventana aun no disponible ---")
                continue
            ndays = closes.index.get_loc(exit_ts) - closes.index.get_loc(asof_ts)
            print(f"\n--- {label} ({asof} -> {exit_ts.date()}, {ndays} dias trading) ---")
            sub = lambda names: {t: rets_all[t] for t in names if t in rets_all}
            print(f"  A) OLD (criterio viejo)      {stats(sub(old_rec))}")
            print(f"  B) OLD sin vetados (gate)    {stats(sub(gate_survivors))}")
            print(f"  C) NEW (pipeline actual)     {stats(sub(new_rec))}")
            for b in BENCHMARKS:
                if b in rets_all:
                    print(f"     {b:<4}                        {rets_all[b]:+6.2f}%")

        if vetoed_old:
            _, rets5 = fwd_returns(closes, vetoed_old, asof_ts, 5)
            print("\n  Vetados por el gate (criterio nuevo) y su retorno real +5d:")
            for t in vetoed_old:
                r = rets5.get(t)
                reason = str(by_ticker.at[t, "reason"])
                dist = by_ticker.at[t, "dist_20d_high"] if "dist_20d_high" in by_ticker.columns else float("nan")
                rs = by_ticker.at[t, "ret_5d_10d"] if "ret_5d_10d" in by_ticker.columns else float("nan")
                print(f"    {t:<6} {r if r is None else f'{r:+7.2f}%':>9}   "
                      f"dist20dH {dist:+6.1f}%  ret10d {rs:+7.1f}%  | {reason}")
        if entrants:
            _, rets5 = fwd_returns(closes, entrants, asof_ts, 5)
            print("\n  Nuevos entrantes del pipeline actual (no estaban en OLD) y retorno +5d:")
            for t in entrants:
                r = rets5.get(t)
                print(f"    {t:<6} {r if r is None else f'{r:+7.2f}%':>9}")


if __name__ == "__main__":
    main()
