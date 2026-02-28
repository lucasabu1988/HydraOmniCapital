"""
EXPERIMENT 42 (FIXED): COMPASS v8.3 '666 FRAMEWORK' BACKTEST

Mathematics PhD forum recommendations (Tier 1):
  1. Lookback period: 90d -> 666 trading days (~2.6 years)
  2. Stock selection: 40 -> 66 stocks
  3. Sector constraint: Maximum 11 stocks per GICS sector
  4. Rebalancing: 5-day hold -> 6.66% drift threshold

BUGS FIXED:
  - Universe now selects top-66 (not top-40)
  - Rebalance condition changed from strict to graceful
  - Allows partial fills if <66 stocks available

Period: 1996-2026 (30 years)
Baseline: Exp41 v8.2 (11.31% CAGR, 0.528 Sharpe, -63.41% max DD)
"""

import pandas as pd
import numpy as np
import pickle
import os
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Tuple
import sys

# ============================================================================
# PARAMETERS
# ============================================================================

# v8.3 '666 Framework' parameters
TOP_N = 66  # Up from 40
MOMENTUM_LOOKBACK = 666  # Trading days (~2.6 years), up from 90
MOMENTUM_SKIP = 5
SECTOR_MAX = 11  # Maximum stocks per GICS sector
REBALANCE_DRIFT_PCT = 0.0666  # 6.66% drift threshold

# Position sizing
NUM_POSITIONS = 66  # Risk-on: 66 stocks
NUM_POSITIONS_RISK_OFF = 11  # Risk-off: 11 stocks (1/6 of 66, keeping theme)

# Risk management (unchanged from v8.2)
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03
PORTFOLIO_STOP_LOSS = -0.15
PROTECTION_RECOVERY_THRESHOLD_S1 = 63  # days
PROTECTION_RECOVERY_THRESHOLD_S2 = 126  # days

# Costs
COMMISSION_PER_SHARE = 0.001
MARGIN_RATE = 0.02
CASH_YIELD_RATE = 0.04

# Data
START_DATE = '1996-01-02'
END_DATE = '2027-01-01'

print("=" * 80)
print("EXPERIMENT 42 (FIXED): COMPASS v8.3 '666 FRAMEWORK' BACKTEST")
print("=" * 80)
print(f"\nImplementing mathematics PhD forum Tier 1 recommendations:")
print(f"  1. Lookback period: 90d -> {MOMENTUM_LOOKBACK} trading days (~{MOMENTUM_LOOKBACK/252:.1f} years)")
print(f"  2. Stock selection: 40 -> {TOP_N} stocks")
print(f"  3. Sector constraint: Maximum {SECTOR_MAX} stocks per GICS sector")
print(f"  4. Rebalancing: 5-day hold -> {REBALANCE_DRIFT_PCT:.2%} drift threshold")
print(f"\nBaseline (Exp41 v8.2): 11.31% CAGR, Sharpe 0.528, -63.41% max DD")
print(f"Period: {START_DATE} to 2026 (30 years)")
print()

# ============================================================================
# DATA FUNCTIONS (Import from Exp41)
# ============================================================================

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from exp41_extended_1996 import (
    download_sp500_constituents_history,
    build_point_in_time_universe,
    download_expanded_pool,
    filter_anomalous_stocks,
    download_spy,
    download_cash_yield
)

def compute_market_regime(spy_data: pd.DataFrame) -> pd.Series:
    """
    Compute market regime (RISK_ON vs RISK_OFF).
    RISK_ON = SPY > SMA200
    RISK_OFF = SPY <= SMA200
    """
    spy_data = spy_data.copy()
    spy_data['SMA200'] = spy_data['Close'].rolling(window=200).mean()
    regime = spy_data['Close'] > spy_data['SMA200']
    return regime

# ============================================================================
# GICS SECTOR DOWNLOAD
# ============================================================================

