"""
COMPASS v8.2 — Cloud Dashboard (Read-Only)
============================================
Lightweight Flask dashboard for Render deployment.
Shows backtest equity curves, COMPASS vs S&P 500 comparison,
and static state data. NO live trading engine.

Deploy: git push to GitHub, connect to Render.
"""

from flask import Flask, jsonify, render_template
import json
import os
import numpy as np
import pandas as pd
from datetime import datetime

app = Flask(__name__)

# ============================================================================
# COMPASS v8.2 PARAMETERS (read-only reference)
# ============================================================================

COMPASS_CONFIG = {
    'HOLD_DAYS': 5,
    'POSITION_STOP_LOSS': -0.08,
    'TRAILING_ACTIVATION': 0.05,
    'TRAILING_STOP_PCT': 0.03,
    'PORTFOLIO_STOP_LOSS': -0.15,
    'RECOVERY_STAGE_1_DAYS': 63,
    'RECOVERY_STAGE_2_DAYS': 126,
    'NUM_POSITIONS': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'TARGET_VOL': 0.15,
    'LEVERAGE_MIN': 0.3,
    'LEVERAGE_MAX': 2.0,
    'INITIAL_CAPITAL': 100_000,
}

STATE_FILE = 'state/compass_state_latest.json'
STATE_DIR = 'state'


# ============================================================================
# STATE READER
# ============================================================================

