"""
Test: Protection-Mode Inverse ETF Trading vs Cash Baseline
==========================================================
During portfolio stop-loss protection (~2,002 days / 30.5% of backtest),
instead of sitting in cash at 3%, trade inverse ETFs with staged sizing.

A) BASELINE        -- Cash at 3% yield during protection (current v8.2)
B) SH_STAGED       -- Buy SH (1x inverse SPY) during protection
                      Stage 1: 15% of cash, Stage 2: 30% of cash
C) SDS_STAGED      -- Buy SDS (2x inverse SPY) during protection
                      Stage 1: 10% of cash, Stage 2: 20% of cash
D) SH_AGGRESSIVE   -- SH with higher allocation
                      Stage 1: 25% of cash, Stage 2: 50% of cash

For pre-2006 (SH/SDS didn't exist), we use synthetic inverse SPY returns.
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

# Protection short parameters
SH_INCEPTION = pd.Timestamp('2006-06-23')
SDS_INCEPTION = pd.Timestamp('2006-07-10')

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


def download_inverse_etf(ticker: str) -> pd.DataFrame:
    """Download SH or SDS inverse ETF data."""
    cache_file = f'data_cache/{ticker}_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        print(f"[Cache] Loading {ticker} data...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    print(f"[Download] Downloading {ticker}...")
    try:
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False)
        if not df.empty and len(df) > 50:
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            os.makedirs('data_cache', exist_ok=True)
            df.to_csv(cache_file)
            return df
    except Exception as e:
        print(f"  [Warning] Could not download {ticker}: {e}")
    return pd.DataFrame()


def build_inverse_returns(spy_data: pd.DataFrame,
                          sh_data: pd.DataFrame,
                          sds_data: pd.DataFrame) -> Dict[str, pd.Series]:
    """
    Build daily return series for inverse instruments.
    Uses real ETF data when available, synthetic (SPY * -1x or -2x) before inception.

    Returns dict with 'sh_return' and 'sds_return' series indexed by date.
    """
    spy_returns = spy_data['Close'].pct_change()

    # SH returns: -1x SPY
    sh_returns = pd.Series(index=spy_returns.index, dtype=float)
    # Pre-inception: synthetic
    sh_returns.loc[:] = -1.0 * spy_returns
    # Post-inception: use real SH data if available
    if not sh_data.empty:
        sh_real = sh_data['Close'].pct_change()
        for date in sh_real.index:
            if date in sh_returns.index and date >= SH_INCEPTION:
                sh_returns.loc[date] = sh_real.loc[date]
        real_count = (sh_returns.index >= SH_INCEPTION).sum()
        synth_count = (sh_returns.index < SH_INCEPTION).sum()
        print(f"  SH returns: {synth_count} synthetic + {real_count} real days")

    # SDS returns: -2x SPY
    sds_returns = pd.Series(index=spy_returns.index, dtype=float)
    # Pre-inception: synthetic 2x
    sds_returns.loc[:] = -2.0 * spy_returns
    # Post-inception: use real SDS data
    if not sds_data.empty:
        sds_real = sds_data['Close'].pct_change()
        for date in sds_real.index:
            if date in sds_returns.index and date >= SDS_INCEPTION:
                sds_returns.loc[date] = sds_real.loc[date]
        real_count = (sds_returns.index >= SDS_INCEPTION).sum()
        synth_count = (sds_returns.index < SDS_INCEPTION).sum()
        print(f"  SDS returns: {synth_count} synthetic + {real_count} real days")

    return {
        'sh_return': sh_returns.fillna(0),
        'sds_return': sds_returns.fillna(0),
    }


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
# BACKTEST ENGINE WITH PROTECTION-MODE SHORT VARIANTS
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data,
                 variant='baseline',
                 inverse_returns=None,
                 stage1_alloc=0.0,
                 stage2_alloc=0.0,
                 inverse_key='sh_return') -> Dict:
    """
    Run COMPASS backtest with variant-specific protection-mode behavior.

    Variants:
        'baseline'      - Cash at 3% during protection (v8.2)
        'sh_staged'     - Buy SH (1x inverse) during protection, staged sizing
        'sds_staged'    - Buy SDS (2x inverse) during protection, staged sizing
        'sh_aggressive' - Buy SH with higher allocation during protection
    """

    use_inverse = variant != 'baseline'

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

    # Protection tracking
    protection_day_count = 0
    recovery_events = []
    current_stop_date = None

    # Inverse ETF position tracking during protection
    inverse_position_value = 0.0  # Current value allocated to inverse ETF
    total_inverse_pnl = 0.0

    for i, date in enumerate(all_dates):
        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # --- Calculate portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # Add inverse ETF position value to portfolio
        portfolio_value += inverse_position_value

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

            # --- Apply inverse ETF daily return during protection ---
            if use_inverse and inverse_position_value > 0 and inverse_returns is not None:
                if date in inverse_returns[inverse_key].index:
                    daily_ret = inverse_returns[inverse_key].loc[date]
                    if not np.isnan(daily_ret):
                        pnl_today = inverse_position_value * daily_ret
                        inverse_position_value += pnl_today
                        total_inverse_pnl += pnl_today
                        # Prevent going negative
                        if inverse_position_value < 0:
                            total_inverse_pnl += inverse_position_value  # adjust for the loss
                            inverse_position_value = 0.0

            # Stage transitions
            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2
                # Close inverse position from stage 1, re-allocate for stage 2
                if use_inverse and inverse_position_value > 0:
                    cash += inverse_position_value
                    inverse_position_value = 0.0
                # Open stage 2 inverse position with higher allocation
                if use_inverse:
                    alloc = stage2_alloc
                    inverse_position_value = cash * alloc
                    cash -= inverse_position_value
                print(f"  [RECOVERY S1] {date.strftime('%Y-%m-%d')}: Stage 2 | "
                      f"Days: {days_since_stop} | Value: ${portfolio_value:,.0f}")

            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                # Close inverse position on full recovery
                if inverse_position_value > 0:
                    cash += inverse_position_value
                    inverse_position_value = 0.0
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

            # Open inverse ETF position for stage 1
            if use_inverse:
                alloc = stage1_alloc
                inverse_position_value = cash * alloc
                cash -= inverse_position_value
                print(f"    [INVERSE] Opened {inverse_key} position: ${inverse_position_value:,.0f} ({alloc:.0%} of cash)")

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

        # --- Cash yield (on uninvested cash, not on inverse position) ---
        if cash > 0:
            daily_yield = cash * (CASH_YIELD_RATE / 252)
            cash += daily_yield
            total_cash_yield += daily_yield

        # --- Compute momentum scores ---
        daily_scores = None
        if len(positions) < max_positions:
            daily_scores = compute_momentum_scores(price_data, tradeable_symbols, date, i)

        # --- Close positions (standard v8.2) ---
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

        # --- Open new positions ---
        needed = max_positions - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            if daily_scores is None:
                daily_scores = compute_momentum_scores(price_data, tradeable_symbols, date, i)
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
            'protection_stage': protection_stage,
            'inverse_value': inverse_position_value,
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
        'recovery_events': recovery_events,
        'total_protection_days': protection_day_count,
        'total_inverse_pnl': total_inverse_pnl,
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

    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()

    if len(trades_df) > 0 and 'entry_date' in trades_df.columns and 'exit_date' in trades_df.columns:
        trades_df_copy = trades_df.copy()
        trades_df_copy['entry_date'] = pd.to_datetime(trades_df_copy['entry_date'])
        trades_df_copy['exit_date'] = pd.to_datetime(trades_df_copy['exit_date'])
        avg_hold_days = (trades_df_copy['exit_date'] - trades_df_copy['entry_date']).dt.days.mean()
    else:
        avg_hold_days = 0

    avg_portfolio = df['value'].mean()
    turnover_ratio = results.get('total_turnover', 0) / avg_portfolio / years if avg_portfolio > 0 and years > 0 else 0

    # Recovery metrics
    recovery_events = results.get('recovery_events', [])
    total_protection_days = results.get('total_protection_days', 0)
    protection_pct = total_protection_days / len(df) * 100 if len(df) > 0 else 0

    if recovery_events:
        durations = [e['duration_days'] for e in recovery_events]
        avg_recovery = np.mean(durations)
    else:
        avg_recovery = 0

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
        'total_protection_days': total_protection_days,
        'protection_pct': protection_pct,
        'avg_recovery_duration': avg_recovery,
        'total_inverse_pnl': results.get('total_inverse_pnl', 0),
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("PROTECTION-MODE INVERSE ETF TEST")
    print("Short via inverse ETFs during portfolio stop-loss protection")
    print("=" * 80)
    print()

    # 1. Load data
    price_data = download_broad_pool()
    print(f"Symbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    sh_data = download_inverse_etf('SH')
    print(f"SH data: {len(sh_data)} trading days" if not sh_data.empty else "SH: no data (will use synthetic)")

    sds_data = download_inverse_etf('SDS')
    print(f"SDS data: {len(sds_data)} trading days" if not sds_data.empty else "SDS: no data (will use synthetic)")

    # 2. Build inverse return series
    print("\nBuilding inverse return series...")
    inverse_returns = build_inverse_returns(spy_data, sh_data, sds_data)

    # 3. Annual top-40
    print("\nComputing annual top-40...")
    annual_universe = compute_annual_top40(price_data)

    # 4. Define variants
    VARIANTS = [
        {
            'label': 'A) BASELINE (v8.2)',
            'variant': 'baseline',
            'stage1_alloc': 0.0,
            'stage2_alloc': 0.0,
            'inverse_key': 'sh_return',
        },
        {
            'label': 'B) SH STAGED (15%/30%)',
            'variant': 'sh_staged',
            'stage1_alloc': 0.15,
            'stage2_alloc': 0.30,
            'inverse_key': 'sh_return',
        },
        {
            'label': 'C) SDS STAGED (10%/20%)',
            'variant': 'sds_staged',
            'stage1_alloc': 0.10,
            'stage2_alloc': 0.20,
            'inverse_key': 'sds_return',
        },
        {
            'label': 'D) SH AGGRESSIVE (25%/50%)',
            'variant': 'sh_aggressive',
            'stage1_alloc': 0.25,
            'stage2_alloc': 0.50,
            'inverse_key': 'sh_return',
        },
    ]

    # 5. Run all variants
    all_results = {}
    all_metrics = {}

    for v in VARIANTS:
        print(f"\n{'='*60}")
        print(f"Running: {v['label']}")
        if v['variant'] != 'baseline':
            print(f"  Stage 1: {v['stage1_alloc']:.0%} -> Stage 2: {v['stage2_alloc']:.0%} in {v['inverse_key']}")
        print(f"{'='*60}")

        results = run_backtest(
            price_data, annual_universe, spy_data,
            variant=v['variant'],
            inverse_returns=inverse_returns,
            stage1_alloc=v['stage1_alloc'],
            stage2_alloc=v['stage2_alloc'],
            inverse_key=v['inverse_key'],
        )
        metrics = calculate_metrics(results)
        all_results[v['label']] = results
        all_metrics[v['label']] = metrics

        inv_pnl = metrics.get('total_inverse_pnl', 0)
        print(f"  Final: ${metrics['final_value']:,.0f} | CAGR: {metrics['cagr']:.2%} | "
              f"Sharpe: {metrics['sharpe']:.3f} | MaxDD: {metrics['max_drawdown']:.1%} | "
              f"Inverse P&L: ${inv_pnl:,.0f}")

    # 6. Performance comparison table
    print("\n\n" + "=" * 100)
    print("PERFORMANCE COMPARISON -- Protection-Mode Inverse ETF Trading")
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
        ('Win Rate',         'win_rate',        '{:>14.1%}'),
        ('Total Trades',     'total_trades',    '{:>14,}'),
        ('Best Year',        'best_year',       '{:>14.1%}'),
        ('Worst Year',       'worst_year',      '{:>14.1%}'),
        ('Cash Yield Total', 'total_cash_yield','${:>13,.0f}'),
        ('Inverse P&L',      'total_inverse_pnl','${:>13,.0f}'),
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

    # 7. Protection analysis
    print(f"\n{'='*100}")
    print("PROTECTION ANALYSIS")
    print(f"{'='*100}")

    header = f"{'Metric':<22}"
    for label in labels:
        short = label.split(')')[0] + ')'
        header += f" {short:>18}"
    print(header)
    print("-" * 100)

    prot_rows = [
        ('Stop Events',         'stop_events',          '{:>14}'),
        ('Protection Days',     'total_protection_days', '{:>14,}'),
        ('% Time Protected',    'protection_pct',        '{:>13.1f}%'),
        ('Avg Recovery (days)', 'avg_recovery_duration', '{:>14.0f}'),
    ]

    for row_label, key, fmt in prot_rows:
        row = f"{row_label:<22}"
        for label in labels:
            val = all_metrics[label].get(key, 0)
            try:
                row += f" {fmt.format(val):>18}"
            except (ValueError, TypeError):
                row += f" {str(val):>18}"
        print(row)

    # 8. Verdict
    print(f"\n{'='*100}")
    print("VERDICT")
    print(f"{'='*100}")

    baseline_cagr = all_metrics[labels[0]]['cagr']
    baseline_dd = all_metrics[labels[0]]['max_drawdown']

    for label in labels[1:]:
        m = all_metrics[label]
        cagr_diff = m['cagr'] - baseline_cagr
        dd_diff = m['max_drawdown'] - baseline_dd
        inv_pnl = m.get('total_inverse_pnl', 0)

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
        print(f"    Inverse P&L:      ${inv_pnl:+,.0f}")
        print(f"    Verdict:          {verdict}")

    # 9. Save CSVs
    os.makedirs('backtests', exist_ok=True)
    for v in VARIANTS:
        safe_name = v['variant']
        all_results[v['label']]['portfolio_values'].to_csv(
            f'backtests/protshort_{safe_name}_daily.csv', index=False)

    print(f"\nDaily CSVs saved to backtests/protshort_*.csv")
    print("\n" + "=" * 80)
    print("PROTECTION-MODE INVERSE ETF TEST COMPLETE")
    print("=" * 80)
