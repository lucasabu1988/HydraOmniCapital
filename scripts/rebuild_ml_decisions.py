"""
Rebuild ML decision log with accurate data from state files and logs.
Covers: Cycle 1 entries, LRCX stop, Cycle 1 exits, Cycle 2 entries.
"""
import json
import uuid
from pathlib import Path

DECISIONS_FILE = "state/ml_learning/decisions.jsonl"
OUTCOMES_FILE = "state/ml_learning/outcomes.jsonl"

records = []
outcomes = []

# ============================================================
# CYCLE 1 ENTRIES — bought at close Mar 5 (entry_day_index=1)
# From state_20260306.json: prices, vol, sectors
# Regime at entry: score=0.50, 4 positions selected
# Selection rationale: top-4 risk-adjusted momentum (90d lookback,
# 5d skip) from 40-stock universe. Only 4 positions because
# regime_score=0.50 → RISK_OFF initially (2 target), but engine
# placed 4 based on startup logic.
# ============================================================

c1_entry_common = {
    'decision_type': 'entry',
    'trading_day': 1,
    'date': '2026-03-05',
    'timestamp': '2026-03-05T15:30:00.000000',
    'regime_score': 0.50,
    'regime_bucket': 'mild_bull',
    'max_positions_target': 5,
    'current_n_positions': 4,
    'portfolio_value': 100000.0,
    'portfolio_drawdown': 0.0,
    'current_leverage': 1.0,
    'crash_cooldown': 0,
    'spy_price': None,
    'spy_sma200': None,
    'spy_vs_sma200_pct': None,
    'spy_sma50': None,
    'spy_10d_vol': None,
    'spy_20d_return': None,
    'days_held': None,
    'current_return': None,
    'high_price': None,
    'drawdown_from_high': None,
    'exit_reason': None,
    'skip_reason': None,
    'skip_universe_rank': None,
    'version': '8.4',
    'source': 'live',
}

c1_stocks = [
    {
        'symbol': 'MRK', 'sector': 'Healthcare',
        'entry_price': 116.07,
        'entry_vol_ann': 0.2864, 'entry_daily_vol': 0.01804,
        'adaptive_stop_pct': -0.06, 'trailing_stop_pct': 0.03,
        'momentum_score': None, 'momentum_rank': None,
    },
    {
        'symbol': 'JNJ', 'sector': 'Healthcare',
        'entry_price': 239.63,
        'entry_vol_ann': 0.1553, 'entry_daily_vol': 0.00979,
        'adaptive_stop_pct': -0.06, 'trailing_stop_pct': 0.03,
        'momentum_score': None, 'momentum_rank': None,
    },
    {
        'symbol': 'LRCX', 'sector': 'Technology',
        'entry_price': 214.68,
        'entry_vol_ann': 0.4929, 'entry_daily_vol': 0.03105,
        'adaptive_stop_pct': -0.07762, 'trailing_stop_pct': 0.03,
        'momentum_score': None, 'momentum_rank': None,
    },
    {
        'symbol': 'GOOGL', 'sector': 'Technology',
        'entry_price': 300.88,
        'entry_vol_ann': 0.2348, 'entry_daily_vol': 0.01479,
        'adaptive_stop_pct': -0.06, 'trailing_stop_pct': 0.03,
        'momentum_score': None, 'momentum_rank': None,
    },
]

for stock in c1_stocks:
    rec = dict(c1_entry_common)
    rec['decision_id'] = uuid.uuid4().hex
    rec.update(stock)
    records.append(rec)

# ============================================================
# CYCLE 1 — LRCX STOP EXIT (Mar 9, trading day 2)
# Sold @ $196.97 (from log), entry=$214.68, return=-8.25%
# Adaptive stop was -7.76% but actual return was -8.25%
# (gap down through stop level)
# SPY context from snapshot: 666.42, sma200=654.52
# ============================================================

