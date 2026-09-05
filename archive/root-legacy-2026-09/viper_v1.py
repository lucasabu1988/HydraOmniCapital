#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║  VIPER v1.0 — Volatility-Informed Portfolio & ETF Rotation  ║
║  Orthogonal Strategy to COMPASS v8.2                        ║
║  Designed by Claude · Seed 666                              ║
╚══════════════════════════════════════════════════════════════╝

PHILOSOPHY:
  COMPASS exploits cross-sectional momentum in individual US large-caps.
  VIPER exploits INTER-ASSET momentum + inverse-volatility weighting
  across broad asset classes via ETFs. The two systems should be
  minimally correlated, improving combined Sharpe.

UNIVERSE (12 ETFs spanning 6 asset classes):
  US Equity:    SPY (S&P 500), QQQ (Nasdaq), IWM (Russell 2000)
  Intl Equity:  EFA (Developed), EEM (Emerging)
  Bonds:        TLT (Long Treasury), IEF (7-10y Treasury), LQD (Corp)
  Commodities:  GLD (Gold), DBC (Commodities)
  Real Estate:  VNQ (REITs)
  Cash Proxy:   SHY (1-3y Treasury) — safe haven

SIGNAL:
  1. Momentum score: weighted average of 1M, 3M, 6M, 12M returns
     (weights: 12M=0.35, 6M=0.25, 3M=0.25, 1M=0.15)
  2. Volatility filter: 20-day realized vol for each ETF
  3. Trend filter: price > SMA(200) → eligible; else → penalized

ALLOCATION:
  - Rank ETFs by momentum score (exclude SHY from ranking)
  - Select top-N (N=4 in risk-on, N=2 in risk-off + rest in SHY)
  - Weight by inverse volatility (risk parity lite)
  - Regime: if SPY < SMA(200), shift to defensive (bonds + gold + SHY)
  - Rebalance monthly (21 trading days)

RISK:
  - Max single position: 40%
  - Min single position: 5%
  - If all assets negative momentum → 100% SHY
  - No leverage (1.0x max)
  - No shorting
