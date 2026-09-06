"""Drive the PRODUCTION engine through the lab panel (TASK-347 in-sample, TASK-350 --oos).

Each 5-bar step: lab rank_day reshaped as in the parity test -> plan() -> settle() at t+1
-> summary_table book value. Engine as it is today (interest on both sleeves, pair reset,
trailing T-bill hurdle). No parameter changes. This is production plumbing, not a new
variant (TEST-read-once).

    python experiments/engine_backtest.py          # in-sample _sweep_cache/ 2020-26
    python experiments/engine_backtest.py --oos    # PIT _sweep_cache_oos/ 2004-26
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import redesign_lab as L  # noqa: E402
import sleeve_lab as S  # noqa: E402
from config import V9  # noqa: E402
import core.portfolio_engine as E  # noqa: E402

START = 280
STEP = 5
AUDIT_MIX = dict(ann_net=6.91, sharpe_net=0.74, maxdd_net=-19.5)
AUDIT_STEPS = os.path.join(HERE, "_sweep_cache_etf", "audit_steps.pkl")


def _stats(values: pd.Series, label: str, step=STEP) -> dict:
    r = values.pct_change().dropna()
    if r.empty:
        return dict(config=label, cycles=0)
    py = 252.0 / step

    def ann(x):
        return float(((1 + x).prod() ** (py / len(x)) - 1) * 100)

    eq = (1 + r).cumprod()
    dd = float((eq / eq.cummax() - 1).min()) * 100
    return dict(
        config=label, cycles=int(len(r)),
        ann_net=round(ann(r), 2),
        sharpe_net=round(float(r.mean() / r.std() * np.sqrt(py)), 2) if r.std() else 0.0,
        maxdd_net=round(dd, 1),
    )


def _stats_from_net(net: pd.Series, label: str, step=STEP) -> dict:
    r = net.dropna()
    if r.empty:
        return dict(config=label, cycles=0)
    py = 252.0 / step

    def ann(x):
        return float(((1 + x).prod() ** (py / len(x)) - 1) * 100)

    eq = (1 + r).cumprod()
    dd = float((eq / eq.cummax() - 1).min()) * 100
    return dict(
        config=label, cycles=int(len(r)),
        ann_net=round(ann(r), 2),
        sharpe_net=round(float(r.mean() / r.std() * np.sqrt(py)), 2) if r.std() else 0.0,
        maxdd_net=round(dd, 1),
    )


def _ranking(P, t, c):
    out = L.rank_day(P, t, c)
    if out is None:
        return None
    m = P.meta_for(t, True)
    n = max(6, min(int(round(14 * m.overall_aggression * m.pillar_multipliers["COMPASS"])), 28))
    return pd.DataFrame({
        "ticker": out.index,
        "rank": range(1, len(out) + 1),
        "sector": out["sector"].values,
        "reason": np.where(L.vetoed(out).values, "Vetado: gate", ""),
        "recommended_count": n,
        "recommended": [i < n for i in range(len(out))],
    })


def _settle_pending(st, P, etf, cfg, prev_t, counts):
    if not st.get("pending") or prev_t is None:
        return
    e = prev_t + 1
    if e >= len(P.close.index):
        return
    fills = E.settle(st, str(P.close.index[e].date()), P.close.iloc[e], etf.iloc[e], cfg)
    counts["not_filled"] += sum(1 for f in fills if f.get("status") == "not_filled")
    counts["hold_no_price"] += sum(1 for f in fills if f.get("side") == "hold_no_price")
    for f in fills:
        if f.get("side") == "hold_no_price":
            counts["_hnp_tickers"].add(str(f.get("ticker")))
        if f.get("status") == "not_filled":
            counts["_nf_tickers"].add(str(f.get("ticker")))


def drive_engine(P, *, progress_every=50) -> tuple[pd.Series, dict]:
    cfg = dict(V9)
    idx = P.close.index
    st = E.new_state(1.0, str(idx[START].date()), cfg)
    recs = []
    expos, distincts, turnovers = [], [], []
    counts = dict(not_filled=0, hold_no_price=0, write_offs=0, write_off_dollars=0.0,
                  transfers=0, plans=0, _hnp_tickers=set(), _nf_tickers=set())
    prev_t = None
    etf = P.ETF
    irx = P.IRX
    c = dict(L.BASE)
    c.update(L.CONFIGS["T20"])
    n_steps = len(range(START, len(idx) - 6, STEP))
    for i, t in enumerate(range(START, len(idx) - 6, STEP)):
        today = str(idx[t].date())
        _settle_pending(st, P, etf, cfg, prev_t, counts)
        rk = _ranking(P, t, c)
        if rk is None:
            prev_t = t
            continue
        st, orders = E.plan(st, today, rk, P.close.iloc[: t + 1], etf.iloc[: t + 1], irx, cfg)
        counts["plans"] += 1
        counts["transfers"] += sum(1 for o in (st.get("pending") or [])
                                   if str(o.get("side", "")).startswith("transfer"))
        traded = sum(float(o.get("dollars") or 0) for o in (st.get("pending") or [])
                     if o.get("side") in ("buy", "sell"))
        prev_t = t
        s = E.summary_table(st, P.close.iloc[t], etf.iloc[t], cfg)
        recs.append((idx[t], s["total"]))
        tot = s["total"] or 1.0
        expos.append(s["sleeves"]["stocks"]["exposure"] * 0.5 + s["sleeves"]["etf"]["exposure"] * 0.5)
        distincts.append(s["sleeves"]["stocks"]["distinct"] + s["sleeves"]["etf"]["distinct"])
        turnovers.append(traded / tot if tot else 0.0)
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  engine {i + 1}/{n_steps} {today} book={tot:.4f} "
                  f"nf={counts['not_filled']} hnp={counts['hold_no_price']} "
                  f"wo={len(st.get('write_offs') or [])}", flush=True)
    _settle_pending(st, P, etf, cfg, prev_t, counts)
    wo = list(st.get("write_offs") or [])
    counts["write_offs"] = len(wo)
    counts["write_off_dollars"] = round(float(sum(float(w.get("proceeds") or 0) for w in wo)), 6)
    counts["write_off_names"] = [
        dict(date=w.get("date"), sleeve=w.get("sleeve"), ticker=w.get("ticker"),
             proceeds=round(float(w.get("proceeds") or 0), 6))
        for w in wo
    ]
    counts["hold_no_price_names"] = sorted(counts.pop("_hnp_tickers"))
    counts["not_filled_names"] = sorted(counts.pop("_nf_tickers"))
    counts["turnover"] = round(float(np.mean(turnovers) * 100), 1) if turnovers else 0.0
    counts["exposure"] = round(float(np.mean(expos) * 100), 0) if expos else 0.0
    counts["distinct"] = round(float(np.mean(distincts)), 1) if distincts else 0.0
    interest = list(st.get("interest") or [])
    counts["interest_dollars"] = round(float(sum(float(x.get("dollars") or 0) for x in interest)), 6)
    counts["interest_n"] = len(interest)
    ser = pd.Series({d: v for d, v in recs}, dtype=float).sort_index()
    counts["interest_by_year"] = _interest_by_year(interest, ser)
    return ser, counts


def _interest_by_year(interest: list, book: pd.Series) -> list:
    if not interest:
        return []
    recs = pd.DataFrame(interest)
    recs["date"] = pd.to_datetime(recs["date"])
    recs["dollars"] = pd.to_numeric(recs["dollars"], errors="coerce").fillna(0.0)
    book = book.copy()
    book.index = pd.DatetimeIndex(book.index)
    out = []
    for year, g in recs.groupby(recs["date"].dt.year):
        dollars = float(g["dollars"].sum())
        b = book[book.index.year == int(year)]
        mean_book = float(b.mean()) if len(b) else float("nan")
        pct = (dollars / mean_book * 100.0) if mean_book and np.isfinite(mean_book) else None
        out.append(dict(
            year=int(year),
            interest_dollars=round(dollars, 6),
            mean_book=round(mean_book, 6) if np.isfinite(mean_book) else None,
            interest_pct_of_book=round(pct, 3) if pct is not None else None,
        ))
    return out


def _yearly(engine: pd.Series, lab_net: pd.Series | None) -> list:
    r = engine.pct_change().dropna()
    lab = lab_net.dropna() if lab_net is not None else None
    rows = []
    years = sorted(set(r.index.year) | (set(lab.index.year) if lab is not None and len(lab) else set()))
    py = 252.0 / STEP
    for year in years:
        g = r[r.index.year == year]
        row = dict(year=int(year), n_engine=int(len(g)))
        if len(g):
            eq = (1 + g).cumprod()
            row["engine_net"] = round(float((1 + g).prod() - 1) * 100, 1)
            row["engine_sharpe"] = round(float(g.mean() / g.std() * np.sqrt(py)), 2) if g.std() else 0.0
            row["engine_dd"] = round(float((eq / eq.cummax() - 1).min()) * 100, 1)
        if lab is not None:
            lg = lab[lab.index.year == year]
            row["n_lab"] = int(len(lg))
            if len(lg):
                row["lab_net"] = round(float((1 + lg).prod() - 1) * 100, 1)
        rows.append(row)
    return rows


def _load_lab_mix(P, oos: bool) -> tuple[pd.Series, dict]:
    """Lab 50/50 T20+ETF. OOS uses the audit pickle (the 6.91 / 0.74 / -19.5 series)."""
    if oos and os.path.exists(AUDIT_STEPS):
        blob = pd.read_pickle(AUDIT_STEPS)
        mix = blob["P_5050"]
        print("  lab mix from audit_steps.pkl P_5050", mix.shape,
              str(mix.index[0].date()), "->", str(mix.index[-1].date()), flush=True)
        return mix["net"], _stats_from_net(mix["net"], "lab mix T20+ETF equal (audit)")
    print("lab T20 exec + ETF sleeve + mix equal...", flush=True)
    t20 = L.run_exec(P, L.CONFIGS["T20"])
    etf = S.run_sleeve(P, {})
    mixed = S.mix([t20, etf], "equal")
    return mixed["net"], _stats_from_net(mixed["net"], "lab mix T20+ETF equal")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Production engine end-to-end vs lab 50/50 mix")
    ap.add_argument("--oos", action="store_true",
                    help="PIT panel _sweep_cache_oos/ 2004-2026 (TASK-350). Default: in-sample 2020-26.")
    args = ap.parse_args(argv)

    cache = os.path.join(HERE, "_sweep_cache_oos" if args.oos else "_sweep_cache", "close.pkl")
    if not os.path.exists(cache):
        print("SKIP:", cache, "missing")
        return 0
    label = "OOS PIT" if args.oos else "in-sample"
    print(f"loading {label} panel...", flush=True)
    P = L.load_panel(oos=args.oos)
    P.ETF = S.load_etfs(P.close.index)
    print("  close", P.close.shape, "ETF", P.ETF.shape,
          str(P.close.index[0].date()), "->", str(P.close.index[-1].date()), flush=True)
    print("NOTE: same 50/50 T20+ETF strategy with production plumbing; not a new variant "
          "(TEST-read-once).", flush=True)

    lab_net, lab_s = _load_lab_mix(P, args.oos)
    if args.oos:
        lab_s["ann_net_audit"] = AUDIT_MIX["ann_net"]
        lab_s["sharpe_audit"] = AUDIT_MIX["sharpe_net"]
        lab_s["maxdd_audit"] = AUDIT_MIX["maxdd_net"]

    print("engine (pair reset, trailing hurdle, interest)...", flush=True)
    eng, counts = drive_engine(P)
    print("  engine series", len(eng), str(eng.index[0].date()), "->", str(eng.index[-1].date()),
          flush=True)

    common = lab_net.index.intersection(eng.index)
    lab_on_overlap = _stats_from_net(lab_net.reindex(common).dropna(), lab_s["config"] + " overlap")
    mix_c = lab_net.reindex(common).dropna()
    rows = [
        {**lab_s, "overlap_ann_net": lab_on_overlap.get("ann_net"),
         "overlap_sharpe": lab_on_overlap.get("sharpe_net"),
         "overlap_maxdd": lab_on_overlap.get("maxdd_net"),
         "overlap_cycles": lab_on_overlap.get("cycles")},
        {**_stats(eng, "engine production (pair reset)"), **{
            k: v for k, v in counts.items()
            if k not in ("write_off_names", "hold_no_price_names", "not_filled_names",
                         "interest_by_year")
        }},
    ]
    print(pd.DataFrame(rows).to_string(index=False), flush=True)

    yearly = _yearly(eng, lab_net)
    print("\nyearly net (%) engine vs lab mix", flush=True)
    print(pd.DataFrame(yearly).to_string(index=False), flush=True)

    print("\ninterest as % of mean book, by year", flush=True)
    print(pd.DataFrame(counts["interest_by_year"]).to_string(index=False), flush=True)

    print("\nplumbing counts:", flush=True)
    print("  not_filled", counts["not_filled"], "names", counts["not_filled_names"], flush=True)
    print("  hold_no_price", counts["hold_no_price"], "names", counts["hold_no_price_names"], flush=True)
    print("  write-offs", counts["write_offs"], "dollars", counts["write_off_dollars"],
          "detail", counts["write_off_names"], flush=True)
    print("  transfers", counts["transfers"], "interest $", counts["interest_dollars"],
          "on start book 1.0", flush=True)

    scratch_name = "task350.json" if args.oos else "task347.json"
    scratch = os.path.join(HERE, "_lab_scratch", scratch_name)
    payload = dict(oos=bool(args.oos), rows=rows, yearly=yearly,
                   interest_by_year=counts["interest_by_year"],
                   write_off_names=counts["write_off_names"],
                   hold_no_price_names=counts["hold_no_price_names"],
                   not_filled_names=counts["not_filled_names"],
                   engine_first=str(eng.index[0].date()) if len(eng) else None,
                   engine_last=str(eng.index[-1].date()) if len(eng) else None,
                   note="production plumbing of the 50/50 T20+ETF mix; not a new variant")
    os.makedirs(os.path.dirname(scratch), exist_ok=True)
    with open(scratch, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print("wrote", scratch, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
