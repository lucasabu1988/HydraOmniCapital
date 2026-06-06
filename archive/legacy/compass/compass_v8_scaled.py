"""
OmniCapital v8 COMPASS - SCALED EDITION
=========================================
Three upgrades over base v8.2:
  1. Capital: $1,000,000 (vs $100k)
  2. Universe: ~250 stocks (vs 113) - S&P 500 + quality midcaps
  3. Execution: Institutional costs ($0.0005/share, 3% margin vs 6%)

Top-60 annual rotation (vs top-40) to leverage deeper universe.
All signal/regime/risk parameters UNCHANGED from v8.2 production.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
import time
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETERS — UNCHANGED from v8.2 (signal, regime, risk)
# ============================================================================

# Universe (EXPANDED)
TOP_N = 60                      # Was 40 — deeper pool with 250 stocks
MIN_AGE_DAYS = 63

# Signal (UNCHANGED)
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20

# Regime (UNCHANGED)
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3

# Positions (UNCHANGED)
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5

# Position-level risk (UNCHANGED)
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03

# Portfolio-level risk (UNCHANGED)
PORTFOLIO_STOP_LOSS = -0.15

# Recovery (UNCHANGED)
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126

# Leverage & Vol targeting (UNCHANGED)
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 2.0
VOL_LOOKBACK = 20

# === SCALED CHANGES ===
INITIAL_CAPITAL = 1_000_000     # Was 100,000
MARGIN_RATE = 0.03              # Was 0.06 — institutional prime broker rate
COMMISSION_PER_SHARE = 0.0005   # Was 0.001 — institutional execution (IBKR Pro)

# Data
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# Expanded Universe: ~250 stocks
# Original 113 + ~137 new S&P 500 components + quality midcaps
BROAD_POOL = [
    # === ORIGINAL 113 (unchanged) ===
    # Technology (25)
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'AMD',
    'INTC', 'CSCO', 'IBM', 'TXN', 'QCOM', 'ORCL', 'ACN', 'NOW', 'INTU',
    'AMAT', 'MU', 'LRCX', 'SNPS', 'CDNS', 'KLAC', 'MRVL',
    # Financials (18)
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
    'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG',
    # Healthcare (18)
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'AMGN', 'BMY', 'MDT', 'ISRG', 'SYK', 'GILD', 'REGN', 'VRTX', 'BIIB',
    # Consumer (20)
    'AMZN', 'TSLA', 'WMT', 'HD', 'PG', 'COST', 'KO', 'PEP', 'NKE',
    'MCD', 'DIS', 'SBUX', 'TGT', 'LOW', 'CL', 'KMB', 'GIS', 'EL',
    'MO', 'PM',
    # Energy (9)
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'PSX', 'VLO',
    # Industrials (14)
    'GE', 'CAT', 'BA', 'HON', 'UNP', 'RTX', 'LMT', 'DE', 'UPS', 'FDX',
    'MMM', 'GD', 'NOC', 'EMR',
    # Utilities & RE (5)
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    # Telecom (4)
    'VZ', 'T', 'TMUS', 'CMCSA',

    # === NEW ADDITIONS (~137 stocks) ===

    # Technology — Midcap & Missing S&P 500
    'PANW', 'CRWD', 'FTNT', 'ZS', 'DDOG', 'SNOW', 'PLTR', 'NXPI',
    'MCHP', 'ON', 'SWKS', 'MPWR', 'ANSS', 'PTC', 'KEYS', 'TER',
    'CTSH', 'IT', 'EPAM', 'GDDY', 'GEN', 'AKAM', 'JNPR', 'FFIV',
    'HPQ', 'HPE', 'DELL', 'WDC', 'STX',

    # Financials — Regional banks, Insurance, Asset managers
    'MET', 'PRU', 'AFL', 'TRV', 'ALL', 'AJG', 'AON', 'SPGI', 'MCO',
    'ICE', 'CME', 'NDAQ', 'MSCI', 'FIS', 'FISV', 'GPN', 'PYPL',
    'COF', 'DFS', 'SYF', 'ALLY', 'CFG', 'RF', 'HBAN', 'FITB',
    'KEY', 'MTB', 'ZION',

    # Healthcare — Biotech & Devices
    'DXCM', 'IDXX', 'ZBH', 'BAX', 'BDX', 'EW', 'BSX', 'HOLX',
    'ALGN', 'TECH', 'IQV', 'CRL', 'A', 'WAT', 'MTD',
    'MRNA', 'JAZZ', 'NBIX', 'EXAS',

    # Consumer Discretionary — Retail, Autos, Leisure
    'ROST', 'TJX', 'ORLY', 'AZO', 'POOL', 'TSCO', 'DG', 'DLTR',
    'YUM', 'CMG', 'DPZ', 'DARDEN', 'HLT', 'MAR', 'H',
    'GM', 'F', 'APTV', 'BWA', 'LEA',
    'LULU', 'DECK', 'GRMN', 'EBAY', 'ETSY',

    # Consumer Staples
    'MNST', 'STZ', 'BF-B', 'TAP', 'SJM', 'MKC', 'HRL', 'CAG',
    'HSY', 'CHD', 'WBA', 'SYY', 'ADM', 'BG',

    # Industrials — Aerospace, Transport, Building
    'WM', 'RSG', 'FAST', 'IR', 'ROK', 'AME', 'DOV', 'ITW',
    'SWK', 'PH', 'ETN', 'XYL', 'GNRC',
    'CSX', 'NSC', 'JBHT', 'CHRW', 'EXPD',
    'DAL', 'UAL', 'LUV', 'AAL',

    # Materials
    'LIN', 'APD', 'SHW', 'ECL', 'PPG', 'NEM', 'FCX', 'CTVA',
    'DD', 'DOW', 'NUE', 'STLD', 'CF', 'MOS',

    # Real Estate
    'AMT', 'PLD', 'CCI', 'EQIX', 'SPG', 'O', 'WELL', 'DLR',
    'PSA', 'AVB',

    # Utilities (more)
    'SRE', 'ES', 'WEC', 'AEE', 'CMS', 'XEL', 'ED', 'EXC', 'PEG',
]

print("=" * 80)
print("OMNICAPITAL v8 COMPASS — SCALED EDITION")
print("$1M Capital | 250+ Universe | Institutional Execution")
print("=" * 80)
print(f"\nBroad pool: {len(BROAD_POOL)} stocks | Top-{TOP_N} annual rotation")
print(f"Capital: ${INITIAL_CAPITAL:,.0f} | Margin: {MARGIN_RATE:.0%} | Commission: ${COMMISSION_PER_SHARE}/share")
print(f"Signal: Momentum {MOMENTUM_LOOKBACK}d (skip {MOMENTUM_SKIP}d) + Inverse Vol sizing")
print(f"Regime: SPY SMA{REGIME_SMA_PERIOD} | Vol target: {TARGET_VOL:.0%}")
print(f"Hold: {HOLD_DAYS}d | Pos stop: {POSITION_STOP_LOSS:.0%} | Port stop: {PORTFOLIO_STOP_LOSS:.0%}")
print()


# ============================================================================
# DATA FUNCTIONS
# ============================================================================

def download_broad_pool() -> Dict[str, pd.DataFrame]:
    cache_file = f'data_cache/broad_pool_scaled_{START_DATE}_{END_DATE}.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading scaled broad pool data...")
        try:
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
            print(f"  Loaded {len(data)} symbols from cache")
            # Check if we need to download new symbols
            missing = [s for s in BROAD_POOL if s not in data]
            if not missing:
                return data
            print(f"  {len(missing)} new symbols to download...")
        except Exception:
            print("[Cache] Failed to load, re-downloading...")
            data = {}
    else:
        data = {}

    # Try loading the original 113-stock cache first
    original_cache = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'
    if os.path.exists(original_cache) and not data:
        try:
            print("[Cache] Loading original pool as base...")
            with open(original_cache, 'rb') as f:
                data = pickle.load(f)
            print(f"  Base: {len(data)} symbols from original cache")
        except Exception:
            pass

    # Download missing symbols
    to_download = [s for s in BROAD_POOL if s not in data]
    if to_download:
        print(f"[Download] Downloading {len(to_download)} new symbols...")
        failed = []
        for i, symbol in enumerate(to_download):
            try:
                df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
                if not df.empty and len(df) > 100:
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                    data[symbol] = df
                    if (i + 1) % 25 == 0:
                        print(f"  [{i+1}/{len(to_download)}] Downloaded...")
                else:
                    failed.append(symbol)
            except Exception:
                failed.append(symbol)

        print(f"[Download] {len(data)} total symbols, {len(failed)} failed")
        if failed:
            print(f"  Failed: {failed[:20]}{'...' if len(failed) > 20 else ''}")

        os.makedirs('data_cache', exist_ok=True)
        with open(cache_file, 'wb') as f:
            pickle.dump(data, f)
    else:
        print(f"[Cache] All {len(data)} symbols loaded")

    return data


def download_spy() -> pd.DataFrame:
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading SPY data...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    print("[Download] Downloading SPY...")
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def compute_annual_top_n(price_data, top_n=TOP_N):
    """Compute top-N by avg daily dollar volume per year"""
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
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
        for symbol, df in price_data.items():
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top = [s for s, _ in ranked[:top_n]]
        annual_universe[year] = top

        if year > years[0] and year - 1 in annual_universe:
            prev = set(annual_universe[year - 1])
            curr = set(top)
            added = curr - prev
            removed = prev - curr
            if added or removed:
                print(f"  {year}: Top-{top_n} | +{len(added)} in, -{len(removed)} out")
        else:
            print(f"  {year}: Initial top-{top_n} = {len(top)} stocks")

    return annual_universe


# ============================================================================
# SIGNAL & REGIME (IDENTICAL to v8.2)
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
        score = momentum_90d - skip_5d
        scores[symbol] = score
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


# ============================================================================
# BACKTEST
# ============================================================================

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


def run_backtest(price_data, annual_universe, spy_data):
    print("\n" + "=" * 80)
    print("RUNNING COMPASS SCALED BACKTEST")
    print("=" * 80)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    print("\nComputing market regime (SPY vs SMA200)...")
    regime = compute_regime(spy_data)
    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

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
    current_year = None

    for i, date in enumerate(all_dates):
        if date.year != current_year:
            current_year = date.year

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # Portfolio value
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # Peak
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # Recovery
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = True
            if date in regime.index:
                is_regime_on = bool(regime.loc[date])
            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2
                print(f"  [RECOVERY S1] {date.strftime('%Y-%m-%d')}: Stage 2 | ${portfolio_value:,.0f}")
            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None
                print(f"  [RECOVERY S2] {date.strftime('%Y-%m-%d')}: Normal | ${portfolio_value:,.0f}")

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # Portfolio stop
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({'date': date, 'portfolio_value': portfolio_value, 'drawdown': drawdown})
            print(f"\n  [STOP] {date.strftime('%Y-%m-%d')}: DD {drawdown:.1%} | ${portfolio_value:,.0f}")
            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    proceeds = pos['shares'] * exit_price
                    commission = pos['shares'] * COMMISSION_PER_SHARE
                    cash += proceeds - commission
                    pnl = (exit_price - pos['entry_price']) * pos['shares'] - commission
                    trades.append({
                        'symbol': symbol, 'entry_date': pos['entry_date'],
                        'exit_date': date, 'exit_reason': 'portfolio_stop',
                        'pnl': pnl, 'return': pnl / (pos['entry_price'] * pos['shares'])
                    })
                del positions[symbol]
            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i
            post_stop_base = cash

        # Regime
        is_risk_on = True
        if date in regime.index:
            is_risk_on = bool(regime.loc[date])
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # Leverage & positions
        if in_protection_mode:
            if protection_stage == 1:
                max_positions = 2
                current_leverage = 0.3
            else:
                max_positions = 3
                current_leverage = 1.0
        elif not is_risk_on:
            max_positions = NUM_POSITIONS_RISK_OFF
            current_leverage = 1.0
        else:
            max_positions = NUM_POSITIONS
            current_leverage = compute_dynamic_leverage(spy_data, date)

        # Margin cost
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # Close positions
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue
            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            days_held = i - pos['entry_idx']
            if days_held >= HOLD_DAYS:
                exit_reason = 'hold_expired'

            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'

            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            if exit_reason is None and len(positions) > max_positions:
                pos_returns = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        cp = price_data[s].loc[date, 'Close']
                        pos_returns[s] = (cp - p['entry_price']) / p['entry_price']
                worst = min(pos_returns, key=pos_returns.get)
                if symbol == worst:
                    exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                commission = shares * COMMISSION_PER_SHARE
                cash += proceeds - commission
                pnl = (current_price - pos['entry_price']) * shares - commission
                trades.append({
                    'symbol': symbol, 'entry_date': pos['entry_date'],
                    'exit_date': date, 'exit_reason': exit_reason,
                    'pnl': pnl, 'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # Open new positions
        needed = max_positions - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
            available_scores = {s: sc for s, sc in scores.items() if s not in positions}
            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]
                weights = compute_volatility_weights(price_data, selected, date)
                effective_capital = cash * current_leverage * 0.95

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue
                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue
                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = effective_capital * weight
                    max_per_position = cash * 0.40
                    position_value = min(position_value, max_per_position)
                    shares = position_value / entry_price
                    cost = shares * entry_price
                    commission = shares * COMMISSION_PER_SHARE
                    if cost + commission <= cash * 0.90:
                        positions[symbol] = {
                            'entry_price': entry_price, 'shares': shares,
                            'entry_date': date, 'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + commission

        # Record
        portfolio_values.append({
            'date': date, 'value': portfolio_value, 'cash': cash,
            'positions': len(positions), 'drawdown': drawdown,
            'leverage': current_leverage, 'in_protection': in_protection_mode,
            'risk_on': is_risk_on, 'universe_size': len(tradeable_symbols)
        })

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [PROT S{protection_stage}]" if in_protection_mode else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str} | Pos: {len(positions)}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'annual_universe': annual_universe,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results):
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']
    stop_df = results['stop_events']

    initial = INITIAL_CAPITAL
    final_value = df['value'].iloc[-1]
    years = len(df) / 252
    cagr = (final_value / initial) ** (1 / years) - 1

    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)
    max_dd = df['drawdown'].min()
    sharpe = cagr / volatility if volatility > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0

    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    avg_winner = trades_df.loc[trades_df['pnl'] > 0, 'pnl'].mean() if (trades_df['pnl'] > 0).any() else 0
    avg_loser = trades_df.loc[trades_df['pnl'] < 0, 'pnl'].mean() if (trades_df['pnl'] < 0).any() else 0

    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}
    protection_days = df['in_protection'].sum()
    risk_off_pct = results['risk_off_days'] / (results['risk_on_days'] + results['risk_off_days']) * 100

    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()

    return {
        'initial': initial,
        'final_value': final_value,
        'total_return': (final_value - initial) / initial,
        'years': years,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'avg_trade': avg_trade,
        'avg_winner': avg_winner,
        'avg_loser': avg_loser,
        'trades': len(trades_df),
        'exit_reasons': exit_reasons,
        'stop_events': len(stop_df),
        'protection_days': int(protection_days),
        'risk_off_pct': risk_off_pct,
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    t_start = time.time()

    # 1. Data
    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    # 2. Annual top-N
    print(f"\n--- Computing Annual Top-{TOP_N} ---")
    annual_universe = compute_annual_top_n(price_data, TOP_N)

    # 3. Backtest
    results = run_backtest(price_data, annual_universe, spy_data)

    # 4. Metrics
    metrics = calculate_metrics(results)

    # 5. Print
    print("\n" + "=" * 80)
    print("RESULTS - COMPASS v8 SCALED")
    print("=" * 80)

    print(f"\n--- Performance ---")
    print(f"Initial capital:        ${metrics['initial']:>15,.0f}")
    print(f"Final value:            ${metrics['final_value']:>15,.0f}")
    print(f"Total return:           {metrics['total_return']:>15,.1%}")
    print(f"CAGR:                   {metrics['cagr']:>15.2%}")
    print(f"Volatility (annual):    {metrics['volatility']:>15.2%}")

    print(f"\n--- Risk-Adjusted ---")
    print(f"Sharpe ratio:           {metrics['sharpe']:>15.3f}")
    print(f"Sortino ratio:          {metrics['sortino']:>15.3f}")
    print(f"Calmar ratio:           {metrics['calmar']:>15.3f}")
    print(f"Max drawdown:           {metrics['max_drawdown']:>15.1%}")

    print(f"\n--- Trading ---")
    print(f"Trades executed:        {metrics['trades']:>15,}")
    print(f"Win rate:               {metrics['win_rate']:>15.1%}")
    print(f"Avg P&L per trade:      ${metrics['avg_trade']:>15,.0f}")
    print(f"Avg winner:             ${metrics['avg_winner']:>15,.0f}")
    print(f"Avg loser:              ${metrics['avg_loser']:>15,.0f}")

    print(f"\n--- Exit Reasons ---")
    for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: -x[1]):
        print(f"  {reason:25s}: {count:>6,} ({count/metrics['trades']*100:.1f}%)")

    print(f"\n--- Risk Management ---")
    print(f"Stop loss events:       {metrics['stop_events']:>15,}")
    print(f"Days in protection:     {metrics['protection_days']:>15,}")
    print(f"Risk-off days:          {metrics['risk_off_pct']:>14.1f}%")

    # 6. Comparison vs base
    base_cagr = 0.1604
    base_sharpe = 0.770
    base_maxdd = -0.288
    base_final = 4_822_626

    print(f"\n{'='*80}")
    print(f"COMPARISON: BASE ($100k, 113 stocks) vs SCALED ($1M, {len(BROAD_POOL)} stocks)")
    print(f"{'='*80}")
    col = 18
    print(f"\n{'Metric':<25}{'BASE v8.2':>{col}}{'SCALED':>{col}}{'Delta':>{col}}")
    print("-" * (25 + col * 3))
    print(f"{'Capital':<25}{'$100,000':>{col}}{'$1,000,000':>{col}}{'10x':>{col}}")
    print(f"{'Universe':<25}{'113 stocks':>{col}}{f'{len(BROAD_POOL)} stocks':>{col}}{f'+{len(BROAD_POOL)-113}':>{col}}")
    print(f"{'Top-N':<25}{'40':>{col}}{f'{TOP_N}':>{col}}{f'+{TOP_N-40}':>{col}}")
    print(f"{'Commission':<25}{'$0.001/sh':>{col}}{'$0.0005/sh':>{col}}{'50% less':>{col}}")
    print(f"{'Margin Rate':<25}{'6.0%':>{col}}{'3.0%':>{col}}{'50% less':>{col}}")
    s_final = f"${metrics['final_value']:,.0f}"
    s_cagr = f"{metrics['cagr']:.2%}"
    s_sharpe = f"{metrics['sharpe']:.3f}"
    s_maxdd = f"{metrics['max_drawdown']:.1%}"
    s_wr = f"{metrics['win_rate']:.1%}"
    s_trades = f"{metrics['trades']:,}"
    d_final = f"{metrics['final_value']/base_final:.1f}x"
    d_cagr = f"{metrics['cagr']-base_cagr:+.2%}"
    d_sharpe = f"{metrics['sharpe']-base_sharpe:+.3f}"
    d_maxdd = f"{metrics['max_drawdown']-base_maxdd:+.1%}"
    d_wr = f"{metrics['win_rate']-0.553:+.1%}"
    d_trades = f"{metrics['trades']-5386:+,}"

    print(f"{'Final Value':<25}{f'${base_final:,.0f}':>{col}}{s_final:>{col}}{d_final:>{col}}")
    print(f"{'CAGR':<25}{f'{base_cagr:.2%}':>{col}}{s_cagr:>{col}}{d_cagr:>{col}}")
    print(f"{'Sharpe':<25}{f'{base_sharpe:.3f}':>{col}}{s_sharpe:>{col}}{d_sharpe:>{col}}")
    print(f"{'Max Drawdown':<25}{f'{base_maxdd:.1%}':>{col}}{s_maxdd:>{col}}{d_maxdd:>{col}}")
    print(f"{'Win Rate':<25}{'55.3%':>{col}}{s_wr:>{col}}{d_wr:>{col}}")
    print(f"{'Trades':<25}{'5,386':>{col}}{s_trades:>{col}}{d_trades:>{col}}")

    # 7. Save
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/v8_scaled_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/v8_scaled_trades.csv', index=False)

    # 8. Chart
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), gridspec_kw={'height_ratios': [3, 1]})
        fig.patch.set_facecolor('#0a0a0a')
        for ax in [ax1, ax2]:
            ax.set_facecolor('#0a0a0a')
            for s in ax.spines.values():
                s.set_color('#333')
            ax.tick_params(colors='#666')
            ax.grid(True, alpha=0.15, color='#333')

        df_pv = results['portfolio_values']
        dates = pd.to_datetime(df_pv['date'])

        ax1.semilogy(dates, df_pv['value'], color='#ff8c00', linewidth=1.5,
                      label=f'SCALED: ${metrics["final_value"]:,.0f} ({metrics["cagr"]:.1%} CAGR)')

        # Load base for comparison
        base_file = 'backtests/v8_opt_base_v8.2_daily.csv'
        if os.path.exists(base_file):
            base_df = pd.read_csv(base_file, parse_dates=['date'])
            ax1.semilogy(base_df['date'], base_df['value'], color='#666',
                          linewidth=1, alpha=0.7, linestyle='--',
                          label=f'BASE: ${base_final:,.0f} ({base_cagr:.1%} CAGR)')

        ax1.set_title('COMPASS v8 SCALED - $1M / 250 stocks / Institutional',
                       color='#ff8c00', fontsize=14, fontweight='bold', fontfamily='monospace')
        ax1.set_ylabel('Portfolio Value (log)', color='#888', fontfamily='monospace')
        ax1.legend(fontsize=10, loc='upper left', facecolor='#1a1a1a',
                    edgecolor='#333', labelcolor='#ccc')

        ax2.fill_between(dates, df_pv['drawdown'] * 100, 0, color='#ff3333', alpha=0.4)
        ax2.plot(dates, df_pv['drawdown'] * 100, color='#ff3333', linewidth=0.5)
        ax2.set_title('Drawdown', color='#ff8c00', fontsize=11, fontfamily='monospace')
        ax2.set_ylabel('DD %', color='#888', fontfamily='monospace')

        plt.tight_layout()
        plt.savefig('backtests/v8_scaled_equity.png', dpi=150, facecolor='#0a0a0a', bbox_inches='tight')
        plt.close()
        print(f"\nSaved: backtests/v8_scaled_equity.png")
    except Exception as e:
        print(f"[WARN] Chart error: {e}")

    elapsed = time.time() - t_start
    print(f"\nTotal time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"\nSaved: backtests/v8_scaled_daily.csv")
    print(f"Saved: backtests/v8_scaled_trades.csv")

    print("\n" + "=" * 80)
    print("COMPASS SCALED BACKTEST COMPLETE")
    print("=" * 80)
