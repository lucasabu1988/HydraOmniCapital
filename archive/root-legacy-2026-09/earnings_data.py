"""
Earnings Data Module — Historical Earnings Surprises
=====================================================
Provides historical earnings surprise data for backtesting the
Earnings Momentum Booster (Pilar 4).

Strategy:
  1. Try yfinance earnings_dates (has EPS actual + estimate for recent quarters)
  2. For deeper history, use price-reaction proxy: detect earnings dates from
     volume spikes and estimate surprise direction/magnitude from the overnight
     gap (close-to-open return on earnings day). This is a well-documented
     proxy used in academic research (DellaVigna & Pollet 2009).

Cache: Saves to data_cache/earnings_surprises.pkl
"""

import pandas as pd
import numpy as np
import yfinance as yf
import pickle
import os
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)

CACHE_DIR = 'data_cache'
CACHE_FILE = os.path.join(CACHE_DIR, 'earnings_surprises.pkl')

# Minimum volume spike to detect earnings day (vs 20-day avg)
VOLUME_SPIKE_THRESHOLD = 1.8
# Quarterly cadence: look for earnings every ~60-70 trading days
MIN_DAYS_BETWEEN_EARNINGS = 45


def detect_earnings_dates_from_price(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect likely earnings dates from volume spikes + overnight gaps.

    Returns DataFrame with columns: [date, surprise_proxy]
    where surprise_proxy is the close-to-close return on the earnings day,
    used as a proxy for earnings surprise magnitude.
    """
    if len(df) < 30:
        return pd.DataFrame(columns=['date', 'surprise_proxy'])

    close = df['Close']
    volume = df['Volume']

    # 20-day average volume
    vol_avg = volume.rolling(20, min_periods=10).mean()
    vol_ratio = volume / vol_avg

    # Overnight gap: open vs previous close
    prev_close = close.shift(1)
    if 'Open' in df.columns:
        gap_return = (df['Open'] / prev_close) - 1.0
    else:
        gap_return = pd.Series(0.0, index=df.index)

    # Daily return (close-to-close) as surprise proxy
    daily_return = close.pct_change()

    # Detect earnings: volume spike > threshold
    is_spike = vol_ratio > VOLUME_SPIKE_THRESHOLD

    # Filter: require minimum spacing (avoid consecutive spikes)
    spike_dates = df.index[is_spike].tolist()
    filtered_dates = []
    last_date_idx = -MIN_DAYS_BETWEEN_EARNINGS

    for d in spike_dates:
        idx = df.index.get_loc(d)
        if idx - last_date_idx >= MIN_DAYS_BETWEEN_EARNINGS:
            filtered_dates.append(d)
            last_date_idx = idx

    if not filtered_dates:
        return pd.DataFrame(columns=['date', 'surprise_proxy'])

    # Build surprise data
    records = []
    for d in filtered_dates:
        ret = daily_return.get(d, 0.0)
        gap = gap_return.get(d, 0.0)

        if pd.isna(ret):
            continue

        # Surprise proxy: use the absolute daily return as magnitude,
        # sign determined by the gap direction (more reliable than close-to-close
        # because intraday reversal can mask the true surprise)
        if not pd.isna(gap) and abs(gap) > 0.005:
            # Use gap sign with close-to-close magnitude for robustness
            surprise = abs(ret) * np.sign(gap)
        else:
            surprise = ret

        records.append({
            'date': d,
            'surprise_proxy': float(surprise),
        })

    return pd.DataFrame(records)


def fetch_yfinance_earnings(symbol: str) -> pd.DataFrame:
    """
    Try to get earnings surprise data from yfinance.
    Returns DataFrame with [date, surprise_pct] or empty if unavailable.
    """
    try:
        ticker = yf.Ticker(symbol)

        # Try earnings_dates (has EPS Estimate and EPS Actual)
        ed = getattr(ticker, 'earnings_dates', None)
        if ed is not None and len(ed) > 0:
            records = []
            for idx, row in ed.iterrows():
                actual = row.get('Reported EPS')
                estimate = row.get('EPS Estimate')
                if pd.notna(actual) and pd.notna(estimate) and estimate != 0:
                    surprise_pct = (actual - estimate) / abs(estimate)
                    dt = idx if isinstance(idx, pd.Timestamp) else pd.Timestamp(idx)
                    records.append({
                        'date': dt.normalize(),
                        'surprise_pct': float(surprise_pct),
                    })
            if records:
                return pd.DataFrame(records)

    except Exception as e:
        logger.debug(f"yfinance earnings failed for {symbol}: {e}")

    return pd.DataFrame(columns=['date', 'surprise_pct'])


def build_earnings_surprises(
    price_data: Dict[str, pd.DataFrame],
    symbols: List[str],
    force_refresh: bool = False
) -> Dict[str, pd.DataFrame]:
    """
    Build earnings surprise dataset for all symbols.

    Returns dict: symbol -> DataFrame with columns [date, surprise_pct]
    where surprise_pct is the earnings surprise as a fraction
    (e.g., 0.10 = beat by 10%, -0.05 = missed by 5%).

    Uses yfinance for recent data and price-reaction proxy for history.

    Note: Uses pickle for caching, consistent with the rest of the HYDRA
    data pipeline (broad_pool, SPY, EFA caches all use pickle).
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    if not force_refresh and os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, 'rb') as f:
            cached = pickle.load(f)
        # Check if we have data for most symbols
        cached_symbols = set(cached.keys())
        needed = set(symbols)
        if len(needed - cached_symbols) < len(needed) * 0.1:
            logger.info(f"Loaded earnings cache: {len(cached)} symbols")
            return cached

    print(f"\nBuilding earnings surprise data for {len(symbols)} symbols...")
    all_earnings = {}

    for i, symbol in enumerate(symbols):
        if (i + 1) % 20 == 0:
            print(f"  Processing {i+1}/{len(symbols)}...")

        # Step 1: Get yfinance earnings (recent quarters)
        yf_data = fetch_yfinance_earnings(symbol)
        yf_dates = set()
        if len(yf_data) > 0:
            yf_dates = set(yf_data['date'].dt.normalize())

        # Step 2: Get price-reaction proxy (full history)
        if symbol in price_data:
            proxy_data = detect_earnings_dates_from_price(price_data[symbol])
        else:
            proxy_data = pd.DataFrame(columns=['date', 'surprise_proxy'])

        # Step 3: Merge — prefer yfinance actuals, fill gaps with proxy
        records = []

        # Add yfinance actuals
        for _, row in yf_data.iterrows():
            records.append({
                'date': pd.Timestamp(row['date']).normalize(),
                'surprise_pct': row['surprise_pct'],
                'source': 'yfinance',
            })

        # Add proxy for dates not covered by yfinance
        for _, row in proxy_data.iterrows():
            proxy_date = pd.Timestamp(row['date']).normalize()
            # Check if we already have yfinance data within +/-5 days
            too_close = any(abs((proxy_date - yd).days) <= 5 for yd in yf_dates)
            if not too_close:
                # Scale proxy: typical daily return on earnings day is ~3-5%
                # but actual EPS surprise is ~5-15% of estimate
                # Use a 2x multiplier as rough calibration
                surprise = float(row['surprise_proxy']) * 2.0
                # Clip to reasonable range
                surprise = np.clip(surprise, -0.50, 0.50)
                records.append({
                    'date': proxy_date,
                    'surprise_pct': surprise,
                    'source': 'proxy',
                })

        if records:
            df = pd.DataFrame(records).sort_values('date').reset_index(drop=True)
            all_earnings[symbol] = df
        else:
            all_earnings[symbol] = pd.DataFrame(columns=['date', 'surprise_pct', 'source'])

    # Cache
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(all_earnings, f)
    print(f"  Cached earnings data: {len(all_earnings)} symbols -> {CACHE_FILE}")

    return all_earnings


