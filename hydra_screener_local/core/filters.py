"""
Filtros prácticos para el Screener HYDRA Local.

Mantener la estructura ligera.
"""
import pandas as pd
from typing import List, Dict


def apply_practical_filters(
    prices: pd.DataFrame,
    min_avg_volume: int = 1_000_000,
    min_price: float = 5.0,
    max_price: float = None,
    exclude_sectors: List[str] = None,
) -> pd.DataFrame:
    """
    Aplica filtros básicos de liquidez y precio.

    Nota: El filtro de liquidez (min_avg_volume) está deshabilitado por defecto
    porque fetch solo trae precios Close. min_price sí está activo.
    Para activar volumen real: extender fetch_prices para pedir Volume y pasar DF separado.
    """
    filtered = prices.copy()

    # 1. Filtro de liquidez (placeholder - requiere Volume data del fetch para ser real)
    # Actualmente min_avg_volume=0 por defecto para no romper con DF de solo precios.
    if min_avg_volume > 0:
        recent = filtered.iloc[-20:].mean()
        # Heurística: si los valores parecen precios (<10k), ignorar para no vaciar el DF
        if recent.max() < 10000:
            pass  # skip mis-applied price-as-volume filter
        else:
            liquid_tickers = recent[recent >= min_avg_volume].index.tolist()
            filtered = filtered[liquid_tickers]

    # 2. Filtro de precio mínimo
    if min_price > 0:
        current_prices = filtered.iloc[-1]
        valid_price = current_prices[current_prices >= min_price].index.tolist()
        filtered = filtered[valid_price]

    # 3. Filtro de precio máximo (opcional)
    if max_price is not None and max_price > 0:
        current_prices = filtered.iloc[-1]
        valid_price = current_prices[current_prices <= max_price].index.tolist()
        filtered = filtered[valid_price]

    return filtered


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