def download_gics_sectors(expanded_data: Dict[str, pd.DataFrame],
                         constituents_history: pd.DataFrame) -> Dict[str, str]:
    """
    Download GICS sector classifications for all tickers.

    Sources:
    1. Wikipedia S&P 500 list (current stocks)
    2. yfinance ticker.info['sector'] (fill gaps)
    3. Manual mappings for known bankruptcies

    Returns:
        Dict mapping ticker -> GICS sector name
    """
    import requests
    import yfinance as yf

    sectors = {}

    print("[Download] Downloading GICS sector classifications...")

    # Try Wikipedia
    try:
        print("  Trying Wikipedia S&P 500 list...")
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        tables = pd.read_html(url)
        sp500_table = tables[0]
        for _, row in sp500_table.iterrows():
            ticker = row['Symbol']
            sector = row['GICS Sector']
            sectors[ticker] = sector
        print(f"  [OK] Downloaded {len(sectors)} sectors from Wikipedia")
    except Exception as e:
        print(f"  [FAIL] Wikipedia failed: {e}")

    # Fill gaps with yfinance
    print("  Filling gaps with yfinance...")
    all_tickers = set(expanded_data.keys())
    missing = all_tickers - set(sectors.keys())

    filled_count = 0
    for ticker in missing:
        try:
            info = yf.Ticker(ticker).info
            if 'sector' in info and info['sector']:
                sectors[ticker] = info['sector']
                filled_count += 1
                if filled_count % 20 == 0:
                    print(f"    Filled {filled_count} sectors via yfinance...")
        except:
            pass

    if filled_count > 0:
        print(f"  [OK] Filled {filled_count} additional sectors via yfinance")

    # Manual mappings for bankruptcies
    manual_sectors = {
        'LEH': 'Financials',
        'BSC': 'Financials',
        'WM': 'Financials',
        'WCOM': 'Communication Services',
        'ENE': 'Energy',
        'CFC': 'Financials'
    }
    sectors.update(manual_sectors)

    print(f"\n[Download] Total sectors mapped: {len(sectors)} tickers")

    # Show distribution
    from collections import Counter
    sector_counts = Counter(sectors.values())
    print("\n  Sector distribution:")
    for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1]):
        print(f"    {sector}: {count}")

    return sectors


# ============================================================================
# ANNUAL UNIVERSE (TOP-66, NOT TOP-40)
# ============================================================================

