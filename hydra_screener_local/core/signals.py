"""
Lógica de señales para el Screener HYDRA Local.
Versión inicial limpia y extensible.
"""
import pandas as pd
import numpy as np
from config import MOMENTUM_LOOKBACK, MOMENTUM_SKIP, REGIME_SMA, MIN_REGIME_SCORE


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
    
    # Momentum reciente (20 días)
    ret_20d = (current / spy.iloc[-20] - 1) if len(spy) >= 20 else 0
    mom_score = np.clip((ret_20d + 0.05) / 0.15, 0, 1)  # normalización burda
    
    regime = (0.7 * trend) + (0.3 * mom_score)
    return round(float(regime), 3)


def generate_daily_candidates(prices: pd.DataFrame, spy: pd.Series) -> pd.DataFrame:
    """
    Genera el ranking diario de candidatos.
    Por ahora usa momentum + filtro de régimen básico.
    """
    momentum = compute_momentum_score(prices)
    regime_score = compute_regime_score(spy)
    
    df = pd.DataFrame({
        'ticker': momentum.index,
        'momentum_score': momentum.values
    })
    
    df = df.sort_values('momentum_score', ascending=False).reset_index(drop=True)
    df['rank'] = range(1, len(df) + 1)
    df['regime_score'] = regime_score
    
    # Filtro simple de régimen
    if regime_score < MIN_REGIME_SCORE:
        df['recommended'] = False
        df['reason'] = 'Régimen débil'
    else:
        df['recommended'] = df['rank'] <= 20
        df['reason'] = 'Top momentum'
    
    return df[['rank', 'ticker', 'momentum_score', 'regime_score', 'recommended', 'reason']]