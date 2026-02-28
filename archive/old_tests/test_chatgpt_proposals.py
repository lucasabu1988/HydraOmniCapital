"""
Test: ChatGPT Proposals vs COMPASS v8.2 Baseline
==================================================
Tests THREE proposed modifications from ChatGPT quantitative review:

A) BASELINE         -- Pure COMPASS v8.2 (production, with cash yield)
B) ENSEMBLE_MOM     -- Ensemble momentum: avg of 60d/90d/120d scores (stabilize signal)
C) COND_HOLD_EXT    -- Conditional hold extension: extend to 10d if Top-5 + ATR5 < ATR20
D) PREEMPTIVE_STOP  -- Preemptive protection: -8% stop (vs -15%) + faster recovery (32d/63d)
E) ENSEMBLE+COND    -- Proposals B+C combined (best signal + best exit)
F) ALL_THREE        -- All three proposals together

All variants use identical COMPASS v8.2 engine (regime, sizing, leverage, margin, cash yield).
Only SIGNAL, EXIT LOGIC, and STOP THRESHOLD differ per variant.

Key question: Can any proposal beat 16.95% CAGR without worsening -28.4% MaxDD?
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
CASH_YIELD_RATE = 0.03  # 3% annual on idle cash (T-bill proxy)
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# --- Proposal B: Ensemble Momentum parameters ---
ENSEMBLE_LOOKBACKS = [60, 90, 120]  # Average momentum across these windows

# --- Proposal C: Conditional Hold Extension parameters ---
EXTENDED_HOLD_DAYS = 10       # Extend to 10d if conditions met
COND_TOP_N_RANK = 5           # Must still be in top-5
ATR_SHORT = 5                 # Short-term ATR window
ATR_LONG = 20                 # Long-term ATR window

# --- Proposal D: Preemptive Protection parameters ---
PREEMPTIVE_STOP_LOSS = -0.08          # Trigger at -8% instead of -15%
PREEMPTIVE_RECOVERY_STAGE_1_DAYS = 32  # ~1.5 months (vs 63)
PREEMPTIVE_RECOVERY_STAGE_2_DAYS = 63  # ~3 months (vs 126)

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
# DATA FUNCTIONS (reused from v8 compass)
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
# SIGNAL & REGIME FUNCTIONS
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


def compute_momentum_scores_standard(price_data, tradeable, date, date_idx):
    """Standard COMPASS momentum: 90d lookback, 5d skip."""
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


def compute_momentum_scores_ensemble(price_data, tradeable, date, date_idx):
    """
    Ensemble momentum: average of RANK positions across 60d/90d/120d lookbacks.
    Each window computes momentum_Nd - reversal_5d, then we average the RANKS
    across all three windows. This stabilizes the signal without diluting it.
    """
    window_scores = {}  # {window: {symbol: score}}

    for lookback in ENSEMBLE_LOOKBACKS:
        scores = {}
        for symbol in tradeable:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            if date not in df.index:
                continue
            needed = lookback + MOMENTUM_SKIP
            try:
                sym_idx = df.index.get_loc(date)
            except KeyError:
                continue
            if sym_idx < needed:
                continue

            close_today = df['Close'].iloc[sym_idx]
            close_skip = df['Close'].iloc[sym_idx - MOMENTUM_SKIP]
            close_lookback = df['Close'].iloc[sym_idx - lookback]

            if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
                continue

            momentum = (close_skip / close_lookback) - 1.0
            skip_5d = (close_today / close_skip) - 1.0
            score = momentum - skip_5d
            scores[symbol] = score

        window_scores[lookback] = scores

    # Average RANKS across windows
    # Only include symbols present in ALL windows
    common_symbols = None
    for lookback in ENSEMBLE_LOOKBACKS:
        syms = set(window_scores[lookback].keys())
        if common_symbols is None:
            common_symbols = syms
        else:
            common_symbols = common_symbols & syms

    if not common_symbols:
        # Fallback to standard if no common symbols
        return compute_momentum_scores_standard(price_data, tradeable, date, date_idx)

    # Compute rank for each window (rank 1 = best momentum)
    avg_ranks = {}
    for symbol in common_symbols:
        ranks = []
        for lookback in ENSEMBLE_LOOKBACKS:
            # Sort all symbols in this window by score descending
            sorted_syms = sorted(window_scores[lookback].keys(),
                                 key=lambda s: window_scores[lookback][s], reverse=True)
            rank = sorted_syms.index(symbol) + 1
            ranks.append(rank)
        avg_ranks[symbol] = sum(ranks) / len(ranks)

    # Convert back to scores: lower avg rank = higher score
    # Invert so that rank 1 (best) gets highest score
    max_rank = max(avg_ranks.values()) if avg_ranks else 1
    ensemble_scores = {}
    for symbol, avg_rank in avg_ranks.items():
        ensemble_scores[symbol] = max_rank - avg_rank + 1  # Higher = better

    return ensemble_scores


def compute_atr(price_data, symbol, date, period):
    """Compute Average True Range over given period."""
    if symbol not in price_data:
        return None
    df = price_data[symbol]
    if date not in df.index:
        return None
    try:
        sym_idx = df.index.get_loc(date)
    except KeyError:
        return None
    if sym_idx < period + 1:
        return None

    # True Range = max(H-L, |H-Cprev|, |L-Cprev|)
    highs = df['High'].iloc[sym_idx - period:sym_idx + 1]
    lows = df['Low'].iloc[sym_idx - period:sym_idx + 1]
    closes = df['Close'].iloc[sym_idx - period - 1:sym_idx + 1]

    tr_values = []
    for j in range(1, len(highs)):
        h = highs.iloc[j]
        l = lows.iloc[j]
        c_prev = closes.iloc[j - 1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        tr_values.append(tr)

    if not tr_values:
        return None
    return np.mean(tr_values)


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
# UNIFIED BACKTEST ENGINE WITH CHATGPT PROPOSAL VARIANTS
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data, variant='baseline') -> Dict:
    """
    Run COMPASS backtest with variant-specific modifications.

    Variants:
        'baseline'       - Standard v8.2 (5-day hold, cash yield, -15% stop)
        'ensemble_mom'   - Ensemble momentum scoring (60d/90d/120d avg ranks)
        'cond_hold_ext'  - Conditional hold extension (extend to 10d if Top-5 + calm vol)
        'preemptive_stop'- Preemptive protection (-8% stop, faster recovery 32d/63d)
        'ensemble_cond'  - Proposals B+C combined
        'all_three'      - All three proposals together
    """

    use_ensemble = variant in ('ensemble_mom', 'ensemble_cond', 'all_three')
    use_cond_hold = variant in ('cond_hold_ext', 'ensemble_cond', 'all_three')
    use_preemptive = variant in ('preemptive_stop', 'all_three')

    # Set stop/recovery params based on variant
    if use_preemptive:
        portfolio_stop = PREEMPTIVE_STOP_LOSS
        recovery_s1_days = PREEMPTIVE_RECOVERY_STAGE_1_DAYS
        recovery_s2_days = PREEMPTIVE_RECOVERY_STAGE_2_DAYS
    else:
        portfolio_stop = PORTFOLIO_STOP_LOSS
        recovery_s1_days = RECOVERY_STAGE_1_DAYS
        recovery_s2_days = RECOVERY_STAGE_2_DAYS

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
    total_cash_yield = 0.0
    total_turnover = 0.0
    protection_days = 0
    hold_extensions = 0  # Track how many times hold was extended

    for i, date in enumerate(all_dates):
        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # --- Calculate portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # --- Update peak ---
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # --- Recovery from protection mode ---
        if in_protection_mode:
            protection_days += 1
            if stop_loss_day_index is not None:
                days_since_stop = i - stop_loss_day_index
                is_regime_on = True
                if date in regime.index:
                    is_regime_on = bool(regime.loc[date])

                if protection_stage == 1 and days_since_stop >= recovery_s1_days and is_regime_on:
                    protection_stage = 2

                if protection_stage == 2 and days_since_stop >= recovery_s2_days and is_regime_on:
                    in_protection_mode = False
                    protection_stage = 0
                    peak_value = portfolio_value
                    stop_loss_day_index = None
                    post_stop_base = None

        # --- Drawdown ---
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # --- Portfolio stop loss ---
        if drawdown <= portfolio_stop and not in_protection_mode:
            stop_events.append({
                'date': date,
                'portfolio_value': portfolio_value,
                'drawdown': drawdown,
                'stop_threshold': portfolio_stop,
            })

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

        # --- Cash yield (always on for all variants, matching v8.2 production) ---
        if cash > 0:
            daily_yield = cash * (CASH_YIELD_RATE / 252)
            cash += daily_yield
            total_cash_yield += daily_yield

        # --- Compute momentum scores ---
        daily_scores = None
        if len(positions) < max_positions or use_cond_hold:
            if use_ensemble:
                daily_scores = compute_momentum_scores_ensemble(
                    price_data, tradeable_symbols, date, i)
            else:
                daily_scores = compute_momentum_scores_standard(
                    price_data, tradeable_symbols, date, i)

        # --- Close positions ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            # 1. Hold time (with optional conditional extension)
            days_held = i - pos['entry_idx']

            if use_cond_hold:
                # Conditional hold extension logic:
                # At day 5, check if position qualifies for extension to day 10
                if days_held >= HOLD_DAYS:
                    if days_held < EXTENDED_HOLD_DAYS and not pos.get('extended', False):
                        # Check conditions for extension
                        extend = False
                        if daily_scores is not None:
                            # Condition 1: Still in Top-5 of momentum universe
                            ranked_tickers = sorted(daily_scores.keys(),
                                                    key=lambda x: daily_scores[x], reverse=True)
                            try:
                                current_rank = ranked_tickers.index(symbol) + 1
                                if current_rank <= COND_TOP_N_RANK:
                                    # Condition 2: ATR(5) < ATR(20) -- volatility declining
                                    atr_short = compute_atr(price_data, symbol, date, ATR_SHORT)
                                    atr_long = compute_atr(price_data, symbol, date, ATR_LONG)
                                    if atr_short is not None and atr_long is not None:
                                        if atr_short < atr_long:
                                            extend = True
                            except ValueError:
                                pass

                        if extend and days_held == HOLD_DAYS:
                            pos['extended'] = True
                            hold_extensions += 1
                            # Don't exit -- continue holding
                        elif pos.get('extended', False) and days_held >= EXTENDED_HOLD_DAYS:
                            exit_reason = 'hold_extended_expired'
                        elif not pos.get('extended', False):
                            exit_reason = 'hold_expired'
                    elif pos.get('extended', False) and days_held >= EXTENDED_HOLD_DAYS:
                        exit_reason = 'hold_extended_expired'
                    elif not pos.get('extended', False):
                        exit_reason = 'hold_expired'
            else:
                # Standard v8.2: fixed 5-day hold
                if days_held >= HOLD_DAYS:
                    exit_reason = 'hold_expired'

            # 2. Position stop loss (-8%)
            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'

            # 3. Trailing stop
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            # 4. Stock no longer in top-40
            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            # 5. Excess positions
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

        # --- Open new positions ---
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            if daily_scores is None:
                if use_ensemble:
                    daily_scores = compute_momentum_scores_ensemble(
                        price_data, tradeable_symbols, date, i)
                else:
                    daily_scores = compute_momentum_scores_standard(
                        price_data, tradeable_symbols, date, i)

            available_scores = {s: sc for s, sc in daily_scores.items() if s not in positions}

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
                            'extended': False,
                        }
                        cash -= cost + commission
                        total_turnover += abs(cost)

        # --- Record daily snapshot ---
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
            'in_protection': in_protection_mode,
            'risk_on': is_risk_on,
        })

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
        'total_cash_yield': total_cash_yield,
        'total_turnover': total_turnover,
        'protection_days': protection_days,
        'hold_extensions': hold_extensions,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results: Dict) -> Dict:
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
    total_trades = len(trades_df)

    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}

    # Annual returns
    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()

    # Average holding period
    if len(trades_df) > 0 and 'entry_date' in trades_df.columns and 'exit_date' in trades_df.columns:
        trades_df_copy = trades_df.copy()
        trades_df_copy['entry_date'] = pd.to_datetime(trades_df_copy['entry_date'])
        trades_df_copy['exit_date'] = pd.to_datetime(trades_df_copy['exit_date'])
        avg_hold_days = (trades_df_copy['exit_date'] - trades_df_copy['entry_date']).dt.days.mean()
    else:
        avg_hold_days = 0

    # Turnover ratio
    avg_portfolio = df['value'].mean()
    turnover_ratio = results.get('total_turnover', 0) / avg_portfolio / years if avg_portfolio > 0 and years > 0 else 0

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
        'trades_per_year': total_trades / years if years > 0 else 0,
        'avg_hold_days': avg_hold_days,
        'exit_reasons': exit_reasons,
        'stop_events': len(stop_df),
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
        'positive_years': int((annual_returns > 0).sum()) if len(annual_returns) > 0 else 0,
        'total_years': len(annual_returns),
        'total_cash_yield': results.get('total_cash_yield', 0),
        'turnover_ratio': turnover_ratio,
        'protection_days': results.get('protection_days', 0),
        'hold_extensions': results.get('hold_extensions', 0),
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 100)
    print("CHATGPT PROPOSAL TEST -- Ensemble Mom + Conditional Hold + Preemptive Stop")
    print("=" * 100)
    print(f"Proposal B: Ensemble momentum lookbacks = {ENSEMBLE_LOOKBACKS}")
    print(f"Proposal C: Conditional hold extension to {EXTENDED_HOLD_DAYS}d if Top-{COND_TOP_N_RANK} + ATR({ATR_SHORT}) < ATR({ATR_LONG})")
    print(f"Proposal D: Preemptive stop at {PREEMPTIVE_STOP_LOSS:.0%} (vs {PORTFOLIO_STOP_LOSS:.0%}), "
          f"recovery {PREEMPTIVE_RECOVERY_STAGE_1_DAYS}d/{PREEMPTIVE_RECOVERY_STAGE_2_DAYS}d "
          f"(vs {RECOVERY_STAGE_1_DAYS}d/{RECOVERY_STAGE_2_DAYS}d)")
    print()

    # 1. Load data
    price_data = download_broad_pool()
    print(f"Symbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    # 2. Annual top-40
    print("\nComputing annual top-40...")
    annual_universe = compute_annual_top40(price_data)

    # 3. Run all variants
    VARIANTS = [
        ('A) BASELINE (v8.2)', 'baseline'),
        ('B) ENSEMBLE MOM (60/90/120d)', 'ensemble_mom'),
        ('C) COND HOLD EXT (Top5+ATR)', 'cond_hold_ext'),
        ('D) PREEMPTIVE STOP (-8%)', 'preemptive_stop'),
        ('E) ENSEMBLE+COND (B+C)', 'ensemble_cond'),
        ('F) ALL THREE (B+C+D)', 'all_three'),
    ]

    all_results = {}
    all_metrics = {}

    for label, variant in VARIANTS:
        print(f"\n{'='*60}")
        print(f"Running: {label}")
        print(f"{'='*60}")

        results = run_backtest(
            price_data, annual_universe, spy_data,
            variant=variant,
        )
        metrics = calculate_metrics(results)
        all_results[label] = results
        all_metrics[label] = metrics

        extra = ""
        if metrics.get('hold_extensions', 0) > 0:
            extra += f" | Extensions: {metrics['hold_extensions']}"
        if metrics.get('protection_days', 0) > 0:
            extra += f" | ProtDays: {metrics['protection_days']}"

        print(f"  Final: ${metrics['final_value']:,.0f} | CAGR: {metrics['cagr']:.2%} | "
              f"Sharpe: {metrics['sharpe']:.3f} | MaxDD: {metrics['max_drawdown']:.1%} | "
              f"Trades: {metrics['total_trades']:,} | Stops: {metrics['stop_events']}"
              f"{extra}")

    # 4. Print comparison table
    print("\n\n" + "=" * 120)
    print("COMPARISON TABLE -- CHATGPT PROPOSALS vs BASELINE")
    print("=" * 120)

    header = f"{'Metric':<22}"
    for label, _ in VARIANTS:
        short = label.split(')')[0] + ')'
        header += f" {short:>16}"
    print(header)
    print("-" * 120)

    metric_rows = [
        ('Final Value', 'final_value', '${:>12,.0f}'),
        ('CAGR', 'cagr', '{:>12.2%}'),
        ('CAGR vs Base', None, None),  # Computed inline
        ('Sharpe', 'sharpe', '{:>12.3f}'),
        ('Sortino', 'sortino', '{:>12.3f}'),
        ('Calmar', 'calmar', '{:>12.3f}'),
        ('Max Drawdown', 'max_drawdown', '{:>12.1%}'),
        ('Volatility', 'volatility', '{:>12.1%}'),
        ('Win Rate', 'win_rate', '{:>12.1%}'),
        ('Total Trades', 'total_trades', '{:>12,}'),
        ('Trades/Year', 'trades_per_year', '{:>12.0f}'),
        ('Avg Hold (days)', 'avg_hold_days', '{:>12.1f}'),
        ('Stop Events', 'stop_events', '{:>12}'),
        ('Protection Days', 'protection_days', '{:>12,}'),
        ('Hold Extensions', 'hold_extensions', '{:>12,}'),
        ('Best Year', 'best_year', '{:>12.1%}'),
        ('Worst Year', 'worst_year', '{:>12.1%}'),
        ('Positive Years', 'positive_years', '{:>12}'),
        ('Cash Yield Total', 'total_cash_yield', '${:>11,.0f}'),
    ]

    baseline_cagr = all_metrics[VARIANTS[0][0]]['cagr']
    baseline_dd = all_metrics[VARIANTS[0][0]]['max_drawdown']

    for row_label, key, fmt in metric_rows:
        if row_label == 'CAGR vs Base':
            row = f"{'  CAGR delta':<22}"
            for label, _ in VARIANTS:
                diff = all_metrics[label]['cagr'] - baseline_cagr
                val_str = f"{diff:+.2%}"
                row += f" {val_str:>16}"
            print(row)
            continue

        row = f"{row_label:<22}"
        for label, _ in VARIANTS:
            val = all_metrics[label].get(key, 0)
            try:
                row += f" {fmt.format(val):>16}"
            except (ValueError, TypeError):
                row += f" {str(val):>16}"
        print(row)

    # 5. Exit reason breakdown
    print(f"\n{'='*120}")
    print("EXIT REASON BREAKDOWN")
    print(f"{'='*120}")

    all_reasons = set()
    for label, _ in VARIANTS:
        all_reasons.update(all_metrics[label].get('exit_reasons', {}).keys())
    all_reasons = sorted(all_reasons)

    header = f"{'Reason':<24}"
    for label, _ in VARIANTS:
        short = label.split(')')[0] + ')'
        header += f" {short:>16}"
    print(header)
    print("-" * 120)

    for reason in all_reasons:
        row = f"{reason:<24}"
        for label, _ in VARIANTS:
            count = all_metrics[label].get('exit_reasons', {}).get(reason, 0)
            total = all_metrics[label].get('total_trades', 1)
            pct = count / total * 100 if total > 0 else 0
            row += f" {count:>7} ({pct:>4.1f}%)  "
        print(row)

    # 6. Verdict
    print(f"\n{'='*120}")
    print("VERDICT")
    print(f"{'='*120}")

    for label, _ in VARIANTS[1:]:
        m = all_metrics[label]
        cagr_diff = m['cagr'] - baseline_cagr
        dd_diff = m['max_drawdown'] - baseline_dd

        if m['cagr'] > baseline_cagr and m['max_drawdown'] >= baseline_dd:
            verdict = "WINNER -- Higher CAGR, same or better MaxDD"
            emoji = ">>>"
        elif m['cagr'] > baseline_cagr and m['max_drawdown'] < baseline_dd:
            verdict = "MIXED -- Higher CAGR but WORSE MaxDD"
            emoji = "~~>"
        elif m['cagr'] <= baseline_cagr and m['max_drawdown'] >= baseline_dd:
            verdict = "LOSE -- Lower CAGR (better DD doesn't compensate)"
            emoji = " X "
        else:
            verdict = "LOSE -- Lower CAGR AND worse MaxDD"
            emoji = "XXX"

        print(f"\n  [{emoji}] {label}")
        print(f"    CAGR delta:       {cagr_diff:+.2%}")
        print(f"    MaxDD delta:      {dd_diff:+.1%} ({'better' if dd_diff > 0 else 'worse'})")
        print(f"    Stop events:      {m['stop_events']} (baseline: {all_metrics[VARIANTS[0][0]]['stop_events']})")
        print(f"    Protection days:  {m['protection_days']:,} (baseline: {all_metrics[VARIANTS[0][0]]['protection_days']:,})")
        if m.get('hold_extensions', 0) > 0:
            print(f"    Hold extensions:  {m['hold_extensions']:,}")
        print(f"    Verdict:          {verdict}")

    # 7. Save daily CSVs
    os.makedirs('backtests', exist_ok=True)
    for label, variant in VARIANTS:
        safe_name = variant.replace(' ', '_')
        all_results[label]['portfolio_values'].to_csv(
            f'backtests/chatgpt_{safe_name}_daily.csv', index=False)

    print(f"\nDaily CSVs saved to backtests/chatgpt_*.csv")
    print("\n" + "=" * 100)
    print("CHATGPT PROPOSAL TEST COMPLETE")
    print("=" * 100)
