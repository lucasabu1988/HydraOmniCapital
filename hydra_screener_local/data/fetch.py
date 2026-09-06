"""
Data fetching ligero para el screener local.
Maneja bien universos grandes (S&P 500) usando descargas por lotes.
"""
import yfinance as yf
import pandas as pd
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


def fetch_index(symbol: str, period: str = "1y") -> pd.Series:
    """Descarga un solo símbolo (SPY, IWM, ...) como Serie de cierres limpia.

    Added for the secondary regime (audit R1): the regime gate is computed on SPY while the
    production universe is Russell-heavy, and in 12.5% of days SPY is above its SMA200 while
    IWM is below. Persisting IWM's regime next to SPY's is how that gap becomes measurable.
    """
    spy = yf.download(symbol, period=period, progress=False, auto_adjust=True)
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


def fetch_spy(period: str = "1y") -> pd.Series:
    """Descarga solo SPY para cálculo de régimen. Siempre devuelve Series limpia."""
    return fetch_index("SPY", period=period)


# ----------------------------------------------------------------------------- HYDRA v9 data layer (TASK-339)
# Stock fetch already takes `period` (default "1y"): the v8.4 call in screener.py is unchanged.
# v9 callers pass period=V9_PRICE_PERIOD ("2y") so 12-7 momentum has 252+126+vol63 bars.
V9_PRICE_PERIOD = "2y"
ETF_UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "DBC", "VNQ"]
TBILL_SYMBOL = "^IRX"
# Isolated holiday/gap fills only. A hole longer than this stays NaN (the engine's 10-bar
# stale carry / write-off is a holdings policy, not a fetch policy).
FFILL_LIMIT_BARS = 3


def _yf_download(batch: list[str], *, auto_adjust: bool, period: str | None = None,
                 start=None, end=None):
    """Shared yfinance download used by `_download_close_batch` and the bar-store provider.

    `end` is inclusive: yfinance treats daily `end` as exclusive, so we add one day.
    """
    kw = dict(progress=False, auto_adjust=auto_adjust, threads=True)
    if start is not None:
        kw["start"] = pd.Timestamp(start).strftime("%Y-%m-%d")
        if end is not None:
            kw["end"] = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        kw["period"] = period or "1y"
    return yf.download(batch, **kw)


def _volume_frame_from_yf(data, batch: list[str]) -> pd.DataFrame:
    """Normalize a yfinance download into a Volume DataFrame keyed by ticker."""
    if data is None or getattr(data, "empty", False):
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        if "Volume" not in data.columns.get_level_values(0):
            return pd.DataFrame()
        vol = data["Volume"]
        if isinstance(vol, pd.Series):
            name = batch[0] if len(batch) == 1 else (vol.name if vol.name in batch else batch[0])
            vol = vol.to_frame(name)
        elif isinstance(vol.columns, pd.MultiIndex):
            vol.columns = vol.columns.get_level_values(-1)
    else:
        if "Volume" not in data.columns:
            return pd.DataFrame()
        vol = data[["Volume"]].rename(columns={"Volume": batch[0]})
        if isinstance(vol, pd.Series):
            vol = vol.to_frame(batch[0])
    vol.columns = [str(c) for c in vol.columns]
    return vol


def _close_frame_from_yf(data, batch: list[str]) -> pd.DataFrame:
    """Normalize a yfinance download into a Close DataFrame keyed by ticker."""
    if data is None or getattr(data, "empty", False):
        raise RuntimeError("empty response")
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"] if "Close" in data.columns.get_level_values(0) else data.iloc[:, 0]
        if isinstance(close, pd.Series):
            name = batch[0] if len(batch) == 1 else (close.name if close.name in batch else batch[0])
            close = close.to_frame(name)
        elif isinstance(close.columns, pd.MultiIndex):
            close.columns = close.columns.get_level_values(-1)
    else:
        if "Close" in data.columns:
            close = data[["Close"]].rename(columns={"Close": batch[0]})
        else:
            close = data.iloc[:, [0]].copy()
            close.columns = [batch[0]]
        if isinstance(close, pd.Series):
            close = close.to_frame(batch[0])
    close.columns = [str(c) for c in close.columns]
    return close


