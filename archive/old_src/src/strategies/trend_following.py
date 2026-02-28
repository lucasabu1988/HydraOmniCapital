"""
Estrategias de Trend Following

Basadas en:
- Dennis, R. & Eckhardt, W. - Turtle Trading System
- Donchian, R. - Donchian Channels
- Covel, M.W. (2009) - Trend Following
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime

from .base import BaseStrategy, StrategySignal, Allocation


class TurtleStrategy(BaseStrategy):
    """
    Estrategia de Turtle Trading System.
    
    Sistema completo de trend following con:
    - Entrada en breakout de 20/55 días
    - Position sizing basado en ATR (N)
    - Stop loss de 2N
    - Pyramiding (hasta 4 unidades)
    - Sistema 1 (20 días) y Sistema 2 (55 días)
    
    Config:
        entry_period: Período para breakout de entrada (20 o 55)
        exit_period: Período para breakout de salida (10 o 20)
        atr_period: Período para calcular ATR (default: 20)
        risk_per_trade: Riesgo por trade como % del capital (default: 0.01)
        max_units: Máximo número de unidades por posición (default: 4)
        atr_multiple_stop: Múltiplo de ATR para stop loss (default: 2)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.entry_period = config.get('entry_period', 20)
        self.exit_period = config.get('exit_period', 10)
        self.atr_period = config.get('atr_period', 20)
        self.risk_per_trade = config.get('risk_per_trade', 0.01)
        self.max_units = config.get('max_units', 4)
        self.atr_multiple_stop = config.get('atr_multiple_stop', 2.0)
        
        # Tracking de posiciones
        self.positions: Dict[str, Dict] = {}
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales siguiendo las reglas de Turtle Trading.
        """
        signals = []
        
        # Necesitamos High, Low, Close - usamos precios aproximados
        # En producción, usar datos OHLC completos
        
        for symbol in prices.columns:
            price_series = prices[symbol].dropna()
            
            if len(price_series) < max(self.entry_period, self.exit_period, self.atr_period) + 5:
                continue
            
            current_price = price_series.iloc[-1]
            
            # Calcular ATR (usando True Range simplificado)
            atr = self._calculate_atr_simple(price_series, self.atr_period)
            
            if atr == 0 or pd.isna(atr):
                continue
            
            # Nivel de entrada (Donchian Channel)
            entry_high = price_series.tail(self.entry_period).max()
            entry_low = price_series.tail(self.entry_period).min()
            
            # Nivel de salida
            exit_high = price_series.tail(self.exit_period).max()
            exit_low = price_series.tail(self.exit_period).min()
            
            has_position = symbol in self.positions
            
            if not has_position:
                # Señal de entrada en breakout
                if current_price > entry_high:
                    # Breakout alcista
                    dollar_risk = self.risk_per_trade  # Simplificado
                    position_size = self._calculate_position_size(dollar_risk, atr)
                    
                    signal = StrategySignal(
                        symbol=symbol,
                        action='BUY',
                        strength=0.9,
                        timestamp=prices.index[-1],
                        strategy_name=self.name,
                        metadata={
                            'entry_type': 'breakout_long',
                            'entry_price': current_price,
                            'atr': atr,
                            'stop_loss': current_price - self.atr_multiple_stop * atr,
                            'position_size': position_size,
                            'units': 1
                        }
                    )
                    signals.append(signal)
                    
                    self.positions[symbol] = {
                        'direction': 'LONG',
                        'entry_price': current_price,
                        'atr': atr,
                        'units': 1,
                        'stop_loss': current_price - self.atr_multiple_stop * atr
                    }
                    self.record_signal(signal)
                    
                elif current_price < entry_low:
                    # Breakout bajista (short)
                    signal = StrategySignal(
                        symbol=symbol,
                        action='SELL',
                        strength=0.9,
                        timestamp=prices.index[-1],
                        strategy_name=self.name,
                        metadata={
                            'entry_type': 'breakout_short',
                            'entry_price': current_price,
                            'atr': atr,
                            'stop_loss': current_price + self.atr_multiple_stop * atr
                        }
                    )
                    signals.append(signal)
                    
                    self.positions[symbol] = {
                        'direction': 'SHORT',
                        'entry_price': current_price,
                        'atr': atr,
                        'units': 1,
                        'stop_loss': current_price + self.atr_multiple_stop * atr
                    }
                    self.record_signal(signal)
            else:
                position = self.positions[symbol]
                
                # Verificar stop loss
                if position['direction'] == 'LONG':
                    if current_price <= position['stop_loss']:
                        # Stop loss hit
                        signal = StrategySignal(
                            symbol=symbol,
                            action='SELL',
                            strength=1.0,
                            timestamp=prices.index[-1],
                            strategy_name=self.name,
                            metadata={
                                'exit_type': 'stop_loss',
                                'exit_price': current_price,
                                'pnl_pct': (current_price - position['entry_price']) / position['entry_price']
                            }
                        )
                        signals.append(signal)
                        del self.positions[symbol]
                        self.record_signal(signal)
                        continue
                    
                    # Verificar salida por breakout inverso
                    if current_price < exit_low:
                        signal = StrategySignal(
                            symbol=symbol,
                            action='SELL',
                            strength=0.8,
                            timestamp=prices.index[-1],
                            strategy_name=self.name,
                            metadata={
                                'exit_type': 'breakout_exit',
                                'exit_price': current_price,
                                'pnl_pct': (current_price - position['entry_price']) / position['entry_price']
                            }
                        )
                        signals.append(signal)
                        del self.positions[symbol]
                        self.record_signal(signal)
                        continue
                    
                    # Pyramiding: agregar unidades si el precio sube 0.5N
                    if position['units'] < self.max_units:
                        next_add = position['entry_price'] + 0.5 * position['atr'] * position['units']
                        if current_price >= next_add:
                            position['units'] += 1
                            # Actualizar stop loss
                            position['stop_loss'] = current_price - self.atr_multiple_stop * atr
                            
                            signal = StrategySignal(
                                symbol=symbol,
                                action='BUY',
                                strength=0.7,
                                timestamp=prices.index[-1],
                                strategy_name=self.name,
                                metadata={
                                    'entry_type': 'pyramiding',
                                    'unit': position['units'],
                                    'atr': atr
                                }
                            )
                            signals.append(signal)
                            self.record_signal(signal)
        
        return signals
    
    def _calculate_atr_simple(self, prices: pd.Series, period: int = 20) -> float:
        """Calcula ATR simplificado usando solo precios de cierre"""
        if len(prices) < period + 1:
            return 0.0
        
        # Usar rangos de precios como aproximación
        high_low = prices.diff().abs()
        atr = high_low.tail(period).mean()
        
        return atr if not pd.isna(atr) else 0.0
    
    def _calculate_position_size(self, dollar_risk: float, atr: float) -> float:
        """Calcula tamaño de posición en unidades"""
        risk_per_unit = self.atr_multiple_stop * atr
        if risk_per_unit == 0:
            return 0
        return dollar_risk / risk_per_unit


class DonchianStrategy(BaseStrategy):
    """
    Estrategia de Donchian Channels.
    
    Sistema simple de trend following:
    - Compra cuando el precio rompe el máximo de N períodos
    - Vende cuando el precio rompe el mínimo de N períodos
    
    Config:
        channel_period: Período para calcular canales (default: 20)
        use_filter: Usar filtro de tendencia (default: True)
        filter_period: Período para filtro de tendencia (default: 50)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.channel_period = config.get('channel_period', 20)
        self.use_filter = config.get('use_filter', True)
        self.filter_period = config.get('filter_period', 50)
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales basadas en breakouts de Donchian Channels.
        """
        signals = []
        
        for symbol in prices.columns:
            price_series = prices[symbol].dropna()
            
            min_period = max(self.channel_period, self.filter_period) if self.use_filter else self.channel_period
            if len(price_series) < min_period + 5:
                continue
            
            current_price = price_series.iloc[-1]
            
            # Calcular canales de Donchian
            upper_channel = price_series.tail(self.channel_period).max()
            lower_channel = price_series.tail(self.channel_period).min()
            middle_channel = (upper_channel + lower_channel) / 2
            
            # Filtro de tendencia
            if self.use_filter:
                trend_ma = price_series.tail(self.filter_period).mean()
                trend_up = current_price > trend_ma
            else:
                trend_up = True
            
            # Detectar breakout
            prev_price = price_series.iloc[-2]
            
            # Breakout alcista
            if current_price > upper_channel and prev_price <= upper_channel and trend_up:
                strength = min(1.0, (current_price - upper_channel) / upper_channel * 20 + 0.5)
                
                signal = StrategySignal(
                    symbol=symbol,
                    action='BUY',
                    strength=strength,
                    timestamp=prices.index[-1],
                    strategy_name=self.name,
                    metadata={
                        'breakout_type': 'upper',
                        'channel_high': upper_channel,
                        'channel_low': lower_channel,
                        'trend_aligned': trend_up
                    }
                )
                signals.append(signal)
                self.record_signal(signal)
            
            # Breakout bajista
            elif current_price < lower_channel and prev_price >= lower_channel:
                strength = min(1.0, (lower_channel - current_price) / lower_channel * 20 + 0.5)
                
                signal = StrategySignal(
                    symbol=symbol,
                    action='SELL',
                    strength=strength,
                    timestamp=prices.index[-1],
                    strategy_name=self.name,
                    metadata={
                        'breakout_type': 'lower',
                        'channel_high': upper_channel,
                        'channel_low': lower_channel,
                        'trend_aligned': not trend_up
                    }
                )
                signals.append(signal)
                self.record_signal(signal)
        
        return signals


class MovingAverageTrendStrategy(BaseStrategy):
    """
    Estrategia de Trend Following con Múltiples Medias Móviles.
    
    Usa triple sistema de MAs:
    - Fast MA: Señal de entrada
    - Medium MA: Confirmación de tendencia
    - Slow MA: Filtro de tendencia mayor
    
    Config:
        fast_ma: Período MA rápida (default: 10)
        medium_ma: Período MA media (default: 30)
        slow_ma: Período MA lenta (default: 50)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.fast_ma = config.get('fast_ma', 10)
        self.medium_ma = config.get('medium_ma', 30)
        self.slow_ma = config.get('slow_ma', 50)
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales basadas en alineación de medias móviles.
        """
        signals = []
        
        for symbol in prices.columns:
            price_series = prices[symbol].dropna()
            
            if len(price_series) < self.slow_ma + 5:
                continue
            
            # Calcular MAs
            fast = price_series.rolling(self.fast_ma).mean().iloc[-1]
            medium = price_series.rolling(self.medium_ma).mean().iloc[-1]
            slow = price_series.rolling(self.slow_ma).mean().iloc[-1]
            current_price = price_series.iloc[-1]
            
            if pd.isna(fast) or pd.isna(medium) or pd.isna(slow):
                continue
            
            # Calcular valores previos para detectar cruces
            fast_prev = price_series.rolling(self.fast_ma).mean().iloc[-2]
            medium_prev = price_series.rolling(self.medium_ma).mean().iloc[-2]
            
            # Tendencia alcista: Fast > Medium > Slow
            uptrend = fast > medium > slow
            downtrend = fast < medium < slow
            
            # Cruce alcista
            if fast > medium and fast_prev <= medium_prev and uptrend:
                strength = min(1.0, (fast - medium) / medium * 50 + 0.5)
                
                signal = StrategySignal(
                    symbol=symbol,
                    action='BUY',
                    strength=strength,
                    timestamp=prices.index[-1],
                    strategy_name=self.name,
                    metadata={
                        'signal_type': 'ma_crossover',
                        'fast_ma': fast,
                        'medium_ma': medium,
                        'slow_ma': slow,
                        'trend': 'uptrend'
                    }
                )
                signals.append(signal)
                self.record_signal(signal)
            
            # Cruce bajista
            elif fast < medium and fast_prev >= medium_prev and downtrend:
                strength = min(1.0, (medium - fast) / medium * 50 + 0.5)
                
                signal = StrategySignal(
                    symbol=symbol,
                    action='SELL',
                    strength=strength,
                    timestamp=prices.index[-1],
                    strategy_name=self.name,
                    metadata={
                        'signal_type': 'ma_crossover',
                        'fast_ma': fast,
                        'medium_ma': medium,
                        'slow_ma': slow,
                        'trend': 'downtrend'
                    }
                )
                signals.append(signal)
                self.record_signal(signal)
        
        return signals


class KeltnerChannelStrategy(BaseStrategy):
    """
    Estrategia de Keltner Channels.
    
    Similar a Bollinger Bands pero usando ATR:
    - Upper Band: EMA + (ATR * multiplier)
    - Lower Band: EMA - (ATR * multiplier)
    
    Config:
        ema_period: Período para EMA (default: 20)
        atr_period: Período para ATR (default: 14)
        atr_multiplier: Multiplicador de ATR (default: 2.0)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.ema_period = config.get('ema_period', 20)
        self.atr_period = config.get('atr_period', 14)
        self.atr_multiplier = config.get('atr_multiplier', 2.0)
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales basadas en Keltner Channels.
        """
        signals = []
        
        for symbol in prices.columns:
            price_series = prices[symbol].dropna()
            
            if len(price_series) < max(self.ema_period, self.atr_period) + 5:
                continue
            
            # EMA
            ema = price_series.ewm(span=self.ema_period).mean()
            current_ema = ema.iloc[-1]
            
            # ATR simplificado
            atr = self._calculate_atr(price_series, self.atr_period)
            
            if pd.isna(atr) or atr == 0:
                continue
            
            # Keltner Channels
            upper_band = current_ema + self.atr_multiplier * atr
            lower_band = current_ema - self.atr_multiplier * atr
            
            current_price = price_series.iloc[-1]
            prev_price = price_series.iloc[-2]
            
            # Breakout alcista (cierre por encima de upper band)
            if current_price > upper_band and prev_price <= upper_band:
                signal = StrategySignal(
                    symbol=symbol,
                    action='BUY',
                    strength=0.85,
                    timestamp=prices.index[-1],
                    strategy_name=self.name,
                    metadata={
                        'channel_type': 'keltner',
                        'upper_band': upper_band,
                        'lower_band': lower_band,
                        'ema': current_ema,
                        'atr': atr
                    }
                )
                signals.append(signal)
                self.record_signal(signal)
            
            # Breakout bajista
            elif current_price < lower_band and prev_price >= lower_band:
                signal = StrategySignal(
                    symbol=symbol,
                    action='SELL',
                    strength=0.85,
                    timestamp=prices.index[-1],
                    strategy_name=self.name,
                    metadata={
                        'channel_type': 'keltner',
                        'upper_band': upper_band,
                        'lower_band': lower_band,
                        'ema': current_ema,
                        'atr': atr
                    }
                )
                signals.append(signal)
                self.record_signal(signal)
        
        return signals
    
    def _calculate_atr(self, prices: pd.Series, period: int) -> float:
        """Calcula ATR simplificado"""
        if len(prices) < period + 1:
            return 0.0
        
        high_low = prices.diff().abs()
        atr = high_low.rolling(window=period).mean().iloc[-1]
        
        return atr if not pd.isna(atr) else 0.0