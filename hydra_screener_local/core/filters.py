"""
Filtros prácticos para el Screener HYDRA Local.

Mantener la estructura ligera.
"""
import pandas as pd
from typing import List, Dict
from config import (
    ENABLE_SECTOR_CONTROL, MAX_PER_SECTOR, SECTOR_OVERWEIGHT_PENALTY, SECTOR_BUCKETS
)


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


def remove_zombie_tickers(prices: pd.DataFrame, max_flat_days: int = 5, min_price: float = 0.01) -> pd.DataFrame:
    """
    Defensa en profundidad contra tickers "zombie" (delistados o con datos corruptos de yfinance).

    Detecta series que en los últimos días tienen:
    - Precio extremadamente bajo o cero
    - O precio completamente plano (retorno cero) por varios días seguidos
      (síntoma típico de tickers delistados que yfinance sigue devolviendo con el último precio conocido).

    Esto complementa el hard blacklist de config.DELISTED_OR_BAD_TICKERS.
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

        # Precio inválido o demasiado bajo
        if last_price < min_price:
            to_drop.append(ticker)
            continue

        # Precio completamente plano en los últimos N días (zombie signal)
        if len(series) >= max_flat_days:
            recent = series.iloc[-max_flat_days:]
            if recent.nunique() == 1:  # todos iguales
                to_drop.append(ticker)
                continue

            # Retornos cero en toda la ventana reciente
            recent_rets = recent.pct_change().dropna()
            if len(recent_rets) > 0 and (recent_rets.abs() < 1e-9).all():
                to_drop.append(ticker)

    if to_drop:
        filtered = filtered.drop(columns=to_drop, errors="ignore")
        try:
            print(f"   [DATA QUALITY] Eliminados {len(to_drop)} tickers zombie/planos por sanity check: {to_drop[:6]}{'...' if len(to_drop)>6 else ''}")
        except UnicodeEncodeError:
            print(f"   [DATA QUALITY] Eliminados {len(to_drop)} tickers zombie/planos.")

    return filtered


def get_sector(ticker: str) -> str:
    """Devuelve el bucket grueso de un ticker (o 'Other')."""
    return SECTOR_BUCKETS.get(ticker, "Other")


def apply_sector_concentration_control(
    candidates_df: pd.DataFrame,
    max_per_sector: int = None,
    penalty: float = None,
) -> pd.DataFrame:
    """
    Control ligero de concentración sectorial/temática.

    - Aplica una penalidad suave al composite_score de los nombres que exceden el límite por bucket.
    - También puede usarse para hard-cap al momento de seleccionar recomendados.

    Retorna el DF con columnas adicionales:
      - sector
      - sector_rank (ranking dentro de su bucket)
      - sector_penalty_applied
    """
    if not ENABLE_SECTOR_CONTROL:
        return candidates_df

    max_per = max_per_sector or MAX_PER_SECTOR
    pen = penalty or SECTOR_OVERWEIGHT_PENALTY

    df = candidates_df.copy()
    df["sector"] = df["ticker"].apply(get_sector)

    # Calcular ranking dentro de cada sector (1 = mejor del bucket)
    df["sector_rank"] = df.groupby("sector")["composite_score"].rank(method="first", ascending=False).astype(int)

    # Aplicar penalidad a los que exceden el límite
    df["sector_penalty_applied"] = False

    for sector in df["sector"].unique():
        sector_mask = df["sector"] == sector
        excess = df.loc[sector_mask & (df["sector_rank"] > max_per)]

        if not excess.empty:
            df.loc[excess.index, "composite_score"] = (
                df.loc[excess.index, "composite_score"] * (1 - pen)
            ).round(4)
            df.loc[excess.index, "sector_penalty_applied"] = True

    # Re-ordenar después de la penalidad
    df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)

    if df["sector_penalty_applied"].any():
        penalized = df[df["sector_penalty_applied"]]["ticker"].tolist()
        print(f"   [SECTOR CONTROL] Penalizados {len(penalized)} nombres por sobre-concentración "
              f"(>{max_per} por bucket): {penalized[:5]}{'...' if len(penalized)>5 else ''}")

    return df