lrcx_exit = {
    'decision_id': uuid.uuid4().hex,
    'decision_type': 'exit',
    'timestamp': '2026-03-09T08:35:50.000000',
    'trading_day': 2,
    'date': '2026-03-09',
    'symbol': 'LRCX',
    'sector': 'Technology',
    'regime_score': 0.5478,
    'regime_bucket': 'mild_bull',
    'max_positions_target': 4,
    'current_n_positions': 4,
    'portfolio_value': 99055.19,
    'portfolio_drawdown': -0.00945,
    'current_leverage': 1.0,
    'crash_cooldown': 0,
    'spy_price': 666.42,
    'spy_sma200': 654.52,
    'spy_vs_sma200_pct': 0.01818,
    'spy_sma50': 687.62,
    'spy_10d_vol': 0.1221,
    'spy_20d_return': -0.0350,
    'momentum_score': None,
    'momentum_rank': None,
    'entry_vol_ann': 0.4929,
    'entry_daily_vol': 0.03105,
    'adaptive_stop_pct': -0.07762,
    'trailing_stop_pct': None,
    'days_held': 2,
    'current_return': -0.0825,
    'high_price': 214.68,
    'entry_price': 214.68,
    'drawdown_from_high': -0.0825,
    'exit_reason': 'position_stop',
    'skip_reason': None,
    'skip_universe_rank': None,
    'version': '8.4',
    'source': 'live',
}
records.append(lrcx_exit)

# ============================================================
# CYCLE 1 — HOLD EXPIRED EXITS (Mar 11, trading day 4)
# MRK, JNJ, GOOGL sold at close on Mar 11
# 5-day hold: entry day 1 (Mar 5) → days_held on day 4 = 4
# But wait: HOLD_DAYS=5, days_held = trading_day - entry_day_index + 1
# day 4 - 1 + 1 = 4 → NOT expired yet (need >=5)
# So these actually exited on day 5 (trading_day_counter=5)?
# But state shows cycle completed with trading_day_counter=4.
# The state was manually adjusted (retroactive close at Mar 11).
# Cycle log confirms: end_date=2026-03-11, status=completed.
# Recording as-is from the actual cycle log data.
# ============================================================

c1_exit_common = {
    'decision_type': 'exit',
    'trading_day': 4,
    'date': '2026-03-11',
    'timestamp': '2026-03-11T15:30:00.000000',
    'regime_score': 0.6104,
    'regime_bucket': 'mild_bull',
    'max_positions_target': 5,
    'current_n_positions': 3,
    'portfolio_value': 100954.90,
    'portfolio_drawdown': 0.0,
    'current_leverage': 1.0,
    'crash_cooldown': 0,
    'spy_price': 677.58,
    'spy_sma200': 655.08,
    'spy_vs_sma200_pct': 0.0343,
    'spy_sma50': None,
    'spy_10d_vol': 0.1202,
    'spy_20d_return': -0.0224,
    'trailing_stop_pct': None,
    'exit_reason': 'hold_expired',
    'skip_reason': None,
    'skip_universe_rank': None,
    'version': '8.4',
    'source': 'live',
}

c1_exits = [
    {
        'symbol': 'MRK', 'sector': 'Healthcare',
        'entry_price': 116.07, 'high_price': 118.83,
        'entry_vol_ann': 0.2864, 'entry_daily_vol': 0.01804,
        'adaptive_stop_pct': -0.06,
        'momentum_score': None, 'momentum_rank': None,
    },
    {
        'symbol': 'JNJ', 'sector': 'Healthcare',
        'entry_price': 239.63, 'high_price': 244.845,
        'entry_vol_ann': 0.1553, 'entry_daily_vol': 0.00979,
        'adaptive_stop_pct': -0.06,
        'momentum_score': None, 'momentum_rank': None,
    },
    {
        'symbol': 'GOOGL', 'sector': 'Technology',
        'entry_price': 300.88, 'high_price': 308.80,
        'entry_vol_ann': 0.2348, 'entry_daily_vol': 0.01479,
        'adaptive_stop_pct': -0.06,
        'momentum_score': None, 'momentum_rank': None,
    },
]

for stock in c1_exits:
    rec = dict(c1_exit_common)
    rec['decision_id'] = uuid.uuid4().hex
    rec['days_held'] = 4
    rec['current_return'] = None  # exact exit price not in logs
    rec['drawdown_from_high'] = None
    rec.update(stock)
    records.append(rec)

# ============================================================
# CYCLE 2 ENTRIES — bought at close Mar 11 (entry_day_index=4)
# From compass_state_latest.json: prices, vol, sectors
# Regime: score=0.6104 (mild_bull), RISK_OFF display but 5 positions
# Selection: top-5 risk-adjusted momentum from 40-stock universe
# Notable: JNJ + MRK re-selected (strong healthcare momentum)
#          WMT (consumer staples), XOM (energy), AMAT (tech)
#          Sector diversification: 3 sectors (Healthcare x2, Consumer, Energy, Tech)
#          Sector limit check: Healthcare=2 (under max 3), OK
# ============================================================

