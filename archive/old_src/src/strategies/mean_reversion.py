"""
Estrategias de Mean Reversion

Basadas en:
- Gatev, E., Goetzmann, W.N., & Rouwenhorst, K.G. (2006) - Pairs Trading
- Avellaneda, M. & Lee, J.H. (2010) - Statistical Arbitrage
- Poterba, J.M. & Summers, L.H. (1988) - Mean Reversion in Stock Prices
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from scipy import stats
from datetime import datetime

from .base import BaseStrategy, StrategySignal, Allocation


class PairsTradingStrategy(BaseStrategy):
    """
    Estrategia de Pairs Trading basada en cointegración.
    
    Identifica pares de stocks cointegrados y genera señales
    cuando el spread se desvía de su media.
    
    Lógica:
    1. Calcular hedge ratio (regresión del par)
    2. Calcular spread = Y - βX
    3. Normalizar a z-score
    4. Entrar cuando |z| > umbral, salir cuando z cruza 0
    
    Config:
        lookback_days: Período para calcular hedge ratio
        entry_zscore: Umbral de entrada (default: 2.0)
        exit_zscore: Umbral de salida (default: 0.5)
        pairs: Lista de tuplas (symbol1, symbol2) o None para auto-detectar
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.lookback_days = config.get('lookback_days', 252)
        self.entry_zscore = config.get('entry_zscore', 2.0)
        self.exit_zscore = config.get('exit_zscore', 0.5)
        self.pairs = config.get('pairs', None)
        self.min_correlation = config.get('min_correlation', 0.80)
        self.max_pairs = config.get('max_pairs', 5)
        
        # Estado de los pares activos
        self.active_pairs: Dict[Tuple[str, str], Dict] = {}
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales de pairs trading.
        """
        signals = []
        
        if len(prices) < self.lookback_days:
            return signals
        
        # Detectar pares si no están definidos
        if self.pairs is None:
            self.pairs = self._find_cointegrated_pairs(prices)
        
        historical_prices = prices.tail(self.lookback_days)
        current_prices = prices.iloc[-1]
        
        for pair in self.pairs[:self.max_pairs]:
            symbol1, symbol2 = pair
            
            if symbol1 not in prices.columns or symbol2 not in prices.columns:
                continue
            
            # Calcular hedge ratio y spread
            hedge_ratio, spread_mean, spread_std = self._calculate_pair_stats(
                historical_prices, symbol1, symbol2
            )
            
            if spread_std == 0 or pd.isna(hedge_ratio):
                continue
            
            # Calcular spread actual
            current_spread = current_prices[symbol1] - hedge_ratio * current_prices[symbol2]
            zscore = (current_spread - spread_mean) / spread_std
            
            # Generar señales
            pair_key = (symbol1, symbol2)
            
            if pair_key in self.active_pairs:
                # Verificar si cerrar
                position = self.active_pairs[pair_key]
                
                if abs(zscore) < self.exit_zscore or np.sign(zscore) != np.sign(position['entry_zscore']):
                    # Cerrar posición
                    action1 = 'SELL' if position['action1'] == 'BUY' else 'BUY'
                    action2 = 'SELL' if position['action2'] == 'BUY' else 'BUY'
                    
                    signals.append(StrategySignal(
                        symbol=symbol1,
                        action=action1,
                        strength=0.8,
                        timestamp=prices.index[-1],
                        strategy_name=self.name,
                        metadata={'pair': pair, 'zscore': zscore, 'close_pair': True}
                    ))
                    signals.append(StrategySignal(
                        symbol=symbol2,
                        action=action2,
                        strength=0.8,
                        timestamp=prices.index[-1],
                        strategy_name=self.name,
                        metadata={'pair': pair, 'zscore': zscore, 'close_pair': True}
                    ))
                    
                    del self.active_pairs[pair_key]
            else:
                # Verificar si abrir
                if abs(zscore) > self.entry_zscore:
                    # Abrir posición: largo el subvalorado, corto el sobrevalorado
                    if zscore > 0:
                        # Symbol1 sobrevalorado, Symbol2 subvalorado
                        action1, action2 = 'SELL', 'BUY'
                    else:
                        # Symbol1 subvalorado, Symbol2 sobrevalorado
                        action1, action2 = 'BUY', 'SELL'
                    
                    strength = min(1.0, abs(zscore) / 3)
                    
                    signals.append(StrategySignal(
                        symbol=symbol1,
                        action=action1,
                        strength=strength,
                        timestamp=prices.index[-1],
                        strategy_name=self.name,
                        metadata={
                            'pair': pair,
                            'hedge_ratio': hedge_ratio,
                            'zscore': zscore,
                            'spread_mean': spread_mean,
                            'spread_std': spread_std
                        }
                    ))
                    signals.append(StrategySignal(
                        symbol=symbol2,
                        action=action2,
                        strength=strength,
                        timestamp=prices.index[-1],
                        strategy_name=self.name,
                        metadata={
                            'pair': pair,
                            'hedge_ratio': hedge_ratio,
                            'zscore': zscore
                        }
                    ))
                    
                    self.active_pairs[pair_key] = {
                        'action1': action1,
                        'action2': action2,
                        'entry_zscore': zscore,
                        'hedge_ratio': hedge_ratio
                    }
        
        for signal in signals:
            self.record_signal(signal)
        
        return signals
    
    def _find_cointegrated_pairs(
        self,
        prices: pd.DataFrame,
        max_pairs: int = 10
    ) -> List[Tuple[str, str]]:
        """
        Encuentra pares cointegrados basándose en correlación.
        """
        symbols = prices.columns
        pairs = []
        correlations = []
        
        returns = prices.pct_change().dropna()
        
        for i, s1 in enumerate(symbols):
            for s2 in symbols[i+1:]:
                if s1 in returns.columns and s2 in returns.columns:
                    corr = returns[s1].corr(returns[s2])
                    if corr > self.min_correlation:
                        correlations.append((s1, s2, corr))
        
        # Ordenar por correlación y seleccionar top
        correlations.sort(key=lambda x: x[2], reverse=True)
        pairs = [(s1, s2) for s1, s2, _ in correlations[:max_pairs]]
        
        return pairs
    
    def _calculate_pair_stats(
        self,
        prices: pd.DataFrame,
        symbol1: str,
        symbol2: str
    ) -> Tuple[float, float, float]:
        """
        Calcula hedge ratio y estadísticas del spread.
        """
        y = prices[symbol1].dropna()
        x = prices[symbol2].dropna()
        
        # Alinear índices
        common_idx = y.index.intersection(x.index)
        y = y.loc[common_idx]
        x = x.loc[common_idx]
        
        if len(y) < 30:
            return np.nan, 0, 0
        
        # Hedge ratio por regresión
        slope, intercept, _, _, _ = stats.linregress(x, y)
        
        # Spread
        spread = y - slope * x
        
        return slope, spread.mean(), spread.std()


class MeanReversionStrategy(BaseStrategy):
    """
    Estrategia de Mean Reversion para stocks individuales.
    
    Basada en Bollinger Bands y RSI.
    Compra cuando el precio está por debajo de la banda inferior + RSI < 30.
    Vende cuando el precio está por encima de la banda superior + RSI > 70.
    
    Config:
        bb_period: Período para Bollinger Bands
        bb_std: Desviaciones estándar para las bandas
        rsi_period: Período para RSI
        rsi_oversold: Nivel de sobreventa
        rsi_overbought: Nivel de sobrecompra
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.bb_period = config.get('bb_period', 20)
        self.bb_std = config.get('bb_std', 2.0)
        self.rsi_period = config.get('rsi_period', 14)
        self.rsi_oversold = config.get('rsi_oversold', 30)
        self.rsi_overbought = config.get('rsi_overbought', 70)
        self.min_holding_days = config.get('min_holding_days', 5)
        
        # Tracking de posiciones
        self.position_entry_date: Dict[str, datetime] = {}
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales de mean reversion.
        """
        signals = []
        current_date = prices.index[-1]
        
        for symbol in prices.columns:
            price_series = prices[symbol].dropna()
            
            if len(price_series) < max(self.bb_period, self.rsi_period) + 5:
                continue
            
            current_price = price_series.iloc[-1]
            
            # Calcular Bollinger Bands
            sma = price_series.tail(self.bb_period).mean()
            std = price_series.tail(self.bb_period).std()
            upper_band = sma + self.bb_std * std
            lower_band = sma - self.bb_std * std
            
            # Calcular RSI
            rsi = self._calculate_rsi(price_series, self.rsi_period)
            
            # Verificar si tenemos posición
            has_position = symbol in self.position_entry_date
            
            if not has_position:
                # Señal de compra: precio < lower_band y RSI < oversold
                if current_price < lower_band and rsi < self.rsi_oversold:
                    strength = min(1.0, (lower_band - current_price) / std * 0.5 + 
                                  (self.rsi_oversold - rsi) / 30 * 0.5)
                    
                    signal = StrategySignal(
                        symbol=symbol,
                        action='BUY',
                        strength=strength,
                        timestamp=current_date,
                        strategy_name=self.name,
                        metadata={
                            'price': current_price,
                            'lower_band': lower_band,
                            'upper_band': upper_band,
                            'rsi': rsi,
                            'sma': sma
                        }
                    )
                    signals.append(signal)
                    self.position_entry_date[symbol] = current_date
                    self.record_signal(signal)
            else:
                # Verificar si cerrar
                holding_days = (current_date - self.position_entry_date[symbol]).days
                
                if holding_days >= self.min_holding_days:
                    # Cerrar si precio > upper_band o RSI > overbought
                    if current_price > upper_band or rsi > self.rsi_overbought:
                        strength = min(1.0, (current_price - upper_band) / std * 0.5 + 
                                      (rsi - self.rsi_overbought) / 30 * 0.5)
                        
                        signal = StrategySignal(
                            symbol=symbol,
                            action='SELL',
                            strength=strength,
                            timestamp=current_date,
                            strategy_name=self.name,
                            metadata={
                                'price': current_price,
                                'upper_band': upper_band,
                                'rsi': rsi,
                                'holding_days': holding_days
                            }
                        )
                        signals.append(signal)
                        del self.position_entry_date[symbol]
                        self.record_signal(signal)
        
        return signals
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """Calcula RSI"""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = prices.diff()
        gain = (deltas.where(deltas > 0, 0)).rolling(window=period).mean()
        loss = (-deltas.where(deltas < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0


class StatisticalArbitrageStrategy(BaseStrategy):
    """
    Estrategia de Statistical Arbitrage basada en PCA.
    
    Identifica factores principales del mercado y genera
    señales contra los residuos (alpha).
    
    Config:
        n_components: Número de factores principales
        lookback_days: Período de lookback
        entry_threshold: Umbral de entrada en desviaciones
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.n_components = config.get('n_components', 5)
        self.lookback_days = config.get('lookback_days', 252)
        self.entry_threshold = config.get('entry_threshold', 2.0)
        
        try:
            from sklearn.decomposition import PCA
            self.pca_available = True
        except ImportError:
            self.pca_available = False
            print("Warning: sklearn no disponible, StatisticalArbitrage deshabilitado")
    
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales basadas en residuos del modelo de factores.
        """
        if not self.pca_available or len(prices) < self.lookback_days:
            return []
        
        from sklearn.decomposition import PCA
        
        signals = []
        returns = self.calculate_returns(prices.tail(self.lookback_days))
        
        # Normalizar retornos
        returns_clean = returns.dropna(axis=1, thresh=len(returns)*0.9)
        returns_clean = returns_clean.fillna(0)
        
        if len(returns_clean.columns) < self.n_components:
            return []
        
        # PCA
        pca = PCA(n_components=self.n_components)
        factors = pca.fit_transform(returns_clean)
        
        # Reconstruir y calcular residuos
        reconstructed = pca.inverse_transform(factors)
        residuals = returns_clean.values - reconstructed
        
        # Z-score de residuos para cada stock
        for i, symbol in enumerate(returns_clean.columns):
            resid_series = residuals[:, i]
            current_resid = resid_series[-1]
            resid_std = np.std(resid_series)
            
            if resid_std == 0:
                continue
            
            zscore = current_resid / resid_std
            
            if abs(zscore) > self.entry_threshold:
                # Señal contraria al residuo
                action = 'BUY' if zscore < 0 else 'SELL'
                strength = min(1.0, abs(zscore) / 3)
                
                signal = StrategySignal(
                    symbol=symbol,
                    action=action,
                    strength=strength,
                    timestamp=prices.index[-1],
                    strategy_name=self.name,
                    metadata={
                        'residual_zscore': zscore,
                        'explained_variance': sum(pca.explained_variance_ratio_)
                    }
                )
                signals.append(signal)
                self.record_signal(signal)
        
        return signals