"""
exp44 Risk Management Module
=============================

Improvements over exp43 "Adaptive Shield" risk architecture:

1. CRASH VELOCITY CIRCUIT BREAKER
   Detects rapid equity deterioration that smooth DD scaling misses.
   - -6% in 5 days OR -10% in 10 days triggers CRASH state.
   - Overrides leverage to 0.15x for a mandatory 10-day cooldown.
   - exp43 problem: smooth DD scaling reacts too slowly to sudden crashes
     because it only looks at peak-to-trough, not the velocity of decline.

2. IMPROVED DRAWDOWN SCALING
   Same smooth approach as exp43 but with a lower floor:
   - 0% to -5%:    Full 1.0x
   - -5% to -15%:  Linear 1.0x to 0.5x
   - -15% to -25%: Linear 0.5x to 0.25x
   - Below -25%:   Floor at 0.20x (lowered from exp43's 0.25x)
   Rationale: in the deepest drawdowns (2008, 2020 crash), even 0.25x
   bleeds too much. 0.20x provides additional capital preservation at the
   tail while still keeping us invested for the recovery.

3. AGGRESSIVE VOL TARGETING
   exp43's vol targeting was largely ineffective because:
   - 15% target was too permissive (never bound in normal markets).
   - 20-day lookback was too slow (vol spikes are already fading by then).
   Fixes:
   - TARGET_VOL lowered to 12%.
   - Lookback shortened to 10 days for faster response.
   - Added vol expansion ratio: if 10d vol > 1.5x the 63d baseline vol,
     cut exposure proportionally. This catches regime changes even when
     absolute vol is still below target.
   - Final vol leverage = min(absolute_target, ratio_target) -- always
     takes the more restrictive of the two signals.

4. CORRELATION-AWARE POSITION SIZING
   exp43 acknowledged correlation risk in its docstring (line 6 of the
   architecture notes) but never implemented it. When the top momentum
   stocks cluster in the same sector/factor, pairwise correlations spike
   and the portfolio behaves like a concentrated bet.
   - Compute average pairwise correlation over a 60-day lookback.
   - If avg correlation > 0.6, reduce total exposure by up to 50%.
   - Linear scaling between 0.3 (no penalty) and 0.6 (max penalty).

5. CORRECTED SHARPE RATIO
   exp43 (line 1024) computed Sharpe as CAGR / annualized_vol, which is
   a commonly-seen but incorrect approximation. The proper formula is:
     Sharpe = mean(daily_excess_return) / std(daily_return) * sqrt(252)
   where daily_excess_return = daily_return - daily_risk_free_rate.
   Uses Moody's AAA yield data (already in the system) as the risk-free
   proxy, converted to daily rates.

Exports
-------
compute_dd_leverage          -- Drawdown-based leverage multiplier.
compute_vol_leverage         -- Volatility targeting leverage multiplier.
detect_crash                 -- Crash velocity circuit breaker.
compute_correlation_adjustment -- Correlation-based exposure reduction.
compute_final_leverage       -- Unified leverage combining all signals.
compute_sharpe_ratio         -- Correct Sharpe with risk-free subtraction.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional


# =============================================================================
# CONSTANTS
# =============================================================================

# --- Crash Velocity Circuit Breaker ---
CRASH_THRESHOLD_5D = -0.06        # -6% in 5 trading days
CRASH_THRESHOLD_10D = -0.10       # -10% in 10 trading days
CRASH_LEVERAGE_OVERRIDE = 0.15    # Override leverage during crash cooldown
CRASH_COOLDOWN_DAYS = 10          # Minimum days in crash lockdown

# --- Drawdown Scaling (improved breakpoints) ---
DD_TIER_1 = -0.05                 # Start reducing at -5%
DD_TIER_2 = -0.15                 # Further reduction at -15%
DD_TIER_3 = -0.25                 # Floor zone at -25%
LEV_FULL = 1.0                    # Full leverage
LEV_REDUCED = 0.50                # Tier 2 target
LEV_MINIMUM = 0.20                # Floor (lowered from exp43's 0.25)

# --- Volatility Targeting (aggressive) ---
TARGET_VOL = 0.12                 # 12% annualized target (from 15%)
VOL_LOOKBACK_SHORT = 10           # 10-day lookback (from 20)
VOL_LOOKBACK_LONG = 63            # 63-day baseline for ratio
VOL_EXPANSION_THRESHOLD = 1.5     # Ratio trigger: 10d > 1.5x 63d
LEVERAGE_MAX = 1.0                # Hard cap (no actual leverage)

# --- Correlation Adjustment ---
CORR_LOOKBACK = 60                # Lookback for pairwise correlations
CORR_FLOOR = 0.30                 # Below this, no penalty
CORR_CEILING = 0.60               # At/above this, maximum penalty
CORR_MIN_MULTIPLIER = 0.50        # Max penalty = 50% exposure reduction


# =============================================================================
# 1. CRASH VELOCITY CIRCUIT BREAKER
# =============================================================================

def detect_crash(portfolio_values: list, current_idx: int) -> bool:
    """
    Detect rapid equity deterioration independent of smooth DD scaling.

    Checks two conditions (either triggers a crash):
      - Portfolio dropped >= 6% over the last 5 trading days.
      - Portfolio dropped >= 10% over the last 10 trading days.

    This catches sharp, fast declines that smooth drawdown scaling reacts
    to too slowly. For example, in March 2020 or Oct 2008, the portfolio
    could lose 8% in a week while the DD scaler was only beginning to
    tighten because peak-to-trough was still modest.

    Parameters
    ----------
    portfolio_values : list
        Chronological list of daily portfolio values. Must contain at least
        current_idx + 1 entries.
    current_idx : int
        Index into portfolio_values for the current day.

    Returns
    -------
    bool
        True if crash velocity is detected, False otherwise.
    """
    if not portfolio_values or current_idx < 5:
        return False

    # Clamp index to valid range
    idx = min(current_idx, len(portfolio_values) - 1)
    if idx < 5:
        return False

    # Support both raw floats and dict-style {'value': float} entries
    def _val(entry):
        if isinstance(entry, dict):
            return entry.get('value', 0)
        return entry

    current_val = _val(portfolio_values[idx])

    # Check 5-day velocity
    val_5d_ago = _val(portfolio_values[idx - 5])
    if val_5d_ago > 0:
        ret_5d = (current_val - val_5d_ago) / val_5d_ago
        if ret_5d <= CRASH_THRESHOLD_5D:
            return True

    # Check 10-day velocity
    if idx >= 10:
        val_10d_ago = _val(portfolio_values[idx - 10])
        if val_10d_ago > 0:
            ret_10d = (current_val - val_10d_ago) / val_10d_ago
            if ret_10d <= CRASH_THRESHOLD_10D:
                return True

    return False


# =============================================================================
# 2. IMPROVED DRAWDOWN SCALING
# =============================================================================

def compute_dd_leverage(current_dd: float) -> float:
    """
    Smooth drawdown-based leverage scaling with improved breakpoints.

    Replaces exp43's version by lowering the floor from 0.25x to 0.20x.
    The rationale: during extreme drawdowns (> -25%), every percentage
    point of additional loss compounds the recovery required. At -25% DD,
    you need +33% to recover; at -35% you need +54%. The extra 5pp of
    exposure reduction (0.25 -> 0.20) meaningfully slows the bleed.

    Tiers:
        DD 0% to -5%:    Full 1.0x leverage (normal conditions).
        DD -5% to -15%:  Linear interpolation from 1.0x down to 0.5x.
        DD -15% to -25%: Linear interpolation from 0.5x down to 0.25x.
        DD below -25%:   Floor at 0.20x (never go to zero).

    Parameters
    ----------
    current_dd : float
        Current drawdown as a negative fraction (e.g., -0.10 for -10%).

    Returns
    -------
    float
        Leverage multiplier in range [LEV_MINIMUM, LEV_FULL].
    """
    dd = current_dd

    if dd >= DD_TIER_1:
        # 0% to -5%: full leverage
        return LEV_FULL
    elif dd >= DD_TIER_2:
        # -5% to -15%: linear from 1.0x to 0.50x
        frac = (dd - DD_TIER_1) / (DD_TIER_2 - DD_TIER_1)
        return LEV_FULL + frac * (LEV_REDUCED - LEV_FULL)
    elif dd >= DD_TIER_3:
        # -15% to -25%: linear from 0.50x to 0.25x
        # Note: we interpolate to 0.25x at the -25% boundary, then the
        # floor at 0.20x applies for anything worse. This avoids a
        # discontinuity at -25%.
        lev_at_tier3 = LEV_MINIMUM + 0.05  # 0.25 at the -25% boundary
        frac = (dd - DD_TIER_2) / (DD_TIER_3 - DD_TIER_2)
        return LEV_REDUCED + frac * (lev_at_tier3 - LEV_REDUCED)
    else:
        # Below -25%: hard floor
        return LEV_MINIMUM


# =============================================================================
# 3. AGGRESSIVE VOL TARGETING
# =============================================================================

def compute_vol_leverage(spy_data: pd.DataFrame, date,
                         target_vol: float = TARGET_VOL) -> float:
    """
    Volatility-targeting leverage multiplier using dual signals.

    exp43's vol targeting (lines 850-863) was largely ineffective because
    its 15% target almost never bound in normal markets, and its 20-day
    lookback was too slow to catch sudden vol spikes. This version fixes
    both issues:

    Signal 1 -- Absolute targeting:
        vol_leverage = target_vol / realized_10d_vol
        Capped at 1.0 (no leverage amplification).

    Signal 2 -- Vol expansion ratio:
        If 10d vol > 1.5x the 63d baseline vol, compute a penalty:
        ratio_leverage = (1.5 * vol_63d) / vol_10d
        This catches regime changes where absolute vol may still be
        below 12% but is expanding rapidly relative to its recent norm.

    The final vol leverage is min(signal_1, signal_2) -- always takes
    the more restrictive of the two.

    Parameters
    ----------
    spy_data : pd.DataFrame
        SPY price data with a 'Close' column and DatetimeIndex.
    date : datetime-like
        Current trading date. Must exist in spy_data.index.
    target_vol : float, optional
        Annualized target volatility (default 0.12 = 12%).

    Returns
    -------
    float
        Leverage multiplier in range (0, 1.0].
    """
    if date not in spy_data.index:
        return 1.0

    spy_idx = spy_data.index.get_loc(date)

    # --- Signal 1: Absolute vol targeting with 10-day lookback ---
    abs_leverage = 1.0
    if spy_idx >= VOL_LOOKBACK_SHORT + 1:
        prices_short = spy_data['Close'].iloc[spy_idx - VOL_LOOKBACK_SHORT:spy_idx + 1]
        returns_short = prices_short.pct_change().dropna()
        if len(returns_short) >= VOL_LOOKBACK_SHORT - 2:
            realized_vol_short = returns_short.std() * np.sqrt(252)
            if realized_vol_short > 0.01:
                abs_leverage = min(target_vol / realized_vol_short, 1.0)

    # --- Signal 2: Vol expansion ratio (10d vs 63d) ---
    ratio_leverage = 1.0
    if spy_idx >= VOL_LOOKBACK_LONG + 1:
        prices_long = spy_data['Close'].iloc[spy_idx - VOL_LOOKBACK_LONG:spy_idx + 1]
        returns_long = prices_long.pct_change().dropna()

        prices_short_for_ratio = spy_data['Close'].iloc[spy_idx - VOL_LOOKBACK_SHORT:spy_idx + 1]
        returns_short_for_ratio = prices_short_for_ratio.pct_change().dropna()

        if len(returns_long) >= VOL_LOOKBACK_LONG - 5 and len(returns_short_for_ratio) >= VOL_LOOKBACK_SHORT - 2:
            vol_short = returns_short_for_ratio.std() * np.sqrt(252)
            vol_long = returns_long.std() * np.sqrt(252)

            if vol_long > 0.01 and vol_short > 0.01:
                expansion_ratio = vol_short / vol_long
                if expansion_ratio > VOL_EXPANSION_THRESHOLD:
                    # Scale down proportionally to the expansion
                    ratio_leverage = min(
                        (VOL_EXPANSION_THRESHOLD * vol_long) / vol_short,
                        1.0
                    )

    # Take the more restrictive of the two signals
    final_vol_leverage = min(abs_leverage, ratio_leverage)

    # Ensure a sane floor -- never zero out entirely from vol alone
    return max(final_vol_leverage, 0.10)


# =============================================================================
# 4. CORRELATION-AWARE POSITION SIZING
# =============================================================================

def compute_correlation_adjustment(price_data: dict, selected_stocks: list,
                                   date, lookback: int = CORR_LOOKBACK) -> float:
    """
    Reduce total exposure when selected stocks are highly correlated.

    exp43 noted correlation as a risk factor (architecture doc, line 6:
    "NO CORRELATION AWARENESS: Top-5 momentum stocks are often in the
    same sector (tech), creating hidden concentration risk") and used
    sector caps to partially address it. But sector caps alone are
    insufficient -- stocks in different sectors can still be highly
    correlated (e.g., cyclical industrials and materials during risk-off).

    This function computes the average pairwise correlation among all
    selected stocks over the lookback window. If the average is high,
    the portfolio effectively has fewer independent bets and should
    reduce total exposure accordingly.

    Scaling:
        avg_corr <= 0.30:  multiplier = 1.0 (no penalty)
        avg_corr >= 0.60:  multiplier = 0.5 (maximum penalty)
        In between:        linear interpolation

    Parameters
    ----------
    price_data : dict
        Mapping of ticker -> pd.DataFrame with 'Close' column and
        DatetimeIndex.
    selected_stocks : list
        List of ticker strings currently selected for the portfolio.
    date : datetime-like
        Current trading date.
    lookback : int, optional
        Number of trading days for correlation window (default 60).

    Returns
    -------
    float
        Multiplier in range [CORR_MIN_MULTIPLIER, 1.0].
    """
    if len(selected_stocks) < 2:
        return 1.0

    # Collect return series for each stock over the lookback window
    return_series = {}
    for stock in selected_stocks:
        if stock not in price_data:
            continue
        df = price_data[stock]
        if date not in df.index:
            continue
        idx = df.index.get_loc(date)
        if idx < lookback:
            continue
        prices = df['Close'].iloc[idx - lookback:idx + 1]
        rets = prices.pct_change().dropna()
        if len(rets) >= lookback - 5:
            return_series[stock] = rets.values

    stocks_with_data = list(return_series.keys())
    if len(stocks_with_data) < 2:
        return 1.0

    # Align all series to the same length (minimum across all)
    min_len = min(len(v) for v in return_series.values())
    aligned = np.column_stack([return_series[s][-min_len:] for s in stocks_with_data])

    # Compute pairwise correlation matrix
    # Use numpy for speed; handle degenerate cases
    n_stocks = aligned.shape[1]
    try:
        corr_matrix = np.corrcoef(aligned, rowvar=False)
    except Exception:
        return 1.0

    # Extract upper triangle (excluding diagonal)
    upper_tri_indices = np.triu_indices(n_stocks, k=1)
    pairwise_corrs = corr_matrix[upper_tri_indices]

    # Filter out NaN values that can arise from zero-variance series
    valid_corrs = pairwise_corrs[~np.isnan(pairwise_corrs)]
    if len(valid_corrs) == 0:
        return 1.0

    avg_corr = float(np.mean(valid_corrs))

    # Linear scaling between CORR_FLOOR and CORR_CEILING
    if avg_corr <= CORR_FLOOR:
        return 1.0
    elif avg_corr >= CORR_CEILING:
        return CORR_MIN_MULTIPLIER
    else:
        # Linear interpolation: 1.0 at CORR_FLOOR, CORR_MIN_MULTIPLIER at CORR_CEILING
        frac = (avg_corr - CORR_FLOOR) / (CORR_CEILING - CORR_FLOOR)
        return 1.0 + frac * (CORR_MIN_MULTIPLIER - 1.0)


# =============================================================================
# 5. CORRECTED SHARPE RATIO
# =============================================================================

def compute_sharpe_ratio(daily_returns: pd.Series,
                         daily_rf_rates: pd.Series) -> float:
    """
    Compute the annualized Sharpe ratio with proper risk-free subtraction.

    exp43 (line 1024) used: Sharpe = CAGR / annualized_vol
    This is incorrect because:
      (a) CAGR is a geometric return, not arithmetic mean.
      (b) No risk-free rate subtraction.
      (c) Mixing annualized return with annualized vol conflates
          compounding effects.

    The standard formula (Lo, 2002) for annualized Sharpe is:
      Sharpe = mean(r_i - rf_i) / std(r_i) * sqrt(252)

    where r_i are daily portfolio returns and rf_i are daily risk-free
    rates. We use Moody's AAA corporate bond yield (already downloaded
    in exp43's data pipeline) as the risk-free proxy, converted from
    annual percentage to daily decimal rate.

    Parameters
    ----------
    daily_returns : pd.Series
        Daily portfolio returns (e.g., from pct_change on portfolio
        values). Index should be DatetimeIndex.
    daily_rf_rates : pd.Series
        Daily risk-free rates as annual percentages (e.g., 4.5 means
        4.5% per year). This matches the format of the Moody's AAA
        yield data stored in the system. Index should be DatetimeIndex.

    Returns
    -------
    float
        Annualized Sharpe ratio. Returns 0.0 if insufficient data or
        zero standard deviation.
    """
    if daily_returns is None or len(daily_returns) < 30:
        return 0.0

    # Align return dates with risk-free dates
    common_dates = daily_returns.index.intersection(daily_rf_rates.index)

    if len(common_dates) < 30:
        # Fall back: if alignment fails, use the mean rf rate over
        # the full rf series as a constant daily rate
        mean_rf_annual = daily_rf_rates.mean() / 100.0  # pct to decimal
        daily_rf_constant = mean_rf_annual / 252.0
        excess_returns = daily_returns - daily_rf_constant
    else:
        aligned_returns = daily_returns.loc[common_dates]
        aligned_rf = daily_rf_rates.loc[common_dates]
        # Convert annual percentage to daily decimal rate
        daily_rf_decimal = aligned_rf / 100.0 / 252.0
        excess_returns = aligned_returns - daily_rf_decimal

    mean_excess = excess_returns.mean()
    std_returns = daily_returns.std()

    if std_returns < 1e-10:
        return 0.0

    sharpe = (mean_excess / std_returns) * np.sqrt(252)
    return float(sharpe)


# =============================================================================
# UNIFIED LEVERAGE COMPUTATION
# =============================================================================

def compute_final_leverage(current_dd: float,
                           spy_data: pd.DataFrame,
                           date,
                           portfolio_values: list,
                           current_idx: int,
                           crash_cooldown: int,
                           price_data: dict = None,
                           selected_stocks: list = None) -> Tuple[float, int]:
    """
    Compute the final leverage multiplier by combining all risk signals.

    This is the main entry point for the risk module. It layers all five
    risk controls in a multiplicative chain:

        final_leverage = min(dd_leverage, vol_leverage) * corr_adjustment

    with a crash override that supersedes everything when active.

    Ordering / priority:
        1. Crash circuit breaker (highest priority -- overrides all).
        2. DD-based leverage (smooth scaling).
        3. Vol-based leverage (dual signal).
        4. Correlation adjustment (multiplicative on the min of 2+3).
        5. Hard floor at LEV_MINIMUM (0.20x) and hard cap at LEVERAGE_MAX.

    State management:
        The crash cooldown counter is passed in and returned updated.
        The caller is responsible for persisting this across days.

    Parameters
    ----------
    current_dd : float
        Current drawdown as a negative fraction (e.g., -0.10).
    spy_data : pd.DataFrame
        SPY price data with 'Close' column and DatetimeIndex.
    date : datetime-like
        Current trading date.
    portfolio_values : list
        Chronological list of daily portfolio values.
    current_idx : int
        Index into portfolio_values for the current day.
    crash_cooldown : int
        Remaining days in crash cooldown (0 = not in cooldown).
    price_data : dict, optional
        Ticker -> DataFrame mapping for correlation computation.
        If None, correlation adjustment is skipped.
    selected_stocks : list, optional
        Currently selected stock tickers. If None, correlation
        adjustment is skipped.

    Returns
    -------
    tuple[float, int]
        (final_leverage, updated_crash_cooldown)
        - final_leverage: float in [LEV_MINIMUM, LEVERAGE_MAX].
        - updated_crash_cooldown: int, decremented or freshly set.
    """
    updated_cooldown = crash_cooldown

    # --- Step 1: Crash circuit breaker ---
    crash_detected = detect_crash(portfolio_values, current_idx)

    if crash_detected:
        # Fresh crash -- reset cooldown to full duration
        updated_cooldown = CRASH_COOLDOWN_DAYS

    if updated_cooldown > 0:
        # Crash override is active -- use the override leverage.
        # The DD scaler can push it even lower only if drawdown is
        # catastrophic (DD scaler returns below 0.15 only past ~-27%).
        # The crash floor is CRASH_LEVERAGE_OVERRIDE itself (0.15),
        # NOT the normal LEV_MINIMUM (0.20), because the entire point
        # of the circuit breaker is to go below normal minimum.
        dd_lev = compute_dd_leverage(current_dd)
        final = min(CRASH_LEVERAGE_OVERRIDE, dd_lev)
        # Decrement AFTER applying the override for this day.
        # cooldown=1 means "this is the last protected day".
        # The returned value of 0 tells the caller that cooldown
        # has expired and the next day will run normally.
        updated_cooldown -= 1
        return (final, updated_cooldown)

    # --- Step 2: DD-based leverage ---
    dd_lev = compute_dd_leverage(current_dd)

    # --- Step 3: Vol-based leverage ---
    vol_lev = compute_vol_leverage(spy_data, date)

    # --- Step 4: Take the more restrictive of DD and vol ---
    base_leverage = min(dd_lev, vol_lev)

    # --- Step 5: Correlation adjustment (multiplicative) ---
    corr_mult = 1.0
    if price_data is not None and selected_stocks is not None and len(selected_stocks) >= 2:
        corr_mult = compute_correlation_adjustment(price_data, selected_stocks, date)

    final = base_leverage * corr_mult

    # --- Enforce bounds ---
    final = min(final, LEVERAGE_MAX)
    final = max(final, LEV_MINIMUM)

    return (final, updated_cooldown)