c2_entry_common = {
    'decision_type': 'entry',
    'trading_day': 4,
    'date': '2026-03-11',
    'timestamp': '2026-03-11T15:30:00.000000',
    'regime_score': 0.6104,
    'regime_bucket': 'mild_bull',
    'max_positions_target': 5,
    'current_n_positions': 5,
    'portfolio_value': 100954.90,
    'portfolio_drawdown': 0.0,
    'current_leverage': 1.0,
    'crash_cooldown': 0,
    'spy_price': 677.58,
    'spy_sma200': 655.08,
    'spy_vs_sma200_pct': 0.0343,
    'spy_sma50': None,
    'spy_10d_vol': 0.1202,
    'spy_20d_return': -0.0224,
    'days_held': None,
    'current_return': None,
    'high_price': None,
    'drawdown_from_high': None,
    'exit_reason': None,
    'skip_reason': None,
    'skip_universe_rank': None,
    'version': '8.4',
    'source': 'live',
}

c2_stocks = [
    {
        'symbol': 'JNJ', 'sector': 'Healthcare',
        'entry_price': 242.99,
        'entry_vol_ann': 0.172, 'entry_daily_vol': 0.010838,
        'adaptive_stop_pct': -0.06, 'trailing_stop_pct': 0.03,
        'momentum_score': None, 'momentum_rank': None,
    },
    {
        'symbol': 'MRK', 'sector': 'Healthcare',
        'entry_price': 116.21,
        'entry_vol_ann': 0.2593, 'entry_daily_vol': 0.016337,
        'adaptive_stop_pct': -0.06, 'trailing_stop_pct': 0.03,
        'momentum_score': None, 'momentum_rank': None,
    },
    {
        'symbol': 'WMT', 'sector': 'Consumer Staples',
        'entry_price': 123.49,
        'entry_vol_ann': 0.3034, 'entry_daily_vol': 0.019112,
        'adaptive_stop_pct': -0.06, 'trailing_stop_pct': 0.03,
        'momentum_score': None, 'momentum_rank': None,
    },
    {
        'symbol': 'XOM', 'sector': 'Energy',
        'entry_price': 151.58,
        'entry_vol_ann': 0.2872, 'entry_daily_vol': 0.01809,
        'adaptive_stop_pct': -0.06, 'trailing_stop_pct': 0.03,
        'momentum_score': None, 'momentum_rank': None,
    },
    {
        'symbol': 'AMAT', 'sector': 'Technology',
        'entry_price': 351.07,
        'entry_vol_ann': 0.5784, 'entry_daily_vol': 0.036437,
        'adaptive_stop_pct': -0.09109, 'trailing_stop_pct': 0.03,
        'momentum_score': None, 'momentum_rank': None,
    },
]

for stock in c2_stocks:
    rec = dict(c2_entry_common)
    rec['decision_id'] = uuid.uuid4().hex
    rec.update(stock)
    records.append(rec)

# ============================================================
# OUTCOME RECORDS — completed cycle 1 trades
# ============================================================

# LRCX: stopped out day 2
outcomes.append({
    'outcome_id': uuid.uuid4().hex,
    'entry_decision_id': records[2]['decision_id'],  # LRCX entry (index 2)
    'symbol': 'LRCX',
    'sector': 'Technology',
    'entry_date': '2026-03-05',
    'exit_date': '2026-03-09',
    'trading_days_held': 2,
    'gross_return': -0.0825,
    'pnl_usd': -761.53,
    'exit_reason': 'position_stop',
    'entry_regime_score': 0.50,
    'entry_regime_bucket': 'mild_bull',
    'entry_momentum_score': None,
    'entry_momentum_rank': None,
    'entry_vol_ann': 0.4929,
    'entry_daily_vol': 0.03105,
    'entry_portfolio_drawdown': 0.0,
    'entry_spy_vs_sma200': None,
    'entry_adaptive_stop': -0.07762,
    'outcome_label': 'stop_loss',
    'was_stopped': True,
    'was_trailed': False,
    'held_to_expiry': False,
    'beat_spy': False,
    'spy_return_during_hold': -0.035,
    'alpha_vs_spy': -0.0475,
    'version': '8.4',
})

