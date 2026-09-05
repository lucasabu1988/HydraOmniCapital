"""
Practical Filters + Sector Concentration Control

Implements:
- apply_practical_filters (price + volume)
- remove_zombie_tickers
- apply_sector_concentration_control (SPEC 4.6, hard cap at selection)

Sector control caps how many names of one sector reach the recommended list.
"""
import pandas as pd
from typing import List, Dict
from config import (
    ENABLE_SECTOR_CONTROL, MAX_PER_SECTOR, SECTOR_BUCKETS
)
from data.sectors import UNKNOWN_SECTOR


def apply_practical_filters(
    prices: pd.DataFrame,
    volumes: pd.DataFrame = None,
    min_avg_volume: int = 1_000_000,
    min_price: float = 5.0,
    max_price: float = None,
    exclude_sectors: List[str] = None,
    min_dollar_volume: float = None,
) -> tuple[pd.DataFrame, Dict]:
    """
    Aplica filtros básicos de liquidez y precio.
    Retorna (DataFrame filtrado, breakdown dict).

    Liquidity is checked two ways when `volumes` is given:
    - min_avg_volume: 20-day mean SHARES traded (legacy; keeps obvious ghosts out).
    - min_dollar_volume: 20-day mean of close x volume in USD. This is the one that matters
      for a strategy rotating ~39% of the list every week on a Russell-heavy universe: 100k
      shares of a $5 stock is $500k/day, far too thin to trade. Selection rule, not scoring
      (SPEC 1) - audit 2026-09-06, D3.
    """
    original_tickers = set(prices.columns)
    filtered = prices.copy()
    breakdown = {}

    # 1. Filtro de liquidez (placeholder - requiere Volume data del fetch para ser real)
    # Actualmente min_avg_volume=0 por defecto para no romper con DF de solo precios.
    # Cuando se pasa volumes= (de fetch_prices_and_volume), se activa el filtro real.
    if min_avg_volume > 0:
        if volumes is not None:
            # A ticker with prices but no volume column cannot prove its liquidity: it fails.
            # (Indexing volumes[filtered.columns] used to raise KeyError in that case.)
            cols = filtered.columns.intersection(volumes.columns)
            recent_volume = volumes[cols].iloc[-20:].mean()
            liquid_tickers = recent_volume[recent_volume >= min_avg_volume].index.tolist()
            removed_vol = len(filtered.columns) - len(liquid_tickers)
            filtered = filtered[liquid_tickers]
            breakdown["volume"] = removed_vol
        else:
            breakdown["volume"] = 0
    else:
        breakdown["volume"] = 0

    # 1b. Filtro de liquidez en dólares (ADV$ 20d)
    if min_dollar_volume and volumes is not None and len(filtered.columns) > 0:
        cols = filtered.columns.intersection(volumes.columns)
        adv_usd = (filtered[cols].iloc[-20:] * volumes[cols].iloc[-20:]).mean()
        liquid = adv_usd[adv_usd >= min_dollar_volume].index.tolist()
        # a ticker with no volume data at all cannot prove its liquidity: it does not pass
        breakdown["dollar_volume"] = len(filtered.columns) - len(liquid)
        filtered = filtered[liquid]
    else:
        breakdown["dollar_volume"] = 0

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
    """Cache GICS -> SECTOR_BUCKETS -> "Other". Reads only, never touches the network."""
    try:
        from data.sectors import lookup_sector
        return lookup_sector(ticker)
    except Exception:
        return SECTOR_BUCKETS.get(ticker, UNKNOWN_SECTOR)


def apply_sector_concentration_control(
    candidates_df: pd.DataFrame,
    dynamic_count: int = None,
    max_per_sector: int = None,
    sector_map: dict = None,
) -> pd.DataFrame:
    """
    SPEC 4.6 - Sector Concentration Control: a hard cap applied while picking the list.

    TASK-320 replaced the previous soft 15% penalty, which had two defects. It was applied
    across the whole scored universe, so with ~500 names in ~10 buckets it penalised 87%
    of them for being 9th of 45 in their sector - a tax on not being in an 80-name
    hardcoded map, not a concentration control. And being soft, it never actually bound:
    penalised names were re-sorted and the replacements entering the list were never
    re-checked, so 100% of simulated cycles ended above the cap (worst case 20 names in
    one sector).

    Now the score is left alone - scoring stays separate from portfolio construction
    (SPEC 1) - and the cap is enforced during selection: walk down the ranking and skip a
    name whose sector is already full. The cap holds by construction, and it still holds
    after the downtrend gate, since vetoing names can only lower a sector's count.

    `UNKNOWN_SECTOR` is exempt. It means "we failed to look this up", not a sector, and
    you cannot be over-concentrated in the unknown. Without that exemption the old defect
    just moves from the universe to the pool: with an empty sector cache 18 of 22 pool
    names are "Other", and a cap of 3 would skip 15 of them.

    Args:
        candidates_df: scored frame, already sorted by composite_score descending.
        dynamic_count: size of the list being picked. None = treat the whole frame as
            the pool (used by experiment scripts that pass an already-selected subset).
        sector_map: {ticker: sector} resolved upstream. None = fall back to the local
            cache/buckets lookup, which is what keeps tests and the backtest offline.

    Adds: sector, sector_rank, sector_penalty_applied (True = skipped by the cap),
    sector_selected (the picked list, before the regime flag and the downtrend gate).
    """
    df = candidates_df.copy()
    if sector_map:
        df["sector"] = [sector_map.get(t) or get_sector(t) for t in df["ticker"]]
    else:
        df["sector"] = df["ticker"].apply(get_sector)

    # 1 = best of its sector. Informative only; the cap below uses the walk order.
    df["sector_rank"] = df.groupby("sector")["composite_score"].rank(
        method="first", ascending=False).astype(int)
    df["sector_penalty_applied"] = False
    df["sector_selected"] = False

    n_pool = len(df) if dynamic_count is None else max(0, min(int(dynamic_count), len(df)))
    if not ENABLE_SECTOR_CONTROL:
        df.loc[df.index[:n_pool], "sector_selected"] = True
        return df

    max_per = max_per_sector or MAX_PER_SECTOR
    picked, skipped, counts = [], [], {}
    for idx, sector in df["sector"].items():
        if len(picked) >= n_pool:
            break
        if sector != UNKNOWN_SECTOR and counts.get(sector, 0) >= max_per:
            skipped.append(idx)
            continue
        picked.append(idx)
        counts[sector] = counts.get(sector, 0) + 1

    df.loc[picked, "sector_selected"] = True
    df.loc[skipped, "sector_penalty_applied"] = True

    if skipped:
        names = df.loc[skipped, "ticker"].tolist()
        print(f"   [SECTOR CONTROL] {len(names)} nombres desplazados por el limite de "
              f"{max_per} por sector: {names[:5]}{'...' if len(names) > 5 else ''}")

    return df
