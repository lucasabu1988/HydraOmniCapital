#!/usr/bin/env python3
"""
Experiment #64: Universe Filters on PIT Selection
==================================================
Tests filters on the 113-stock broad pool before top-40 dollar-volume ranking.

Variant A: SMA200 trend filter — exclude stocks below their SMA200
Variant B: Net margin >= 15% — exclude low-margin companies

Pipeline:
  1) S&P 500 PIT (~503) -> top 113 by dollar volume
  2) FILTER: apply criterion
  3) Top 40 by dollar volume from survivors
  4) COMPASS v8.2 algorithm runs on those 40

If fewer than MIN_POST_FILTER stocks survive, relax filter.
Period: 2000-01-01 to 2026 | Baseline: PIT no filter
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
BROAD_N = 113
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

# Filter parameters
SMA_FILTER_PERIOD = 200
MIN_POST_FILTER = 60  # minimum stocks after filtering; relax if below this
NET_MARGIN_THRESHOLD = 0.15  # 15% net margin minimum

np.random.seed(SEED)

# SEC EDGAR cached data paths (from exp62)
SEC_EDGAR_NETINCOME_CACHE = 'data_cache/sec_edgar_netincome.json'
SEC_EDGAR_REVENUE_CACHE = 'data_cache/sec_edgar_revenue.json'


# =============================================================================
# DATA LOADING (reuses exp61 cached data)
# =============================================================================

def load_sp500_snapshots() -> pd.DataFrame:
    cache_file = 'data_cache/sp500_snapshots.csv'
    if not os.path.exists(cache_file):
        print("ERROR: sp500_snapshots.csv not found. Run exp40 first.")
        sys.exit(1)
    print("[Cache] Loading S&P 500 daily snapshots...")
    return pd.read_csv(cache_file, parse_dates=['date'])


def load_universe_prices() -> Dict[str, pd.DataFrame]:
    merged_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              'data_sources', 'merged_universe')
    if os.path.exists(merged_dir):
        print(f"[merged_universe] Loading from {merged_dir}...")
        data = {}
        corrupted = 0
        for f in os.listdir(merged_dir):
            if not f.endswith('.parquet'):
                continue
            ticker = f.replace('.parquet', '')
            try:
                df = pd.read_parquet(os.path.join(merged_dir, f))
                if len(df) < 10 or 'Close' not in df.columns:
                    continue
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                if len(df) < 10:
                    continue
                if df['Close'].max() > 5000:
                    corrupted += 1; continue
                if (df['Close'] < 0.01).sum() > 5:
                    corrupted += 1; continue
                returns = df['Close'].pct_change().abs()
                bad = returns > 0.80
                if bad.sum() / len(df) > 0.02:
                    corrupted += 1; continue
                if bad.sum() > 0:
                    bad.iloc[0] = False
                    df = df[~bad]
                if len(df) < 10:
                    continue
                data[ticker] = df
            except Exception:
                pass
        print(f"  Loaded {len(data)} tickers ({corrupted} corrupted removed)")
        return data

    print("ERROR: No merged_universe found. Run merge_survivorship_data.py first.")
    sys.exit(1)


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
# UNIVERSE SELECTION — BASELINE (no filter) + SMA200 FILTER
# =============================================================================

def compute_universe_baseline(price_data, snapshots):
    """Baseline: PIT S&P 500 -> top 113 by $vol -> top 40 by $vol (no filter)."""
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}
    for year in years:
        ref_date = pd.Timestamp(f'{year}-01-01')
        sp500_members = get_sp500_members_on_date(snapshots, ref_date)
        ranking_end = pd.Timestamp(f'{year}-01-01')
        ranking_start = pd.Timestamp(f'{year - 1}-01-01')

        dv_scores = {}
        for symbol in sp500_members:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dv_scores[symbol] = (window['Close'] * window['Volume']).mean()

        ranked = sorted(dv_scores.items(), key=lambda x: x[1], reverse=True)
        broad_113 = [s for s, _ in ranked[:BROAD_N]]
        top_40 = broad_113[:TOP_N]
        annual_universe[year] = top_40
    return annual_universe


def compute_universe_sma_filter(price_data, snapshots):
    """SMA200 filter: PIT -> top 113 by $vol -> exclude below SMA200 -> top 40 by $vol."""
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}
    filter_stats = {}

    for year in years:
        ref_date = pd.Timestamp(f'{year}-01-01')
        sp500_members = get_sp500_members_on_date(snapshots, ref_date)
        ranking_end = pd.Timestamp(f'{year}-01-01')
        ranking_start = pd.Timestamp(f'{year - 1}-01-01')

        # Stage 1: top 113 by dollar volume
        dv_scores = {}
        for symbol in sp500_members:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dv_scores[symbol] = (window['Close'] * window['Volume']).mean()

        ranked = sorted(dv_scores.items(), key=lambda x: x[1], reverse=True)
        broad_113 = [s for s, _ in ranked[:BROAD_N]]

        # Stage 2: SMA200 filter — check if stock is above its SMA200 at year-end
        above_sma = []
        below_sma = []
        sma_distance = {}  # for relaxation fallback

        for symbol in broad_113:
            if symbol not in price_data:
                below_sma.append(symbol)
                continue
            df = price_data[symbol]
            # Get data up to ranking_end
            hist = df[df.index < ranking_end]
            if len(hist) < SMA_FILTER_PERIOD:
                below_sma.append(symbol)
                continue

            close = hist['Close'].iloc[-1]
            sma200 = hist['Close'].iloc[-SMA_FILTER_PERIOD:].mean()

            if close > sma200:
                above_sma.append(symbol)
            else:
                below_sma.append(symbol)
            sma_distance[symbol] = (close / sma200 - 1.0) if sma200 > 0 else -1.0

        # Relaxation: if too few stocks pass, add closest-to-SMA from below
        filtered_pool = list(above_sma)
        relaxed = 0
        if len(filtered_pool) < MIN_POST_FILTER:
            # Sort below-SMA stocks by distance to SMA (closest first)
            below_ranked = sorted(below_sma, key=lambda s: sma_distance.get(s, -1.0), reverse=True)
            needed = MIN_POST_FILTER - len(filtered_pool)
            filtered_pool.extend(below_ranked[:needed])
            relaxed = min(needed, len(below_ranked))

        # Stage 3: top 40 by dollar volume from filtered pool
        filtered_dv = [(s, dv_scores[s]) for s in filtered_pool if s in dv_scores]
        filtered_dv.sort(key=lambda x: x[1], reverse=True)
        top_40 = [s for s, _ in filtered_dv[:TOP_N]]
        annual_universe[year] = top_40

        filter_stats[year] = {
            'sp500': len(sp500_members),
            'broad': len(broad_113),
            'above_sma': len(above_sma),
            'below_sma': len(below_sma),
            'relaxed': relaxed,
            'final_pool': len(filtered_pool),
        }

        # Logging
        excluded = set(broad_113[:TOP_N]) - set(top_40)
        added = set(top_40) - set(broad_113[:TOP_N])
        stats = filter_stats[year]
        relaxed_str = f", relaxed +{stats['relaxed']}" if stats['relaxed'] > 0 else ''
        print(f"  {year}: {stats['broad']} broad -> {stats['above_sma']} above SMA200 "
              f"(filtered {stats['below_sma']}{relaxed_str}) "
              f"-> {len(top_40)} final")
        if excluded:
            print(f"         Filtered OUT: {', '.join(sorted(excluded)[:8])}"
                  f"{'...' if len(excluded) > 8 else ''}")
        if added:
            print(f"         Promoted IN:  {', '.join(sorted(added)[:8])}"
                  f"{'...' if len(added) > 8 else ''}")

    return annual_universe, filter_stats


def load_sec_edgar_data():
    """Load cached net income and revenue from exp62's SEC EDGAR downloads."""
    import json
    ni_data = {}
    rev_data = {}
    if os.path.exists(SEC_EDGAR_NETINCOME_CACHE):
        with open(SEC_EDGAR_NETINCOME_CACHE, 'r') as f:
            raw = json.load(f)
        ni_data = {t: {int(y): v for y, v in years.items()} for t, years in raw.items()}
    if os.path.exists(SEC_EDGAR_REVENUE_CACHE):
        with open(SEC_EDGAR_REVENUE_CACHE, 'r') as f:
            raw = json.load(f)
        rev_data = {t: {int(y): v for y, v in years.items()} for t, years in raw.items()}
    return ni_data, rev_data


