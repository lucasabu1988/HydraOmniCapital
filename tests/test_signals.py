"""
Tests para el módulo de señales
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.signals.technical import TechnicalSignals, SignalType
from src.signals.fundamental import FundamentalSignals, FundamentalMetrics, FundamentalScore


class TestTechnicalSignals:
    """Tests para señales técnicas"""
    
    @pytest.fixture
    def tech_signals(self):
        config = {
            'entry': [
                {'name': 'momentum', 'weight': 0.30, 'lookback': 90, 'min_momentum': 0.05},
                {'name': 'trend', 'weight': 0.20, 'short_ma': 20, 'long_ma': 50}
            ]
        }
        return TechnicalSignals(config)
    
    @pytest.fixture
    def bullish_prices(self):
        """Genera precios con tendencia alcista"""
        np.random.seed(42)
        trend = np.linspace(100, 150, 100)
        noise = np.random.normal(0, 2, 100)
        prices = trend + noise
        return pd.Series(prices, index=pd.date_range('2023-01-01', periods=100))
    
    @pytest.fixture
    def bearish_prices(self):
        """Genera precios con tendencia bajista"""
        np.random.seed(42)
        trend = np.linspace(150, 100, 100)
        noise = np.random.normal(0, 2, 100)
        prices = trend + noise
        return pd.Series(prices, index=pd.date_range('2023-01-01', periods=100))
    
    def test_calculate_momentum(self, tech_signals, bullish_prices):
        """Test cálculo de momentum"""
        momentum = tech_signals.calculate_momentum(bullish_prices, lookback=20)
        assert momentum > 0  # Debe ser positivo en tendencia alcista
    
    def test_calculate_moving_averages(self, tech_signals, bullish_prices):
        """Test cálculo de medias móviles"""
        short_ma, long_ma = tech_signals.calculate_moving_averages(bullish_prices)
        
        assert len(short_ma) == len(bullish_prices)
        assert len(long_ma) == len(bullish_prices)
        assert short_ma.iloc[-1] > long_ma.iloc[-1]  # Tendencia alcista
    
    def test_calculate_rsi(self, tech_signals):
        """Test cálculo de RSI"""
        # Precios que suben consistentemente
        prices = pd.Series([100 + i for i in range(50)])
        rsi = tech_signals.calculate_rsi(prices)
        
        assert 0 <= rsi <= 100
        assert rsi > 50  # RSI alto en tendencia alcista
    
    def test_calculate_macd(self, tech_signals, bullish_prices):
        """Test cálculo de MACD"""
        macd_line, signal_line, histogram = tech_signals.calculate_macd(bullish_prices)
        
        assert isinstance(macd_line, float)
        assert isinstance(signal_line, float)
        assert isinstance(histogram, float)
    
    def test_calculate_bollinger_bands(self, tech_signals, bullish_prices):
        """Test cálculo de Bandas de Bollinger"""
        upper, middle, lower = tech_signals.calculate_bollinger_bands(bullish_prices)
        
        assert upper > middle > lower
        assert upper > 0 and middle > 0 and lower > 0
    
    def test_generate_momentum_signal_buy(self, tech_signals, bullish_prices):
        """Test señal de compra por momentum"""
        signal = tech_signals.generate_momentum_signal('AAPL', bullish_prices)
        
        if signal:
            assert signal.type == SignalType.BUY
            assert signal.strength > 0
            assert signal.indicator == 'MOMENTUM'
    
    def test_generate_trend_signal_crossover(self, tech_signals):
        """Test señal de cruce de medias móviles"""
        # Simular cruce alcista
        prices = pd.Series([100] * 19 + list(range(100, 120)))
        
        signal = tech_signals.generate_trend_signal('AAPL', prices)
        
        # Puede ser BUY o None dependiendo de los datos
        if signal:
            assert signal.symbol == 'AAPL'
            assert signal.strength >= 0
    
    def test_generate_rsi_signal_oversold(self, tech_signals):
        """Test señal RSI sobreventa"""
        # Precios que caen para generar RSI bajo
        prices = pd.Series([100 - i * 2 for i in range(30)])
        
        signal = tech_signals.generate_rsi_signal('AAPL', prices)
        
        if signal:
            assert signal.type == SignalType.BUY
            assert signal.indicator == 'RSI_OVERSOLD'
    
    def test_analyze_all_signals(self, tech_signals, bullish_prices):
        """Test análisis completo de señales"""
        result = tech_signals.analyze_all_signals('AAPL', bullish_prices)
        
        assert 'symbol' in result
        assert 'signals' in result
        assert 'final_signal' in result
        assert 'indicators' in result
        
        assert result['symbol'] == 'AAPL'
        assert isinstance(result['signals'], list)


class TestFundamentalSignals:
    """Tests para señales fundamentales"""
    
    @pytest.fixture
    def fund_signals(self):
        config = {
            'entry': [
                {'name': 'value', 'weight': 0.25},
                {'name': 'quality', 'weight': 0.25, 'min_roe': 0.15}
            ]
        }
        return FundamentalSignals(config)
    
    @pytest.fixture
    def strong_company(self):
        """Métricas de empresa fuerte"""
        return FundamentalMetrics(
            symbol='AAPL',
            pe_ratio=12.0,
            forward_pe=10.0,
            pb_ratio=1.5,
            ev_ebitda=8.0,
            roe=0.25,
            roa=0.15,
            operating_margin=0.25,
            debt_equity=0.20,
            current_ratio=2.0,
            revenue_growth=0.15,
            earnings_growth=0.20,
            dividend_yield=0.03
        )
    
    @pytest.fixture
    def weak_company(self):
        """Métricas de empresa débil"""
        return FundamentalMetrics(
            symbol='WEAK',
            pe_ratio=50.0,
            forward_pe=45.0,
            pb_ratio=5.0,
            ev_ebitda=25.0,
            roe=0.05,
            roa=0.02,
            operating_margin=0.05,
            debt_equity=2.0,
            current_ratio=0.8,
            revenue_growth=-0.05,
            earnings_growth=-0.10
        )
    
    def test_calculate_value_score_strong(self, fund_signals, strong_company):
        """Test score de valor para empresa fuerte"""
        score = fund_signals.calculate_value_score(strong_company)
        
        assert 0 <= score <= 1
        assert score > 0.7  # Debe ser alto para empresa con buena valoración
    
    def test_calculate_value_score_weak(self, fund_signals, weak_company):
        """Test score de valor para empresa débil"""
        score = fund_signals.calculate_value_score(weak_company)
        
        assert 0 <= score <= 1
        assert score < 0.5  # Debe ser bajo para empresa cara
    
    def test_calculate_quality_score_strong(self, fund_signals, strong_company):
        """Test score de calidad para empresa fuerte"""
        score = fund_signals.calculate_quality_score(strong_company)
        
        assert 0 <= score <= 1
        assert score > 0.7
    
    def test_calculate_quality_score_weak(self, fund_signals, weak_company):
        """Test score de calidad para empresa débil"""
        score = fund_signals.calculate_quality_score(weak_company)
        
        assert 0 <= score <= 1
        assert score < 0.5
    
    def test_calculate_growth_score(self, fund_signals):
        """Test score de crecimiento"""
        high_growth = FundamentalMetrics(
            symbol='GROW',
            revenue_growth=0.30,
            earnings_growth=0.35
        )
        
        score = fund_signals.calculate_growth_score(high_growth)
        
        assert 0 <= score <= 1
        assert score > 0.8  # Alto crecimiento = alto score
    
    def test_generate_fundamental_signal_strong(self, fund_signals, strong_company):
        """Test señal fundamental para empresa fuerte"""
        result = fund_signals.generate_fundamental_signal(strong_company)
        
        assert result['symbol'] == 'AAPL'
        assert result['composite_score'] > 0.6
        assert result['signal'] in [FundamentalScore.BUY, FundamentalScore.STRONG_BUY]
    
    def test_generate_fundamental_signal_weak(self, fund_signals, weak_company):
        """Test señal fundamental para empresa débil"""
        result = fund_signals.generate_fundamental_signal(weak_company)
        
        assert result['symbol'] == 'WEAK'
        assert result['composite_score'] < 0.5
        assert result['signal'] in [FundamentalScore.SELL, FundamentalScore.STRONG_SELL]
    
    def test_screen_universe(self, fund_signals, strong_company, weak_company):
        """Test screening de universo"""
        metrics_list = [strong_company, weak_company]
        qualified = fund_signals.screen_universe(metrics_list, min_score=0.60)
        
        assert 'AAPL' in qualified
        assert 'WEAK' not in qualified
    
    def test_detect_deterioration(self, fund_signals, strong_company):
        """Test detección de deterioro"""
        # Crear versión deteriorada
        deteriorated = FundamentalMetrics(
            symbol='AAPL',
            roe=0.20,  # Bajo de 0.25
            debt_equity=0.50,  # Subió de 0.20
            operating_margin=0.20,  # Bajo de 0.25
            revenue_growth=0.08  # Bajo
        )
        
        is_deteriorated = fund_signals.detect_deterioration(deteriorated, strong_company)
        
        assert is_deteriorated == True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
