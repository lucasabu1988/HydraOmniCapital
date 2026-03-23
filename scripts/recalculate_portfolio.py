"""Recalculate all portfolio values with actual close prices,
using the new Catalyst positions (TLT:57, GLD:10, DBC:176) as if
the EXP71 config had been active since 2026-03-16.
"""
import json
import os
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'state')

# New catalyst positions (from migration)
NEW_CATALYST = {
    'TLT': {'shares': 57, 'entry_price': 87.21},
    'GLD': {'shares': 10, 'entry_price': 460.43},
    'DBC': {'shares': 176, 'entry_price': 28.31},
}

# Download close prices for ALL symbols that appear in any state file
print("Scanning state files for all symbols...")
all_symbols = set()
state_files = []
for fname in sorted(os.listdir(STATE_DIR)):
    if not fname.startswith('compass_state_2026') or not fname.endswith('.json'):
        continue
    fpath = os.path.join(STATE_DIR, fname)
    with open(fpath) as f:
        s = json.load(f)
    positions = s.get('positions', {})
    if not positions:
        continue
    all_symbols.update(positions.keys())
    state_files.append(fname)

# Also add new catalyst symbols
all_symbols.update(NEW_CATALYST.keys())
all_symbols = sorted(all_symbols)
print(f"Symbols: {all_symbols}")
print(f"State files with positions: {state_files}")