def _download_close_batch(batch: list[str], period: str | None = None, *, auto_adjust: bool = True,
                          start=None, end=None) -> pd.DataFrame:
    data = _yf_download(batch, auto_adjust=auto_adjust, period=period, start=start, end=end)
    return _close_frame_from_yf(data, batch)


def _fetch_closes(tickers: list[str], period: str, *, auto_adjust: bool, report: dict | None,
                  label: str) -> pd.DataFrame:
    """Retry-once batch download of Close. Failures go into `report`; never raised to the caller."""
    if report is None:
        report = {}
    if not tickers:
        report.update(requested=0, downloaded=0, failed_batches=0, failed_tickers=[], missing_share=0.0)
        return pd.DataFrame()

    print(f"Descargando {label} ({len(tickers)} simbolos, period={period})...")
    frames: list[pd.DataFrame] = []
    failed_batches = 0
    failed_tickers: list[str] = []
    batch_size = max(len(tickers), 1)

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        last_err = None
        for attempt in (1, 2):
            try:
                frames.append(_download_close_batch(batch, period, auto_adjust=auto_adjust))
                print("[OK]" if attempt == 1 else "[OK tras reintento]")
                break
            except Exception as e:
                last_err = e
                if attempt == 1:
                    time.sleep(3.0)
        else:
            failed_batches += 1
            failed_tickers.extend(batch)
            print(f"[ERR] {label} lote perdido tras 2 intentos: {last_err}")

    if not frames:
        report.update(requested=len(tickers), downloaded=0, failed_batches=failed_batches,
                      failed_tickers=failed_tickers, missing_share=1.0)
        return pd.DataFrame()

    prices = pd.concat(frames, axis=1).dropna(axis=1, how="all")
    prices = prices.ffill(limit=FFILL_LIMIT_BARS)
    missing = [t for t in tickers if t not in prices.columns]
    failed_tickers = list(dict.fromkeys(failed_tickers + missing))
    downloaded = len(prices.columns)
    requested = len(tickers)
    missing_share = 1.0 - downloaded / requested if requested else 0.0
    report.update(requested=requested, downloaded=downloaded, failed_batches=failed_batches,
                  failed_tickers=failed_tickers, missing_share=round(missing_share, 4))
    return prices


def fetch_etf_closes(symbols: list[str] | None = None, period: str = V9_PRICE_PERIOD,
                     report: dict | None = None) -> pd.DataFrame:
    """Close prices for the v9 ETF sleeve. Default universe is the 10-name design list.

    Gaps of at most FFILL_LIMIT_BARS (3) are forward-filled; longer holes stay NaN.
    A Yahoo failure is recorded in `report` (same shape as fetch_prices_and_volume) and
    not raised — the caller trades what arrived.
    """
    if report is None:
        report = {}
    symbols = list(symbols if symbols is not None else ETF_UNIVERSE)
    prices = _fetch_closes(symbols, period, auto_adjust=True, report=report, label="ETFs")
    if prices.empty:
        return prices
    ordered = [s for s in symbols if s in prices.columns]
    return prices[ordered]


def fetch_tbill(period: str = V9_PRICE_PERIOD, report: dict | None = None) -> pd.Series:
    """13-week T-bill (`^IRX`) as a percent yield Series (not decimal). Empty Series on failure.

    Yahoo's Close for ^IRX is the discount rate in percent (e.g. 5.2, not 0.052). auto_adjust
    is off: this is a rate, not a total-return price. Same 3-bar ffill and report-not-raise
    policy as fetch_etf_closes.
    """
    if report is None:
        report = {}
    px = _fetch_closes([TBILL_SYMBOL], period, auto_adjust=False, report=report, label="T-bill ^IRX")
    if px.empty or TBILL_SYMBOL not in px.columns:
        # yfinance sometimes names the single column "Close" — take the only column
        if not px.empty and px.shape[1] == 1:
            s = px.iloc[:, 0]
        else:
            return pd.Series(dtype=float, name=TBILL_SYMBOL)
    else:
        s = px[TBILL_SYMBOL]
    s = s.rename(TBILL_SYMBOL)
    return s


