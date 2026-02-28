#!/usr/bin/env python3
"""
COMPASS v8.2 — Cross-Validation: yfinance vs Stooq
=====================================================
Downloads the same BROAD_POOL from Stooq (independent data source)
and re-runs the FULL COMPASS backtest to validate results.

Stooq provides free historical OHLCV data (split+dividend adjusted)
for US stocks without requiring an API key.

This script:
  1. Downloads all 113 stocks + SPY from Stooq
  2. Compares daily returns vs yfinance data (correlation analysis)
  3. Runs the EXACT same COMPASS backtest with Stooq data
  4. Reports metric differences (CAGR, Sharpe, MaxDD, trades)

Usage:  python cross_validation_stooq.py
"""

import os
import sys
import time
import pickle
import requests
import io
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

# =============================================================================
# COMPASS v8.2 PARAMETERS (EXACT COPY — DO NOT MODIFY)
# =============================================================================
INITIAL_CAPITAL = 100_000
TOP_N = 40
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
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
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126

START_DATE = '2000-01-01'
END_DATE = '2027-01-01'

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


# =============================================================================
# STOOQ DATA DOWNLOAD
# =============================================================================

def stooq_ticker(ticker: str) -> str:
    """Convert standard ticker to Stooq format"""
    # BRK-B -> brk-b.us, normal tickers -> ticker.us
    return f"{ticker.lower()}.us"


def download_stooq_stock(ticker: str, start: str = '20000101', end: str = '20261231',
                          max_retries: int = 3) -> Optional[pd.DataFrame]:
    """Download a single stock from Stooq"""
    stooq_sym = stooq_ticker(ticker)
    url = f'https://stooq.com/q/d/l/?s={stooq_sym}&d1={start}&d2={end}&i=d'

    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (COMPASS CrossVal)'}, timeout=30)
            if r.status_code != 200:
                time.sleep(1)
                continue

            text = r.text.strip()
            if not text or 'No data' in text or len(text) < 50:
                return None

            df = pd.read_csv(io.StringIO(text), parse_dates=['Date'], index_col='Date')
            df = df.sort_index()

            # Stooq Close is already split+dividend adjusted
            if 'Close' not in df.columns or len(df) < 100:
                return None

            # Ensure numeric
            for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            df = df.dropna(subset=['Close'])
            return df

        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
            continue

    return None


def download_stooq_broad_pool() -> Dict[str, pd.DataFrame]:
    """Download all BROAD_POOL stocks from Stooq"""
    cache_file = 'data_cache/stooq_broad_pool.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading Stooq broad pool data...")
        try:
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
            print(f"  {len(data)} symbols loaded from cache")
            return data
        except Exception:
            print("[Cache] Failed, re-downloading...")

    print(f"\n[Stooq] Downloading {len(BROAD_POOL)} symbols...")
    data = {}
    failed = []

    for i, symbol in enumerate(BROAD_POOL):
        df = download_stooq_stock(symbol)
        if df is not None and len(df) > 100:
            data[symbol] = df
        else:
            failed.append(symbol)

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(BROAD_POOL)}] Downloaded {len(data)} | Failed {len(failed)}")

        # Polite delay to avoid rate limiting
        time.sleep(0.4)

    print(f"\n[Stooq] {len(data)} symbols valid, {len(failed)} failed")
    if failed:
        print(f"  Failed: {failed}")

    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)

    return data