def compute_universe_margin_filter(price_data, snapshots, ni_data, rev_data):
    """Net margin filter: PIT -> top 113 by $vol -> exclude margin < 15% -> top 40 by $vol."""
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}
    filter_stats = {}

    for year in years:
        ref_date = pd.Timestamp(f'{year}-01-01')
        sp500_members = get_sp500_members_on_date(snapshots, ref_date)
        ranking_end = pd.Timestamp(f'{year}-01-01')
        ranking_start = pd.Timestamp(f'{year - 1}-01-01')

        # Stage 1: top 113 by dollar volume
        dv_scores = {}
        for symbol in sp500_members:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dv_scores[symbol] = (window['Close'] * window['Volume']).mean()

        ranked = sorted(dv_scores.items(), key=lambda x: x[1], reverse=True)
        broad_113 = [s for s, _ in ranked[:BROAD_N]]

        # Stage 2: Net margin filter — require >= 15%
        passes = []
        fails = []
        no_data = []
        margins = {}

        for symbol in broad_113:
            ticker_ni = ni_data.get(symbol, {})
            ticker_rev = rev_data.get(symbol, {})
            ni_val = ticker_ni.get(year - 1) or ticker_ni.get(year - 2)
            rev_val = ticker_rev.get(year - 1) or ticker_rev.get(year - 2)
            if ni_val is not None and rev_val and rev_val > 0:
                margin = ni_val / rev_val
                margins[symbol] = margin
                if margin >= NET_MARGIN_THRESHOLD:
                    passes.append(symbol)
                else:
                    fails.append(symbol)
            else:
                no_data.append(symbol)

        # Relaxation: if too few pass, add highest-margin from fails + no_data
        filtered_pool = list(passes)
        relaxed = 0
        if len(filtered_pool) < MIN_POST_FILTER:
            # Sort fails by margin descending (closest to threshold first)
            fails_ranked = sorted(fails, key=lambda s: margins.get(s, -999), reverse=True)
            needed = MIN_POST_FILTER - len(filtered_pool)
            extra = fails_ranked + no_data  # prefer known margins over unknown
            filtered_pool.extend(extra[:needed])
            relaxed = min(needed, len(extra))

        # Stage 3: top 40 by dollar volume from filtered pool
        filtered_dv = [(s, dv_scores[s]) for s in filtered_pool if s in dv_scores]
        filtered_dv.sort(key=lambda x: x[1], reverse=True)
        top_40 = [s for s, _ in filtered_dv[:TOP_N]]
        annual_universe[year] = top_40

        filter_stats[year] = {
            'broad': len(broad_113),
            'passes': len(passes),
            'fails': len(fails),
            'no_data': len(no_data),
            'relaxed': relaxed,
        }

        excluded = set(broad_113[:TOP_N]) - set(top_40)
        added = set(top_40) - set(broad_113[:TOP_N])
        s = filter_stats[year]
        relaxed_str = f", relaxed +{s['relaxed']}" if s['relaxed'] > 0 else ''
        print(f"  {year}: {s['broad']} broad -> {s['passes']} pass >=15% "
              f"(reject {s['fails']}, no_data {s['no_data']}{relaxed_str}) "
              f"-> {len(top_40)} final")
        if excluded:
            excl_with_margin = [(e, f"{margins[e]:.0%}") if e in margins else (e, "n/a") for e in sorted(excluded)[:6]]
            print(f"         Filtered OUT: {', '.join(f'{e}({m})' for e, m in excl_with_margin)}"
                  f"{'...' if len(excluded) > 6 else ''}")

    return annual_universe, filter_stats


