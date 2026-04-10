"""
exp44_modules/exits.py -- Exit Logic & Stop Computation
========================================================

Improvements over exp43's hard-coded exit rules:

1. Momentum-exhaustion exit: after 3+ days held, re-score the stock; exit if
   its z-score dropped below -0.5 AND short-term return is negative.

2. RSI overbought/oversold exit:
       RSI(14) > 80  AND  profit > 5%   -->  take-profit (overbought)
       RSI(14) < 25  AND  loss   > 3%   -->  cut-loss    (oversold)

3. Adaptive hold period: high-conviction entries (entry z-score > 1.5) get
   1.5x the base hold.  Weak entries (z-score < 0.5) get 0.7x.

4. ATR-based stops: 2.5x 20-day ATR (as fraction of price), floored at -8%
   and capped at -20%.  Trailing stop at 1.5x ATR after activation.

Exported API
------------
compute_rsi(closes, period=14)                            -> float
compute_atr(df, date, lookback=20)                        -> float
check_exit(position, current_price, date, days_held,
           base_hold_days, price_data, symbol, ...)       -> str | None
compute_entry_stops(price_data, symbol, date, entry_price) -> dict
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Dict, Optional, Callable, List

# ---------------------------------------------------------------------------
# Configurable constants
# ---------------------------------------------------------------------------

# Momentum exhaustion
EXHAUSTION_MIN_DAYS    = 3      # only test after this many days held
EXHAUSTION_ZSCORE_THRESH = -0.5

# RSI
RSI_PERIOD             = 14
RSI_OVERBOUGHT         = 80
RSI_OVERSOLD           = 25
RSI_PROFIT_THRESH      = 0.05   # +5% profit required for OB exit
RSI_LOSS_THRESH        = -0.03  # -3% loss required for OS exit

# Adaptive hold multipliers
HIGH_CONVICTION_ZSCORE = 1.5
WEAK_CONVICTION_ZSCORE = 0.5
HIGH_HOLD_MULT         = 1.5
WEAK_HOLD_MULT         = 0.7

# ATR-based stops
ATR_LOOKBACK           = 20
ATR_STOP_MULT          = 2.5    # initial stop = 2.5x ATR below entry
ATR_TRAIL_MULT         = 1.5    # trailing = 1.5x ATR below peak
STOP_FLOOR             = -0.08  # tightest allowed stop (-8%)
STOP_CEILING           = -0.20  # widest  allowed stop (-20%)

# Trailing activation (same semantics as exp43)
TRAILING_ACTIVATION    = 0.08   # trailing engages after +8% gain


# ============================================================================
# RSI
# ============================================================================

def compute_rsi(closes: pd.Series, period: int = RSI_PERIOD) -> float:
    """Compute the Relative Strength Index for the latest bar.

    Parameters
    ----------
    closes : pd.Series
        Price series (at least *period + 1* values).
    period : int
        Look-back window (default 14).

    Returns
    -------
    float
        RSI value in [0, 100].  Returns 50.0 (neutral) if there is
        insufficient data.
    """
    if len(closes) < period + 1:
        return 50.0

    deltas = closes.diff().iloc[1:]  # drop first NaN

    gains = deltas.where(deltas > 0, 0.0)
    losses = (-deltas).where(deltas < 0, 0.0)

    # Wilder's smoothed average (EMA with alpha = 1/period)
    avg_gain = gains.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean().iloc[-1]
    avg_loss = losses.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean().iloc[-1]

    if avg_loss < 1e-10:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ============================================================================
# ATR (as fraction of price)
# ============================================================================

def compute_atr(
    df: pd.DataFrame,
    date,
    lookback: int = ATR_LOOKBACK,
) -> float:
    """Compute the Average True Range as a *fraction of the current price*.

    Parameters
    ----------
    df : pd.DataFrame
        OHLC DataFrame with DatetimeIndex and columns 'High', 'Low', 'Close'.
    date : pd.Timestamp
        The reference date (must be in the index).
    lookback : int
        Number of bars for the ATR average (default 20).

    Returns
    -------
    float
        ATR / current_close.  Returns 0.02 (2%) as a safe fallback when
        data is insufficient.
    """
    date = pd.Timestamp(date)
    if date not in df.index:
        return 0.02
    try:
        idx = df.index.get_loc(date)
    except KeyError:
        return 0.02

    if idx < lookback + 1:
        return 0.02

    window = df.iloc[idx - lookback : idx + 1]
    high  = window["High"].values
    low   = window["Low"].values
    close = window["Close"].values

    # True Range components (vectorised)
    tr1 = high[1:] - low[1:]
    tr2 = np.abs(high[1:] - close[:-1])
    tr3 = np.abs(low[1:]  - close[:-1])
    true_range = np.maximum(tr1, np.maximum(tr2, tr3))

    atr = true_range.mean()
    current_close = close[-1]
    if current_close <= 0:
        return 0.02
    return atr / current_close


# ============================================================================
# ENTRY-TIME STOP COMPUTATION
# ============================================================================

def compute_entry_stops(
    price_data: Dict[str, pd.DataFrame],
    symbol: str,
    date,
    entry_price: float,
) -> dict:
    """Compute per-stock stop levels at entry time.

    Returns
    -------
    dict
        {
            'custom_stop':       float,   # absolute price level for initial stop
            'custom_trail':      float,   # trailing offset in dollars (1.5x ATR)
            'trail_activation':  float,   # price at which trailing engages
        }

    The initial stop is placed at 2.5x ATR below entry, clamped between
    -8% and -20%.  The trailing offset is 1.5x ATR (in dollars).
    Trailing activates after the position gains +8%.
    """
    date = pd.Timestamp(date)
    atr_frac = 0.02  # fallback

    if symbol in price_data:
        df = price_data[symbol]
        atr_frac = compute_atr(df, date, ATR_LOOKBACK)

    # Initial stop distance (as fraction)
    stop_dist = ATR_STOP_MULT * atr_frac               # e.g. 2.5 * 0.03 = 7.5%
    stop_dist = max(stop_dist, abs(STOP_FLOOR))         # at least 8%
    stop_dist = min(stop_dist, abs(STOP_CEILING))       # at most 20%
    custom_stop = entry_price * (1.0 - stop_dist)

    # Trailing offset (dollars)
    custom_trail = ATR_TRAIL_MULT * atr_frac * entry_price

    # Trailing activation price
    trail_activation = entry_price * (1.0 + TRAILING_ACTIVATION)

    return {
        "custom_stop":      custom_stop,
        "custom_trail":     custom_trail,
        "trail_activation": trail_activation,
    }


# ============================================================================
# ADAPTIVE HOLD PERIOD
# ============================================================================

def _adaptive_hold(base_hold_days: int, entry_zscore: float) -> int:
    """Scale the base hold period by conviction strength.

    High-conviction entries (z-score >= 1.5) hold 1.5x longer.
    Weak entries (z-score < 0.5) hold only 0.7x as long.
    Everything in between uses the base unchanged.

    Returns at least 1 day.
    """
    if entry_zscore >= HIGH_CONVICTION_ZSCORE:
        mult = HIGH_HOLD_MULT
    elif entry_zscore < WEAK_CONVICTION_ZSCORE:
        mult = WEAK_HOLD_MULT
    else:
        mult = 1.0
    return max(1, int(round(base_hold_days * mult)))


# ============================================================================
# MAIN EXIT CHECK
# ============================================================================

def check_exit(
    position: dict,
    current_price: float,
    date,
    days_held: int,
    base_hold_days: int,
    price_data: Dict[str, pd.DataFrame],
    symbol: str,
    compute_signals_fn: Optional[Callable] = None,
    tradeable: Optional[List[str]] = None,
    sector_map: Optional[Dict[str, str]] = None,
) -> Optional[str]:
    """Evaluate all exit conditions and return the first triggered reason.

    Exit checks are evaluated in priority order:

    1. **ATR-based stop-loss** -- hard floor.
    2. **Trailing stop** -- 1.5x ATR from peak after activation.
    3. **RSI overbought take-profit** -- RSI > 80 with > 5% profit.
    4. **RSI oversold cut-loss** -- RSI < 25 with > 3% loss.
    5. **Momentum exhaustion** -- re-scored z < -0.5 AND negative short return
       (only after 3+ days held).
    6. **Adaptive hold expiry** -- base_hold scaled by entry conviction.

    Parameters
    ----------
    position : dict
        Must contain at least:
            'entry_price'  : float
            'high_price'   : float   (running peak since entry)
            'entry_zscore' : float   (composite score at entry time)
        Optionally:
            'custom_stop'       : float  (from compute_entry_stops)
            'custom_trail'      : float  (trailing offset in $)
            'trail_activation'  : float  (price level)
    current_price : float
        Latest close.
    date : pd.Timestamp or compatible
        Current bar date.
    days_held : int
        Number of trading days since entry.
    base_hold_days : int
        Regime-dependent base hold period (e.g. 10 in bull, 5 in bear).
    price_data : dict
        Full price data dict.
    symbol : str
        Ticker being evaluated.
    compute_signals_fn : callable, optional
        Reference to signals.compute_signals so that momentum exhaustion
        can re-score the stock.
    tradeable : list, optional
        Current tradeable universe (needed by compute_signals_fn).
    sector_map : dict, optional
        Sector mapping (needed by compute_signals_fn).

    Returns
    -------
    str or None
        Exit reason string, or None if no exit is triggered.
    """
    date = pd.Timestamp(date)
    entry_price  = position["entry_price"]
    high_price   = position.get("high_price", entry_price)
    entry_zscore = position.get("entry_zscore", 1.0)

    pos_return = (current_price - entry_price) / entry_price if entry_price > 0 else 0.0

    # ------------------------------------------------------------------
    # 1. ATR-based stop-loss
    # ------------------------------------------------------------------
    custom_stop = position.get("custom_stop")
    if custom_stop is not None and current_price <= custom_stop:
        return "atr_stop"

    # Fallback hard stop if no custom_stop was stored
    if custom_stop is None and pos_return <= STOP_CEILING:
        return "hard_stop"

    # ------------------------------------------------------------------
    # 2. Trailing stop (ATR-based, after activation)
    # ------------------------------------------------------------------
    trail_activation = position.get("trail_activation")
    custom_trail     = position.get("custom_trail")
    if trail_activation is not None and custom_trail is not None:
        if high_price >= trail_activation:
            trail_level = high_price - custom_trail
            if current_price <= trail_level:
                return "trailing_stop"
    else:
        # Legacy fallback: percent-based trailing
        if high_price > entry_price * (1.0 + TRAILING_ACTIVATION):
            trail_level = high_price * 0.95  # 5% from peak
            if current_price <= trail_level:
                return "trailing_stop"

    # ------------------------------------------------------------------
    # 3. RSI overbought take-profit
    # ------------------------------------------------------------------
    if symbol in price_data:
        df = price_data[symbol]
        if date in df.index:
            try:
                idx = df.index.get_loc(date)
            except KeyError:
                idx = None
            if idx is not None and idx >= RSI_PERIOD + 1:
                rsi_closes = df["Close"].iloc[idx - RSI_PERIOD - 30 : idx + 1]
                rsi = compute_rsi(rsi_closes, RSI_PERIOD)

                if rsi > RSI_OVERBOUGHT and pos_return > RSI_PROFIT_THRESH:
                    return "rsi_overbought"

                # 4. RSI oversold cut-loss
                if rsi < RSI_OVERSOLD and pos_return < RSI_LOSS_THRESH:
                    return "rsi_oversold"

    # ------------------------------------------------------------------
    # 5. Momentum exhaustion
    # ------------------------------------------------------------------
    if (
        days_held >= EXHAUSTION_MIN_DAYS
        and compute_signals_fn is not None
        and tradeable is not None
        and sector_map is not None
    ):
        try:
            fresh_scores = compute_signals_fn(
                price_data, tradeable, date, sector_map,
            )
            current_zscore = fresh_scores.get(symbol)
            if current_zscore is not None:
                if current_zscore < EXHAUSTION_ZSCORE_THRESH and pos_return < 0:
                    return "momentum_exhaustion"
        except Exception:
            pass  # signal computation failure is non-fatal

    # ------------------------------------------------------------------
    # 6. Adaptive hold expiry
    # ------------------------------------------------------------------
    adj_hold = _adaptive_hold(base_hold_days, entry_zscore)
    if days_held >= adj_hold:
        return "hold_expired"

    return None
