"""
Tracking de rendimiento forward para el Screener HYDRA Local.

Calcula retornos 5d/10d de los candidatos recomendados y genera
reportes de win-rate por regimen y Special Mode.
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from core.history import list_available_dates, load_daily_run

HISTORY_DIR = "history"
TRACKING_DIR = "history/tracking"
DEFAULT_HORIZONS = [5, 10]


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
    """Calcula retornos forward para una corrida dada."""
    if horizons is None:
        horizons = DEFAULT_HORIZONS

    run_date_str = run["date"]
    run_date = datetime.strptime(run_date_str, "%Y%m%d")

    if not isinstance(prices_df.index, pd.DatetimeIndex):
        prices_df.index = pd.to_datetime(prices_df.index)

    results = {
        "date": run_date_str,
        "regime": run.get("regime", {}),
        "candidates": [],
    }

    for c in run.get("top_candidates", []):
        if not c.get("recommended"):
            continue

        ticker = c["ticker"]
        if ticker not in prices_df.columns:
            continue

        series = prices_df[ticker].dropna()
        if series.empty:
            continue

        entry_price = _nearest_price(series, run_date, max_offset=5)
        if entry_price is None or entry_price <= 0:
            continue

        candidate = {
            "ticker": ticker,
            "entry_price": round(entry_price, 4),
            "entry_date": run_date.strftime("%Y-%m-%d"),
            "returns": {},
        }

        for h in horizons:
            target_date = run_date + timedelta(days=h)
            exit_price = _nearest_price(series, target_date, max_offset=7)
            if exit_price is not None:
                ret = (exit_price / entry_price) - 1
                candidate["returns"][f"return_{h}d"] = round(ret, 4)
                candidate["returns"][f"exit_price_{h}d"] = round(exit_price, 4)
            else:
                candidate["returns"][f"return_{h}d"] = None

        results["candidates"].append(candidate)

    return results


def update_tracking(force_recompute: bool = False):
    """Calcula o actualiza tracking para todas las corridas historicas."""
    dates = list_available_dates()
    if not dates:
        print("No hay historial disponible.")
        return

    runs = [load_daily_run(d) for d in dates]

    # Determinar rango de fechas necesario
    first_date = datetime.strptime(min(dates), "%Y%m%d") - timedelta(days=10)
    last_date = datetime.strptime(max(dates), "%Y%m%d") + timedelta(days=max(DEFAULT_HORIZONS) + 10)
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
    for run in runs:
        date = run["date"]
        if not force_recompute:
            existing = load_tracking(date)
            if existing and existing.get("candidates"):
                skipped += 1
                continue

        result = compute_forward_returns_for_run(run, prices_df)
        save_tracking(date, result)
        updated += 1
        print(f"  OK {date}: {len(result['candidates'])} candidatos trackeados")

    print(f"\nResumen: {updated} actualizados, {skipped} saltados (ya tenian tracking)")


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

    report = {
        "total_candidates_tracked": len(df),
        "unique_dates": df["date"].nunique(),
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

        report["by_horizon"][f"{h}d"] = {
            "total": int(total),
            "wins": int(wins),
            "losses": int(losses),
            "win_rate": round(float(wins / total), 4) if total > 0 else 0.0,
            "avg_return": round(float(valid[col].mean()), 4),
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
    print(f"{'Fecha':<10} {'Ticker':<8} {'Regimen':<10} {'Special Mode':<22} {'Entry':>10} {'Exit 5d':>10} {'Ret 5d':>8} {'Ret 10d':>8}")
    print("-" * 92)

    for _, r in df.iterrows():
        ret_5d = r.get("return_5d")
        ret_10d = r.get("return_10d")
        entry = r.get("entry_price")
        exit_5d = r.get("exit_price_5d")

        ret_5d_str = f"{ret_5d:>7.2%}" if pd.notna(ret_5d) else "   N/A"
        ret_10d_str = f"{ret_10d:>7.2%}" if pd.notna(ret_10d) else "   N/A"
        entry_str = f"{entry:>10.2f}" if pd.notna(entry) else "      N/A"
        exit_str = f"{exit_5d:>10.2f}" if pd.notna(exit_5d) else "      N/A"

        print(f"{r['date']:<10} {r['ticker']:<8} {r['regime_type']:<10} {r['special_modes']:<22} {entry_str} {exit_str} {ret_5d_str} {ret_10d_str}")

    print()


def print_winrate_report(report: Dict):
    """Muestra el reporte de win-rate en consola."""
    if "error" in report:
        print(f"\n{report['error']}")
        return

    print("\n=== HYDRA Screener - Win-Rate Report ===\n")
    print(f"Candidatos trackeados: {report['total_candidates_tracked']}")
    print(f"Dias unicos: {report['unique_dates']}\n")

    for horizon, stats in report["by_horizon"].items():
        print(f"--- Horizonte {horizon} ---")
        print(f"  Total:   {stats['total']}")
        print(f"  Wins:    {stats['wins']}  |  Losses: {stats['losses']}")
        print(f"  Win-rate: {stats['win_rate']:.2%}")
        print(f"  Avg ret:  {stats['avg_return']:.2%}")
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
