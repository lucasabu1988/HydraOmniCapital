"""
HYDRA v9 sleeve B — ETF trend following (time-series momentum).

Pure functions on a closes DataFrame and a T-bill rate series; no network. The rule is the one
pre-registered in .comms/claude-sleeves-design-2026-09-06.md and measured in experiments/sleeve_lab.py
(`run_sleeve`, executable accounting):

- an ETF is eligible on bar t when it has a close at t and at t - lookback;
- signal: 12-month total return minus the T-bill accumulated over the same window > 0 -> long,
  otherwise the slot stays in T-bill;
- weights: inverse 63-day volatility normalised over the WHOLE eligible universe, so the share of the
  ETFs that are "off" is left in cash (exposure <= 1, no leverage).

`target_weights()` returns exactly what the lab's target function returns for the same inputs; the
parity test in test_portfolio_engine.py checks it against sleeve_lab.run_sleeve.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import V9

UNIVERSE = list(V9["etf_universe"])


def eligible(closes: pd.DataFrame, lookback: int = V9["etf_lookback_bars"]) -> list:
    """ETFs with a price on the last bar and `lookback` bars earlier."""
    if len(closes) <= lookback:
        return []
    last, back = closes.iloc[-1], closes.iloc[-1 - lookback]
    return [c for c in closes.columns if np.isfinite(last.get(c, np.nan)) and np.isfinite(back.get(c, np.nan))]


def tsmom_signal(closes: pd.DataFrame, tbill_daily: pd.Series, lookback: int = V9["etf_lookback_bars"]) -> pd.Series:
    """True where the 12-month excess return over the T-bill is positive (last bar)."""
    names = eligible(closes, lookback)
    if not names:
        return pd.Series(dtype=bool)
    mom = closes[names].iloc[-1] / closes[names].iloc[-1 - lookback] - 1
    tb = float(tbill_daily.reindex(closes.index).ffill().fillna(0.0).iloc[-lookback:].sum())
    return (mom - tb) > 0


def target_weights(closes: pd.DataFrame, tbill_daily: pd.Series, weights: str = "invvol",
                   lookback: int = V9["etf_lookback_bars"], vol_bars: int = V9["etf_vol_bars"]) -> pd.Series:
    """Target weights of the sleeve's capital for the renewed tranche (sum <= 1; remainder = T-bill).

    `tbill_daily` is the annualised rate / 252 per bar, indexed like `closes` (or a superset)."""
    names = eligible(closes, lookback)
    if not names:
        return pd.Series(dtype=float)
    on = tsmom_signal(closes, tbill_daily, lookback)
    rets = closes[names].pct_change(fill_method=None)
    vol = rets.rolling(vol_bars).std().iloc[-1] * np.sqrt(252)
    if weights == "invvol":
        iv = (1.0 / vol).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        base = iv / iv.sum() if iv.sum() > 0 else pd.Series(1.0 / len(names), index=names)
    else:
        base = pd.Series(1.0 / len(names), index=names)
    w = (base * on.reindex(names).fillna(False).astype(float)).astype(float)
    return w[w > 0]
