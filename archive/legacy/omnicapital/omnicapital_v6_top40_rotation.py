"""
OmniCapital v6 - Top 40 Annual Rotation Backtest
=================================================
Identical to v6 final optimized but with PROPER annual rotation:
- Broad pool of ~100 S&P 500 stocks
- Each January 1st, rank by market cap proxy (avg daily dollar volume)
- Select only the TOP 40 as eligible universe for that year
- Stocks not in top-40 that year cannot be traded
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import random
import pickle
import os
from typing import Dict, List, Set, Tuple
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETROS (same as v6 final)
# ============================================================================

HOLD_MINUTES = 666
NUM_POSITIONS = 5
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
COMMISSION_PER_SHARE = 0.001
MIN_AGE_DAYS = 63

LEVERAGE = 2.0
MARGIN_RATE = 0.06
HEDGE_COST_PCT = 0.025
PORTFOLIO_STOP_LOSS = -0.20
RECOVERY_COOLDOWN_DAYS = 126   # ~6 months minimum cooldown
RECOVERY_GROWTH_PCT = 0.10     # Must grow 10% from post-stop-loss level before restoring leverage

TOP_N = 40  # Select top 40 by market cap each year

START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# Broad pool of S&P 500 constituents (historical large-caps)
# ~100 stocks that have been in S&P 500 at various points
BROAD_POOL = [
    # Technology
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'AMD',
    'INTC', 'CSCO', 'IBM', 'TXN', 'QCOM', 'ORCL', 'ACN', 'NOW', 'INTU',
    'AMAT', 'MU', 'LRCX', 'SNPS', 'CDNS', 'KLAC', 'MRVL',
    # Financials
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
    'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG',
    # Healthcare
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'AMGN', 'BMY', 'MDT', 'ISRG', 'SYK', 'GILD', 'REGN', 'VRTX', 'BIIB',
    # Consumer
    'AMZN', 'TSLA', 'WMT', 'HD', 'PG', 'COST', 'KO', 'PEP', 'NKE',
    'MCD', 'DIS', 'SBUX', 'TGT', 'LOW', 'CL', 'KMB', 'GIS', 'EL',
    'MO', 'PM',
    # Energy
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'PSX', 'VLO',
    # Industrials
    'GE', 'CAT', 'BA', 'HON', 'UNP', 'RTX', 'LMT', 'DE', 'UPS', 'FDX',
    'MMM', 'GD', 'NOC', 'EMR',
    # Utilities & Real Estate
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    # Telecom
    'VZ', 'T', 'TMUS', 'CMCSA',
]

print("=" * 80)
print("OMNICAPITAL v6 - TOP 40 ANNUAL ROTATION BACKTEST")
print("=" * 80)
print(f"\nBroad pool: {len(BROAD_POOL)} stocks")
print(f"Annual selection: Top {TOP_N} by market cap proxy")
print(f"Hold time: {HOLD_MINUTES} min | Stop loss: {abs(PORTFOLIO_STOP_LOSS):.0%} | Leverage: {LEVERAGE:.0f}:1")
print()


def download_broad_pool():
    """Download data for the broad pool of stocks"""
    cache_file = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading broad pool data...")
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            print("[Cache] Failed to load, re-downloading...")

    print(f"[Download] Downloading {len(BROAD_POOL)} symbols...")
    data = {}
    failed = []

    for i, symbol in enumerate(BROAD_POOL):
        try:
            df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[symbol] = df
                if (i + 1) % 20 == 0:
                    print(f"  [{i+1}/{len(BROAD_POOL)}] Downloaded {len(data)} symbols so far...")
            else:
                failed.append(symbol)
        except Exception as e:
            failed.append(symbol)

    print(f"[Download] {len(data)} symbols valid, {len(failed)} failed")
    if failed:
        print(f"  Failed: {failed}")

    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)

    return data


def compute_annual_top40(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    """
    For each year, compute the top-40 stocks by market cap proxy.

    Market cap proxy: average daily dollar volume (Close * Volume) over
    the prior 252 trading days. This correlates strongly with market cap
    and avoids look-ahead bias (uses only past data).
    """
    # Get all unique years
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))

    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}

    for year in years:
        # Use data from the prior year (or available history) to rank
        # For the first year, use first 30 days
        if year == years[0]:
            # First year: use all available stocks with data
            ranking_end = pd.Timestamp(f'{year}-02-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') else None)
        else:
            # Use prior year data to rank
            ranking_end = pd.Timestamp(f'{year}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') else None)

        scores = {}
        for symbol, df in price_data.items():
            # Filter to ranking window
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]

            if len(window) < 20:  # Need at least 20 days of data
                continue

            # Dollar volume = Close * Volume (proxy for market cap/liquidity)
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol

        # Rank and select top N
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_n = [s for s, _ in ranked[:TOP_N]]
        annual_universe[year] = top_n

        # Print rotation info
        if year > years[0] and year - 1 in annual_universe:
            prev = set(annual_universe[year - 1])
            curr = set(top_n)
            added = curr - prev
            removed = prev - curr
            if added or removed:
                print(f"  {year}: Top-40 updated | +{len(added)} added, -{len(removed)} removed | "
                      f"Added: {sorted(added)[:5]}{'...' if len(added) > 5 else ''}")
            else:
                print(f"  {year}: Top-40 unchanged")
        else:
            print(f"  {year}: Initial top-40 = {len(top_n)} stocks")

    return annual_universe


def get_tradeable_symbols(price_data: Dict[str, pd.DataFrame], date: pd.Timestamp,
                          first_date: pd.Timestamp, annual_universe: Dict[int, List[str]]) -> List[str]:
    """Return tradeable symbols - ONLY from the top-40 for that year"""
    year = date.year
    eligible = set(annual_universe.get(year, []))

    tradeable = []
    for symbol in eligible:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue

        symbol_first_date = df.index[0]
        days_since_start = (date - symbol_first_date).days

        if date <= first_date + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since_start >= MIN_AGE_DAYS:
            tradeable.append(symbol)

    return tradeable


def minutes_held(entry_date: pd.Timestamp, current_date: pd.Timestamp) -> int:
    return (current_date - entry_date).days * 390


def run_backtest(price_data: Dict[str, pd.DataFrame], annual_universe: Dict[int, List[str]]) -> Dict:
    """Run backtest with annual top-40 rotation"""

    print("\n" + "=" * 80)
    print("RUNNING BACKTEST WITH ANNUAL TOP-40 ROTATION")
    print("=" * 80)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

    equity = INITIAL_CAPITAL
    borrowed = INITIAL_CAPITAL * (LEVERAGE - 1)
    total_capital = equity + borrowed
    cash = total_capital

    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []

    current_leverage = LEVERAGE
    peak_value = total_capital
    in_protection_mode = False
    stop_loss_day_index = None  # Track when stop loss was triggered
    post_stop_base = None       # Portfolio value right after stop loss

    daily_margin_cost = MARGIN_RATE / 252 * borrowed
    daily_hedge_cost = HEDGE_COST_PCT / 252 * total_capital

    current_year = None
    current_eligible = []

    for i, date in enumerate(all_dates):
        # Check for annual rotation
        if date.year != current_year:
            current_year = date.year
            current_eligible = annual_universe.get(current_year, [])

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # Calculate portfolio value
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # Update peak
        if portfolio_value > peak_value:
            peak_value = portfolio_value

        # Check recovery from protection mode
        # Require BOTH: minimum cooldown AND portfolio growth from post-stop base
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            growth_from_base = (portfolio_value - post_stop_base) / post_stop_base if post_stop_base > 0 else 0
            if days_since_stop >= RECOVERY_COOLDOWN_DAYS and growth_from_base >= RECOVERY_GROWTH_PCT:
                in_protection_mode = False
                current_leverage = LEVERAGE
                # Reset peak to current value (rolling peak) so we track DD from here
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None
                print(f"  [RECOVERY] {date.strftime('%Y-%m-%d')}: Leverage restored to {LEVERAGE:.0f}x | "
                      f"Growth: {growth_from_base:.1%} | New peak: ${portfolio_value:,.0f}")

        drawdown = (portfolio_value - peak_value) / peak_value

        # STOP LOSS
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({
                'date': date,
                'portfolio_value': portfolio_value,
                'drawdown': drawdown
            })
            print(f"\n  [STOP LOSS] {date.strftime('%Y-%m-%d')}: DD {drawdown:.1%} | Value: ${portfolio_value:,.0f}")

            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    cash += positions[symbol]['shares'] * exit_price
                del positions[symbol]

            current_leverage = 1.0
            in_protection_mode = True
            stop_loss_day_index = i
            # Record base value after closing all positions
            post_stop_base = cash  # all in cash now

        # Daily costs (only when using leverage)
        if not in_protection_mode:
            current_borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * current_borrowed
            daily_hedge = HEDGE_COST_PCT / 252 * portfolio_value
            cash -= (daily_margin + daily_hedge)

        # Close expired positions
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if minutes_held(pos['entry_date'], date) >= HOLD_MINUTES:
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    shares = pos['shares']
                    proceeds = shares * exit_price
                    commission = shares * COMMISSION_PER_SHARE
                    cash += proceeds - commission

                    pnl = (exit_price - pos['entry_price']) * shares - commission
                    trades.append({
                        'symbol': symbol,
                        'entry_date': pos['entry_date'],
                        'exit_date': date,
                        'pnl': pnl,
                        'return': pnl / (pos['entry_price'] * shares)
                    })
                del positions[symbol]

        # Close positions NOT in current year's top-40
        for symbol in list(positions.keys()):
            if symbol not in tradeable_symbols:
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    shares = positions[symbol]['shares']
                    proceeds = shares * exit_price
                    commission = shares * COMMISSION_PER_SHARE
                    cash += proceeds - commission

                    pnl = (exit_price - positions[symbol]['entry_price']) * shares - commission
                    trades.append({
                        'symbol': symbol,
                        'entry_date': positions[symbol]['entry_date'],
                        'exit_date': date,
                        'pnl': pnl,
                        'return': pnl / (positions[symbol]['entry_price'] * shares)
                    })
                del positions[symbol]

        # Open new positions
        needed = NUM_POSITIONS - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= needed:
            available_for_entry = [s for s in tradeable_symbols if s not in positions]

            if len(available_for_entry) >= needed:
                random.seed(RANDOM_SEED + date.toordinal())
                selected = random.sample(available_for_entry, needed)

                effective_capital = cash * current_leverage
                position_value = (effective_capital * 0.95) / NUM_POSITIONS

                for symbol in selected:
                    if symbol in price_data and date in price_data[symbol].index:
                        entry_price = price_data[symbol].loc[date, 'Close']
                        shares = position_value / entry_price
                        cost = shares * entry_price
                        commission = shares * COMMISSION_PER_SHARE

                        if cost + commission <= cash * 0.95:
                            positions[symbol] = {
                                'entry_price': entry_price,
                                'shares': shares,
                                'entry_date': date
                            }
                            cash -= cost + commission

        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
            'in_protection': in_protection_mode,
            'universe_size': len(tradeable_symbols)
        })

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            current_borrowed = portfolio_value * (current_leverage - 1) / current_leverage if current_leverage > 1 else 0
            equity_value = portfolio_value - current_borrowed
            status = "[PROTECTION]" if in_protection_mode else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | Equity: ${equity_value:,.0f} | "
                  f"DD: {drawdown:.1%} | Lev: {current_leverage:.1f}x | "
                  f"Universe: {len(tradeable_symbols)} {status}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'],
        'annual_universe': annual_universe
    }


def calculate_metrics(results: Dict) -> Dict:
    """Calculate performance metrics"""
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']
    stop_df = results['stop_events']

    initial = INITIAL_CAPITAL
    final_value = df['value'].iloc[-1]
    final_leverage = df['leverage'].iloc[-1]
    final_borrowed = final_value * (final_leverage - 1) / final_leverage if final_leverage > 1 else 0
    final_equity = final_value - final_borrowed

    years = len(df) / 252
    cagr = (final_equity / initial) ** (1/years) - 1

    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)

    max_dd = df['drawdown'].min()

    sharpe = cagr / volatility if volatility > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0

    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100

    # Rotation stats
    annual_u = results.get('annual_universe', {})
    years_list = sorted(annual_u.keys())
    total_rotations = 0
    for i in range(1, len(years_list)):
        prev = set(annual_u[years_list[i-1]])
        curr = set(annual_u[years_list[i]])
        total_rotations += len(curr - prev)

    return {
        'initial': initial,
        'final_value': final_value,
        'final_equity': final_equity,
        'total_return': (final_equity - initial) / initial,
        'years': years,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'avg_trade': avg_trade,
        'trades': len(trades_df),
        'stop_events': len(stop_df),
        'protection_days': protection_days,
        'protection_pct': protection_pct,
        'total_rotations': total_rotations,
        'avg_rotations_per_year': total_rotations / max(1, len(years_list) - 1)
    }


def print_rotation_analysis(annual_universe: Dict[int, List[str]]):
    """Print detailed rotation analysis"""
    print("\n" + "=" * 80)
    print("ANNUAL ROTATION ANALYSIS")
    print("=" * 80)

    years = sorted(annual_universe.keys())
    all_unique = set()

    for year in years:
        stocks = annual_universe[year]
        all_unique.update(stocks)

    print(f"\nTotal unique stocks used across all years: {len(all_unique)}")
    print(f"Years covered: {years[0]} - {years[-1]}")

    for i, year in enumerate(years):
        curr = set(annual_universe[year])
        if i > 0:
            prev = set(annual_universe[years[i-1]])
            added = sorted(curr - prev)
            removed = sorted(prev - curr)
            retained = len(curr & prev)
            print(f"\n  {year}: {len(curr)} stocks | "
                  f"Retained: {retained} | Added: {len(added)} | Removed: {len(removed)}")
            if added:
                print(f"    + {added}")
            if removed:
                print(f"    - {removed}")
        else:
            print(f"\n  {year}: {len(curr)} stocks (initial)")
            print(f"    {sorted(curr)}")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # Download/load data
    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")

    # Compute annual top-40
    print("\n--- Computing Annual Top-40 ---")
    annual_universe = compute_annual_top40(price_data)

    # Print rotation analysis
    print_rotation_analysis(annual_universe)

    # Run backtest
    results = run_backtest(price_data, annual_universe)

    # Calculate metrics
    metrics = calculate_metrics(results)

    # Print results
    print("\n" + "=" * 80)
    print("RESULTS - OMNICAPITAL v6 WITH TOP-40 ANNUAL ROTATION")
    print("=" * 80)
    print(f"\nInitial capital:        ${metrics['initial']:>15,.0f}")
    print(f"Final value (total):    ${metrics['final_value']:>15,.2f}")
    print(f"Final equity (net):     ${metrics['final_equity']:>15,.2f}")
    print(f"Total return:           {metrics['total_return']:>15.2%}")
    print(f"CAGR:                   {metrics['cagr']:>15.2%}")
    print(f"Volatility (annual):    {metrics['volatility']:>15.2%}")
    print(f"Sharpe ratio:           {metrics['sharpe']:>15.2f}")
    print(f"Calmar ratio:           {metrics['calmar']:>15.2f}")
    print(f"Max drawdown:           {metrics['max_drawdown']:>15.2%}")

    print(f"\nTrading days:           {len(results['portfolio_values']):>15,}")
    print(f"Years:                  {metrics['years']:>15.2f}")

    if metrics['trades'] > 0:
        print(f"\nTrades executed:        {metrics['trades']:>15,}")
        print(f"Win rate:               {metrics['win_rate']:>15.2%}")
        print(f"Avg P&L per trade:      ${metrics['avg_trade']:>15,.2f}")

    if metrics['stop_events'] > 0:
        print(f"\nStop loss events:       {metrics['stop_events']:>15,}")
        print(f"Days in protection:     {metrics['protection_days']:>15,} ({metrics['protection_pct']:.1f}%)")

    print(f"\n--- Rotation Stats ---")
    print(f"Total stock rotations:  {metrics['total_rotations']:>15,}")
    print(f"Avg rotations/year:     {metrics['avg_rotations_per_year']:>15.1f}")

    # Save results
    output_file = 'results_v6_top40_rotation.pkl'
    with open(output_file, 'wb') as f:
        pickle.dump({
            'params': {
                'hold_minutes': HOLD_MINUTES,
                'stop_loss': PORTFOLIO_STOP_LOSS,
                'leverage': LEVERAGE,
                'num_positions': NUM_POSITIONS,
                'top_n': TOP_N,
                'broad_pool_size': len(BROAD_POOL),
            },
            'metrics': metrics,
            'portfolio_values': results['portfolio_values'],
            'trades': results['trades'],
            'stop_events': results['stop_events'],
            'annual_universe': results['annual_universe']
        }, f)

    # Save daily results CSV
    results['portfolio_values'].to_csv('backtests/v6_top40_rotation_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/v6_top40_rotation_trades.csv', index=False)

    print(f"\nResults saved: {output_file}")
    print(f"Daily CSV: backtests/v6_top40_rotation_daily.csv")

    print("\n" + "=" * 80)
    print("EXECUTIVE SUMMARY")
    print("=" * 80)
    print(f"\nOmniCapital v6 with Top-40 Annual Rotation:")
    print(f"  CAGR: {metrics['cagr']:.2%} (${metrics['initial']:,.0f} -> ${metrics['final_equity']:,.0f} in {metrics['years']:.0f} years)")
    print(f"  Sharpe: {metrics['sharpe']:.2f} | Max DD: {metrics['max_drawdown']:.1%}")
    print(f"  Annual rotation: {metrics['avg_rotations_per_year']:.1f} stocks change per year on average")
    print("=" * 80)
