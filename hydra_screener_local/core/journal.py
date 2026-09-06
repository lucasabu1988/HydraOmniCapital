"""TASK-355 — weekly journal builder (spec 10.1).

Pure: state + ranking + summary + orders/fills -> one record. Never changes a
parameter, never writes files (journal.py does I/O).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, cast

import numpy as np
import pandas as pd

from config import V9
from core.dividends import etf_universe
from core.ledger import CONFIRMED_STATUSES, PRESUMED_STATUSES, moves_book
from data.sectors import sector_degraded_message

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
CONE_JSON = _ROOT / "data" / "oos_cone_5050.json"
AUDIT_PICKLE = _ROOT / "experiments" / "_sweep_cache_etf" / "audit_steps.pkl"


def _f(x, default=0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        return default if v != v else v
    except (TypeError, ValueError):
        return default


def _first(ranking: pd.DataFrame | None, col: str, default=None):
    if ranking is None or col not in ranking.columns or len(ranking) == 0:
        return default
    v = ranking[col].iloc[0]
    if isinstance(v, (list, dict)):
        return v
    try:
        if pd.isna(v):
            return default
    except (TypeError, ValueError):
        pass
    return v


def _held_units(state: dict) -> dict[str, dict[str, float]]:
    """sleeve -> {ticker: units} aggregated across tranches."""
    out: dict[str, dict[str, float]] = {"stocks": {}, "etf": {}}
    for sleeve, blob in (state.get("sleeves") or {}).items():
        acc = out.setdefault(sleeve, {})
        for tr in blob.get("tranches") or []:
            for t, u in (tr.get("units") or {}).items():
                acc[t] = acc.get(t, 0.0) + _f(u)
    return out


def _last_px(state: dict, sleeve: str, ticker: str) -> float | None:
    for tr in ((state.get("sleeves") or {}).get(sleeve) or {}).get("tranches") or []:
        px = (tr.get("last_px") or {}).get(ticker)
        if px is not None:
            return _f(px)
    return None


def basket_vol63(prices: pd.DataFrame | None, tickers: Iterable[str]) -> float | None:
    if prices is None or len(prices) < 64:
        return None
    cols = [t for t in tickers if t in prices.columns]
    if not cols:
        return None
    rets = prices[cols].pct_change(fill_method=None).iloc[-63:]
    basket = rets.mean(axis=1).dropna()
    if len(basket) < 10:
        return None
    return float(basket.std(ddof=1) * np.sqrt(252))


def _slippage_bp(fills: list) -> dict:
    rows = []
    for f in fills or []:
        # canonical projection: `("filled", "confirmed")` dropped confirmed_unplanned,
        # so slippage on a fill Lucas made off-sheet was invisible
        if not moves_book(f.get("status")):
            continue
        if f.get("side") not in ("buy", "sell"):
            continue
        est, px = _f(f.get("est_price"), default=float("nan")), _f(f.get("price"), default=float("nan"))
        if not (est > 0 and px > 0):
            continue
        raw = (px / est - 1.0) * 10000.0
        adverse = raw if f.get("side") == "buy" else -raw
        modelled = 10.0 if f.get("sleeve") == "stocks" else 5.0
        rows.append(dict(sleeve=f.get("sleeve"), ticker=f.get("ticker"), side=f.get("side"),
                         slippage_bp=round(adverse, 2), modelled_bp=modelled,
                         vs_modelled_bp=round(adverse - modelled, 2)))
    by_s: dict[str, list[float]] = {}
    for r in rows:
        by_s.setdefault(r["sleeve"], []).append(r["slippage_bp"])
    return {
        "n": len(rows),
        "mean_bp": round(float(np.mean([r["slippage_bp"] for r in rows])), 2) if rows else None,
        "by_sleeve_mean_bp": {k: round(float(np.mean(v)), 2) for k, v in by_s.items()},
        "rows": rows,
    }


def percentile_of(x: float, dist: Iterable[float]) -> float | None:
    arr = np.asarray(list(dist), dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0 or not np.isfinite(x):
        return None
    return float((arr <= x).mean() * 100.0)


def cone(dist: Iterable[float], n_steps: int) -> dict | None:
    """5/50/95 of overlapping n-step compounded returns from the OOS step series."""
    r = np.asarray(list(dist), dtype=float)
    r = r[np.isfinite(r)]
    n = int(n_steps)
    if n <= 0 or len(r) < n:
        return None
    windows = np.array([(1.0 + r[i:i + n]).prod() - 1.0 for i in range(len(r) - n + 1)])
    return dict(
        n_steps=n,
        n_windows=int(len(windows)),
        p5=round(float(np.percentile(windows, 5)) * 100, 2),
        p50=round(float(np.percentile(windows, 50)) * 100, 2),
        p95=round(float(np.percentile(windows, 95)) * 100, 2),
    )


def load_cone_table(path: str | os.PathLike | None = None) -> dict | None:
    """Tracked JSON first (TASK-381). None if missing/unreadable."""
    p = Path(path) if path is not None else CONE_JSON
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def cone_from_table(table: dict, n_steps: int) -> dict | None:
    rec = (table.get("horizons") or {}).get(str(int(n_steps)))
    if not rec:
        return None
    out = dict(n_steps=int(n_steps))
    for k in ("n_windows", "p5", "p25", "p50", "p75", "p95"):
        if k in rec:
            out[k] = rec[k]
    return out


def load_oos_step_returns(pickle_path: str | os.PathLike | None = None) -> list[float]:
    """JSON step_returns first; pickle P_5050.net only as fallback."""
    table = load_cone_table()
    if table and table.get("step_returns"):
        return [float(x) for x in table["step_returns"]]
    p = Path(pickle_path) if pickle_path is not None else AUDIT_PICKLE
    if not p.exists():
        return []
    try:
        blob = pd.read_pickle(p)
    except Exception:
        return []
    mix = blob.get("P_5050") if isinstance(blob, dict) else None
    if mix is None or "net" not in getattr(mix, "columns", []):
        return []
    return [float(x) for x in mix["net"].dropna().tolist()]


def build_record(
    *,
    date: str,
    state: dict | None,
    ranking: pd.DataFrame | None = None,
    summary: dict | None = None,
    orders: list | None = None,
    fills: list | None = None,
    preflight: dict | None = None,
    reconcile: dict | None = None,
    prices: pd.DataFrame | None = None,
    etf: pd.DataFrame | None = None,
    irx=None,
    prior_total: float | None = None,
    live_curve: list | None = None,
    oos_step_returns: Iterable[float] | None = None,
    errors: list | None = None,
    observations: list | None = None,
    last_bars: dict | None = None,
    manifest_path: str | None = None,
) -> dict:
    """One journal record. Missing pieces become None / empty, never a crash."""
    state = state or {}
    summary = summary or {}
    orders = list(orders or [])
    fills = list(fills or [])
    sleeves = summary.get("sleeves") or {}
    held = _held_units(state)

    rec_n = _first(ranking, "recommended_count")
    try:
        rec_n = int(rec_n) if rec_n is not None else None
    except (TypeError, ValueError):
        rec_n = None

    displaced = []
    if ranking is not None and "sector_penalty_applied" in ranking.columns:
        flag = ranking["sector_penalty_applied"].fillna(False).astype(bool)
        tickers = ranking["ticker"] if "ticker" in ranking.columns else pd.Series(ranking.index)
        sectors = ranking["sector"] if "sector" in ranking.columns else None
        for i, on in enumerate(flag.tolist()):
            if not on:
                continue
            displaced.append({
                "ticker": str(tickers.iloc[i]),
                "sector": None if sectors is None else str(sectors.iloc[i]),
                "rank": int(ranking["rank"].iloc[i]) if "rank" in ranking.columns else i + 1,
            })

    etf_on, etf_w = [], {}
    etf_val = _f((sleeves.get("etf") or {}).get("value"))
    for t, u in held.get("etf", {}).items():
        if abs(u) < 1e-12:
            continue
        etf_on.append(t)
        px = _last_px(state, "etf", t)
        if etf_val > 0 and px is not None:
            etf_w[t] = round(u * px / etf_val, 4)
    etf_off = [t for t in etf_universe() if t not in etf_on]

    stock_expo = _f((sleeves.get("stocks") or {}).get("exposure"))
    vol = basket_vol63(prices, held.get("stocks", {}).keys())
    target = float(cast(float, V9.get("stock_target_vol", 0.15)))
    expo_rule = None if vol is None or vol <= 0 else round(min(1.0, target / vol), 4)

    coverage = None
    if prices is not None and len(prices) and len(prices.columns):
        coverage = round(float(pd.to_numeric(prices.iloc[-1], errors="coerce").notna().mean()), 4)

    bars = last_bars or {}
    if not bars:
        def _ld(frame):
            if frame is None or len(frame) == 0:
                return None
            return str(pd.Timestamp(frame.index[-1]).date())
        bars = {"stocks": _ld(prices), "etf": _ld(etf), "^IRX": _ld(irx)}

    presumed = [f for f in fills if str(f.get("status") or "") in PRESUMED_STATUSES]
    confirmed = [f for f in fills if str(f.get("status") or "") in CONFIRMED_STATUSES]
    interest_today = [x for x in (state.get("interest") or []) if str(x.get("date")) == date]
    interest_dollars = round(sum(_f(x.get("dollars")) for x in interest_today), 6)
    wo = [w for w in (state.get("write_offs") or []) if str(w.get("date")) == date]

    total = _f(summary.get("total"))
    step_ret = None
    if prior_total and prior_total > 0 and total:
        step_ret = total / prior_total - 1.0
    oos = list(oos_step_returns or [])
    live_n = 0
    if live_curve:
        live_n = max(0, len(live_curve) - 1)
    pct = percentile_of(step_ret, oos) if step_ret is not None else None
    cap = _f(state.get("capital_reference"), default=0.0)
    live_cum = (total / cap - 1.0) if cap > 0 and total else None
    live_cone = cone(oos, live_n) if live_n and oos else None
    if live_cone is None and live_n:
        table = load_cone_table()
        if table:
            live_cone = cone_from_table(table, live_n)

    seen = dict(
        regime_score=_first(ranking, "regime"),
        # the ranking contract (SPEC 7) names the column `regime_type`; the pre-rename name is kept
        # as a fallback (found by the TASK-383 rehearsal: the label was always None)
        regime_label=_first(ranking, "regime_type") if _first(ranking, "regime_type") is not None
        else _first(ranking, "meta_regime_type"),
        recommended_count=rec_n,
        recommended_n=int(ranking["recommended"].sum()) if ranking is not None and "recommended" in ranking.columns else None,
        stock_exposure=stock_expo,
        basket_vol63=None if vol is None else round(vol, 4),
        vol_target_exposure=expo_rule,
        etf_on=sorted(etf_on),
        etf_off=etf_off,
        etf_weights=etf_w,
        sector_cap_displaced=displaced,
        degraded=sector_degraded_message(ranking),
        coverage=coverage,
        last_bars=bars,
    )
    did = dict(
        orders=[{"sleeve": o.get("sleeve"), "tranche": o.get("tranche"), "side": o.get("side"),
                 "ticker": o.get("ticker"), "dollars": _f(o.get("dollars"))} for o in orders],
        n_orders=len(orders),
        fills_presumed=len(presumed),
        fills_confirmed=len(confirmed),
        slippage=_slippage_bp(fills),
        not_filled=sum(1 for f in fills if f.get("status") == "not_filled"),
        hold_no_price=sum(1 for f in fills if f.get("side") == "hold_no_price"),
        write_offs=len(wo),
        write_off_dollars=round(sum(_f(w.get("proceeds")) for w in wo), 6),
        transfers=sum(1 for o in orders if str(o.get("side", "")).startswith("transfer")),
        interest_dollars=interest_dollars,
    )
    book = dict(
        total=total,
        capital_reference=cap,
        week_index=state.get("week_index"),
        last_renewal_date=state.get("last_renewal_date"),
        sleeves={
            name: dict(value=_f(sl.get("value")), share=_f(sl.get("share")),
                       cash=_f(sl.get("cash")), exposure=_f(sl.get("exposure")),
                       distinct=sl.get("distinct"), names=list(sl.get("names") or []))
            for name, sl in sleeves.items()
        },
    )
    expectation = dict(
        step_return=None if step_ret is None else round(step_ret, 6),
        step_return_percentile=None if pct is None else round(pct, 1),
        live_cumulative=None if live_cum is None else round(live_cum, 6),
        cone=live_cone,
        oos_source="injected" if oos else None,
    )
    process = dict(
        preflight=None if preflight is None else {
            "hard": bool(preflight.get("hard")),
            "warn": bool(preflight.get("warn")),
            "ok": bool(preflight.get("ok", not preflight.get("hard"))),
            "rows": list(preflight.get("rows") or []),
        },
        reconcile_residual=None if reconcile is None else reconcile.get("residual"),
        errors=list(errors or []),
        manifest_path=manifest_path,      # TASK-359: which run produced this record
    )
    return dict(
        date=date,
        algo_version=state.get("algo_version") or "v9",
        schema="journal-1",
        seen=seen,
        did=did,
        book=book,
        expectation=expectation,
        process=process,
        attribution=_attribution_block(state),
        observations=list(observations or []),
    )


def _attribution_block(state: dict) -> dict | None:
    """TASK-367: cumulative components (no per-position list). None for an empty state."""
    if not state or not state.get("sleeves"):
        return None
    try:
        from analytics.attribution import attribution
        block = attribution(state)
    except Exception:
        return None
    return {k: v for k, v in block.items() if k != "positions"}


def render_markdown(records: list[dict]) -> str:
    """Human JOURNAL.md from a list of records (oldest first)."""
    lines = ["# HYDRA v9 journal", "",
             "Automatic rollup (spec 10.1). Does not change any parameter.", ""]
    for rec in records:
        date = rec.get("date")
        book = rec.get("book") or {}
        seen = rec.get("seen") or {}
        did = rec.get("did") or {}
        exp = rec.get("expectation") or {}
        proc = rec.get("process") or {}
        tot = book.get("total")
        lines += [f"## {date}", ""]
        if tot is not None:
            lines.append(f"Book **{tot:,.2f}**  week {book.get('week_index')}  "
                         f"renewal {book.get('last_renewal_date') or '—'}")
        lines.append(f"Regime {seen.get('regime_score')} ({seen.get('regime_label')})  "
                     f"rec {seen.get('recommended_n')}/{seen.get('recommended_count')}  "
                     f"expo {seen.get('stock_exposure')}  vol63 {seen.get('basket_vol63')}")
        if seen.get("degraded"):
            lines.append(f"DEGRADED {seen['degraded']}")
        lines.append(f"ETF on {seen.get('etf_on')}  off {seen.get('etf_off')}")
        disp = seen.get("sector_cap_displaced") or []
        if disp:
            lines.append("Sector-cap displaced: " + ", ".join(
                f"{d.get('ticker')}({d.get('sector')})" for d in disp))
        lines.append(f"Orders {did.get('n_orders')}  presumed {did.get('fills_presumed')}  "
                     f"confirmed {did.get('fills_confirmed')}  not_filled {did.get('not_filled')}  "
                     f"hold_no_price {did.get('hold_no_price')}  write-offs {did.get('write_offs')}  "
                     f"transfers {did.get('transfers')}  interest {did.get('interest_dollars')}")
        slip = (did.get("slippage") or {}).get("mean_bp")
        lines.append(f"Slippage mean {slip} bp vs modelled 10/5.")
        if exp.get("step_return") is not None:
            lines.append(f"Step return {100 * exp['step_return']:.2f}%  "
                         f"percentile {exp.get('step_return_percentile')}  "
                         f"live cum {exp.get('live_cumulative')}")
        cone = exp.get("cone")
        if cone:
            lines.append(f"Cone {cone.get('n_steps')} steps: "
                         f"5/50/95 = {cone.get('p5')}/{cone.get('p50')}/{cone.get('p95')} %")
        pf = proc.get("preflight") or {}
        if pf:
            lines.append(f"Preflight hard={pf.get('hard')} warn={pf.get('warn')}")
        if proc.get("reconcile_residual") is not None:
            lines.append(f"Reconcile residual {proc['reconcile_residual']}")
        if proc.get("errors"):
            lines.append("Errors: " + "; ".join(map(str, proc["errors"])))
        for note in rec.get("observations") or []:
            lines.append(f"> {note}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