# =============================================================================
# COMPASS v8.2 BACKTEST (EXACT COPY from exp61)
# =============================================================================

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
            is_regime_on = bool(regime.loc[date]) if date in regime.index else True
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

        is_risk_on = bool(regime.loc[date]) if date in regime.index else True
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        if in_protection_mode:
            max_positions = 2 if protection_stage == 1 else 3
            current_leverage = 0.3 if protection_stage == 1 else 1.0
        elif not is_risk_on:
            max_positions = NUM_POSITIONS_RISK_OFF
            current_leverage = 1.0
        else:
            max_positions = NUM_POSITIONS
            current_leverage = compute_dynamic_leverage(spy_data, date)

        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            cash -= MARGIN_RATE / 252 * borrowed

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
                if current_price <= pos['high_price'] * (1 - TRAILING_STOP_PCT):
                    exit_reason = 'trailing_stop'
            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'
            if exit_reason is None and len(positions) > max_positions:
                pos_returns = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        pos_returns[s] = (price_data[s].loc[date, 'Close'] - p['entry_price']) / p['entry_price']
                if symbol == min(pos_returns, key=pos_returns.get):
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
                    position_value = min(effective_capital * weight, cash * 0.40)
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

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
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
    sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    sortino_denom = returns[returns < 0].std() * np.sqrt(252)
    sortino = cagr / sortino_denom if sortino_denom > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    protection_pct = df['in_protection'].sum() / len(df) * 100
    annual = df['value'].resample('YE').last().pct_change().dropna()
    return {
        'final': final_value, 'cagr': cagr, 'vol': volatility,
        'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar,
        'maxdd': max_dd, 'trades': len(trades_df), 'win_rate': win_rate,
        'avg_trade': avg_trade, 'stops': len(stop_df),
        'protection_pct': protection_pct, 'years': years, 'annual': annual,
    }


