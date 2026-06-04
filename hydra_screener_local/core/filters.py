"""
Filtros prácticos para el Screener HYDRA Local.

Mantener la estructura ligera.
"""
import pandas as pd
from typing import List, Dict


def apply_practical_filters(
    prices: pd.DataFrame,
    volumes: pd.DataFrame = None,
    min_avg_volume: int = 1_000_000,
    min_price: float = 5.0,
    max_price: float = None,
    exclude_sectors: List[str] = None,
) -> tuple[pd.DataFrame, Dict]:
    """
    Aplica filtros básicos de liquidez y precio.
    Retorna (DataFrame filtrado, breakdown dict).

    Nota: Para filtros por sector reales necesitaríamos metadata de sectores.
    Por ahora solo implementamos liquidez y precio (lo más útil y ligero).
    """
    original_tickers = set(prices.columns)
    filtered = prices.copy()
    breakdown = {}

    # 1. Filtro de liquidez (volumen promedio de los últimos 20 días)
    if min_avg_volume > 0:
        if volumes is not None:
            aligned_vol = volumes[filtered.columns]
            recent_volume = aligned_vol.iloc[-20:].mean()
            liquid_tickers = recent_volume[recent_volume >= min_avg_volume].index.tolist()
            removed_vol = len(filtered.columns) - len(liquid_tickers)
            filtered = filtered[liquid_tickers]
            breakdown["volume"] = removed_vol
        else:
            breakdown["volume"] = 0
    else:
        breakdown["volume"] = 0

    # 2. Filtro de precio mínimo
    if min_price > 0:
        before = len(filtered.columns)
        current_prices = filtered.iloc[-1]
        valid_price = current_prices[current_prices >= min_price].index.tolist()
        filtered = filtered[valid_price]
        breakdown["min_price"] = before - len(filtered.columns)
    else:
        breakdown["min_price"] = 0

    # 3. Filtro de precio máximo (opcional)
    if max_price is not None and max_price > 0:
        before = len(filtered.columns)
        current_prices = filtered.iloc[-1]
        valid_price = current_prices[current_prices <= max_price].index.tolist()
        filtered = filtered[valid_price]
        breakdown["max_price"] = before - len(filtered.columns)
    else:
        breakdown["max_price"] = 0

    breakdown["total_removed"] = len(original_tickers) - len(filtered.columns)
    breakdown["remaining"] = len(filtered.columns)
    return filtered, breakdown


def get_filter_summary(original_count: int, filtered_df: pd.DataFrame) -> Dict:
    """Devuelve un resumen de cuántos tickers fueron filtrados."""
    final_count = len(filtered_df.columns)
    removed = original_count - final_count

    return {
        "original": original_count,
        "remaining": final_count,
        "removed": removed,
        "removal_pct": round(removed / original_count * 100, 1) if original_count > 0 else 0
    }


def remove_zombie_tickers(prices: pd.DataFrame, max_flat_days: int = 5, min_price: float = 0.01) -> pd.DataFrame:
    """
    Defensa contra tickers 'zombie' (delistados o con datos corruptos de yfinance).

    Detecta series que en los ultimos dias tienen:
    - Precio extremadamente bajo o cero
    - O precio completamente plano (retorno cero) por varios dias seguidos
      (sintoma tipico de tickers delistados que yfinance sigue devolviendo).
    """
    if prices.empty:
        return prices

    filtered = prices.copy()
    to_drop = []

    for ticker in filtered.columns:
        series = filtered[ticker].dropna()
        if len(series) < 2:
            to_drop.append(ticker)
            continue

        last_price = float(series.iloc[-1])

        # Precio invalido o demasiado bajo
        if last_price < min_price:
            to_drop.append(ticker)
            continue

        # Precio completamente plano en los ultimos N dias (zombie signal)
        if len(series) >= max_flat_days:
            recent = series.iloc[-max_flat_days:]
            if recent.nunique() == 1:
                to_drop.append(ticker)
                continue

            recent_rets = recent.pct_change().dropna()
            if len(recent_rets) > 0 and (recent_rets.abs() < 1e-9).all():
                to_drop.append(ticker)

    if to_drop:
        filtered = filtered.drop(columns=to_drop, errors="ignore")
        print(f"   [DATA QUALITY] Eliminados {len(to_drop)} tickers zombie/planos: {to_drop[:6]}{'...' if len(to_drop)>6 else ''}")

    return filtered