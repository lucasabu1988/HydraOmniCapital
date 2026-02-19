"""
OmniCapital v6 - Data Feed Module
Provee datos de mercado en tiempo real desde multiples fuentes.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import logging
from typing import Dict, Optional, List
import threading
import time

logger = logging.getLogger(__name__)


class DataFeed:
    """Base class para data feeds"""
    
    def __init__(self):
        self.data = {}
        self.last_update = None
        
    def get_price(self, symbol: str) -> Optional[float]:
        raise NotImplementedError
    
    def get_prices(self, symbols: List[str]) -> Dict[str, float]:
        raise NotImplementedError
    
    def is_connected(self) -> bool:
        raise NotImplementedError


class YahooDataFeed(DataFeed):
    """Data feed usando Yahoo Finance (gratuito, delay 15min)"""
    
    def __init__(self, cache_duration: int = 60):
        super().__init__()
        self.cache_duration = cache_duration  # segundos
        self._cache = {}
        self._cache_time = {}
        
    def get_price(self, symbol: str) -> Optional[float]:
        """Obtiene precio actual con cache"""
        now = datetime.now()
        
        # Verificar cache
        if symbol in self._cache:
            cache_age = (now - self._cache_time[symbol]).total_seconds()
            if cache_age < self.cache_duration:
                return self._cache[symbol]
        
        # Obtener nuevo dato
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            price = info.get('last_price', None)
            
            if price:
                self._cache[symbol] = price
                self._cache_time[symbol] = now
                return price
                
        except Exception as e:
            logger.warning(f"Error obteniendo {symbol}: {e}")
        
        # Retornar cache si existe
        return self._cache.get(symbol, None)
    
    def get_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Obtiene multiples precios"""
        prices = {}
        for symbol in symbols:
            price = self.get_price(symbol)
            if price:
                prices[symbol] = price
        return prices
    
    def is_connected(self) -> bool:
        """Verifica conexion"""
        try:
            test = yf.Ticker("SPY").fast_info
            return test.get('last_price', None) is not None
        except:
            return False


class IBKRDataFeed(DataFeed):
    """Data feed usando Interactive Brokers API (tiempo real)"""
    
    def __init__(self, host: str = '127.0.0.1', port: int = 7497, client_id: int = 1):
        super().__init__()
        self.host = host
        self.port = port
        self.client_id = client_id
        self.ib = None
        self._connect()
        
    def _connect(self):
        """Conecta con IBKR"""
        try:
            from ib_insync import IB, Stock
            self.ib = IB()
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            logger.info("Conectado a IBKR")
        except Exception as e:
            logger.error(f"Error conectando a IBKR: {e}")
            self.ib = None
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Obtiene precio en tiempo real"""
        if not self.ib:
            return None
        
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            ticker = self.ib.reqMktData(contract)
            
            # Esperar hasta 5 segundos por datos
            for _ in range(50):
                if ticker.last:
                    return ticker.last
                time.sleep(0.1)
            
            return ticker.close if ticker.close else None
            
        except Exception as e:
            logger.warning(f"Error obteniendo {symbol}: {e}")
            return None
    
    def get_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Obtiene multiples precios"""
        if not self.ib:
            return {}
        
        prices = {}
        contracts = [Stock(s, 'SMART', 'USD') for s in symbols]
        tickers = self.ib.reqTickers(*contracts)
        
        for ticker in tickers:
            if ticker.last:
                prices[ticker.contract.symbol] = ticker.last
            elif ticker.close:
                prices[ticker.contract.symbol] = ticker.close
        
        return prices
    
    def is_connected(self) -> bool:
        """Verifica conexion"""
        return self.ib is not None and self.ib.isConnected()


class AlpacaDataFeed(DataFeed):
    """Data feed usando Alpaca Markets API"""
    
    def __init__(self, api_key: str, api_secret: str, paper: bool = True):
        super().__init__()
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper = paper
        self.api = None
        self._connect()
        
    def _connect(self):
        """Conecta con Alpaca"""
        try:
            from alpaca_trade_api import REST
            base_url = 'https://paper-api.alpaca.markets' if self.paper else 'https://api.alpaca.markets'
            self.api = REST(self.api_key, self.api_secret, base_url)
            logger.info("Conectado a Alpaca")
        except Exception as e:
            logger.error(f"Error conectando a Alpaca: {e}")
            self.api = None
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Obtiene ultimo precio"""
        if not self.api:
            return None
        
        try:
            bar = self.api.get_latest_bar(symbol)
            return bar.c if bar else None
        except Exception as e:
            logger.warning(f"Error obteniendo {symbol}: {e}")
            return None
    
    def get_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Obtiene multiples precios"""
        if not self.api:
            return {}
        
        prices = {}
        try:
            bars = self.api.get_latest_bars(symbols)
            for symbol, bar in bars.items():
                prices[symbol] = bar.c
        except Exception as e:
            logger.error(f"Error obteniendo precios: {e}")
        
        return prices
    
    def is_connected(self) -> bool:
        """Verifica conexion"""
        return self.api is not None


