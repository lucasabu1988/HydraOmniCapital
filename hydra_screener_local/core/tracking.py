"""
Tracking de rendimiento forward para el Screener HYDRA Local.

Calcula retornos 5d/10d de los candidatos recomendados y genera
reportes de win-rate por regimen y Special Mode.
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from config import COST_BP_PER_SIDE
from core.history import list_available_dates, load_daily_run
from utils.trading_calendar import first_bar_after, bar_ahead

HISTORY_DIR = "history"
TRACKING_DIR = "history/tracking"
DEFAULT_HORIZONS = [5, 10]          # TRADING days (bars), see TRACKING_SCHEMA_VERSION 2

# v1 measured horizons in calendar days and entered at the observed close. On 2020-2026 data
# that made "5d" mean 3 trading days in 65% of cycles and understated the strategy by
# ~18 bp/cycle (audit 2026-09-06, T1). v2 counts bars and enters at the first bar after the
# signal - the earliest price anyone can actually get. Files below this version are recomputed.
TRACKING_SCHEMA_VERSION = 2


def _ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def _tracking_path(date: str) -> str:
    return os.path.join(TRACKING_DIR, f"{date}.json")


def load_tracking(date: str) -> Dict:
    path = _tracking_path(date)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_tracking(date: str, data: Dict):
    _ensure_dir(TRACKING_DIR)
    with open(_tracking_path(date), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def _get_unique_recommended_tickers(runs: List[Dict]) -> List[str]:
    tickers = set()
    for run in runs:
        for c in run.get("top_candidates", []):
            if c.get("recommended"):
                tickers.add(c["ticker"])
    return sorted(tickers)


def _fetch_prices(tickers: List[str], start: str, end: str) -> pd.DataFrame:
    """Descarga precios de cierre para tracking."""
    if not tickers:
        return pd.DataFrame()

    try:
        data = yf.download(
            tickers,
            start=start,
            end=end,
            progress=False,
            auto_adjust=True,
            threads=True,
        )
    except Exception as e:
        print(f"ERROR descargando precios: {e}")
        return pd.DataFrame()

    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"]
    else:
        close = data[["Close"]].rename(columns={"Close": tickers[0]})

    return close


def _nearest_price(series: pd.Series, target_date: datetime, max_offset: int = 5) -> Optional[float]:
    """Busca precio en target_date o dias habiles siguientes."""
    if not isinstance(series.index, pd.DatetimeIndex):
        series.index = pd.to_datetime(series.index)

    for offset in range(max_offset):
        try_date = pd.Timestamp(target_date + timedelta(days=offset))
        mask = series.index.normalize() == try_date.normalize()
        if mask.any():
            val = series.loc[mask].iloc[-1]
            if pd.notna(val):
                return float(val)
    return None


def compute_forward_returns_for_run(run: Dict, prices_df: pd.DataFrame, horizons: List[int] = None) -> Dict:
    """Forward returns for one screener run, measured the way the strategy is meant to trade.

    Entry  = close of the first bar strictly AFTER the signal bar (the bar the screener saw).
    Exit   = entry bar + h BARS. Horizons are trading days by construction.
    Both positions come from the panel index, so every ticker in a run shares the same
    calendar and a holiday or a data gap cannot stretch one name's horizon and not another's.

    Names that cannot be measured are listed under `omitted` with a reason instead of being
    dropped silently - a delisted or acquired name vanishing from the win-rate is survivorship
    bias in the live measurement (audit T2).
    """
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    run_date_str = run["date"]
    run_date = datetime.strptime(run_date_str, "%Y%m%d")
    # Runs since history schema v2 record the last bar they actually scored. Older runs did
    # not; the run date is the best available proxy for the signal bar.
    signal_date = pd.Timestamp(run.get("data_last_bar") or run_date)

    if not isinstance(prices_df.index, pd.DatetimeIndex):
        prices_df.index = pd.to_datetime(prices_df.index)
    idx = prices_df.index

    results = {
        "schema_version": TRACKING_SCHEMA_VERSION,
        "horizon_basis": "trading_days",
        "entry_basis": "first_close_after_signal",
        "date": run_date_str,
        "signal_date": signal_date.strftime("%Y-%m-%d"),
        "regime": run.get("regime", {}),
        # provenance: which run produced the signal and which prices measured it, so a later
        # update can tell "the history file changed" from "more bars arrived" (audit finding C)
        "run_schema_version": run.get("schema_version", 1),
        "recommended_snapshot": sorted({c["ticker"] for c in run.get("top_candidates", []) if c.get("recommended")}),
        "price_source": "yfinance",
        "candidates": [],
        "omitted": [],
    }

    entry_pos = first_bar_after(idx, signal_date)
    last_pos = len(idx) - 1

    seen = set()
    for c in run.get("top_candidates", []):
        if not c.get("recommended"):
            continue
        ticker = c["ticker"]
        if ticker in seen:
            continue                      # malformed history: measure a ticker once (review 336)
        seen.add(ticker)

        if ticker not in prices_df.columns:
            results["omitted"].append({"ticker": ticker, "reason": "no_price_data"})
            continue
        if entry_pos is None:
            results["omitted"].append({"ticker": ticker, "reason": "no_bar_after_signal_yet"})
            continue

        entry_price = prices_df[ticker].iloc[entry_pos]
        if pd.isna(entry_price) or entry_price <= 0:
            results["omitted"].append({"ticker": ticker, "reason": "no_entry_price"})
            continue
        entry_price = float(entry_price)

        candidate = {
            "ticker": ticker,
            "entry_price": round(entry_price, 4),
            "entry_date": idx[entry_pos].strftime("%Y-%m-%d"),
            "returns": {},
            "status": {},        # per horizon: measured | pending | unmeasurable (with reason)
        }

        series = prices_df[ticker]
        for h in horizons:
            key = f"return_{h}d"
            exit_pos = bar_ahead(idx, entry_pos, h)
            if exit_pos is None:
                candidate["returns"][key] = None
                candidate["status"][f"{h}d"] = {"state": "pending", "reason": "exit_bar_not_yet_available"}
                continue
            exit_price = series.iloc[exit_pos]
            if pd.isna(exit_price):
                candidate["returns"][key] = None
                later = series.iloc[exit_pos + 1:].notna().any()
                if later:
                    # the name trades again after the exit bar: this is a hole in the data, not a delisting
                    candidate["status"][f"{h}d"] = {"state": "unmeasurable", "reason": "no_price_at_exit_bar"}
                elif last_pos - exit_pos >= UNMEASURABLE_AFTER_BARS:
                    candidate["status"][f"{h}d"] = {"state": "unmeasurable", "reason": "delisted_or_missing_after_exit"}
                else:
                    candidate["status"][f"{h}d"] = {"state": "pending", "reason": "no_price_yet_at_exit_bar"}
                continue
            candidate["returns"][key] = round(float(exit_price) / entry_price - 1, 4)
            candidate["returns"][f"exit_price_{h}d"] = round(float(exit_price), 4)
            candidate["returns"][f"exit_date_{h}d"] = idx[exit_pos].strftime("%Y-%m-%d")
            candidate["status"][f"{h}d"] = {"state": "measured"}

        results["candidates"].append(candidate)

    return results


RETRYABLE_OMISSIONS = {"no_price_data", "no_bar_after_signal_yet", "no_entry_price"}   # holes a later download can fill
UNMEASURABLE_AFTER_BARS = 10     # a NaN exit bar with this many later bars and still no price = gone


def needs_update(existing: Optional[Dict], run: Dict) -> Tuple[bool, str]:
    """Should this run's tracking be (re)computed? Returns (decision, reason).

    A v2 file used to be skipped for good as soon as it had candidates, even with every
    horizon still None (audit finding C). Now a file is final only when nothing is pending,
    nothing omitted is retryable, and the run it measured has not changed underneath it.
    """
    if not existing:
        return True, "no_tracking_yet"
    if existing.get("schema_version", 1) < TRACKING_SCHEMA_VERSION:
        return True, "older_schema"
    snapshot = sorted({c["ticker"] for c in run.get("top_candidates", []) if c.get("recommended")})
    known = existing.get("recommended_snapshot")
    if known is None:
        # pre-provenance v2 file: the set it measured is what it lists (candidates + omitted)
        known = sorted({c["ticker"] for c in existing.get("candidates", [])} | {o["ticker"] for o in existing.get("omitted", [])})
    if sorted(known) != snapshot:
        return True, "history_recommended_set_changed"
    signal_date = pd.Timestamp(run.get("data_last_bar") or datetime.strptime(run["date"], "%Y%m%d")).strftime("%Y-%m-%d")
    if existing.get("signal_date") != signal_date:
        return True, "signal_date_changed"
    if any(o.get("reason") in RETRYABLE_OMISSIONS for o in existing.get("omitted", [])):
        return True, "retryable_omissions"
    for c in existing.get("candidates", []):
        status = c.get("status")
        if status is None:
            # pre-status v2 file: any None return is pending by definition
            if any(v is None for k, v in c.get("returns", {}).items() if k.startswith("return_")):
                return True, "pending_returns"
            continue
        if any(s.get("state") == "pending" for s in status.values()):
            return True, "pending_returns"
    return False, "complete"


def update_tracking(force_recompute: bool = False):
    """Calcula o actualiza tracking para todas las corridas historicas."""
    dates = list_available_dates()
    if not dates:
        print("No hay historial disponible.")
        return

    runs = [load_daily_run(d) for d in dates]

    # Determinar rango de fechas necesario. Horizons are in bars, so ask for enough calendar
    # days to contain max(horizon) bars plus weekends/holidays with margin.
    first_date = datetime.strptime(min(dates), "%Y%m%d") - timedelta(days=10)
    last_date = datetime.strptime(max(dates), "%Y%m%d") + timedelta(days=max(DEFAULT_HORIZONS) * 2 + 10)
    today = datetime.now()

    # No pedir fechas futuras innecesarias
    if last_date > today:
        last_date = today

    tickers = _get_unique_recommended_tickers(runs)
    if not tickers:
        print("No hay tickers recomendados en el historial.")
        return

    # yfinance 'end' es exclusivo; sumamos 1 dia para incluir last_date
    end_exclusive = (last_date + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Descargando precios para {len(tickers)} tickers desde {first_date.date()} hasta {last_date.date()}...")
    prices_df = _fetch_prices(tickers, first_date.strftime("%Y-%m-%d"), end_exclusive)

    if prices_df.empty:
        print("No se pudieron descargar precios.")
        return

    updated = 0
    skipped = 0
    omitted_total = 0
    pending_total = 0
    for run in runs:
        date = run["date"]
        if not force_recompute:
            existing = load_tracking(date)
            redo, why = needs_update(existing, run)
            if not redo:
                skipped += 1
                continue
            if why == "history_recommended_set_changed":
                print(f"  AVISO {date}: la lista recomendada del history cambio desde el ultimo tracking; se recalcula")

        result = compute_forward_returns_for_run(run, prices_df)
        save_tracking(date, result)
        updated += 1
        omitted_total += len(result["omitted"])
        n_pending = sum(1 for c in result["candidates"] for s in c["status"].values() if s["state"] == "pending")
        pending_total += n_pending
        omitted_note = f", {len(result['omitted'])} omitidos" if result["omitted"] else ""
        pending_note = f", {n_pending} horizontes pendientes" if n_pending else ""
        print(f"  OK {date}: {len(result['candidates'])} candidatos trackeados{omitted_note}{pending_note}")

    print(f"\nResumen: {updated} actualizados, {skipped} completos (sin pendientes), {pending_total} horizontes aun pendientes")
    if omitted_total:
        print(f"AVISO: {omitted_total} recomendaciones sin precio de entrada o sin datos (ver 'omitted' "
              f"en cada tracking JSON). No cuentan en el win-rate; si son delistados/adquiridos, el "
              f"win-rate esta sesgado por supervivencia.")


def aggregate_winrate() -> Dict:
    """Genera reporte de win-rate por horizonte, regimen y Special Mode."""
    dates = list_available_dates()

    rows = []
    for d in dates:
        tracking = load_tracking(d)
        run = load_daily_run(d)
        regime = run.get("regime", {})

        for c in tracking.get("candidates", []):
            if not c.get("returns"):
                continue
            row = {
                "date": d,
                "ticker": c["ticker"],
                "regime_type": regime.get("type", "UNKNOWN"),
                "special_modes": regime.get("special_modes", []),
            }
            for k, v in c["returns"].items():
                if k.startswith("return_"):
                    row[k] = v
            rows.append(row)

    if not rows:
        return {"error": "No hay datos de tracking disponibles. Ejecuta update_tracking() primero."}

    df = pd.DataFrame(rows)

    rt_cost = 2.0 * COST_BP_PER_SIDE / 10000.0
    report = {
        "total_candidates_tracked": len(df),
        "unique_dates": df["date"].nunique(),
        "cost_assumption": {
            "bp_per_side": COST_BP_PER_SIDE,
            "round_trip": rt_cost,
            "label": "modelled, not fills",
        },
        "by_horizon": {},
    }

    for h in DEFAULT_HORIZONS:
        col = f"return_{h}d"
        if col not in df.columns:
            continue

        valid = df[df[col].notna()].copy()
        if valid.empty:
            continue

        wins = (valid[col] > 0).sum()
        losses = (valid[col] <= 0).sum()
        total = len(valid)
        net = valid[col] - rt_cost

        report["by_horizon"][f"{h}d"] = {
            "total": int(total),
            "wins": int(wins),
            "losses": int(losses),
            "win_rate": round(float(wins / total), 4) if total > 0 else 0.0,
            "win_rate_net": round(float((net > 0).mean()), 4) if total > 0 else 0.0,
            "avg_return": round(float(valid[col].mean()), 4),
            "avg_return_net": round(float(net.mean()), 4),
            "median_return": round(float(valid[col].median()), 4),
            "std_return": round(float(valid[col].std()), 4),
            "best": round(float(valid[col].max()), 4),
            "worst": round(float(valid[col].min()), 4),
        }

        # Por regimen
        by_regime = {}
        for reg_type, group in valid.groupby("regime_type"):
            g_wins = (group[col] > 0).sum()
            g_total = len(group)
            by_regime[reg_type] = {
                "total": int(g_total),
                "wins": int(g_wins),
                "win_rate": round(float(g_wins / g_total), 4) if g_total > 0 else 0.0,
                "avg_return": round(float(group[col].mean()), 4),
            }
        report["by_horizon"][f"{h}d"]["by_regime"] = by_regime

        # Por Special Mode (expandir lista)
        mode_rows = []
        for _, row in valid.iterrows():
            modes = row["special_modes"] if isinstance(row["special_modes"], list) else []
            if not modes:
                modes = ["NONE"]
            for m in modes:
                m = m.strip()
                if not m:
                    continue
                r = row.to_dict()
                r["_mode"] = m
                mode_rows.append(r)

        if mode_rows:
            mode_df = pd.DataFrame(mode_rows)
            by_mode = {}
            for mode, group in mode_df.groupby("_mode"):
                m_wins = (group[col] > 0).sum()
                m_total = len(group)
                by_mode[mode] = {
                    "total": int(m_total),
                    "wins": int(m_wins),
                    "win_rate": round(float(m_wins / m_total), 4) if m_total > 0 else 0.0,
                    "avg_return": round(float(group[col].mean()), 4),
                }
            report["by_horizon"][f"{h}d"]["by_special_mode"] = by_mode

    return report


def get_detailed_trades() -> pd.DataFrame:
    """Devuelve DataFrame con cada trade individual y sus retornos."""
    dates = list_available_dates()
    rows = []
    for d in dates:
        tracking = load_tracking(d)
        run = load_daily_run(d)
        regime = run.get("regime", {})

        for c in tracking.get("candidates", []):
            row = {
                "date": d,
                "ticker": c["ticker"],
                "entry_price": c.get("entry_price"),
                "regime_type": regime.get("type", "UNKNOWN"),
                "special_modes": ", ".join(regime.get("special_modes", [])) or "NONE",
            }
            for k, v in c.get("returns", {}).items():
                if k.startswith("return_"):
                    row[k] = v
                if k.startswith("exit_price_"):
                    row[k] = v
            rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def print_detailed_report(df: pd.DataFrame):
    """Muestra tabla detallada ticker por ticker."""
    if df.empty:
        print("\nNo hay trades detallados para mostrar.")
        return

    print("\n=== Detalle por Ticker ===\n")
    print(f"{'Fecha':<10} {'Ticker':<8} {'Regimen':<10} {'Special Mode':<22} {'Entry':>10} {'Exit 5d':>10} {'Ret 5d':>8} {'Net 5d':>8} {'Ret 10d':>8}")
    print("-" * 102)

    for _, r in df.iterrows():
        ret_5d = r.get("return_5d")
        ret_10d = r.get("return_10d")
        entry = r.get("entry_price")
        exit_5d = r.get("exit_price_5d")

        ret_5d_str = f"{ret_5d:>7.2%}" if pd.notna(ret_5d) else "   N/A"
        net_5d = (ret_5d - 2.0 * COST_BP_PER_SIDE / 10000.0) if pd.notna(ret_5d) else None
        net_5d_str = f"{net_5d:>7.2%}" if net_5d is not None else "   N/A"
        ret_10d_str = f"{ret_10d:>7.2%}" if pd.notna(ret_10d) else "   N/A"
        entry_str = f"{entry:>10.2f}" if pd.notna(entry) else "      N/A"
        exit_str = f"{exit_5d:>10.2f}" if pd.notna(exit_5d) else "      N/A"

        print(f"{r['date']:<10} {r['ticker']:<8} {r['regime_type']:<10} {r['special_modes']:<22} {entry_str} {exit_str} {ret_5d_str} {net_5d_str} {ret_10d_str}")

    print()


def print_winrate_report(report: Dict):
    """Muestra el reporte de win-rate en consola."""
    if "error" in report:
        print(f"\n{report['error']}")
        return

    print("\n=== HYDRA Screener - Win-Rate Report ===\n")
    print(f"Candidatos trackeados: {report['total_candidates_tracked']}")
    print(f"Dias unicos: {report['unique_dates']}")
    cost = report.get("cost_assumption") or {}
    if cost:
        print(f"Cost assumption: {cost.get('bp_per_side')} bp/side "
              f"({cost.get('label', 'modelled')}; round-trip {cost.get('round_trip', 0):.2%})\n")
    else:
        print()

    for horizon, stats in report["by_horizon"].items():
        print(f"--- Horizonte {horizon} ---")
        print(f"  Total:   {stats['total']}")
        print(f"  Wins:    {stats['wins']}  |  Losses: {stats['losses']}")
        print(f"  Win-rate: {stats['win_rate']:.2%}"
              + (f"  |  net {stats['win_rate_net']:.2%}" if "win_rate_net" in stats else ""))
        print(f"  Avg ret:  {stats['avg_return']:.2%}"
              + (f"  |  net {stats['avg_return_net']:.2%}" if "avg_return_net" in stats else ""))
        print(f"  Median:   {stats['median_return']:.2%}")
        print(f"  Std:      {stats['std_return']:.2%}")
        print(f"  Best:     {stats['best']:.2%}  |  Worst: {stats['worst']:.2%}")
        print()

        if stats.get("by_regime"):
            print("  Por Regimen:")
            for reg, s in sorted(stats["by_regime"].items(), key=lambda x: -x[1]["win_rate"]):
                print(f"    {reg:12s}  WR: {s['win_rate']:.2%}  ({s['wins']}/{s['total']})  Avg: {s['avg_return']:.2%}")
            print()

        if stats.get("by_special_mode"):
            print("  Por Special Mode:")
            for mode, s in sorted(stats["by_special_mode"].items(), key=lambda x: -x[1]["win_rate"]):
                print(f"    {mode:25s}  WR: {s['win_rate']:.2%}  ({s['wins']}/{s['total']})  Avg: {s['avg_return']:.2%}")
            print()
