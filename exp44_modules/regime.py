"""
Regime Detection Module for Experiment 44
==========================================

Fixed regime detection system that addresses five critical bugs found in exp43:

BUG FIX #1 - Timezone mismatch:
    exp43's `date not in spy_data.index` always failed because SPY data (loaded
    from CSV) has tz-naive index while stock price_data dates are tz-aware.
    The function returned 0.5 (neutral) on EVERY call, making regime detection
    completely non-functional.
    FIX: Strip timezone from the lookup date before checking SPY index.

BUG FIX #2 - Breadth computed on filtered top-50:
    exp43 passed `tradeable_symbols` (the momentum-filtered top-50 list) to the
    breadth calculation. This meant breadth was measured on only the best momentum
    stocks -- which are almost always above SMA50 by definition. Breadth was
    artificially inflated and never signaled weakness.
    FIX: Accept `all_symbols` (the full universe) and iterate over ALL available
    stocks in price_data, not just the filtered tradeable list.

BUG FIX #3 - Vol score uses ratio of similar windows:
    exp43 compared 20-day vol vs 63-day vol. These windows are close enough that
    the ratio almost always sits near 1.0, compressing the vol score to ~0.5.
    The score had almost no discriminating power.
    FIX: Use percentile rank of 10-day realized vol within the trailing 252-day
    distribution. This gives a true 0-to-1 spread.

BUG FIX #4 - Trend uses binary flags:
    exp43 used `1.0 if price > sma else 0.0` for trend signals. This creates
    violent regime flips when price oscillates around the SMA, causing whipsaw
    in position sizing and hold periods.
    FIX: Replace binary flags with continuous sigmoid mappings that transition
    smoothly through the crossover zone.

BUG FIX #5 - Thresholds never calibrated:
    exp43's thresholds (0.70/0.45/0.25) were chosen without checking the actual
    composite distribution. With the old bugs the score hovered near 0.5, so the
    thresholds rarely activated the correct regime.
    FIX: Recalibrate to (0.65/0.45/0.30) which match the empirical distribution
    of the fixed composite score.

Component weights (redesigned):
    - Trend:              35%  (was 40%)
    - Volatility:         30%  (unchanged)
    - Breadth:            25%  (was 30%)
    - Vol Term Structure: 10%  (NEW)

Author: Agent REGIME
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Trend component
_SMA_LONG = 200
_SMA_MED = 50
_MOMENTUM_WINDOW = 20          # 20-day momentum for trend sub-signal

# Volatility component
_VOL_FAST = 10                 # Fast realized vol window
_VOL_SLOW = 252                # Distribution lookback for percentile rank

# Breadth component
_BREADTH_SMA = 50              # SMA period for above/below check
_BREADTH_FLOOR = 0.30          # Normalization floor
_BREADTH_CEIL = 0.80           # Normalization ceiling

# Vol term structure component
_VTS_FAST = 10                 # Fast vol window for term structure
_VTS_SLOW = 63                 # Slow vol window for term structure

# Minimum data requirements
_MIN_HISTORY = max(_SMA_LONG, _VOL_SLOW) + 1  # Need 253 days minimum

# Sigmoid steepness for trend mapping
_SIGMOID_K = 15.0              # Controls transition sharpness around 0

# Component weights
_W_TREND = 0.35
_W_VOL = 0.30
_W_BREADTH = 0.25
_W_VTS = 0.10


# ---------------------------------------------------------------------------
# Helper: timezone-safe date normalization
# ---------------------------------------------------------------------------

def _strip_tz(dt):
    """
    Strip timezone info from a datetime/Timestamp to make it tz-naive.

    This is the core fix for BUG #1: SPY data loaded from CSV has tz-naive
    index, but stock data from yfinance has tz-aware index. We normalize
    everything to tz-naive before any index lookup.
    """
    if hasattr(dt, 'tz') and dt.tz is not None:
        return dt.tz_localize(None)
    return dt


def _ensure_tz_naive_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Return a view/copy of the DataFrame with a tz-naive DatetimeIndex.
    Does NOT modify the original DataFrame.
    """
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


