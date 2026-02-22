"""
COMPASS v8.2 - AMPLIFICATION TEST
===================================
3 variants that amplify existing strengths (not change signals):

V1: CONVICTION SIZING - Weight positions by momentum score * inverse vol
V2: SECTOR GUARD - Max 2 positions per sector to reduce concentration risk
V3: ADAPTIVE HOLD - Extend hold to 7d when position is winning > 3%

Compared against BASE v8.2 (unchanged).
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')
import time as time_module

# ============================================================================
# PARAMETERS (v8.2 base)
# ============================================================================

TOP_N = 40
MIN_AGE_DAYS = 63
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03
PORTFOLIO_STOP_LOSS = -0.15
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 2.0
VOL_LOOKBACK = 20
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# Variant parameters
ADAPTIVE_HOLD_EXTENDED = 7     # V3: extended hold days
ADAPTIVE_HOLD_THRESHOLD = 0.03 # V3: +3% gain to extend
MAX_PER_SECTOR = 2             # V2: max positions per sector

BROAD_POOL = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'AMD',
    'INTC', 'CSCO', 'IBM', 'TXN', 'QCOM', 'ORCL', 'ACN', 'NOW', 'INTU',
    'AMAT', 'MU', 'LRCX', 'SNPS', 'CDNS', 'KLAC', 'MRVL',
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
    'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG',
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'AMGN', 'BMY', 'MDT', 'ISRG', 'SYK', 'GILD', 'REGN', 'VRTX', 'BIIB',
    'AMZN', 'TSLA', 'WMT', 'HD', 'PG', 'COST', 'KO', 'PEP', 'NKE',
    'MCD', 'DIS', 'SBUX', 'TGT', 'LOW', 'CL', 'KMB', 'GIS', 'EL',
    'MO', 'PM',
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'PSX', 'VLO',
    'GE', 'CAT', 'BA', 'HON', 'UNP', 'RTX', 'LMT', 'DE', 'UPS', 'FDX',
    'MMM', 'GD', 'NOC', 'EMR',
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    'VZ', 'T', 'TMUS', 'CMCSA',
]

# Sector mapping for V2
SECTOR_MAP = {}
_tech = ['AAPL','MSFT','NVDA','GOOGL','META','AVGO','ADBE','CRM','AMD','INTC',
         'CSCO','IBM','TXN','QCOM','ORCL','ACN','NOW','INTU','AMAT','MU',
         'LRCX','SNPS','CDNS','KLAC','MRVL']
_fin  = ['BRK-B','JPM','V','MA','BAC','WFC','GS','MS','AXP','BLK','SCHW','C',
         'USB','PNC','TFC','CB','MMC','AIG']
_hc   = ['UNH','JNJ','LLY','ABBV','MRK','PFE','TMO','ABT','DHR','AMGN','BMY',
         'MDT','ISRG','SYK','GILD','REGN','VRTX','BIIB']
_con  = ['AMZN','TSLA','WMT','HD','PG','COST','KO','PEP','NKE','MCD','DIS',
         'SBUX','TGT','LOW','CL','KMB','GIS','EL','MO','PM']
_nrg  = ['XOM','CVX','COP','SLB','EOG','OXY','MPC','PSX','VLO']
_ind  = ['GE','CAT','BA','HON','UNP','RTX','LMT','DE','UPS','FDX','MMM','GD',
         'NOC','EMR']
_util = ['NEE','DUK','SO','D','AEP']
_tel  = ['VZ','T','TMUS','CMCSA']
for s in _tech: SECTOR_MAP[s] = 'TECH'
for s in _fin:  SECTOR_MAP[s] = 'FIN'
for s in _hc:   SECTOR_MAP[s] = 'HC'
for s in _con:  SECTOR_MAP[s] = 'CON'
for s in _nrg:  SECTOR_MAP[s] = 'NRG'
for s in _ind:  SECTOR_MAP[s] = 'IND'
for s in _util: SECTOR_MAP[s] = 'UTIL'
for s in _tel:  SECTOR_MAP[s] = 'TEL'

print("=" * 80)
print("COMPASS v8.2 - AMPLIFICATION TEST")
print("V1: Conviction Sizing | V2: Sector Guard | V3: Adaptive Hold")
print("=" * 80)


# ============================================================================
# DATA
# ============================================================================

def load_data():
    cache_file = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'
    if os.path.exists(cache_file):
        print("[Cache] Loading broad pool...")
        with open(cache_file, 'rb') as f:
            price_data = pickle.load(f)
    else:
        raise RuntimeError("No cache found. Run omnicapital_v8_compass.py first.")

    spy_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    spy_data = pd.read_csv(spy_file, index_col=0, parse_dates=True)
    return price_data, spy_data


def compute_annual_top40(price_data):
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))
    annual_universe = {}
    for year in years:
        if year == years[0]:
            re = pd.Timestamp(f'{year}-02-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            rs = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        else:
            re = pd.Timestamp(f'{year}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            rs = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        scores = {}
        for symbol, df in price_data.items():
            mask = (df.index >= rs) & (df.index < re)
            window = df.loc[mask]
            if len(window) < 20: continue
            scores[symbol] = (window['Close'] * window['Volume']).mean()
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        annual_universe[year] = [s for s, _ in ranked[:TOP_N]]
    return annual_universe


# ============================================================================
# ENGINE FUNCTIONS (shared)
# ============================================================================

def compute_regime(spy_data):
    spy_close = spy_data['Close']
    sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean()
    raw_signal = spy_close > sma200
    regime = pd.Series(index=spy_close.index, dtype=bool)
    regime.iloc[:REGIME_SMA_PERIOD] = True
    current_regime = True
    consecutive_count = 0
    last_raw = True
    for i in range(REGIME_SMA_PERIOD, len(raw_signal)):
        raw = raw_signal.iloc[i]
        if pd.isna(raw):
            regime.iloc[i] = current_regime
            continue
        if raw == last_raw:
            consecutive_count += 1
        else:
            consecutive_count = 1
            last_raw = raw
        if raw != current_regime and consecutive_count >= REGIME_CONFIRM_DAYS:
            current_regime = raw
        regime.iloc[i] = current_regime
    return regime


def compute_momentum_scores(price_data, tradeable, date, date_idx):
    scores = {}
    for symbol in tradeable:
        if symbol not in price_data: continue
        df = price_data[symbol]
        if date not in df.index: continue
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue
        needed = MOMENTUM_LOOKBACK + MOMENTUM_SKIP
        if sym_idx < needed: continue
        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - MOMENTUM_SKIP]
        close_lookback = df['Close'].iloc[sym_idx - MOMENTUM_LOOKBACK]
        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0: continue
        momentum_90d = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        scores[symbol] = momentum_90d - skip_5d
    return scores


def compute_volatility_weights(price_data, selected, date):
    vols = {}
    for symbol in selected:
        if symbol not in price_data: continue
        df = price_data[symbol]
        if date not in df.index: continue
        sym_idx = df.index.get_loc(date)
        if sym_idx < VOL_LOOKBACK + 1: continue
        returns = df['Close'].iloc[sym_idx - VOL_LOOKBACK:sym_idx + 1].pct_change().dropna()
        if len(returns) < VOL_LOOKBACK - 2: continue
        vol = returns.std() * np.sqrt(252)
        if vol > 0.01:
            vols[symbol] = vol
    if not vols:
        return {s: 1.0 / len(selected) for s in selected}
    raw_weights = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw_weights.values())
    return {s: w / total for s, w in raw_weights.items()}


def compute_dynamic_leverage(spy_data, date):
    if date not in spy_data.index: return 1.0
    idx = spy_data.index.get_loc(date)
    if idx < VOL_LOOKBACK + 1: return 1.0
    returns = spy_data['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
    if len(returns) < VOL_LOOKBACK - 2: return 1.0
    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol < 0.01: return LEVERAGE_MAX
    leverage = TARGET_VOL / realized_vol
    return max(LEVERAGE_MIN, min(LEVERAGE_MAX, leverage))


def get_tradeable(price_data, date, first_date, annual_universe):
    eligible = set(annual_universe.get(date.year, []))
    tradeable = []
    for symbol in eligible:
        if symbol not in price_data: continue
        df = price_data[symbol]
        if date not in df.index: continue
        days_since = (date - df.index[0]).days
        if date <= first_date + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since >= MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


# ============================================================================
# PARAMETERIZED BACKTEST ENGINE
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data, regime,
                 all_dates, first_date, label,
                 use_conviction=False,
                 use_sector_guard=False,
                 use_adaptive_hold=False):
    """Run backtest with optional amplification variants."""

    t0 = time_module.time()
    print(f"\n{'='*60}")
    print(f"  RUNNING: {label}")
    print(f"{'='*60}")

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []

    peak_value = float(INITIAL_CAPITAL)
    in_protection_mode = False
    protection_stage = 0
    stop_loss_day_index = None
    post_stop_base = None

    for i, date in enumerate(all_dates):
        tradeable_symbols = get_tradeable(price_data, date, first_date, annual_universe)

        # Portfolio value
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                portfolio_value += pos['shares'] * price_data[symbol].loc[date, 'Close']

        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # Recovery
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = bool(regime.loc[date]) if date in regime.index else True
            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2
            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # Portfolio stop
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({'date': date, 'value': portfolio_value, 'dd': drawdown})
            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    ep = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    proceeds = pos['shares'] * ep
                    comm = pos['shares'] * COMMISSION_PER_SHARE
                    cash += proceeds - comm
                    pnl = (ep - pos['entry_price']) * pos['shares'] - comm
                    trades.append({'symbol': symbol, 'exit_reason': 'portfolio_stop',
                                   'pnl': pnl, 'ret': pnl / (pos['entry_price'] * pos['shares'])})
                del positions[symbol]
            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i

        # Regime
        is_risk_on = bool(regime.loc[date]) if date in regime.index else True

        # Leverage & positions
        if in_protection_mode:
            if protection_stage == 1:
                max_positions = 2; current_leverage = 0.3
            else:
                max_positions = 3; current_leverage = 1.0
        elif not is_risk_on:
            max_positions = NUM_POSITIONS_RISK_OFF; current_leverage = 1.0
        else:
            max_positions = NUM_POSITIONS
            current_leverage = compute_dynamic_leverage(spy_data, date)

        # Margin cost
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            cash -= MARGIN_RATE / 252 * borrowed

        # --- CLOSE POSITIONS ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue
            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            # Hold time
            days_held = i - pos['entry_idx']

            if use_adaptive_hold:
                # V3: Extend hold if winning > threshold
                pos_return = (current_price - pos['entry_price']) / pos['entry_price']
                hold_limit = ADAPTIVE_HOLD_EXTENDED if pos_return >= ADAPTIVE_HOLD_THRESHOLD else HOLD_DAYS
            else:
                hold_limit = HOLD_DAYS

            if days_held >= hold_limit:
                exit_reason = 'hold_expired'

            # Position stop
            pos_return_chk = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return_chk <= POSITION_STOP_LOSS:
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

            # Excess positions
            if exit_reason is None and len(positions) > max_positions:
                pos_rets = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        pos_rets[s] = (price_data[s].loc[date, 'Close'] - p['entry_price']) / p['entry_price']
                worst = min(pos_rets, key=pos_rets.get)
                if symbol == worst:
                    exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                comm = shares * COMMISSION_PER_SHARE
                cash += proceeds - comm
                pnl = (current_price - pos['entry_price']) * shares - comm
                trades.append({'symbol': symbol, 'exit_reason': exit_reason,
                               'pnl': pnl, 'ret': pnl / (pos['entry_price'] * shares)})
                del positions[symbol]

        # --- OPEN NEW POSITIONS ---
        needed = max_positions - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            scores = compute_momentum_scores(price_data, tradeable_symbols, date, i)
            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

            if use_sector_guard:
                # V2: Count current sector exposure
                sector_count = {}
                for s in positions:
                    sec = SECTOR_MAP.get(s, 'OTHER')
                    sector_count[sec] = sector_count.get(sec, 0) + 1
                # Filter out stocks from sectors already at max
                filtered = {}
                for s, sc in available_scores.items():
                    sec = SECTOR_MAP.get(s, 'OTHER')
                    if sector_count.get(sec, 0) < MAX_PER_SECTOR:
                        filtered[s] = sc
                available_scores = filtered

            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]
                selected_scores = {s: sc for s, sc in ranked[:needed]}

                if use_conviction:
                    # V1: Conviction sizing = inverse_vol * momentum_score_weight
                    vol_weights = compute_volatility_weights(price_data, selected, date)
                    # Normalize momentum scores to [0,1] range for weighting
                    score_vals = [selected_scores[s] for s in selected]
                    min_sc = min(score_vals)
                    max_sc = max(score_vals)
                    range_sc = max_sc - min_sc if max_sc > min_sc else 1.0
                    score_weights = {s: 0.5 + 0.5 * ((selected_scores[s] - min_sc) / range_sc)
                                     for s in selected}
                    # Combine: conviction = vol_weight * score_weight
                    combined = {s: vol_weights.get(s, 1/len(selected)) * score_weights[s]
                                for s in selected}
                    total_c = sum(combined.values())
                    weights = {s: c / total_c for s, c in combined.items()}
                else:
                    weights = compute_volatility_weights(price_data, selected, date)

                effective_capital = cash * current_leverage * 0.95

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue
                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0: continue
                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = effective_capital * weight
                    max_per_position = cash * 0.40
                    position_value = min(position_value, max_per_position)
                    shares = position_value / entry_price
                    cost = shares * entry_price
                    comm = shares * COMMISSION_PER_SHARE
                    if cost + comm <= cash * 0.90:
                        positions[symbol] = {
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + comm

        portfolio_values.append({
            'date': date, 'value': portfolio_value, 'drawdown': drawdown
        })

        if i % 1260 == 0 and i > 0:
            print(f"  [{label}] Day {i}: ${portfolio_value:,.0f} | DD: {drawdown:.1%}")

    elapsed = time_module.time() - t0
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    pv_df = pd.DataFrame(portfolio_values)

    print(f"  [{label}] DONE: ${portfolio_values[-1]['value']:,.0f} | "
          f"Trades: {len(trades_df)} | Stops: {len(stop_events)}")
    print(f"  Time: {elapsed:.0f}s")

    return pv_df, trades_df, stop_events


# ============================================================================
# METRICS
# ============================================================================

def calc_metrics(pv_df, trades_df, stops):
    df = pv_df.set_index('date')
    final = df['value'].iloc[-1]
    years = len(df) / 252
    cagr = (final / INITIAL_CAPITAL) ** (1 / years) - 1
    rets = df['value'].pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    max_dd = df['drawdown'].min()
    sharpe = cagr / vol if vol > 0 else 0
    downside = rets[rets < 0]
    ds_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else vol
    sortino = cagr / ds_vol if ds_vol > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0

    # Annual returns
    ann = df['value'].resample('YE').last().pct_change().dropna()
    best_yr = ann.max() if len(ann) > 0 else 0
    worst_yr = ann.min() if len(ann) > 0 else 0

    # Position stop stats
    pos_stops = trades_df[trades_df['exit_reason'] == 'position_stop'] if len(trades_df) > 0 else pd.DataFrame()
    pos_stop_pct = len(pos_stops) / len(trades_df) * 100 if len(trades_df) > 0 else 0

    return {
        'final': final, 'cagr': cagr, 'sharpe': sharpe, 'sortino': sortino,
        'max_dd': max_dd, 'calmar': calmar, 'vol': vol,
        'win_rate': win_rate, 'avg_trade': avg_trade,
        'trades': len(trades_df), 'stops': len(stops),
        'best_yr': best_yr, 'worst_yr': worst_yr,
        'pos_stop_pct': pos_stop_pct,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    price_data, spy_data = load_data()
    print(f"Price data: {len(price_data)} symbols")
    print(f"SPY: {len(spy_data)} days")

    annual_universe = compute_annual_top40(price_data)

    # All dates
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    regime = compute_regime(spy_data)

    # ---- Run all 4 configs ----
    configs = [
        ("BASE",       dict(use_conviction=False, use_sector_guard=False, use_adaptive_hold=False)),
        ("V1:Convict", dict(use_conviction=True,  use_sector_guard=False, use_adaptive_hold=False)),
        ("V2:Sector",  dict(use_conviction=False, use_sector_guard=True,  use_adaptive_hold=False)),
        ("V3:AdapHold",dict(use_conviction=False, use_sector_guard=False, use_adaptive_hold=True)),
    ]

    results = {}
    for label, kwargs in configs:
        pv, tr, st = run_backtest(
            price_data, annual_universe, spy_data, regime,
            all_dates, first_date, label, **kwargs
        )
        results[label] = calc_metrics(pv, tr, st)

    # ---- Comparison table ----
    base = results["BASE"]
    print("\n\n" + "=" * 100)
    print("  AMPLIFICATION COMPARISON")
    print("=" * 100)

    metrics_list = [
        ('Final Value',  'final',    lambda v: f"${v:,.0f}"),
        ('CAGR',         'cagr',     lambda v: f"{v:.2%}"),
        ('Sharpe',       'sharpe',   lambda v: f"{v:.3f}"),
        ('Sortino',      'sortino',  lambda v: f"{v:.3f}"),
        ('Max Drawdown', 'max_dd',   lambda v: f"{v:.1%}"),
        ('Calmar',       'calmar',   lambda v: f"{v:.3f}"),
        ('Volatility',   'vol',      lambda v: f"{v:.2%}"),
        ('Win Rate',     'win_rate', lambda v: f"{v:.1%}"),
        ('Avg Trade',    'avg_trade',lambda v: f"${v:,.0f}"),
        ('Trades',       'trades',   lambda v: f"{v:,}"),
        ('Stop Events',  'stops',    lambda v: f"{v}"),
        ('Pos Stop %',   'pos_stop_pct', lambda v: f"{v:.1f}%"),
        ('Best Year',    'best_yr',  lambda v: f"{v:.1%}"),
        ('Worst Year',   'worst_yr', lambda v: f"{v:.1%}"),
    ]

    labels = list(results.keys())
    col = 18
    header = f"{'Metric':<20}"
    for lb in labels:
        header += f"{lb:>{col}}"
    print(f"\n{header}")
    print("-" * (20 + col * len(labels)))

    for name, key, fmt in metrics_list:
        row = f"{name:<20}"
        for lb in labels:
            row += f"{fmt(results[lb][key]):>{col}}"
        print(row)

    # Delta rows
    print()
    delta_metrics = [
        ('d_Sharpe', 'sharpe', lambda d: f"{d:+.3f}"),
        ('d_CAGR',   'cagr',   lambda d: f"{d:+.2%}"),
        ('d_MaxDD',  'max_dd', lambda d: f"{d:+.1%}"),
        ('d_Calmar', 'calmar', lambda d: f"{d:+.3f}"),
    ]
    for name, key, fmt in delta_metrics:
        row = f"{name:<20}"
        for lb in labels:
            if lb == "BASE":
                row += f"{'---':>{col}}"
            else:
                delta = results[lb][key] - base[key]
                row += f"{fmt(delta):>{col}}"
        print(row)

    print("=" * 100)

    # ---- Save chart ----
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(14, 6))
        fig.patch.set_facecolor('#0a0a0a')
        ax.set_facecolor('#0a0a0a')

        colors = {'BASE': '#888888', 'V1:Convict': '#00ff41',
                  'V2:Sector': '#4488ff', 'V3:AdapHold': '#ff8c00'}

        # Re-run to get pv data for chart
        for label, kwargs in configs:
            pv, _, _ = run_backtest(
                price_data, annual_universe, spy_data, regime,
                all_dates, first_date, label, **kwargs
            )
            ax.plot(pv['date'], pv['value'], label=label, color=colors.get(label, '#fff'),
                    linewidth=1.5 if label != 'BASE' else 2, alpha=0.9)

        ax.set_yscale('log')
        ax.set_title('COMPASS v8.2 Amplification Test', color='#ff8c00', fontsize=14, fontweight='bold')
        ax.set_ylabel('Portfolio Value (log)', color='#888')
        ax.legend(loc='upper left', fontsize=10)
        ax.tick_params(colors='#666')
        ax.grid(True, alpha=0.1)
        for spine in ax.spines.values():
            spine.set_color('#333')

        os.makedirs('backtests', exist_ok=True)
        plt.tight_layout()
        plt.savefig('backtests/v8_amplify_comparison.png', dpi=150, facecolor='#0a0a0a')
        print("\nSaved: backtests/v8_amplify_comparison.png")
    except Exception as e:
        print(f"\nChart error: {e}")

    elapsed_total = sum(1 for _ in [])  # placeholder
    print("\nDONE.")
