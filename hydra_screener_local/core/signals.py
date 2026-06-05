"""
Lógica de señales para el Screener HYDRA Local.
Incluye integración con Meta-Layer.
"""
import pandas as pd
import numpy as np
from config import (
    MOMENTUM_LOOKBACK, MOMENTUM_SKIP, REGIME_SMA, MIN_REGIME_SCORE,
    SHORT_TERM_LOOKBACK, PROXIMITY_HIGH_DAYS, MAX_DIST_TO_HIGH_PCT, SHORT_TERM_BOOST,
    GEOPOLITICAL_RISK_LEVEL, GEO_VOL_THRESHOLD_ADJUST, VOL_SURGE_THRESHOLD, MIN_VOL_THRESHOLD
)
from .meta_layer import LightweightMetaLayer, apply_meta_to_candidates
from .regime import compute_rich_regime_scores
from .filters import apply_sector_concentration_control


def compute_momentum_score(prices: pd.DataFrame) -> pd.Series:
    """
    Calcula el score de momentum estilo COMPASS v8.4 simplificado:
    (retorno 90d / volatilidad 63d)
    """
    returns = prices.pct_change()
    
    mom = prices.pct_change(MOMENTUM_LOOKBACK)
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


def generate_daily_candidates(prices: pd.DataFrame, spy: pd.Series, volumes: pd.DataFrame = None) -> pd.DataFrame:
    """
    Genera candidatos diarios aplicando momentum + Meta-Layer con régimen rico.
    Si se pasa `volumes`, calcula también el surge de volumen y marca quién pasa el Strict Filter.
    """
    momentum = compute_momentum_score(prices)
    
    # Régimen más rico (múltiples dimensiones)
    rich_regime = compute_rich_regime_scores(spy, prices)
    regime_score = rich_regime.overall
    
    df = pd.DataFrame({
        'ticker': momentum.index,
        'momentum_score': momentum.values,
        'rank': range(1, len(momentum) + 1)
    })
    # Normalize name for apply_meta + final output contract
    df = df.rename(columns={'momentum_score': 'momentum'})
    
    # === Integración de Meta-Layer (versión más potente) ===
    meta_layer = LightweightMetaLayer()
    
    recent_dd = max(0.0, (float(spy.rolling(60).max().iloc[-1]) - float(spy.iloc[-1])) / float(spy.rolling(60).max().iloc[-1]))
    spy_20d_ret = (float(spy.iloc[-1]) / float(spy.iloc[-20]) - 1) if len(spy) >= 20 else 0.0
    spy_60d_ret = (float(spy.iloc[-1]) / float(spy.iloc[-60]) - 1) if len(spy) >= 60 else 0.0
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

    # ============================================================
    # NUEVAS REGLAS - Short Term Momentum + Proximity Boost + Volume (Strict Filter)
    # (basado en análisis post-mortem de recomendaciones 31-may)
    # ============================================================
    short_features = compute_short_term_features(prices, volumes=volumes)
    if not short_features.empty:
        df = df.merge(short_features, on="ticker", how="left")
    else:
        df["ret_short"] = 0.0
        df["dist_to_high"] = -10.0

    # Calcular si pasa el Strict Filter (ret >15%, cerca de highs, volumen surge)
    dynamic_vol_threshold = VOL_SURGE_THRESHOLD + (GEOPOLITICAL_RISK_LEVEL * GEO_VOL_THRESHOLD_ADJUST)
    dynamic_vol_threshold = max(MIN_VOL_THRESHOLD, dynamic_vol_threshold)

    df["vol_ratio"] = df.get("vol_ratio", pd.NA)
    df["passes_strict"] = (
        (df["ret_short"].fillna(0) > 15) &
        (df["dist_to_high"].fillna(-100) >= -2) &
        (df["vol_ratio"].fillna(0) > dynamic_vol_threshold)
    ).fillna(False)

    # Boost por momentum reciente + cercanía a máximos
    # - ret_short alto → positivo
    # - dist_to_high cerca de 0 (o positivo) → positivo
    short_boost = (
        (df["ret_short"].fillna(0) / 20).clip(-0.5, 1.5) +                    # normalizado
        ((MAX_DIST_TO_HIGH_PCT - df["dist_to_high"].fillna(-10)).clip(0, MAX_DIST_TO_HIGH_PCT) / MAX_DIST_TO_HIGH_PCT)
    ) / 2

    df["short_term_boost"] = short_boost.round(3)
    df["composite_score"] = (df["meta_score"] * (1 + df["short_term_boost"] * SHORT_TERM_BOOST)).round(4)

    # === Umbral dinámico de volumen según riesgo geopolítico ===
    # NUNCA baja de 1.0 (piso duro), independientemente del nivel de riesgo
    dynamic_vol_threshold = VOL_SURGE_THRESHOLD + (GEOPOLITICAL_RISK_LEVEL * GEO_VOL_THRESHOLD_ADJUST)
    dynamic_vol_threshold = max(MIN_VOL_THRESHOLD, dynamic_vol_threshold)
    df["dynamic_vol_threshold"] = round(dynamic_vol_threshold, 2)

    # Bonus para los que pasan el Strict Filter (volumen + momentum fuerte)
    strict_bonus = 0.18
    if "passes_strict" in df.columns:
        df.loc[df["passes_strict"], "composite_score"] = (
            df.loc[df["passes_strict"], "composite_score"] * (1 + strict_bonus)
        ).round(4)

    # Re-ordenar por el nuevo composite (esto cambia el ranking efectivo)
    df = df.sort_values("composite_score", ascending=False).reset_index(drop=True)
    df["rank"] = range(1, len(df) + 1)

    # === Control de concentración sectorial (nuevo) ===
    # Aplica penalidad suave y re-ordena si hay sobre-concentración por bucket
    df = apply_sector_concentration_control(df)

    # === Número dinámico de recomendaciones basado en Pillar Multipliers ===
    compass_mult = meta_adj.pillar_multipliers.get("COMPASS", 1.0)
    overall_aggression = meta_adj.overall_aggression
    
    # Fórmula para cantidad recomendada (base 12-15, ajustado por Meta-Layer)
    base_recommendations = 14
    dynamic_count = int(round(base_recommendations * overall_aggression * compass_mult))
    
    # Límites razonables (no queremos recomendar 3 ni 45)
    dynamic_count = max(6, min(dynamic_count, 28))
    
    # Lógica de recomendación final (ahora dinámica)
    df['recommended'] = (df['rank'] <= dynamic_count) & (meta_adj.regime_score >= MIN_REGIME_SCORE * 0.85)
    df['reason'] = df.apply(
        lambda r: meta_adj.rationale if r['recommended'] else 'Filtrado por Meta-Layer', 
        axis=1
    )
    
    # Guardamos el número dinámico para mostrarlo en el resumen
    df['recommended_count'] = dynamic_count
    
    final_df = df[['rank', 'ticker', 'momentum', 'meta_score', 'composite_score',
                   'ret_short', 'dist_to_high', 'short_term_boost',
                   'vol_ratio', 'passes_strict',
                   'sector', 'sector_rank', 'sector_penalty_applied',
                   'dynamic_vol_threshold',
                   'regime', 'meta_regime_type', 'meta_special_modes', 'aggression', 
                   'compass_mult', 'recommended', 'reason', 'recommended_count',
                   'pillar_multipliers', 'recovery_boost']].copy()
    
    final_df.columns = ['rank', 'ticker', 'momentum', 'meta_score', 'composite_score',
                        'ret_5d_10d', 'dist_20d_high', 'short_boost',
                        'vol_ratio', 'passes_strict',
                        'sector', 'sector_rank', 'sector_penalty_applied',
                        'dynamic_vol_threshold',
                        'regime', 'regime_type', 'special_modes', 'aggression', 
                        'compass_mult', 'recommended', 'reason', 'recommended_count',
                        'pillar_multipliers', 'recovery_boost']
    
    return final_df.sort_values('composite_score', ascending=False).reset_index(drop=True)