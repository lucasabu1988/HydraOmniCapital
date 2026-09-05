"""Apply retroactive rotation: sell hold-expired COMPASS positions and buy
new entries at Apr 1 2026 close prices.

This corrects a missed preclose rotation (bug: catch-up was unreachable
after market close on Render).
"""
import yfinance as yf
import pandas as pd
import numpy as np
import json
import os
import shutil
from datetime import datetime

STATE_FILE = 'state/compass_state_latest.json'
CYCLE_LOG = 'state/cycle_log.json'
ROTATION_DATE = '2026-04-01'
ROTATION_DAY_INDEX = 51  # trading_day_counter on Apr 1

# ===== Load state =====
with open(STATE_FILE) as f:
    state = json.load(f)
with open(CYCLE_LOG) as f:
    cycles = json.load(f)

universe = state['current_universe']
cash_before = state['cash']

# ===== Identify COMPASS positions to sell =====
sell_positions = {}
for sym, meta in state['position_meta'].items():
    if meta.get('_catalyst') or meta.get('_efa'):
        continue
    sell_positions[sym] = {
        'shares': state['positions'][sym]['shares'],
        'avg_cost': state['positions'][sym]['avg_cost'],
        'entry_price': meta['entry_price'],
        'sector': meta.get('sector', 'Unknown'),
    }

print("=== POSITIONS TO SELL (hold_expired) ===")
for sym, info in sell_positions.items():
    print(f"  {sym}: {info['shares']:.0f} shares, entry=${info['entry_price']:.2f}")

# ===== Download historical data =====
all_syms = list(set(universe) | set(state['positions'].keys()) | {'^GSPC', 'SPY'})
hist_data = yf.download(all_syms, end='2026-04-02', period='6mo', progress=False)
if isinstance(hist_data.columns, pd.MultiIndex):
    closes_all = hist_data['Close']
else:
    closes_all = hist_data

apr1_closes = closes_all.loc[ROTATION_DATE]

# Apr 2 closes for portfolio valuation
apr2_data = yf.download(
    ['XOM', 'JNJ', 'GLD', 'DBC', 'EFA', '^GSPC'],
    start='2026-04-02', end='2026-04-03', progress=False
)
if isinstance(apr2_data.columns, pd.MultiIndex):
    apr2_closes = apr2_data['Close'].iloc[-1]
else:
    apr2_closes = apr2_data['Close'].iloc[-1]

# ===== Compute sell proceeds =====
total_proceeds = 0
sell_details = []
for sym, info in sell_positions.items():
    exit_price = float(apr1_closes[sym])
    proceeds = info['shares'] * exit_price
    pnl_pct = (exit_price - info['entry_price']) / info['entry_price'] * 100
    total_proceeds += proceeds
    sell_details.append({
        'symbol': sym, 'shares': info['shares'],
        'exit_price': exit_price, 'entry_price': info['entry_price'],
        'proceeds': proceeds, 'pnl_pct': pnl_pct, 'sector': info['sector'],
    })
    print(f"  SELL {sym}: {info['shares']:.0f} shares @ ${exit_price:.2f} = ${proceeds:,.2f} (PnL: {pnl_pct:+.2f}%)")

cash_after_sells = cash_before + total_proceeds

# ===== Compute momentum scores (signal = Close[T-1] = Mar 31) =====
LOOKBACK, SKIP, VOL_WINDOW = 90, 5, 63
scores, entry_vols, daily_vols = {}, {}, {}
for sym in universe:
    try:
        if sym not in closes_all.columns:
            continue
        s = closes_all[sym].loc[:'2026-03-31'].dropna()
        if len(s) < LOOKBACK + SKIP:
            continue
        price_end = s.iloc[-(SKIP + 1)]
        price_start = s.iloc[-(LOOKBACK + SKIP)]
        ret_90d = (price_end - price_start) / price_start
        rets = s.pct_change().dropna().iloc[-(VOL_WINDOW + SKIP):-(SKIP)]
        vol = rets.std() * np.sqrt(252)
        daily_vol = rets.std()
        if vol > 0.01:
            scores[sym] = ret_90d / vol
            entry_vols[sym] = vol
            daily_vols[sym] = daily_vol
    except Exception:
        pass

ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
max_positions = 2  # RISK_OFF

# Exclude non-COMPASS held positions
held_non_compass = {
    s for s, m in state['position_meta'].items()
    if m.get('_catalyst') or m.get('_efa')
}
available = [(s, sc) for s, sc in ranked if s not in held_non_compass]
selected = [s for s, _ in available[:max_positions]]

print(f"\n=== NEW ENTRIES (top {max_positions} in RISK_OFF) ===")
for s, sc in available[:max_positions]:
    print(f"  {s}: score={sc:.4f}, vol={entry_vols[s]:.1%}")

