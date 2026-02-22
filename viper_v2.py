#!/usr/bin/env python3
"""
VIPER v2.0 - Sector Momentum Rotation (Aggressive)
===================================================
Philosophy: If COMPASS finds alpha in top-5 individual stocks,
VIPER v2 hunts alpha in top-3 SECTORS with the same momentum logic.

Universe: 11 Select Sector SPDRs + QQQ + 3 leveraged alternatives
Signal: 90-day momentum (same as COMPASS) + trend filter
Hold: Bi-weekly rebalance
Risk: SPY regime filter + concentrated positions (3 max)

This is closer to COMPASS's DNA but on sectors, not stocks.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import warnings
import os
import pickle

warnings.filterwarnings('ignore')

SEED = 666
np.random.seed(SEED)

# Sector ETFs (Select Sector SPDRs — inception ~1998)
SECTORS = [
    'XLK',  # Technology
    'XLF',  # Financials
    'XLV',  # Healthcare
    'XLE',  # Energy
    'XLY',  # Consumer Discretionary
    'XLP',  # Consumer Staples
    'XLI',  # Industrials
    'XLB',  # Materials
    'XLU',  # Utilities
    'XLRE', # Real Estate (from 2015)
    'XLC',  # Communications (from 2018)
    'QQQ',  # Nasdaq-100 (tech-heavy proxy)
    'SMH',  # Semiconductors (VanEck)
    'XBI',  # Biotech
    'IYT',  # Transportation
]

SAFE_HAVEN = 'SHY'
ALL_TICKERS = SECTORS + [SAFE_HAVEN, 'SPY']

# Signal: match COMPASS's 90-day lookback
MOM_LOOKBACK = 90       # Primary signal — same as COMPASS
MOM_SKIP = 5            # Skip last 5 days (mean-reversion noise)
SECONDARY_MOM = 21      # 1-month secondary signal for confirmation

# Allocation
TOP_N = 3               # Concentrated: top 3 sectors
REBALANCE_DAYS = 10     # Rebalance every 2 weeks
MAX_WEIGHT = 0.50
MIN_WEIGHT = 0.10

# Regime
REGIME_SMA = 200
REGIME_CONFIRM = 3

# Trend filter
TREND_SMA = 200
TREND_PENALTY = 0.0     # Zero = exclude below-trend assets entirely

# Risk
VOL_LOOKBACK = 20
VOL_TARGET = 0.15       # 15% vol target — same as COMPASS
MIN_LEVERAGE = 0.3
MAX_LEVERAGE = 1.5      # Allow modest leverage

INITIAL_CAPITAL = 100_000
COMMISSION_BPS = 5
CACHE_FILE = 'viper_v2_cache.pkl'
MIN_SECTORS = 6


def download_data():
    if os.path.exists(CACHE_FILE):
        mod_time = os.path.getmtime(CACHE_FILE)
        if (datetime.now().timestamp() - mod_time) / 3600 < 24:
            print("  Loading cached data...")
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)

    print("  Downloading sector ETF data...")
    data = {}
    for ticker in ALL_TICKERS:
        print(f"    {ticker}...", end=' ', flush=True)
        try:
            df = yf.download(ticker, start='1998-01-01', end='2026-02-21',
                           auto_adjust=True, progress=False)
            if len(df) > 0:
                close = df['Close']
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                close = close.squeeze()
                data[ticker] = close
                print(f"{len(close)} days")
            else:
                print("NO DATA")
        except Exception as e:
            print(f"ERROR: {e}")

    prices = pd.DataFrame(data).ffill().dropna(how='all')
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(prices, f)
    return prices


def run_backtest(prices):
    dates = prices.index
    n_days = len(dates)
    min_history = MOM_LOOKBACK + MOM_SKIP + 50

    cash = float(INITIAL_CAPITAL)
    holdings = {}
    portfolio_values = []
    trade_log = []
    regime_log = []

    days_since_rebalance = REBALANCE_DAYS
    current_regime = 'RISK_ON'
    regime_counter = 0
    prev_leverage = 1.0

    print(f"\n  Running backtest from day {min_history}...")

    for i in range(n_days):
        date = dates[i]

        # Portfolio value
        port_val = cash
        for t, sh in holdings.items():
            if t in prices.columns and not pd.isna(prices[t].iloc[i]):
                port_val += sh * float(prices[t].iloc[i])
        portfolio_values.append({'date': date, 'value': float(port_val)})

        if i < min_history:
            continue

        # Check enough sectors available
        avail_sectors = [t for t in SECTORS
                        if t in prices.columns
                        and not pd.isna(prices[t].iloc[i])
                        and i >= MOM_LOOKBACK + MOM_SKIP]
        if len(avail_sectors) < MIN_SECTORS:
            continue

        days_since_rebalance += 1

        # ── REGIME ──
        if 'SPY' in prices.columns and not pd.isna(prices['SPY'].iloc[i]) and i >= REGIME_SMA:
            spy_price = float(prices['SPY'].iloc[i])
            spy_sma = float(prices['SPY'].iloc[i - REGIME_SMA + 1:i + 1].mean())

            if spy_price > spy_sma:
                if current_regime == 'RISK_OFF':
                    regime_counter += 1
                    if regime_counter >= REGIME_CONFIRM:
                        current_regime = 'RISK_ON'
                        regime_counter = 0
                else:
                    regime_counter = 0
            else:
                if current_regime == 'RISK_ON':
                    regime_counter += 1
                    if regime_counter >= REGIME_CONFIRM:
                        current_regime = 'RISK_OFF'
                        regime_counter = 0
                        days_since_rebalance = REBALANCE_DAYS
                else:
                    regime_counter = 0

        if days_since_rebalance < REBALANCE_DAYS:
            continue
        days_since_rebalance = 0

        # ── MOMENTUM SIGNAL ──
        mom_scores = {}
        for t in avail_sectors:
            # 90-day return with 5-day skip (same as COMPASS)
            idx_end = i - MOM_SKIP
            idx_start = idx_end - MOM_LOOKBACK
            if idx_start < 0 or idx_end < 0:
                continue

            p_now = float(prices[t].iloc[idx_end])
            p_past = float(prices[t].iloc[idx_start])

            if pd.isna(p_now) or pd.isna(p_past) or p_past <= 0:
                continue

            primary_mom = (p_now / p_past) - 1.0

            # Secondary: 21-day confirmation
            idx_sec = i - MOM_SKIP - SECONDARY_MOM
            if idx_sec >= 0 and not pd.isna(prices[t].iloc[idx_sec]):
                p_sec = float(prices[t].iloc[idx_sec])
                if p_sec > 0:
                    sec_mom = (p_now / p_sec) - 1.0
                else:
                    sec_mom = 0
            else:
                sec_mom = 0

            # Composite: 70% primary + 30% secondary
            score = 0.7 * primary_mom + 0.3 * sec_mom

            # Trend filter: price above SMA(200)?
            if i >= TREND_SMA:
                sma_val = float(prices[t].iloc[i - TREND_SMA + 1:i + 1].mean())
                current_price = float(prices[t].iloc[i])
                if current_price < sma_val:
                    if TREND_PENALTY == 0:
                        continue  # Exclude entirely
                    else:
                        score *= TREND_PENALTY

            mom_scores[t] = score

        if not mom_scores:
            continue

        # ── SELECT & RANK ──
        ranked = sorted(mom_scores.items(), key=lambda x: x[1], reverse=True)

        if current_regime == 'RISK_ON':
            # Top N with positive momentum
            selected = [(t, s) for t, s in ranked if s > 0][:TOP_N]
        else:
            # Risk-off: only top 1, rest in SHY
            selected = [(t, s) for t, s in ranked if s > 0][:1]

        # ── VOLATILITY TARGETING ──
        # Compute portfolio vol estimate
        if selected:
            sel_tickers = [t for t, s in selected]
            window = prices[sel_tickers].iloc[max(0, i - VOL_LOOKBACK):i + 1]
            port_daily_vol = window.pct_change().dropna().mean(axis=1).std()
            port_annual_vol = port_daily_vol * np.sqrt(252) if not pd.isna(port_daily_vol) and port_daily_vol > 0 else 0.15

            leverage = VOL_TARGET / port_annual_vol
            leverage = np.clip(leverage, MIN_LEVERAGE, MAX_LEVERAGE)
            # Smooth leverage changes
            leverage = 0.7 * leverage + 0.3 * prev_leverage
            prev_leverage = leverage
        else:
            leverage = MIN_LEVERAGE

        # ── COMPUTE WEIGHTS ──
        if not selected:
            target_weights = {SAFE_HAVEN: 1.0}
        else:
            # Inverse-vol weighting
            vols = {}
            for t, _ in selected:
                w = prices[t].iloc[max(0, i - VOL_LOOKBACK):i + 1]
                v = w.pct_change().dropna().std() * np.sqrt(252)
                vols[t] = float(v) if not pd.isna(v) and v > 0 else 0.2

            inv_vols = {t: 1.0 / v for t, v in vols.items()}
            total_inv = sum(inv_vols.values())
            raw_weights = {t: iv / total_inv for t, iv in inv_vols.items()}

            # Apply leverage
            target_weights = {t: w * leverage for t, w in raw_weights.items()}

            # Clip individual weights
            for t in target_weights:
                target_weights[t] = np.clip(target_weights[t], MIN_WEIGHT, MAX_WEIGHT)

            total_alloc = sum(target_weights.values())
            if total_alloc < 1.0:
                # Put remainder in SHY
                target_weights[SAFE_HAVEN] = 1.0 - total_alloc

            # If over-allocated (leverage > 1), normalize
            if total_alloc > 1.0:
                # Cap at total_alloc (allow leverage up to MAX_LEVERAGE)
                pass  # Keep as-is, will be handled by cash constraint

        # ── EXECUTE ──
        # Sell all
        for t, sh in list(holdings.items()):
            if sh > 0 and t in prices.columns and not pd.isna(prices[t].iloc[i]):
                p = float(prices[t].iloc[i])
                proceeds = sh * p
                comm = proceeds * COMMISSION_BPS / 10000
                cash += proceeds - comm
                trade_log.append({'date': date, 'ticker': t, 'action': 'SELL',
                                 'shares': sh, 'price': p})
        holdings = {}

        # Buy
        for t, w in target_weights.items():
            if t not in prices.columns or pd.isna(prices[t].iloc[i]):
                continue
            p = float(prices[t].iloc[i])
            if p <= 0 or pd.isna(p):
                continue

            target_val = port_val * w
            shares = int(target_val / p)
            if shares <= 0:
                continue
            cost = shares * p
            comm = cost * COMMISSION_BPS / 10000
            if cost + comm <= cash:
                cash -= cost + comm
                holdings[t] = shares
                trade_log.append({'date': date, 'ticker': t, 'action': 'BUY',
                                 'shares': shares, 'price': p})

        regime_log.append({'date': date, 'regime': current_regime,
                          'leverage': leverage,
                          'holdings': list(target_weights.keys())})

    return pd.DataFrame(portfolio_values), pd.DataFrame(trade_log), regime_log


def analyze(portfolio_df, trade_df, regime_log):
    df = portfolio_df.set_index('date')
    df = df[df['value'] > 0]
    df['return'] = df['value'].pct_change().dropna()
    df = df.dropna()

    total_days = len(df)
    years = total_days / 252
    final_val = df['value'].iloc[-1]
    cagr = (final_val / INITIAL_CAPITAL) ** (1 / years) - 1
    annual_vol = df['return'].std() * np.sqrt(252)
    sharpe = (cagr - 0.02) / annual_vol if annual_vol > 0 else 0

    cummax = df['value'].cummax()
    dd = (df['value'] / cummax) - 1
    max_dd = dd.min()

    downside = df['return'][df['return'] < 0].std() * np.sqrt(252)
    sortino = (cagr - 0.02) / downside if downside > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    monthly = df['value'].resample('ME').last()
    monthly_ret = monthly.pct_change().dropna()
    win_rate = (monthly_ret > 0).mean()

    yearly = df['value'].resample('YE').last()
    yearly_ret = yearly.pct_change().dropna()

    total_trades = len(trade_df) if len(trade_df) > 0 else 0

    print(f"\n{'='*60}")
    print(f"  VIPER v2.0 SECTOR MOMENTUM — RESULTS")
    print(f"{'='*60}")
    print(f"  Period:       {df.index[0].strftime('%Y-%m-%d')} -> {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Years:        {years:.1f}")
    print(f"")
    print(f"  Initial:      ${INITIAL_CAPITAL:>12,.0f}")
    print(f"  Final:        ${final_val:>12,.0f}")
    print(f"  CAGR:         {cagr:>11.2%}")
    print(f"  Sharpe:       {sharpe:>11.2f}")
    print(f"  Sortino:      {sortino:>11.2f}")
    print(f"  Calmar:       {calmar:>11.2f}")
    print(f"  Max DD:       {max_dd:>11.2%}")
    print(f"  Annual Vol:   {annual_vol:>11.2%}")
    print(f"  Win Rate:     {win_rate:>10.1%}")
    print(f"  Trades:       {total_trades:>8,}")
    print(f"")

    # Comparison with COMPASS
    print(f"  {'METRIC':<18} {'VIPER v2':>10} {'COMPASS':>10} {'WINNER':>10}")
    print(f"  {'-'*48}")
    compass_cagr, compass_sharpe, compass_dd = 0.1695, 0.81, -0.284
    v = lambda a, b: 'VIPER' if a > b else ('TIE' if a == b else 'COMPASS')
    vd = lambda a, b: 'VIPER' if abs(a) < abs(b) else 'COMPASS'
    print(f"  {'CAGR':<18} {cagr:>9.2%} {compass_cagr:>9.2%} {v(cagr, compass_cagr):>10}")
    print(f"  {'Sharpe':<18} {sharpe:>10.2f} {compass_sharpe:>10.2f} {v(sharpe, compass_sharpe):>10}")
    print(f"  {'Max Drawdown':<18} {max_dd:>9.2%} {compass_dd:>9.2%} {vd(max_dd, compass_dd):>10}")
    print(f"  {'Volatility':<18} {annual_vol:>9.2%} {'~18%':>10}")

    print(f"\n  -- ANNUAL RETURNS --")
    for idx, ret in yearly_ret.items():
        yr = idx.year
        bar = '+' * min(int(abs(ret) * 100), 40) if ret > 0 else '-' * min(int(abs(ret) * 100), 40)
        sign = '+' if ret > 0 else '-'
        print(f"  {yr}  {sign}{abs(ret):>6.1%}  {bar}")

    # Top holdings
    if regime_log:
        from collections import Counter
        all_h = []
        for r in regime_log:
            all_h.extend(r['holdings'])
        counter = Counter(all_h)
        print(f"\n  -- TOP SECTORS --")
        for t, c in counter.most_common(8):
            print(f"  {t:<6} {c:>4}x ({c/len(regime_log)*100:.0f}%)")

    print(f"\n{'='*60}")
    return {'cagr': cagr, 'sharpe': sharpe, 'max_dd': max_dd, 'final_value': final_val}


if __name__ == '__main__':
    print("VIPER v2.0 - Sector Momentum Rotation")
    print("=" * 40)

    print("\nStep 1: Data...")
    prices = download_data()
    print(f"  {len(prices)} days, {len(prices.columns)} tickers")

    print("\nStep 2: Backtest...")
    port_df, trade_df, regime_log = run_backtest(prices)

    print("\nStep 3: Analysis...")
    metrics = analyze(port_df, trade_df, regime_log)
