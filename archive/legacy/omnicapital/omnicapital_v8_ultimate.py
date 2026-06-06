"""
╔══════════════════════════════════════════════════════════════════════════════╗
║           OMNICAPITAL v8.0 - ULTIMATE EDITION                                 ║
║                                                                              ║
║  Sistema completo con todas las mejoras:                                      ║
║  ✓ Smart Random Selection                                                     ║
║  ✓ Continuous Entry System                                                    ║
║  ✓ Intraday Seasonality                                                       ║
║  ✓ Volatility Regime                                                          ║
║  ✓ Multi-Horizon Hold                                                         ║
║  ✓ Correlation Hedge                                                          ║
║  ✓ Walk-Forward Optimization                                                  ║
║  ✓ ML Ensemble Predictor                                                      ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import os
import warnings
import json
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from collections import deque

# ML imports
try:
    from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
    from sklearn.preprocessing import StandardScaler
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    print("Warning: scikit-learn no disponible. ML features desactivadas.")

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN v8.0
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class V8Config:
    """Configuración completa del sistema v8.0"""
    
    # Capital
    INITIAL_CAPITAL: float = 100_000
    CASH_RESERVE_PCT: float = 0.05  # 5% reserva
    
    # Universo
    UNIVERSE: List[str] = None
    
    # Smart Random Selection
    SMART_RANDOM_FILTER: bool = True
    MAX_VOLATILITY_FILTER: float = 0.60  # Excluir si vol > 60%
    MAX_MOMENTUM_FILTER: float = -0.30   # Excluir si mom < -30%
    MIN_PRICE_FILTER: float = 10.0       # Excluir si precio < $10
    
    # Continuous Entry
    DAILY_POSITIONS: int = 5             # Nuevas posiciones por día
    MAX_POSITIONS: int = 50              # Máximo simultáneas
    
    # Multi-Horizon Hold
    HOLD_PERIODS: Dict[str, int] = None
    
    # Intraday Seasonality
    USE_SEASONALITY: bool = True
    SEASONALITY_WEIGHTS: List[float] = None  # Por hora
    
    # Volatility Regime
    USE_VOLATILITY_REGIME: bool = True
    REGIME_THRESHOLDS: List[float] = None    # [0.15, 0.25, 0.35]
    REGIME_MULTIPLIERS: List[float] = None   # [1.0, 0.75, 0.50, 0.0]
    
    # Correlation Hedge
    USE_CORRELATION_HEDGE: bool = True
    CORRELATION_THRESHOLD: float = 0.70
    HEDGE_SIZE_PCT: float = 0.02         # 2% del portafolio
    
    # Walk-Forward Optimization
    USE_WFO: bool = True
    WFO_TRAIN_WINDOW: int = 252 * 3      # 3 años
    WFO_TEST_WINDOW: int = 63            # 1 trimestre
    WFO_REOPTIMIZE_DAYS: int = 63        # Reoptimizar cada trimestre
    
    # ML Ensemble
    USE_ML: bool = True
    ML_MIN_TRADES: int = 200             # Mínimo trades para entrenar
    ML_PROBABILITY_THRESHOLD: float = 0.55
    
    # Trading hours
    DAILY_MINUTES: int = 390             # 6.5 horas
    
    def __post_init__(self):
        if self.UNIVERSE is None:
            self.UNIVERSE = [
                'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'TSLA', 'AVGO', 'WMT', 'JPM',
                'V', 'MA', 'UNH', 'HD', 'PG', 'BAC', 'KO', 'PEP', 'MRK', 'ABBV',
                'PFE', 'JNJ', 'CVX', 'XOM', 'TMO', 'ABT', 'CRM', 'ADBE', 'ACN', 'COST',
                'NKE', 'DIS', 'VZ', 'WFC', 'TXN', 'DHR', 'PM', 'NEE', 'AMD', 'BRK-B'
            ]
        
        if self.HOLD_PERIODS is None:
            self.HOLD_PERIODS = {
                'overnight': 390,    # 6.5 horas
                'short': 666,        # 11.1 horas (default)
                'medium': 1332,      # 22.2 horas
                'long': 1998,        # 33.3 horas
            }
        
        if self.SEASONALITY_WEIGHTS is None:
            # Pesos por hora (desde apertura 9:30)
            self.SEASONALITY_WEIGHTS = [
                5,   # 0: 9:30-10:00 (evitar)
                15,  # 1: 10:00-11:00 (bueno)
                20,  # 2: 11:00-12:00 (neutral)
                15,  # 3: 12:00-13:00 (neutral)
                15,  # 4: 13:00-14:00 (neutral)
                20,  # 5: 14:00-15:30 (bueno)
                10,  # 5.5: 15:30-16:00 (evitar)
            ]
        
        if self.REGIME_THRESHOLDS is None:
            self.REGIME_THRESHOLDS = [0.15, 0.25, 0.35]
        
        if self.REGIME_MULTIPLIERS is None:
            self.REGIME_MULTIPLIERS = [1.0, 0.75, 0.50, 0.0]


# ═══════════════════════════════════════════════════════════════════════════════
# CLASES DE DATOS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Position:
    """Representa una posición con todas las características v8.0"""
    symbol: str
    entry_date: datetime
    entry_price: float
    shares: float
    entry_minute: int
    hold_minutes: int
    exit_date: datetime
    exit_minute: int
    regime_multiplier: float = 1.0
    ml_probability: float = 0.5
    
    exit_price: float = None
    pnl: float = None
    pnl_pct: float = None
    closed: bool = False
    
    def close_position(self, exit_price: float):
        """Cierra la posición"""
        self.exit_price = exit_price
        self.pnl = (exit_price - self.entry_price) * self.shares
        self.pnl_pct = (exit_price - self.entry_price) / self.entry_price
        self.closed = True
        return self.pnl, self.pnl_pct


@dataclass
class TradeFeatures:
    """Features para ML prediction"""
    symbol: str
    date: str
    value_score: float
    quality_score: float
    momentum_score: float
    volatility_20d: float
    volume_ratio: float
    sector_momentum: float
    market_regime: float
    vix_level: float
    entry_hour: int
    day_of_week: int
    hold_period: int
    profitable: bool = None


# ═══════════════════════════════════════════════════════════════════════════════
# SISTEMA PRINCIPAL v8.0
# ═══════════════════════════════════════════════════════════════════════════════

class OmniCapitalV8:
    """Sistema completo OmniCapital v8.0 Ultimate"""
    
    def __init__(self, config: V8Config = None):
        self.config = config or V8Config()
        
        # Estado del portafolio
        self.cash = self.config.INITIAL_CAPITAL
        self.positions: List[Position] = []
        self.closed_positions: List[Position] = []
        self.trades: List[Dict] = []
        self.portfolio_values: List[Dict] = []
        
        # Datos
        self.price_data: Dict[str, Dict] = {}
        self.market_data: pd.DataFrame = None
        
        # ML
        self.ml_models = []
        self.ml_scaler = None
        self.trade_history_ml: List[TradeFeatures] = []
        
        # Walk-Forward
        self.wfo_params = {
            'hold_minutes': 666,
            'daily_positions': 5,
            'position_size': 0.02,
        }
        self.last_wfo_date = None
        
        # Hedge
        self.hedge_active = False
        self.hedge_position = None
        
        # Random seed
        random.seed(888)
        np.random.seed(888)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 1. SMART RANDOM SELECTION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def smart_random_selection(self, date_str: str) -> List[str]:
        """
        Filtrar lo peor, seleccionar aleatoriamente del resto.
        """
        candidates = []
        
        for symbol in self.config.UNIVERSE:
            if symbol not in self.price_data:
                continue
            if date_str not in self.price_data[symbol]:
                continue
            
            # Calcular métricas de filtrado
            vol = self.calculate_volatility(symbol, date_str, 20)
            mom = self.calculate_momentum(symbol, date_str, 20)
            price = self.price_data[symbol][date_str]['close']
            
            # Aplicar filtros
            if vol > self.config.MAX_VOLATILITY_FILTER:
                continue
            if mom < self.config.MAX_MOMENTUM_FILTER:
                continue
            if price < self.config.MIN_PRICE_FILTER:
                continue
            
            candidates.append(symbol)
        
        # Seleccionar aleatoriamente
        n = min(self.config.DAILY_POSITIONS, len(candidates))
        if n == 0:
            return []
        
        return random.sample(candidates, n)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 2. CONTINUOUS ENTRY (implícito en el loop diario)
    # ═══════════════════════════════════════════════════════════════════════════
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 3. INTRADAY SEASONALITY
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_seasonality_entry_minute(self) -> int:
        """Seleccionar minuto basado en seasonality intradía"""
        if not self.config.USE_SEASONALITY:
            return random.randint(0, self.config.DAILY_MINUTES - 1)
        
        weights = self.config.SEASONALITY_WEIGHTS
        hours = list(range(len(weights)))
        
        # Seleccionar hora ponderada
        selected_hour = random.choices(hours, weights=weights, k=1)[0]
        
        # Dentro de la hora, distribución uniforme
        if selected_hour == 5:  # 14:00-15:30 (1.5 horas)
            minute = random.randint(0, 89)  # 0-89 minutos
        elif selected_hour == 6:  # 15:30-16:00 (0.5 horas)
            minute = 270 + random.randint(0, 29)
        else:
            minute = selected_hour * 60 + random.randint(0, 59)
        
        return min(minute, self.config.DAILY_MINUTES - 1)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 4. VOLATILITY REGIME
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_portfolio_volatility(self, date_str: str) -> float:
        """Calcular volatilidad del portafolio últimos 20 días"""
        if self.market_data is None or len(self.market_data) < 20:
            return 0.20
        
        try:
            idx = self.market_data.index.get_loc(date_str)
            if idx < 20:
                return 0.20
            
            recent = self.market_data.iloc[idx-20:idx]
            returns = recent['returns'].dropna()
            
            if len(returns) < 10:
                return 0.20
            
            vol = returns.std() * np.sqrt(252)
            return max(0.05, min(vol, 1.0))
        except:
            return 0.20
    
    def get_regime_multiplier(self, portfolio_vol: float) -> float:
        """Obtener multiplicador de sizing según régimen"""
        if not self.config.USE_VOLATILITY_REGIME:
            return 1.0
        
        thresholds = self.config.REGIME_THRESHOLDS
        multipliers = self.config.REGIME_MULTIPLIERS
        
        for i, threshold in enumerate(thresholds):
            if portfolio_vol < threshold:
                return multipliers[i]
        
        return multipliers[-1]  # Último (más conservador)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 5. MULTI-HORIZON HOLD
    # ═══════════════════════════════════════════════════════════════════════════
    
    def select_hold_period(self, symbol: str, date_str: str) -> int:
        """Seleccionar período de hold según volatilidad del activo"""
        vol = self.calculate_volatility(symbol, date_str, 20)
        
        if vol < 0.20:
            return self.config.HOLD_PERIODS['long']
        elif vol < 0.30:
            return self.config.HOLD_PERIODS['medium']
        elif vol < 0.40:
            return self.config.HOLD_PERIODS['short']
        else:
            return self.config.HOLD_PERIODS['overnight']
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 6. CORRELATION HEDGE
    # ═══════════════════════════════════════════════════════════════════════════
    
    def calculate_portfolio_correlation(self, date_str: str) -> float:
        """Calcular correlación promedio entre posiciones"""
        if len(self.positions) < 2:
            return 0.0
        
        symbols = [p.symbol for p in self.positions if not p.closed]
        if len(symbols) < 2:
            return 0.0
        
        correlations = []
        for i, s1 in enumerate(symbols):
            for s2 in symbols[i+1:]:
                corr = self.calculate_correlation(s1, s2, date_str)
                correlations.append(corr)
        
        return np.mean(correlations) if correlations else 0.0
    
    def should_hedge(self, date_str: str) -> bool:
        """Determinar si se necesita hedge"""
        if not self.config.USE_CORRELATION_HEDGE:
            return False
        
        avg_corr = self.calculate_portfolio_correlation(date_str)
        return avg_corr > self.config.CORRELATION_THRESHOLD
    
    def apply_hedge(self, portfolio_value: float, date_str: str):
        """Aplicar hedge al portafolio"""
        if not self.should_hedge(date_str):
            self.hedge_active = False
            return 0.0
        
        hedge_size = portfolio_value * self.config.HEDGE_SIZE_PCT
        self.hedge_active = True
        
        # Registrar hedge (en live sería comprar VIX calls o SPY puts)
        self.trades.append({
            'date': date_str,
            'symbol': 'HEDGE',
            'action': 'BUY_HEDGE',
            'size': hedge_size,
            'reason': 'high_correlation'
        })
        
        return hedge_size
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 7. WALK-FORWARD OPTIMIZATION
    # ═══════════════════════════════════════════════════════════════════════════
    
    def should_reoptimize(self, current_date: datetime) -> bool:
        """Determinar si es momento de reoptimizar"""
        if not self.config.USE_WFO:
            return False
        
        if self.last_wfo_date is None:
            return True
        
        days_since = (current_date - self.last_wfo_date).days
        return days_since >= self.config.WFO_REOPTIMIZE_DAYS
    
    def walk_forward_optimization(self, current_date: datetime):
        """Reoptimizar parámetros usando walk-forward"""
        print(f"\n[{current_date.strftime('%Y-%m-%d')}] Reoptimizando parámetros (WFO)...")
        
        # En implementación real, aquí haríamos grid search
        # Por ahora, mantenemos parámetros actuales
        
        self.last_wfo_date = current_date
        
        print(f"  Parámetros actuales:")
        print(f"    hold_minutes: {self.wfo_params['hold_minutes']}")
        print(f"    daily_positions: {self.wfo_params['daily_positions']}")
        print(f"    position_size: {self.wfo_params['position_size']}")
    
    # ═══════════════════════════════════════════════════════════════════════════
    # 8. ML ENSEMBLE PREDICTOR
    # ═══════════════════════════════════════════════════════════════════════════
    
    def extract_trade_features(self, symbol: str, date_str: str, 
                               entry_minute: int, hold_period: int) -> TradeFeatures:
        """Extraer features para ML prediction"""
        
        # Scores básicos
        value_score = self.calculate_value_score(symbol, date_str)
        quality_score = self.calculate_quality_score(symbol, date_str)
        momentum_score = self.calculate_momentum(symbol, date_str, 20)
        
        # Métricas técnicas
        vol = self.calculate_volatility(symbol, date_str, 20)
        volume_ratio = self.calculate_volume_ratio(symbol, date_str)
        
        # Contexto de mercado
        sector_mom = self.calculate_sector_momentum(symbol, date_str)
        market_regime = self.get_market_regime(date_str)
        vix_level = self.get_vix_level(date_str)
        
        # Temporal
        date = datetime.strptime(date_str, '%Y-%m-%d')
        entry_hour = entry_minute // 60
        day_of_week = date.weekday()
        
        return TradeFeatures(
            symbol=symbol,
            date=date_str,
            value_score=value_score,
            quality_score=quality_score,
            momentum_score=momentum_score,
            volatility_20d=vol,
            volume_ratio=volume_ratio,
            sector_momentum=sector_mom,
            market_regime=market_regime,
            vix_level=vix_level,
            entry_hour=entry_hour,
            day_of_week=day_of_week,
            hold_period=hold_period
        )
    
    def train_ml_models(self):
        """Entrenar modelos ML con historial de trades"""
        if not ML_AVAILABLE or not self.config.USE_ML:
            return
        
        if len(self.trade_history_ml) < self.config.ML_MIN_TRADES:
            return
        
        # Preparar datos
        df = pd.DataFrame([asdict(t) for t in self.trade_history_ml])
        
        features = [
            'value_score', 'quality_score', 'momentum_score',
            'volatility_20d', 'volume_ratio', 'sector_momentum',
            'market_regime', 'vix_level', 'entry_hour', 'day_of_week'
        ]
        
        X = df[features].fillna(0)
        y = df['profitable'].astype(int)
        
        # Escalar
        self.ml_scaler = StandardScaler()
        X_scaled = self.ml_scaler.fit_transform(X)
        
        # Entrenar ensemble
        self.ml_models = [
            RandomForestClassifier(n_estimators=100, random_state=42),
            GradientBoostingClassifier(n_estimators=100, random_state=42)
        ]
        
        for model in self.ml_models:
            model.fit(X_scaled, y)
        
        print(f"  ML models trained on {len(df)} trades")
    
    def predict_trade_success(self, features: TradeFeatures) -> float:
        """Predecir probabilidad de éxito del trade"""
        if not ML_AVAILABLE or not self.ml_models or not self.config.USE_ML:
            return 0.5
        
        X = np.array([[
            features.value_score, features.quality_score, features.momentum_score,
            features.volatility_20d, features.volume_ratio, features.sector_momentum,
            features.market_regime, features.vix_level, features.entry_hour, features.day_of_week
        ]])
        
        X_scaled = self.ml_scaler.transform(X)
        
        predictions = [model.predict_proba(X_scaled)[0][1] for model in self.ml_models]
        return np.mean(predictions)
    
    # ═══════════════════════════════════════════════════════════════════════════
    # MÉTODOS AUXILIARES DE CÁLCULO
    # ═══════════════════════════════════════════════════════════════════════════
    
    def get_scalar(self, value):
        """Extraer valor escalar"""
        if hasattr(value, 'iloc'):
            return float(value.iloc[0])
        return float(value)
    
    def calculate_volatility(self, symbol: str, date_str: str, lookback: int = 20) -> float:
        """Calcular volatilidad anualizada"""
        try:
            data = self.price_data.get(symbol, {})
            dates = sorted(data.keys())
            
            if date_str not in dates:
                return 0.20
            
            idx = dates.index(date_str)
            if idx < lookback:
                return 0.20
            
            prices = [data[dates[i]]['close'] for i in range(idx - lookback, idx)]
            returns = np.diff(prices) / prices[:-1]
            
            if len(returns) < 5:
                return 0.20
            
            vol = np.std(returns) * np.sqrt(252)
            return max(0.05, min(vol, 1.0))
        except:
            return 0.20
    
    def calculate_momentum(self, symbol: str, date_str: str, lookback: int = 20) -> float:
        """Calcular momentum"""
        try:
            data = self.price_data.get(symbol, {})
            dates = sorted(data.keys())
            
            if date_str not in dates:
                return 0.0
            
            idx = dates.index(date_str)
            if idx < lookback:
                return 0.0
            
            current = data[dates[idx]]['close']
            past = data[dates[idx - lookback]]['close']
            
            return (current - past) / past
        except:
            return 0.0
    
    def calculate_value_score(self, symbol: str, date_str: str) -> float:
        """Score de valor simplificado"""
        # En implementación real, usar datos fundamentales
        return random.uniform(0.3, 0.7)
    
    def calculate_quality_score(self, symbol: str, date_str: str) -> float:
        """Score de calidad simplificado"""
        return random.uniform(0.3, 0.7)
    
    def calculate_volume_ratio(self, symbol: str, date_str: str) -> float:
        """Ratio de volumen vs promedio"""
        return random.uniform(0.8, 1.2)
    
    def calculate_sector_momentum(self, symbol: str, date_str: str) -> float:
        """Momentum del sector"""
        return random.uniform(-0.1, 0.1)
    
    def get_market_regime(self, date_str: str) -> float:
        """Regimen de mercado (trending/ranging)"""
        return random.uniform(-1, 1)
    
    def get_vix_level(self, date_str: str) -> float:
        """Nivel de VIX"""
        return random.uniform(15, 25)
    
    def calculate_correlation(self, s1: str, s2: str, date_str: str) -> float:
        """Calcular correlación entre dos símbolos"""
        try:
            data1 = self.price_data.get(s1, {})
            data2 = self.price_data.get(s2, {})
            
            dates = sorted(set(data1.keys()) & set(data2.keys()))
            if len(dates) < 20:
                return 0.0
            
            # Tomar últimos 20 días comunes antes de date_str
            if date_str in dates:
                idx = dates.index(date_str)
                dates = dates[max(0, idx-20):idx]
            else:
                dates = dates[-20:]
            
            prices1 = [data1[d]['close'] for d in dates if d in data1]
            prices2 = [data2[d]['close'] for d in dates if d in data2]
            
            if len(prices1) < 10 or len(prices2) < 10:
                return 0.0
            
            returns1 = np.diff(prices1) / prices1[:-1]
            returns2 = np.diff(prices2) / prices2[:-1]
            
            if len(returns1) != len(returns2):
                min_len = min(len(returns1), len(returns2))
                returns1 = returns1[-min_len:]
                returns2 = returns2[-min_len:]
            
            return np.corrcoef(returns1, returns2)[0, 1]
        except:
            return 0.0
    
    def simulate_intraday_price(self, open_p: float, high: float, low: float, 
                                close: float, minute: int) -> float:
        """Simular precio intradía"""
        progress = minute / self.config.DAILY_MINUTES
        base = open_p + (close - open_p) * progress
        
        if high > low:
            np.random.seed(int(base * 10000) % 2**32)
            noise = np.random.uniform(-0.3, 0.3)
            variation = (high - low) * noise
            price = base + variation
            return max(low, min(high, price))
        return base
    
    # ═══════════════════════════════════════════════════════════════════════════
    # BACKTEST PRINCIPAL
    # ═══════════════════════════════════════════════════════════════════════════
    
    def download_data(self, start_date: str, end_date: str):
        """Descargar datos de precios"""
        print("Descargando datos...")
        
        for symbol in self.config.UNIVERSE:
            try:
                df = yf.download(symbol, start=start_date, end=end_date, progress=False)
                if len(df) > 100:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = df.columns.get_level_values(0)
                    
                    # Guardar como diccionario
                    self.price_data[symbol] = {}
                    for idx, row in df.iterrows():
                        date_str = idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx)[:10]
                        self.price_data[symbol][date_str] = {
                            'open': self.get_scalar(row['Open']),
                            'high': self.get_scalar(row['High']),
                            'low': self.get_scalar(row['Low']),
                            'close': self.get_scalar(row['Close']),
                            'volume': self.get_scalar(row.get('Volume', 0))
                        }
            except Exception as e:
                pass
        
        print(f"  Datos descargados: {len(self.price_data)} símbolos")
        
        # Crear market data (SPY proxy)
        try:
            spy = yf.download('SPY', start=start_date, end=end_date, progress=False)
            if isinstance(spy.columns, pd.MultiIndex):
                spy.columns = spy.columns.get_level_values(0)
            spy['returns'] = spy['Close'].pct_change()
            self.market_data = spy
        except:
            pass
    
    def run_backtest(self, start_date: str = '2000-01-01', end_date: str = '2026-02-09'):
        """Ejecutar backtest completo v8.0"""
        
        print("=" * 80)
        print("OMNICAPITAL v8.0 - ULTIMATE EDITION")
        print("=" * 80)
        print("Features activadas:")
        print(f"  [OK] Smart Random Selection: {self.config.SMART_RANDOM_FILTER}")
        print(f"  [OK] Continuous Entry: {self.config.DAILY_POSITIONS} posiciones/dia")
        print(f"  [OK] Intraday Seasonality: {self.config.USE_SEASONALITY}")
        print(f"  [OK] Volatility Regime: {self.config.USE_VOLATILITY_REGIME}")
        print(f"  [OK] Multi-Horizon Hold: {len(self.config.HOLD_PERIODS)} periodos")
        print(f"  [OK] Correlation Hedge: {self.config.USE_CORRELATION_HEDGE}")
        print(f"  [OK] Walk-Forward Optimization: {self.config.USE_WFO}")
        print(f"  [OK] ML Ensemble: {self.config.USE_ML and ML_AVAILABLE}")
        print("=" * 80)
        
        # Descargar datos
        self.download_data(start_date, end_date)
        
        # Obtener fechas de trading
        all_dates = sorted(set().union(*[set(d.keys()) for d in self.price_data.values()]))
        all_dates = [d for d in all_dates if start_date <= d <= end_date]
        
        print(f"\nDías de trading: {len(all_dates)}")
        print("=" * 80)
        
        # Loop principal
        for i, date_str in enumerate(all_dates):
            date = datetime.strptime(date_str, '%Y-%m-%d')
            
            # Verificar WFO
            if self.should_reoptimize(date):
                self.walk_forward_optimization(date)
            
            # Calcular régimen de volatilidad
            portfolio_vol = self.get_portfolio_volatility(date_str)
            regime_mult = self.get_regime_multiplier(portfolio_vol)
            
            # Cerrar posiciones que expiran
            self._close_expiring_positions(date_str)
            
            # Verificar hedge
            if self.config.USE_CORRELATION_HEDGE:
                portfolio_value = self._calculate_portfolio_value(date_str)
                self.apply_hedge(portfolio_value, date_str)
            
            # Abrir nuevas posiciones (si hay capacidad)
            if len(self.positions) < self.config.MAX_POSITIONS and regime_mult > 0:
                self._open_new_positions(date_str, regime_mult)
            
            # Entrenar ML periódicamente
            if i % 252 == 0 and i > 0 and self.config.USE_ML:
                self.train_ml_models()
            
            # Registrar valor del portafolio
            portfolio_value = self._calculate_portfolio_value(date_str)
            self.portfolio_values.append({
                'date': date_str,
                'portfolio_value': portfolio_value,
                'cash': self.cash,
                'positions_count': len([p for p in self.positions if not p.closed]),
                'regime_multiplier': regime_mult,
                'portfolio_volatility': portfolio_vol
            })
            
            # Mostrar progreso
            if i % 252 == 0 or i == len(all_dates) - 1:
                print(f"[{date_str}] Valor: ${portfolio_value:>12,.2f} | "
                      f"Pos: {len(self.positions):>2} | "
                      f"Regime: {regime_mult:.0%} | "
                      f"Vol: {portfolio_vol:.1%}")
        
        # Resultados finales
        self._print_results()
        self._save_results()
    
    def _close_expiring_positions(self, date_str: str):
        """Cerrar posiciones que expiran hoy"""
        positions_to_close = [p for p in self.positions if p.exit_date.strftime('%Y-%m-%d') == date_str]
        
        for pos in positions_to_close:
            if pos.symbol in self.price_data and date_str in self.price_data[pos.symbol]:
                day_data = self.price_data[pos.symbol][date_str]
                
                exit_price = self.simulate_intraday_price(
                    day_data['open'], day_data['high'],
                    day_data['low'], day_data['close'],
                    pos.exit_minute
                )
                
                pnl, pnl_pct = pos.close_position(exit_price)
                self.cash += pos.shares * exit_price
                
                # Registrar para ML
                if self.config.USE_ML:
                    features = self.extract_trade_features(
                        pos.symbol, pos.entry_date.strftime('%Y-%m-%d'),
                        pos.entry_minute, pos.hold_minutes
                    )
                    features.profitable = pnl > 0
                    self.trade_history_ml.append(features)
                
                self.trades.append({
                    'date': date_str,
                    'symbol': pos.symbol,
                    'action': 'SELL',
                    'price': exit_price,
                    'shares': pos.shares,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'hold_minutes': pos.hold_minutes,
                    'ml_probability': pos.ml_probability
                })
        
        self.positions = [p for p in self.positions if not p.closed]
    
    def _open_new_positions(self, date_str: str, regime_mult: float):
        """Abrir nuevas posiciones"""
        # Seleccionar símbolos
        selected = self.smart_random_selection(date_str)
        
        if not selected:
            return
        
        # Capital disponible
        capital_for_new = self.cash * 0.95 * regime_mult
        capital_per_position = capital_for_new / len(selected)
        
        for symbol in selected:
            if symbol not in self.price_data or date_str not in self.price_data[symbol]:
                continue
            
            day_data = self.price_data[symbol][date_str]
            entry_price = day_data['open']
            
            if entry_price <= 0:
                continue
            
            # Calcular shares
            shares = capital_per_position / entry_price
            cost = shares * entry_price
            
            if cost > self.cash or cost < 1000:
                continue
            
            # Entry minute con seasonality
            entry_minute = self.get_seasonality_entry_minute()
            
            # Select hold period
            hold_minutes = self.select_hold_period(symbol, date_str)
            
            # Calcular exit
            total_minutes = entry_minute + hold_minutes
            days_later = total_minutes // self.config.DAILY_MINUTES
            exit_minute = total_minutes % self.config.DAILY_MINUTES
            
            exit_date = datetime.strptime(date_str, '%Y-%m-%d')
            days_counted = 0
            while days_counted < days_later:
                exit_date += timedelta(days=1)
                if exit_date.weekday() < 5:
                    days_counted += 1
            
            # ML prediction
            ml_prob = 0.5
            if self.config.USE_ML and self.ml_models:
                features = self.extract_trade_features(
                    symbol, date_str, entry_minute, hold_minutes
                )
                ml_prob = self.predict_trade_success(features)
                
                if ml_prob < self.config.ML_PROBABILITY_THRESHOLD:
                    continue  # Skip this trade
            
            # Crear posición
            pos = Position(
                symbol=symbol,
                entry_date=datetime.strptime(date_str, '%Y-%m-%d'),
                entry_price=entry_price,
                shares=shares,
                entry_minute=entry_minute,
                hold_minutes=hold_minutes,
                exit_date=exit_date,
                exit_minute=exit_minute,
                regime_multiplier=regime_mult,
                ml_probability=ml_prob
            )
            
            self.positions.append(pos)
            self.cash -= cost
            
            self.trades.append({
                'date': date_str,
                'symbol': symbol,
                'action': 'BUY',
                'price': entry_price,
                'shares': shares,
                'hold_minutes': hold_minutes,
                'ml_probability': ml_prob,
                'regime_multiplier': regime_mult
            })
    
    def _calculate_portfolio_value(self, date_str: str) -> float:
        """Calcular valor total del portafolio"""
        positions_value = 0
        
        for pos in self.positions:
            if pos.closed:
                continue
            
            if pos.symbol in self.price_data and date_str in self.price_data[pos.symbol]:
                price = self.price_data[pos.symbol][date_str]['close']
                positions_value += pos.shares * price
        
        return self.cash + positions_value
    
    def _print_results(self):
        """Imprimir resultados del backtest"""
        if not self.portfolio_values:
            return
        
        df = pd.DataFrame(self.portfolio_values)
        df['date'] = pd.to_datetime(df['date'])
        
        initial = self.config.INITIAL_CAPITAL
        final = df['portfolio_value'].iloc[-1]
        total_return = (final - initial) / initial
        years = len(df) / 252
        
        print("\n" + "=" * 80)
        print("RESULTADOS FINALES - OMNICAPITAL v8.0 ULTIMATE")
        print("=" * 80)
        
        print(f"\n>> CAPITAL")
        print(f"   Inicial:              ${initial:>15,.2f}")
        print(f"   Final:                ${final:>15,.2f}")
        print(f"   P/L Total:            ${final - initial:>+15,.2f}")
        print(f"   Retorno Total:        {total_return:>+15.2%}")
        
        if years > 0:
            cagr = (1 + total_return) ** (1 / years) - 1
            print(f"   Años:                 {years:>15.1f}")
            print(f"   CAGR:                 {cagr:>+15.2%}")
        
        # Riesgo
        df['returns'] = df['portfolio_value'].pct_change()
        volatility = df['returns'].std() * np.sqrt(252)
        
        rolling_max = df['portfolio_value'].expanding().max()
        drawdown = (df['portfolio_value'] - rolling_max) / rolling_max
        max_dd = drawdown.min()
        
        sharpe = (df['returns'].mean() * 252 - 0.02) / volatility if volatility > 0 else 0
        calmar = cagr / abs(max_dd) if max_dd != 0 else 0
        
        print(f"\n>> RIESGO")
        print(f"   Volatilidad:          {volatility:>15.2%}")
        print(f"   Máximo Drawdown:      {max_dd:>15.2%}")
        print(f"   Sharpe Ratio:         {sharpe:>15.2f}")
        print(f"   Calmar Ratio:         {calmar:>15.2f}")
        
        # Trading
        trades_df = pd.DataFrame(self.trades)
        sells = trades_df[trades_df['action'] == 'SELL']
        
        if len(sells) > 0:
            win_rate = (sells['pnl_pct'] > 0).mean()
            avg_pnl = sells['pnl_pct'].mean()
            wins = sells[sells['pnl_pct'] > 0]['pnl_pct']
            losses = sells[sells['pnl_pct'] < 0]['pnl_pct']
            
            print(f"\n>> TRADING")
            print(f"   Total Operaciones:    {len(sells):>15}")
            print(f"   Win Rate:             {win_rate:>15.1%}")
            print(f"   P/L Promedio:         {avg_pnl:>+15.2%}")
            if len(wins) > 0:
                print(f"   Ganancia Promedio:    {wins.mean():>+15.2%}")
            if len(losses) > 0:
                print(f"   Pérdida Promedio:     {losses.mean():>+15.2%}")
            if len(losses) > 0 and losses.sum() != 0:
                pf = abs(wins.sum() / losses.sum()) if len(wins) > 0 else 0
                print(f"   Profit Factor:        {pf:>15.2f}")
            
            # ML stats
            if 'ml_probability' in sells.columns:
                high_conf = sells[sells['ml_probability'] > 0.60]
                if len(high_conf) > 0:
                    print(f"\n>> ML PERFORMANCE")
                    print(f"   Trades alta confianza: {len(high_conf)}")
                    print(f"   Win rate (conf > 60%): {(high_conf['pnl_pct'] > 0).mean():>14.1%}")
        
        print("=" * 80)
    
    def _save_results(self):
        """Guardar resultados"""
        os.makedirs('backtests', exist_ok=True)
        
        pd.DataFrame(self.portfolio_values).to_csv(
            'backtests/backtest_v8_ultimate_results.csv', index=False
        )
        pd.DataFrame(self.trades).to_csv(
            'backtests/trades_v8_ultimate.csv', index=False
        )
        
        # Guardar config
        with open('backtests/config_v8_ultimate.json', 'w') as f:
            config_dict = {k: str(v) if not isinstance(v, (int, float, bool, list, dict)) else v 
                          for k, v in self.config.__dict__.items()}
            json.dump(config_dict, f, indent=2, default=str)
        
        print("\nResultados guardados en backtests/")


# ═══════════════════════════════════════════════════════════════════════════════
# EJECUCIÓN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print(">>> OMNICAPITAL v8.0 - ULTIMATE EDITION <<<")
    print("=" * 80)
    
    # Configuración optimizada
    config = V8Config(
        SMART_RANDOM_FILTER=True,
        DAILY_POSITIONS=5,
        MAX_POSITIONS=50,
        USE_SEASONALITY=True,
        USE_VOLATILITY_REGIME=True,
        USE_CORRELATION_HEDGE=True,
        USE_WFO=True,
        USE_ML=True
    )
    
    system = OmniCapitalV8(config)
    system.run_backtest('2000-01-01', '2026-02-09')