# ===== Inverse-vol weights =====
inv_vols = {s: 1.0 / entry_vols[s] for s in selected}
total_inv = sum(inv_vols.values())
weights = {s: v / total_inv for s, v in inv_vols.items()}

compass_alloc = state['hydra']['capital_manager']['compass_account']
compass_budget = min(cash_after_sells, compass_alloc + total_proceeds) * 0.95

buy_details = []
total_invested = 0
remaining = cash_after_sells
for sym in selected:
    price = float(apr1_closes[sym])
    position_value = min(compass_budget * weights[sym], remaining * 0.40)
    shares = int(position_value / price)
    if shares <= 0:
        continue
    cost = shares * price
    remaining -= cost
    total_invested += cost
    buy_details.append({
        'symbol': sym, 'shares': shares, 'price': price, 'cost': cost,
        'weight': weights[sym], 'vol': entry_vols[sym],
        'daily_vol': daily_vols[sym], 'score': scores[sym],
    })
    print(f"  BUY {sym}: {shares} shares @ ${price:.2f} = ${cost:,.2f}")

final_cash = cash_after_sells - total_invested

# ===== Apply to state =====

# Remove sold positions
for sell in sell_details:
    sym = sell['symbol']
    state['positions'].pop(sym, None)
    state['position_meta'].pop(sym, None)

# Add new positions
SECTOR_MAP = {'XOM': 'Energy', 'JNJ': 'Healthcare'}
for buy in buy_details:
    sym = buy['symbol']
    state['positions'][sym] = {
        'shares': float(buy['shares']),
        'avg_cost': buy['price'],
    }
    state['position_meta'][sym] = {
        'entry_price': buy['price'],
        'entry_date': ROTATION_DATE,
        'entry_day_index': ROTATION_DAY_INDEX,
        'original_entry_day_index': ROTATION_DAY_INDEX,
        'high_price': max(buy['price'], float(apr2_closes.get(sym, buy['price']))),
        'entry_vol': buy['vol'],
        'entry_daily_vol': buy['daily_vol'],
        'sector': SECTOR_MAP.get(sym, 'Unknown'),
        'entry_momentum_score': buy['score'],
        'entry_momentum_rank': 1.0 if sym == selected[0] else 0.975,
        '_entry_reconciled': True,
    }

state['cash'] = final_cash

# Portfolio value with Apr 2 prices
total_value = state['cash']
for sym, pos in state['positions'].items():
    p = float(apr2_closes.get(sym, pos['avg_cost']))
    total_value += pos['shares'] * p

state['portfolio_value'] = total_value
state['peak_value'] = max(state.get('peak_value', 0), total_value)
state['_preclose_entries_done'] = True
state['_daily_open_done'] = True
state['timestamp'] = datetime.now().isoformat()
state['stats']['cycles_completed'] = 4

# Pre-rotation snapshot
state['_pre_rotation_positions_data'] = {
    sym: {
        'shares': pos['shares'], 'avg_cost': pos['avg_cost'],
        'market_price': float(apr2_closes.get(sym, pos['avg_cost'])),
        'entry_price': state['position_meta'].get(sym, {}).get('entry_price', pos['avg_cost']),
        'sector': state['position_meta'].get(sym, {}).get('sector', 'Unknown'),
        'entry_day_index': state['position_meta'].get(sym, {}).get('entry_day_index', ROTATION_DAY_INDEX),
        'entry_date': state['position_meta'].get(sym, {}).get('entry_date'),
    }
    for sym, pos in state['positions'].items()
}
state['_pre_rotation_cash'] = state['cash']
state['_pre_rotation_value'] = total_value

# Update portfolio_values_history
state['portfolio_values_history'].append(total_value)
if len(state['portfolio_values_history']) > 30:
    state['portfolio_values_history'] = state['portfolio_values_history'][-30:]

# HYDRA capital manager
cm = state['hydra']['capital_manager']
compass_invested = sum(
    state['positions'][s]['shares'] * state['positions'][s]['avg_cost']
    for s in state['positions']
    if s in state['position_meta']
    and not state['position_meta'][s].get('_catalyst')
    and not state['position_meta'][s].get('_efa')
)
cm['compass_account'] = state['cash'] + compass_invested
if 'EFA' in state['positions']:
    cm['efa_value'] = state['positions']['EFA']['shares'] * float(apr2_closes.get('EFA', 98.0))

# ===== Update cycle log =====
cycle4 = cycles[-1]
assert cycle4['cycle'] == 4 and cycle4['status'] == 'active', f"Expected active cycle 4, got {cycle4}"

gspc_apr1 = float(apr1_closes['^GSPC'])

# Portfolio at cycle close = cash + all positions at Apr 1 close
portfolio_end_c4 = final_cash
apr1_price_map = {'GLD': 437.82, 'DBC': 28.68, 'EFA': 98.61}
for sym, pos in state['positions'].items():
    p = apr1_price_map.get(sym, float(apr1_closes.get(sym, pos['avg_cost'])))
    portfolio_end_c4 += pos['shares'] * p

