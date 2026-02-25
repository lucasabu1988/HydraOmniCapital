"""
Force Rotation: Simulate selling current positions and buying new ones
=====================================================================
The algorithm failed to rotate on schedule. This script:
1. Fetches current prices for all held positions
2. Sells them all (simulating MOC execution)
3. Computes fresh momentum ranking for the universe
4. Buys top-5 new stocks (excluding just-sold ones)
5. Saves updated state to compass_state_latest.json + dated backup
"""

import json
import os
import sys
import numpy as np
from datetime import datetime, date
from copy import deepcopy

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'state')
STATE_FILE = os.path.join(STATE_DIR, 'compass_state_latest.json')

COMMISSION_PER_SHARE = 0.001
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
NUM_POSITIONS = 5

# ============================================================================
# LOAD STATE
# ============================================================================

print("=" * 70)
print("FORCE ROTATION — Sell all + Buy new top-5 momentum")
print("=" * 70)

with open(STATE_FILE, 'r') as f:
    state = json.load(f)

# Backup current state
today_str = date.today().strftime('%Y%m%d')
backup_file = os.path.join(STATE_DIR, f'compass_state_{today_str}_pre_rotation.json')
with open(backup_file, 'w') as f:
    json.dump(state, f, indent=2, default=str)
print(f"\n[Backup] Saved pre-rotation state to {backup_file}")

positions = state['positions']
position_meta = state.get('position_meta', {})
cash = state['cash']
universe = state['current_universe']

print(f"\nCurrent state:")
print(f"  Cash: ${cash:,.2f}")
print(f"  Positions: {list(positions.keys())}")
print(f"  Universe: {len(universe)} stocks")

# ============================================================================
# STEP 1: FETCH CURRENT PRICES
# ============================================================================

print(f"\n[1] Fetching current prices...")

all_symbols = list(set(universe + list(positions.keys()) + ['SPY']))
prices = {}

for sym in all_symbols:
    try:
        t = yf.Ticker(sym)
        hist = t.history(period='5d')
        if len(hist) > 0:
            prices[sym] = float(hist['Close'].iloc[-1])
    except Exception:
        pass

print(f"  Fetched {len(prices)} prices")

# ============================================================================
# STEP 2: SELL ALL POSITIONS
# ============================================================================

print(f"\n[2] Selling all positions...")

total_proceeds = 0
trades_log = []

for sym, pos in positions.items():
    price = prices.get(sym)
    if price is None:
        print(f"  WARNING: No price for {sym}, using avg_cost")
        price = pos['avg_cost']

    shares = pos['shares']
    proceeds = shares * price
    commission = shares * COMMISSION_PER_SHARE
    net_proceeds = proceeds - commission

    entry_price = pos['avg_cost']
    pnl = (price - entry_price) * shares - commission
    pnl_pct = (price - entry_price) / entry_price * 100

    cash += net_proceeds
    total_proceeds += net_proceeds

    meta = position_meta.get(sym, {})
    entry_date = meta.get('entry_date', '?')

    trades_log.append({
        'symbol': sym,
        'action': 'SELL',
        'shares': shares,
        'entry_price': entry_price,
        'exit_price': price,
        'pnl': pnl,
        'pnl_pct': pnl_pct,
        'entry_date': entry_date,
    })

    arrow = "+" if pnl >= 0 else ""
    print(f"  SELL {sym}: {shares:.2f} shares @ ${price:.2f} "
          f"(entry ${entry_price:.2f}) -> {arrow}${pnl:,.2f} ({arrow}{pnl_pct:.1f}%)")

print(f"\n  Total proceeds: ${total_proceeds:,.2f}")
print(f"  Cash after sells: ${cash:,.2f}")

# ============================================================================
# STEP 3: COMPUTE MOMENTUM RANKING
# ============================================================================

print(f"\n[3] Computing momentum scores for {len(universe)} stocks...")

scores = {}
sold_symbols = set(positions.keys())

for sym in universe:
    try:
        t = yf.Ticker(sym)
        hist = t.history(period='6mo')
        if len(hist) < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
            continue

        close_today = float(hist['Close'].iloc[-1])
        close_skip = float(hist['Close'].iloc[-MOMENTUM_SKIP - 1])
        close_lookback = float(hist['Close'].iloc[-MOMENTUM_LOOKBACK - 1])

        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue

        momentum_90d = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        score = momentum_90d - skip_5d

        scores[sym] = score
    except Exception:
        continue

print(f"  Computed scores for {len(scores)} stocks")

# Rank all
ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

print(f"\n  Top-15 momentum ranking:")
for i, (sym, sc) in enumerate(ranked[:15]):
    held = " (JUST SOLD)" if sym in sold_symbols else ""
    print(f"    {i+1:2d}. {sym:6s} score={sc:+.4f}{held}")

# ============================================================================
# STEP 4: BUY TOP-5 (EXCLUDING JUST SOLD)
# ============================================================================