# MRK cycle 1: hold expired
outcomes.append({
    'outcome_id': uuid.uuid4().hex,
    'entry_decision_id': records[0]['decision_id'],  # MRK entry (index 0)
    'symbol': 'MRK',
    'sector': 'Healthcare',
    'entry_date': '2026-03-05',
    'exit_date': '2026-03-11',
    'trading_days_held': 4,
    'gross_return': None,
    'pnl_usd': None,
    'exit_reason': 'hold_expired',
    'entry_regime_score': 0.50,
    'entry_regime_bucket': 'mild_bull',
    'entry_momentum_score': None,
    'entry_momentum_rank': None,
    'entry_vol_ann': 0.2864,
    'entry_daily_vol': 0.01804,
    'entry_portfolio_drawdown': 0.0,
    'entry_spy_vs_sma200': None,
    'entry_adaptive_stop': -0.06,
    'outcome_label': 'hold_expired',
    'was_stopped': False,
    'was_trailed': False,
    'held_to_expiry': True,
    'beat_spy': None,
    'spy_return_during_hold': None,
    'alpha_vs_spy': None,
    'version': '8.4',
})

# JNJ cycle 1: hold expired
outcomes.append({
    'outcome_id': uuid.uuid4().hex,
    'entry_decision_id': records[1]['decision_id'],  # JNJ entry (index 1)
    'symbol': 'JNJ',
    'sector': 'Healthcare',
    'entry_date': '2026-03-05',
    'exit_date': '2026-03-11',
    'trading_days_held': 4,
    'gross_return': None,
    'pnl_usd': None,
    'exit_reason': 'hold_expired',
    'entry_regime_score': 0.50,
    'entry_regime_bucket': 'mild_bull',
    'entry_momentum_score': None,
    'entry_momentum_rank': None,
    'entry_vol_ann': 0.1553,
    'entry_daily_vol': 0.00979,
    'entry_portfolio_drawdown': 0.0,
    'entry_spy_vs_sma200': None,
    'entry_adaptive_stop': -0.06,
    'outcome_label': 'hold_expired',
    'was_stopped': False,
    'was_trailed': False,
    'held_to_expiry': True,
    'beat_spy': None,
    'spy_return_during_hold': None,
    'alpha_vs_spy': None,
    'version': '8.4',
})

# GOOGL cycle 1: hold expired
outcomes.append({
    'outcome_id': uuid.uuid4().hex,
    'entry_decision_id': records[3]['decision_id'],  # GOOGL entry (index 3)
    'symbol': 'GOOGL',
    'sector': 'Technology',
    'entry_date': '2026-03-05',
    'exit_date': '2026-03-11',
    'trading_days_held': 4,
    'gross_return': None,
    'pnl_usd': None,
    'exit_reason': 'hold_expired',
    'entry_regime_score': 0.50,
    'entry_regime_bucket': 'mild_bull',
    'entry_momentum_score': None,
    'entry_momentum_rank': None,
    'entry_vol_ann': 0.2348,
    'entry_daily_vol': 0.01479,
    'entry_portfolio_drawdown': 0.0,
    'entry_spy_vs_sma200': None,
    'entry_adaptive_stop': -0.06,
    'outcome_label': 'hold_expired',
    'was_stopped': False,
    'was_trailed': False,
    'held_to_expiry': True,
    'beat_spy': None,
    'spy_return_during_hold': None,
    'alpha_vs_spy': None,
    'version': '8.4',
})

# ============================================================
# WRITE FILES
# ============================================================

with open(DECISIONS_FILE, 'w') as f:
    for r in records:
        f.write(json.dumps(r) + '\n')

with open(OUTCOMES_FILE, 'w') as f:
    for o in outcomes:
        f.write(json.dumps(o) + '\n')

print(f"Written {len(records)} decision records:")
for r in records:
    reason = r.get('exit_reason') or 'momentum_entry'
    print(f"  {r['decision_type']:5s} | {r['date']} | {r['symbol']:5s} | {reason}")
print()
print(f"Written {len(outcomes)} outcome records:")
for o in outcomes:
    print(f"  {o['symbol']:5s} | {o['entry_date']} -> {o['exit_date']} | {o['exit_reason']}")
