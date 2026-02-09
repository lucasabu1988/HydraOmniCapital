"""
Tests para el módulo de gestión de riesgo
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.risk.position_risk import PositionRiskManager, Position
from src.risk.portfolio_risk import PortfolioRiskManager, PortfolioMetrics


class TestPositionRiskManager:
    """Tests para PositionRiskManager"""
    
    @pytest.fixture
    def risk_manager(self):
        config = {
            'stop_loss': {
                'method': 'fixed',
                'fixed_percentage': 0.05,
                'atr_multiplier': 2.0,
                'trailing': True
            },
            'take_profit': {
                'method': 'risk_reward',
                'fixed_percentage': 0.15,
                'risk_reward_ratio': 3.0,
                'partial_exit': {
                    'enabled': True,
                    'levels': [
                        {'percent': 0.50, 'close': 0.30},
                        {'percent': 0.75, 'close': 0.30},
                        {'percent': 1.00, 'close': 0.40}
                    ]
                }
            },
            'position_sizing': {
                'method': 'kelly_criterion',
                'kelly_fraction': 0.25
            },
            'max_position_size': 0.10,
            'min_position_size': 0.02
        }
        return PositionRiskManager(config)
    
    @pytest.fixture
    def sample_prices(self):
        """Genera precios de ejemplo"""
        np.random.seed(42)
        returns = np.random.normal(0.001, 0.02, 100)
        prices = 100 * np.exp(np.cumsum(returns))
        return pd.Series(prices, index=pd.date_range('2023-01-01', periods=100))
    
    def test_calculate_stop_loss_fixed(self, risk_manager):
        """Test stop loss con método fijo"""
        stop_loss = risk_manager.calculate_stop_loss(
            entry_price=100.0,
            prices=pd.Series([100, 101, 99, 102]),
            method='fixed'
        )
        assert stop_loss == 95.0  # 100 * (1 - 0.05)
    
    def test_calculate_stop_loss_atr(self, risk_manager, sample_prices):
        """Test stop loss con ATR"""
        stop_loss = risk_manager.calculate_stop_loss(
            entry_price=100.0,
            prices=sample_prices,
            method='atr'
        )
        assert stop_loss < 100.0  # Stop debe ser menor que entrada
        assert stop_loss > 80.0   # Pero no demasiado bajo
    
    def test_calculate_take_profit_risk_reward(self, risk_manager):
        """Test take profit con ratio riesgo/beneficio"""
        entry_price = 100.0
        stop_loss = 95.0
        
        take_profit = risk_manager.calculate_take_profit(
            entry_price=entry_price,
            stop_loss_price=stop_loss,
            method='risk_reward'
        )
        
        expected = entry_price + (entry_price - stop_loss) * 3.0  # ratio 1:3
        assert take_profit == expected
    
    def test_calculate_position_size_kelly(self, risk_manager):
        """Test sizing de posición con Kelly"""
        sizing = risk_manager.calculate_position_size(
            capital=100000,
            entry_price=100.0,
            stop_loss_price=95.0,
            win_rate=0.55,
            avg_win_loss_ratio=2.0
        )
        
        assert sizing['position_pct'] > 0
        assert sizing['position_pct'] <= 0.10  # Max position size
        assert sizing['shares'] > 0
        assert sizing['risk_amount'] > 0
    
    def test_check_exit_signals_stop_loss(self, risk_manager):
        """Test señal de salida por stop loss"""
        position = Position(
            symbol='AAPL',
            sector='Technology',
            entry_price=100.0,
            current_price=90.0,
            shares=100,
            entry_date=datetime.now(),
            stop_loss_price=95.0,
            take_profit_price=115.0
        )
        
        signals = risk_manager.check_exit_signals(position, 94.0)
        
        assert signals['should_exit'] == True
        assert signals['reason'] == 'STOP_LOSS'
    
    def test_update_trailing_stop(self, risk_manager):
        """Test actualización de trailing stop"""
        position = Position(
            symbol='AAPL',
            sector='Technology',
            entry_price=100.0,
            current_price=110.0,
            shares=100,
            entry_date=datetime.now(),
            stop_loss_price=95.0,
            highest_price=110.0
        )
        
        new_stop = risk_manager.update_trailing_stop(position, 110.0, 110.0)
        
        assert new_stop > 95.0  # Stop debe haber subido


class TestPortfolioRiskManager:
    """Tests para PortfolioRiskManager"""
    
    @pytest.fixture
    def portfolio_manager(self):
        config = {
            'max_portfolio_positions': 20,
            'max_sector_exposure': 0.30,
            'objectives': {
                'max_drawdown': 0.15,
                'volatility_target': 0.20
            }
        }
        return PortfolioRiskManager(config)
    
    @pytest.fixture
    def sample_positions(self):
        """Posiciones de ejemplo"""
        return {
            'AAPL': {
                'market_value': 15000,
                'weight': 0.15,
                'sector': 'Technology',
                'beta': 1.2
            },
            'MSFT': {
                'market_value': 12000,
                'weight': 0.12,
                'sector': 'Technology',
                'beta': 1.0
            },
            'JPM': {
                'market_value': 10000,
                'weight': 0.10,
                'sector': 'Financials',
                'beta': 1.1
            }
        }
    
    def test_calculate_sector_exposure(self, portfolio_manager, sample_positions):
        """Test cálculo de exposición por sector"""
        total_value = 100000
        
        exposure = portfolio_manager._calculate_sector_exposure(
            sample_positions, total_value
        )
        
        assert 'Technology' in exposure
        assert 'Financials' in exposure
        assert exposure['Technology'] == 0.27  # 0.15 + 0.12
        assert exposure['Financials'] == 0.10
    
    def test_check_risk_limits_drawdown(self, portfolio_manager):
        """Test verificación de límite de drawdown"""
        metrics = PortfolioMetrics(
            total_value=100000,
            cash=20000,
            positions_value=80000,
            num_positions=5,
            sector_exposure={'Technology': 0.40},  # Excede límite
            portfolio_beta=1.1,
            volatility=0.15,
            var_95=-0.02,
            expected_shortfall=-0.03,
            max_drawdown=0.20,  # Excede límite de 15%
            current_drawdown=0.18,
            sharpe_ratio=1.2
        )
        
        result = portfolio_manager.check_risk_limits(metrics)
        
        assert result['is_compliant'] == False
        assert len(result['violations']) > 0
        assert 'REDUCE_EXPOSURE' in result['recommended_actions']
    
    def test_calculate_risk_score(self, portfolio_manager):
        """Test cálculo de score de riesgo"""
        metrics = PortfolioMetrics(
            total_value=100000,
            cash=20000,
            positions_value=80000,
            num_positions=5,
            sector_exposure={'Technology': 0.20},
            portfolio_beta=1.0,
            volatility=0.18,
            var_95=-0.02,
            expected_shortfall=-0.03,
            max_drawdown=0.10,
            current_drawdown=0.05,
            sharpe_ratio=1.5
        )
        
        score = portfolio_manager._calculate_risk_score(metrics)
        
        assert 0 <= score <= 100
        assert score < 70  # Score razonable para portafolio balanceado
    
    def test_should_rebalance(self, portfolio_manager):
        """Test decisión de rebalanceo"""
        target = {'AAPL': 0.10, 'MSFT': 0.10, 'GOOGL': 0.10}
        current = {'AAPL': 0.15, 'MSFT': 0.08, 'GOOGL': 0.07}
        
        should_rebalance = portfolio_manager.should_rebalance(
            target, current, threshold=0.05
        )
        
        assert should_rebalance == True  # AAPL drift = 0.05
    
    def test_should_not_rebalance(self, portfolio_manager):
        """Test cuando no se debe rebalancear"""
        target = {'AAPL': 0.10, 'MSFT': 0.10}
        current = {'AAPL': 0.11, 'MSFT': 0.09}
        
        should_rebalance = portfolio_manager.should_rebalance(
            target, current, threshold=0.05
        )
        
        assert should_rebalance == False  # Drift dentro del umbral


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
