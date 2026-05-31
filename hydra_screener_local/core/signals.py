"""
Lógica de señales para el Screener HYDRA Local.
Incluye integración con Meta-Layer.
"""
import pandas as pd
import numpy as np
from config import MOMENTUM_LOOKBACK, MOMENTUM_SKIP, REGIME_SMA, MIN_REGIME_SCORE
from .meta_layer import LightweightMetaLayer, apply_meta_to_candidates
from .regime import compute_rich_regime_scores


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


def compute_regime_score(spy: pd.Series) -> float:
    """
    Regime Score simple (0 a 1).
    Combina tendencia (SPY vs SMA200) + momentum reciente.
    """
    if len(spy) < REGIME_SMA:
        return 0.5
    
    current = spy.iloc[-1]
    sma200 = spy.rolling(REGIME_SMA).mean().iloc[-1]
    
    trend = 1 if current > sma200 else 0
    
    ret_20d = (current / spy.iloc[-20] - 1) if len(spy) >= 20 else 0
    mom_score = np.clip((ret_20d + 0.05) / 0.15, 0, 1)
    
    regime = (0.7 * trend) + (0.3 * mom_score)
    return round(float(regime), 3)


def generate_daily_candidates(prices: pd.DataFrame, spy: pd.Series) -> pd.DataFrame:
    """
    Genera candidatos diarios aplicando momentum + Meta-Layer con régimen rico.
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
    
    # === Integración de Meta-Layer (versión más potente) ===
    meta_layer = LightweightMetaLayer()
    
    recent_dd = max(0.0, (spy.rolling(60).max().iloc[-1] - spy.iloc[-1]) / spy.rolling(60).max().iloc[-1])
    spy_20d_ret = (spy.iloc[-1] / spy.iloc[-20] - 1) if len(spy) >= 20 else 0.0
    spy_60d_ret = (spy.iloc[-1] / spy.iloc[-60] - 1) if len(spy) >= 60 else 0.0
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
    
    # Lógica de recomendación final
    df['recommended'] = (df['rank'] <= 25) & (meta_adj.regime_score >= MIN_REGIME_SCORE * 0.9)
    df['reason'] = df.apply(
        lambda r: meta_adj.rationale if r['recommended'] else 'Filtrado por Meta-Layer', 
        axis=1
    )
    
    final_df = df[['rank', 'ticker', 'momentum', 'meta_score', 'regime', 
                   'meta_regime_type', 'meta_special_modes', 'aggression', 
                   'recommended', 'reason']].copy()
    
    final_df.columns = ['rank', 'ticker', 'momentum', 'meta_score', 'regime', 
                        'regime_type', 'special_modes', 'aggression', 
                        'recommended', 'reason']
    
    return final_df.sort_values('meta_score', ascending=False).reset_index(drop=True)