def get_latest_surprise(
    symbol: str,
    current_date: pd.Timestamp,
    earnings_data: Dict[str, pd.DataFrame],
    max_age_days: int = 90
) -> Optional[Tuple[float, int]]:
    """
    Get the most recent earnings surprise for a symbol as of current_date.

    Returns (surprise_pct, days_since) or None if no earnings found within max_age_days.
    """
    if symbol not in earnings_data:
        return None

    df = earnings_data[symbol]
    if len(df) == 0:
        return None

    # Find most recent earnings BEFORE current_date
    mask = df['date'] <= current_date
    past = df[mask]
    if len(past) == 0:
        return None

    latest = past.iloc[-1]
    days_since = (current_date - latest['date']).days
    if days_since > max_age_days:
        return None

    return (float(latest['surprise_pct']), int(days_since))


def compute_earnings_booster(
    symbol: str,
    current_date: pd.Timestamp,
    earnings_data: Dict[str, pd.DataFrame],
    # Parameters
    sensitivity_pos: float = 2.5,
    sensitivity_neg: float = 4.0,
    half_life_days: float = 15.0,
    booster_floor: float = 0.50,
    booster_cap: float = 1.40,
    max_effect_days: int = 60,
) -> float:
    """
    Compute earnings momentum booster for a symbol.

    Returns a multiplier [booster_floor, booster_cap] to apply to the
    momentum score. 1.0 = neutral (no effect).

    Beats amplify the score, misses penalize it (asymmetrically).
    Effect decays exponentially with half_life_days.
    """
    result = get_latest_surprise(symbol, current_date, earnings_data, max_age_days=max_effect_days)
    if result is None:
        return 1.0

    surprise_pct, days_since = result

    # Exponential decay: exp(-ln(2)/half_life * days)
    decay_rate = np.log(2) / half_life_days
    decay = np.exp(-decay_rate * days_since)

    if surprise_pct > 0:
        booster = 1.0 + sensitivity_pos * surprise_pct * decay
    elif surprise_pct < 0:
        booster = 1.0 + sensitivity_neg * surprise_pct * decay  # negative * positive = penalty
    else:
        booster = 1.0

    return float(np.clip(booster, booster_floor, booster_cap))


if __name__ == '__main__':
    # Quick test with a single stock
    print("Testing earnings data module...")

    ticker = yf.Ticker('AAPL')
    hist = ticker.history(period='5y')
    price_data = {'AAPL': hist}

    earnings = build_earnings_surprises(price_data, ['AAPL'], force_refresh=True)

    if 'AAPL' in earnings and len(earnings['AAPL']) > 0:
        print(f"\nAAPL earnings events: {len(earnings['AAPL'])}")
        print(earnings['AAPL'].tail(10))

        # Test booster computation
        today = pd.Timestamp.now().normalize()
        booster = compute_earnings_booster('AAPL', today, earnings)
        print(f"\nAAPL booster today: {booster:.3f}")
    else:
        print("No earnings data found for AAPL")