"""

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import warnings
import os
import pickle

warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════
# PARAMETERS
# ═══════════════════════════════════════════════════════════

SEED = 666
np.random.seed(SEED)

# Universe
RISK_ASSETS = ['SPY', 'QQQ', 'IWM', 'EFA', 'EEM', 'TLT', 'IEF', 'LQD', 'GLD', 'DBC', 'VNQ']
SAFE_HAVEN = 'SHY'
ALL_TICKERS = RISK_ASSETS + [SAFE_HAVEN]

# Signal weights for multi-period momentum
# Emphasize medium-term (6M) — sweet spot for asset class momentum
MOM_WEIGHTS = {252: 0.30, 126: 0.35, 63: 0.20, 21: 0.15}  # 12M, 6M, 3M, 1M

# Allocation
TOP_N_RISK_ON = 3      # Concentrate on fewer, stronger trends
TOP_N_RISK_OFF = 2     # Number of holdings in risk-off
REBALANCE_DAYS = 15    # Bi-weekly rebalance (faster than monthly)
MAX_WEIGHT = 0.50      # Allow more concentration
MIN_WEIGHT = 0.05      # Min single position weight

# Regime
REGIME_SMA = 200       # SPY SMA for regime detection
REGIME_CONFIRM = 3     # Days to confirm regime change

# Volatility
VOL_LOOKBACK = 20      # Days for realized vol calculation

# Trend filter
TREND_SMA = 200        # SMA for trend filter
TREND_PENALTY = 0.3    # Stronger penalty for below-trend assets

# Minimum ETFs available to start trading (wait for enough universe)
MIN_ETFS_AVAILABLE = 8

# Backtest
INITIAL_CAPITAL = 100_000
START_DATE = '2000-01-01'
END_DATE = '2026-02-20'
COMMISSION_BPS = 5     # 5 bps per trade (round trip ~10bps)

# Cache
CACHE_FILE = 'viper_data_cache.pkl'


def download_data():
    """Download or load cached ETF data."""
    if os.path.exists(CACHE_FILE):
        mod_time = os.path.getmtime(CACHE_FILE)
        age_hours = (datetime.now().timestamp() - mod_time) / 3600
        if age_hours < 24:
            print(f"  Loading cached data ({age_hours:.1f}h old)...")
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)

    print("  Downloading ETF data from Yahoo Finance...")
    data = {}
    for ticker in ALL_TICKERS:
        print(f"    {ticker}...", end=' ', flush=True)
        try:
            df = yf.download(ticker, start='1999-01-01', end=END_DATE,
                           auto_adjust=True, progress=False)
            if len(df) > 0:
                close = df['Close']
                # Handle multi-level columns from newer yfinance
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                # Ensure it's a proper Series with DatetimeIndex
                close = close.squeeze()
                data[ticker] = close
                print(f"{len(close)} days")
            else:
                print("NO DATA")
        except Exception as e:
            print(f"ERROR: {e}")

    prices = pd.DataFrame(data)
    prices = prices.ffill().dropna(how='all')

    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(prices, f)

    return prices


def compute_momentum(prices, date_idx, lookback_days):
    """Compute return over lookback period ending at date_idx."""
    if date_idx < lookback_days:
        return pd.Series(dtype=float)

    current = prices.iloc[date_idx]
    past = prices.iloc[date_idx - lookback_days]

    # Avoid division by zero
    valid = past > 0
    ret = pd.Series(index=prices.columns, dtype=float)
    ret[valid] = (current[valid] / past[valid]) - 1.0
    return ret


def compute_composite_momentum(prices, date_idx):
    """Compute weighted multi-period momentum score."""
    score = pd.Series(0.0, index=prices.columns)
    total_weight = 0

    for lookback, weight in MOM_WEIGHTS.items():
        if date_idx >= lookback:
            mom = compute_momentum(prices, date_idx, lookback)
            if not mom.empty:
                score += mom.fillna(-999) * weight
                total_weight += weight

    if total_weight > 0:
        score /= total_weight

    return score


def compute_volatility(prices, date_idx, lookback=VOL_LOOKBACK):
    """Compute annualized realized volatility."""
    if date_idx < lookback + 1:
        return pd.Series(0.2, index=prices.columns)  # Default 20%

    window = prices.iloc[date_idx - lookback:date_idx + 1]
    daily_ret = window.pct_change().dropna()
    vol = daily_ret.std() * np.sqrt(252)
    vol = vol.fillna(0.2).clip(lower=0.01)  # Floor at 1%, fill NaN with 20%
    return vol


def inverse_vol_weights(vol, tickers):
    """Compute inverse-volatility weights for selected tickers."""
    v = vol[tickers].fillna(0.2).clip(lower=0.01)
    inv_vol = 1.0 / v
    weights = inv_vol / inv_vol.sum()

    # Apply min/max constraints
    weights = weights.clip(lower=MIN_WEIGHT, upper=MAX_WEIGHT)
    weights = weights.fillna(0)
    s = weights.sum()
    if s > 0:
        weights /= s  # Re-normalize
    else:
        weights = pd.Series(1.0 / len(tickers), index=tickers)

    return weights


def run_backtest(prices):
    """Run the VIPER backtest."""

    dates = prices.index
    n_days = len(dates)

    # Find common start (need enough history)
    min_history = max(MOM_WEIGHTS.keys()) + 10  # 252 + 10

    # Track portfolio
    cash = INITIAL_CAPITAL
    holdings = {}  # ticker -> shares
    portfolio_values = []
    trade_log = []
    regime_log = []

    days_since_rebalance = REBALANCE_DAYS  # Force rebalance on first valid day
    current_regime = 'RISK_ON'
    regime_counter = 0

    print(f"\n{'='*60}")
    print(f"  VIPER v1.0 BACKTEST")
    print(f"  Period: {dates[min_history].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
    print(f"  Initial Capital: ${INITIAL_CAPITAL:,.0f}")
    print(f"{'='*60}\n")

    for i in range(n_days):
        date = dates[i]

        # Compute portfolio value
        port_val = cash
        for ticker, shares in holdings.items():
            if ticker in prices.columns and not pd.isna(prices[ticker].iloc[i]):
                port_val += shares * float(prices[ticker].iloc[i])

        portfolio_values.append({'date': date, 'value': float(port_val)})

        # Skip until we have enough history
        if i < min_history:
            continue

        # Skip until enough ETFs are available
        available_count = sum(1 for t in RISK_ASSETS
                            if t in prices.columns and not pd.isna(prices[t].iloc[i]))
        if available_count < MIN_ETFS_AVAILABLE:
            continue

        days_since_rebalance += 1

        # ─── REGIME DETECTION ───
        spy_price = prices['SPY'].iloc[i] if 'SPY' in prices.columns else None
        if spy_price is not None and i >= REGIME_SMA:
            spy_sma = prices['SPY'].iloc[i - REGIME_SMA + 1:i + 1].mean()

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
                        days_since_rebalance = REBALANCE_DAYS  # Force rebalance
                else:
                    regime_counter = 0

        # ─── REBALANCE CHECK ───
        if days_since_rebalance < REBALANCE_DAYS:
            continue

        days_since_rebalance = 0

        # ─── COMPUTE SIGNALS ───
        # Available tickers (must have price today)
        available = [t for t in RISK_ASSETS
                     if t in prices.columns and not pd.isna(prices[t].iloc[i])]

        if not available:
            continue

        # Composite momentum
        mom_scores = compute_composite_momentum(prices, i)

        # Trend filter: penalize assets below SMA(200)
        if i >= TREND_SMA:
            for t in available:
                sma = prices[t].iloc[i - TREND_SMA + 1:i + 1].mean()
                if prices[t].iloc[i] < sma:
                    mom_scores[t] *= TREND_PENALTY

        # Volatility
        vol = compute_volatility(prices, i)

        # ─── SELECT ASSETS ───
        top_n = TOP_N_RISK_ON if current_regime == 'RISK_ON' else TOP_N_RISK_OFF

        # Filter to available and rank
        ranked = mom_scores[available].sort_values(ascending=False)

        # Only select assets with positive momentum
        positive = ranked[ranked > 0]
        selected = list(positive.head(top_n).index)

        # ─── COMPUTE WEIGHTS ───
        if len(selected) == 0:
            # All negative momentum → 100% safe haven
            target_weights = {SAFE_HAVEN: 1.0}
        else:
            weights = inverse_vol_weights(vol, selected)
            target_weights = weights.to_dict()

            if current_regime == 'RISK_OFF':
                # Risk-off: min 40% in SHY
                total_risk = sum(target_weights.values())
                shy_weight = max(0.40, 1.0 - total_risk)
                scale = (1.0 - shy_weight) / total_risk if total_risk > 0 else 0
                target_weights = {k: v * scale for k, v in target_weights.items()}
                target_weights[SAFE_HAVEN] = shy_weight
            elif len(selected) < top_n:
                # Risk-on but fewer good assets: put remainder in SHY
                shy_alloc = (top_n - len(selected)) / top_n * 0.5
                if shy_alloc > 0.05:
                    scale = 1.0 - shy_alloc
                    target_weights = {k: v * scale for k, v in target_weights.items()}
                    target_weights[SAFE_HAVEN] = shy_alloc

        # ─── EXECUTE TRADES ───
        # First, compute current portfolio value
        port_val = cash
        for ticker, shares in holdings.items():
            if ticker in prices.columns and not pd.isna(prices[ticker].iloc[i]):
                port_val += shares * float(prices[ticker].iloc[i])

        # Sell everything first
        for ticker, shares in list(holdings.items()):
            if shares > 0 and ticker in prices.columns and not pd.isna(prices[ticker].iloc[i]):
                sell_price = float(prices[ticker].iloc[i])
                proceeds = shares * sell_price
                commission = proceeds * COMMISSION_BPS / 10000
                cash += proceeds - commission
                trade_log.append({
                    'date': date, 'ticker': ticker, 'action': 'SELL',
                    'shares': shares, 'price': sell_price, 'commission': commission
                })
        holdings = {}

        # Buy target positions
        for ticker, weight in target_weights.items():
            if ticker not in prices.columns or pd.isna(prices[ticker].iloc[i]):
                continue
            buy_price = prices[ticker].iloc[i]
            if pd.isna(buy_price) or buy_price <= 0:
                continue

            target_value = port_val * weight
            if pd.isna(target_value) or pd.isna(buy_price) or float(buy_price) == 0:
                continue
            shares = int(float(target_value) / float(buy_price))
            if shares <= 0:
                continue

            cost = shares * buy_price
            commission = cost * COMMISSION_BPS / 10000

            if cost + commission <= cash:
                cash -= cost + commission
                holdings[ticker] = shares
                trade_log.append({
                    'date': date, 'ticker': ticker, 'action': 'BUY',
                    'shares': shares, 'price': buy_price, 'commission': commission
                })

        regime_log.append({
            'date': date, 'regime': current_regime,
            'holdings': list(target_weights.keys()),
            'weights': target_weights
        })

    return pd.DataFrame(portfolio_values), pd.DataFrame(trade_log), regime_log


def analyze_results(portfolio_df, trade_df, regime_log, prices):
    """Compute and display backtest statistics."""

    df = portfolio_df.set_index('date')
    df = df[df['value'] > 0]

    # Daily returns
    df['return'] = df['value'].pct_change()
    df = df.dropna()

    # Key metrics
    total_days = len(df)
    years = total_days / 252

    final_val = df['value'].iloc[-1]
    total_return = (final_val / INITIAL_CAPITAL) - 1
    cagr = (final_val / INITIAL_CAPITAL) ** (1 / years) - 1

    # Volatility & Sharpe
    annual_vol = df['return'].std() * np.sqrt(252)
    risk_free = 0.02  # 2% risk-free
    sharpe = (cagr - risk_free) / annual_vol if annual_vol > 0 else 0

    # Drawdown
    cummax = df['value'].cummax()
    drawdown = (df['value'] / cummax) - 1
    max_dd = drawdown.min()
    max_dd_date = drawdown.idxmin()

    # Find peak before max drawdown
    peak_date = df['value'][:max_dd_date].idxmax()

    # Recovery: find first date after trough where value >= peak value
    peak_val = df['value'][peak_date]
    trough_onwards = df['value'][max_dd_date:]
    recovery_dates = trough_onwards[trough_onwards >= peak_val]
    recovery_date = recovery_dates.index[0] if len(recovery_dates) > 0 else None

    # Win rate (monthly)
    monthly = df['value'].resample('ME').last()
    monthly_ret = monthly.pct_change().dropna()
    win_rate = (monthly_ret > 0).mean()

    # Best/worst year
    yearly = df['value'].resample('YE').last()
    yearly_ret = yearly.pct_change().dropna()
    best_year = yearly_ret.max()
    worst_year = yearly_ret.min()
    best_year_date = yearly_ret.idxmax().year
    worst_year_date = yearly_ret.idxmin().year

    # Trade stats
    total_trades = len(trade_df) if len(trade_df) > 0 else 0
    total_commission = trade_df['commission'].sum() if total_trades > 0 else 0

    # Calmar ratio
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    # Sortino
    downside = df['return'][df['return'] < 0].std() * np.sqrt(252)
    sortino = (cagr - risk_free) / downside if downside > 0 else 0

    print(f"\n{'═'*60}")
    print(f"  VIPER v1.0 — BACKTEST RESULTS")
    print(f"{'═'*60}")
    print(f"  Period:          {df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Trading Days:    {total_days:,}")
    print(f"  Years:           {years:.1f}")
    print(f"")
    print(f"  ── RETURNS ──")
    print(f"  Initial:         ${INITIAL_CAPITAL:>12,.0f}")
    print(f"  Final:           ${final_val:>12,.0f}")
    print(f"  Total Return:    {total_return:>11.1%}")
    print(f"  CAGR:            {cagr:>11.2%}")
    print(f"")
    print(f"  ── RISK ──")
    print(f"  Annual Vol:      {annual_vol:>11.2%}")
    print(f"  Max Drawdown:    {max_dd:>11.2%}")
    print(f"  DD Peak:         {peak_date.strftime('%Y-%m-%d')}")
    print(f"  DD Trough:       {max_dd_date.strftime('%Y-%m-%d')}")
    if recovery_date:
        print(f"  DD Recovery:     {recovery_date.strftime('%Y-%m-%d')}")
    else:
        print(f"  DD Recovery:     NOT YET")
    print(f"")
    print(f"  ── RATIOS ──")
    print(f"  Sharpe:          {sharpe:>11.2f}")
    print(f"  Sortino:         {sortino:>11.2f}")
    print(f"  Calmar:          {calmar:>11.2f}")
    print(f"")
    print(f"  ── TRADING ──")
    print(f"  Total Trades:    {total_trades:>8,}")
    print(f"  Total Commission:${total_commission:>11,.0f}")
    print(f"  Monthly Win Rate:{win_rate:>10.1%}")
    print(f"")
    print(f"  ── YEARLY ──")
    print(f"  Best Year:       {best_year:>11.1%} ({best_year_date})")
    print(f"  Worst Year:      {worst_year:>11.1%} ({worst_year_date})")
    print(f"")

    # Print yearly breakdown
    print(f"  ── ANNUAL RETURNS ──")
    for idx, ret in yearly_ret.items():
        yr = idx.year
        bar_len = int(abs(ret) * 100)
        bar = '█' * min(bar_len, 40)
        color_marker = '+' if ret > 0 else '-'
        print(f"  {yr}  {color_marker}{abs(ret):>6.1%}  {bar}")

    # Regime breakdown
    if regime_log:
        risk_on_count = sum(1 for r in regime_log if r['regime'] == 'RISK_ON')
        risk_off_count = sum(1 for r in regime_log if r['regime'] == 'RISK_OFF')
        print(f"\n  ── REGIME ──")
        print(f"  Risk-On periods:  {risk_on_count}")
        print(f"  Risk-Off periods: {risk_off_count}")

    # Most held ETFs
    if regime_log:
        from collections import Counter
        all_holdings = []
        for r in regime_log:
            all_holdings.extend(r['holdings'])
        counter = Counter(all_holdings)
        print(f"\n  ── TOP HOLDINGS (frequency) ──")
        for ticker, count in counter.most_common(8):
            pct = count / len(regime_log) * 100
            print(f"  {ticker:<6} {count:>4}x  ({pct:.0f}%)")

    print(f"\n{'═'*60}")

    # Return metrics dict for comparison
    return {
        'cagr': cagr,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_dd': max_dd,
        'annual_vol': annual_vol,
        'final_value': final_val,
        'total_return': total_return,
        'win_rate': win_rate,
        'portfolio_df': df
    }


def compare_with_compass(viper_df):
    """Load COMPASS backtest and compute correlation."""

    # Check if COMPASS equity data exists
    compass_files = [
        'state/backtest_equity.pkl',
        'backtest_equity.pkl',
    ]

    compass_df = None
    for f in compass_files:
        if os.path.exists(f):
            try:
                compass_df = pd.read_pickle(f)
                print(f"\n  Loaded COMPASS data from {f}")
                break
            except:
                pass

    if compass_df is None:
        print("\n  [COMPASS equity data not found — skipping correlation analysis]")
        return

    # Align dates
    viper_returns = viper_df['return']

    if isinstance(compass_df, pd.DataFrame):
        if 'value' in compass_df.columns:
            compass_returns = compass_df['value'].pct_change().dropna()
        elif 'portfolio_value' in compass_df.columns:
            compass_returns = compass_df['portfolio_value'].pct_change().dropna()
        else:
            compass_returns = compass_df.iloc[:, 0].pct_change().dropna()
    elif isinstance(compass_df, pd.Series):
        compass_returns = compass_df.pct_change().dropna()
    else:
        print("  [Cannot parse COMPASS data format]")
        return

    # Find common dates
    common_dates = viper_returns.index.intersection(compass_returns.index)

    if len(common_dates) < 100:
        print(f"  [Only {len(common_dates)} common dates — insufficient for correlation]")
        return

    v = viper_returns[common_dates]
    c = compass_returns[common_dates]

    correlation = v.corr(c)

    print(f"\n{'═'*60}")
    print(f"  VIPER × COMPASS CORRELATION ANALYSIS")
    print(f"{'═'*60}")
    print(f"  Common trading days: {len(common_dates):,}")
    print(f"  Daily return correlation: {correlation:.3f}")

    if abs(correlation) < 0.3:
        print(f"  ✓ LOW correlation — excellent diversification potential!")
    elif abs(correlation) < 0.5:
        print(f"  ~ MODERATE correlation — some diversification benefit")
    else:
        print(f"  ✗ HIGH correlation — limited diversification benefit")

    # Compute combined portfolio (50/50)
    combined = 0.5 * v + 0.5 * c
    combined_vol = combined.std() * np.sqrt(252)
    viper_vol = v.std() * np.sqrt(252)
    compass_vol = c.std() * np.sqrt(252)

    print(f"\n  ── 50/50 COMBINED PORTFOLIO ──")
    print(f"  VIPER vol:    {viper_vol:.2%}")
    print(f"  COMPASS vol:  {compass_vol:.2%}")
    print(f"  Combined vol: {combined_vol:.2%}")
    print(f"  Vol reduction: {(1 - combined_vol / ((viper_vol + compass_vol)/2)):.1%}")
    print(f"{'═'*60}")


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  VIPER v1.0 — Volatility-Informed Portfolio & ETF Rot.  ║")
    print("║  Orthogonal to COMPASS v8.2                             ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # 1. Download data
    print("STEP 1: Loading price data...")
    prices = download_data()
    print(f"  Loaded {len(prices)} trading days, {len(prices.columns)} ETFs")
    print(f"  Date range: {prices.index[0].strftime('%Y-%m-%d')} → {prices.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Available: {', '.join(prices.columns.tolist())}")

    # Show ETF availability
    print("\n  ETF availability:")
    for col in prices.columns:
        first_valid = prices[col].first_valid_index()
        print(f"    {col:<5} from {first_valid.strftime('%Y-%m-%d')}")

    # 2. Run backtest
    print("\nSTEP 2: Running backtest...")
    portfolio_df, trade_df, regime_log = run_backtest(prices)

    # 3. Analyze
    print("\nSTEP 3: Analyzing results...")
    metrics = analyze_results(portfolio_df, trade_df, regime_log, prices)

    # 4. Compare with COMPASS
    print("\nSTEP 4: Correlation with COMPASS...")
    compare_with_compass(metrics['portfolio_df'])

    print("\n  Done. 🐍")
