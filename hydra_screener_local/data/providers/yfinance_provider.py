"""yfinance BarProvider (TASK-361).

Wraps the existing `data.fetch` download machinery: one download with
`auto_adjust=True` (adjusted close) and one with `False` (raw close + volume),
same batch size and retry-once policy as `_fetch_closes`.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd

from data.fetch import _close_frame_from_yf, _volume_frame_from_yf, _yf_download

BATCH_SIZE = 75
SOURCE = "yfinance"


class YFinanceProvider:
    source = SOURCE

    def __init__(self, batch_size: int = BATCH_SIZE):
        self.batch_size = int(batch_size) if batch_size else BATCH_SIZE

    def fetch(self, tickers: list[str], start, end) -> pd.DataFrame:
        names = [str(t) for t in tickers if t]
        if not names:
            return pd.DataFrame(columns=["ticker", "date", "close_adj", "close_raw", "volume"])
        parts: list[pd.DataFrame] = []
        n = self.batch_size
        for i in range(0, len(names), n):
            batch = names[i : i + n]
            last_err = None
            for attempt in (1, 2):
                try:
                    parts.append(_fetch_batch(batch, start, end))
                    break
                except Exception as e:
                    last_err = e
                    if attempt == 1:
                        time.sleep(3.0)
            else:
                print(f"   [bar store] lote perdido tras 2 intentos ({batch[:3]}...): {last_err}")
            if i + n < len(names):
                time.sleep(1.0)
        if not parts:
            return pd.DataFrame(columns=["ticker", "date", "close_adj", "close_raw", "volume"])
        out = pd.concat(parts, ignore_index=True)
        return out


def _fetch_batch(batch: list[str], start, end) -> pd.DataFrame:
    data_adj = _yf_download(batch, auto_adjust=True, start=start, end=end)
    data_raw = _yf_download(batch, auto_adjust=False, start=start, end=end)
    close_adj = _close_frame_from_yf(data_adj, batch)
    close_raw = _close_frame_from_yf(data_raw, batch)
    volume = _volume_frame_from_yf(data_raw, batch)
    if volume.empty:
        volume = _volume_frame_from_yf(data_adj, batch)
    return _assemble_long(close_adj, close_raw, volume)


def _assemble_long(
    close_adj: pd.DataFrame,
    close_raw: pd.DataFrame,
    volume: pd.DataFrame,
) -> pd.DataFrame:
    a = _wide_to_long(close_adj, "close_adj")
    r = _wide_to_long(close_raw, "close_raw")
    v = _wide_to_long(volume, "volume")
    out = a.merge(r, on=["date", "ticker"], how="outer").merge(v, on=["date", "ticker"], how="outer")
    out = out.dropna(subset=["close_adj", "close_raw"], how="all")
    out["source"] = SOURCE
    out["fetched_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out.reset_index(drop=True)


def _wide_to_long(df: pd.DataFrame, value_name: str) -> pd.DataFrame:
    if df is None or getattr(df, "empty", True):
        return pd.DataFrame(columns=["date", "ticker", value_name])
    x = df.copy()
    x.index = pd.to_datetime(x.index)
    if getattr(x.index, "tz", None) is not None:
        x.index = x.index.tz_convert("UTC").tz_localize(None)
    x.index.name = "date"
    x = x.reset_index()
    long = x.melt(id_vars=["date"], var_name="ticker", value_name=value_name)
    long["ticker"] = long["ticker"].astype(str)
    return long.dropna(subset=[value_name])