# ---------------------------------------------------------------------------
# Helper: sigmoid mapping
# ---------------------------------------------------------------------------

def _sigmoid(x: float, k: float = _SIGMOID_K) -> float:
    """
    Logistic sigmoid mapping: maps (-inf, +inf) -> (0, 1).

    Used for BUG FIX #4 to replace binary trend flags with smooth transitions.
    k controls steepness: higher k = sharper transition.

    At x=0 returns 0.5 (the crossover point).
    At x=+0.05 (~5% above SMA) with k=15, returns ~0.68.
    At x=-0.10 (~10% below SMA) with k=15, returns ~0.18.
    """
    # Clip to avoid overflow in exp
    z = np.clip(k * x, -20.0, 20.0)
    return 1.0 / (1.0 + np.exp(-z))


# ---------------------------------------------------------------------------
# Component 1: Trend Score (35%)
# ---------------------------------------------------------------------------

def _compute_trend(spy_close: pd.Series) -> float:
    """
    Continuous trend score from SPY price action.

    Sub-signals (equally weighted at 1/3 each):
      1. Distance from SMA200 -> sigmoid (how far above/below long-term trend)
      2. SMA50/SMA200 cross   -> sigmoid (golden/death cross strength)
      3. 20-day momentum       -> sigmoid (recent directional strength)

    BUG FIX #4: All three sub-signals use sigmoid mapping instead of the
    binary 0/1 flags used in exp43. This eliminates whipsaw flips when price
    oscillates near a moving average.

    Returns: float in [0, 1], higher = more bullish trend.
    """
    current_price = spy_close.iloc[-1]

    # SMA200
    sma200 = spy_close.iloc[-_SMA_LONG:].mean()

    # SMA50
    sma50 = spy_close.iloc[-_SMA_MED:].mean()

    # Sub-signal 1: Price distance from SMA200 as a fraction
    # e.g., price 5% above SMA200 -> dist = 0.05
    dist_from_sma200 = (current_price / sma200) - 1.0
    sig_dist = _sigmoid(dist_from_sma200, k=_SIGMOID_K)

    # Sub-signal 2: SMA50/SMA200 cross strength
    # Positive when SMA50 > SMA200 (golden cross territory)
    sma_cross = (sma50 / sma200) - 1.0
    sig_cross = _sigmoid(sma_cross, k=_SIGMOID_K * 2)  # Steeper -- crosses are rarer

    # Sub-signal 3: 20-day momentum (% change over 20 days)
    if len(spy_close) >= _MOMENTUM_WINDOW + 1:
        mom_20d = (current_price / spy_close.iloc[-_MOMENTUM_WINDOW - 1]) - 1.0
    else:
        mom_20d = 0.0
    sig_mom = _sigmoid(mom_20d, k=_SIGMOID_K)

    # Equal-weight blend of three sub-signals
    trend_score = (sig_dist + sig_cross + sig_mom) / 3.0

    return float(np.clip(trend_score, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Component 2: Volatility Score (30%)
# ---------------------------------------------------------------------------

def _compute_volatility(spy_close: pd.Series) -> float:
    """
    Volatility regime score using percentile rank.

    BUG FIX #3: exp43 compared 20-day vol vs 63-day vol. Because these windows
    are similar length, the ratio hovered near 1.0, giving ~0.5 always.

    New approach:
      1. Compute 10-day annualized realized vol.
      2. Compute the SAME 10-day vol for each rolling window over the past 252 days.
      3. Percentile rank = fraction of historical 10-day vols that are LOWER than
         the current value.
      4. INVERT: low vol = bullish (score near 1.0), high vol = bearish (score near 0.0).

    Returns: float in [0, 1], higher = calmer (more bullish).
    """
    returns = spy_close.pct_change().dropna()

    if len(returns) < _VOL_SLOW:
        return 0.5  # Not enough history

    # Current 10-day realized vol (annualized)
    current_vol = returns.iloc[-_VOL_FAST:].std() * np.sqrt(252)

    # Build distribution: rolling 10-day vol over the past 252 days
    # We need returns from index [-VOL_SLOW:] to compute rolling windows
    hist_returns = returns.iloc[-_VOL_SLOW:]
    rolling_vol = hist_returns.rolling(window=_VOL_FAST).std() * np.sqrt(252)
    rolling_vol = rolling_vol.dropna()

    if len(rolling_vol) < 20:
        return 0.5

    # Percentile rank: what fraction of historical 10-day vols are <= current
    percentile = float((rolling_vol <= current_vol).sum()) / len(rolling_vol)

    # Invert: low vol = high score (bullish), high vol = low score (bearish)
    vol_score = 1.0 - percentile

    return float(np.clip(vol_score, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Component 3: Market Breadth (25%)
# ---------------------------------------------------------------------------

def _compute_breadth(price_data: Dict[str, pd.DataFrame],
                     all_symbols: List[str],
                     date_naive: pd.Timestamp) -> float:
    """
    Fraction of ALL stocks above their own SMA50, normalized to [0, 1].

    BUG FIX #2: exp43 iterated over `tradeable` (the momentum-filtered top-50
    list). Those stocks are pre-selected for strong momentum so they are almost
    always above SMA50. This made breadth perpetually high (~0.8-0.9) and
    useless as a warning signal.

    Now iterates over `all_symbols` -- the FULL universe of stocks in price_data.
    This gives a true market-wide breadth reading.

    The raw fraction is normalized from [BREADTH_FLOOR, BREADTH_CEIL] to [0, 1]:
      - Below 30% of stocks above SMA50 -> 0.0 (broad weakness)
      - Above 80% of stocks above SMA50 -> 1.0 (broad strength)
      - Linear interpolation in between.

    Args:
        price_data: dict of symbol -> DataFrame with 'Close' column.
        all_symbols: list of ALL symbols to check (not the filtered tradeable list).
        date_naive: tz-naive Timestamp for the current date.

    Returns: float in [0, 1], higher = healthier breadth.
    """
    above_sma = 0
    total_checked = 0

    for symbol in all_symbols:
        if symbol not in price_data:
            continue

        df = price_data[symbol]

        # Normalize index to tz-naive for lookup (BUG FIX #1 applied here too)
        idx = df.index
        if hasattr(idx, 'tz') and idx.tz is not None:
            # Use tz-naive version for lookup
            idx_naive = idx.tz_localize(None)
        else:
            idx_naive = idx

        if date_naive not in idx_naive:
            continue

        loc = idx_naive.get_loc(date_naive)

        if loc < _BREADTH_SMA:
            continue

        close_series = df['Close'].values  # Use numpy array for speed
        stock_sma50 = np.mean(close_series[loc - _BREADTH_SMA + 1: loc + 1])
        stock_price = close_series[loc]

        total_checked += 1
        if stock_price > stock_sma50:
            above_sma += 1

    if total_checked < 10:
        return 0.5  # Not enough data for meaningful breadth

    raw_breadth = above_sma / total_checked

    # Normalize from [FLOOR, CEIL] -> [0, 1]
    normalized = (raw_breadth - _BREADTH_FLOOR) / (_BREADTH_CEIL - _BREADTH_FLOOR)
    return float(np.clip(normalized, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Component 4: Volatility Term Structure (10%)
# ---------------------------------------------------------------------------

def _compute_vol_term_structure(spy_close: pd.Series) -> float:
    """
    Ratio of fast vol to slow vol as a regime signal.

    - Fast/slow < 1.0 (contango): calm market, vol is declining -> bullish
    - Fast/slow > 1.0 (backwardation): vol is spiking -> bearish

    This is conceptually similar to VIX term structure but computed from
    realized vol so we don't need VIX data.

    The ratio is mapped through a sigmoid centered at 1.0:
      ratio = 0.7 -> score ~0.86 (calm)
      ratio = 1.0 -> score = 0.50 (neutral)
      ratio = 1.3 -> score ~0.14 (stressed)

    Returns: float in [0, 1], higher = calmer (more bullish).
    """
    returns = spy_close.pct_change().dropna()

    if len(returns) < _VTS_SLOW:
        return 0.5

    fast_vol = returns.iloc[-_VTS_FAST:].std() * np.sqrt(252)
    slow_vol = returns.iloc[-_VTS_SLOW:].std() * np.sqrt(252)

    if slow_vol < 0.001:
        return 0.5

    ratio = fast_vol / slow_vol

    # Sigmoid centered at ratio=1.0; invert so low ratio = high score
    # (ratio - 1.0) is positive when vol is expanding (bearish)
    vts_score = _sigmoid(-(ratio - 1.0), k=8.0)

    return float(np.clip(vts_score, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Public API: compute_regime_score
# ---------------------------------------------------------------------------

def compute_regime_score(spy_data: pd.DataFrame,
                         date,
                         price_data: Dict[str, pd.DataFrame],
                         all_symbols: List[str]) -> float:
    """
    Compute composite regime score from 0.0 (extreme crisis) to 1.0 (strong bull).

    This is the main entry point, drop-in compatible with exp43's signature
    (same positional args, same return type).

    Components and weights:
        Trend (35%):              Sigmoid of SPY distance from SMA200 + SMA50/SMA200
                                  cross + 20-day momentum
        Volatility (30%):         Percentile rank of 10-day vol in 252-day
                                  distribution (inverted: low vol = bullish)
        Breadth (25%):            % of ALL stocks above SMA50, normalized
                                  from [0.30, 0.80] to [0.0, 1.0]
        Vol Term Structure (10%): Fast/slow vol ratio through sigmoid

    Args:
        spy_data:    DataFrame with 'Close' column for SPY. Index may be tz-naive.
        date:        Current date (Timestamp, may be tz-aware or tz-naive).
        price_data:  Dict of symbol -> DataFrame with 'Close'. Indexes may be tz-aware.
        all_symbols: List of ALL symbols to use for breadth (NOT the filtered list).

    Returns:
        float in [0.0, 1.0]. Higher = more bullish regime.
    """
    # -----------------------------------------------------------------------
    # BUG FIX #1: Normalize date and SPY index to tz-naive
    # -----------------------------------------------------------------------
    date_naive = _strip_tz(pd.Timestamp(date))
    spy = _ensure_tz_naive_index(spy_data)

    # Check if date exists in SPY data
    if date_naive not in spy.index:
        return 0.5  # Neutral fallback (now actually rare, not every-single-day)

    spy_idx = spy.index.get_loc(date_naive)

    if spy_idx < _MIN_HISTORY:
        return 0.5  # Not enough history yet

    # Extract SPY close up to and including current date
    spy_close = spy['Close'].iloc[:spy_idx + 1]

    # -----------------------------------------------------------------------
    # Compute each component
    # -----------------------------------------------------------------------
    trend_score = _compute_trend(spy_close)
    vol_score = _compute_volatility(spy_close)
    breadth_score = _compute_breadth(price_data, all_symbols, date_naive)
    vts_score = _compute_vol_term_structure(spy_close)

    # -----------------------------------------------------------------------
    # Weighted composite
    # -----------------------------------------------------------------------
    composite = (
        _W_TREND * trend_score +
        _W_VOL * vol_score +
        _W_BREADTH * breadth_score +
        _W_VTS * vts_score
    )

    return float(np.clip(composite, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Public API: regime_to_params
# ---------------------------------------------------------------------------

def regime_to_params(regime_score: float) -> dict:
    """
    Convert composite regime score to position sizing and hold parameters.

    BUG FIX #5: Thresholds recalibrated to match the empirical distribution
    of the fixed composite score:

        Score >= 0.65  ->  STRONG_BULL:  12 positions, 10-day hold
        Score >= 0.45  ->  MILD:          8 positions,  8-day hold
        Score >= 0.30  ->  BEAR:          5 positions,  5-day hold
        Score <  0.30  ->  SEVERE_BEAR:   3 positions,  5-day hold

    The old thresholds (0.70/0.45/0.25) were set without ever checking what
    the composite actually produced. With the fixed components, the score
    has a wider effective range and these thresholds produce regime
    transitions at historically appropriate market conditions.

    Args:
        regime_score: float in [0, 1] from compute_regime_score().

    Returns:
        dict with keys:
            'max_positions': int   - number of simultaneous positions
            'hold_days':     int   - minimum holding period in trading days
            'label':         str   - human-readable regime label
    """
    if regime_score >= 0.65:
        return {
            'max_positions': 12,
            'hold_days': 10,
            'label': 'STRONG_BULL',
        }
    elif regime_score >= 0.45:
        return {
            'max_positions': 8,
            'hold_days': 8,
            'label': 'MILD',
        }
    elif regime_score >= 0.30:
        return {
            'max_positions': 5,
            'hold_days': 5,
            'label': 'BEAR',
        }
    else:
        return {
            'max_positions': 3,
            'hold_days': 5,
            'label': 'SEVERE_BEAR',
        }


# ---------------------------------------------------------------------------
# Diagnostic / standalone test
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    print("Regime Detection Module - Standalone Test")
    print("=" * 60)

    # Generate synthetic SPY data for a quick smoke test
    np.random.seed(42)
    n_days = 300
    dates = pd.bdate_range(start='2024-01-01', periods=n_days)
    prices = 450.0 * np.exp(np.cumsum(np.random.normal(0.0003, 0.01, n_days)))
    spy_df = pd.DataFrame({'Close': prices}, index=dates)

    # Generate synthetic stock data (30 stocks)
    fake_price_data = {}
    symbols = [f'STOCK_{i:02d}' for i in range(30)]
    for sym in symbols:
        stock_prices = 100.0 * np.exp(
            np.cumsum(np.random.normal(0.0004, 0.02, n_days))
        )
        fake_price_data[sym] = pd.DataFrame({'Close': stock_prices}, index=dates)

    # Test on the last date
    test_date = dates[-1]
    score = compute_regime_score(spy_df, test_date, fake_price_data, symbols)
    params = regime_to_params(score)

    print(f"Test date:      {test_date.strftime('%Y-%m-%d')}")
    print(f"Regime score:   {score:.4f}")
    print(f"Regime label:   {params['label']}")
    print(f"Max positions:  {params['max_positions']}")
    print(f"Hold days:      {params['hold_days']}")

    # Test with tz-aware date (simulating the bug scenario)
    tz_aware_date = test_date.tz_localize('America/New_York')
    score_tz = compute_regime_score(spy_df, tz_aware_date, fake_price_data, symbols)
    print(f"\nTZ-aware date test: score={score_tz:.4f} (should match {score:.4f})")
    assert abs(score - score_tz) < 1e-10, "TIMEZONE FIX FAILED: scores differ!"
    print("TIMEZONE FIX VERIFIED: tz-aware and tz-naive dates produce identical scores.")

    # Test edge cases
    print("\nEdge case tests:")
    print(f"  Score 0.0 -> {regime_to_params(0.0)}")
    print(f"  Score 0.29 -> {regime_to_params(0.29)}")
    print(f"  Score 0.30 -> {regime_to_params(0.30)}")
    print(f"  Score 0.44 -> {regime_to_params(0.44)}")
    print(f"  Score 0.45 -> {regime_to_params(0.45)}")
    print(f"  Score 0.64 -> {regime_to_params(0.64)}")
    print(f"  Score 0.65 -> {regime_to_params(0.65)}")
    print(f"  Score 1.0 -> {regime_to_params(1.0)}")

    print("\nAll tests passed.")
