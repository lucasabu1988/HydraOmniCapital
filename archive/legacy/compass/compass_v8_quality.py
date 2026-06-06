"""
OmniCapital v8 COMPASS - QUALITY EDITION
==========================================
Adds a net profit margin filter (>=15%) to the universe selection.
Eliminates low-quality/commodity businesses from the momentum pool.

Three configs tested:
  A) BASE:    $1M, 283 stocks, top-60, NO margin filter
  B) QUALITY: $1M, 283 stocks, top-60, margin >= 15%
  C) QUALITY ORIGINAL: $1M, 113 stocks, top-40, margin >= 15%
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
import time
import json
from typing import Dict, List
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETERS (from v8.2)
# ============================================================================

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
INITIAL_CAPITAL = 1_000_000
MARGIN_RATE = 0.03
COMMISSION_PER_SHARE = 0.0005
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# Quality filter
MIN_NET_MARGIN = 0.15  # 15% minimum net profit margin

# Full expanded pool (283 stocks)
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
    'PANW', 'CRWD', 'FTNT', 'ZS', 'DDOG', 'SNOW', 'PLTR', 'NXPI',
    'MCHP', 'ON', 'SWKS', 'MPWR', 'ANSS', 'PTC', 'KEYS', 'TER',
    'CTSH', 'IT', 'EPAM', 'GDDY', 'GEN', 'AKAM', 'JNPR', 'FFIV',
    'HPQ', 'HPE', 'DELL', 'WDC', 'STX',
    'MET', 'PRU', 'AFL', 'TRV', 'ALL', 'AJG', 'AON', 'SPGI', 'MCO',
    'ICE', 'CME', 'NDAQ', 'MSCI', 'FIS', 'FISV', 'GPN', 'PYPL',
    'COF', 'DFS', 'SYF', 'ALLY', 'CFG', 'RF', 'HBAN', 'FITB',
    'KEY', 'MTB', 'ZION',
    'DXCM', 'IDXX', 'ZBH', 'BAX', 'BDX', 'EW', 'BSX', 'HOLX',
    'ALGN', 'TECH', 'IQV', 'CRL', 'A', 'WAT', 'MTD',
    'MRNA', 'JAZZ', 'NBIX', 'EXAS',
    'ROST', 'TJX', 'ORLY', 'AZO', 'POOL', 'TSCO', 'DG', 'DLTR',
    'YUM', 'CMG', 'DPZ', 'DARDEN', 'HLT', 'MAR', 'H',
    'GM', 'F', 'APTV', 'BWA', 'LEA',
    'LULU', 'DECK', 'GRMN', 'EBAY', 'ETSY',
    'MNST', 'STZ', 'BF-B', 'TAP', 'SJM', 'MKC', 'HRL', 'CAG',
    'HSY', 'CHD', 'WBA', 'SYY', 'ADM', 'BG',
    'WM', 'RSG', 'FAST', 'IR', 'ROK', 'AME', 'DOV', 'ITW',
    'SWK', 'PH', 'ETN', 'XYL', 'GNRC',
    'CSX', 'NSC', 'JBHT', 'CHRW', 'EXPD',
    'DAL', 'UAL', 'LUV', 'AAL',
    'LIN', 'APD', 'SHW', 'ECL', 'PPG', 'NEM', 'FCX', 'CTVA',
    'DD', 'DOW', 'NUE', 'STLD', 'CF', 'MOS',
    'AMT', 'PLD', 'CCI', 'EQIX', 'SPG', 'O', 'WELL', 'DLR',
    'PSA', 'AVB',
    'SRE', 'ES', 'WEC', 'AEE', 'CMS', 'XEL', 'ED', 'EXC', 'PEG',
]

# Original pool (113 stocks)
ORIGINAL_POOL = [
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

print("=" * 80)
print("OMNICAPITAL v8 COMPASS - QUALITY EDITION")
print("Net Margin >= 15% Filter")
print("=" * 80)


# ============================================================================
# DATA FUNCTIONS
# ============================================================================

def load_price_data():
    """Load price data from existing caches"""
    # Try scaled cache first (has 271 symbols)
    scaled_cache = f'data_cache/broad_pool_scaled_{START_DATE}_{END_DATE}.pkl'
    if os.path.exists(scaled_cache):
        print("[Cache] Loading scaled pool...")
        try:
            with open(scaled_cache, 'rb') as f:
                return pickle.load(f)
        except Exception:
            pass

    # Fallback to original
    orig_cache = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'
    if os.path.exists(orig_cache):
        print("[Cache] Loading original pool...")
        with open(orig_cache, 'rb') as f:
            return pickle.load(f)

    raise RuntimeError("No price cache found. Run compass_v8_scaled.py first.")


def download_spy():
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.to_csv(cache_file)
    return df


def fetch_net_margins(symbols):
    """Fetch current net profit margin for all symbols via yfinance .info"""
    cache_file = 'data_cache/net_margins.json'

    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f:
            cached = json.load(f)
        # Check if we have all symbols
        missing = [s for s in symbols if s not in cached]
        if not missing:
            print(f"[Cache] Net margins loaded for {len(cached)} stocks")
            return cached
        print(f"[Cache] {len(cached)} cached, {len(missing)} to fetch...")
        margins = cached
    else:
        margins = {}
        missing = symbols

    print(f"[Fetching] Net margins for {len(missing)} stocks...")
    for i, sym in enumerate(missing):
        try:
            t = yf.Ticker(sym)
            info = t.info
            pm = info.get('profitMargins', None)
            if pm is not None:
                margins[sym] = pm
            else:
                # Try computing from financials
                fin = t.financials
                if fin is not None and not fin.empty:
                    if 'Net Income' in fin.index and 'Total Revenue' in fin.index:
                        ni = fin.loc['Net Income'].dropna()
                        rev = fin.loc['Total Revenue'].dropna()
                        if len(ni) > 0 and len(rev) > 0 and rev.iloc[0] > 0:
                            margins[sym] = float(ni.iloc[0] / rev.iloc[0])
                        else:
                            margins[sym] = None
                    else:
                        margins[sym] = None
                else:
                    margins[sym] = None
        except Exception:
            margins[sym] = None

        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(missing)}] fetched...")

    # Save cache
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'w') as f:
        json.dump(margins, f, indent=2)
    print(f"[Saved] Net margins cached for {len(margins)} stocks")

    return margins


def filter_by_margin(symbols, margins, min_margin=MIN_NET_MARGIN):
    """Filter stocks by net profit margin threshold"""
    passed = []
    failed = []
    no_data = []

    for sym in symbols:
        m = margins.get(sym, None)
        if m is None:
            no_data.append(sym)
            # Include stocks without data (benefit of doubt)
            passed.append(sym)
        elif m >= min_margin:
            passed.append(sym)
        else:
            failed.append((sym, m))

    print(f"\n  Margin Filter (>= {min_margin:.0%}):")
    print(f"  PASS: {len(passed)} stocks (incl {len(no_data)} without data)")
    print(f"  FAIL: {len(failed)} stocks removed")
    if failed:
        failed_sorted = sorted(failed, key=lambda x: x[1])
        examples = failed_sorted[:15]
        print(f"  Removed: {', '.join(f'{s}({m:.0%})' for s,m in examples)}")
        if len(failed) > 15:
            print(f"           ... and {len(failed)-15} more")

    return passed


# ============================================================================
# ENGINE FUNCTIONS (identical to v8.2)
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


def compute_annual_top_n(price_data, pool_symbols, top_n):
    """Compute annual top-N from a specific pool of symbols"""
    # Only use symbols that are in the pool AND have price data
    valid_symbols = [s for s in pool_symbols if s in price_data]

    all_dates = set()
    for s in valid_symbols:
        all_dates.update(price_data[s].index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}
    for year in years:
        if year == years[0]:
            ranking_end = pd.Timestamp(f'{year}-02-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        else:
            ranking_end = pd.Timestamp(f'{year}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)

        scores = {}
        for symbol in valid_symbols:
            df = price_data[symbol]
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top = [s for s, _ in ranked[:top_n]]
        annual_universe[year] = top

    return annual_universe


def compute_momentum_scores(price_data, tradeable, date, all_dates, date_idx):
    scores = {}
    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        needed = MOMENTUM_LOOKBACK + MOMENTUM_SKIP
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue
        if sym_idx < needed:
            continue
        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - MOMENTUM_SKIP]
        close_lookback = df['Close'].iloc[sym_idx - MOMENTUM_LOOKBACK]
        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue
        momentum_90d = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        scores[symbol] = momentum_90d - skip_5d
    return scores


def compute_volatility_weights(price_data, selected, date):
    vols = {}
    for symbol in selected:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        sym_idx = df.index.get_loc(date)
        if sym_idx < VOL_LOOKBACK + 1:
            continue
        returns = df['Close'].iloc[sym_idx - VOL_LOOKBACK:sym_idx + 1].pct_change().dropna()
        if len(returns) < VOL_LOOKBACK - 2:
            continue
        vol = returns.std() * np.sqrt(252)
        if vol > 0.01:
            vols[symbol] = vol
    if not vols:
        return {s: 1.0 / len(selected) for s in selected}
    raw_weights = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw_weights.values())
    return {s: w / total for s, w in raw_weights.items()}


def compute_dynamic_leverage(spy_data, date):
    if date not in spy_data.index:
        return 1.0
    idx = spy_data.index.get_loc(date)
    if idx < VOL_LOOKBACK + 1:
        return 1.0
    returns = spy_data['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
    if len(returns) < VOL_LOOKBACK - 2:
        return 1.0
    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol < 0.01:
        return LEVERAGE_MAX
    leverage = TARGET_VOL / realized_vol
    return max(LEVERAGE_MIN, min(LEVERAGE_MAX, leverage))


def get_tradeable_symbols(price_data, date, first_date, annual_universe):
    eligible = set(annual_universe.get(date.year, []))
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


# ============================================================================
# BACKTEST
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data, label=""):
    print(f"\n{'='*60}")
    print(f"  RUNNING: {label}")
    print(f"{'='*60}")

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    regime = compute_regime(spy_data)

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
    risk_on_days = 0
    risk_off_days = 0

    for i, date in enumerate(all_dates):
        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                portfolio_value += pos['shares'] * price_data[symbol].loc[date, 'Close']

        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

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

        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({'date': date, 'value': portfolio_value, 'drawdown': drawdown})
            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    ep = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    cash += pos['shares'] * ep - pos['shares'] * COMMISSION_PER_SHARE
                    pnl = (ep - pos['entry_price']) * pos['shares']
                    trades.append({'symbol': symbol, 'entry_date': pos['entry_date'],
                                   'exit_date': date, 'exit_reason': 'portfolio_stop',
                                   'pnl': pnl, 'return': pnl / (pos['entry_price'] * pos['shares'])})
                del positions[symbol]
            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i

        is_risk_on = bool(regime.loc[date]) if date in regime.index else True
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

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

        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            cash -= MARGIN_RATE / 252 * borrowed

        # Close positions
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue
            cp = price_data[symbol].loc[date, 'Close']
            exit_reason = None
            if i - pos['entry_idx'] >= HOLD_DAYS:
                exit_reason = 'hold_expired'
            pr = (cp - pos['entry_price']) / pos['entry_price']
            if pr <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'
            if cp > pos['high_price']:
                pos['high_price'] = cp
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                if cp <= pos['high_price'] * (1 - TRAILING_STOP_PCT):
                    exit_reason = 'trailing_stop'
            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'
            if exit_reason is None and len(positions) > max_positions:
                prs = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        prs[s] = (price_data[s].loc[date, 'Close'] - p['entry_price']) / p['entry_price']
                if symbol == min(prs, key=prs.get):
                    exit_reason = 'regime_reduce'
            if exit_reason:
                sh = pos['shares']
                cash += sh * cp - sh * COMMISSION_PER_SHARE
                pnl = (cp - pos['entry_price']) * sh
                trades.append({'symbol': symbol, 'entry_date': pos['entry_date'],
                               'exit_date': date, 'exit_reason': exit_reason,
                               'pnl': pnl, 'return': pnl / (pos['entry_price'] * sh)})
                del positions[symbol]

        # Open positions
        needed = max_positions - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
            avail = {s: sc for s, sc in scores.items() if s not in positions}
            if len(avail) >= needed:
                ranked = sorted(avail.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]
                weights = compute_volatility_weights(price_data, selected, date)
                eff_cap = cash * current_leverage * 0.95
                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue
                    ep = price_data[symbol].loc[date, 'Close']
                    if ep <= 0:
                        continue
                    w = weights.get(symbol, 1.0 / len(selected))
                    pv = min(eff_cap * w, cash * 0.40)
                    sh = pv / ep
                    cost = sh * ep + sh * COMMISSION_PER_SHARE
                    if cost <= cash * 0.90:
                        positions[symbol] = {'entry_price': ep, 'shares': sh,
                                             'entry_date': date, 'entry_idx': i, 'high_price': ep}
                        cash -= cost

        portfolio_values.append({
            'date': date, 'value': portfolio_value, 'cash': cash,
            'positions': len(positions), 'drawdown': drawdown,
            'leverage': current_leverage, 'in_protection': in_protection_mode,
            'risk_on': is_risk_on, 'universe_size': len(tradeable_symbols)
        })

        if i % (252 * 5) == 0 and i > 0:
            print(f"  [{label}] Day {i}: ${portfolio_value:,.0f} | DD: {drawdown:.1%}")

    final = portfolio_values[-1]['value']
    print(f"  [{label}] DONE: ${final:,.0f} | Trades: {len(trades)} | Stops: {len(stop_events)}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': stop_events,
        'final_value': final,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
        'label': label,
    }


def calculate_metrics(results):
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']
    initial = INITIAL_CAPITAL
    final = df['value'].iloc[-1]
    years = len(df) / 252
    cagr = (final / initial) ** (1 / years) - 1
    rets = df['value'].pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    max_dd = df['drawdown'].min()
    sharpe = cagr / vol if vol > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    ds = rets[rets < 0]
    ds_vol = ds.std() * np.sqrt(252) if len(ds) > 0 else vol
    sortino = cagr / ds_vol if ds_vol > 0 else 0
    wr = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_t = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    exits = trades_df['exit_reason'].value_counts().to_dict() if len(trades_df) > 0 else {}
    prot_d = int(df['in_protection'].sum())
    ro_pct = results['risk_off_days'] / max(1, results['risk_on_days'] + results['risk_off_days']) * 100
    ann = df['value'].resample('YE').last().pct_change().dropna()

    return {
        'label': results['label'], 'final_value': final, 'cagr': cagr,
        'volatility': vol, 'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar,
        'max_drawdown': max_dd, 'win_rate': wr, 'avg_trade': avg_t,
        'trades': len(trades_df), 'stop_events': len(results['stop_events']),
        'protection_days': prot_d, 'risk_off_pct': ro_pct,
        'exit_reasons': exits, 'pos_stop_pct': exits.get('position_stop', 0) / max(1, len(trades_df)) * 100,
        'best_year': ann.max() if len(ann) > 0 else 0,
        'worst_year': ann.min() if len(ann) > 0 else 0,
    }


# ============================================================================
# OUTPUT
# ============================================================================

def print_comparison(all_metrics):
    print("\n")
    print("=" * 100)
    print("  QUALITY FILTER COMPARISON")
    print("=" * 100)

    labels = [m['label'] for m in all_metrics]
    col_w = 20

    print(f"\n{'Metric':<22}", end='')
    for lbl in labels:
        print(f"{lbl[:col_w-1]:>{col_w}}", end='')
    print()
    print("-" * (22 + col_w * len(labels)))

    rows = [
        ('Final Value',    'final_value',    lambda v: f"${v:,.0f}"),
        ('CAGR',           'cagr',           lambda v: f"{v:.2%}"),
        ('Sharpe',         'sharpe',         lambda v: f"{v:.3f}"),
        ('Sortino',        'sortino',        lambda v: f"{v:.3f}"),
        ('Max Drawdown',   'max_drawdown',   lambda v: f"{v:.1%}"),
        ('Calmar',         'calmar',         lambda v: f"{v:.3f}"),
        ('Volatility',     'volatility',     lambda v: f"{v:.2%}"),
        ('Win Rate',       'win_rate',       lambda v: f"{v:.1%}"),
        ('Avg Trade',      'avg_trade',      lambda v: f"${v:,.0f}"),
        ('Trades',         'trades',         lambda v: f"{v:,}"),
        ('Stop Events',    'stop_events',    lambda v: f"{v}"),
        ('Pos Stop %',     'pos_stop_pct',   lambda v: f"{v:.1f}%"),
        ('Best Year',      'best_year',      lambda v: f"{v:.1%}"),
        ('Worst Year',     'worst_year',     lambda v: f"{v:.1%}"),
    ]

    for name, key, fmt_fn in rows:
        print(f"{name:<22}", end='')
        for m in all_metrics:
            print(f"{fmt_fn(m.get(key, 0)):>{col_w}}", end='')
        print()

    # Delta vs first (base)
    base = all_metrics[0]
    print()
    for key, name, fmt in [('sharpe', 'd_Sharpe', '+.3f'), ('cagr', 'd_CAGR', '+.2%'), ('max_drawdown', 'd_MaxDD', '+.1%')]:
        print(f"{name:<22}", end='')
        for m in all_metrics:
            d = m[key] - base[key]
            s = f"{d:{fmt}}" if m != base else "---"
            print(f"{s:>{col_w}}", end='')
        print()

    print("=" * 100)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    t_start = time.time()

    # 1. Load price data
    price_data = load_price_data()
    print(f"Price data: {len(price_data)} symbols")

    spy_data = download_spy()
    print(f"SPY: {len(spy_data)} days")

    # 2. Fetch net margins
    all_symbols = list(set(BROAD_POOL + ORIGINAL_POOL))
    all_symbols = [s for s in all_symbols if s in price_data]
    print(f"\nFetching net margins for {len(all_symbols)} stocks...")
    margins = fetch_net_margins(all_symbols)

    # 3. Apply quality filter
    print("\n--- Expanded Pool (283 stocks) ---")
    expanded_valid = [s for s in BROAD_POOL if s in price_data]
    expanded_quality = filter_by_margin(expanded_valid, margins)

    print("\n--- Original Pool (113 stocks) ---")
    original_valid = [s for s in ORIGINAL_POOL if s in price_data]
    original_quality = filter_by_margin(original_valid, margins)

    # 4. Compute universes
    print("\n--- Computing Annual Rotations ---")

    print("\nA) Expanded top-60 (no filter):")
    univ_a = compute_annual_top_n(price_data, expanded_valid, 60)

    print("\nB) Expanded top-60 (quality filter):")
    univ_b = compute_annual_top_n(price_data, expanded_quality, 60)

    print("\nC) Original top-40 (quality filter):")
    univ_c = compute_annual_top_n(price_data, original_quality, 40)

    # 5. Run backtests
    all_results = []
    all_metrics_list = []

    configs = [
        ('A: Scaled NoFilter', univ_a),
        ('B: Scaled Quality', univ_b),
        ('C: Orig Quality', univ_c),
    ]

    for label, univ in configs:
        t0 = time.time()
        result = run_backtest(price_data, univ, spy_data, label=label)
        elapsed = time.time() - t0
        print(f"  Time: {elapsed:.0f}s")
        metrics = calculate_metrics(result)
        all_results.append(result)
        all_metrics_list.append(metrics)

    # 6. Compare
    print_comparison(all_metrics_list)

    # 7. Save
    os.makedirs('backtests', exist_ok=True)
    for r in all_results:
        safe = r['label'].replace(' ', '_').replace(':', '').lower()
        r['portfolio_values'].to_csv(f'backtests/v8_quality_{safe}_daily.csv', index=False)

    # 8. Chart
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), gridspec_kw={'height_ratios': [3, 1]})
        fig.patch.set_facecolor('#0a0a0a')
        colors = ['#666666', '#ff8c00', '#00ff41']

        for ax in [ax1, ax2]:
            ax.set_facecolor('#0a0a0a')
            for s in ax.spines.values():
                s.set_color('#333')
            ax.tick_params(colors='#666')
            ax.grid(True, alpha=0.15, color='#333')

        for idx, (r, m) in enumerate(zip(all_results, all_metrics_list)):
            df = r['portfolio_values']
            dates = pd.to_datetime(df['date'])
            c = colors[idx]
            ax1.semilogy(dates, df['value'], color=c, linewidth=1.3,
                          label=f"{m['label']} (Sharpe:{m['sharpe']:.3f})", alpha=0.9)
            ax2.fill_between(dates, df['drawdown'] * 100, 0, color=c, alpha=0.2)

        ax1.set_title('COMPASS Quality Filter Comparison', color='#ff8c00',
                       fontsize=14, fontweight='bold', fontfamily='monospace')
        ax1.set_ylabel('Value (log)', color='#888', fontfamily='monospace')
        ax1.legend(fontsize=10, loc='upper left', facecolor='#1a1a1a',
                    edgecolor='#333', labelcolor='#ccc')
        ax2.set_title('Drawdown', color='#ff8c00', fontsize=11, fontfamily='monospace')
        ax2.set_ylabel('DD %', color='#888', fontfamily='monospace')

        plt.tight_layout()
        plt.savefig('backtests/v8_quality_comparison.png', dpi=150, facecolor='#0a0a0a', bbox_inches='tight')
        plt.close()
        print("\nSaved: backtests/v8_quality_comparison.png")
    except Exception as e:
        print(f"[Chart error]: {e}")

    total = time.time() - t_start
    print(f"\nTotal time: {total:.0f}s ({total/60:.1f} min)")
    print("\nDONE.")
