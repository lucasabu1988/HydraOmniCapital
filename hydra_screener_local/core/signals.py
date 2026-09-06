"""
HYDRA Scoring Logic - Core Signals Module

This module implements the scoring and ranking logic defined in:
HYDRA_ALGORITHM_SPEC.md (version 1.2 - Expanded & Formal)

See especially:
- Section 3: Full Pipeline (formal pseudocode)
- Section 4.1: Momentum Score
- Section 4.2: Short-Term Features + Strict Filter
- Section 4.5: Composite Score Assembly
- Section 4.7: Dynamic Recommendation Count + Final Flag
- Section 7: Output Column Contract

This is the reference Python implementation of the language-agnostic spec.
"""

import pandas as pd
import numpy as np
from config import (
    MOMENTUM_LOOKBACK, MOMENTUM_WINDOW, REGIME_SMA, MIN_REGIME_SCORE,
    SHORT_TERM_LOOKBACK, PROXIMITY_HIGH_DAYS, MAX_DIST_TO_HIGH_PCT, SHORT_TERM_BOOST,
    GEOPOLITICAL_RISK_LEVEL, GEO_VOL_THRESHOLD_ADJUST, VOL_SURGE_THRESHOLD, MIN_VOL_THRESHOLD,
    ENABLE_DOWNTREND_GATE, GATE_MAX_DIST_TO_HIGH_PCT, GATE_MIN_RET_SHORT_PCT
)
from .meta_layer import LightweightMetaLayer, apply_meta_to_candidates
from .regime import compute_rich_regime_scores
from .filters import apply_sector_concentration_control


def compute_momentum_score(prices: pd.DataFrame, window: str = None) -> pd.Series:
    """Risk-adjusted momentum (SPEC 4.1).

    window="ret90"   : close[t]/close[t-90] - 1            (v8.4 production)
    window="mom12_7" : close[t-126]/close[t-252] - 1       (v9 stock sleeve; Novy-Marx 2012)
    Both divided by the 63-day annualised volatility. Default = config.MOMENTUM_WINDOW.
    """
    window = window or MOMENTUM_WINDOW
    returns = prices.pct_change(fill_method=None)
    if window == "ret90":
        mom = prices.pct_change(MOMENTUM_LOOKBACK, fill_method=None)
    elif window == "mom12_7":
        mom = prices.shift(126) / prices.shift(252) - 1
    else:
        raise ValueError(f"unknown momentum window {window!r}")
    vol = returns.rolling(63).std() * np.sqrt(252)

    score = mom / vol.replace(0, np.nan)
    return score.iloc[-1].dropna()


def compute_short_term_features(prices: pd.DataFrame, volumes: pd.DataFrame = None) -> pd.DataFrame:
    """
    Nuevas reglas post-análisis (31-may):
    - Retorno reciente (SHORT_TERM_LOOKBACK días)
    - Distancia al máximo de los últimos PROXIMITY_HIGH_DAYS días
    - (Opcional) Volumen relativo (surge) si se pasa el DF de volumes.

    Esto permite detectar aceleraciones frescas + confirmación de volumen (el "Strict Filter").
    """
    features = []
    for ticker in prices.columns:
        try:
            series = prices[ticker].dropna()
            if len(series) < max(SHORT_TERM_LOOKBACK, PROXIMITY_HIGH_DAYS) + 1:
                continue

            # Retorno reciente
            ret_short = (series.iloc[-1] / series.iloc[-SHORT_TERM_LOOKBACK-1] - 1) * 100

            # Distancia al máximo reciente
            recent_high = series.iloc[-PROXIMITY_HIGH_DAYS:].max()
            dist_to_high = (series.iloc[-1] / recent_high - 1) * 100

            feat = {
                "ticker": ticker,
                "ret_short": round(ret_short, 2),
                "dist_to_high": round(dist_to_high, 2)
            }

            # === Nuevo: Volumen relativo (5d vs 20d) si tenemos datos ===
            if volumes is not None and ticker in volumes.columns:
                vol_series = volumes[ticker].dropna()
                if len(vol_series) >= 25:
                    avg_vol_20 = vol_series.iloc[-20:].mean()
                    avg_vol_5 = vol_series.iloc[-5:].mean()
                    if avg_vol_20 > 0:
                        vol_ratio = round(avg_vol_5 / avg_vol_20, 3)
                        feat["vol_ratio"] = vol_ratio

            features.append(feat)
        except Exception:
            continue

    return pd.DataFrame(features)


