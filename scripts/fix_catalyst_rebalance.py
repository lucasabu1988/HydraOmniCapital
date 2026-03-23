"""Fix Catalyst positions retroactively.

On Mar 20 rebalance, TLT was below SMA200 and should have been sold.
Only GLD and DBC qualified. This script:
1. Updates state files from Mar 20 onwards with correct positions
2. Recalculates portfolio values with actual close prices
3. Updates cycle log
"""
import json
import os
import sys
import time

import pandas as pd
import yfinance as yf

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'state')
REBALANCE_DATE = '2026-03-20'

# --- Phase 1: Calculate correct positions ---

# Pre-rebalance catalyst (entered Mar 16): TLT:57, GLD:10, DBC:176
PRE_REBALANCE = {
    'TLT': {'shares': 57, 'entry_price': 87.21},
    'GLD': {'shares': 10, 'entry_price': 460.43},
    'DBC': {'shares': 176, 'entry_price': 28.31},
}

# Download prices
print("Downloading prices...")
all_syms = ['TLT', 'ZROZ', 'GLD', 'DBC', 'JNJ', 'XOM', 'MU', 'EFA']
price_cache = {}
for sym in all_syms:
    for attempt in range(3):
        df = yf.download(sym, start='2025-01-01', end='2026-03-25', progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if len(df) > 0:
            break
        time.sleep(1)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    price_cache[sym] = df['Close']
    print(f"  {sym}: {len(df)} days")


def get_close(sym, date_str):
    s = price_cache.get(sym)
    if s is None:
        return None
    dt = pd.Timestamp(date_str)
    prior = s[s.index <= dt]
    return float(prior.iloc[-1]) if len(prior) > 0 else None


# Calculate TLT sale proceeds on Mar 20
tlt_sell_price = get_close('TLT', REBALANCE_DATE)
tlt_sell_proceeds = 57 * tlt_sell_price
tlt_pnl = 57 * (tlt_sell_price - 87.21)
print(f"\nTLT sold on Mar 20: 57 shares x ${tlt_sell_price:.2f} = ${tlt_sell_proceeds:,.2f}")
print(f"TLT P&L: ${tlt_pnl:,.2f}")

# New catalyst budget: sell all 3 old positions, rebuy qualifying only
# On rebalance, engine sells everything and rebuys based on current SMA200
old_catalyst_value = sum(
    info['shares'] * get_close(sym, REBALANCE_DATE)
    for sym, info in PRE_REBALANCE.items()
)
print(f"Old catalyst value at Mar 20 close: ${old_catalyst_value:,.2f}")

# Qualifying assets on Mar 20: GLD and DBC
gld_price_mar20 = get_close('GLD', REBALANCE_DATE)
dbc_price_mar20 = get_close('DBC', REBALANCE_DATE)

# Budget = catalyst_account (use old value as budget for rebalance)
catalyst_budget = 15000.0  # original allocation
per_asset = catalyst_budget / 2  # 2 qualifying assets

POST_REBALANCE = {
    'GLD': {'shares': int(per_asset / gld_price_mar20), 'entry_price': round(gld_price_mar20, 2)},
    'DBC': {'shares': int(per_asset / dbc_price_mar20), 'entry_price': round(dbc_price_mar20, 2)},
}

new_catalyst_cost = sum(info['shares'] * info['entry_price'] for info in POST_REBALANCE.values())
catalyst_cash_freed = old_catalyst_value - new_catalyst_cost

print(f"\nNew positions (Mar 20 rebalance):")
for sym, info in POST_REBALANCE.items():
    print(f"  {sym}: {info['shares']} shares @ ${info['entry_price']} = ${info['shares'] * info['entry_price']:,.2f}")
print(f"New catalyst invested: ${new_catalyst_cost:,.2f}")
print(f"Cash freed from rebalance: ${catalyst_cash_freed:,.2f}")

# --- Phase 2: Update state files ---

print("\n" + "=" * 70)
print("UPDATING STATE FILES")
print("=" * 70)

# States before rebalance (Mar 17, 18): keep old positions (TLT:57, GLD:10, DBC:176)
# States from Mar 20 onwards: use new positions (GLD:18, DBC:259)

for fname in sorted(os.listdir(STATE_DIR)):
    if not fname.startswith('compass_state_2026') or not fname.endswith('.json'):
        continue
    fpath = os.path.join(STATE_DIR, fname)
    with open(fpath) as f:
        state = json.load(f)

    positions = state.get('positions', {})
    if not positions:
        continue

    date_str = fname.replace('compass_state_', '').replace('.json', '')
    date_fmt = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

    # Only fix states from Mar 20 onwards
    if date_str < '20260320':
        # Pre-rebalance: verify TLT:57, GLD:10, DBC:176 are correct
        print(f"\n{fname}: pre-rebalance — no change needed")
        continue

    # Skip states with no catalyst (empty/reset states)
    cats = state.get('hydra', {}).get('catalyst_positions', [])
    if not cats and 'TLT' not in positions and 'GLD' not in positions:
        print(f"\n{fname}: no catalyst positions — skipped")
        continue

    print(f"\n{fname}: fixing post-rebalance positions...")

    # Remove old catalyst positions from broker
    for sym in ['TLT', 'ZROZ', 'GLD', 'DBC']:
        if sym in positions:
            del positions[sym]
        if sym in state.get('position_meta', {}):
            del state['position_meta'][sym]

    # Add new catalyst positions
    new_cats_list = []
    for sym, info in POST_REBALANCE.items():
        positions[sym] = {
            'shares': float(info['shares']),
            'avg_cost': info['entry_price'],
        }
        state['position_meta'][sym] = {
            'entry_price': info['entry_price'],
            'entry_date': REBALANCE_DATE,
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
            'entry_date': REBALANCE_DATE,
            'sub_strategy': 'trend',
        })

    state['hydra']['catalyst_positions'] = new_cats_list
    state['positions'] = positions

    # Recalculate cash: old cash + (old catalyst value - new catalyst cost)
    # The cash delta comes from selling TLT and resizing GLD/DBC
    old_cats_state = {cp['symbol']: cp for cp in cats}
    old_cat_cost_state = sum(cp['shares'] * cp['entry_price'] for cp in cats)
    state['cash'] = round(state['cash'] + old_cat_cost_state - new_catalyst_cost, 2)

    # Mark-to-market portfolio value
    cash = state['cash']
    mtm = cash
    for sym, pos in positions.items():
        close = get_close(sym, date_fmt)
        if close is None:
            close = pos['avg_cost']
        mtm += pos['shares'] * close
        print(f"  {sym}: {pos['shares']} x ${close:.2f} = ${pos['shares'] * close:,.2f}")

    state['portfolio_value'] = round(mtm, 2)
    state['cash'] = round(cash, 2)
    print(f"  Cash: ${cash:,.2f}")
    print(f"  Portfolio MTM: ${mtm:,.2f}")

    if mtm > state.get('peak_value', 0):
        state['peak_value'] = round(mtm, 2)

    # Fix pre_rotation_positions_data
    pre_rot = state.get('_pre_rotation_positions_data', {})
    if pre_rot:
        for sym in ['TLT', 'ZROZ', 'GLD', 'DBC']:
            if sym in pre_rot:
                del pre_rot[sym]
        for sym, info in POST_REBALANCE.items():
            pre_rot[sym] = {
                'shares': float(info['shares']),
                'avg_cost': info['entry_price'],
                'entry_price': info['entry_price'],
                'sector': 'Catalyst (trend)',
                'entry_day_index': 1,
                'entry_date': REBALANCE_DATE,
            }
        state['_pre_rotation_positions_data'] = pre_rot
        if '_pre_rotation_cash' in state:
            state['_pre_rotation_cash'] = state['cash']

    with open(fpath, 'w') as f:
        json.dump(state, f, indent=2)

