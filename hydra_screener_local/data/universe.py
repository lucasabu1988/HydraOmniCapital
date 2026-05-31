"""
Manejo del universo de acciones.
Soporta tanto lista pequeña como el S&P 500 completo de forma ligera.
"""
import pandas as pd
import requests
from io import StringIO
import os
from datetime import datetime, timedelta

CACHE_PATH = "output/sp500_tickers.csv"
CACHE_DAYS = 7  # refrescar la lista cada 7 días


def get_sp500_tickers(use_cache: bool = True) -> list[str]:
    """
    Devuelve la lista actual de tickers del S&P 500.
    - Primero intenta usar caché local (rápido).
    - Si no hay caché reciente, descarga desde Wikipedia.
    """
    if use_cache and os.path.exists(CACHE_PATH):
        mod_time = datetime.fromtimestamp(os.path.getmtime(CACHE_PATH))
        if datetime.now() - mod_time < timedelta(days=CACHE_DAYS):
            df = pd.read_csv(CACHE_PATH)
            return df['ticker'].tolist()

    print("Descargando lista actualizada del S&P 500 desde Wikipedia...", end=" ", flush=True)
    try:
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        response = requests.get(url, timeout=15)
        tables = pd.read_html(StringIO(response.text))
        df = tables[0]
        tickers = df['Symbol'].tolist()

        # Guardar caché
        os.makedirs("output", exist_ok=True)
        pd.DataFrame({"ticker": tickers}).to_csv(CACHE_PATH, index=False)

        print(f"✓ {len(tickers)} tickers")
        return tickers

    except Exception as e:
        print(f"✗ Error descargando lista ({e})")
        print("Usando lista de respaldo (puede estar desactualizada).")
        return get_fallback_sp500_tickers()


def get_fallback_sp500_tickers() -> list[str]:
    """Lista de respaldo por si falla la descarga de Wikipedia."""
    # Esta es una lista aproximada actualizada a 2025-2026.
    # Se actualiza automáticamente la próxima vez que funcione la descarga.
    return [
        "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "TSLA", "BRK-B", "JPM",
        "V", "MA", "XOM", "UNH", "JNJ", "PG", "COST", "HD", "MRK", "LLY", "ABBV", "PEP",
        "KO", "MCD", "WMT", "DIS", "NFLX", "ADBE", "CRM", "INTC", "AMD", "QCOM", "TXN",
        "HON", "UPS", "BA", "CAT", "CVX", "ABT", "TMO", "DHR", "NEE", "LIN", "MDT",
        "BMY", "AMGN", "GILD", "ISRG", "SYK", "BSX", "ELV", "CI", "HUM", "SPGI", "BLK",
        "AXP", "GS", "MS", "C", "BAC", "WFC", "LOW", "NKE", "SBUX", "TGT", "ORCL", "IBM",
        "CSCO", "PFE", "T", "VZ", "CMCSA", "COP", "SLB", "EOG", "MPC", "PSX", "VLO",
        "DE", "LMT", "RTX", "NOC", "GD", "GE", "HON", "MMM", "ITW", "ETN", "EMR", "ROK",
        # ... (puedes agregar más si quieres, pero la descarga desde Wikipedia es preferible)
    ]


def get_universe(full_sp500: bool = False) -> list[str]:
    """
    Devuelve el universo a usar.
    - full_sp500=False → lista pequeña y rápida (para pruebas)
    - full_sp500=True  → S&P 500 completo
    """
    if full_sp500:
        return get_sp500_tickers()
    else:
        from config import INITIAL_UNIVERSE
        return INITIAL_UNIVERSE