def compute_annual_top66(expanded_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    """
    Compute annual top-66 stocks by dollar volume.

    This replaces compute_annual_top40_corrected from Exp41.
    """
    print("\nComputing annual top-66 rotation (by dollar volume)...")

    annual_universe = {}

    for year in range(1996, 2027):
        year_start = pd.Timestamp(f"{year}-01-01")
        year_end = pd.Timestamp(f"{year}-12-31")

        # Compute average daily dollar volume for each stock
        volumes = {}
        for ticker, df in expanded_data.items():
            # Filter to year
            df_year = df[(df.index >= year_start) & (df.index <= year_end)]
            if len(df_year) < 50:  # Require at least 50 days of data
                continue

            # Dollar volume = Close * Volume
            if 'Close' in df_year.columns and 'Volume' in df_year.columns:
                dollar_vol = (df_year['Close'] * df_year['Volume']).mean()
                if dollar_vol > 0:
                    volumes[ticker] = dollar_vol

        # Select top 66 by volume
        if len(volumes) >= 66:
            sorted_tickers = sorted(volumes.items(), key=lambda x: -x[1])
            top66 = [t[0] for t in sorted_tickers[:66]]
        else:
            # If < 66 available, take all
            top66 = list(volumes.keys())

        annual_universe[year] = top66

        # Log changes
        if year > 1996:
            prev = set(annual_universe[year - 1])
            curr = set(top66)
            added = len(curr - prev)
            removed = len(prev - curr)
            print(f"  {year}: Top-{len(top66)} | +{added} added, -{removed} removed")
        else:
            print(f"  {year}: Initial top-{len(top66)} = {len(top66)} stocks")

    return annual_universe


# ============================================================================
# MOMENTUM SCORING (666-day)
# ============================================================================

def compute_momentum_scores_666(price_data: Dict[str, pd.DataFrame],
                                tradeable_symbols: List[str],
                                current_date: pd.Timestamp,
                                all_dates: List[pd.Timestamp],
                                current_idx: int) -> Dict[str, float]:
    """
    Compute 666-day momentum scores with adaptive fallback.

    In early period (1996-1998), not enough history for 666 days.
    Use adaptive lookback with floor at 180 days.
    """
    scores = {}

    for symbol in tradeable_symbols:
        if symbol not in price_data:
            continue

        df = price_data[symbol]

        # Normalize date
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df_norm = df.copy()
            df_norm.index = df_norm.index.tz_localize(None)
        else:
            df_norm = df

        date_norm = current_date.tz_localize(None) if hasattr(current_date, 'tz') and current_date.tz else current_date

        if date_norm not in df_norm.index:
            continue

        sym_idx = list(df_norm.index).index(date_norm)

        # Adaptive lookback
        if sym_idx < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
            adaptive_lookback = min(sym_idx - MOMENTUM_SKIP, MOMENTUM_LOOKBACK)
            if adaptive_lookback < 180:  # Floor at 180 days (old v8.2 lookback)
                continue
            lookback_actual = adaptive_lookback
        else:
            lookback_actual = MOMENTUM_LOOKBACK

        # Skip recent 5 days
        if sym_idx < MOMENTUM_SKIP:
            continue

        try:
            current_price = df_norm.iloc[sym_idx]['Close']
            past_price = df_norm.iloc[sym_idx - lookback_actual]['Close']
            skip_price = df_norm.iloc[sym_idx - MOMENTUM_SKIP]['Close']

            if past_price > 0 and skip_price > 0:
                momentum = (skip_price / past_price) - 1.0
                scores[symbol] = momentum
        except:
            continue

    return scores


# ============================================================================
# SECTOR-CONSTRAINED SELECTION
# ============================================================================

def select_stocks_with_sector_constraint(momentum_scores: Dict[str, float],
                                        gics_sectors: Dict[str, str],
                                        target_count: int,
                                        sector_max: int) -> List[str]:
    """
    Select stocks with sector constraint: max `sector_max` per GICS sector.

    Algorithm:
    1. Rank all stocks by momentum
    2. Iterate from best to worst
    3. Add stock if its sector has < sector_max stocks
    4. Stop when we have `target_count` stocks or run out
    """
    # Rank by momentum
    ranked = sorted(momentum_scores.items(), key=lambda x: -x[1])

    selected = []
    sector_counts = defaultdict(int)

    for ticker, score in ranked:
        # Get sector (default to 'Unknown' if missing)
        sector = gics_sectors.get(ticker, 'Unknown')

        # Check constraint
        if sector_counts[sector] < sector_max:
            selected.append(ticker)
            sector_counts[sector] += 1

        # Stop if we have enough
        if len(selected) >= target_count:
            break

    return selected


# ============================================================================
# POSITION MANAGEMENT
# ============================================================================

def compute_equal_weights(selected: List[str]) -> Dict[str, float]:
    """Compute equal weights for selected stocks"""
    n = len(selected)
    if n == 0:
        return {}
    return {ticker: 1.0 / n for ticker in selected}


def check_rebalance_needed(positions: Dict[str, Dict],
                          price_data: Dict[str, pd.DataFrame],
                          date: pd.Timestamp,
                          target_weights: Dict[str, float],
                          portfolio_value: float) -> bool:
    """
    Check if rebalancing is needed based on drift threshold.
    """
    if not positions or portfolio_value <= 0:
        return False

    date_norm = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

    for symbol, pos in positions.items():
        if symbol not in price_data:
            continue

        df = price_data[symbol]
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df_norm = df.copy()
            df_norm.index = df_norm.index.tz_localize(None)
        else:
            df_norm = df

        if date_norm not in df_norm.index:
            continue

        current_price = df_norm.loc[date_norm, 'Close']
        position_value = pos['shares'] * current_price
        current_weight = position_value / portfolio_value

        target_weight = target_weights.get(symbol, 0)
        if target_weight == 0:
            return True  # Position should be closed

        # Check drift
        relative_drift = abs(current_weight - target_weight) / target_weight
        if relative_drift > REBALANCE_DRIFT_PCT:
            return True

    return False


def compute_dynamic_leverage(spy_data: pd.DataFrame, date: pd.Timestamp) -> float:
    """
    Compute dynamic leverage based on volatility.
    For now, use 1.0× (no leverage) to keep it simple.
    """
    return 1.0


# ============================================================================
# MAIN BACKTEST
# ============================================================================

def main():
    # ------------------------------------------------------------------------
    # STEP 1: LOAD HISTORICAL DATA
    # ------------------------------------------------------------------------
    print("=" * 80)
    print("STEP 1: LOAD HISTORICAL DATA (FROM EXP41 CACHE)")
    print("=" * 80)

    constituents_history = download_sp500_constituents_history()
    point_in_time_universe = build_point_in_time_universe(constituents_history, START_DATE, END_DATE)
    expanded_data = download_expanded_pool(point_in_time_universe)
    expanded_data = filter_anomalous_stocks(expanded_data)
    spy_data = download_spy()
    cash_yield_daily = download_cash_yield()

    # ------------------------------------------------------------------------
    # STEP 2: DOWNLOAD GICS SECTOR DATA
    # ------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 2: DOWNLOAD GICS SECTOR DATA")
    print("=" * 80)

    gics_sectors = download_gics_sectors(expanded_data, constituents_history)

    # ------------------------------------------------------------------------
    # STEP 3: COMPUTE ANNUAL TOP-66 UNIVERSE
    # ------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 3: COMPUTE ANNUAL TOP-66 UNIVERSE")
    print("=" * 80)

    annual_universe_v83 = compute_annual_top66(expanded_data)

    # ------------------------------------------------------------------------
    # STEP 4: RUN BACKTEST
    # ------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 4: RUN COMPASS v8.3 '666 FRAMEWORK' BACKTEST")
    print("=" * 80)

    # Compute regime
    regime = compute_market_regime(spy_data)

    # Initialize
    cash = 100000.0
    positions = {}
    target_weights = {}
    trades = []
    daily_results = []
    rebalance_events = []

    in_protection_mode = False
    protection_stage = 1
    stop_loss_day_index = 0

    total_commissions = 0.0
    risk_on_days = 0
    risk_off_days = 0

    # Get all trading dates
    all_dates = sorted(set([
        d for df in expanded_data.values()
        for d in df.index
        if d >= pd.Timestamp(START_DATE) and d < pd.Timestamp(END_DATE)
    ]))

    print("\n" + "=" * 80)
    print("RUNNING COMPASS v8.3 '666 FRAMEWORK' BACKTEST")
    print("=" * 80)
    print(f"\nComputing market regime (SPY vs SMA200)...")
    print(f"Period: {START_DATE} to 2026-02-27")
    print(f"Trading days: {len(all_dates)}")
    print(f"Universe: Top-{TOP_N} stocks, max {SECTOR_MAX} per sector")
    print(f"Rebalancing: {REBALANCE_DRIFT_PCT:.2%} drift threshold")

    for i, date in enumerate(all_dates):
        # Get tradeable universe for current year
        year = date.year
        tradeable_symbols = annual_universe_v83.get(year, [])

        # Portfolio value
        portfolio_value = cash
        for symbol, pos in positions.items():
            if symbol in expanded_data:
                df = expanded_data[symbol]
                if hasattr(df.index, 'tz') and df.index.tz is not None:
                    df_norm = df.copy()
                    df_norm.index = df_norm.index.tz_localize(None)
                else:
                    df_norm = df

                date_norm = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

                if date_norm in df_norm.index:
                    current_price = df_norm.loc[date_norm, 'Close']
                    portfolio_value += pos['shares'] * current_price

        # Daily results
        daily_results.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions)
        })

        # Progress every year
        days_in_year = 252
        if i % days_in_year == 0 and i > 0:
            years_elapsed = i / days_in_year
            dd = 0.0
            print(f"  [{date.date()}] Year {years_elapsed:.1f} | Value: ${portfolio_value:,.0f} | Positions: {len(positions)} | DD: {dd:.1f}%")

        # Portfolio stop
        peak_value = max([r['value'] for r in daily_results])
        drawdown = (portfolio_value / peak_value - 1) if peak_value > 0 else 0

        if drawdown <= PORTFOLIO_STOP_LOSS:
            # Close all positions
            for symbol in list(positions.keys()):
                if symbol in expanded_data:
                    df = expanded_data[symbol]
                    if hasattr(df.index, 'tz') and df.index.tz is not None:
                        df_norm = df.copy()
                        df_norm.index = df_norm.index.tz_localize(None)
                    else:
                        df_norm = df

                    date_norm = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

                    if date_norm in df_norm.index:
                        exit_price = df_norm.loc[date_norm, 'Close']
                        pos = positions[symbol]
                        proceeds = pos['shares'] * exit_price
                        commission = pos['shares'] * COMMISSION_PER_SHARE
                        total_commissions += commission
                        cash += proceeds - commission
                        pnl = (exit_price - pos['entry_price']) * pos['shares'] - commission
                        trades.append({
                            'symbol': symbol,
                            'entry_date': pos['entry_date'],
                            'exit_date': date,
                            'exit_reason': 'portfolio_stop',
                            'pnl': pnl,
                            'return': pnl / (pos['entry_price'] * pos['shares'])
                        })
                del positions[symbol]

            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i
            target_weights = {}

        # Regime
        regime_date = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date
        is_risk_on = True
        if regime_date in regime.index:
            is_risk_on = bool(regime.loc[regime_date])
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # Determine target positions and leverage
        if in_protection_mode:
            if protection_stage == 1:
                target_positions = 11
                current_leverage = 0.3
            else:
                target_positions = 33
                current_leverage = 1.0
        elif not is_risk_on:
            target_positions = NUM_POSITIONS_RISK_OFF  # 11
            current_leverage = 1.0
        else:
            target_positions = NUM_POSITIONS  # 66
            current_leverage = compute_dynamic_leverage(spy_data, date)

        # Daily costs
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # Cash yield
        if cash > 0:
            if cash_yield_daily is not None and regime_date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[regime_date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        # Position-level stops
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in expanded_data:
                continue

            df = expanded_data[symbol]
            if hasattr(df.index, 'tz') and df.index.tz is not None:
                df_norm = df.copy()
                df_norm.index = df_norm.index.tz_localize(None)
            else:
                df_norm = df

            date_norm = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

            if date_norm not in df_norm.index:
                continue

            current_price = df_norm.loc[date_norm, 'Close']
            exit_reason = None

            # Position stop loss
            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'

            # Trailing stop
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            # Universe rotation
            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                commission = shares * COMMISSION_PER_SHARE
                total_commissions += commission
                cash += proceeds - commission
                pnl = (current_price - pos['entry_price']) * shares - commission
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]
                if symbol in target_weights:
                    del target_weights[symbol]

        # Check drift-based rebalancing
        needs_rebalance = False

        # FIXED: More graceful condition
        # Rebalance if we have 0 positions OR position count mismatch (and enough stocks available)
        if len(positions) == 0 and len(tradeable_symbols) > 0:
            needs_rebalance = True
        elif len(positions) != target_positions and len(tradeable_symbols) >= target_positions // 2:
            needs_rebalance = True

        # Check drift for existing positions
        if not needs_rebalance and len(positions) > 0:
            needs_rebalance = check_rebalance_needed(positions, expanded_data, date,
                                                    target_weights, portfolio_value)

        # Rebalance if needed
        if needs_rebalance and cash > 1000 and len(tradeable_symbols) >= target_positions // 4:
            rebalance_events.append({
                'date': date,
                'reason': 'drift_threshold',
                'positions_before': len(positions),
                'portfolio_value': portfolio_value
            })

            # Close all positions
            for symbol in list(positions.keys()):
                if symbol in expanded_data:
                    df = expanded_data[symbol]
                    if hasattr(df.index, 'tz') and df.index.tz is not None:
                        df_norm = df.copy()
                        df_norm.index = df_norm.index.tz_localize(None)
                    else:
                        df_norm = df

                    date_norm = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

                    if date_norm in df_norm.index:
                        exit_price = df_norm.loc[date_norm, 'Close']
                        pos = positions[symbol]
                        proceeds = pos['shares'] * exit_price
                        commission = pos['shares'] * COMMISSION_PER_SHARE
                        total_commissions += commission
                        cash += proceeds - commission
                        pnl = (exit_price - pos['entry_price']) * pos['shares'] - commission
                        trades.append({
                            'symbol': symbol,
                            'entry_date': pos['entry_date'],
                            'exit_date': date,
                            'exit_reason': 'rebalance',
                            'pnl': pnl,
                            'return': pnl / (pos['entry_price'] * pos['shares'])
                        })
                del positions[symbol]

            positions = {}
            target_weights = {}

            # Open new positions
            # FIXED: More flexible - allow partial fills
            min_stocks = max(5, target_positions // 4)  # At least 5 stocks or 1/4 of target
            if len(tradeable_symbols) >= min_stocks:
                # Compute 666-day momentum scores
                scores = compute_momentum_scores_666(expanded_data, tradeable_symbols, date, all_dates, i)

                if len(scores) >= min_stocks:
                    # Select with sector constraint
                    selected = select_stocks_with_sector_constraint(
                        scores, gics_sectors, target_positions, SECTOR_MAX
                    )

                    if len(selected) > 0:
                        # Equal weights
                        target_weights = compute_equal_weights(selected)

                        # Effective capital
                        effective_capital = cash * current_leverage * 0.95

                        # Open positions
                        for symbol in selected:
                            if symbol not in expanded_data:
                                continue

                            df = expanded_data[symbol]
                            if hasattr(df.index, 'tz') and df.index.tz is not None:
                                df_norm = df.copy()
                                df_norm.index = df_norm.index.tz_localize(None)
                            else:
                                df_norm = df

                            date_norm = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

                            if date_norm not in df_norm.index:
                                continue

                            entry_price = df_norm.loc[date_norm, 'Close']
                            if entry_price <= 0:
                                continue

                            weight = target_weights[symbol]
                            position_value = effective_capital * weight
                            shares = position_value / entry_price
                            cost = shares * entry_price
                            commission = shares * COMMISSION_PER_SHARE

                            if cost + commission <= cash:
                                cash -= cost + commission
                                total_commissions += commission
                                positions[symbol] = {
                                    'shares': shares,
                                    'entry_price': entry_price,
                                    'entry_date': date,
                                    'high_price': entry_price
                                }

    # ------------------------------------------------------------------------
    # STEP 5: SAVE RESULTS
    # ------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("BACKTEST COMPLETE")
    print("=" * 80)

    final_value = daily_results[-1]['value']
    total_return = (final_value / 100000 - 1) * 100
    years = len(all_dates) / 252
    cagr = (final_value / 100000) ** (1 / years) - 1

    print(f"\nFinal Value: ${final_value:,.0f}")
    print(f"Total Return: {total_return:.2f}%")
    print(f"CAGR: {cagr * 100:.2f}%")
    print(f"Years: {years:.2f}")
    print(f"Total Trades: {len(trades)}")
    print(f"Total Commissions: ${total_commissions:,.2f}")
    print(f"Rebalance Events: {len(rebalance_events)}")
    print(f"Risk-On Days: {risk_on_days} ({risk_on_days/len(all_dates)*100:.1f}%)")
    print(f"Risk-Off Days: {risk_off_days} ({risk_off_days/len(all_dates)*100:.1f}%)")

    print("\n" + "=" * 80)
    print("STEP 5: SAVE RESULTS")
    print("=" * 80)

    # Save daily
    df_daily = pd.DataFrame(daily_results)
    df_daily.to_csv('backtests/exp42_compass_666_fixed_daily.csv', index=False)
    print("  Saved: backtests/exp42_compass_666_fixed_daily.csv")

    # Save trades
    df_trades = pd.DataFrame(trades)
    df_trades.to_csv('backtests/exp42_compass_666_fixed_trades.csv', index=False)
    print("  Saved: backtests/exp42_compass_666_fixed_trades.csv")

    # Save rebalances
    df_rebalances = pd.DataFrame(rebalance_events)
    df_rebalances.to_csv('backtests/exp42_compass_666_fixed_rebalances.csv', index=False)
    print("  Saved: backtests/exp42_compass_666_fixed_rebalances.csv")

    # ------------------------------------------------------------------------
    # STEP 6: COMPARE vs BASELINE
    # ------------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("STEP 6: COMPARE vs BASELINE (EXP41)")
    print("=" * 80)

    # Load baseline
    try:
        df_baseline = pd.read_csv('backtests/exp41_corrected_daily.csv')
        baseline_final = df_baseline['value'].iloc[-1]
        baseline_cagr = (baseline_final / 100000) ** (1 / 30) - 1

        print("\n" + "=" * 80)
        print("PERFORMANCE COMPARISON: v8.2 (Baseline) vs v8.3 (666 Framework)")
        print("=" * 80)

        print(f"\nMetric                         v8.2 (Exp41)         v8.3 (666)           Improvement")
        print("-" * 85)
        print(f"Final Value                    $ {baseline_final:>14,.0f} $ {final_value:>14,.0f} $ {final_value - baseline_final:>12,.0f}")
        print(f"CAGR                                   {baseline_cagr*100:>6.2f}%          {cagr*100:>6.2f}%      {(cagr - baseline_cagr)*100:>6.2f}%")
        print(f"Total Trades                           {6480:>6}             {len(trades):>6}       {len(trades) - 6480:>6}")
        print("-" * 85)

        if cagr > baseline_cagr:
            print(f"\nIMPROVEMENT: +{(cagr - baseline_cagr)*100:.2f}% CAGR")
            print(f"  The '666 Framework' outperformed v8.2 baseline by {(cagr - baseline_cagr)*100:.2f}% per year")
        else:
            print(f"\nREGRESSION: {(cagr - baseline_cagr)*100:.2f}% CAGR")
            print(f"  The '666 Framework' underperformed v8.2 baseline by {abs(cagr - baseline_cagr)*100:.2f}% per year")

        print("=" * 85)

    except Exception as e:
        print(f"[ERROR] Could not load baseline: {e}")


if __name__ == '__main__':
    main()
