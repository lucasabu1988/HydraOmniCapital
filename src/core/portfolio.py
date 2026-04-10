"""
Gestión de Portafolio y Rebalanceo
Maneja las posiciones, allocación y rebalanceo del portafolio
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict


@dataclass
class Trade:
    """Representa una operación de trading"""
    symbol: str
    side: str  # 'BUY' o 'SELL'
    shares: int
    price: float
    timestamp: datetime
    reason: str
    commission: float = 0.0
    # BUG-01 FIX: guardar entry_price y pnl al cerrar para calcular win_rate correctamente
    entry_price: Optional[float] = None   # solo relevante para trades SELL
    pnl: Optional[float] = None           # ganancia/pérdida realizada neta
    is_full_close: bool = False           # BUG-07 FIX: distinguir cierre total vs parcial

    @property
    def value(self) -> float:
        return self.shares * self.price

    @property
    def net_value(self) -> float:
        return self.value + (self.commission if self.side == 'BUY' else -self.commission)


@dataclass
class Position:
    """Posición detallada con información de riesgo"""
    symbol: str
    sector: str
    entry_price: float
    current_price: float
    shares: int
    entry_date: datetime
    weight: float = 0.0
    beta: float = 1.0

    # Niveles de riesgo
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    highest_price: float = 0.0
    initial_shares: int = 0
    sold_tiers: List[float] = field(default_factory=list)

    @property
    def market_value(self) -> float:
        return self.current_price * self.shares

    @property
    def cost_basis(self) -> float:
        return self.entry_price * self.shares

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis

    @property
    def unrealized_pnl_pct(self) -> float:
        return (self.current_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0

    @property
    def is_profitable(self) -> bool:
        return self.unrealized_pnl > 0


class Portfolio:
    """
    Gestiona el estado del portafolio de inversión
    """

    def __init__(self, initial_capital: float, cash_buffer: float = 0.05):
        self.initial_capital = initial_capital
        self.cash_buffer = cash_buffer
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.history: List[Dict] = []
        self.last_update = datetime.now()

    @property
    def total_value(self) -> float:
        """Valor total del portafolio (cash + posiciones)"""
        return self.cash + sum(p.market_value for p in self.positions.values())

    @property
    def invested_value(self) -> float:
        """Valor invertido en posiciones"""
        return sum(p.market_value for p in self.positions.values())

    @property
    def available_cash(self) -> float:
        """Efectivo disponible para nuevas posiciones (respetando buffer)"""
        return max(0, self.cash - (self.total_value * self.cash_buffer))

    @property
    def num_positions(self) -> int:
        return len(self.positions)

    def get_position_weights(self) -> Dict[str, float]:
        """Calcula los pesos actuales de las posiciones"""
        total = self.total_value
        if total == 0:
            return {}
        return {symbol: pos.market_value / total for symbol, pos in self.positions.items()}

    def get_sector_exposure(self) -> Dict[str, float]:
        """Calcula la exposición por sector"""
        sector_values = defaultdict(float)
        total = self.total_value

        if total == 0:
            return {}

        for pos in self.positions.values():
            sector_values[pos.sector] += pos.market_value / total

        return dict(sector_values)

    def add_position(
        self,
        symbol: str,
        sector: str,
        shares: int,
        price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        beta: float = 1.0,
        current_date: Optional[datetime] = None
    ) -> None:
        """Añade o incrementa una posición en el portafolio.
        
        BUG-05 FIX: si ya existe posición para el símbolo, hace average-down
        en lugar de sobreescribir (conserva entry_price ponderado, highest_price y sold_tiers).
        """
        exec_date = current_date or datetime.now()
        cost = shares * price
        commission = cost * 0.001  # 0.1% comisión
        total_cost = cost + commission

        if total_cost > self.cash:
            raise ValueError(f"Fondos insuficientes. Requerido: {total_cost}, Disponible: {self.cash}")

        if symbol in self.positions:
            # Average-down: actualizar entry_price ponderado por shares
            existing = self.positions[symbol]
            total_shares = existing.shares + shares
            weighted_entry = (existing.entry_price * existing.shares + price * shares) / total_shares
            existing.entry_price = weighted_entry
            existing.shares = total_shares
            existing.initial_shares += shares
            existing.highest_price = max(existing.highest_price, price)
            # Actualizar stop/take si se proveen explícitamente
            if stop_loss is not None:
                existing.stop_loss_price = stop_loss
            if take_profit is not None:
                existing.take_profit_price = take_profit
        else:
            position = Position(
                symbol=symbol,
                sector=sector,
                entry_price=price,
                current_price=price,
                shares=shares,
                entry_date=exec_date,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
                highest_price=price,
                beta=beta,
                initial_shares=shares
            )
            self.positions[symbol] = position

        self.cash -= total_cost

        trade = Trade(
            symbol=symbol,
            side='BUY',
            shares=shares,
            price=price,
            timestamp=exec_date,
            reason='NEW_POSITION' if symbol not in self.positions else 'ADD_TO_POSITION',
            commission=commission
        )
        self.trades.append(trade)
        self._update_weights()

    def close_position(self, symbol: str, price: float, reason: str, current_date: Optional[datetime] = None) -> float:
        """Cierra una posición existente"""
        if symbol not in self.positions:
            return 0.0

        exec_date = current_date or datetime.now()
        position = self.positions[symbol]
        proceeds = position.shares * price
        commission = proceeds * 0.001
        net_proceeds = proceeds - commission

        # BUG-01 FIX: calcular pnl y guardar entry_price en el Trade antes de eliminar la posición
        realized_pnl = (price - position.entry_price) * position.shares - commission

        self.cash += net_proceeds

        trade = Trade(
            symbol=symbol,
            side='SELL',
            shares=position.shares,
            price=price,
            timestamp=exec_date,
            reason=reason,
            commission=commission,
            entry_price=position.entry_price,
            pnl=realized_pnl,
            is_full_close=True  # BUG-07 FIX
        )
        self.trades.append(trade)

        del self.positions[symbol]
        self._update_weights()

        return net_proceeds

    def partial_close(self, symbol: str, shares: int, price: float, reason: str, current_date: Optional[datetime] = None) -> float:
        """Cierra parcialmente una posición"""
        if symbol not in self.positions:
            return 0.0

        exec_date = current_date or datetime.now()
        position = self.positions[symbol]
        shares = min(shares, position.shares)

        proceeds = shares * price
        commission = proceeds * 0.001
        net_proceeds = proceeds - commission

        # BUG-01 FIX: guardar entry_price y pnl parcial
        realized_pnl = (price - position.entry_price) * shares - commission

        position.shares -= shares
        self.cash += net_proceeds

        trade = Trade(
            symbol=symbol,
            side='SELL',
            shares=shares,
            price=price,
            timestamp=exec_date,
            reason=reason,
            commission=commission,
            entry_price=position.entry_price,
            pnl=realized_pnl,
            is_full_close=False  # BUG-07 FIX: es cierre parcial
        )
        self.trades.append(trade)

        if position.shares == 0:
            del self.positions[symbol]

        self._update_weights()
        return net_proceeds

    def update_prices(self, prices: Dict[str, float]) -> None:
        """Actualiza los precios de las posiciones"""
        for symbol, price in prices.items():
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos.current_price = price
                pos.highest_price = max(pos.highest_price, price)

        self._update_weights()
        self.last_update = datetime.now()

    def _update_weights(self) -> None:
        """Actualiza los pesos de todas las posiciones"""
        total = self.total_value
        if total > 0:
            for pos in self.positions.values():
                pos.weight = pos.market_value / total

    def get_performance_metrics(self) -> Dict[str, float]:
        """Calcula métricas de rendimiento.
        
        BUG-01 FIX: usa entry_price y pnl guardados en Trade para calcular win_rate correctamente.
        BUG-07 FIX: separa cierres totales de parciales para métricas de win_rate.
        """
        total_value = self.total_value
        total_return = (total_value - self.initial_capital) / self.initial_capital

        # BUG-07 FIX: solo trades de cierre TOTAL para win_rate (no parciales que distorsionan)
        full_close_trades = [t for t in self.trades if t.side == 'SELL' and t.is_full_close]
        all_sell_trades = [t for t in self.trades if t.side == 'SELL']

        # BUG-01 FIX: usar pnl guardado en el Trade, no comparar precio contra posición ya eliminada
        winning_trades = [t for t in full_close_trades if t.pnl is not None and t.pnl > 0]

        win_rate = len(winning_trades) / len(full_close_trades) if full_close_trades else 0.0

        return {
            'total_value': total_value,
            'total_return': total_return,
            'cash': self.cash,
            'invested': self.invested_value,
            'num_positions': self.num_positions,
            'win_rate': win_rate,
            'total_trades': len(all_sell_trades),
            'full_close_trades': len(full_close_trades),
            'total_realized_pnl': sum(t.pnl for t in all_sell_trades if t.pnl is not None)
        }

    def snapshot(self) -> Dict:
        """Crea un snapshot del estado actual"""
        snapshot = {
            'timestamp': datetime.now(),
            'total_value': self.total_value,
            'cash': self.cash,
            'positions': {
                symbol: {
                    'sector': pos.sector,
                    'shares': pos.shares,
                    'entry_price': pos.entry_price,
                    'current_price': pos.current_price,
                    'market_value': pos.market_value,
                    'unrealized_pnl': pos.unrealized_pnl,
                    'unrealized_pnl_pct': pos.unrealized_pnl_pct,
                    'weight': pos.weight,
                    'stop_loss': pos.stop_loss_price,
                    'take_profit': pos.take_profit_price
                }
                for symbol, pos in self.positions.items()
            },
            'sector_exposure': self.get_sector_exposure(),
            'metrics': self.get_performance_metrics()
        }
        self.history.append(snapshot)
        return snapshot


class RebalancingEngine:
    """
    Motor de rebalanceo de portafolio
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.frequency = config.get('frequency', 'monthly')
        self.threshold = config.get('threshold', 0.05)
        self.max_turnover = config.get('max_turnover', 0.50)
        self.tax_efficient = config.get('tax_efficient', True)

        self.last_rebalance = None
        self.rebalance_count = 0

    def should_rebalance(
        self,
        portfolio: 'Portfolio',
        target_weights: Dict[str, float],
        current_date: Optional[datetime] = None
    ) -> bool:
        """
        Determina si es momento de rebalancear.
        
        BUG-10 FIX: actualiza last_rebalance aquí cuando retorna True,
        no solo en generate_rebalance_trades(), evitando rebalanceos infinitos
        si se llama should_rebalance() sin llamar generate_rebalance_trades().
        """
        current_date = current_date or datetime.now()

        if self.last_rebalance:
            if self.frequency == 'daily':
                min_interval = timedelta(days=1)
            elif self.frequency == 'weekly':
                min_interval = timedelta(weeks=1)
            elif self.frequency == 'monthly':
                min_interval = timedelta(days=30)
            elif self.frequency == 'quarterly':
                min_interval = timedelta(days=90)
            else:
                min_interval = timedelta(days=1)

            if current_date - self.last_rebalance < min_interval and self.frequency != 'threshold':
                return False

        current_weights = portfolio.get_position_weights()

        max_drift = 0
        all_symbols = set(target_weights.keys()) | set(current_weights.keys())

        for symbol in all_symbols:
            target = target_weights.get(symbol, 0)
            current = current_weights.get(symbol, 0)
            drift = abs(target - current)
            max_drift = max(max_drift, drift)

        needs_rebalance = max_drift > self.threshold

        # BUG-10 FIX: actualizar last_rebalance al decidir rebalancear
        if needs_rebalance:
            self.last_rebalance = current_date

        return needs_rebalance

    def generate_rebalance_trades(
        self,
        portfolio: 'Portfolio',
        target_weights: Dict[str, float],
        current_prices: Dict[str, float]
    ) -> List[Dict]:
        """
        Genera las órdenes necesarias para rebalancear.
        
        BUG-10 FIX: ya no actualiza last_rebalance aquí (movido a should_rebalance).
        """
        trades = []
        total_value = portfolio.total_value
        current_weights = portfolio.get_position_weights()

        all_symbols = set(target_weights.keys()) | set(current_weights.keys()) | set(portfolio.positions.keys())

        for symbol in all_symbols:
            target_weight = target_weights.get(symbol, 0)
            current_weight = current_weights.get(symbol, 0)

            target_value = total_value * target_weight
            current_value = total_value * current_weight

            price = current_prices.get(symbol)
            if not price or price <= 0:
                continue

            if target_weight > current_weight:
                value_to_buy = target_value - current_value
                shares_to_buy = int(value_to_buy / price)

                if shares_to_buy > 0:
                    trades.append({
                        'symbol': symbol,
                        'action': 'BUY',
                        'shares': shares_to_buy,
                        'price': price,
                        'value': shares_to_buy * price,
                        'reason': 'REBALANCE'
                    })

            elif target_weight < current_weight:
                if symbol in portfolio.positions:
                    position = portfolio.positions[symbol]
                    value_to_sell = current_value - target_value
                    shares_to_sell = min(int(value_to_sell / price), position.shares)

                    if shares_to_sell > 0:
                        if self.tax_efficient and position.unrealized_pnl < 0:
                            reason = 'REBALANCE_TAX_EFFICIENT'
                        else:
                            reason = 'REBALANCE'

                        trades.append({
                            'symbol': symbol,
                            'action': 'SELL',
                            'shares': shares_to_sell,
                            'price': price,
                            'value': shares_to_sell * price,
                            'reason': reason
                        })

        total_trades_value = sum(t['value'] for t in trades)
        turnover = total_trades_value / total_value if total_value > 0 else 0

        if turnover > self.max_turnover:
            scale_factor = self.max_turnover / turnover
            for trade in trades:
                trade['shares'] = int(trade['shares'] * scale_factor)
                trade['value'] = trade['shares'] * trade['price']

        self.rebalance_count += 1

        return [t for t in trades if t['shares'] > 0]

    def calculate_optimal_weights(
        self,
        symbols: List[str],
        returns_data: pd.DataFrame,
        method: str = 'risk_parity'
    ) -> Dict[str, float]:
        """
        Calcula pesos óptimos para el portafolio.
        
        Métodos disponibles: 'equal', 'risk_parity', 'min_variance'.
        min_variance usa volatilidad anualizada (distinto de risk_parity que usa diaria).
        """
        valid_symbols = [s for s in symbols if s in returns_data.columns]

        if len(valid_symbols) == 0:
            return {}

        if method == 'equal':
            weight = 1.0 / len(valid_symbols)
            return {s: weight for s in valid_symbols}

        elif method == 'risk_parity':
            # Pesos inversamente proporcionales a la volatilidad diaria
            volatilities = returns_data[valid_symbols].std() * np.sqrt(252)
            inverse_vol = 1 / volatilities.replace(0, np.nan).dropna()
            weights = inverse_vol / inverse_vol.sum()
            return {s: weights[s] for s in valid_symbols if s in weights}

        elif method == 'min_variance':
            # Pesos inversamente proporcionales a la varianza (vol^2) — distinto de risk_parity
            variances = (returns_data[valid_symbols].std() * np.sqrt(252)) ** 2
            inverse_var = 1 / variances.replace(0, np.nan).dropna()
            weights = inverse_var / inverse_var.sum()
            return {s: weights[s] for s in valid_symbols if s in weights}

        else:
            return {s: 1.0 / len(valid_symbols) for s in valid_symbols}
