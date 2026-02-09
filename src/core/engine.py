"""
Motor Principal del Algoritmo Financiero
Coordina todos los componentes para ejecutar la estrategia
"""

import yaml
import logging
import pandas as pd
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
from pathlib import Path

from ..data.data_provider import YFinanceProvider
from ..data.fundamental_provider import FundamentalProvider
from ..signals.composite import CompositeSignalGenerator
from ..signals.fundamental import FundamentalMetrics
from ..risk.position_risk import PositionRiskManager, Position
from ..risk.portfolio_risk import PortfolioRiskManager, PortfolioMetrics
from ..core.portfolio import Portfolio, RebalancingEngine
from ..execution.executor import TradeExecutor, OrderSide


class TradingEngine:
    """
    Motor principal que coordina la ejecución de la estrategia
    """
    
    def __init__(self, config_path: str = "config/strategy.yaml"):
        # Cargar configuración
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        # Configurar logging
        self._setup_logging()
        
        # Inicializar componentes
        strategy_config = self.config.get('strategy', {})
        capital_config = self.config.get('capital', {})
        risk_config = self.config.get('risk_management', {})
        signals_config = self.config.get('signals', {})
        
        # Proveedores de datos
        self.data_provider = YFinanceProvider()
        self.fundamental_provider = FundamentalProvider()
        
        # Generador de señales
        self.signal_generator = CompositeSignalGenerator(
            technical_config=signals_config,
            fundamental_config=signals_config,
            weights={'technical': 0.35, 'fundamental': 0.35, 'risk': 0.20, 'momentum': 0.10}
        )
        
        # Gestores de riesgo
        self.position_risk = PositionRiskManager({**risk_config, **capital_config})
        self.portfolio_risk = PortfolioRiskManager(self.config)
        
        # Portafolio y rebalanceo
        initial_capital = capital_config.get('initial_capital', 1000000)
        cash_buffer = capital_config.get('cash_buffer', 0.05)
        self.portfolio = Portfolio(initial_capital, cash_buffer)
        self.rebalancing_engine = RebalancingEngine(self.config.get('rebalancing', {}))
        
        # Ejecutor
        self.executor = TradeExecutor()
        
        # Estado
        self.universe: List[str] = []
        self.fundamental_data: Dict[str, FundamentalMetrics] = {}
        self.price_history: pd.DataFrame = pd.DataFrame()
        self.current_prices: Dict[str, float] = {}
        self.market_regime: str = 'neutral'
        
        self.logger.info("Trading Engine inicializado")
    
    def _setup_logging(self):
        """Configura el sistema de logging"""
        log_level = self.config.get('monitoring', {}).get('log_level', 'INFO')
        
        logging.basicConfig(
            level=getattr(logging, log_level),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/trading_engine.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger('TradingEngine')
    
    def initialize_universe(self, symbols: Optional[List[str]] = None):
        """
        Inicializa el universo de inversión
        
        Args:
            symbols: Lista de símbolos (si es None, usa S&P 500)
        """
        self.logger.info("Inicializando universo de inversión...")
        
        if symbols is None:
            symbols = self.data_provider.get_sp500_symbols()
        
        # Filtrar por criterios de capitalización y volumen
        universe_config = self.config.get('universe', {})
        min_market_cap = universe_config.get('min_market_cap', 1e9)
        min_volume = universe_config.get('min_avg_volume', 1e6)
        
        self.universe = self.data_provider.filter_universe(
            symbols, min_market_cap, min_volume
        )
        
        self.logger.info(f"Universo filtrado: {len(self.universe)} símbolos")
    
    def load_data(self, lookback_days: int = 365):
        """
        Carga datos históricos y fundamentales
        
        Args:
            lookback_days: Días de histórico a cargar
        """
        self.logger.info("Cargando datos...")
        
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)
        
        # Cargar precios históricos
        self.price_history = self.data_provider.get_historical_prices(
            self.universe,
            start_date=start_date,
            end_date=end_date
        )
        
        # Cargar precios actuales
        self.current_prices = self.data_provider.get_current_price(self.universe)
        
        # Cargar datos fundamentales
        self.fundamental_data = self.fundamental_provider.get_batch_fundamental_data(
            self.universe
        )
        
        # Determinar régimen de mercado
        self.market_regime = self.data_provider.get_market_regime()
        self.logger.info(f"Régimen de mercado: {self.market_regime}")
        
        self.logger.info("Datos cargados exitosamente")
    
    def scan_opportunities(self) -> List[Dict]:
        """
        Escanea el universo en busca de oportunidades
        
        Returns:
            Lista de señales de trading
        """
        self.logger.info("Escaneando oportunidades...")
        
        signals = []
        
        for symbol in self.universe:
            if symbol not in self.price_history.columns:
                continue
            
            prices = self.price_history[symbol].dropna()
            if len(prices) < 50:
                continue
            
            fundamental = self.fundamental_data.get(symbol)
            
            # Generar señal
            signal = self.signal_generator.generate_signal(
                symbol=symbol,
                prices=prices,
                metrics=fundamental,
                market_regime=self.market_regime
            )
            
            if signal.action == 'BUY' and signal.confidence >= 0.60:
                signals.append({
                    'signal': signal,
                    'current_price': self.current_prices.get(symbol, prices.iloc[-1]),
                    'fundamental': fundamental
                })
        
        # Ordenar por confianza
        signals.sort(key=lambda x: x['signal'].confidence, reverse=True)
        
        self.logger.info(f"Oportunidades encontradas: {len(signals)}")
        return signals
    
    def evaluate_new_position(
        self,
        symbol: str,
        current_price: float,
        fundamental: Optional[FundamentalMetrics]
    ) -> Optional[Dict]:
        """
        Evalúa si se debe abrir una nueva posición
        
        Args:
            symbol: Símbolo
            current_price: Precio actual
            fundamental: Datos fundamentales
            
        Returns:
            Diccionario con parámetros de la posición o None
        """
        # Verificar límites de portafolio
        if self.portfolio.num_positions >= self.config['capital']['max_portfolio_positions']:
            return None
        
        # Verificar exposición por sector
        sector = fundamental.sector if fundamental else 'Unknown'
        current_exposure = self.portfolio.get_sector_exposure()
        max_sector = self.config['capital']['max_sector_exposure']
        
        if current_exposure.get(sector, 0) >= max_sector:
            return None
        
        # Calcular niveles de riesgo
        prices = self.price_history[symbol].dropna()
        
        stop_loss = self.position_risk.calculate_stop_loss(
            entry_price=current_price,
            prices=prices
        )
        
        take_profit = self.position_risk.calculate_take_profit(
            entry_price=current_price,
            stop_loss_price=stop_loss
        )
        
        # Calcular tamaño de posición
        position_sizing = self.position_risk.calculate_position_size(
            capital=self.portfolio.total_value,
            entry_price=current_price,
            stop_loss_price=stop_loss
        )
        
        # Verificar que el tamaño no exceda límites
        max_position = self.config['capital']['max_position_size']
        if position_sizing['position_pct'] > max_position:
            position_sizing['position_pct'] = max_position
            position_sizing['shares'] = int(
                (self.portfolio.total_value * max_position) / current_price
            )
            position_sizing['position_value'] = position_sizing['shares'] * current_price
        
        # Verificar disponibilidad de efectivo
        if position_sizing['position_value'] > self.portfolio.available_cash:
            return None
        
        return {
            'symbol': symbol,
            'entry_price': current_price,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'shares': position_sizing['shares'],
            'position_value': position_sizing['position_value'],
            'risk_amount': position_sizing['risk_amount'],
            'sector': sector,
            'beta': fundamental.roe if fundamental else 1.0  # Simplificado
        }
    
    def open_position(self, opportunity: Dict):
        """
        Abre una nueva posición
        
        Args:
            opportunity: Diccionario con parámetros de la posición
        """
        try:
            self.portfolio.add_position(
                symbol=opportunity['symbol'],
                sector=opportunity['sector'],
                shares=opportunity['shares'],
                price=opportunity['entry_price'],
                stop_loss=opportunity['stop_loss'],
                take_profit=opportunity['take_profit'],
                beta=opportunity.get('beta', 1.0)
            )
            
            # Configurar reglas de salida
            self.executor.set_exit_rules(
                symbol=opportunity['symbol'],
                stop_loss=opportunity['stop_loss'],
                take_profit=opportunity['take_profit']
            )
            
            self.logger.info(
                f"Posición abierta: {opportunity['symbol']} - "
                f"{opportunity['shares']} acciones @ ${opportunity['entry_price']:.2f}"
            )
            
        except Exception as e:
            self.logger.error(f"Error abriendo posición {opportunity['symbol']}: {e}")
    
    def check_exits(self):
        """Verifica y ejecuta salidas de posiciones existentes"""
        positions_to_close = []
        
        for symbol, position in self.portfolio.positions.items():
            current_price = self.current_prices.get(symbol)
            if not current_price:
                continue
            
            # Verificar stop loss
            if position.stop_loss_price and current_price <= position.stop_loss_price:
                positions_to_close.append({
                    'symbol': symbol,
                    'price': current_price,
                    'reason': 'STOP_LOSS',
                    'percentage': 1.0
                })
                continue
            
            # Verificar take profit
            if position.take_profit_price:
                progress = (current_price - position.entry_price) / (position.take_profit_price - position.entry_price)
                
                # Niveles de take profit parcial
                if progress >= 1.0:
                    positions_to_close.append({
                        'symbol': symbol,
                        'price': current_price,
                        'reason': 'TAKE_PROFIT_100',
                        'percentage': 0.40
                    })
                elif progress >= 0.75 and position.shares == int(position.shares * 0.70):  # Ya vendió 30%
                    positions_to_close.append({
                        'symbol': symbol,
                        'price': current_price,
                        'reason': 'TAKE_PROFIT_75',
                        'percentage': 0.30
                    })
                elif progress >= 0.50 and position.shares == int(position.shares * 1.0):  # Sin ventas aún
                    positions_to_close.append({
                        'symbol': symbol,
                        'price': current_price,
                        'reason': 'TAKE_PROFIT_50',
                        'percentage': 0.30
                    })
            
            # Actualizar trailing stop
            if self.config['risk_management']['stop_loss'].get('trailing', False):
                new_stop = self.position_risk.update_trailing_stop(
                    position, current_price, position.highest_price
                )
                if new_stop:
                    position.stop_loss_price = new_stop
        
        # Ejecutar cierres
        for exit_order in positions_to_close:
            position = self.portfolio.positions[exit_order['symbol']]
            shares_to_close = int(position.shares * exit_order['percentage'])
            
            if exit_order['percentage'] >= 1.0:
                self.portfolio.close_position(
                    symbol=exit_order['symbol'],
                    price=exit_order['price'],
                    reason=exit_order['reason']
                )
            else:
                self.portfolio.partial_close(
                    symbol=exit_order['symbol'],
                    shares=shares_to_close,
                    price=exit_order['price'],
                    reason=exit_order['reason']
                )
            
            self.logger.info(
                f"Posición cerrada: {exit_order['symbol']} - "
                f"Razón: {exit_order['reason']}"
            )
    
    def rebalance_portfolio(self):
        """Ejecuta rebalanceo de portafolio si es necesario"""
        if not self.config.get('rebalancing', {}).get('enabled', True):
            return
        
        target_weights = self._calculate_target_weights()
        current_weights = self.portfolio.get_position_weights()
        
        if self.rebalancing_engine.should_rebalance(
            self.portfolio, target_weights
        ):
            self.logger.info("Iniciando rebalanceo de portafolio...")
            
            trades = self.rebalancing_engine.generate_rebalance_trades(
                self.portfolio, target_weights, self.current_prices
            )
            
            for trade in trades:
                if trade['action'] == 'SELL':
                    self.portfolio.close_position(
                        trade['symbol'],
                        trade['price'],
                        'REBALANCE'
                    )
                elif trade['action'] == 'BUY':
                    # Solo ejecutar si hay suficiente cash
                    cost = trade['shares'] * trade['price'] * 1.001
                    if cost <= self.portfolio.available_cash:
                        fundamental = self.fundamental_data.get(trade['symbol'])
                        self.portfolio.add_position(
                            symbol=trade['symbol'],
                            sector=fundamental.sector if fundamental else 'Unknown',
                            shares=trade['shares'],
                            price=trade['price']
                        )
            
            self.logger.info(f"Rebalanceo completado: {len(trades)} trades")
    
    def _calculate_target_weights(self) -> Dict[str, float]:
        """Calcula los pesos objetivo del portafolio"""
        # Usar equal weight como base, ajustado por riesgo
        symbols = list(self.portfolio.positions.keys())
        
        if not symbols:
            return {}
        
        weights = {}
        for symbol in symbols:
            prices = self.price_history[symbol].dropna()
            volatility = prices.pct_change().std() * (252 ** 0.5)
            
            # Menor peso para mayor volatilidad
            risk_adjusted_weight = 1.0 / (volatility + 0.01)
            weights[symbol] = risk_adjusted_weight
        
        # Normalizar
        total = sum(weights.values())
        return {k: v/total for k, v in weights.items()}
    
    def check_risk_limits(self):
        """Verifica límites de riesgo del portafolio"""
        metrics = self.portfolio_risk.calculate_portfolio_metrics(
            positions=self.portfolio.positions,
            cash=self.portfolio.cash,
            price_history=self.price_history
        )
        
        risk_check = self.portfolio_risk.check_risk_limits(metrics)
        
        if not risk_check['is_compliant']:
            self.logger.warning(f"Violaciones de riesgo: {risk_check['violations']}")
            
            for action in risk_check['recommended_actions']:
                if action == 'REDUCE_EXPOSURE':
                    self._reduce_exposure()
                elif action.startswith('REDUCE_SECTOR'):
                    sector = action.split('_')[-1]
                    self._reduce_sector_exposure(sector)
    
    def _reduce_exposure(self):
        """Reduce la exposición general del portafolio"""
        # Cerrar posiciones con menor score
        if self.portfolio.positions:
            # Por simplicidad, cerrar la posición más pequeña
            smallest = min(
                self.portfolio.positions.items(),
                key=lambda x: x[1].market_value
            )
            current_price = self.current_prices.get(smallest[0], smallest[1].current_price)
            self.portfolio.close_position(smallest[0], current_price, 'RISK_REDUCTION')
            self.logger.info(f"Exposición reducida: cerrada {smallest[0]}")
    
    def _reduce_sector_exposure(self, sector: str):
        """Reduce la exposición de un sector específico"""
        for symbol, position in list(self.portfolio.positions.items()):
            if position.sector == sector:
                current_price = self.current_prices.get(symbol, position.current_price)
                self.portfolio.close_position(symbol, current_price, f'SECTOR_LIMIT_{sector}')
                break
    
    def run_iteration(self):
        """Ejecuta una iteración completa del algoritmo"""
        self.logger.info("=" * 60)
        self.logger.info("Iniciando iteración de trading")
        self.logger.info("=" * 60)
        
        # 1. Cargar datos actualizados
        self.load_data(lookback_days=90)
        
        # 2. Actualizar precios del portafolio
        self.portfolio.update_prices(self.current_prices)
        
        # 3. Verificar salidas de posiciones existentes
        self.check_exits()
        
        # 4. Verificar límites de riesgo
        self.check_risk_limits()
        
        # 5. Rebalancear si es necesario
        self.rebalance_portfolio()
        
        # 6. Buscar nuevas oportunidades
        opportunities = self.scan_opportunities()
        
        # 7. Evaluar y abrir nuevas posiciones
        for opp in opportunities[:5]:  # Top 5 oportunidades
            if self.portfolio.num_positions >= self.config['capital']['max_portfolio_positions']:
                break
            
            signal = opp['signal']
            position_params = self.evaluate_new_position(
                signal.symbol,
                opp['current_price'],
                opp['fundamental']
            )
            
            if position_params:
                self.open_position(position_params)
        
        # 8. Snapshot del estado
        snapshot = self.portfolio.snapshot()
        
        self.logger.info(f"Iteración completada. Valor del portafolio: ${snapshot['total_value']:,.2f}")
        
        return snapshot
    
    def run_backtest(
        self,
        start_date: datetime,
        end_date: datetime,
        rebalance_frequency: str = 'M'
    ) -> pd.DataFrame:
        """
        Ejecuta backtest de la estrategia
        
        Args:
            start_date: Fecha de inicio
            end_date: Fecha de fin
            rebalance_frequency: Frecuencia de rebalanceo ('D', 'W', 'M')
            
        Returns:
            DataFrame con resultados
        """
        self.logger.info(f"Iniciando backtest: {start_date} a {end_date}")
        
        dates = pd.date_range(start=start_date, end=end_date, freq=rebalance_frequency)
        results = []
        
        for date in dates:
            # Simular iteración en fecha histórica
            snapshot = self.run_iteration()
            snapshot['date'] = date
            results.append(snapshot)
        
        df_results = pd.DataFrame(results)
        
        # Calcular métricas de rendimiento
        df_results['returns'] = df_results['total_value'].pct_change()
        df_results['cumulative_returns'] = (1 + df_results['returns']).cumprod() - 1
        
        self.logger.info("Backtest completado")
        
        return df_results
    
    def get_portfolio_snapshot(self) -> Dict[str, Any]:
        """Obtiene un snapshot del estado actual del portafolio"""
        return self.portfolio.snapshot()

    def generate_report(self) -> Dict[str, Any]:
        """Genera reporte del estado actual"""
        metrics = self.portfolio.get_performance_metrics()
        
        return {
            'timestamp': datetime.now(),
            'portfolio_value': self.portfolio.total_value,
            'initial_capital': self.portfolio.initial_capital,
            'total_return': metrics['total_return'],
            'cash': metrics['cash'],
            'invested': metrics['invested'],
            'num_positions': metrics['num_positions'],
            'positions': {
                symbol: {
                    'sector': pos.sector,
                    'shares': pos.shares,
                    'entry_price': pos.entry_price,
                    'current_price': pos.current_price,
                    'unrealized_pnl_pct': pos.unrealized_pnl_pct,
                    'weight': pos.weight
                }
                for symbol, pos in self.portfolio.positions.items()
            },
            'sector_exposure': self.portfolio.get_sector_exposure(),
            'win_rate': metrics['win_rate'],
            'total_trades': metrics['total_trades']
        }
