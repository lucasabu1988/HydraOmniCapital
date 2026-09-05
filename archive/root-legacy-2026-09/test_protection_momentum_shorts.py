"""
Test: Short Bottom-N Momentum Stocks During Protection Mode
============================================================
During portfolio stop-loss protection (~2,002 days / 30.5% of backtest),
instead of sitting in cash at 3%, short the WORST momentum stocks
from our own universe -- the same signal, just inverted.

A) BASELINE           -- Cash at 3% yield during protection (current v8.2)
B) SHORT_5_STAGED     -- Short bottom-5 momentum, Stage1: 15%, Stage2: 30%
C) SHORT_3_STAGED     -- Short bottom-3 momentum, Stage1: 15%, Stage2: 30%
D) SHORT_5_AGGRESSIVE -- Short bottom-5 momentum, Stage1: 25%, Stage2: 50%

Short mechanics (simulated):
- Pick worst-N by momentum score from current universe
- Allocate X% of cash equally across N shorts
- Daily P&L = position_value * (-1 * stock_daily_return)
- Rebalance shorts every 5 days (same as HOLD_DAYS)
- Short borrow cost: 1% annual (conservative estimate)
- No short on stocks below $5 (hard to borrow)

All variants use identical COMPASS v8.2 engine outside of protection mode.
Cash yield (3%) applies to UNINVESTED cash in all variants.
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

# ============================================================================
# CONSTANTS (matching COMPASS v8.2 exactly)
# ============================================================================
INITIAL_CAPITAL = 100_000
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
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.03
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# Short parameters
SHORT_BORROW_COST = 0.01   # 1% annual borrow fee
SHORT_MIN_PRICE = 5.0      # Don't short stocks below $5
SHORT_STOP_LOSS = -0.10    # Close individual short if it loses 10%

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

# ============================================================================
# DATA FUNCTIONS
# ============================================================================

def download_broad_pool() -> Dict[str, pd.DataFrame]:
    cache_file = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'
    if os.path.exists(cache_file):
        print("[Cache] Loading broad pool data...")
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            print("[Cache] Failed to load, re-downloading...")
    print(f"[Download] Downloading {len(BROAD_POOL)} symbols...")
    data = {}
    failed = []
    for i, symbol in enumerate(BROAD_POOL):
        try:
            df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[symbol] = df
                if (i + 1) % 20 == 0:
                    print(f"  [{i+1}/{len(BROAD_POOL)}] Downloaded {len(data)} symbols...")
            else:
                failed.append(symbol)
        except Exception:
            failed.append(symbol)
    print(f"[Download] {len(data)} symbols valid, {len(failed)} failed")
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)
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


def compute_annual_top40(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
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
        top_n = [s for s, _ in ranked[:TOP_N]]
        annual_universe[year] = top_n
    return annual_universe


# ============================================================================
# SIGNAL & REGIME FUNCTIONS (identical to v8)
# ============================================================================

def compute_regime(spy_data: pd.DataFrame) -> pd.Series:
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
# BACKTEST ENGINE WITH PROTECTION-MODE MOMENTUM SHORTS
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data,
                 variant='baseline',
                 num_shorts=5,
                 stage1_alloc=0.0,
                 stage2_alloc=0.0) -> Dict:
    """
    Run COMPASS backtest with protection-mode momentum short variants.

    During protection mode, short the bottom-N momentum stocks from the universe.
    Shorts are rebalanced every HOLD_DAYS (5 trading days).
    """

    use_shorts = variant != 'baseline'

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    regime = compute_regime(spy_data)

    cash = float(INITIAL_CAPITAL)
    positions = {}       # Long positions (normal COMPASS)
    short_positions = {} # Short positions during protection
    portfolio_values = []
    trades = []
    stop_events = []
    short_trades = []

    peak_value = float(INITIAL_CAPITAL)
    in_protection_mode = False
    protection_stage = 0
    stop_loss_day_index = None
    post_stop_base = None

    risk_on_days = 0
    risk_off_days = 0
    total_cash_yield = 0.0
    total_turnover = 0.0

    # Protection tracking
    protection_day_count = 0
    recovery_events = []
    current_stop_date = None
    total_short_pnl = 0.0
    short_rebalance_idx = None  # Track when to rebalance shorts

    for i, date in enumerate(all_dates):
        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # --- Calculate portfolio value ---
        portfolio_value = cash

        # Long positions value
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # Short positions value (unrealized P&L)
        short_unrealized = 0.0
        for symbol, spos in list(short_positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                current_price = price_data[symbol].loc[date, 'Close']
                # Short P&L: we sold at entry, price moved to current
                # If price went down, we profit
                short_pnl = (spos['entry_price'] - current_price) * spos['shares']
                short_unrealized += short_pnl
        # Cash collateral for shorts is already in 'cash'
        # Add unrealized short P&L to portfolio value
        portfolio_value += short_unrealized

        # --- Update peak ---
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # --- Recovery from protection mode ---
        if in_protection_mode and stop_loss_day_index is not None:
            protection_day_count += 1
            days_since_stop = i - stop_loss_day_index
            is_regime_on = True
            if date in regime.index:
                is_regime_on = bool(regime.loc[date])

            # Stage 1 -> Stage 2
            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2
                # Close stage 1 shorts, reopen with stage 2 allocation
                if use_shorts:
                    for sym in list(short_positions.keys()):
                        spos = short_positions[sym]
                        if sym in price_data and date in price_data[sym].index:
                            close_price = price_data[sym].loc[date, 'Close']
                            pnl = (spos['entry_price'] - close_price) * spos['shares']
                            borrow_days = i - spos['entry_idx']
                            borrow_cost = spos['notional'] * (SHORT_BORROW_COST / 252) * borrow_days
                            net_pnl = pnl - borrow_cost
                            cash += net_pnl  # Return collateral + P&L
                            total_short_pnl += net_pnl
                            short_trades.append({
                                'symbol': sym, 'entry_date': spos['entry_date'],
                                'exit_date': date, 'exit_reason': 'stage_transition',
                                'pnl': net_pnl, 'side': 'SHORT',
                            })
                        del short_positions[sym]
                    short_rebalance_idx = i  # Force rebalance
                print(f"  [RECOVERY S1] {date.strftime('%Y-%m-%d')}: Stage 2 | "
                      f"Days: {days_since_stop} | Value: ${portfolio_value:,.0f}")

            # Stage 2 -> Normal
            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                # Close all shorts on full recovery
                if use_shorts:
                    for sym in list(short_positions.keys()):
                        spos = short_positions[sym]
                        if sym in price_data and date in price_data[sym].index:
                            close_price = price_data[sym].loc[date, 'Close']
                            pnl = (spos['entry_price'] - close_price) * spos['shares']
                            borrow_days = i - spos['entry_idx']
                            borrow_cost = spos['notional'] * (SHORT_BORROW_COST / 252) * borrow_days
                            net_pnl = pnl - borrow_cost
                            cash += net_pnl
                            total_short_pnl += net_pnl
                            short_trades.append({
                                'symbol': sym, 'entry_date': spos['entry_date'],
                                'exit_date': date, 'exit_reason': 'recovery',
                                'pnl': net_pnl, 'side': 'SHORT',
                            })
                        del short_positions[sym]

                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None
                recovery_events.append({
                    'stop_date': current_stop_date,
                    'recovery_date': date,
                    'duration_days': days_since_stop,
                    'portfolio_at_recovery': portfolio_value,
                })
                print(f"  [RECOVERY S2] {date.strftime('%Y-%m-%d')}: Full recovery | "
                      f"Days: {days_since_stop} | Value: ${portfolio_value:,.0f}")

        # --- Drawdown ---
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # --- Portfolio stop loss ---
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({'date': date, 'portfolio_value': portfolio_value, 'drawdown': drawdown})
            print(f"\n  [STOP LOSS] {date.strftime('%Y-%m-%d')}: DD {drawdown:.1%} | Value: ${portfolio_value:,.0f}")

            # Close all LONG positions
            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    proceeds = pos['shares'] * exit_price
                    commission = pos['shares'] * COMMISSION_PER_SHARE
                    cash += proceeds - commission
                    pnl = (exit_price - pos['entry_price']) * pos['shares'] - commission
                    total_turnover += abs(proceeds)
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
            current_stop_date = date
            short_rebalance_idx = i  # Open shorts immediately

        # --- Manage short positions during protection ---
        if use_shorts and in_protection_mode and len(short_positions) > 0:
            # Check individual short stop losses and update
            for sym in list(short_positions.keys()):
                spos = short_positions[sym]
                if sym not in price_data or date not in price_data[sym].index:
                    continue
                current_price = price_data[sym].loc[date, 'Close']
                # Short loss = price went UP
                short_return = (spos['entry_price'] - current_price) / spos['entry_price']
                if short_return <= SHORT_STOP_LOSS:
                    # Close this short at a loss
                    pnl = (spos['entry_price'] - current_price) * spos['shares']
                    borrow_days = i - spos['entry_idx']
                    borrow_cost = spos['notional'] * (SHORT_BORROW_COST / 252) * borrow_days
                    net_pnl = pnl - borrow_cost
                    cash += net_pnl
                    total_short_pnl += net_pnl
                    short_trades.append({
                        'symbol': sym, 'entry_date': spos['entry_date'],
                        'exit_date': date, 'exit_reason': 'short_stop',
                        'pnl': net_pnl, 'side': 'SHORT',
                    })
                    del short_positions[sym]

            # Rebalance shorts every HOLD_DAYS
            if short_rebalance_idx is not None and (i - short_rebalance_idx) >= HOLD_DAYS:
                # Close existing shorts
                for sym in list(short_positions.keys()):
                    spos = short_positions[sym]
                    if sym in price_data and date in price_data[sym].index:
                        close_price = price_data[sym].loc[date, 'Close']
                        pnl = (spos['entry_price'] - close_price) * spos['shares']
                        borrow_days = i - spos['entry_idx']
                        borrow_cost = spos['notional'] * (SHORT_BORROW_COST / 252) * borrow_days
                        net_pnl = pnl - borrow_cost
                        cash += net_pnl
                        total_short_pnl += net_pnl
                        short_trades.append({
                            'symbol': sym, 'entry_date': spos['entry_date'],
                            'exit_date': date, 'exit_reason': 'rebalance',
                            'pnl': net_pnl, 'side': 'SHORT',
                        })
                    del short_positions[sym]
                short_rebalance_idx = i  # Reset rebalance timer

        # --- Open new shorts during protection ---
        if use_shorts and in_protection_mode and len(short_positions) == 0 and short_rebalance_idx == i:
            # Determine allocation based on stage
            if protection_stage == 1:
                alloc = stage1_alloc
            else:
                alloc = stage2_alloc

            total_short_capital = cash * alloc
            if total_short_capital > 500 and len(tradeable_symbols) >= 10:
                # Compute momentum scores and pick the WORST
                scores = compute_momentum_scores(price_data, tradeable_symbols, date, i)
                if len(scores) >= num_shorts + 5:  # Need enough stocks
                    # Sort ascending = worst momentum first
                    ranked = sorted(scores.items(), key=lambda x: x[1])
                    # Filter: price > $5, not already in long positions
                    candidates = []
                    for sym, sc in ranked:
                        if sym in positions:
                            continue
                        if sym in price_data and date in price_data[sym].index:
                            price = price_data[sym].loc[date, 'Close']
                            if price >= SHORT_MIN_PRICE:
                                candidates.append((sym, sc))
                        if len(candidates) >= num_shorts:
                            break

                    if candidates:
                        per_position = total_short_capital / len(candidates)
                        for sym, sc in candidates:
                            entry_price = price_data[sym].loc[date, 'Close']
                            shares = per_position / entry_price
                            short_positions[sym] = {
                                'entry_price': entry_price,
                                'shares': shares,
                                'notional': per_position,
                                'entry_date': date,
                                'entry_idx': i,
                                'score': sc,
                            }
                            # Cash stays as collateral, no deduction
                            # (shorts don't require upfront cash in margin account)

        # --- Regime ---
        is_risk_on = True
        if date in regime.index:
            is_risk_on = bool(regime.loc[date])
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # --- Determine max positions and leverage ---
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

        # --- Daily margin cost ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # --- Cash yield (on uninvested cash) ---
        if cash > 0:
            daily_yield = cash * (CASH_YIELD_RATE / 252)
            cash += daily_yield
            total_cash_yield += daily_yield

        # --- Compute momentum scores for long entries ---
        daily_scores = None
        if len(positions) < max_positions:
            daily_scores = compute_momentum_scores(price_data, tradeable_symbols, date, i)

        # --- Close LONG positions (standard v8.2) ---
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
                total_turnover += abs(proceeds)
                trades.append({
                    'symbol': symbol, 'entry_date': pos['entry_date'],
                    'exit_date': date, 'exit_reason': exit_reason,
                    'pnl': pnl, 'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # --- Open new LONG positions ---
        needed = max_positions - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            if daily_scores is None:
                daily_scores = compute_momentum_scores(price_data, tradeable_symbols, date, i)
            available_scores = {s: sc for s, sc in daily_scores.items()
                                if s not in positions and s not in short_positions}
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
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + commission
                        total_turnover += abs(cost)

        # --- Record daily snapshot ---
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'shorts': len(short_positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
            'in_protection': in_protection_mode,
            'risk_on': is_risk_on,
            'protection_stage': protection_stage,
        })

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'short_trades': pd.DataFrame(short_trades) if short_trades else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
        'total_cash_yield': total_cash_yield,
        'total_turnover': total_turnover,
        'recovery_events': recovery_events,
        'total_protection_days': protection_day_count,
        'total_short_pnl': total_short_pnl,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results: Dict) -> Dict:
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']
    stop_df = results['stop_events']
    short_df = results.get('short_trades', pd.DataFrame())

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
    total_trades = len(trades_df)

    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()

    if len(trades_df) > 0 and 'entry_date' in trades_df.columns and 'exit_date' in trades_df.columns:
        tdc = trades_df.copy()
        tdc['entry_date'] = pd.to_datetime(tdc['entry_date'])
        tdc['exit_date'] = pd.to_datetime(tdc['exit_date'])
        avg_hold_days = (tdc['exit_date'] - tdc['entry_date']).dt.days.mean()
    else:
        avg_hold_days = 0

    avg_portfolio = df['value'].mean()
    turnover_ratio = results.get('total_turnover', 0) / avg_portfolio / years if avg_portfolio > 0 and years > 0 else 0

    recovery_events = results.get('recovery_events', [])
    total_protection_days = results.get('total_protection_days', 0)
    protection_pct = total_protection_days / len(df) * 100 if len(df) > 0 else 0

    # Short-specific metrics
    num_short_trades = len(short_df)
    short_win_rate = 0
    if num_short_trades > 0 and 'pnl' in short_df.columns:
        short_win_rate = (short_df['pnl'] > 0).mean()

    return {
        'final_value': final_value,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'total_trades': total_trades,
        'avg_hold_days': avg_hold_days,
        'stop_events': len(stop_df),
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
        'positive_years': int((annual_returns > 0).sum()) if len(annual_returns) > 0 else 0,
        'total_years': len(annual_returns),
        'total_cash_yield': results.get('total_cash_yield', 0),
        'total_protection_days': total_protection_days,
        'protection_pct': protection_pct,
        'total_short_pnl': results.get('total_short_pnl', 0),
        'num_short_trades': num_short_trades,
        'short_win_rate': short_win_rate,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("PROTECTION-MODE MOMENTUM SHORTS TEST")
    print("Short bottom-N momentum stocks during portfolio stop-loss protection")
    print("=" * 80)
    print(f"Signal: Same momentum (90d lookback, 5d skip) -- pick WORST scores")
    print(f"Short borrow cost: {SHORT_BORROW_COST:.0%} annual")
    print(f"Short stop loss: {SHORT_STOP_LOSS:.0%} per position")
    print(f"Min price for short: ${SHORT_MIN_PRICE}")
    print(f"Rebalance every {HOLD_DAYS} days")
    print()

    # 1. Load data
    price_data = download_broad_pool()
    print(f"Symbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    # 2. Annual top-40
    print("\nComputing annual top-40...")
    annual_universe = compute_annual_top40(price_data)

    # 3. Define variants
    VARIANTS = [
        {
            'label': 'A) BASELINE (v8.2)',
            'variant': 'baseline',
            'num_shorts': 0,
            'stage1_alloc': 0.0,
            'stage2_alloc': 0.0,
        },
        {
            'label': 'B) SHORT-5 (15%/30%)',
            'variant': 'short_5_staged',
            'num_shorts': 5,
            'stage1_alloc': 0.15,
            'stage2_alloc': 0.30,
        },
        {
            'label': 'C) SHORT-3 (15%/30%)',
            'variant': 'short_3_staged',
            'num_shorts': 3,
            'stage1_alloc': 0.15,
            'stage2_alloc': 0.30,
        },
        {
            'label': 'D) SHORT-5 AGG (25%/50%)',
            'variant': 'short_5_aggressive',
            'num_shorts': 5,
            'stage1_alloc': 0.25,
            'stage2_alloc': 0.50,
        },
    ]

    # 4. Run all variants
    all_results = {}
    all_metrics = {}

    for v in VARIANTS:
        print(f"\n{'='*60}")
        print(f"Running: {v['label']}")
        if v['variant'] != 'baseline':
            print(f"  {v['num_shorts']} shorts | Stage1: {v['stage1_alloc']:.0%} | Stage2: {v['stage2_alloc']:.0%}")
        print(f"{'='*60}")

        results = run_backtest(
            price_data, annual_universe, spy_data,
            variant=v['variant'],
            num_shorts=v['num_shorts'],
            stage1_alloc=v['stage1_alloc'],
            stage2_alloc=v['stage2_alloc'],
        )
        metrics = calculate_metrics(results)
        all_results[v['label']] = results
        all_metrics[v['label']] = metrics

        spnl = metrics.get('total_short_pnl', 0)
        swr = metrics.get('short_win_rate', 0)
        snt = metrics.get('num_short_trades', 0)
        print(f"  Final: ${metrics['final_value']:,.0f} | CAGR: {metrics['cagr']:.2%} | "
              f"Sharpe: {metrics['sharpe']:.3f} | MaxDD: {metrics['max_drawdown']:.1%}")
        if snt > 0:
            print(f"  Short P&L: ${spnl:,.0f} | Short trades: {snt} | Short win rate: {swr:.1%}")

    # 5. Performance table
    print("\n\n" + "=" * 100)
    print("PERFORMANCE COMPARISON -- Momentum Shorts During Protection")
    print("=" * 100)

    labels = [v['label'] for v in VARIANTS]
    header = f"{'Metric':<22}"
    for label in labels:
        short = label.split(')')[0] + ')'
        header += f" {short:>18}"
    print(header)
    print("-" * 100)

    metric_rows = [
        ('Final Value',      'final_value',     '${:>14,.0f}'),
        ('CAGR',             'cagr',            '{:>14.2%}'),
        ('Sharpe',           'sharpe',          '{:>14.3f}'),
        ('Sortino',          'sortino',         '{:>14.3f}'),
        ('Calmar',           'calmar',          '{:>14.3f}'),
        ('Max Drawdown',     'max_drawdown',    '{:>14.1%}'),
        ('Volatility',       'volatility',      '{:>14.1%}'),
        ('Best Year',        'best_year',       '{:>14.1%}'),
        ('Worst Year',       'worst_year',      '{:>14.1%}'),
        ('Cash Yield Total', 'total_cash_yield','${:>13,.0f}'),
        ('Short P&L',        'total_short_pnl', '${:>13,.0f}'),
        ('Short Trades',     'num_short_trades', '{:>14}'),
        ('Short Win Rate',   'short_win_rate',  '{:>14.1%}'),
    ]

    for row_label, key, fmt in metric_rows:
        row = f"{row_label:<22}"
        for label in labels:
            val = all_metrics[label].get(key, 0)
            try:
                row += f" {fmt.format(val):>18}"
            except (ValueError, TypeError):
                row += f" {str(val):>18}"
        print(row)

    # 6. Verdict
    print(f"\n{'='*100}")
    print("VERDICT")
    print(f"{'='*100}")

    baseline_cagr = all_metrics[labels[0]]['cagr']
    baseline_dd = all_metrics[labels[0]]['max_drawdown']

    for label in labels[1:]:
        m = all_metrics[label]
        cagr_diff = m['cagr'] - baseline_cagr
        dd_diff = m['max_drawdown'] - baseline_dd
        spnl = m.get('total_short_pnl', 0)

        if m['cagr'] > baseline_cagr and m['max_drawdown'] >= baseline_dd - 0.02:
            verdict = "WINNER -- Higher CAGR, acceptable MaxDD"
        elif m['cagr'] > baseline_cagr and m['max_drawdown'] < baseline_dd - 0.02:
            verdict = "REJECT -- Higher CAGR but MaxDD too much worse (>2%)"
        elif m['cagr'] <= baseline_cagr:
            verdict = "LOSE -- Lower or equal CAGR"
        else:
            verdict = "MIXED"

        print(f"\n  {label}")
        print(f"    CAGR delta:       {cagr_diff:+.2%}")
        print(f"    MaxDD delta:      {dd_diff:+.1%} ({'better' if dd_diff > 0 else 'worse'})")
        print(f"    Short P&L:        ${spnl:+,.0f}")
        print(f"    Verdict:          {verdict}")

    # 7. Save CSVs
    os.makedirs('backtests', exist_ok=True)
    for v in VARIANTS:
        safe_name = v['variant']
        all_results[v['label']]['portfolio_values'].to_csv(
            f'backtests/protmomshort_{safe_name}_daily.csv', index=False)

    print(f"\nDaily CSVs saved to backtests/protmomshort_*.csv")
    print("\n" + "=" * 80)
    print("PROTECTION-MODE MOMENTUM SHORTS TEST COMPLETE")
    print("=" * 80)