def download_stooq_spy() -> pd.DataFrame:
    """Download SPY from Stooq. Falls back to ^SPX index if SPY too short."""
    cache_file = 'data_cache/stooq_spy.csv'

    if os.path.exists(cache_file):
        print("[Cache] Loading Stooq SPY data...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)

    # Try SPY ETF first
    print("[Stooq] Downloading SPY...")
    df = download_stooq_stock('SPY')

    if df is None or len(df) < 2000:
        # Stooq SPY only goes back to ~2005, use S&P 500 index instead
        print("[Stooq] SPY too short, trying ^SPX index...")
        url = 'https://stooq.com/q/d/l/?s=^spx&d1=19990101&d2=20261231&i=d'
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
            df = pd.read_csv(io.StringIO(r.text), parse_dates=['Date'], index_col='Date')
            df = df.sort_index()
            for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            df = df.dropna(subset=['Close'])
            print(f"  ^SPX data: {len(df)} days ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
        except Exception as e:
            print(f"  ^SPX failed: {e}")
            return None

    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


# =============================================================================
# DATA COMPARISON (yfinance vs Stooq)
# =============================================================================

def compare_data_sources(yf_data: Dict[str, pd.DataFrame],
                          stooq_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Compare daily returns between yfinance and Stooq for each stock"""
    print("\n" + "=" * 80)
    print("DATA SOURCE COMPARISON: yfinance vs Stooq")
    print("=" * 80)

    common_symbols = sorted(set(yf_data.keys()) & set(stooq_data.keys()))
    print(f"\nCommon symbols: {len(common_symbols)}")
    print(f"yfinance only: {len(set(yf_data.keys()) - set(stooq_data.keys()))}")
    print(f"Stooq only: {len(set(stooq_data.keys()) - set(yf_data.keys()))}")

    results = []

    for symbol in common_symbols:
        yf_df = yf_data[symbol]
        st_df = stooq_data[symbol]

        # Align on common dates
        common_dates = yf_df.index.intersection(st_df.index)
        if len(common_dates) < 100:
            results.append({
                'symbol': symbol,
                'common_days': len(common_dates),
                'return_corr': None,
                'mean_abs_diff': None,
                'max_abs_diff': None,
                'price_corr': None,
                'note': 'insufficient_overlap'
            })
            continue

        yf_close = yf_df.loc[common_dates, 'Close']
        st_close = st_df.loc[common_dates, 'Close']

        # Daily returns comparison (this is what matters for COMPASS)
        yf_ret = yf_close.pct_change().dropna()
        st_ret = st_close.pct_change().dropna()

        common_ret_dates = yf_ret.index.intersection(st_ret.index)
        yf_ret = yf_ret.loc[common_ret_dates]
        st_ret = st_ret.loc[common_ret_dates]

        if len(yf_ret) < 50:
            continue

        # Metrics
        return_corr = yf_ret.corr(st_ret)
        diff = (yf_ret - st_ret).abs()
        mean_abs_diff = diff.mean() * 100  # in %
        max_abs_diff = diff.max() * 100

        # Price level correlation
        yf_p = yf_close.loc[common_dates]
        st_p = st_close.loc[common_dates]
        price_corr = yf_p.corr(st_p)

        # Price level difference (%)
        price_diff_pct = ((yf_p - st_p).abs() / yf_p).mean() * 100

        results.append({
            'symbol': symbol,
            'common_days': len(common_dates),
            'return_corr': return_corr,
            'mean_abs_diff_pct': mean_abs_diff,
            'max_abs_diff_pct': max_abs_diff,
            'price_corr': price_corr,
            'price_diff_pct': price_diff_pct,
            'note': 'ok'
        })

    df = pd.DataFrame(results)
    ok = df[df['note'] == 'ok']

    print(f"\n--- Daily Return Correlation ---")
    print(f"Mean:   {ok['return_corr'].mean():.6f}")
    print(f"Median: {ok['return_corr'].median():.6f}")
    print(f"Min:    {ok['return_corr'].min():.6f}  ({ok.loc[ok['return_corr'].idxmin(), 'symbol']})")
    print(f"Max:    {ok['return_corr'].max():.6f}  ({ok.loc[ok['return_corr'].idxmax(), 'symbol']})")
    print(f"Stocks with corr > 0.999: {(ok['return_corr'] > 0.999).sum()}/{len(ok)}")
    print(f"Stocks with corr > 0.99:  {(ok['return_corr'] > 0.99).sum()}/{len(ok)}")
    print(f"Stocks with corr > 0.95:  {(ok['return_corr'] > 0.95).sum()}/{len(ok)}")

    print(f"\n--- Mean Abs Daily Return Difference ---")
    print(f"Mean:   {ok['mean_abs_diff_pct'].mean():.4f}%")
    print(f"Median: {ok['mean_abs_diff_pct'].median():.4f}%")
    print(f"Max:    {ok['mean_abs_diff_pct'].max():.4f}%  ({ok.loc[ok['mean_abs_diff_pct'].idxmax(), 'symbol']})")

    print(f"\n--- Price Level Difference ---")
    print(f"Mean:   {ok['price_diff_pct'].mean():.2f}%")
    print(f"Median: {ok['price_diff_pct'].median():.2f}%")
    print(f"Max:    {ok['price_diff_pct'].max():.2f}%  ({ok.loc[ok['price_diff_pct'].idxmax(), 'symbol']})")

    # Flag problematic stocks
    problematic = ok[ok['return_corr'] < 0.99]
    if len(problematic) > 0:
        print(f"\n--- PROBLEMATIC STOCKS (return corr < 0.99) ---")
        for _, row in problematic.iterrows():
            print(f"  {row['symbol']}: corr={row['return_corr']:.4f} | diff={row['mean_abs_diff_pct']:.4f}%")

    return df


# =============================================================================
# MOMENTUM RANKING COMPARISON
# =============================================================================

def compare_momentum_rankings(yf_data: Dict[str, pd.DataFrame],
                                stooq_data: Dict[str, pd.DataFrame],
                                sample_dates: int = 20) -> None:
    """Compare momentum rankings between data sources on random dates"""
    from scipy import stats as scipy_stats

    print("\n" + "=" * 80)
    print("MOMENTUM RANKING COMPARISON")
    print("=" * 80)

    common_symbols = sorted(set(yf_data.keys()) & set(stooq_data.keys()))

    # Get common trading dates
    yf_dates = set()
    for df in yf_data.values():
        yf_dates.update(df.index)

    st_dates = set()
    for df in stooq_data.values():
        st_dates.update(df.index)

    common_dates = sorted(yf_dates & st_dates)
    # Only use dates where we have enough history
    valid_dates = [d for d in common_dates if d >= pd.Timestamp('2001-06-01')]

    if len(valid_dates) < sample_dates:
        print("Not enough common dates for comparison")
        return

    # Sample evenly across the backtest period
    np.random.seed(666)
    step = len(valid_dates) // sample_dates
    check_dates = [valid_dates[i * step] for i in range(sample_dates)]

    spearman_corrs = []
    top5_matches = []

    for date in check_dates:
        yf_scores = {}
        st_scores = {}

        for symbol in common_symbols:
            # yfinance scores
            if symbol in yf_data:
                yf_df = yf_data[symbol]
                if date in yf_df.index:
                    try:
                        idx = yf_df.index.get_loc(date)
                        if idx >= MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
                            c_today = yf_df['Close'].iloc[idx]
                            c_skip = yf_df['Close'].iloc[idx - MOMENTUM_SKIP]
                            c_look = yf_df['Close'].iloc[idx - MOMENTUM_LOOKBACK]
                            if c_look > 0 and c_skip > 0 and c_today > 0:
                                mom = (c_skip / c_look) - 1.0
                                skip = (c_today / c_skip) - 1.0
                                yf_scores[symbol] = mom - skip
                    except Exception:
                        pass

            # Stooq scores
            if symbol in stooq_data:
                st_df = stooq_data[symbol]
                if date in st_df.index:
                    try:
                        idx = st_df.index.get_loc(date)
                        if idx >= MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
                            c_today = st_df['Close'].iloc[idx]
                            c_skip = st_df['Close'].iloc[idx - MOMENTUM_SKIP]
                            c_look = st_df['Close'].iloc[idx - MOMENTUM_LOOKBACK]
                            if c_look > 0 and c_skip > 0 and c_today > 0:
                                mom = (c_skip / c_look) - 1.0
                                skip = (c_today / c_skip) - 1.0
                                st_scores[symbol] = mom - skip
                    except Exception:
                        pass

        # Compare rankings
        common_scored = sorted(set(yf_scores.keys()) & set(st_scores.keys()))
        if len(common_scored) < 10:
            continue

        yf_vals = [yf_scores[s] for s in common_scored]
        st_vals = [st_scores[s] for s in common_scored]

        corr, _ = scipy_stats.spearmanr(yf_vals, st_vals)
        spearman_corrs.append(corr)

        # Top-5 match
        yf_top5 = set(sorted(common_scored, key=lambda s: yf_scores[s], reverse=True)[:5])
        st_top5 = set(sorted(common_scored, key=lambda s: st_scores[s], reverse=True)[:5])
        overlap = len(yf_top5 & st_top5)
        top5_matches.append(overlap)

    print(f"\nSampled {len(spearman_corrs)} dates across backtest period")
    print(f"\n--- Spearman Rank Correlation (Momentum Scores) ---")
    print(f"Mean:   {np.mean(spearman_corrs):.4f}")
    print(f"Median: {np.median(spearman_corrs):.4f}")
    print(f"Min:    {np.min(spearman_corrs):.4f}")
    print(f"Max:    {np.max(spearman_corrs):.4f}")

    print(f"\n--- Top-5 Stock Selection Match ---")
    print(f"Mean overlap: {np.mean(top5_matches):.1f}/5 ({np.mean(top5_matches)/5*100:.0f}%)")
    print(f"Min overlap:  {np.min(top5_matches)}/5")
    print(f"Max overlap:  {np.max(top5_matches)}/5")
    print(f"Perfect match (5/5): {sum(1 for x in top5_matches if x == 5)}/{len(top5_matches)}")


# =============================================================================
# COMPASS BACKTEST (EXACT REPLICA)
# =============================================================================
# Imported directly from omnicapital_v8_compass.py logic — DO NOT MODIFY

def compute_annual_top40(price_data):
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))
    annual_universe = {}
    for year in years:
        if year == years[0]:
            ranking_end = pd.Timestamp(f'{year}-02-01')
            ranking_start = pd.Timestamp(f'{year-1}-01-01')
        else:
            ranking_end = pd.Timestamp(f'{year}-01-01')
            ranking_start = pd.Timestamp(f'{year-1}-01-01')
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


def download_cash_yield():
    cache_file = 'data_cache/moody_aaa_yield.csv'
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        daily = df['yield_pct'].resample('D').ffill()
        return daily
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=1999-01-01&coed=2026-12-31'
        df = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
        df.columns = ['yield_pct']
        os.makedirs('data_cache', exist_ok=True)
        df.to_csv(cache_file)
        daily = df['yield_pct'].resample('D').ffill()
        return daily
    except Exception:
        return None


def run_backtest(price_data, annual_universe, spy_data, cash_yield_daily=None, label="STOOQ"):
    """Run COMPASS backtest — exact replica"""
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
                        'symbol': symbol, 'entry_date': pos['entry_date'], 'exit_date': date,
                        'exit_reason': 'portfolio_stop', 'pnl': pnl,
                        'return': pnl / (pos['entry_price'] * pos['shares'])
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
                    'symbol': symbol, 'entry_date': pos['entry_date'], 'exit_date': date,
                    'exit_reason': exit_reason, 'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares)
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
                            'entry_date': date, 'entry_idx': i, 'high_price': entry_price,
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
            prot_str = f" [PROT S{protection_stage}]" if in_protection_mode else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str}")

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
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100
    risk_off_pct = results['risk_off_days'] / (results['risk_on_days'] + results['risk_off_days']) * 100
    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}

    return {
        'initial': initial, 'final_value': final_value,
        'years': years, 'cagr': cagr, 'volatility': volatility,
        'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar,
        'max_drawdown': max_dd, 'win_rate': win_rate, 'avg_trade': avg_trade,
        'trades': len(trades_df), 'exit_reasons': exit_reasons,
        'stop_events': len(stop_df),
        'protection_days': protection_days, 'protection_pct': protection_pct,
        'risk_off_pct': risk_off_pct,
    }


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    t_start = time.time()

    print("=" * 80)
    print("COMPASS v8.2 — CROSS-VALIDATION: yfinance vs Stooq")
    print("=" * 80)
    print(f"Broad pool: {len(BROAD_POOL)} stocks")
    print(f"Period: {START_DATE} to present")
    print()

    # -------------------------------------------------------------------------
    # 1. LOAD yfinance DATA (from existing cache)
    # -------------------------------------------------------------------------
    print("--- STEP 1: Load yfinance data (existing cache) ---")
    import yfinance as yf

    yf_cache = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'
    if os.path.exists(yf_cache):
        with open(yf_cache, 'rb') as f:
            yf_data = pickle.load(f)
        print(f"  yfinance: {len(yf_data)} symbols loaded from cache")
    else:
        print("  ERROR: yfinance cache not found. Run omnicapital_v8_compass.py first.")
        sys.exit(1)

    # Load yfinance SPY
    yf_spy_cache = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(yf_spy_cache):
        yf_spy = pd.read_csv(yf_spy_cache, index_col=0, parse_dates=True)
        print(f"  yfinance SPY: {len(yf_spy)} days")
    else:
        print("  Downloading yfinance SPY...")
        yf_spy = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
        yf_spy.columns = [c[0] if isinstance(c, tuple) else c for c in yf_spy.columns]
        print(f"  yfinance SPY: {len(yf_spy)} days")

    # -------------------------------------------------------------------------
    # 2. DOWNLOAD STOOQ DATA
    # -------------------------------------------------------------------------
    print("\n--- STEP 2: Download Stooq data ---")
    stooq_data = download_stooq_broad_pool()
    stooq_spy = download_stooq_spy()

    if stooq_spy is None or len(stooq_spy) < 1000:
        print("  ERROR: Could not download SPY/^SPX from Stooq.")
        print("  Using yfinance SPY for regime filter (data comparison still valid for stocks)")
        stooq_spy = yf_spy.copy()

    print(f"  Stooq SPY: {len(stooq_spy)} days")

    # -------------------------------------------------------------------------
    # 3. DATA COMPARISON
    # -------------------------------------------------------------------------
    print("\n--- STEP 3: Data source comparison ---")
    comparison_df = compare_data_sources(yf_data, stooq_data)

    # -------------------------------------------------------------------------
    # 4. MOMENTUM RANKING COMPARISON
    # -------------------------------------------------------------------------
    print("\n--- STEP 4: Momentum ranking comparison ---")
    try:
        compare_momentum_rankings(yf_data, stooq_data, sample_dates=20)
    except Exception as e:
        print(f"  Ranking comparison failed (scipy not available?): {e}")

    # -------------------------------------------------------------------------
    # 5. RUN COMPASS BACKTEST WITH STOOQ DATA
    # -------------------------------------------------------------------------
    print("\n--- STEP 5: Run COMPASS backtest with Stooq data ---")

    print("\nComputing annual top-40 (Stooq)...")
    stooq_annual = compute_annual_top40(stooq_data)

    cash_yield = download_cash_yield()

    print("\nRunning COMPASS backtest (Stooq)...")
    stooq_results = run_backtest(stooq_data, stooq_annual, stooq_spy, cash_yield, label="STOOQ")
    stooq_metrics = calculate_metrics(stooq_results)

    # -------------------------------------------------------------------------
    # 6. COMPARE RESULTS
    # -------------------------------------------------------------------------
    # Load yfinance baseline metrics
    yf_results_file = 'results_v8_compass.pkl'
    if os.path.exists(yf_results_file):
        with open(yf_results_file, 'rb') as f:
            yf_full = pickle.load(f)
        yf_metrics = yf_full.get('metrics', {})
    else:
        print("  WARNING: yfinance results file not found. Running yfinance backtest...")
        yf_annual = compute_annual_top40(yf_data)
        yf_results = run_backtest(yf_data, yf_annual, yf_spy, cash_yield, label="YFINANCE")
        yf_metrics = calculate_metrics(yf_results)

    print("\n" + "=" * 80)
    print("CROSS-VALIDATION RESULTS")
    print("=" * 80)

    print(f"\n{'Metric':<30} {'yfinance':>15} {'Stooq':>15} {'Diff':>12}")
    print("-" * 75)

    metrics_to_compare = [
        ('CAGR', 'cagr', '{:.2%}'),
        ('Sharpe', 'sharpe', '{:.3f}'),
        ('Sortino', 'sortino', '{:.3f}'),
        ('Calmar', 'calmar', '{:.3f}'),
        ('Max Drawdown', 'max_drawdown', '{:.2%}'),
        ('Volatility', 'volatility', '{:.2%}'),
        ('Win Rate', 'win_rate', '{:.2%}'),
        ('Total Trades', 'trades', '{:.0f}'),
        ('Avg P&L/Trade', 'avg_trade', '${:,.0f}'),
        ('Stop Events', 'stop_events', '{:.0f}'),
        ('Protection Days', 'protection_days', '{:.0f}'),
        ('Protection %', 'protection_pct', '{:.1f}%'),
        ('Risk-Off %', 'risk_off_pct', '{:.1f}%'),
        ('Final Value', 'final_value', '${:,.0f}'),
    ]

    for label, key, fmt in metrics_to_compare:
        yf_val = yf_metrics.get(key, 0)
        st_val = stooq_metrics.get(key, 0)

        if isinstance(yf_val, (int, float)) and isinstance(st_val, (int, float)):
            if '%' in fmt and 'pct' not in key:
                diff = st_val - yf_val
                diff_str = f"{diff:+.2%}" if abs(diff) < 1 else f"{diff:+.0f}"
            elif key == 'final_value' or key == 'avg_trade':
                diff = st_val - yf_val
                diff_str = f"${diff:+,.0f}"
            else:
                diff = st_val - yf_val
                diff_str = f"{diff:+.2f}" if abs(diff) < 100 else f"{diff:+,.0f}"

            yf_str = fmt.format(yf_val) if yf_val else 'N/A'
            st_str = fmt.format(st_val) if st_val else 'N/A'
            print(f"  {label:<28} {yf_str:>15} {st_str:>15} {diff_str:>12}")

    # -------------------------------------------------------------------------
    # 7. VERDICT
    # -------------------------------------------------------------------------
    cagr_diff = abs(stooq_metrics['cagr'] - yf_metrics.get('cagr', 0))
    sharpe_diff = abs(stooq_metrics['sharpe'] - yf_metrics.get('sharpe', 0))

    print("\n" + "=" * 80)
    print("CROSS-VALIDATION VERDICT")
    print("=" * 80)

    if cagr_diff < 0.02:  # < 2% CAGR difference
        print(f"\n  CAGR difference: {cagr_diff:.2%} --> PASS (< 2.0%)")
    elif cagr_diff < 0.05:
        print(f"\n  CAGR difference: {cagr_diff:.2%} --> MARGINAL (2-5%)")
    else:
        print(f"\n  CAGR difference: {cagr_diff:.2%} --> FAIL (> 5%)")

    if sharpe_diff < 0.10:
        print(f"  Sharpe difference: {sharpe_diff:.3f} --> PASS (< 0.10)")
    elif sharpe_diff < 0.20:
        print(f"  Sharpe difference: {sharpe_diff:.3f} --> MARGINAL (0.10-0.20)")
    else:
        print(f"  Sharpe difference: {sharpe_diff:.3f} --> FAIL (> 0.20)")

    print(f"\n  Data source agreement: Both sources must produce similar risk-adjusted returns.")
    print(f"  Small differences (<2% CAGR) are expected due to different dividend adjustment")
    print(f"  reference dates. Large differences (>5% CAGR) would indicate data quality issues.")

    # -------------------------------------------------------------------------
    # 8. SAVE RESULTS
    # -------------------------------------------------------------------------
    stooq_results['portfolio_values'].to_csv('backtests/stooq_crossval_daily.csv', index=False)
    if len(stooq_results['trades']) > 0:
        stooq_results['trades'].to_csv('backtests/stooq_crossval_trades.csv', index=False)
    comparison_df.to_csv('backtests/stooq_vs_yfinance_comparison.csv', index=False)

    elapsed = time.time() - t_start
    print(f"\n  Total time: {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Results saved: backtests/stooq_crossval_*.csv")
    print(f"  Comparison saved: backtests/stooq_vs_yfinance_comparison.csv")

    print("\n" + "=" * 80)
    print("CROSS-VALIDATION COMPLETE")
    print("=" * 80)