# =============================================================================
# HYDRA COMBINATION (from exp63)
# =============================================================================

def load_efa():
    cache_path = 'data_cache/efa_daily.pkl'
    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as f:
            return pickle.load(f)
    raw = yf.download('EFA', start='2001-01-01', end='2026-12-31', progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    efa = raw[['Close']].rename(columns={'Close': 'close'})
    efa['ret'] = efa['close'].pct_change()
    efa['sma200'] = efa['close'].rolling(200).mean()
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_path, 'wb') as f:
        pickle.dump(efa, f)
    return efa


def load_catalyst_assets():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets = {}
    for ticker in ['TLT', 'GLD', 'DBC', 'GC=F']:
        cache_path = os.path.join(base_dir, 'data_cache', f'catalyst_{ticker.replace("=", "_")}.pkl')
        if os.path.exists(cache_path):
            with open(cache_path, 'rb') as f:
                assets[ticker] = pickle.load(f)
        else:
            df = yf.download(ticker, start='1999-01-01', end='2026-12-31', progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df[['Close']].dropna()
            df.columns = ['close']
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            df['ret'] = df['close'].pct_change().fillna(0)
            df['sma200'] = df['close'].rolling(200).mean()
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, 'wb') as f:
                pickle.dump(df, f)
            assets[ticker] = df
    return assets