def apply_downtrend_gate(df: pd.DataFrame) -> pd.DataFrame:
    """
    Veto duro (SPEC 4.7): una acción en caída reciente NO puede estar en
    'recommended', sin importar qué tan alto rankee por momentum de 90d.

    Columnas disponibles en df (antes del rename final):
    - df["ret_short"]:    retorno % de los últimos SHORT_TERM_LOOKBACK (10) días.
                          Puede ser NaN si faltan datos.
    - df["dist_to_high"]: distancia % al máximo de 20d. Siempre ≤ 0.
                          Ej: -8.0 = está 8% debajo de su máximo. Puede ser NaN.
    - df["recommended"]:  flag booleano ya calculado por rank + régimen.

    Umbrales configurables en config.py:
    - GATE_MAX_DIST_TO_HIGH_PCT (ej: -8.0)
    - GATE_MIN_RET_SHORT_PCT    (ej: -5.0)

    Regla (2026-06-12): el veto solo aplica EN NEGATIVO — `ret_short < 0` es
    condición necesaria. Una acción con retorno reciente positivo nunca se veta,
    aunque esté lejos de su máximo de 20d (dip dentro de un uptrend: subió fuerte,
    retrocede del pico pero sigue neta arriba). Verificado en el replay del selloff
    jun-2026 (experiments/backtest_gate_variants.py): la regla OR pura vetaba el
    rebote post-crash (nombres aún positivos a 10d) y costaba retorno cada día.
    Sobre la condición necesaria, cualquiera de las dos señales veta (OR).
    NaN TAMBIÉN veta: en un sistema que ejecuta capital real, un dato ausente no
    cuenta como luz verde. Con el universo ampliado (~3000 tickers) los huecos de
    descarga de Yahoo son más frecuentes, así que "sin datos frescos de corto
    plazo" = no recomendable hoy.
    """
    if not ENABLE_DOWNTREND_GATE:
        return df

    in_downtrend = (
        (df["ret_short"] < 0) &
        (
            (df["dist_to_high"] < GATE_MAX_DIST_TO_HIGH_PCT) |
            (df["ret_short"] < GATE_MIN_RET_SHORT_PCT)
        )
    ).fillna(False)
    # NaN < umbral da False en pandas, así que los huecos de datos se chequean aparte
    missing_data = df["dist_to_high"].isna() | df["ret_short"].isna()

    veto_downtrend = in_downtrend & df["recommended"]
    veto_missing = missing_data & df["recommended"] & ~in_downtrend
    df.loc[veto_downtrend, "reason"] = "Vetado: caída reciente (downtrend gate, SPEC 4.7)"
    df.loc[veto_missing, "reason"] = "Vetado: datos de corto plazo incompletos (gate, SPEC 4.7)"
    df.loc[veto_downtrend | veto_missing, "recommended"] = False
    return df


def compute_regime_score(spy: pd.Series) -> float:
    """
    Regime Score simple (0 a 1).
    Combina tendencia (SPY vs SMA200) + momentum reciente.
    """
    if len(spy) < REGIME_SMA:
        return 0.5
    
    current = float(spy.iloc[-1])
    sma200 = float(spy.rolling(REGIME_SMA).mean().iloc[-1])
    
    trend = 1 if current > sma200 else 0
    
    ret_20d = (current / float(spy.iloc[-20]) - 1) if len(spy) >= 20 else 0
    mom_score = np.clip((ret_20d + 0.05) / 0.15, 0, 1)
    
    regime = (0.7 * trend) + (0.3 * mom_score)
    return round(float(regime), 3)


