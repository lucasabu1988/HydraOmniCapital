"""
Data fetching ligero para el screener local.
Maneja bien universos grandes (S&P 500) usando descargas por lotes.
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import warnings
import time

warnings.filterwarnings("ignore")


def fetch_prices(tickers: list[str], period: str = "1y", batch_size: int = 75) -> pd.DataFrame:
    """
    Descarga precios de cierre ajustados.
    Divide en lotes para evitar rate limits cuando el universo es grande (S&P 500).
    """
    print(f"Descargando datos de {len(tickers)} tickers (en lotes de ~{batch_size})...")
    
    all_data = []
    
    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        print(f"  Lote {i//batch_size + 1} ({len(batch)} tickers)...", end=" ", flush=True)
        
        try:
            data = yf.download(
                batch,
                period=period,
                progress=False,
                auto_adjust=True,
                threads=True
            )
            
            if isinstance(data.columns, pd.MultiIndex):
                close = data['Close']
            else:
                close = data[['Close']].rename(columns={'Close': batch[0]})
            
            all_data.append(close)
            print("✓")
            
            # Pequeña pausa para no saturar Yahoo
            if i + batch_size < len(tickers):
                time.sleep(1.0)
                
        except Exception as e:
            print(f"✗ Error: {e}")
            continue
    
    if not all_data:
        return pd.DataFrame()
    
    # Unir todos los lotes
    combined = pd.concat(all_data, axis=1)
    combined = combined.dropna(axis=1, how='all')
    
    print(f"\nDescarga completada: {len(combined.columns)} tickers con datos.\n")
    return combined


def fetch_spy(period: str = "1y") -> pd.Series:
    """Descarga solo SPY para cálculo de régimen."""
    spy = yf.download("SPY", period=period, progress=False, auto_adjust=True)
    return spy['Close'] if isinstance(spy, pd.DataFrame) else spy