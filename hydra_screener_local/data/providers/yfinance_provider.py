"""yfinance BarProvider (TASK-361 / TASK-378 / TASK-382).

Default: one `auto_adjust=False` download per batch; `close_adj` from
`Adj Close`, `close_raw` from `Close`, volume from `Volume`. The old
two-download path is `YFinanceProvider(two_pass=True)` for parity.

Short windows (a store *tail* of <= TAIL_MAX_BARS bars) carry ~10 rows per ticker,
so they use a bigger batch and a shorter pause between batches (TASK-382); the
full-period path keeps 75 names / 1 s.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import pandas as pd

from data.fetch import _close_frame_from_yf, _field_frame_from_yf, _volume_frame_from_yf, _yf_download

BATCH_SIZE = 75
TAIL_BATCH_SIZE = 300      # TASK-382 measured default; see .comms/grok-task-382-tail-batches.md
TAIL_SLEEP = 0.25
TAIL_MAX_BARS = 15         # a window this short (business days) is a tail
SLEEP_BETWEEN_BATCHES = 1.0
SOURCE = "yfinance"


def window_bars(start, end) -> int | None:
    """Business days in [start, end]; None when either bound is missing."""
    if start is None or end is None:
        return None
    try:
        return int(len(pd.bdate_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize())))
    except Exception:
        return None


class YFinanceProvider:
    source = SOURCE

    def __init__(self, batch_size: int = BATCH_SIZE, two_pass: bool = False, *,
                 tail_batch_size: int = TAIL_BATCH_SIZE, tail_sleep: float = TAIL_SLEEP,
                 tail_max_bars: int = TAIL_MAX_BARS):
        self.batch_size = int(batch_size) if batch_size else BATCH_SIZE
        self.two_pass = bool(two_pass)
        self.tail_batch_size = int(tail_batch_size) if tail_batch_size else self.batch_size
        self.tail_sleep = float(tail_sleep)
        self.tail_max_bars = int(tail_max_bars)
        self.last_batches = 0            # how many downloads the last fetch() issued (for the bench)
        self.total_batches = 0           # cumulative over the provider's life (for the bench)

    def batch_plan(self, start, end) -> tuple[int, float]:
        """(batch size, sleep between batches) for this window."""
        bars = window_bars(start, end)
        if bars is not None and bars <= self.tail_max_bars:
            return self.tail_batch_size, self.tail_sleep
        return self.batch_size, SLEEP_BETWEEN_BATCHES

    def fetch(self, tickers: list[str], start, end) -> pd.DataFrame:
        names = [str(t) for t in tickers if t]
        if not names:
            return pd.DataFrame(columns=["ticker", "date", "close_adj", "close_raw", "volume"])
        parts: list[pd.DataFrame] = []
        n, pause = self.batch_plan(start, end)
        self.last_batches = 0
        for i in range(0, len(names), n):
            self.last_batches += 1
            self.total_batches += 1
            batch = names[i : i + n]
            last_err = None
            for attempt in (1, 2):
                try:
                    parts.append(_fetch_batch(batch, start, end, two_pass=self.two_pass))
                    break
                except Exception as e:
                    last_err = e
                    if attempt == 1:
                        time.sleep(3.0)
            else:
                print(f"   [bar store] lote perdido tras 2 intentos ({batch[:3]}...): {last_err}")
            if i + n < len(names):              # never after the last batch
                time.sleep(pause)
        if not parts:
            return pd.DataFrame(columns=["ticker", "date", "close_adj", "close_raw", "volume"])
        out = pd.concat(parts, ignore_index=True)
        return out


def _fetch_batch(batch: list[str], start, end, *, two_pass: bool = False) -> pd.DataFrame:
    if two_pass:
        data_adj = _yf_download(batch, auto_adjust=True, start=start, end=end)
        data_raw = _yf_download(batch, auto_adjust=False, start=start, end=end)
        close_adj = _close_frame_from_yf(data_adj, batch)
        close_raw = _close_frame_from_yf(data_raw, batch)
        volume = _volume_frame_from_yf(data_raw, batch)
        if volume.empty:
            volume = _volume_frame_from_yf(data_adj, batch)
        return _assemble_long(close_adj, close_raw, volume)
    data = _yf_download(batch, auto_adjust=False, start=start, end=end, actions=True)
    close_raw = _close_frame_from_yf(data, batch, field="Close")
    close_adj = _close_frame_from_yf(data, batch, field="Adj Close")
    volume = _volume_frame_from_yf(data, batch)
    dividends = _field_frame_from_yf(data, batch, "Dividends")        # TASK-385
    splits = _field_frame_from_yf(data, batch, "Stock Splits")
    return _assemble_long(close_adj, close_raw, volume, dividends=dividends, splits=splits)


def _assemble_long(
    close_adj: pd.DataFrame,
    close_raw: pd.DataFrame,
    volume: pd.DataFrame,
    dividends: pd.DataFrame | None = None,
    splits: pd.DataFrame | None = None,
) -> pd.DataFrame:
    a = _wide_to_long(close_adj, "close_adj")
    r = _wide_to_long(close_raw, "close_raw")
    v = _wide_to_long(volume, "volume")
    out = a.merge(r, on=["date", "ticker"], how="outer").merge(v, on=["date", "ticker"], how="outer")
    out = out.dropna(subset=["close_adj", "close_raw"], how="all")
    # actions (TASK-385): present only when the download carried the fields; zeros are kept so the
    # store records coverage ("asked, none") and not just the non-zero events
    if dividends is not None and not getattr(dividends, "empty", True):
        d = _wide_to_long(dividends.fillna(0.0), "dividend")
        out = out.merge(d, on=["date", "ticker"], how="left")
        out["dividend"] = out["dividend"].fillna(0.0)
    if splits is not None and not getattr(splits, "empty", True):
        sp = _wide_to_long(splits.fillna(0.0), "split")
        out = out.merge(sp, on=["date", "ticker"], how="left")
        out["split"] = out["split"].fillna(0.0)
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