print(f"\n[4] Buying top-{NUM_POSITIONS} new stocks...")

# Exclude just-sold stocks
available = [(sym, sc) for sym, sc in ranked if sym not in sold_symbols]
selected = [sym for sym, sc in available[:NUM_POSITIONS]]

print(f"  Selected: {selected}")

# Compute inverse-vol weights
vols = {}
for sym in selected:
    try:
        t = yf.Ticker(sym)
        hist = t.history(period='2mo')
        if len(hist) >= 20:
            returns = hist['Close'].pct_change().dropna()
            vol = returns.std() * np.sqrt(252)
            if vol > 0.01:
                vols[sym] = vol
    except Exception:
        pass

if vols:
    raw_weights = {s: 1.0 / v for s, v in vols.items()}
    total_w = sum(raw_weights.values())
    weights = {s: w / total_w for s, w in raw_weights.items()}
else:
    weights = {s: 1.0 / len(selected) for s in selected}

# Buy
effective_capital = cash * 1.0 * 0.95  # leverage 1.0x, 5% buffer
new_positions = {}
new_position_meta = {}

for sym in selected:
    price = prices.get(sym)
    if price is None:
        try:
            t = yf.Ticker(sym)
            hist = t.history(period='5d')
            if len(hist) > 0:
                price = float(hist['Close'].iloc[-1])
                prices[sym] = price
        except Exception:
            continue

    if price is None or price <= 0:
        continue

    weight = weights.get(sym, 1.0 / len(selected))
    position_value = effective_capital * weight
    max_per_position = cash * 0.40
    position_value = min(position_value, max_per_position)

    shares = position_value / price
    cost = shares * price
    commission = shares * COMMISSION_PER_SHARE

    if cost + commission <= cash * 0.90:
        new_positions[sym] = {
            'shares': shares,
            'avg_cost': price
        }
        new_position_meta[sym] = {
            'entry_price': price,
            'entry_date': today_str[:4] + '-' + today_str[4:6] + '-' + today_str[6:],
            'entry_day_index': state['trading_day_counter'] + 1,
            'high_price': price
        }
        cash -= cost + commission

        trades_log.append({
            'symbol': sym,
            'action': 'BUY',
            'shares': shares,
            'price': price,
            'cost': cost + commission,
            'weight': weight,
        })

        print(f"  BUY {sym}: {shares:.2f} shares @ ${price:.2f} "
              f"(weight {weight:.1%}, value ${cost:,.2f})")

# ============================================================================
# STEP 5: COMPUTE NEW PORTFOLIO VALUE & UPDATE STATE
# ============================================================================

print(f"\n[5] Updating state...")

portfolio_value = cash
for sym, pos in new_positions.items():
    price = prices.get(sym, pos['avg_cost'])
    portfolio_value += pos['shares'] * price

peak_value = max(state['peak_value'], portfolio_value)

# Update state
state['cash'] = cash
state['positions'] = new_positions
state['position_meta'] = new_position_meta
state['portfolio_value'] = portfolio_value
state['peak_value'] = peak_value
state['trading_day_counter'] = state['trading_day_counter'] + 1
state['last_trading_date'] = date.today().isoformat()
state['timestamp'] = datetime.now().isoformat()
state['stats']['cycles_completed'] = state['stats'].get('cycles_completed', 0) + 1

# Save
with open(STATE_FILE, 'w') as f:
    json.dump(state, f, indent=2, default=str)

# Also save dated copy
dated_file = os.path.join(STATE_DIR, f'compass_state_{today_str}.json')
with open(dated_file, 'w') as f:
    json.dump(state, f, indent=2, default=str)

print(f"\n  State saved to: {STATE_FILE}")
print(f"  Dated copy: {dated_file}")

# ============================================================================
# SUMMARY
# ============================================================================

invested = sum(pos['shares'] * prices.get(sym, pos['avg_cost'])
               for sym, pos in new_positions.items())

print(f"\n{'='*70}")
print(f"ROTATION COMPLETE")
print(f"{'='*70}")
print(f"  Portfolio value: ${portfolio_value:,.2f}")
print(f"  Cash remaining:  ${cash:,.2f} ({cash/portfolio_value*100:.1f}%)")
print(f"  Invested:        ${invested:,.2f} ({invested/portfolio_value*100:.1f}%)")
print(f"  Positions:       {list(new_positions.keys())}")
print(f"  Trading day:     {state['trading_day_counter']}")
print(f"  Peak value:      ${peak_value:,.2f}")

# P&L summary
total_pnl = sum(t['pnl'] for t in trades_log if t['action'] == 'SELL')
print(f"\n  Cycle P&L:       ${total_pnl:+,.2f}")
for t in trades_log:
    if t['action'] == 'SELL':
        arrow = "+" if t['pnl'] >= 0 else ""
        print(f"    {t['symbol']:6s} {arrow}${t['pnl']:,.2f} ({arrow}{t['pnl_pct']:.1f}%)")

print(f"\n{'='*70}")