cycle4['status'] = 'closed'
cycle4['end_date'] = ROTATION_DATE
cycle4['portfolio_end'] = round(portfolio_end_c4, 2)
cycle4['spy_end'] = round(gspc_apr1, 2)
cycle4['positions_current'] = list(state['positions'].keys())

# Position details
cycle4['positions_detail'] = []
for sell in sell_details:
    cycle4['positions_detail'].append({
        'symbol': sell['symbol'],
        'entry_price': round(sell['entry_price'], 2),
        'exit_price': round(sell['exit_price'], 2),
        'pnl_pct': round(sell['pnl_pct'], 2),
        'exit_reason': 'hold_expired',
        'sector': sell['sector'],
        'days_held': 5,
    })
# Catalyst carried forward
for sym, ep in [('GLD', 405.13), ('DBC', 27.66)]:
    meta = state['position_meta'].get(sym, {})
    ap = apr1_price_map.get(sym, 0)
    pnl = (ap - ep) / ep * 100 if ep > 0 else 0
    cycle4['positions_detail'].append({
        'symbol': sym,
        'entry_price': round(ep, 2),
        'exit_price': round(ap, 2),
        'pnl_pct': round(pnl, 2),
        'exit_reason': 'carried_forward',
        'sector': meta.get('sector', 'Catalyst'),
        'days_held': 8,
    })
# EFA carried
efa_entry = state['position_meta'].get('EFA', {}).get('entry_price', 95.43)
efa_pnl = (98.61 - efa_entry) / efa_entry * 100
cycle4['positions_detail'].append({
    'symbol': 'EFA',
    'entry_price': round(efa_entry, 2),
    'exit_price': 98.61,
    'pnl_pct': round(efa_pnl, 2),
    'exit_reason': 'carried_forward',
    'sector': 'International Equity',
    'days_held': 5,
})

cycle4['exits_by_reason'] = {'rotation': len(sell_details)}
cycle_start = cycle4['portfolio_start']
cycle4['cycle_return_pct'] = round((portfolio_end_c4 - cycle_start) / cycle_start * 100, 2)
spy_start = cycle4['spy_start']
cycle4['spy_return_pct'] = round((gspc_apr1 - spy_start) / spy_start * 100, 2)
cycle4['alpha_pct'] = round(cycle4['cycle_return_pct'] - cycle4['spy_return_pct'], 2)
cycle4['hydra_return'] = round(portfolio_end_c4 - cycle_start, 2)
cycle4['spy_return'] = round(gspc_apr1 - spy_start, 2)
sectors = {}
for d in cycle4['positions_detail']:
    sec = d.get('sector', 'Unknown')
    sectors[sec] = sectors.get(sec, 0) + 1
cycle4['sector_breakdown'] = sectors

# Open cycle 5
cycle5 = {
    'cycle': 5, 'start_date': ROTATION_DATE, 'end_date': None,
    'status': 'active',
    'portfolio_start': round(portfolio_end_c4, 2), 'portfolio_end': None,
    'spy_start': round(gspc_apr1, 2), 'spy_end': None,
    'positions': list(state['positions'].keys()),
    'positions_current': list(state['positions'].keys()),
    'hydra_return': None, 'spy_return': None, 'alpha': None,
    'stop_events': [], 'positions_detail': [],
    'sector_breakdown': {}, 'exits_by_reason': {},
    'cycle_return_pct': None, 'spy_return_pct': None, 'alpha_pct': None,
}
cycles.append(cycle5)

# ===== Save with backups =====
shutil.copy2(STATE_FILE, STATE_FILE + '.bak_pre_retroactive')
shutil.copy2(CYCLE_LOG, CYCLE_LOG + '.bak_pre_retroactive')

tmp = STATE_FILE + '.tmp'
with open(tmp, 'w') as f:
    json.dump(state, f, indent=2)
os.replace(tmp, STATE_FILE)

tmp = CYCLE_LOG + '.tmp'
with open(tmp, 'w') as f:
    json.dump(cycles, f, indent=2)
os.replace(tmp, CYCLE_LOG)

print("\n" + "=" * 60)
print("RETROACTIVE ROTATION COMPLETE")
print("=" * 60)
print(f"Cycle 4: CLOSED (Mar 26 -> Apr 1)")
print(f"  Return: {cycle4['cycle_return_pct']:+.2f}% | SPY: {cycle4['spy_return_pct']:+.2f}% | Alpha: {cycle4['alpha_pct']:+.2f}%")
print(f"Cycle 5: ACTIVE (Apr 1 -> )")
print(f"  Positions: {', '.join(state['positions'].keys())}")
print(f"  Cash: ${state['cash']:,.2f}")
print(f"  Portfolio (Apr 2): ${total_value:,.2f}")
print(f"\nBackups saved: *.bak_pre_retroactive")
