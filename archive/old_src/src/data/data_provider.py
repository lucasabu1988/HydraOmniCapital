"""
Proveedores de Datos de Mercado
Maneja la obtención de datos históricos y en tiempo real
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import yfinance as yf


class DataProvider(ABC):
    """Clase base para proveedores de datos"""
    
    @abstractmethod
    def get_historical_prices(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
        interval: str = '1d'
    ) -> pd.DataFrame:
        """Obtiene precios históricos"""
        pass
    
    @abstractmethod
    def get_current_price(self, symbols: List[str]) -> Dict[str, float]:
        """Obtiene precios actuales"""
        pass


class YFinanceProvider(DataProvider):
    """
    Proveedor de datos usando Yahoo Finance (yfinance)
    """
    
    def __init__(self, cache_dir: Optional[str] = None):
        self.cache_dir = cache_dir
        self._cache: Dict[str, pd.DataFrame] = {}
    
    def get_historical_prices(
        self,
        symbols: List[str],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        interval: str = '1d',
        lookback_years: int = 5
    ) -> pd.DataFrame:
        """
        Obtiene precios históricos para múltiples símbolos
        
        Args:
            symbols: Lista de símbolos de acciones
            start_date: Fecha de inicio
            end_date: Fecha de fin
            interval: Intervalo ('1d', '1wk', '1mo')
            lookback_years: Años de histórico si no se especifica start_date
            
        Returns:
            DataFrame con precios de cierre
        """
        if end_date is None:
            end_date = datetime.now()
        
        if start_date is None:
            start_date = end_date - timedelta(days=365 * lookback_years)
        
        all_data = {}
        
        for symbol in symbols:
            try:
                # Verificar cache
                cache_key = f"{symbol}_{start_date}_{end_date}_{interval}"
                if cache_key in self._cache:
                    all_data[symbol] = self._cache[cache_key]['Close']
                    continue
                
                # Descargar datos
                ticker = yf.Ticker(symbol)
                df = ticker.history(
                    start=start_date,
                    end=end_date,
                    interval=interval,
                    auto_adjust=True
                )
                
                if not df.empty:
                    all_data[symbol] = df['Close']
                    self._cache[cache_key] = df
                    
            except Exception as e:
                print(f"Error descargando {symbol}: {e}")
                continue
        
        if not all_data:
            return pd.DataFrame()
        
        return pd.DataFrame(all_data)
    
    def get_current_price(self, symbols: List[str]) -> Dict[str, float]:
        """
        Obtiene precios actuales para múltiples símbolos
        
        Args:
            symbols: Lista de símbolos
            
        Returns:
            Diccionario {símbolo: precio}
        """
        prices = {}
        
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.info
                prices[symbol] = info.get('currentPrice', info.get('regularMarketPrice', 0))
            except Exception as e:
                print(f"Error obteniendo precio de {symbol}: {e}")
                prices[symbol] = 0.0
        
        return prices
    
    def get_ticker_info(self, symbol: str) -> Dict[str, Any]:
        """
        Obtiene información general del ticker
        
        Args:
            symbol: Símbolo de la acción
            
        Returns:
            Diccionario con información
        """
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            return {
                'name': info.get('longName', ''),
                'sector': info.get('sector', 'Unknown'),
                'industry': info.get('industry', ''),
                'market_cap': info.get('marketCap', 0),
                'beta': info.get('beta', 1.0),
                'dividend_yield': info.get('dividendYield', 0),
                'trailing_pe': info.get('trailingPE'),
                'forward_pe': info.get('forwardPE'),
                'pb_ratio': info.get('priceToBook'),
                'peg_ratio': info.get('pegRatio'),
                'debt_to_equity': info.get('debtToEquity'),
                'current_ratio': info.get('currentRatio'),
                'quick_ratio': info.get('quickRatio'),
                'roe': info.get('returnOnEquity'),
                'roa': info.get('returnOnAssets'),
                'gross_margin': info.get('grossMargins'),
                'operating_margin': info.get('operatingMargins'),
                'profit_margin': info.get('profitMargins'),
                'revenue_growth': info.get('revenueGrowth'),
                'earnings_growth': info.get('earningsGrowth'),
                'avg_volume': info.get('averageVolume', 0),
                'country': info.get('country', 'US')
            }
        except Exception as e:
            print(f"Error obteniendo info de {symbol}: {e}")
            return {}
    
    def get_sp500_symbols(self) -> List[str]:
        """Obtiene lista de símbolos del S&P 500"""
        try:
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            tables = pd.read_html(url)
            df = tables[0]
            return df['Symbol'].tolist()
        except Exception as e:
            print(f"Error obteniendo símbolos S&P 500: {e}")
            # Lista de respaldo con principales empresas
            return [
                'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
                'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
                'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
                'ABT', 'ADBE', 'BAC', 'ACN', 'WFC', 'CRM', 'VZ', 'DHR', 'NKE',
                'TXN', 'PM', 'NEE', 'AMD', 'CMCSA', 'RTX', 'HON', 'INTC', 'IBM'
            ]
    
    def filter_universe(
        self,
        symbols: List[str],
        min_market_cap: float = 1e9,  # $1B
        min_avg_volume: float = 1e6   # 1M
    ) -> List[str]:
        """
        Filtra universo de inversión según criterios
        
        Args:
            symbols: Lista de símbolos
            min_market_cap: Capitalización mínima
            min_avg_volume: Volumen promedio mínimo
            
        Returns:
            Lista filtrada de símbolos
        """
        valid_symbols = []
        
        for symbol in symbols:
            try:
                info = self.get_ticker_info(symbol)
                
                market_cap = info.get('market_cap', 0)
                avg_volume = info.get('avg_volume', 0)
                
                if market_cap >= min_market_cap and avg_volume >= min_avg_volume:
                    valid_symbols.append(symbol)
                    
            except Exception:
                continue
        
        return valid_symbols
    
    def calculate_returns(
        self,
        price_data: pd.DataFrame,
        periods: List[int] = [1, 5, 20, 60, 252]
    ) -> Dict[str, pd.DataFrame]:
        """
        Calcula retornos para diferentes períodos
        
        Args:
            price_data: DataFrame de precios
            periods: Períodos en días
            
        Returns:
            Diccionario de DataFrames de retornos
        """
        returns = {}
        
        for period in periods:
            if period == 1:
                returns[f'daily'] = price_data.pct_change().dropna()
            else:
                returns[f'{period}d'] = price_data.pct_change(period).dropna()
        
        return returns
    
    def calculate_volatility(
        self,
        price_data: pd.DataFrame,
        window: int = 20,
        annualize: bool = True
    ) -> pd.DataFrame:
        """
        Calcula volatilidad móvil
        
        Args:
            price_data: DataFrame de precios
            window: Ventana de cálculo
            annualize: Anualizar resultado
            
        Returns:
            DataFrame de volatilidades
        """
        returns = price_data.pct_change().dropna()
        volatility = returns.rolling(window=window).std()
        
        if annualize:
            volatility = volatility * np.sqrt(252)
        
        return volatility
    
    def get_market_regime(
        self,
        market_symbol: str = 'SPY',
        lookback_days: int = 90
    ) -> str:
        """
        Determina el régimen actual del mercado
        
        Args:
            market_symbol: Símbolo del índice de mercado
            lookback_days: Días de lookback
            
        Returns:
            'bull', 'bear', 'volatile', 'neutral'
        """
        try:
            end = datetime.now()
            start = end - timedelta(days=lookback_days + 50)
            
            prices = self.get_historical_prices([market_symbol], start, end)
            
            if prices.empty:
                return 'neutral'
            
            # Calcular métricas
            returns = prices[market_symbol].pct_change().dropna()
            total_return = (prices[market_symbol].iloc[-1] / prices[market_symbol].iloc[0]) - 1
            volatility = returns.std() * np.sqrt(252)
            
            # SMAs
            sma20 = prices[market_symbol].rolling(20).mean().iloc[-1]
            sma50 = prices[market_symbol].rolling(50).mean().iloc[-1]
            current_price = prices[market_symbol].iloc[-1]
            
            # Determinar régimen
            if total_return > 0.10 and current_price > sma20 > sma50:
                return 'bull'
            elif total_return < -0.10 and current_price < sma20 < sma50:
                return 'bear'
            elif volatility > 0.25:
                return 'volatile'
            else:
                return 'neutral'
                
        except Exception as e:
            print(f"Error determinando régimen de mercado: {e}")
            return 'neutral'
