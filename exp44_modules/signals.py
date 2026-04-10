"""
exp44_modules/signals.py -- Stock Scoring & Selection
======================================================

Improvements over exp43's compute_multi_timeframe_momentum:

1. Vol-adjusted momentum: raw momentum divided by realized vol over the same
   window.  Ranking becomes "who went up most per unit of risk" instead of
   "who went up most".

2. Smooth absolute-momentum penalty: sigmoid replaces the binary *0.5 haircut
   that exp43 applied to negative-return stocks.

3. Multi-factor composite:
       Momentum  40%
       Quality   30%  (median 21d return / std of 21d returns)
       Value     30%  (pullback from 52-week high -- sweet spot 5-20%)

4. Sector momentum overlay: average composite score per sector; top-quartile
   sectors get +20%, bottom-quartile sectors get -30%.

Exported API
------------
compute_signals(price_data, tradeable_symbols, date, sector_map) -> {symbol: score}
select_stocks(scores, max_positions, sector_map, sector_max=3)    -> [symbol, ...]
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from collections import defaultdict
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Configurable constants (may be overridden by the caller's parameter block)
# ---------------------------------------------------------------------------
MOMENTUM_SHORT  = 60
MOMENTUM_MED    = 120
MOMENTUM_LONG   = 252
MOMENTUM_SKIP   = 10
MOMENTUM_WEIGHTS = [0.25, 0.40, 0.35]   # short, med, long

# Factor blend
WEIGHT_MOMENTUM = 0.40
WEIGHT_QUALITY  = 0.30
WEIGHT_VALUE    = 0.30

# Quality-factor rolling window
QUALITY_WINDOW  = 21   # trading days for rolling-return stats

# Value-factor sweet-spot (pullback from 52w high)
VALUE_SWEET_LO  = 0.05   # 5% below 52w high
VALUE_SWEET_HI  = 0.20   # 20% below 52w high
FIFTY_TWO_WEEK  = 252

# Minimum vol floor (prevents division by near-zero vol)
VOL_FLOOR = 0.10

# Sector overlay bonuses / penalties
SECTOR_BONUS    = 0.20   # +20% for top-quartile sector
SECTOR_PENALTY  = -0.30  # -30% for bottom-quartile sector


# ============================================================================
# HELPER -- cross-sectional z-score
# ============================================================================

def _zscore_dict(d: Dict[str, float]) -> Dict[str, float]:
    """Z-score a {symbol: value} dict cross-sectionally.

    Returns an empty dict when the sample is too small (<5) or std is
    negligibly small.
    """
    if len(d) < 5:
        return {}
    vals = np.array(list(d.values()))
    mu = vals.mean()
    sigma = vals.std()
    if sigma < 1e-8:
        return {}
    return {sym: (v - mu) / sigma for sym, v in d.items()}


# ============================================================================
# FACTOR 1 -- Vol-adjusted multi-timeframe momentum
# ============================================================================

def _compute_momentum_factor(
    price_data: Dict[str, pd.DataFrame],
    tradeable: List[str],
    date: pd.Timestamp,
) -> Dict[str, float]:
    """Return {symbol: blended_vol_adjusted_momentum_zscore}.

    For each of three look-back windows (short / med / long) the raw return
    from (tf+skip) to (skip) days ago is divided by realized volatility over
    the same window.  Each time-frame is z-scored cross-sectionally before
    blending with *MOMENTUM_WEIGHTS*.

    A smooth absolute-momentum penalty is applied via sigmoid so that stocks
    with negative 252d returns are down-weighted proportionally rather than
    with the hard *0.5 of exp43.
    """
    raw_vol_adj: Dict[int, Dict[str, float]] = {
        tf: {} for tf in [MOMENTUM_SHORT, MOMENTUM_MED, MOMENTUM_LONG]
    }
    abs_returns: Dict[str, float] = {}   # for sigmoid penalty

    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        try:
            idx = df.index.get_loc(date)
        except KeyError:
            continue

        needed = MOMENTUM_LONG + MOMENTUM_SKIP
        if idx < needed:
            continue

        close_today = df["Close"].iloc[idx]
        close_skip  = df["Close"].iloc[idx - MOMENTUM_SKIP]
        if close_skip <= 0 or close_today <= 0:
            continue

        for tf in [MOMENTUM_SHORT, MOMENTUM_MED, MOMENTUM_LONG]:
            if idx < tf + MOMENTUM_SKIP:
                continue
            close_lookback = df["Close"].iloc[idx - tf - MOMENTUM_SKIP]
            if close_lookback <= 0:
                continue

            raw_momentum = (close_skip / close_lookback) - 1.0

            # Realized vol over the *same* window (skip -> lookback)
            window_start = idx - tf - MOMENTUM_SKIP
            window_end   = idx - MOMENTUM_SKIP + 1
            rets = df["Close"].iloc[window_start:window_end].pct_change().dropna()
            realized_vol = rets.std() * np.sqrt(252) if len(rets) > 5 else VOL_FLOOR
            realized_vol = max(realized_vol, VOL_FLOOR)

            raw_vol_adj[tf][symbol] = raw_momentum / realized_vol

        # Store absolute (252d) return for sigmoid penalty
        if MOMENTUM_LONG in raw_vol_adj and symbol in raw_vol_adj[MOMENTUM_LONG]:
            close_long = df["Close"].iloc[idx - MOMENTUM_LONG - MOMENTUM_SKIP]
            if close_long > 0:
                abs_returns[symbol] = (close_skip / close_long) - 1.0

    # Z-score each time-frame cross-sectionally
    z_per_tf: Dict[int, Dict[str, float]] = {}
    for tf in [MOMENTUM_SHORT, MOMENTUM_MED, MOMENTUM_LONG]:
        z_per_tf[tf] = _zscore_dict(raw_vol_adj[tf])

    # Blend
    weights = dict(zip(
        [MOMENTUM_SHORT, MOMENTUM_MED, MOMENTUM_LONG],
        MOMENTUM_WEIGHTS,
    ))
    blended: Dict[str, float] = {}
    all_symbols = set()
    for tf_dict in z_per_tf.values():
        all_symbols.update(tf_dict.keys())

    for symbol in all_symbols:
        score = 0.0
        total_w = 0.0
        for tf, w in weights.items():
            if symbol in z_per_tf[tf]:
                score += w * z_per_tf[tf][symbol]
                total_w += w
        if total_w > 0:
            blended[symbol] = score / total_w

    # Smooth absolute-momentum penalty (sigmoid)
    for symbol in list(blended.keys()):
        abs_ret = abs_returns.get(symbol, 0.0)
        scalar = 1.0 / (1.0 + np.exp(-10.0 * abs_ret))
        blended[symbol] *= scalar

    return blended


# ============================================================================
# FACTOR 2 -- Quality (return consistency)
# ============================================================================

def _compute_quality_factor(
    price_data: Dict[str, pd.DataFrame],
    tradeable: List[str],
    date: pd.Timestamp,
) -> Dict[str, float]:
    """Return {symbol: quality_zscore}.

    Quality = median(21d rolling return) / std(21d rolling return).
    Stocks with consistently positive short-term returns score higher.
    """
    raw: Dict[str, float] = {}

    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        try:
            idx = df.index.get_loc(date)
        except KeyError:
            continue

        lookback = QUALITY_WINDOW + 60  # need enough history for rolling stats
        if idx < lookback:
            continue

        closes = df["Close"].iloc[idx - lookback : idx + 1]
        rolling_ret = closes.pct_change(QUALITY_WINDOW).dropna()
        if len(rolling_ret) < 10:
            continue

        med = rolling_ret.median()
        std = rolling_ret.std()
        if std < 1e-8:
            continue
        raw[symbol] = med / std

    return _zscore_dict(raw)


# ============================================================================
# FACTOR 3 -- Value (pullback from 52-week high)
# ============================================================================

def _compute_value_factor(
    price_data: Dict[str, pd.DataFrame],
    tradeable: List[str],
    date: pd.Timestamp,
) -> Dict[str, float]:
    """Return {symbol: value_zscore}.

    Value here is a *pullback detector*: we want stocks in the sweet spot of
    5-20% below their 52-week high (they had momentum but pulled back, so
    they offer entry).  Stocks AT the high or MORE THAN 20% below get lower
    scores.

    Score = bell-shaped function peaking in the sweet spot.
    """
    raw: Dict[str, float] = {}

    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        try:
            idx = df.index.get_loc(date)
        except KeyError:
            continue

        if idx < FIFTY_TWO_WEEK:
            continue

        high_52w = df["High"].iloc[idx - FIFTY_TWO_WEEK : idx + 1].max()
        if high_52w <= 0:
            continue
        close = df["Close"].iloc[idx]
        if close <= 0:
            continue

        drawdown = 1.0 - (close / high_52w)  # 0 = at high, 0.20 = 20% below

        # Bell-shaped score: peak at centre of sweet spot
        centre = (VALUE_SWEET_LO + VALUE_SWEET_HI) / 2.0  # 0.125
        width  = (VALUE_SWEET_HI - VALUE_SWEET_LO) / 2.0  # 0.075
        raw[symbol] = np.exp(-0.5 * ((drawdown - centre) / width) ** 2)

    return _zscore_dict(raw)


# ============================================================================
# SECTOR OVERLAY
# ============================================================================

def _apply_sector_overlay(
    scores: Dict[str, float],
    sector_map: Dict[str, str],
) -> Dict[str, float]:
    """Boost top-quartile sectors, penalise bottom-quartile sectors.

    The average composite score per sector determines quartile membership.
    Symbols without a sector mapping are unaffected.
    """
    if not scores:
        return scores

    # Average score per sector
    sector_scores: Dict[str, List[float]] = defaultdict(list)
    for sym, sc in scores.items():
        sector = sector_map.get(sym, "Other")
        sector_scores[sector].append(sc)

    sector_mean = {s: np.mean(v) for s, v in sector_scores.items() if v}
    if len(sector_mean) < 4:
        return scores  # not enough sectors for quartiles

    sorted_sectors = sorted(sector_mean.items(), key=lambda x: x[1])
    n = len(sorted_sectors)
    q1_cutoff = n // 4          # bottom quartile boundary index
    q3_cutoff = n - n // 4      # top quartile boundary index

    bottom_sectors = {s for s, _ in sorted_sectors[:q1_cutoff]}
    top_sectors    = {s for s, _ in sorted_sectors[q3_cutoff:]}

    adjusted = {}
    for sym, sc in scores.items():
        sector = sector_map.get(sym, "Other")
        if sector in top_sectors:
            adjusted[sym] = sc * (1.0 + SECTOR_BONUS)
        elif sector in bottom_sectors:
            adjusted[sym] = sc * (1.0 + SECTOR_PENALTY)   # SECTOR_PENALTY is negative
        else:
            adjusted[sym] = sc
    return adjusted


# ============================================================================
# PUBLIC API
# ============================================================================

def compute_signals(
    price_data: Dict[str, pd.DataFrame],
    tradeable_symbols: List[str],
    date,
    sector_map: Dict[str, str],
) -> Dict[str, float]:
    """Compute multi-factor composite score for every tradeable symbol.

    Factors (all cross-sectionally z-scored before blending):
        - Momentum 40%  (vol-adjusted, multi-timeframe, sigmoid abs-mom)
        - Quality  30%  (return consistency)
        - Value    30%  (pullback from 52w high)

    A sector overlay then adjusts scores: +20% for top-quartile sectors,
    -30% for bottom-quartile sectors.

    Parameters
    ----------
    price_data : dict
        {symbol: DataFrame} with at least 'Close' and 'High' columns,
        DatetimeIndex.
    tradeable_symbols : list
        Symbols eligible for trading on *date*.
    date : pd.Timestamp
        The current trading date.
    sector_map : dict
        {symbol: sector_label}.

    Returns
    -------
    dict
        {symbol: composite_score} for all tradeable symbols that have
        sufficient data.
    """
    date = pd.Timestamp(date)

    mom_z = _compute_momentum_factor(price_data, tradeable_symbols, date)
    qual_z = _compute_quality_factor(price_data, tradeable_symbols, date)
    val_z  = _compute_value_factor(price_data, tradeable_symbols, date)

    # Blend the three factors
    all_syms = set(mom_z) | set(qual_z) | set(val_z)
    composite: Dict[str, float] = {}

    for sym in all_syms:
        score = 0.0
        w_total = 0.0

        if sym in mom_z:
            score += WEIGHT_MOMENTUM * mom_z[sym]
            w_total += WEIGHT_MOMENTUM
        if sym in qual_z:
            score += WEIGHT_QUALITY * qual_z[sym]
            w_total += WEIGHT_QUALITY
        if sym in val_z:
            score += WEIGHT_VALUE * val_z[sym]
            w_total += WEIGHT_VALUE

        if w_total > 0:
            composite[sym] = score / w_total

    # Sector overlay
    composite = _apply_sector_overlay(composite, sector_map)

    return composite


def select_stocks(
    scores: Dict[str, float],
    max_positions: int,
    sector_map: Dict[str, str],
    sector_max: int = 3,
) -> List[str]:
    """Select top-scoring stocks while respecting per-sector caps.

    Parameters
    ----------
    scores : dict
        {symbol: composite_score} as returned by *compute_signals*.
    max_positions : int
        Maximum number of symbols to select.
    sector_map : dict
        {symbol: sector_label}.
    sector_max : int, default 3
        Maximum stocks allowed from any single sector.

    Returns
    -------
    list
        Ordered list of selected symbols (best first).
    """
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    sector_counts: Dict[str, int] = defaultdict(int)
    selected: List[str] = []

    for symbol, _score in ranked:
        if len(selected) >= max_positions:
            break
        sector = sector_map.get(symbol, "Other")
        if sector_counts[sector] >= sector_max:
            continue
        selected.append(symbol)
        sector_counts[sector] += 1

    return selected