# Download daily close prices
print("\nDownloading close prices...")
price_data = {}
for sym in all_symbols:
    df = yf.download(sym, start='2026-03-14', end='2026-03-25', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    price_data[sym] = df['Close']
    dates = df.index.strftime('%m-%d').tolist()
    print(f"  {sym}: {len(df)} days ({dates})")


def get_close(sym, date_str):
    """Get close price for symbol on a date (or nearest prior)."""
    if sym not in price_data:
        return None
    series = price_data[sym]
    dt = pd.Timestamp(date_str)
    # Try exact date
    if dt in series.index:
        return float(series[dt])
    # Try nearest prior
    prior = series[series.index <= dt]
    if len(prior) > 0:
        return float(prior.iloc[-1])
    return None


# Process each state file
print("\n" + "=" * 80)
print("RECALCULATING PORTFOLIO VALUES")
print("=" * 80)

portfolio_history = []  # collect daily values for pvh

for fname in sorted(os.listdir(STATE_DIR)):
    if not fname.startswith('compass_state_2026') or not fname.endswith('.json'):
        continue
    fpath = os.path.join(STATE_DIR, fname)
    with open(fpath) as f:
        state = json.load(f)

    positions = state.get('positions', {})
    if not positions:
        print(f"\n{fname}: no positions — skipped")
        continue

    # Extract date from filename (compass_state_YYYYMMDD.json)
    date_str = fname.replace('compass_state_', '').replace('.json', '')
    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    # Step 1: Replace catalyst positions with new ones
    old_cats = {cp['symbol']: cp for cp in state.get('hydra', {}).get('catalyst_positions', [])}

    # Remove old catalyst from broker positions
    for sym in list(old_cats.keys()):
        if sym in positions:
            del positions[sym]
        if sym in state.get('position_meta', {}):
            del state['position_meta'][sym]

    # Add new catalyst positions
    new_cats_list = []
    for sym, info in NEW_CATALYST.items():
        positions[sym] = {
            'shares': float(info['shares']),
            'avg_cost': info['entry_price'],
        }
        state['position_meta'][sym] = {
            'entry_price': info['entry_price'],
            'entry_date': '2026-03-16',
            'entry_day_index': 1,
            'original_entry_day_index': 1,
            'high_price': info['entry_price'],
            'entry_vol': 0.15,
            'entry_daily_vol': 0.0095,
            'sector': 'Catalyst (trend)',
            '_catalyst': True,
            '_entry_reconciled': True,
        }
        new_cats_list.append({
            'symbol': sym,
            'shares': info['shares'],
            'entry_price': info['entry_price'],
            'entry_date': '2026-03-16',
            'sub_strategy': 'trend',
        })

    state['hydra']['catalyst_positions'] = new_cats_list
    state['positions'] = positions

    # Step 2: Calculate portfolio value with actual close prices
    # Cash: recalculate from original $100K minus what was actually spent
    # We need to figure out the correct cash from positions at cost
    total_at_cost = sum(pos['shares'] * pos['avg_cost'] for pos in positions.values())
    # Cash = initial capital - total invested at cost
    # But cash might have changed from trades... let's use the existing cash
    # and just adjust for the catalyst position difference
    old_catalyst_cost = sum(cp['shares'] * cp['entry_price'] for cp in old_cats.values())
    new_catalyst_cost = sum(info['shares'] * info['entry_price'] for info in NEW_CATALYST.values())
    cash_delta = old_catalyst_cost - new_catalyst_cost
    state['cash'] = round(state['cash'] + cash_delta, 2)

    # Mark-to-market portfolio value
    cash = state['cash']
    mtm = cash
    print(f"\n{fname} ({date_fmt}):")
    print(f"  Cash: ${cash:,.2f}")
    for sym, pos in positions.items():
        close = get_close(sym, date_fmt)
        if close is None:
            # Fallback to avg_cost
            close = pos['avg_cost']
            print(f"  {sym}: {pos['shares']} shares × ${close:.2f} (avg_cost fallback) = ${pos['shares'] * close:,.2f}")
        else:
            print(f"  {sym}: {pos['shares']} shares × ${close:.2f} (close) = ${pos['shares'] * close:,.2f}")
        mtm += pos['shares'] * close

    state['portfolio_value'] = round(mtm, 2)
    print(f"  Portfolio MTM: ${mtm:,.2f}")

    # Track for portfolio_values_history
    portfolio_history.append({'date': date_fmt, 'value': round(mtm, 2), 'fname': fname})

    # Update peak
    if mtm > state.get('peak_value', 0):
        state['peak_value'] = round(mtm, 2)

    # Update pre_rotation data if present
    pre_rot = state.get('_pre_rotation_positions_data', {})
    if pre_rot:
        for sym in list(old_cats.keys()):
            if sym in pre_rot:
                del pre_rot[sym]
        for sym, info in NEW_CATALYST.items():
            pre_rot[sym] = {
                'shares': float(info['shares']),
                'avg_cost': info['entry_price'],
                'entry_price': info['entry_price'],
                'sector': 'Catalyst (trend)',
                'entry_day_index': 1,
                'entry_date': '2026-03-16',
            }
        state['_pre_rotation_positions_data'] = pre_rot
        if '_pre_rotation_cash' in state:
            state['_pre_rotation_cash'] = round(state['_pre_rotation_cash'] + cash_delta, 2)
        # Recalc pre-rotation value with close prices
        if '_pre_rotation_value' in state:
            pre_pv = state['_pre_rotation_cash']
            for sym, pos_data in pre_rot.items():
                close = get_close(sym, date_fmt)
                if close is None:
                    close = pos_data['avg_cost']
                pre_pv += pos_data['shares'] * close
            state['_pre_rotation_value'] = round(pre_pv, 2)

    # Write back
    with open(fpath, 'w') as f:
        json.dump(state, f, indent=2)

# Build portfolio_values_history from daily snapshots
pvh = [ph['value'] for ph in portfolio_history]
print(f"\nPortfolio values history: {pvh}")

# Update latest state with correct pvh
latest_path = os.path.join(STATE_DIR, 'compass_state_latest.json')
with open(latest_path) as f:
    latest = json.load(f)

# Apply same catalyst fix to latest
old_cats_latest = {cp['symbol']: cp for cp in latest['hydra']['catalyst_positions']}
old_cat_cost = sum(cp['shares'] * cp['entry_price'] for cp in old_cats_latest.values())
new_cat_cost = sum(info['shares'] * info['entry_price'] for info in NEW_CATALYST.values())
cash_delta_latest = old_cat_cost - new_cat_cost

# Remove old, add new catalyst positions
for sym in list(old_cats_latest.keys()):
    if sym in latest['positions']:
        del latest['positions'][sym]
    if sym in latest['position_meta']:
        del latest['position_meta'][sym]

for sym, info in NEW_CATALYST.items():
    latest['positions'][sym] = {
        'shares': float(info['shares']),
        'avg_cost': info['entry_price'],
    }
    latest['position_meta'][sym] = {
        'entry_price': info['entry_price'],
        'entry_date': '2026-03-16',
        'entry_day_index': 1,
        'original_entry_day_index': 1,
        'high_price': info['entry_price'],
        'entry_vol': 0.15,
        'entry_daily_vol': 0.0095,
        'sector': 'Catalyst (trend)',
        '_catalyst': True,
        '_entry_reconciled': True,
    }

latest['hydra']['catalyst_positions'] = [
    {'symbol': sym, 'shares': info['shares'], 'entry_price': info['entry_price'],
     'entry_date': '2026-03-16', 'sub_strategy': 'trend'}
    for sym, info in NEW_CATALYST.items()
]

latest['cash'] = round(latest['cash'] + cash_delta_latest, 2)

# MTM latest with most recent close prices
latest_date = latest.get('last_trading_date', '2026-03-23')
mtm_latest = latest['cash']
for sym, pos in latest['positions'].items():
    close = get_close(sym, latest_date)
    if close is None:
        close = pos['avg_cost']
    mtm_latest += pos['shares'] * close
latest['portfolio_value'] = round(mtm_latest, 2)
if mtm_latest > latest.get('peak_value', 0):
    latest['peak_value'] = round(mtm_latest, 2)

# Set pvh from daily snapshots
latest['portfolio_values_history'] = pvh

# Pre-rotation
pre_rot = latest.get('_pre_rotation_positions_data', {})
if pre_rot:
    for sym in list(old_cats_latest.keys()):
        if sym in pre_rot:
            del pre_rot[sym]
    for sym, info in NEW_CATALYST.items():
        pre_rot[sym] = {
            'shares': float(info['shares']),
            'avg_cost': info['entry_price'],
            'entry_price': info['entry_price'],
            'sector': 'Catalyst (trend)',
            'entry_day_index': 1,
            'entry_date': '2026-03-16',
        }
    latest['_pre_rotation_positions_data'] = pre_rot
    if '_pre_rotation_cash' in latest:
        latest['_pre_rotation_cash'] = round(latest['_pre_rotation_cash'] + cash_delta_latest, 2)

with open(latest_path, 'w') as f:
    json.dump(latest, f, indent=2)
print(f"\nLatest state: pv=${mtm_latest:,.2f}, cash=${latest['cash']:,.2f}")

# Update cycle log with correct values
cycle_path = os.path.join(STATE_DIR, 'cycle_log.json')
with open(cycle_path) as f:
    cycles = json.load(f)

# Cycle 1: started 2026-03-16, ended 2026-03-20
# Need close prices on those dates for portfolio value
if len(portfolio_history) >= 1:
    # Cycle 1 start = first day with positions (Mar 17 snapshot = end of Mar 16 trading)
    # Actually cycle 1 start should be $100,000 (initial capital)
    # Cycle 1 end = portfolio value on Mar 20
    for cycle in cycles:
        if cycle['cycle'] == 1:
            cycle['portfolio_start'] = 100000.0
            # Get Mar 20 portfolio value
            for ph in portfolio_history:
                if '0320' in ph['fname'] or '0321' in ph['fname']:
                    cycle['portfolio_end'] = ph['value']
                    break
            else:
                # Use the last value before cycle 2
                # Cycle 1 ended on Mar 20, find the snapshot
                pass
            if cycle.get('portfolio_end') and cycle.get('portfolio_start'):
                ret = cycle['portfolio_end'] - cycle['portfolio_start']
                cycle['hydra_return'] = round(ret, 2)
                cycle['cycle_return_pct'] = round(ret / cycle['portfolio_start'] * 100, 2)
                if cycle.get('spy_return_pct') is not None:
                    cycle['alpha_pct'] = round(cycle['cycle_return_pct'] - cycle['spy_return_pct'], 2)

        elif cycle['cycle'] == 2:
            if cycles[0].get('portfolio_end'):
                cycle['portfolio_start'] = cycles[0]['portfolio_end']

with open(cycle_path, 'w') as f:
    json.dump(cycles, f, indent=2)

# Final summary
print("\n" + "=" * 80)
print("RECALCULATION COMPLETE")
print("=" * 80)
print(f"Portfolio values history:")
for ph in portfolio_history:
    print(f"  {ph['date']}: ${ph['value']:,.2f}")
print(f"\nCycle log updated with mark-to-market values")
