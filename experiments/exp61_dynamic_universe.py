#!/usr/bin/env python3
"""
Experiment #61: Dynamic Universe — Top 113 by Market Cap, Top 40 by Momentum
=============================================================================
Instead of a hardcoded 113-stock pool with dollar-volume top-40 selection:
  1) Each year, get ACTUAL S&P 500 members (point-in-time from fja05680 snapshots)
  2) Rank by dollar volume (market cap proxy) → take top 113 (most valuable)
  3) From those 113, rank by 90d momentum (skip 5d) → take top 40
  4) COMPASS v8.2 algorithm runs on those 40 (unchanged signal logic)

This eliminates look-ahead bias (no NVDA in 2000) and uses momentum-based
universe selection instead of pure liquidity.

Baseline comparison:
  - Production (hardcoded 113, dollar-vol top-40): 18.56% CAGR, 0.90 Sharpe
  - Exp40 survivorship-corrected (PIT 500, dollar-vol top-40): 13.37% CAGR
  - This experiment: PIT 500 → top 113 by value → top 40 by momentum

Uses cached data from Exp #40 (827 tickers with prices, S&P 500 snapshots).
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import timedelta
from typing import Dict, List, Optional, Set
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# COMPASS v8.2 PARAMETERS (EXACT COPY — DO NOT MODIFY)
# =============================================================================
INITIAL_CAPITAL = 100_000
TOP_N = 40
BROAD_N = 113                     # Size of the dynamic broad pool
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20
HOLD_DAYS = 5
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03
PORTFOLIO_STOP_LOSS = -0.15
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 1.0
VOL_LOOKBACK = 20
MIN_AGE_DAYS = 63
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035
CASH_YIELD_SOURCE = 'AAA'
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126

START_DATE = '2000-01-01'
END_DATE = '2027-01-01'
SEED = 666

np.random.seed(SEED)


# =============================================================================
# DATA LOADING (reuses exp40 cached data)
# =============================================================================

def load_sp500_snapshots() -> pd.DataFrame:
    cache_file = 'data_cache/sp500_snapshots.csv'
    if not os.path.exists(cache_file):
        print("ERROR: sp500_snapshots.csv not found. Run exp40 first.")
        sys.exit(1)
    print("[Cache] Loading S&P 500 daily snapshots...")
    return pd.read_csv(cache_file, parse_dates=['date'])


def load_universe_prices() -> Dict[str, pd.DataFrame]:
    cache_file = 'data_cache/sp500_universe_prices.pkl'
    if not os.path.exists(cache_file):
        print("ERROR: sp500_universe_prices.pkl not found. Run exp40 first.")
        sys.exit(1)
    print("[Cache] Loading universe prices (827 tickers)...")
    with open(cache_file, 'rb') as f:
        return pickle.load(f)


def get_sp500_members_on_date(snapshots: pd.DataFrame, date: pd.Timestamp) -> Set[str]:
    valid = snapshots[snapshots['date'] <= date]
    if valid.empty:
        return set()
    latest = valid.iloc[-1]
    return set(t.strip() for t in str(latest['tickers']).split(',') if t.strip())


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


def download_cash_yield() -> Optional[pd.Series]:
    cache_file = 'data_cache/moody_aaa_yield.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading Moody's Aaa yield data...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        daily = df['yield_pct'].resample('D').ffill()
        return daily
    print("[Download] Downloading Moody's Aaa yield from FRED...")
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=1999-01-01&coed=2026-12-31'
        df = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
        df.columns = ['yield_pct']
        os.makedirs('data_cache', exist_ok=True)
        df.to_csv(cache_file)
        daily = df['yield_pct'].resample('D').ffill()
        return daily
    except Exception as e:
        print(f"  FRED failed: {e}. Using fixed {CASH_YIELD_RATE:.1%}")
        return None


# =============================================================================
# UNIVERSE SELECTION — THE KEY CHANGE
# =============================================================================

def compute_dynamic_universe(price_data: Dict[str, pd.DataFrame],
                              snapshots: pd.DataFrame) -> Dict[int, List[str]]:
    """
    Two-stage annual universe selection:
      Stage 1: From S&P 500 members (point-in-time), pick top 113 by dollar volume
      Stage 2: From those 113, pick top 40 by 90d momentum (skip 5d)

    This replaces the hardcoded BROAD_POOL + dollar-volume top-40.
    """
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}

    for year in years:
        ref_date = pd.Timestamp(f'{year}-01-01')
        sp500_members = get_sp500_members_on_date(snapshots, ref_date)

        if year == years[0]:
            ranking_end = pd.Timestamp(f'{year}-02-01')
            ranking_start = pd.Timestamp(f'{year-1}-01-01')
        else:
            ranking_end = pd.Timestamp(f'{year}-01-01')
            ranking_start = pd.Timestamp(f'{year-1}-01-01')

        # ── Stage 1: Top 113 by dollar volume (market cap proxy) ──
        dv_scores = {}
        for symbol in sp500_members:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            idx = df.index
            if idx.tz is not None:
                rs = ranking_start.tz_localize(idx.tz)
                re_ = ranking_end.tz_localize(idx.tz)
            else:
                rs = ranking_start
                re_ = ranking_end
            mask = (idx >= rs) & (idx < re_)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            dv_scores[symbol] = dollar_vol

        ranked_by_value = sorted(dv_scores.items(), key=lambda x: x[1], reverse=True)
        broad_113 = [s for s, _ in ranked_by_value[:BROAD_N]]

        # ── Stage 2: Top 40 by momentum from those 113 ──
        mom_scores = {}
        for symbol in broad_113:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            idx = df.index
            if idx.tz is not None:
                re_ = ranking_end.tz_localize(idx.tz)
            else:
                re_ = ranking_end

            mask = idx < re_
            window = df.loc[mask]
            if len(window) < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
                continue

            close_skip = window['Close'].iloc[-(MOMENTUM_SKIP + 1)]
            close_lookback = window['Close'].iloc[-(MOMENTUM_LOOKBACK + MOMENTUM_SKIP)]
            if close_lookback <= 0 or close_skip <= 0:
                continue
            momentum = close_skip / close_lookback - 1.0
            mom_scores[symbol] = momentum

        ranked_by_momentum = sorted(mom_scores.items(), key=lambda x: x[1], reverse=True)
        top_40 = [s for s, _ in ranked_by_momentum[:TOP_N]]
        annual_universe[year] = top_40

        if year > years[0]:
            prev = set(annual_universe.get(year - 1, []))
            curr = set(top_40)
            added = curr - prev
            removed = prev - curr
            print(f"  {year}: S&P500={len(sp500_members)}, data={len(dv_scores)}, "
                  f"Broad-{BROAD_N}={len(broad_113)}, Top-{TOP_N} by mom | "
                  f"+{len(added)} -{len(removed)}")
        else:
            print(f"  {year}: S&P500={len(sp500_members)}, data={len(dv_scores)}, "
                  f"Broad-{BROAD_N}={len(broad_113)}, Top-{TOP_N} by mom (initial)")

        top5_str = ', '.join(f"{s}({mom_scores[s]:+.1%})" for s, _ in ranked_by_momentum[:5] if s in mom_scores)
        print(f"         Top-5 momentum: {top5_str}")

    return annual_universe


# =============================================================================
# COMPASS v8.2 BACKTEST (EXACT COPY from exp40 — DO NOT MODIFY)
# =============================================================================

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


def run_backtest(price_data, annual_universe, spy_data, cash_yield_daily=None, label=""):
    print(f"\n{'='*80}")
    print(f"RUNNING COMPASS BACKTEST [{label}]")
    print(f"{'='*80}")

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

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

        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = True
            if date in regime.index:
                is_regime_on = bool(regime.loc[date])
            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2
            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({'date': date, 'portfolio_value': portfolio_value, 'drawdown': drawdown})
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

        is_risk_on = True
        if date in regime.index:
            is_risk_on = bool(regime.loc[date])
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

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

        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

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

        portfolio_values.append({
            'date': date, 'value': portfolio_value, 'cash': cash,
            'positions': len(positions), 'drawdown': drawdown,
            'leverage': current_leverage, 'in_protection': in_protection_mode,
            'risk_on': is_risk_on, 'universe_size': len(tradeable_symbols)
        })

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [PROTECTION S{protection_stage}]" if in_protection_mode else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str} | "
                  f"Pos: {len(positions)}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'annual_universe': annual_universe,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
    }


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

    sortino_denom = returns[returns < 0].std() * np.sqrt(252)
    sortino = cagr / sortino_denom if sortino_denom > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0

    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100

    pv = df['value']
    annual = pv.resample('YE').last().pct_change().dropna()

    return {
        'final_value': final_value,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'trades': len(trades_df),
        'win_rate': win_rate,
        'avg_trade': avg_trade,
        'stop_events': len(stop_df),
        'protection_days': protection_days,
        'protection_pct': protection_pct,
        'years': years,
        'annual_returns': annual,
    }


# =============================================================================
# HYDRA + EFA COMBINATION (from exp60)
# =============================================================================

def load_efa_data():
    cache_path = 'data_cache/efa_daily.pkl'
    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as f:
            efa = pickle.load(f)
        print(f"  EFA loaded from cache: {efa.index[0].date()} to {efa.index[-1].date()}")
        return efa
    print("  Downloading EFA data from yfinance...")
    raw = yf.download('EFA', start='2001-01-01', end='2026-12-31', progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    efa = raw[['Close']].rename(columns={'Close': 'close'})
    efa['ret'] = efa['close'].pct_change()
    efa['sma200'] = efa['close'].rolling(200).mean()
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_path, 'wb') as f:
        pickle.dump(efa, f)
    print(f"  EFA cached: {efa.index[0].date()} to {efa.index[-1].date()}")
    return efa


def run_hydra_efa(compass_daily, rattle_daily, efa, use_regime_filter=True):
    """
    Run HYDRA + EFA simulation (same as exp60 variant B).
    """
    MAX_COMPASS_ALLOC = 0.75
    BASE_COMPASS_ALLOC = 0.50
    BASE_RATTLE_ALLOC = 0.50

    c_ret = compass_daily['value'].pct_change()
    r_ret = rattle_daily['value'].pct_change()
    r_exposure = rattle_daily['exposure']

    df = pd.DataFrame({
        'c_ret': c_ret,
        'r_ret': r_ret,
        'r_exposure': r_exposure,
    }).dropna()

    c_account = INITIAL_CAPITAL * BASE_COMPASS_ALLOC
    r_account = INITIAL_CAPITAL * BASE_RATTLE_ALLOC
    efa_value = 0.0

    portfolio_values = []

    for i in range(len(df)):
        date = df.index[i]
        r_exp = df['r_exposure'].iloc[i]
        total_value = c_account + r_account + efa_value

        r_idle = r_account * (1.0 - r_exp)
        max_c_account = total_value * MAX_COMPASS_ALLOC
        max_recyclable = max(0, max_c_account - c_account)
        recycle_amount = min(r_idle, max_recyclable)

        c_effective = c_account + recycle_amount
        r_effective = r_account - recycle_amount

        r_still_idle = r_effective * (1.0 - r_exp)
        idle_cash = r_still_idle

        efa_eligible = True
        if use_regime_filter and date in efa.index:
            sma = efa.loc[date, 'sma200']
            close = efa.loc[date, 'close']
            if pd.notna(sma) and close < sma:
                efa_eligible = False

        if date in efa.index and efa_eligible:
            target_efa = idle_cash
        else:
            target_efa = 0.0

        if target_efa > efa_value:
            buy_amount = target_efa - efa_value
            r_effective -= buy_amount
            efa_value += buy_amount
        elif target_efa < efa_value:
            sell_amount = efa_value - target_efa
            efa_value -= sell_amount
            r_effective += sell_amount

        c_ret_val = df['c_ret'].iloc[i]
        r_ret_val = df['r_ret'].iloc[i]

        if date in efa.index and efa_value > 0:
            efa_ret = efa.loc[date, 'ret']
            if pd.isna(efa_ret):
                efa_ret = 0.0
        else:
            efa_ret = 0.0

        c_account_new = c_effective * (1 + c_ret_val)
        r_account_new = r_effective * (1 + r_ret_val)
        efa_value_new = efa_value * (1 + efa_ret)

        recycled_after = recycle_amount * (1 + c_ret_val)
        c_account = c_account_new - recycled_after
        r_account = r_account_new + recycled_after
        efa_value = efa_value_new

        total_new = c_account + r_account + efa_value
        portfolio_values.append(total_new)

    pv = pd.Series(portfolio_values, index=df.index)
    return pv


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("EXPERIMENT #61: DYNAMIC UNIVERSE")
    print("Top 113 by Market Cap (PIT) -> Top 40 by Momentum")
    print("=" * 80)
    print()

    # ── Load data ──
    print("--- Loading Data ---")
    snapshots = load_sp500_snapshots()
    price_data = load_universe_prices()
    spy_data = download_spy()
    cash_yield_daily = download_cash_yield()
    efa = load_efa_data()

    rattle = pd.read_csv('backtests/rattlesnake_daily.csv', index_col=0, parse_dates=True)
    print(f"  Rattlesnake daily: {rattle.index[0].date()} to {rattle.index[-1].date()}")

    print(f"\n  Universe: {len(price_data)} tickers with price data")

    # ── Compute dynamic universe ──
    print(f"\n--- Computing Dynamic Universe (Top-{BROAD_N} by value -> Top-{TOP_N} by momentum) ---")
    dynamic_universe = compute_dynamic_universe(price_data, snapshots)

    # ── Run COMPASS backtest with dynamic universe ──
    compass_results = run_backtest(price_data, dynamic_universe, spy_data, cash_yield_daily,
                                    label="EXP61: Dynamic Universe")
    compass_metrics = calculate_metrics(compass_results)

    # ── Save COMPASS daily for HYDRA combination ──
    os.makedirs('backtests', exist_ok=True)
    compass_daily = compass_results['portfolio_values'].set_index('date')
    compass_daily.to_csv('backtests/exp61_compass_daily.csv')

    # ── Run HYDRA + EFA ──
    print(f"\n--- Running HYDRA + EFA (regime-filtered) ---")
    hydra_pv = run_hydra_efa(compass_daily, rattle, efa, use_regime_filter=True)

    hydra_years = len(hydra_pv) / 252
    hydra_cagr = (hydra_pv.iloc[-1] / INITIAL_CAPITAL) ** (1 / hydra_years) - 1
    hydra_maxdd = (hydra_pv / hydra_pv.cummax() - 1).min()
    hydra_returns = hydra_pv.pct_change().dropna()
    hydra_sharpe = hydra_returns.mean() / hydra_returns.std() * np.sqrt(252)
    hydra_vol = hydra_returns.std() * np.sqrt(252)

    hydra_out = pd.DataFrame({'value': hydra_pv})
    hydra_out.to_csv('backtests/exp61_hydra_daily.csv')

    # ── Results ──
    print(f"\n\n{'=' * 80}")
    print(f"  EXPERIMENT #61 RESULTS")
    print(f"{'=' * 80}")

    print(f"\n  --- COMPASS STANDALONE (Dynamic Universe) ---")
    print(f"  Period:        {compass_daily.index[0].date()} -> {compass_daily.index[-1].date()}")
    print(f"  Final Value:   ${compass_metrics['final_value']:>12,.0f}")
    print(f"  CAGR:          {compass_metrics['cagr']:>11.2%}")
    print(f"  Volatility:    {compass_metrics['volatility']:>11.2%}")
    print(f"  Max Drawdown:  {compass_metrics['max_drawdown']:>11.2%}")
    print(f"  Sharpe:        {compass_metrics['sharpe']:>11.2f}")
    print(f"  Sortino:       {compass_metrics['sortino']:>11.2f}")
    print(f"  Trades:        {compass_metrics['trades']:>11,}")
    print(f"  Win Rate:      {compass_metrics['win_rate']:>11.2%}")
    print(f"  Avg Trade:     ${compass_metrics['avg_trade']:>11,.2f}")
    print(f"  Stop Events:   {compass_metrics['stop_events']:>11}")
    print(f"  Protection:    {compass_metrics['protection_pct']:>10.1f}%")

    print(f"\n  --- HYDRA + EFA (Dynamic Universe + Rattlesnake + EFA) ---")
    print(f"  Final Value:   ${hydra_pv.iloc[-1]:>12,.0f}")
    print(f"  CAGR:          {hydra_cagr:>11.2%}")
    print(f"  Volatility:    {hydra_vol:>11.2%}")
    print(f"  Max Drawdown:  {hydra_maxdd:>11.2%}")
    print(f"  Sharpe:        {hydra_sharpe:>11.2f}")

    # ── Annual returns ──
    print(f"\n  --- ANNUAL RETURNS (COMPASS) ---")
    for idx, ret in compass_metrics['annual_returns'].items():
        yr = idx.year
        bar = ('+' if ret > 0 else '-') * min(int(abs(ret) * 100), 50)
        print(f"  {yr}  {ret:>+7.2%}  {bar}")

    # ── Comparison table ──
    print(f"\n\n{'=' * 80}")
    print(f"  COMPARISON TABLE")
    print(f"{'=' * 80}")
    print(f"  {'METRIC':<18} {'Production':>14} {'Exp40 (PIT)':>14} {'Exp61 (this)':>14}")
    print(f"  {'-' * 62}")
    print(f"  {'Universe':<18} {'113 fixed':>14} {'~500 PIT':>14} {'113 PIT+mom':>14}")
    print(f"  {'Top-40 by':<18} {'Dollar Vol':>14} {'Dollar Vol':>14} {'Momentum':>14}")
    print(f"  {'CAGR':<18} {'18.56%':>14} {'13.37%':>14} {compass_metrics['cagr']:>13.2%}")
    print(f"  {'Sharpe':<18} {'0.90':>14} {'0.64':>14} {compass_metrics['sharpe']:>13.2f}")
    print(f"  {'Max DD':<18} {'-26.9%':>14} {'-44.2%':>14} {compass_metrics['max_drawdown']:>13.2%}")
    print(f"  {'Final ($100K)':<18} {'$8.43M':>14} {'$1.34M':>14} ${compass_metrics['final_value']/1e6:>12.2f}M")
    print(f"  {'-' * 62}")
    print(f"  {'HYDRA+EFA CAGR':<18} {'--':>14} {'--':>14} {hydra_cagr:>13.2%}")
    print(f"  {'HYDRA+EFA Final':<18} {'$3.77M':>14} {'--':>14} ${hydra_pv.iloc[-1]/1e6:>12.2f}M")
    print(f"{'=' * 80}")

    # ── Verdict ──
    print(f"\n  VERDICT:")
    baseline_cagr = 0.1337
    delta = compass_metrics['cagr'] - baseline_cagr
    if compass_metrics['cagr'] >= 0.15:
        verdict = "STRONG PASS"
    elif compass_metrics['cagr'] >= baseline_cagr:
        verdict = "PASS (beats survivorship-corrected baseline)"
    else:
        verdict = "FAIL (worse than survivorship-corrected baseline)"

    print(f"    COMPASS: {verdict}")
    print(f"    vs Exp40 baseline: {delta:+.2%} CAGR")
    print(f"    vs Production:     {compass_metrics['cagr'] - 0.1856:+.2%} CAGR")

    print(f"\nSaved: backtests/exp61_compass_daily.csv")
    print(f"Saved: backtests/exp61_hydra_daily.csv")
