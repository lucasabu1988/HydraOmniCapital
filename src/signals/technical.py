"""
Señales Técnicas
Indicadores técnicos para generar señales de entrada y salida
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class SignalType(Enum):
    BUY = 1
    SELL = -1
    HOLD = 0


@dataclass
class Signal:
    """Señal de trading"""
    symbol: str
    type: SignalType
    strength: float  # 0.0 a 1.0
    indicator: str
    timestamp: pd.Timestamp
    metadata: Dict[str, Any] = None


class TechnicalSignals:
    """
    Genera señales basadas en indicadores técnicos
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.momentum_config = config.get('entry', [{}])[0] if config.get('entry') else {}
        self.trend_config = next((e for e in config.get('entry', []) if e.get('name') == 'trend'), {})
    
    def calculate_momentum(
        self,
        prices: pd.Series,
        lookback: int = None
    ) -> float:
        """
        Calcula el momentum de un activo
        
        Args:
            prices: Serie de precios
            lookback: Período de lookback
            
        Returns:
            Momentum como retorno porcentual
        """
        if lookback is None:
            lookback = self.momentum_config.get('lookback', 90)
        
        if len(prices) < lookback:
            return 0.0
        
        if prices.iloc[-lookback] == 0:
            return 0.0
        momentum = (prices.iloc[-1] - prices.iloc[-lookback]) / prices.iloc[-lookback]
        return momentum
    
    def calculate_moving_averages(
        self,
        prices: pd.Series
    ) -> Tuple[pd.Series, pd.Series]:
        """
        Calcula medias móviles corta y larga
        
        Args:
            prices: Serie de precios
            
        Returns:
            Tupla (short_ma, long_ma)
        """
        short_period = self.trend_config.get('short_ma', 20)
        long_period = self.trend_config.get('long_ma', 50)
        
        short_ma = prices.rolling(window=short_period, min_periods=1).mean()
        long_ma = prices.rolling(window=long_period, min_periods=1).mean()
        
        return short_ma, long_ma
    
    def calculate_rsi(
        self,
        prices: pd.Series,
        period: int = 14
    ) -> float:
        """
        Calcula el Relative Strength Index (RSI)
        
        Args:
            prices: Serie de precios
            period: Período para el cálculo
            
        Returns:
            Valor RSI (0-100)
        """
        if len(prices) < period + 1:
            return 50.0
        
        deltas = prices.diff()
        gain = (deltas.where(deltas > 0, 0)).rolling(window=period).mean()
        loss = (-deltas.where(deltas < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(100.0)  # loss=0 means all gains, RSI=100
        
        return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0
    
    def calculate_macd(
        self,
        prices: pd.Series,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9
    ) -> Tuple[float, float, float]:
        """
        Calcula MACD (Moving Average Convergence Divergence)
        
        Args:
            prices: Serie de precios
            fast: Período rápido
            slow: Período lento
            signal: Período de señal
            
        Returns:
            Tupla (macd_line, signal_line, histogram)
        """
        ema_fast = prices.ewm(span=fast).mean()
        ema_slow = prices.ewm(span=slow).mean()
        
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal).mean()
        histogram = macd_line - signal_line
        
        return (
            macd_line.iloc[-1],
            signal_line.iloc[-1],
            histogram.iloc[-1]
        )
    
    def calculate_bollinger_bands(
        self,
        prices: pd.Series,
        period: int = 20,
        std_dev: float = 2.0
    ) -> Tuple[float, float, float]:
        """
        Calcula Bandas de Bollinger
        
        Args:
            prices: Serie de precios
            period: Período de la media móvil
            std_dev: Múltiplo de desviación estándar
            
        Returns:
            Tupla (upper_band, middle_band, lower_band)
        """
        middle_band = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        
        upper_band = middle_band + (std * std_dev)
        lower_band = middle_band - (std * std_dev)
        
        return (
            upper_band.iloc[-1],
            middle_band.iloc[-1],
            lower_band.iloc[-1]
        )
    
    def calculate_atr(
        self,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14
    ) -> float:
        """
        Calcula Average True Range (ATR)
        
        Args:
            high: Serie de precios altos
            low: Serie de precios bajos
            close: Serie de precios de cierre
            period: Período para el cálculo
            
        Returns:
            Valor ATR
        """
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr.iloc[-1] if not pd.isna(atr.iloc[-1]) else 0.0
    
    def generate_momentum_signal(
        self,
        symbol: str,
        prices: pd.Series
    ) -> Optional[Signal]:
        """
        Genera señal basada en momentum
        
        Args:
            symbol: Símbolo del activo
            prices: Serie de precios
            
        Returns:
            Señal de trading o None
        """
        momentum = self.calculate_momentum(prices)
        min_momentum = self.momentum_config.get('min_momentum', 0.05)
        
        if momentum > min_momentum:
            strength = min(1.0, momentum / (min_momentum * 2))
            return Signal(
                symbol=symbol,
                type=SignalType.BUY,
                strength=strength,
                indicator='MOMENTUM',
                timestamp=prices.index[-1],
                metadata={'momentum': momentum}
            )
        elif momentum < -min_momentum:
            strength = min(1.0, abs(momentum) / (min_momentum * 2))
            return Signal(
                symbol=symbol,
                type=SignalType.SELL,
                strength=strength,
                indicator='MOMENTUM_REVERSAL',
                timestamp=prices.index[-1],
                metadata={'momentum': momentum}
            )
        
        return None
    
    def generate_trend_signal(
        self,
        symbol: str,
        prices: pd.Series
    ) -> Optional[Signal]:
        """
        Genera señal basada en tendencia (cruce de medias móviles)
        
        Args:
            symbol: Símbolo del activo
            prices: Serie de precios
            
        Returns:
            Señal de trading o None
        """
        short_ma, long_ma = self.calculate_moving_averages(prices)
        
        if len(short_ma) < 2 or len(long_ma) < 2:
            return None
        
        # Cruce alcista
        if short_ma.iloc[-2] <= long_ma.iloc[-2] and short_ma.iloc[-1] > long_ma.iloc[-1]:
            distance = (short_ma.iloc[-1] - long_ma.iloc[-1]) / long_ma.iloc[-1]
            strength = min(1.0, distance * 10)
            return Signal(
                symbol=symbol,
                type=SignalType.BUY,
                strength=strength,
                indicator='TREND_CROSSOVER',
                timestamp=prices.index[-1],
                metadata={'short_ma': short_ma.iloc[-1], 'long_ma': long_ma.iloc[-1]}
            )
        
        # Cruce bajista
        elif short_ma.iloc[-2] >= long_ma.iloc[-2] and short_ma.iloc[-1] < long_ma.iloc[-1]:
            distance = (long_ma.iloc[-1] - short_ma.iloc[-1]) / long_ma.iloc[-1]
            strength = min(1.0, distance * 10)
            return Signal(
                symbol=symbol,
                type=SignalType.SELL,
                strength=strength,
                indicator='TREND_REVERSAL',
                timestamp=prices.index[-1],
                metadata={'short_ma': short_ma.iloc[-1], 'long_ma': long_ma.iloc[-1]}
            )
        
        return None
    
    def generate_rsi_signal(
        self,
        symbol: str,
        prices: pd.Series,
        oversold: float = 30,
        overbought: float = 70
    ) -> Optional[Signal]:
        """
        Genera señal basada en RSI
        
        Args:
            symbol: Símbolo del activo
            prices: Serie de precios
            oversold: Nivel de sobreventa
            overbought: Nivel de sobrecompra
            
        Returns:
            Señal de trading o None
        """
        rsi = self.calculate_rsi(prices)
        
        if rsi < oversold:
            strength = (oversold - rsi) / oversold
            return Signal(
                symbol=symbol,
                type=SignalType.BUY,
                strength=min(1.0, strength),
                indicator='RSI_OVERSOLD',
                timestamp=prices.index[-1],
                metadata={'rsi': rsi}
            )
        elif rsi > overbought:
            strength = (rsi - overbought) / (100 - overbought)
            return Signal(
                symbol=symbol,
                type=SignalType.SELL,
                strength=min(1.0, strength),
                indicator='RSI_OVERBOUGHT',
                timestamp=prices.index[-1],
                metadata={'rsi': rsi}
            )
        
        return None
    
    def generate_macd_signal(
        self,
        symbol: str,
        prices: pd.Series
    ) -> Optional[Signal]:
        """
        Genera señal basada en MACD
        
        Args:
            symbol: Símbolo del activo
            prices: Serie de precios
            
        Returns:
            Señal de trading o None
        """
        macd_line, signal_line, histogram = self.calculate_macd(prices)
        
        # Cruce alcista
        if macd_line > signal_line and histogram > 0:
            strength = min(1.0, abs(histogram) / abs(macd_line) if macd_line != 0 else 0.5)
            return Signal(
                symbol=symbol,
                type=SignalType.BUY,
                strength=strength,
                indicator='MACD_BULLISH',
                timestamp=prices.index[-1],
                metadata={'macd': macd_line, 'signal': signal_line}
            )
        # Cruce bajista
        elif macd_line < signal_line and histogram < 0:
            strength = min(1.0, abs(histogram) / abs(macd_line) if macd_line != 0 else 0.5)
            return Signal(
                symbol=symbol,
                type=SignalType.SELL,
                strength=strength,
                indicator='MACD_BEARISH',
                timestamp=prices.index[-1],
                metadata={'macd': macd_line, 'signal': signal_line}
            )
        
        return None
    
    def analyze_all_signals(
        self,
        symbol: str,
        prices: pd.Series
    ) -> Dict[str, Any]:
        """
        Analiza todas las señales técnicas para un activo
        
        Args:
            symbol: Símbolo del activo
            prices: Serie de precios
            
        Returns:
            Diccionario con todas las señales y análisis
        """
        signals = []
        
        # Generar todas las señales
        momentum_sig = self.generate_momentum_signal(symbol, prices)
        if momentum_sig:
            signals.append(momentum_sig)
        
        trend_sig = self.generate_trend_signal(symbol, prices)
        if trend_sig:
            signals.append(trend_sig)
        
        rsi_sig = self.generate_rsi_signal(symbol, prices)
        if rsi_sig:
            signals.append(rsi_sig)
        
        macd_sig = self.generate_macd_signal(symbol, prices)
        if macd_sig:
            signals.append(macd_sig)
        
        # Calcular score compuesto
        buy_score = sum(s.strength for s in signals if s.type == SignalType.BUY)
        sell_score = sum(s.strength for s in signals if s.type == SignalType.SELL)
        
        # Determinar señal final
        if buy_score > sell_score and buy_score > 0.5:
            final_signal = SignalType.BUY
            final_strength = min(1.0, buy_score / 2)
        elif sell_score > buy_score and sell_score > 0.5:
            final_signal = SignalType.SELL
            final_strength = min(1.0, sell_score / 2)
        else:
            final_signal = SignalType.HOLD
            final_strength = 0.0
        
        return {
            'symbol': symbol,
            'signals': signals,
            'buy_score': buy_score,
            'sell_score': sell_score,
            'final_signal': final_signal,
            'final_strength': final_strength,
            'indicators': {
                'momentum': self.calculate_momentum(prices),
                'rsi': self.calculate_rsi(prices),
                'macd': self.calculate_macd(prices)[0]
            }
        }