def run_full_hydra(compass_daily, rattle_daily, efa, catalyst_assets):
    """Full HYDRA: 42.5% COMPASS + 42.5% Rattlesnake + 15% Catalyst + EFA."""
    c_ret = compass_daily['value'].pct_change()
    r_ret = rattle_daily['value'].pct_change()
    r_exposure = rattle_daily['exposure']
    df = pd.DataFrame({'c_ret': c_ret, 'r_ret': r_ret, 'r_exposure': r_exposure}).dropna()

    c_acc = INITIAL_CAPITAL * 0.425
    r_acc = INITIAL_CAPITAL * 0.425
    cat_acc = INITIAL_CAPITAL * 0.15
    efa_val = 0.0
    pv_list = []

    for i in range(len(df)):
        date = df.index[i]
        r_exp = df['r_exposure'].iloc[i]
        total = c_acc + r_acc + cat_acc + efa_val

        r_idle = r_acc * (1.0 - r_exp)
        max_c = (total - cat_acc) * 0.75
        recycle = min(r_idle, max(0, max_c - c_acc))

        c_eff = c_acc + recycle
        r_eff = r_acc - recycle
        r_still_idle = r_eff * (1.0 - r_exp)

        efa_ok = True
        if date in efa.index:
            s = efa.loc[date, 'sma200']
            c = efa.loc[date, 'close']
            if pd.notna(s) and c < s:
                efa_ok = False
        tgt_efa = r_still_idle if (date in efa.index and efa_ok) else 0.0
        if tgt_efa > efa_val:
            r_eff -= (tgt_efa - efa_val)
            efa_val = tgt_efa
        elif tgt_efa < efa_val:
            r_eff += (efa_val - tgt_efa)
            efa_val = tgt_efa

        # Catalyst return
        trend_rets = []
        for t in ['TLT', 'GLD', 'DBC']:
            d = catalyst_assets.get(t)
            if d is not None and date in d.index and pd.notna(d.loc[date, 'sma200']):
                if d.loc[date, 'close'] > d.loc[date, 'sma200']:
                    trend_rets.append(d.loc[date, 'ret'])
        trend_r = np.mean(trend_rets) if trend_rets else 0.0
        gold_r = 0.0
        gld = catalyst_assets.get('GLD')
        if gld is not None and date in gld.index:
            gold_r = gld.loc[date, 'ret']
        elif 'GC=F' in catalyst_assets and date in catalyst_assets['GC=F'].index:
            gold_r = catalyst_assets['GC=F'].loc[date, 'ret']
        cat_r = 0.667 * trend_r + 0.333 * gold_r

        efa_r = 0.0
        if date in efa.index and efa_val > 0:
            efa_r = efa.loc[date, 'ret']
            if pd.isna(efa_r): efa_r = 0.0

        c_new = c_eff * (1 + df['c_ret'].iloc[i])
        r_new = r_eff * (1 + df['r_ret'].iloc[i])
        cat_new = cat_acc * (1 + cat_r)
        efa_new = efa_val * (1 + efa_r)

        recycled_after = recycle * (1 + df['c_ret'].iloc[i])
        c_acc = c_new - recycled_after
        r_acc = r_new + recycled_after
        cat_acc = cat_new
        efa_val = efa_new
        pv_list.append(c_acc + r_acc + cat_acc + efa_val)

    return pd.Series(pv_list, index=df.index)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("EXPERIMENT #64: SMA200 TREND FILTER ON UNIVERSE SELECTION")
    print("S&P 500 PIT -> top 113 by $vol -> SMA200 filter -> top 40 by $vol")
    print("=" * 80)

    # Load data
    print("\n--- Loading Data ---")
    snapshots = load_sp500_snapshots()
    price_data = load_universe_prices()
    spy_data = download_spy()
    cash_yield_daily = download_cash_yield()

    # Load SEC EDGAR data for margin filter
    print(f"\n--- Loading SEC EDGAR data ---")
    ni_data, rev_data = load_sec_edgar_data()
    print(f"  Net income: {sum(1 for d in ni_data.values() if d)} tickers")
    print(f"  Revenue: {sum(1 for d in rev_data.values() if d)} tickers")

    # Compute universes
    print(f"\n--- Baseline: PIT -> top 113 -> top 40 (no filter) ---")
    baseline_universe = compute_universe_baseline(price_data, snapshots)

    print(f"\n--- Net Margin Filter: PIT -> top 113 -> margin >= 15% -> top 40 ---")
    margin_universe, margin_stats = compute_universe_margin_filter(price_data, snapshots, ni_data, rev_data)

    # Run COMPASS backtests
    baseline_results = run_backtest(price_data, baseline_universe, spy_data, cash_yield_daily,
                                    label="BASELINE (no filter)")
    baseline_m = calculate_metrics(baseline_results)

    margin_results = run_backtest(price_data, margin_universe, spy_data, cash_yield_daily,
                                  label="NET MARGIN >= 15%")
    margin_m = calculate_metrics(margin_results)

    # Save daily results
    os.makedirs('backtests', exist_ok=True)
    baseline_daily = baseline_results['portfolio_values'].set_index('date')
    margin_daily = margin_results['portfolio_values'].set_index('date')
    baseline_daily.to_csv('backtests/exp64_baseline_compass_daily.csv')
    margin_daily.to_csv('backtests/exp64_margin15_compass_daily.csv')

    # Run full HYDRA for both variants
    print(f"\n--- Loading HYDRA components ---")
    rattle = pd.read_csv('backtests/rattlesnake_daily.csv', index_col=0, parse_dates=True)
    efa = load_efa()
    catalyst_assets = load_catalyst_assets()

    print(f"\n--- Running Full HYDRA (baseline) ---")
    hydra_baseline = run_full_hydra(baseline_daily, rattle, efa, catalyst_assets)
    hb_years = len(hydra_baseline) / 252
    hb_cagr = (hydra_baseline.iloc[-1] / INITIAL_CAPITAL) ** (1 / hb_years) - 1
    hb_maxdd = (hydra_baseline / hydra_baseline.cummax() - 1).min()
    hb_sharpe = hydra_baseline.pct_change().dropna().mean() / hydra_baseline.pct_change().dropna().std() * np.sqrt(252)

    print(f"\n--- Running Full HYDRA (margin filter) ---")
    hydra_margin = run_full_hydra(margin_daily, rattle, efa, catalyst_assets)
    hm_years = len(hydra_margin) / 252
    hm_cagr = (hydra_margin.iloc[-1] / INITIAL_CAPITAL) ** (1 / hm_years) - 1
    hm_maxdd = (hydra_margin / hydra_margin.cummax() - 1).min()
    hm_sharpe = hydra_margin.pct_change().dropna().mean() / hydra_margin.pct_change().dropna().std() * np.sqrt(252)

    pd.DataFrame({'value': hydra_baseline}).to_csv('backtests/exp64_baseline_hydra_daily.csv')
    pd.DataFrame({'value': hydra_margin}).to_csv('backtests/exp64_margin15_hydra_daily.csv')

    # Results
    print(f"\n\n{'=' * 80}")
    print(f"  EXPERIMENT #64B — NET MARGIN >= 15% FILTER")
    print(f"{'=' * 80}")
    print(f"\n  COMPASS STANDALONE:")
    print(f"  {'METRIC':<18} {'Baseline':>14} {'Margin>=15%':>14} {'Delta':>10}")
    print(f"  {'-' * 58}")
    print(f"  {'CAGR':<18} {baseline_m['cagr']:>13.2%} {margin_m['cagr']:>13.2%} {margin_m['cagr']-baseline_m['cagr']:>+9.2%}")
    print(f"  {'Sharpe':<18} {baseline_m['sharpe']:>13.2f} {margin_m['sharpe']:>13.2f} {margin_m['sharpe']-baseline_m['sharpe']:>+9.2f}")
    print(f"  {'Sortino':<18} {baseline_m['sortino']:>13.2f} {margin_m['sortino']:>13.2f} {margin_m['sortino']-baseline_m['sortino']:>+9.2f}")
    print(f"  {'Max DD':<18} {baseline_m['maxdd']:>13.2%} {margin_m['maxdd']:>13.2%} {margin_m['maxdd']-baseline_m['maxdd']:>+9.2%}")
    print(f"  {'Volatility':<18} {baseline_m['vol']:>13.2%} {margin_m['vol']:>13.2%} {margin_m['vol']-baseline_m['vol']:>+9.2%}")
    print(f"  {'Win Rate':<18} {baseline_m['win_rate']:>13.2%} {margin_m['win_rate']:>13.2%} {margin_m['win_rate']-baseline_m['win_rate']:>+9.2%}")
    print(f"  {'Trades':<18} {baseline_m['trades']:>13,} {margin_m['trades']:>13,}")
    print(f"  {'Avg Trade':<18} ${baseline_m['avg_trade']:>11,.2f} ${margin_m['avg_trade']:>11,.2f}")
    print(f"  {'Final ($100K)':<18} ${baseline_m['final']/1e6:>11.2f}M ${margin_m['final']/1e6:>11.2f}M")

    print(f"\n  FULL HYDRA (42.5/42.5/15 + EFA):")
    print(f"  {'METRIC':<18} {'Baseline':>14} {'Margin>=15%':>14} {'Delta':>10}")
    print(f"  {'-' * 58}")
    print(f"  {'CAGR':<18} {hb_cagr:>13.2%} {hm_cagr:>13.2%} {hm_cagr-hb_cagr:>+9.2%}")
    print(f"  {'Sharpe':<18} {hb_sharpe:>13.2f} {hm_sharpe:>13.2f} {hm_sharpe-hb_sharpe:>+9.2f}")
    print(f"  {'Max DD':<18} {hb_maxdd:>13.2%} {hm_maxdd:>13.2%} {hm_maxdd-hb_maxdd:>+9.2%}")
    print(f"  {'Final ($100K)':<18} ${hydra_baseline.iloc[-1]/1e6:>11.2f}M ${hydra_margin.iloc[-1]/1e6:>11.2f}M")

    # Annual comparison
    print(f"\n  ANNUAL RETURNS (COMPASS):")
    print(f"  {'Year':<6} {'Baseline':>10} {'Margin15':>10} {'Delta':>8}")
    print(f"  {'-' * 36}")
    b_ann = baseline_m['annual']
    m_ann = margin_m['annual']
    for yr in sorted(set(b_ann.index.year) | set(m_ann.index.year)):
        bv = b_ann[b_ann.index.year == yr]
        mv = m_ann[m_ann.index.year == yr]
        bs = f"{bv.iloc[0]:>+7.2%}" if len(bv) > 0 else f"{'--':>8}"
        ms = f"{mv.iloc[0]:>+7.2%}" if len(mv) > 0 else f"{'--':>8}"
        d = f"{mv.iloc[0]-bv.iloc[0]:>+6.1%}" if len(bv) > 0 and len(mv) > 0 else ""
        print(f"  {yr:<6} {bs:>10} {ms:>10} {d:>8}")

    # Verdict
    compass_better = margin_m['cagr'] > baseline_m['cagr'] and margin_m['maxdd'] >= baseline_m['maxdd'] - 0.05
    hydra_better = hm_cagr > hb_cagr and hm_maxdd >= hb_maxdd - 0.05
    print(f"\n  VERDICT:")
    print(f"    COMPASS: {'IMPROVEMENT' if compass_better else 'NO IMPROVEMENT'} "
          f"(CAGR {margin_m['cagr']-baseline_m['cagr']:+.2%}, MaxDD {margin_m['maxdd']-baseline_m['maxdd']:+.2%})")
    print(f"    HYDRA:   {'IMPROVEMENT' if hydra_better else 'NO IMPROVEMENT'} "
          f"(CAGR {hm_cagr-hb_cagr:+.2%}, MaxDD {hm_maxdd-hb_maxdd:+.2%})")

    print(f"\nSaved: backtests/exp64_*.csv")