def read_state():
    """Read latest state from JSON file (bundled with deploy)."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None


# ============================================================================
# DERIVED CALCULATIONS
# ============================================================================

def compute_position_details(state, prices=None):
    """Compute enriched position data for display."""
    positions = state.get('positions', {})
    position_meta = state.get('position_meta', {})
    trading_day = state.get('trading_day_counter', 0)

    results = []
    for symbol, pos_data in positions.items():
        meta = position_meta.get(symbol, {})
        entry_price = meta.get('entry_price', pos_data.get('avg_cost', 0))
        high_price = meta.get('high_price', entry_price)
        entry_day_index = meta.get('entry_day_index', 0)
        entry_date = meta.get('entry_date', '')
        shares = pos_data.get('shares', 0)
        current_price = (prices or {}).get(symbol, entry_price)

        if current_price and entry_price and entry_price > 0:
            pnl_pct = (current_price - entry_price) / entry_price
            pnl_dollar = (current_price - entry_price) * shares
            market_value = current_price * shares
        else:
            pnl_pct = 0
            pnl_dollar = 0
            market_value = entry_price * shares if entry_price else 0
            current_price = current_price or entry_price or 0

        days_held = trading_day - entry_day_index
        days_remaining = max(0, COMPASS_CONFIG['HOLD_DAYS'] - days_held)

        trailing_active = high_price > entry_price * (1 + COMPASS_CONFIG['TRAILING_ACTIVATION'])
        trailing_stop_level = high_price * (1 - COMPASS_CONFIG['TRAILING_STOP_PCT']) if trailing_active else None
        position_stop_level = entry_price * (1 + COMPASS_CONFIG['POSITION_STOP_LOSS'])

        near_stop = False
        if current_price:
            if trailing_stop_level and current_price < trailing_stop_level * 1.01:
                near_stop = True
            if current_price < position_stop_level * 1.01:
                near_stop = True

        results.append({
            'symbol': symbol,
            'shares': round(shares, 1),
            'entry_price': round(entry_price, 2),
            'current_price': round(current_price, 2),
            'market_value': round(market_value, 0),
            'pnl_dollar': round(pnl_dollar, 0),
            'pnl_pct': round(pnl_pct * 100, 2),
            'days_held': days_held,
            'days_remaining': days_remaining,
            'high_price': round(high_price, 2),
            'trailing_active': trailing_active,
            'trailing_stop_level': round(trailing_stop_level, 2) if trailing_stop_level else None,
            'position_stop_level': round(position_stop_level, 2),
            'entry_date': entry_date,
            'near_stop': near_stop,
        })

    results.sort(key=lambda x: x['pnl_pct'], reverse=True)
    return results


def compute_portfolio_metrics(state, prices=None):
    """Compute portfolio-level dashboard metrics."""
    portfolio_value = state.get('portfolio_value', 0)
    peak_value = state.get('peak_value', 0)
    cash = state.get('cash', 0)
    initial_capital = COMPASS_CONFIG['INITIAL_CAPITAL']

    drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0
    total_return = (portfolio_value - initial_capital) / initial_capital if initial_capital > 0 else 0

    invested = 0
    positions = state.get('positions', {})
    for sym, pos in positions.items():
        price = (prices or {}).get(sym, pos.get('avg_cost', 0))
        invested += pos.get('shares', 0) * price

    recovery = None
    if state.get('in_protection') and state.get('stop_loss_day_index') is not None:
        days_since_stop = state['trading_day_counter'] - state['stop_loss_day_index']
        stage = state.get('protection_stage', 1)
        if stage == 1:
            target_days = COMPASS_CONFIG['RECOVERY_STAGE_1_DAYS']
            next_stage = 'Stage 2 (1.0x leverage, 3 positions)'
        else:
            target_days = COMPASS_CONFIG['RECOVERY_STAGE_2_DAYS']
            next_stage = 'Full Recovery (vol targeting)'
        pct = min(1.0, days_since_stop / target_days) if target_days > 0 else 0
        recovery = {
            'stage': stage,
            'days_elapsed': days_since_stop,
            'days_needed': target_days,
            'days_remaining': max(0, target_days - days_since_stop),
            'pct': round(pct * 100, 1),
            'next_stage': next_stage,
        }

    regime_str = 'RISK_ON' if state.get('current_regime', True) else 'RISK_OFF'

    if state.get('in_protection'):
        leverage = 0.3 if state.get('protection_stage') == 1 else 1.0
    elif not state.get('current_regime', True):
        leverage = 1.0
    else:
        leverage = None

    if state.get('in_protection'):
        max_pos = 2 if state.get('protection_stage') == 1 else 3
    elif not state.get('current_regime', True):
        max_pos = COMPASS_CONFIG['NUM_POSITIONS_RISK_OFF']
    else:
        max_pos = COMPASS_CONFIG['NUM_POSITIONS']

    return {
        'portfolio_value': round(portfolio_value, 2),
        'cash': round(cash, 2),
        'invested': round(invested, 2),
        'peak_value': round(peak_value, 2),
        'drawdown': round(drawdown * 100, 2),
        'total_return': round(total_return * 100, 2),
        'initial_capital': initial_capital,
        'num_positions': len(positions),
        'max_positions': max_pos,
        'regime': regime_str,
        'regime_consecutive': state.get('regime_consecutive', 0),
        'in_protection': state.get('in_protection', False),
        'protection_stage': state.get('protection_stage', 0),
        'leverage': leverage,
        'recovery': recovery,
        'trading_day': state.get('trading_day_counter', 0),
        'last_trading_date': state.get('last_trading_date'),
        'stop_events': state.get('stop_events', []),
        'timestamp': state.get('timestamp', ''),
        'uptime_minutes': state.get('stats', {}).get('uptime_minutes', 0),
    }


# ============================================================================
# FLASK ROUTES
# ============================================================================

@app.route('/')
def index():
    state = read_state()
    return render_template('dashboard.html', has_state=state is not None)


@app.route('/api/state')
def api_state():
    state = read_state()

    if not state:
        return jsonify({
            'status': 'offline',
            'error': 'No state file found',
            'server_time': datetime.now().isoformat(),
            'engine': {'running': False, 'started_at': None, 'error': 'Cloud mode — no live engine', 'cycles': 0},
        })

    position_details = compute_position_details(state)
    portfolio = compute_portfolio_metrics(state)

    return jsonify({
        'status': 'online',
        'portfolio': portfolio,
        'position_details': position_details,
        'prices': {},
        'universe': state.get('current_universe', []),
        'universe_year': state.get('universe_year'),
        'config': COMPASS_CONFIG,
        'chassis': {},
        'server_time': datetime.now().isoformat(),
        'engine': {'running': False, 'started_at': None, 'error': 'Cloud mode — view only', 'cycles': 0},
    })


@app.route('/api/logs')
def api_logs():
    return jsonify({'logs': []})


@app.route('/api/equity')
def api_equity():
    csv_path = os.path.join('backtests', 'v8_compass_daily.csv')
    if not os.path.exists(csv_path):
        return jsonify({'equity': [], 'milestones': [], 'error': 'No backtest data'})

    try:
        df = pd.read_csv(csv_path, parse_dates=['date'])
    except Exception:
        return jsonify({'equity': [], 'milestones': [], 'error': 'Failed to read CSV'})

    val_col = 'portfolio_value' if 'portfolio_value' in df.columns else 'value'
    df = df[df['date'] >= '2016-01-01'].copy()

    milestones = []
    vals = df[val_col]

    for target in [1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000]:
        crossed = df[vals >= target]
        if len(crossed) > 0:
            row = crossed.iloc[0]
            milestones.append({
                'date': row['date'].strftime('%Y-%m-%d'),
                'value': round(float(row[val_col]), 0),
                'label': f'${target/1e6:.0f}M',
                'type': 'milestone',
            })

    peak = vals.expanding().max()
    dd = (vals - peak) / peak
    in_dd = False
    dd_events = []
    for idx in df.index:
        if dd[idx] < -0.15 and not in_dd:
            in_dd = True
            dd_start_idx = idx
        elif dd[idx] >= -0.02 and in_dd:
            in_dd = False
            mask = (df.index >= dd_start_idx) & (df.index <= idx)
            worst_idx = dd[mask].idxmin()
            worst_row = df.loc[worst_idx]
            worst_dd = dd[worst_idx]
            dd_events.append({
                'date': worst_row['date'].strftime('%Y-%m-%d'),
                'value': round(float(worst_row[val_col]), 0),
                'dd_pct': round(float(worst_dd * 100), 1),
            })

    for ev in dd_events:
        d = ev['date']
        if '2020-03' in d:
            ev['label'] = f'COVID Crash {ev["dd_pct"]}%'
        elif '2023' in d:
            ev['label'] = f'Max Drawdown {ev["dd_pct"]}%'
        elif '2024-08' in d or '2024-09' in d:
            ev['label'] = f'Correction {ev["dd_pct"]}%'
        elif '2025' in d:
            ev['label'] = f'Tariff Crisis {ev["dd_pct"]}%'
        else:
            ev['label'] = f'Drawdown {ev["dd_pct"]}%'
        ev['type'] = 'drawdown'
        milestones.append(ev)

    ath_idx = vals.idxmax()
    ath_row = df.loc[ath_idx]
    milestones.append({
        'date': ath_row['date'].strftime('%Y-%m-%d'),
        'value': round(float(ath_row[val_col]), 0),
        'label': f'ATH ${ath_row[val_col]/1e6:.1f}M',
        'type': 'ath',
    })

    sampled = df.iloc[::5]
    equity = []
    for _, row in sampled.iterrows():
        equity.append({
            'date': row['date'].strftime('%Y-%m-%d'),
            'value': round(float(row[val_col]), 0),
        })

    return jsonify({'equity': equity, 'milestones': milestones})


@app.route('/api/equity-comparison')
def api_equity_comparison():
    csv_path = os.path.join('backtests', 'v8_compass_daily.csv')
    spy_csv = os.path.join('backtests', 'spy_benchmark.csv')

    if not os.path.exists(csv_path):
        return jsonify({'error': 'No backtest data'})
    if not os.path.exists(spy_csv):
        return jsonify({'error': 'No SPY benchmark data'})

    try:
        df = pd.read_csv(csv_path, parse_dates=['date'])
        spy_df = pd.read_csv(spy_csv, parse_dates=['date'])
    except Exception as e:
        return jsonify({'error': f'Failed to read CSV: {str(e)}'})

    val_col = 'portfolio_value' if 'portfolio_value' in df.columns else 'value'

    df['date_key'] = df['date'].dt.normalize()
    spy_df['date_key'] = spy_df['date'].dt.normalize()

    merged = pd.merge(df[['date_key', val_col]], spy_df[['date_key', 'close']],
                       on='date_key', how='inner')

    if merged.empty:
        return jsonify({'error': 'No overlapping dates'})

    merged = merged[merged['date_key'] >= '2016-01-01'].copy()
    if merged.empty:
        return jsonify({'error': 'No data from 2016 onward'})

    compass_start = float(merged[val_col].iloc[0])
    spy_start = float(merged['close'].iloc[0])

    merged['compass_val'] = merged[val_col]
    merged['spy_val'] = merged['close'] / spy_start * compass_start

    compass_final = float(merged['compass_val'].iloc[-1])
    spy_final = float(merged['spy_val'].iloc[-1])
    first_date = merged['date_key'].iloc[0]
    last_date = merged['date_key'].iloc[-1]
    years = (last_date - first_date).days / 365.25

    compass_cagr = (pow(compass_final / compass_start, 1 / years) - 1) * 100 if years > 0 else 0
    spy_cagr = (pow(spy_final / compass_start, 1 / years) - 1) * 100 if years > 0 else 0

    sampled = merged.iloc[::5]
    result = []
    for _, row in sampled.iterrows():
        result.append({
            'date': row['date_key'].strftime('%Y-%m-%d'),
            'compass': round(float(row['compass_val']), 0),
            'spy': round(float(row['spy_val']), 0),
        })

    return jsonify({
        'data': result,
        'compass_cagr': round(compass_cagr, 2),
        'spy_cagr': round(spy_cagr, 2),
        'compass_final': round(compass_final, 0),
        'spy_final': round(spy_final, 0),
        'years': round(years, 1),
    })


@app.route('/api/backtest/status')
def api_backtest_status():
    return jsonify({
        'running': False,
        'last_result': 'cloud mode',
        'last_run_date': None,
    })


@app.route('/api/social-feed')
def api_social_feed():
    return jsonify({'messages': [], 'symbols': []})


@app.route('/api/news')
def api_news():
    return api_social_feed()


@app.route('/api/engine/start', methods=['POST'])
def api_engine_start():
    return jsonify({'ok': False, 'message': 'Engine disabled in cloud mode'})


@app.route('/api/engine/stop', methods=['POST'])
def api_engine_stop():
    return jsonify({'ok': False, 'message': 'Engine disabled in cloud mode'})


@app.route('/api/engine/status')
def api_engine_status():
    return jsonify({'running': False, 'started_at': None, 'error': 'Cloud mode — view only', 'cycles': 0})


@app.route('/api/preflight')
def api_preflight():
    return jsonify({'ready': False, 'checks': {}, 'server_time': datetime.now().isoformat()})


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 60)
    print("COMPASS v8.2 — Cloud Dashboard (Read-Only)")
    print("=" * 60)
    print(f"Port: {port}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False)