# ----------------------------------------------------------------------------- TASK-361 cached fetch (additive)
# Production still calls fetch_prices_and_volume. This path is unused until
# config.USE_BAR_STORE is flipped. store_cli --backfill uses it to populate the db.
BAR_STORE_OVERLAP_BARS = 10
_READJUST_REL_TOL = 1e-6
_PERIOD_OFFSETS = {
    "1d": dict(days=1),
    "5d": dict(days=7),
    "1mo": dict(months=1),
    "3mo": dict(months=3),
    "6mo": dict(months=6),
    "1y": dict(years=1),
    "2y": dict(years=2),
    "5y": dict(years=5),
    "10y": dict(years=10),
    "20y": dict(years=20),
}


def period_to_start(period: str, end) -> pd.Timestamp:
    """Map a yfinance period string to an inclusive start date."""
    end_ts = pd.Timestamp(end)
    if end_ts.tzinfo is not None:
        end_ts = end_ts.tz_convert("UTC").tz_localize(None)
    end_ts = end_ts.normalize()
    p = str(period).lower().strip()
    if p == "ytd":
        return pd.Timestamp(year=end_ts.year, month=1, day=1)
    if p == "max":
        return pd.Timestamp("1970-01-01")
    if p not in _PERIOD_OFFSETS:
        raise ValueError(f"unknown period {period!r}")
    return (end_ts - pd.DateOffset(**_PERIOD_OFFSETS[p])).normalize()


def fetch_prices_and_volume_cached(
    tickers: list[str],
    period: str = "1y",
    report: dict | None = None,
    *,
    provider=None,
    store=None,
    asof=None,
    overlap_bars: int = BAR_STORE_OVERLAP_BARS,
):
    """Like fetch_prices_and_volume but persist and reuse bars in the SQLite store.

    Asks `provider` only for [last stored date - overlap_bars, asof] per ticker
    (the full `period` when the ticker is absent). If the overlap's adjusted
    closes differ from the store by > 1e-6 relative, refetches that ticker's
    full period, replaces the rows, and records it in report["readjusted"].
    Returns wide (prices, volumes) from the store. No live caller until the flag.
    """
    from data.store import BarStore

    if report is None:
        report = {}
    report.setdefault("readjusted", [])
    report.setdefault("failed_tickers", [])
    report.setdefault("failed_batches", 0)

    original_count = len(tickers)
    clean = [t for t in tickers if t not in DELISTED_OR_BAD_TICKERS]
    if original_count - len(clean):
        print(f"   [DATA QUALITY] Filtrados {original_count - len(clean)} tickers problemáticos/delisted")
    tickers = [str(t) for t in clean]
    if not tickers:
        report.update(requested=0, downloaded=0, missing_share=0.0, readjusted=[])
        return pd.DataFrame(), pd.DataFrame()

    if store is None:
        store = BarStore()
    if provider is None:
        from data.providers.yfinance_provider import YFinanceProvider
        provider = YFinanceProvider()

    end = pd.Timestamp(asof) if asof is not None else pd.Timestamp.now().normalize()
    if end.tzinfo is not None:
        end = end.tz_convert("UTC").tz_localize(None)
    end = end.normalize()
    start = period_to_start(period, end)
    n_overlap = int(overlap_bars)

    lasts = store.last_dates(tickers)
    missing = [t for t in tickers if t not in lasts]
    present = [t for t in tickers if t in lasts]
    t0 = time.perf_counter()

    if missing:
        print(f"   [bar store] full fetch {len(missing)} ticker(s) {start.date()} -> {end.date()}")
        try:
            full = provider.fetch(missing, start, end)
            got = set()
            if full is not None and not getattr(full, "empty", True) and "ticker" in full.columns:
                store.upsert(full)
                got = set(full["ticker"].astype(str))
            for t in missing:
                if t not in got:
                    report["failed_tickers"].append(t)
                    report.setdefault("failed_reasons", {})[t] = "fetch_empty"
        except Exception as e:
            report["failed_batches"] += 1
            report["failed_tickers"].extend(missing)
            print(f"   [bar store] full fetch failed: {e}")

    if present:
        ostarts = {t: store.overlap_start(t, n=n_overlap) or start for t in present}
        tail_start = min(ostarts.values())
        if tail_start < start:
            tail_start = start
        print(f"   [bar store] tail fetch {len(present)} ticker(s) {tail_start.date()} -> {end.date()}")
        try:
            tail = provider.fetch(present, tail_start, end)
        except Exception as e:
            report["failed_batches"] += 1
            report["failed_tickers"].extend(present)
            print(f"   [bar store] tail fetch failed: {e}")
            tail = pd.DataFrame()
        mismatches: list[str] = []
        matched: list[pd.DataFrame] = []
        if tail is not None and not getattr(tail, "empty", True):
            for t in present:
                incoming = _adj_series(tail, t)
                stored = store.closes([t], ostarts[t], lasts[t], adjusted=True)
                stored_s = stored[t] if (not stored.empty and t in stored.columns) else pd.Series(dtype=float)
                if _relative_mismatch(stored_s, incoming):
                    mismatches.append(t)
                elif "ticker" in tail.columns:
                    matched.append(tail[tail["ticker"].astype(str) == t])
        if matched:
            store.upsert(pd.concat(matched, ignore_index=True))
        if mismatches:
            print(f"   [bar store] readjust {len(mismatches)} ticker(s) batched {start.date()} -> {end.date()}")
            try:
                full = provider.fetch(mismatches, start, end)
                for t in mismatches:
                    piece = full[full["ticker"].astype(str) == t] if (full is not None and not full.empty and "ticker" in full.columns) else pd.DataFrame()
                    n = store.replace_ticker(t, piece, min_bars=n_overlap)
                    if n == 0:
                        report["failed_tickers"].append(t)
                        report.setdefault("failed_reasons", {})[t] = "readjust_empty"
                    else:
                        report["readjusted"].append(t)
            except Exception as e:
                report["failed_tickers"].extend(mismatches)
                print(f"   [bar store] readjust batch failed: {e}")

    elapsed = time.perf_counter() - t0
    try:
        store.record_run(
            tickers_requested=len(tickers),
            tail=len(present),
            readjusted=len(report.get("readjusted") or []),
            seconds=elapsed,
        )
    except Exception:
        pass

    prices = store.closes(tickers, start, end, adjusted=True)
    volumes = store.volumes(tickers, start, end)
    common = prices.columns.intersection(volumes.columns) if not volumes.empty else prices.columns
    prices = prices[common] if len(common) else prices
    volumes = volumes[common] if not volumes.empty and len(common) else (
        pd.DataFrame(columns=list(prices.columns), index=prices.index) if not prices.empty else pd.DataFrame()
    )
    requested = len(tickers)
    downloaded = len(prices.columns)
    missing_share = 1.0 - downloaded / requested if requested else 0.0
    failed = list(dict.fromkeys(report.get("failed_tickers") or []))
    missing_cols = [t for t in tickers if t not in prices.columns]
    failed = list(dict.fromkeys(failed + missing_cols))
    report.update(
        requested=requested,
        downloaded=downloaded,
        failed_tickers=failed,
        missing_share=round(missing_share, 4),
        readjusted=list(report.get("readjusted") or []),
    )
    return prices, volumes


