"""
Practical Filters + Sector Concentration Control

Implements:
- apply_practical_filters (price + volume)
- remove_zombie_tickers
- apply_sector_concentration_control (SPEC 4.6)

Sector control is the soft penalty + re-rank logic described in the SPEC.
"""
import pandas as pd
from typing import List, Dict
from config import (
    ENABLE_SECTOR_CONTROL, MAX_PER_SECTOR, SECTOR_OVERWEIGHT_PENALTY, SECTOR_BUCKETS
)


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

    Nota: El filtro de liquidez (min_avg_volume) está deshabilitado por defecto
    porque fetch solo trae precios Close. min_price sí está activo.
    Para activar volumen real: extender fetch_prices para pedir Volume y pasar DF separado.
    """
    original_tickers = set(prices.columns)
    filtered = prices.copy()
    breakdown = {}

    # 1. Filtro de liquidez (placeholder - requiere Volume data del fetch para ser real)
    # Actualmente min_avg_volume=0 por defecto para no romper con DF de solo precios.
    # Cuando se pasa volumes= (de fetch_prices_and_volume), se activa el filtro real.
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
    SPEC 4.6 - Sector Concentration Control (soft penalty + re-rank)

    Exact logic from the formal specification:
    - Assign coarse buckets from SECTOR_BUCKETS
    - Rank within bucket
    - If > MAX_PER_SECTOR in a bucket → apply SECTOR_OVERWEIGHT_PENALTY (default 15%)
    - Re-sort global list and re-assign ranks
    - Adds: sector, sector_rank, sector_penalty_applied
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
