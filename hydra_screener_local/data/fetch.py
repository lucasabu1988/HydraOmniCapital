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


def fetch_prices(tickers: list[str], period: str = "1y", batch_size: int = 75) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Kept for callers that predate fetch_prices_and_volume; same behaviour, same (prices, volumes) tuple."""
    return fetch_prices_and_volume(tickers, period=period, batch_size=batch_size)


def fetch_prices_and_volume(tickers: list[str], period: str = "1y", batch_size: int = 75,
                            report: dict | None = None):
    """
    Versión extendida que devuelve tanto precios ajustados (Close) como Volumen.
    Mantiene exactamente la misma lógica de baches, pausas y filtrado de bad tickers.

    Returns:
        (prices_df, volume_df)  - ambos DataFrames alineados por fecha y columnas (tickers)

    report (optional dict, filled in place): requested, downloaded, failed_batches,
    failed_tickers, missing_share. A batch that fails is retried once; if it fails again its
    tickers are recorded here instead of vanishing. Before this existed, one Yahoo error
    silently removed 75 names from the universe for the day with nothing but a print
    (audit 2026-09-06, D1). screener.py turns missing_share into a loud warning.
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
        print("   [DATA QUALITY] Todos los tickers fueron filtrados como problematicos.")
        if report is not None:
            report.update(requested=0, downloaded=0, failed_batches=0, failed_tickers=[], missing_share=0.0)
        return pd.DataFrame(), pd.DataFrame()

    print(f"Descargando precios + volumen de {len(tickers)} tickers (lotes de ~{batch_size})...")

    all_prices = []
    all_volumes = []
    failed_batches = 0
    failed_tickers: list[str] = []

    def _download(batch):
        data = yf.download(batch, period=period, progress=False, auto_adjust=True, threads=True)
        if data is None or data.empty:
            raise RuntimeError("empty response")
        if isinstance(data.columns, pd.MultiIndex):
            close = data['Close']
            vol = data['Volume'] if 'Volume' in data.columns.get_level_values(0) else pd.DataFrame()
        else:
            # Caso single ticker (raro en full run)
            close = data[['Close']].rename(columns={'Close': batch[0]})
            vol = data[['Volume']].rename(columns={'Volume': batch[0]}) if 'Volume' in data.columns else pd.DataFrame()
        return close, vol

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        print(f"  Lote {i//batch_size + 1} ({len(batch)} tickers)...", end=" ", flush=True)

        last_err = None
        for attempt in (1, 2):
            try:
                close, vol = _download(batch)
                all_prices.append(close)
                if not vol.empty:
                    all_volumes.append(vol)
                print("[OK]" if attempt == 1 else "[OK tras reintento]")
                break
            except Exception as e:
                last_err = e
                if attempt == 1:
                    time.sleep(3.0)
        else:
            failed_batches += 1
            failed_tickers.extend(batch)
            print(f"[ERR] lote perdido tras 2 intentos: {last_err}")

        if i + batch_size < len(tickers):
            time.sleep(1.0)

    if not all_prices:
        if report is not None:
            report.update(requested=len(tickers), downloaded=0, failed_batches=failed_batches,
                          failed_tickers=failed_tickers, missing_share=1.0)
        return pd.DataFrame(), pd.DataFrame()

    prices = pd.concat(all_prices, axis=1).dropna(axis=1, how='all')
    volumes = pd.concat(all_volumes, axis=1).dropna(axis=1, how='all') if all_volumes else pd.DataFrame()

    # Alinear columnas
    common_cols = prices.columns.intersection(volumes.columns) if not volumes.empty else prices.columns
    prices = prices[common_cols]
    volumes = volumes[common_cols] if not volumes.empty else pd.DataFrame(columns=common_cols)

    requested = len(tickers)
    downloaded = len(prices.columns)
    missing_share = 1.0 - downloaded / requested if requested else 0.0
    if report is not None:
        report.update(requested=requested, downloaded=downloaded, failed_batches=failed_batches,
                      failed_tickers=failed_tickers, missing_share=round(missing_share, 4))
    lost = f" | {failed_batches} lote(s) perdidos, {len(failed_tickers)} tickers" if failed_batches else ""
    print(f"\nDescarga completada: {downloaded}/{requested} tickers con precios + volumen{lost}.\n")
    return prices, volumes


def fetch_spy(period: str = "1y") -> pd.Series:
    """Descarga solo SPY para cálculo de régimen. Siempre devuelve Series limpia."""
    spy = yf.download("SPY", period=period, progress=False, auto_adjust=True)
    if isinstance(spy, pd.DataFrame):
        s = spy['Close'] if 'Close' in spy.columns else spy.iloc[:, 0]
        # yfinance puede retornar MultiIndex incluso para 1 ticker, haciendo que s sea DataFrame
        if isinstance(s, pd.DataFrame):
            s = s.iloc[:, 0]
    else:
        s = spy
    # Asegurar que siempre sea una Serie
    if isinstance(s, pd.Series):
        return s
    return pd.Series([s]) if s is not None else pd.Series(dtype=float)