class HistoricalDataLoader:
    """Carga datos historicos para backfill y analisis"""

    def __init__(self, data_dir: str = 'data_cache'):
        self.data_dir = data_dir

    def load_cache(self, filename: str = None) -> pd.DataFrame:
        """Carga cache de datos historicos"""
        import os
        import glob

        if filename:
            filepath = os.path.join(self.data_dir, filename)
        else:
            # Buscar cache mas reciente
            files = glob.glob(os.path.join(self.data_dir, 'dynamic_universe_*.pkl'))
            if not files:
                raise FileNotFoundError("No se encontro cache de datos")
            filepath = max(files, key=os.path.getctime)

        logger.info(f"Cargando cache: {filepath}")
        return pd.read_pickle(filepath)

    def get_symbol_history(self, symbol: str, days: int = 63) -> pd.DataFrame:
        """Obtiene historial de un simbolo"""
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=f"{days}d")
            return df
        except Exception as e:
            logger.error(f"Error cargando historial de {symbol}: {e}")
            return pd.DataFrame()

    def get_historical_batch(self, symbols: list, period: str = '6mo') -> dict:
        """Download historical data for multiple symbols.
        Returns dict of symbol -> DataFrame with OHLCV data.
        Used by COMPASS v8.2 for momentum scoring and vol targeting."""
        results = {}
        for symbol in symbols:
            try:
                df = yf.download(symbol, period=period, progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                if len(df) > 20:
                    results[symbol] = df
            except Exception as e:
                logger.debug(f"Failed to download {symbol}: {e}")
        logger.info(f"Historical batch: {len(results)}/{len(symbols)} symbols downloaded")
        return results

    def check_symbol_eligibility(self, symbol: str, min_age_days: int = 63) -> bool:
        """Verifica si un simbolo cumple antiguedad minima"""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            # Verificar fecha de IPO
            ipo_date = info.get('firstTradeDateEpochUtc', None)
            if ipo_date:
                ipo_date = datetime.fromtimestamp(ipo_date)
                age_days = (datetime.now() - ipo_date).days
                return age_days >= min_age_days

            # Fallback: verificar datos disponibles
            hist = ticker.history(period=f"{min_age_days}d")
            return len(hist) >= min_age_days * 0.7  # 70% de dias

        except Exception as e:
            logger.warning(f"Error verificando elegibilidad de {symbol}: {e}")
            return False


class MarketDataManager:
    """Manager central de datos de mercado"""
    
    def __init__(self, primary_feed: str = 'yahoo'):
        self.primary_feed = primary_feed
        self.feed = self._create_feed()
        self.historical = HistoricalDataLoader()
        self._running = False
        self._update_thread = None
        self._latest_prices = {}
        
    def _create_feed(self) -> DataFeed:
        """Crea el data feed principal"""
        if self.primary_feed == 'yahoo':
            return YahooDataFeed()
        elif self.primary_feed == 'ibkr':
            return IBKRDataFeed()
        else:
            raise ValueError(f"Feed no soportado: {self.primary_feed}")
    
    def start(self, symbols: List[str], update_interval: int = 60):
        """Inicia actualizacion continua de precios"""
        self._running = True
        self._update_thread = threading.Thread(
            target=self._update_loop,
            args=(symbols, update_interval),
            daemon=True
        )
        self._update_thread.start()
        logger.info(f"Market data manager iniciado con {len(symbols)} simbolos")
    
    def stop(self):
        """Detiene actualizacion"""
        self._running = False
        if self._update_thread:
            self._update_thread.join(timeout=5)
    
    def _update_loop(self, symbols: List[str], interval: int):
        """Loop de actualizacion"""
        while self._running:
            try:
                prices = self.feed.get_prices(symbols)
                self._latest_prices.update(prices)
                time.sleep(interval)
            except Exception as e:
                logger.error(f"Error en update loop: {e}")
                time.sleep(5)
    
    def get_price(self, symbol: str) -> Optional[float]:
        """Obtiene precio mas reciente"""
        return self._latest_prices.get(symbol, None)
    
    def get_all_prices(self) -> Dict[str, float]:
        """Obtiene todos los precios en cache"""
        return self._latest_prices.copy()
    
    def is_ready(self) -> bool:
        """Verifica si hay datos disponibles"""
        return len(self._latest_prices) > 0


if __name__ == "__main__":
    # Test del data feed
    logging.basicConfig(level=logging.INFO)
    
    print("Probando Yahoo Data Feed...")
    feed = YahooDataFeed()
    
    symbols = ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META']
    prices = feed.get_prices(symbols)
    
    print("\nPrecios obtenidos:")
    for sym, price in prices.items():
        print(f"  {sym}: ${price:.2f}")
    
    print(f"\nConectado: {feed.is_connected()}")