def generate_daily_candidates(prices: pd.DataFrame, spy: pd.Series, volumes: pd.DataFrame = None,
                             sector_map: dict = None, momentum_window: str = None) -> pd.DataFrame:
    """
    Main entry point for daily candidate generation.

    Implements the full pipeline described in HYDRA_ALGORITHM_SPEC.md Section 3.

    See SPEC sections:
    - 4.1 Momentum Score
    - 4.2 Short-Term Features + Strict Filter (and the +18% bonus)
    - 4.3 Rich Regime (via compute_rich_regime_scores)
    - 4.4 Meta-Layer (via LightweightMetaLayer + apply_meta_to_candidates)
    - 4.5 Composite Score Assembly (short-term boost + strict bonus)
    - 4.6 Sector Concentration Control (post-processing)
    - 4.7 Dynamic Recommendation Count + Final Flag
    - 7 Output Column Contract (the final_df columns below)

    This function produces the rich output contract expected by history, display,
    analyze_history, tracking, and the hybrid Pine Script layer.

    `sector_map` ({ticker: sector}) is resolved upstream in screener.py so that scoring
    does no network I/O — the backtest and the tests stay offline and deterministic.
    When it is None the sector lookup falls back to the local cache and SECTOR_BUCKETS.
    """
    # SPEC 4.1 - Momentum Score (risk-adjusted)
    momentum = compute_momentum_score(prices, window=momentum_window)
    
    # SPEC 4.3 - Rich Regime (5 sub-scores + weighted overall)
    rich_regime = compute_rich_regime_scores(spy, prices)
    regime_score = rich_regime.overall
    
    df = pd.DataFrame({
        'ticker': momentum.index,
        'momentum_score': momentum.values,
        'rank': range(1, len(momentum) + 1)
    })
    # Normalize name for apply_meta + final output contract
    df = df.rename(columns={'momentum_score': 'momentum'})
    
    # SPEC 4.4 - Meta-Layer (regime type, special modes, pillar_multipliers, aggression)
    meta_layer = LightweightMetaLayer()
    
    spy_current = float(spy.iloc[-1])
    recent_dd = max(0.0, (float(spy.rolling(60).max().iloc[-1]) - spy_current) / float(spy.rolling(60).max().iloc[-1]))
    spy_20d_ret = (spy_current / float(spy.iloc[-20]) - 1) if len(spy) >= 20 else 0.0
    spy_60d_ret = (spy_current / float(spy.iloc[-60]) - 1) if len(spy) >= 60 else 0.0
    vol_level = float(spy.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252)) if len(spy) > 20 else 0.5
    vol_level = min(max(vol_level / 0.25, 0.3), 0.9)
    
    meta_adj = meta_layer.compute_adjustment(
        regime_score=regime_score,
        recent_drawdown=recent_dd,
        spy_20d_return=spy_20d_ret,
        spy_60d_return=spy_60d_ret,
        volatility_level=vol_level
    )
    
    df = apply_meta_to_candidates(df, meta_adj)

    # SPEC 4.2 - Short-Term Features + Strict Filter (ret_short >15%, dist_to_high >= -2, vol surge)
    # +18% bonus applied later if passes_strict (see SPEC 4.5)
    short_features = compute_short_term_features(prices, volumes=volumes)
    if not short_features.empty:
        df = df.merge(short_features, on="ticker", how="left")
    else:
        # Sin features de corto plazo: NaN honesto → el gate los veta como
        # "datos incompletos" (no como falsa "caída reciente" con -10 inventado)
        df["ret_short"] = np.nan
        df["dist_to_high"] = np.nan

    # Calcular si pasa el Strict Filter (ret >15%, cerca de highs, volumen surge)
    dynamic_vol_threshold = VOL_SURGE_THRESHOLD + (GEOPOLITICAL_RISK_LEVEL * GEO_VOL_THRESHOLD_ADJUST)
    dynamic_vol_threshold = max(MIN_VOL_THRESHOLD, dynamic_vol_threshold)

    df["vol_ratio"] = df.get("vol_ratio", pd.NA)
    # Numeric coerce before fillna — avoids pandas FutureWarning on object downcast.
    # Fill values unchanged: ret_short 0, dist_to_high -100, vol_ratio 0 (scoring identical).
    df["ret_short"] = pd.to_numeric(df["ret_short"], errors="coerce")
    df["dist_to_high"] = pd.to_numeric(df["dist_to_high"], errors="coerce")
    df["vol_ratio"] = pd.to_numeric(df["vol_ratio"], errors="coerce")
    # TASK-202/314: share of tickers with missing volume (after coerce so object-NaN counts).
    # Must stay on the SPEC §7 output contract or screener.py always reads the 0.0 default.
    vol_ratio_nan_share = float(df["vol_ratio"].isna().mean()) if len(df) > 0 else 0.0
    df["vol_ratio_nan_share"] = round(vol_ratio_nan_share, 4)
    df["passes_strict"] = (
        (df["ret_short"].fillna(0.0) > 15) &
        (df["dist_to_high"].fillna(-100.0) >= -2) &
        (df["vol_ratio"].fillna(0.0) > dynamic_vol_threshold)
    ).fillna(False)

    # SPEC 4.5 - Short-term boost + composite (momentum * meta * (1 + short_boost * SHORT_TERM_BOOST))
    # - ret_short alto → positivo
    # - dist_to_high cerca de 0 → 1.0, decae a 0 cuando está más de MAX_DIST_TO_HIGH_PCT% debajo del high
    #   (dist_to_high es ≤ 0 por construcción: precio actual vs máximo de 20d)
    short_boost = (
        (df["ret_short"].fillna(0) / 20).clip(-0.5, 1.5) +                    # normalizado
        ((MAX_DIST_TO_HIGH_PCT + df["dist_to_high"].fillna(-10)).clip(0, MAX_DIST_TO_HIGH_PCT) / MAX_DIST_TO_HIGH_PCT)
    ) / 2

    df["short_term_boost"] = short_boost.round(3)
    df["composite_score"] = (df["meta_score"] * (1 + df["short_term_boost"] * SHORT_TERM_BOOST)).round(4)
    df["dynamic_vol_threshold"] = round(dynamic_vol_threshold, 2)

    # SPEC 4.2 + 4.5 - Strict Filter bonus (+18% / 0.18 when passes_strict)
    strict_bonus = 0.18
    if "passes_strict" in df.columns:
        df.loc[df["passes_strict"], "composite_score"] = (
            df.loc[df["passes_strict"], "composite_score"] * (1 + strict_bonus)
        ).round(4)

    # Re-ordenar por el nuevo composite (esto cambia el ranking efectivo)
    df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)

    # SPEC 4.7 - Dynamic Recommendation Count (base 14 * aggression * compass_mult, 6-28).
    # Computed BEFORE sector control: the cap applies to the list being picked, not to the
    # whole scored universe (TASK-320).
    compass_mult = meta_adj.pillar_multipliers.get("COMPASS", 1.0)
    overall_aggression = meta_adj.overall_aggression

    base_recommendations = 14
    dynamic_count = int(round(base_recommendations * overall_aggression * compass_mult))

    # Límites razonables (no queremos recomendar 3 ni 45)
    dynamic_count = max(6, min(dynamic_count, 28))

    # SPEC 4.6 - Sector Concentration Control: hard cap while picking the list.
    # Scores are not modified; the cap is a selection constraint.
    df = apply_sector_concentration_control(df, dynamic_count, sector_map=sector_map)

    # Lógica de recomendación final
    df['recommended'] = df['sector_selected'] & (meta_adj.regime_score >= MIN_REGIME_SCORE * 0.85)
    df['reason'] = np.where(
        df['recommended'],
        meta_adj.rationale,
        np.where(df['sector_penalty_applied'],
                 'Filtrado: límite por sector (SPEC 4.6)',
                 'Filtrado por Meta-Layer'),
    )
    
    # SPEC 4.7 - Downtrend Veto Gate (excluye acciones en caída reciente de 'recommended')
    df = apply_downtrend_gate(df)

    # Guardamos el número dinámico para mostrarlo en el resumen
    # (el gate puede reducir el conteo efectivo por debajo de dynamic_count)
    df['recommended_count'] = dynamic_count
    
    # SPEC 7 - Output Column Contract (rich columns for downstream consumers)
    # This matches exactly the "Output Contract (Rich Columns)" section in the SPEC.
    final_df = df[['rank', 'ticker', 'momentum', 'meta_score', 'composite_score',
                   'ret_short', 'dist_to_high', 'short_term_boost',
                   'vol_ratio', 'passes_strict',
                   'sector', 'sector_rank', 'sector_penalty_applied',
                   'dynamic_vol_threshold', 'vol_ratio_nan_share',
                   'regime', 'meta_regime_type', 'meta_special_modes', 'aggression', 
                   'compass_mult', 'recommended', 'reason', 'recommended_count',
                   'pillar_multipliers', 'recovery_boost']].copy()
    
    final_df.columns = ['rank', 'ticker', 'momentum', 'meta_score', 'composite_score',
                        'ret_5d_10d', 'dist_20d_high', 'short_boost',
                        'vol_ratio', 'passes_strict',
                        'sector', 'sector_rank', 'sector_penalty_applied',
                        'dynamic_vol_threshold', 'vol_ratio_nan_share',
                        'regime', 'regime_type', 'special_modes', 'aggression', 
                        'compass_mult', 'recommended', 'reason', 'recommended_count',
                        'pillar_multipliers', 'recovery_boost']
    
    return final_df.sort_values('composite_score', ascending=False).reset_index(drop=True)