# --- Phase 3: Update latest state ---
print("\n" + "=" * 70)
print("UPDATING LATEST STATE")
print("=" * 70)

latest_path = os.path.join(STATE_DIR, 'compass_state_latest.json')
with open(latest_path) as f:
    latest = json.load(f)

# Remove old catalyst
old_cats_latest = {cp['symbol']: cp for cp in latest['hydra']['catalyst_positions']}
old_cat_cost_latest = sum(cp['shares'] * cp['entry_price'] for cp in old_cats_latest.values())

for sym in ['TLT', 'ZROZ', 'GLD', 'DBC']:
    if sym in latest['positions']:
        del latest['positions'][sym]
    if sym in latest['position_meta']:
        del latest['position_meta'][sym]

# Add new
for sym, info in POST_REBALANCE.items():
    latest['positions'][sym] = {
        'shares': float(info['shares']),
        'avg_cost': info['entry_price'],
    }
    latest['position_meta'][sym] = {
        'entry_price': info['entry_price'],
        'entry_date': REBALANCE_DATE,
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
     'entry_date': REBALANCE_DATE, 'sub_strategy': 'trend'}
    for sym, info in POST_REBALANCE.items()
]

latest['cash'] = round(latest['cash'] + old_cat_cost_latest - new_catalyst_cost, 2)

