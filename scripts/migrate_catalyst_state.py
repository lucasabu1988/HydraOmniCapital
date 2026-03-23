"""Migrate state files: recalculate Catalyst positions as if EXP71 config
(15% trend, 0% permanent gold, +ZROZ) had been active from the start.

Steps:
1. Download historical data for TLT, ZROZ, GLD, DBC
2. Check which were above SMA200 on entry date (2026-03-16)
3. Recalculate equal-weight allocation across qualifying assets
4. Compute delta (shares to add/remove, cash adjustment)
5. Update all state snapshots + latest + cycle log
"""
import json
import os
import sys
from copy import deepcopy
from datetime import datetime

import pandas as pd
import yfinance as yf

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'state')
CATALYST_BUDGET = 15000.0
ENTRY_DATE = '2026-03-16'
NEW_TREND_ASSETS = ['TLT', 'ZROZ', 'GLD', 'DBC']
SMA_PERIOD = 200

# Fix Windows encoding
if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')


def download_and_check_sma(ticker, as_of_date):
    """Download history and check if ticker was above SMA200 on entry date."""
    df = yf.download(ticker, start='2025-01-01', end='2026-03-25', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df[['Close']].dropna()

    as_of = pd.Timestamp(as_of_date)
    # Find the closest trading day on or before as_of_date
    valid_dates = df.index[df.index <= as_of]
    if len(valid_dates) == 0:
        return None, False, 0.0

    check_date = valid_dates[-1]
    if len(df.loc[:check_date]) < SMA_PERIOD:
        # Not enough data — download more
        df2 = yf.download(ticker, start='2024-01-01', end='2026-03-25', progress=False)
        if isinstance(df2.columns, pd.MultiIndex):
            df2.columns = df2.columns.get_level_values(0)
        df2.index = pd.to_datetime(df2.index).tz_localize(None)
        df2 = df2[['Close']].dropna()
        df = df2

    valid_dates = df.index[df.index <= as_of]
    check_date = valid_dates[-1]
    close = float(df.loc[check_date, 'Close'])
    sma = float(df['Close'].loc[:check_date].iloc[-SMA_PERIOD:].mean())
    above = close > sma

    return close, above, sma


def get_entry_price(ticker, as_of_date):
    """Get the close price on the entry date (for position sizing)."""
    df = yf.download(ticker, start='2026-03-10', end='2026-03-20', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    as_of = pd.Timestamp(as_of_date)
    valid = df.index[df.index <= as_of]
    if len(valid) == 0:
        return None
    return float(df.loc[valid[-1], 'Close'])


def get_current_prices(tickers, as_of_date):
    """Get close prices for a specific date."""
    prices = {}
    for t in tickers:
        p = get_entry_price(t, as_of_date)
        if p and p > 0:
            prices[t] = p
    return prices


print("=" * 70)
print("CATALYST STATE MIGRATION — EXP71 CONFIG")
print("=" * 70)

# Step 1: Check SMA200 status for all new trend assets on entry date
print(f"\nChecking SMA200 status on {ENTRY_DATE}...")
qualifying = []
asset_info = {}
for ticker in NEW_TREND_ASSETS:
    close, above, sma = download_and_check_sma(ticker, ENTRY_DATE)
    status = "ABOVE" if above else "BELOW"
    if above:
        qualifying.append(ticker)
    asset_info[ticker] = {'close': close, 'above': above, 'sma': sma}
    print(f"  {ticker}: close=${close:.2f}, SMA200=${sma:.2f} → {status}")

print(f"\nQualifying assets: {qualifying}")

# Step 2: Calculate new position sizes
print(f"\nCalculating new allocations (budget=${CATALYST_BUDGET:,.0f})...")
entry_prices = {}
for ticker in qualifying:
    price = get_entry_price(ticker, ENTRY_DATE)
    entry_prices[ticker] = price
    print(f"  {ticker} entry price: ${price:.2f}")

per_asset_budget = CATALYST_BUDGET / len(qualifying)
new_positions = {}
total_invested = 0
for ticker in qualifying:
    price = entry_prices[ticker]
    shares = int(per_asset_budget / price)
    value = shares * price
    new_positions[ticker] = {
        'shares': shares,
        'entry_price': round(price, 2),
        'value': round(value, 2),
    }
    total_invested += value
    print(f"  {ticker}: {shares} shares × ${price:.2f} = ${value:,.2f}")

cash_not_invested = CATALYST_BUDGET - total_invested
print(f"\n  Total invested: ${total_invested:,.2f}")
print(f"  Catalyst cash remainder: ${cash_not_invested:,.2f}")

# Step 3: Show delta vs old positions
print("\nDELTA vs OLD POSITIONS:")
print("-" * 70)
# Read old state to compare
with open(os.path.join(STATE_DIR, 'compass_state_latest.json')) as f:
    old_state = json.load(f)

old_cats = {cp['symbol']: cp for cp in old_state['hydra']['catalyst_positions']}
old_broker_pos = old_state['positions']

old_catalyst_invested = 0
for sym, cp in old_cats.items():
    old_catalyst_invested += cp['shares'] * cp['entry_price']

print(f"{'Symbol':<8} {'Old Shares':>12} {'New Shares':>12} {'Delta':>8} {'Old $':>12} {'New $':>12}")
print("-" * 70)
all_syms = sorted(set(list(old_cats.keys()) + list(new_positions.keys())))
for sym in all_syms:
    old_sh = old_cats.get(sym, {}).get('shares', 0)
    new_sh = new_positions.get(sym, {}).get('shares', 0)
    old_val = old_sh * old_cats.get(sym, {}).get('entry_price', 0)
    new_val = new_sh * new_positions.get(sym, {}).get('entry_price', 0)
    print(f"{sym:<8} {old_sh:>12} {new_sh:>12} {new_sh - old_sh:>+8} ${old_val:>11,.2f} ${new_val:>11,.2f}")

cash_delta = old_catalyst_invested - total_invested
print(f"\nCash adjustment: {cash_delta:+,.2f} (freed from reallocation)")

# Step 4: Update all state files
print("\nUpdating state files...")
state_files = sorted([f for f in os.listdir(STATE_DIR)
                       if f.startswith('compass_state_') and f.endswith('.json')])

for fname in state_files:
    fpath = os.path.join(STATE_DIR, fname)
    with open(fpath) as f:
        state = json.load(f)

    # Skip states with no catalyst positions (pre-entry)
    cats = state.get('hydra', {}).get('catalyst_positions', [])
    if not cats:
        print(f"  {fname}: no catalyst positions — skipped")
        continue

    old_cats_state = {cp['symbol']: cp for cp in cats}
    old_broker = state.get('positions', {})
    old_meta = state.get('position_meta', {})

    # Calculate old catalyst value at cost
    old_cost = sum(cp['shares'] * cp['entry_price'] for cp in cats)

    # Build new catalyst positions
    new_cats = []
    for ticker in qualifying:
        np_info = new_positions[ticker]
        new_cats.append({
            'symbol': ticker,
            'shares': np_info['shares'],
            'entry_price': np_info['entry_price'],
            'entry_date': ENTRY_DATE,
            'sub_strategy': 'trend',
        })

    # Update hydra.catalyst_positions
    state['hydra']['catalyst_positions'] = new_cats

    # Update broker positions: remove old catalyst, add new
    for sym in list(old_cats_state.keys()):
        if sym in old_broker:
            del old_broker[sym]
        if sym in old_meta:
            del old_meta[sym]

    for ticker in qualifying:
        np_info = new_positions[ticker]
        old_broker[ticker] = {
            'shares': float(np_info['shares']),
            'avg_cost': np_info['entry_price'],
        }
        old_meta[ticker] = {
            'entry_price': np_info['entry_price'],
            'entry_date': ENTRY_DATE,
            'entry_day_index': 1,
            'original_entry_day_index': 1,
            'high_price': np_info['entry_price'],
            'entry_vol': 0.15,
            'entry_daily_vol': 0.0095,
            'sector': 'Catalyst (trend)',
            '_catalyst': True,
            '_entry_reconciled': True,
        }

    state['positions'] = old_broker
    state['position_meta'] = old_meta

    # Adjust cash
    state['cash'] = round(state['cash'] + cash_delta, 2)

    # Recalculate portfolio_value: cash + sum(shares * entry_price) for all positions
    # We use entry prices as approximation since we don't have daily marks for new positions
    # The live engine will recalculate with real prices on next run
    pv = state['cash']
    for sym, pos in state['positions'].items():
        pv += pos['shares'] * pos['avg_cost']
    state['portfolio_value'] = round(pv, 2)

    # Update peak if needed
    if pv > state.get('peak_value', 0):
        state['peak_value'] = round(pv, 2)

    # Update pre_rotation_positions_data if present
    pre_rot = state.get('_pre_rotation_positions_data', {})
    if pre_rot:
        for sym in list(old_cats_state.keys()):
            if sym in pre_rot:
                del pre_rot[sym]
        for ticker in qualifying:
            np_info = new_positions[ticker]
            pre_rot[ticker] = {
                'shares': float(np_info['shares']),
                'avg_cost': np_info['entry_price'],
                'entry_price': np_info['entry_price'],
                'sector': 'Catalyst (trend)',
                'entry_day_index': 1,
                'entry_date': ENTRY_DATE,
            }
        state['_pre_rotation_positions_data'] = pre_rot
        if '_pre_rotation_cash' in state:
            state['_pre_rotation_cash'] = round(state['_pre_rotation_cash'] + cash_delta, 2)
        if '_pre_rotation_value' in state:
            pre_pv = state['_pre_rotation_cash']
            for sym, pos in pre_rot.items():
                pre_pv += pos['shares'] * pos['avg_cost']
            state['_pre_rotation_value'] = round(pre_pv, 2)

    # Recalculate portfolio_values_history using proportional adjustment
    # The delta is small and constant (same positions, different sizes)
    pvh = state.get('portfolio_values_history', [])
    if pvh:
        # Apply cash_delta to each historical value (positions were held from day 1)
        state['portfolio_values_history'] = [round(v + cash_delta, 2) for v in pvh]

    # Write
    with open(fpath, 'w') as f:
        json.dump(state, f, indent=2)
    print(f"  {fname}: updated ({len(new_cats)} catalyst positions)")

# Also update latest
latest_path = os.path.join(STATE_DIR, 'compass_state_latest.json')
with open(latest_path) as f:
    latest = json.load(f)

# Apply same changes
old_cats_latest = {cp['symbol']: cp for cp in latest['hydra']['catalyst_positions']}

new_cats_latest = []
for ticker in qualifying:
    np_info = new_positions[ticker]
    new_cats_latest.append({
        'symbol': ticker,
        'shares': np_info['shares'],
        'entry_price': np_info['entry_price'],
        'entry_date': ENTRY_DATE,
        'sub_strategy': 'trend',
    })
latest['hydra']['catalyst_positions'] = new_cats_latest

# Update broker positions
for sym in list(old_cats_latest.keys()):
    if sym in latest['positions']:
        del latest['positions'][sym]
    if sym in latest['position_meta']:
        del latest['position_meta'][sym]

for ticker in qualifying:
    np_info = new_positions[ticker]
    latest['positions'][ticker] = {
        'shares': float(np_info['shares']),
        'avg_cost': np_info['entry_price'],
    }
    latest['position_meta'][ticker] = {
        'entry_price': np_info['entry_price'],
        'entry_date': ENTRY_DATE,
        'entry_day_index': 1,
        'original_entry_day_index': 1,
        'high_price': np_info['entry_price'],
        'entry_vol': 0.15,
        'entry_daily_vol': 0.0095,
        'sector': 'Catalyst (trend)',
        '_catalyst': True,
        '_entry_reconciled': True,
    }

latest['cash'] = round(latest['cash'] + cash_delta, 2)

pv = latest['cash']
for sym, pos in latest['positions'].items():
    pv += pos['shares'] * pos['avg_cost']
latest['portfolio_value'] = round(pv, 2)
if pv > latest.get('peak_value', 0):
    latest['peak_value'] = round(pv, 2)

# Pre-rotation data
pre_rot = latest.get('_pre_rotation_positions_data', {})
if pre_rot:
    for sym in list(old_cats_latest.keys()):
        if sym in pre_rot:
            del pre_rot[sym]
    for ticker in qualifying:
        np_info = new_positions[ticker]
        pre_rot[ticker] = {
            'shares': float(np_info['shares']),
            'avg_cost': np_info['entry_price'],
            'entry_price': np_info['entry_price'],
            'sector': 'Catalyst (trend)',
            'entry_day_index': 1,
            'entry_date': ENTRY_DATE,
        }
    latest['_pre_rotation_positions_data'] = pre_rot
    if '_pre_rotation_cash' in latest:
        latest['_pre_rotation_cash'] = round(latest['_pre_rotation_cash'] + cash_delta, 2)
    if '_pre_rotation_value' in latest:
        pre_pv = latest['_pre_rotation_cash']
        for sym, pos in pre_rot.items():
            pre_pv += pos['shares'] * pos['avg_cost']
        latest['_pre_rotation_value'] = round(pre_pv, 2)

pvh = latest.get('portfolio_values_history', [])
if pvh:
    latest['portfolio_values_history'] = [round(v + cash_delta, 2) for v in pvh]

with open(latest_path, 'w') as f:
    json.dump(latest, f, indent=2)
print(f"  compass_state_latest.json: updated")

# Step 5: Update cycle log
print("\nUpdating cycle log...")
cycle_path = os.path.join(STATE_DIR, 'cycle_log.json')
with open(cycle_path) as f:
    cycles = json.load(f)

for cycle in cycles:
    if cycle.get('portfolio_start') is not None:
        cycle['portfolio_start'] = round(cycle['portfolio_start'] + cash_delta, 2)
    if cycle.get('portfolio_end') is not None:
        cycle['portfolio_end'] = round(cycle['portfolio_end'] + cash_delta, 2)
    # Recalculate cycle_return_pct if closed
    if cycle.get('status') == 'closed' and cycle.get('portfolio_start') and cycle.get('portfolio_end'):
        ret = cycle['portfolio_end'] - cycle['portfolio_start']
        cycle['hydra_return'] = round(ret, 2)
        cycle['cycle_return_pct'] = round(ret / cycle['portfolio_start'] * 100, 2)
        if cycle.get('spy_return_pct') is not None:
            cycle['alpha_pct'] = round(cycle['cycle_return_pct'] - cycle['spy_return_pct'], 2)

with open(cycle_path, 'w') as f:
    json.dump(cycles, f, indent=2)
print("  cycle_log.json: updated")

print("\n" + "=" * 70)
print("MIGRATION COMPLETE")
print("=" * 70)
print(f"Qualifying trend assets: {qualifying}")
print(f"Cash adjustment applied: {cash_delta:+,.2f}")
print(f"Files updated: {len([f for f in state_files if True])} state snapshots + latest + cycle_log")
print(f"\nNext engine run will recalculate portfolio_value with live prices.")
