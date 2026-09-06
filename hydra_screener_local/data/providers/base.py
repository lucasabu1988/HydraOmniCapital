"""Bar provider protocol (TASK-361)."""
from __future__ import annotations

from typing import Protocol

import pandas as pd


class BarProvider(Protocol):
    """Fetch OHLCV-lite bars as a long DataFrame.

    Return columns: ticker, date, close_adj, close_raw, volume.
    `start` and `end` are inclusive calendar dates.
    """

    def fetch(self, tickers: list[str], start, end) -> pd.DataFrame: ...