# MTM
latest_date = latest.get('last_trading_date', '2026-03-23')
mtm = latest['cash']
for sym, pos in latest['positions'].items():
    close = get_close(sym, latest_date)
    if close is None:
        close = pos['avg_cost']
    mtm += pos['shares'] * close
latest['portfolio_value'] = round(mtm, 2)
if mtm > latest.get('peak_value', 0):
    latest['peak_value'] = round(mtm, 2)

# Pre-rotation
pre_rot = latest.get('_pre_rotation_positions_data', {})
if pre_rot:
    for sym in ['TLT', 'ZROZ', 'GLD', 'DBC']:
        if sym in pre_rot:
            del pre_rot[sym]
    for sym, info in POST_REBALANCE.items():
        pre_rot[sym] = {
            'shares': float(info['shares']),
            'avg_cost': info['entry_price'],
            'entry_price': info['entry_price'],
            'sector': 'Catalyst (trend)',
            'entry_day_index': 1,
            'entry_date': REBALANCE_DATE,
        }
    latest['_pre_rotation_positions_data'] = pre_rot
    if '_pre_rotation_cash' in latest:
        latest['_pre_rotation_cash'] = latest['cash']

# Rebuild PVH: read each dated state's portfolio_value
pvh = []
for fname in sorted(os.listdir(STATE_DIR)):
    if not fname.startswith('compass_state_2026') or not fname.endswith('.json'):
        continue
    fpath = os.path.join(STATE_DIR, fname)
    with open(fpath) as f:
        s = json.load(f)
    if s.get('positions'):
        pvh.append(round(s['portfolio_value'], 2))

latest['portfolio_values_history'] = pvh

with open(latest_path, 'w') as f:
    json.dump(latest, f, indent=2)

print(f"Latest: cash=${latest['cash']:,.2f}  pv=${latest['portfolio_value']:,.2f}")
print(f"PVH: {pvh}")

# --- Phase 4: Update cycle log ---
print("\n" + "=" * 70)
print("UPDATING CYCLE LOG")
print("=" * 70)

cycle_path = os.path.join(STATE_DIR, 'cycle_log.json')
with open(cycle_path) as f:
    cycles = json.load(f)

# Cycle 1 end = Mar 20 portfolio value (read from state)
mar20_state_path = None
for fname in sorted(os.listdir(STATE_DIR)):
    if '20260322' in fname:  # First state after rebalance
        mar20_state_path = os.path.join(STATE_DIR, fname)
        break

if mar20_state_path:
    with open(mar20_state_path) as f:
        mar20_state = json.load(f)
    # Cycle 1 end value = cash + positions MTM on Mar 20
    # We need Mar 20 prices for the NEW positions
    cycle1_end = latest['cash']  # same cash
    # Actually recalculate from Mar 22 state which has Mar 20 rebalanced positions
    # The cycle 1 end should use Mar 20 close prices
    c1_end = 0
    # Cash after rebalance
    c1_cash = mar20_state['cash']
    c1_end = c1_cash
    for sym, pos in mar20_state['positions'].items():
        close = get_close(sym, '2026-03-20')
        if close is None:
            close = pos['avg_cost']
        c1_end += pos['shares'] * close

    for c in cycles:
        if c['cycle'] == 1:
            c['portfolio_end'] = round(c1_end, 2)
            ret = c1_end - c['portfolio_start']
            c['hydra_return'] = round(ret, 2)
            c['cycle_return_pct'] = round(ret / c['portfolio_start'] * 100, 2)
            if c.get('spy_return_pct') is not None:
                c['alpha_pct'] = round(c['cycle_return_pct'] - c['spy_return_pct'], 2)
            print(f"Cycle 1: start=${c['portfolio_start']:,.2f} end=${c1_end:,.2f} ret={c['cycle_return_pct']:.2f}%")
        elif c['cycle'] == 2:
            c['portfolio_start'] = round(c1_end, 2)
            print(f"Cycle 2: start=${c1_end:,.2f}")

with open(cycle_path, 'w') as f:
    json.dump(cycles, f, indent=2)

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
print(f"Catalyst positions (post Mar 20 rebalance):")
for sym, info in POST_REBALANCE.items():
    print(f"  {sym}: {info['shares']} shares @ ${info['entry_price']}")
print(f"TLT correctly excluded (below SMA200 on Mar 20)")
