"""
Analizador de Histórico del Screener HYDRA Local.

Permite ver el rendimiento de las recomendaciones pasadas.
Incluye backtest persistente de las reglas nuevas (composite + short-term boost)
vs el método original.
"""
import json
import os
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
import numpy as np

from core.history import get_recent_runs, list_available_dates
from config import GEOPOLITICAL_RISK_LEVEL, GEO_VOL_THRESHOLD_ADJUST, VOL_SURGE_THRESHOLD, MIN_VOL_THRESHOLD

BACKTEST_DIR = "backtest"
BACKTEST_FILE = os.path.join(BACKTEST_DIR, "backtest_results.json")


def show_summary():
    dates = list_available_dates()
    print(f"\n=== Histórico disponible ===")
    print(f"Total de días guardados: {len(dates)}")
    if dates:
        print(f"Rango: {dates[0]} -> {dates[-1]}")
    print()


def show_last_runs(limit: int = 10):
    runs = get_recent_runs(limit)
    print(f"\n=== Últimos {len(runs)} días ===\n")

    for run in runs:
        date = run["date"]
        regime = run.get("regime", {})
        pillars = run.get("pillar_multipliers", {})
        candidates = run.get("top_candidates", [])

        print(f"Date: {date}")
        print(f"   Régimen: {regime.get('score', 0):.2f} ({regime.get('type', '')})")
        if regime.get("special_modes"):
            print(f"   Special Modes: {', '.join(regime['special_modes'])}")

        if pillars:
            print("   Multipliers:", end=" ")
            for p, m in pillars.items():
                print(f"{p}={m:.2f}", end="  ")
            print()

        if candidates:
            recs = [c for c in candidates if c.get("recommended")]
            print(f"   Recomendados ese día: {len(recs)}")
        print()