def _adj_series(long_df: pd.DataFrame, ticker: str) -> pd.Series:
    if long_df is None or getattr(long_df, "empty", True) or "ticker" not in long_df.columns:
        return pd.Series(dtype=float)
    sub = long_df[long_df["ticker"].astype(str) == str(ticker)]
    if sub.empty or "close_adj" not in sub.columns:
        return pd.Series(dtype=float)
    idx = pd.DatetimeIndex(pd.to_datetime(sub["date"]))
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    idx = idx.normalize()
    return pd.Series(pd.to_numeric(sub["close_adj"], errors="coerce").values, index=idx, dtype=float)


def _naive_index(idx) -> pd.DatetimeIndex:
    out = pd.DatetimeIndex(pd.to_datetime(idx))
    if out.tz is not None:
        out = out.tz_convert("UTC").tz_localize(None)
    return out.normalize()


def _relative_mismatch(stored: pd.Series, incoming: pd.Series, tol: float = _READJUST_REL_TOL) -> bool:
    if stored is None or incoming is None or stored.empty or incoming.empty:
        return False
    a = stored.copy()
    b = incoming.copy()
    a.index = _naive_index(a.index)
    b.index = _naive_index(b.index)
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    a, b = a.align(b, join="inner")
    valid = a.notna() & b.notna()
    if not valid.any():
        return False
    a, b = a[valid], b[valid]
    rel = (b - a).abs() / a.abs().clip(lower=1e-12)
    return bool((rel > tol).any())


