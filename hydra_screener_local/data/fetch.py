"""
Data fetching ligero para el screener local.
Maneja bien universos grandes (S&P 500) usando descargas por lotes.
"""
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import warnings
import time

from config import DELISTED_OR_BAD_TICKERS

warnings.filterwarnings("ignore")


def fetch_prices(tickers: list[str], period: str = "1y", batch_size: int = 75) -> pd.DataFrame:
    """
    Descarga precios de cierre ajustados.
    Divide en lotes para evitar rate limits cuando el universo es grande (S&P 500).

    Aplica automáticamente el filtro de DELISTED_OR_BAD_TICKERS de config.py
    para evitar datos zombies (ej: SNDK) y fallos conocidos de mapeo.
    """
    # === Filtro temprano de tickers malos / delistados ===
    original_count = len(tickers)
    clean_tickers = [t for t in tickers if t not in DELISTED_OR_BAD_TICKERS]
    removed = original_count - len(clean_tickers)

    if removed > 0:
        bad_removed = [t for t in tickers if t in DELISTED_OR_BAD_TICKERS]
        print(f"   [DATA QUALITY] Filtrados {removed} tickers problemáticos/delisted: {bad_removed}")

    tickers = clean_tickers
    if not tickers:
        print("   [DATA QUALITY] Todos los tickers fueron filtrados como problemáticos.")
        return pd.DataFrame()

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
            try:
                print("✓")
            except UnicodeEncodeError:
                print("[OK]")
            
            # Pequeña pausa para no saturar Yahoo
            if i + batch_size < len(tickers):
                time.sleep(1.0)
                
        except Exception as e:
            try:
                print(f"✗ Error: {e}")
            except UnicodeEncodeError:
                print(f"[ERR] {e}")
            continue
    
    if not all_data:
        return pd.DataFrame()
    
    # Unir todos los lotes
    combined = pd.concat(all_data, axis=1)
    combined = combined.dropna(axis=1, how='all')
    
    print(f"\nDescarga completada: {len(combined.columns)} tickers con datos.\n")
    return combined


def fetch_prices_and_volume(tickers: list[str], period: str = "1y", batch_size: int = 75):
    """
    Versión extendida que devuelve tanto precios ajustados (Close) como Volumen.
    Mantiene exactamente la misma lógica de baches, pausas y filtrado de bad tickers.

    Returns:
        (prices_df, volume_df)  — ambos DataFrames alineados por fecha y columnas (tickers)
    """
    # Reutilizamos el filtrado de bad tickers del fetch normal
    original_count = len(tickers)
    clean_tickers = [t for t in tickers if t not in DELISTED_OR_BAD_TICKERS]
    removed = original_count - len(clean_tickers)

    if removed > 0:
        bad_removed = [t for t in tickers if t in DELISTED_OR_BAD_TICKERS]
        print(f"   [DATA QUALITY] Filtrados {removed} tickers problemáticos/delisted: {bad_removed}")

    tickers = clean_tickers
    if not tickers:
        print("   [DATA QUALITY] Todos los tickers fueron filtrados como problemáticos.")
        return pd.DataFrame(), pd.DataFrame()

    print(f"Descargando precios + volumen de {len(tickers)} tickers (lotes de ~{batch_size})...")

    all_prices = []
    all_volumes = []

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
                vol = data['Volume'] if 'Volume' in data.columns.get_level_values(0) else pd.DataFrame()
            else:
                # Caso single ticker (raro en full run)
                close = data[['Close']].rename(columns={'Close': batch[0]})
                vol = data[['Volume']].rename(columns={'Volume': batch[0]}) if 'Volume' in data.columns else pd.DataFrame()

            all_prices.append(close)
            if not vol.empty:
                all_volumes.append(vol)

            try:
                print("✓")
            except UnicodeEncodeError:
                print("[OK]")

            if i + batch_size < len(tickers):
                time.sleep(1.0)

        except Exception as e:
            try:
                print(f"✗ Error: {e}")
            except UnicodeEncodeError:
                print(f"[ERR] {e}")
            continue

    if not all_prices:
        return pd.DataFrame(), pd.DataFrame()

    prices = pd.concat(all_prices, axis=1).dropna(axis=1, how='all')
    volumes = pd.concat(all_volumes, axis=1).dropna(axis=1, how='all') if all_volumes else pd.DataFrame()

    # Alinear columnas
    common_cols = prices.columns.intersection(volumes.columns) if not volumes.empty else prices.columns
    prices = prices[common_cols]
    volumes = volumes[common_cols] if not volumes.empty else pd.DataFrame(columns=common_cols)

    print(f"\nDescarga completada: {len(prices.columns)} tickers con precios + volumen.\n")
    return prices, volumes


def fetch_spy(period: str = "1y") -> pd.Series:
    """Descarga solo SPY para cálculo de régimen. Siempre devuelve Series limpia."""
    spy = yf.download("SPY", period=period, progress=False, auto_adjust=True)
    if isinstance(spy, pd.DataFrame):
        if 'Close' in spy.columns:
            s = spy['Close']
        else:
            s = spy.iloc[:, 0]  # fallback
        return s.squeeze().dropna()
    return pd.Series(spy).squeeze().dropna() if spy is not None else pd.Series(dtype=float)