def load_backtest_results():
    """Carga el historial acumulado de backtests."""
    if os.path.exists(BACKTEST_FILE):
        with open(BACKTEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_updated": None, "results_by_date": {}, "summary": {}}


def save_backtest_results(results: dict):
    """Guarda los resultados del backtest de forma persistente."""
    os.makedirs(BACKTEST_DIR, exist_ok=True)
    results["last_updated"] = datetime.now().isoformat()
    with open(BACKTEST_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"  [OK] Backtest guardado en {BACKTEST_FILE}")


def evaluate_signal_day(signal_date: str, forward_days: int = 1):
    """
    Evalúa el rendimiento forward de las recomendaciones de un día.
    Compara:
      - Método original (por meta_score)
      - Método nuevo (por composite_score, si existe en el history)
    """
    history_file = f"history/{signal_date}.json"
    if not os.path.exists(history_file):
        return None

    with open(history_file, "r", encoding="utf-8") as f:
        hist = json.load(f)

    recs = [c for c in hist.get("top_candidates", []) if c.get("recommended")]
    if not recs:
        return None

    tickers = [c["ticker"] for c in recs]

    # Fechas forward
    signal_dt = datetime.strptime(signal_date, "%Y%m%d")
    forward_dates = []
    for i in range(1, forward_days + 1):
        fwd = (signal_dt + timedelta(days=i)).strftime("%Y-%m-%d")
        forward_dates.append(fwd)

    # Descargar precios + volumen (necesario para el strict filter completo)
    try:
        price_data = yf.download(tickers + ["SPY"], start=signal_dt.strftime("%Y-%m-%d"), 
                                  end=(signal_dt + timedelta(days=forward_days+5)).strftime("%Y-%m-%d"),
                                  progress=False, auto_adjust=True)
        if isinstance(price_data.columns, pd.MultiIndex):
            closes = price_data["Close"]
            volumes = price_data["Volume"]
        else:
            closes = price_data
            volumes = None   # fallback, unlikely
    except Exception as e:
        print(f"  Error descargando precios forward para {signal_date}: {e}")
        return None

    results = []
    for c in recs:
        t = c["ticker"]
        try:
            entry_price = float(closes[t].loc[signal_dt.strftime("%Y-%m-%d")])
            fwd_prices = []
            for fd in forward_dates:
                if fd in closes.index.strftime("%Y-%m-%d"):
                    p = float(closes[t].loc[fd])
                    fwd_prices.append((fd, round((p / entry_price - 1)*100, 2)))

            # === Calcular features de corto plazo en el momento de la señal (incluyendo volumen) ===
            series = closes[t].loc[:signal_dt.strftime("%Y-%m-%d")].dropna()
            ret_5d = np.nan
            dist_to_high = np.nan
            vol_ratio = np.nan

            if len(series) >= 25:
                ret_5d = round((series.iloc[-1] / series.iloc[-6] - 1) * 100, 2)
                recent_high = series.iloc[-20:].max()
                dist_to_high = round((series.iloc[-1] / recent_high - 1) * 100, 2)

            # Volumen relativo (últimos 5 días vs promedio 20 días) en la fecha de señal
            if volumes is not None:
                try:
                    vol_series = volumes[t].loc[:signal_dt.strftime("%Y-%m-%d")].dropna()
                    if len(vol_series) >= 25:
                        avg_vol_20 = vol_series.iloc[-20:].mean()
                        avg_vol_5 = vol_series.iloc[-5:].mean()
                        if avg_vol_20 > 0:
                            vol_ratio = round(avg_vol_5 / avg_vol_20, 2)
                except Exception:
                    vol_ratio = np.nan

            if fwd_prices:
                results.append({
                    "ticker": t,
                    "meta_score": c.get("meta_score"),
                    "composite_score": c.get("composite_score", c.get("meta_score")),
                    "short_boost": c.get("short_boost", 0),
                    "ret_5d": ret_5d,
                    "dist_20d_high": dist_to_high,
                    "vol_ratio": vol_ratio,
                    "forward_returns": fwd_prices
                })
        except Exception:
            continue

    if not results:
        return None

    df = pd.DataFrame(results)

    # Selecciones
    top_original = df.sort_values("meta_score", ascending=False).head(10)
    top_new = df.sort_values("composite_score", ascending=False).head(10)

    def avg_return(selection_df, day_offset=0):
        rets = []
        for _, row in selection_df.iterrows():
            fr = row["forward_returns"]
            if len(fr) > day_offset:
                rets.append(fr[day_offset][1])
        return round(np.mean(rets), 2) if rets else None

    # === Strict Filter (las 3 reglas completas con volumen) ===
    # El umbral de volumen se ajusta SOLO según la situación geopolítica
    # NUNCA puede bajar de 1.0 (piso duro)
    dynamic_vol_threshold = VOL_SURGE_THRESHOLD + (GEOPOLITICAL_RISK_LEVEL * GEO_VOL_THRESHOLD_ADJUST)
    dynamic_vol_threshold = max(MIN_VOL_THRESHOLD, dynamic_vol_threshold)
    dynamic_vol_threshold = round(dynamic_vol_threshold, 2)

    strict_mask = (
        (df["ret_5d"] > 15) & 
        (df["dist_20d_high"] >= -2) & 
        (df["vol_ratio"] > dynamic_vol_threshold)
    )
    strict_df = df[strict_mask]

    strict_avg = avg_return(strict_df, 0) if len(strict_df) > 0 else None
    strict_winrate = round((strict_df["forward_returns"].apply(lambda x: x[0][1] > 0).mean() * 100), 0) if len(strict_df) > 0 else None

    return {
        "signal_date": signal_date,
        "n_recommended": len(recs),
        "original_top10_1d_avg": avg_return(top_original, 0),
        "new_top10_1d_avg": avg_return(top_new, 0),
        "geopolitical_risk_level": GEOPOLITICAL_RISK_LEVEL,
        "dynamic_vol_threshold": dynamic_vol_threshold,
        "strict_filter_count": int(len(strict_df)),
        "strict_filter_1d_avg": strict_avg,
        "strict_filter_win_rate": strict_winrate,
        "details": results[:5]
    }


def run_and_save_backtest():
    """Ejecuta el backtest sobre todo el histórico disponible y guarda resultados."""
    print("\n=== Ejecutando Backtest Persistente ===")
    dates = list_available_dates()
    print(f"Fechas de señal encontradas: {dates}")

    current = load_backtest_results()
    results_by_date = current.get("results_by_date", {})

    new_evaluations = 0
    for d in dates:
        if d in results_by_date:
            continue  # ya evaluado

        print(f"  Evaluando {d}...")
        eval_result = evaluate_signal_day(d, forward_days=1)
        if eval_result:
            results_by_date[d] = eval_result
            new_evaluations += 1
            print(f"    +1d Original: {eval_result['original_top10_1d_avg']}% | Nuevo: {eval_result['new_top10_1d_avg']}%")
            if eval_result.get("strict_filter_count", 0) > 0:
                print(f"      Strict Filter: {eval_result['strict_filter_count']} nombres | "
                      f"Vol threshold (geo-adjusted): {eval_result.get('dynamic_vol_threshold')} | "
                      f"+1d: {eval_result.get('strict_filter_1d_avg')}% | "
                      f"WinRate: {eval_result.get('strict_filter_win_rate')}%")

    if new_evaluations > 0:
        # Calcular summary simple
        all_orig = [v["original_top10_1d_avg"] for v in results_by_date.values() if v.get("original_top10_1d_avg") is not None]
        all_new = [v["new_top10_1d_avg"] for v in results_by_date.values() if v.get("new_top10_1d_avg") is not None]

        strict_avgs = [v["strict_filter_1d_avg"] for v in results_by_date.values() 
                       if v.get("strict_filter_1d_avg") is not None]
        strict_counts = [v["strict_filter_count"] for v in results_by_date.values() 
                         if v.get("strict_filter_count") is not None]

        summary = {
            "total_signal_days": len(results_by_date),
            "avg_original_1d": round(np.mean(all_orig), 2) if all_orig else None,
            "avg_new_1d": round(np.mean(all_new), 2) if all_new else None,
            "strict_filter": {
                "avg_1d_when_used": round(np.mean(strict_avgs), 2) if strict_avgs else None,
                "total_names_passed_across_days": int(np.sum(strict_counts)) if strict_counts else 0,
                "days_with_strict_hits": len(strict_avgs)
            },
            "days_evaluated": len(results_by_date)
        }

        final = {
            "last_updated": datetime.now().isoformat(),
            "results_by_date": results_by_date,
            "summary": summary
        }
        save_backtest_results(final)
        print(f"\nBacktest actualizado. Días nuevos evaluados: {new_evaluations}")
    else:
        print("No hay nuevos días para evaluar.")

    return load_backtest_results()


if __name__ == "__main__":
    print("=== HYDRA Screener - Analizador de Histórico ===\n")
    show_summary()
    show_last_runs(15)

    print("\n--- Backtest con reglas nuevas ---")
    bt = run_and_save_backtest()

    if bt.get("summary"):
        s = bt["summary"]
        print(f"\nResumen acumulado:")
        print(f"  Días evaluados: {s.get('total_signal_days')}")
        print(f"  Promedio Original (Top10): {s.get('avg_original_1d')}%")
        print(f"  Promedio Nuevas Reglas (Top10): {s.get('avg_new_1d')}%")

        strict = s.get("strict_filter", {})
        if strict.get("avg_1d_when_used"):
            print(f"  Strict Filter - Promedio cuando aplicó: {strict['avg_1d_when_used']}% "
                  f"(sobre {strict.get('total_names_passed_across_days', 0)} nombres en {strict.get('days_with_strict_hits', 0)} días)")