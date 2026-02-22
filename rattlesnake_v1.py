#!/usr/bin/env python3
"""
RATTLESNAKE v1.0
================
Reversion After Temporary Turbulence, Leveraging Extreme
Statistical Negativity And Kontrarean Entries

PHILOSOPHY:
  COMPASS buys winners (momentum). RATTLESNAKE buys LOSERS (mean-reversion).
  These are philosophically opposite strategies = low correlation.

  Academic basis: Jegadeesh (1990), Lehmann (1990), Lo & MacKinlay (1990)
  showed short-term (1-5 day) mean-reversion is one of the strongest
  anomalies in equity markets. Stocks that crash hard over 3-5 days
  tend to bounce 60-70% of the time.

SIGNAL:
  1. Screen S&P 100 (OEX) stocks — liquid, no penny stock risk
  2. Find stocks that dropped > X% in the last 5 trading days
  3. Require: RSI(5) < 20 (deeply oversold)
  4. Require: stock is ABOVE its 200-day SMA (uptrend — buying dips, not knives)
  5. Require: stock is in the top 70% by 20-day average volume (liquidity)

ENTRY:
  - Buy at close on signal day
  - Equal-weight across all qualifying stocks (max 5 positions)

EXIT:
  - Sell after stock rebounds X% from entry (profit target)
  - OR sell after N days max hold (time stop)
  - OR sell if drops another Y% (stop loss)

REGIME:
  - VIX-based: if VIX > 35, go to cash (panic selling, not dip-buying)
  - SPY SMA(200): if SPY < SMA, reduce position count to 2

RISK:
  - Max 5 positions, equal weight
  - Hard stop loss per position
  - No leverage
  - Cash earns 3% annual (T-bill proxy like COMPASS)
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

# ================================================================
# UNIVERSE: S&P 100 (OEX) — most liquid large-caps
# Using a fixed list of historically large, liquid stocks
# ================================================================
UNIVERSE = [
    'AAPL', 'ABBV', 'ABT', 'ACN', 'ADBE', 'AIG', 'AMGN', 'AMT', 'AMZN', 'AVGO',
    'AXP', 'BA', 'BAC', 'BK', 'BKNG', 'BLK', 'BMY', 'BRK-B', 'C', 'CAT',
    'CHTR', 'CL', 'CMCSA', 'COF', 'COP', 'COST', 'CRM', 'CSCO', 'CVS', 'CVX',
    'DE', 'DHR', 'DIS', 'DOW', 'DUK', 'EMR', 'EXC', 'F', 'FDX', 'GD',
    'GE', 'GILD', 'GM', 'GOOG', 'GS', 'HD', 'HON', 'IBM', 'INTC', 'INTU',
    'JNJ', 'JPM', 'KHC', 'KO', 'LIN', 'LLY', 'LMT', 'LOW', 'MA', 'MCD',
    'MDLZ', 'MDT', 'MET', 'META', 'MMM', 'MO', 'MRK', 'MS', 'MSFT', 'NEE',
    'NFLX', 'NKE', 'NVDA', 'ORCL', 'PEP', 'PFE', 'PG', 'PM', 'PYPL', 'QCOM',
    'RTX', 'SBUX', 'SCHW', 'SO', 'SPG', 'T', 'TGT', 'TMO', 'TMUS', 'TSLA',
    'TXN', 'UNH', 'UNP', 'UPS', 'USB', 'V', 'VZ', 'WBA', 'WFC', 'WMT', 'XOM',
]

# ================================================================
# PARAMETERS
# ================================================================

# Entry signal
DROP_THRESHOLD = -0.08      # Stock must have dropped >= 8% in lookback window
DROP_LOOKBACK = 5           # Days to measure the drop
RSI_PERIOD = 5              # Short RSI for oversold detection
RSI_THRESHOLD = 25          # RSI must be below this (oversold)
TREND_SMA = 200             # Must be above 200-day SMA (buying dips in uptrends)

# Exit rules
PROFIT_TARGET = 0.04        # Take profit at +4% from entry
MAX_HOLD_DAYS = 8           # Maximum hold period
STOP_LOSS = -0.05           # Stop loss at -5% from entry

# Portfolio
MAX_POSITIONS = 5           # Maximum simultaneous positions
POSITION_SIZE = 0.20        # 20% per position (equal weight, 5 max)

# Regime
REGIME_SMA = 200            # SPY regime filter
REGIME_CONFIRM = 3
MAX_POS_RISK_OFF = 2        # Fewer positions in risk-off
VIX_PANIC = 35              # VIX above this = don't buy (panic mode)

# Cash yield
CASH_YIELD_RATE = 0.03      # 3% annual on cash (same as COMPASS)

# Backtest
INITIAL_CAPITAL = 100_000
COMMISSION_BPS = 5
CACHE_FILE = 'rattlesnake_cache.pkl'


def compute_rsi(prices_series, period=5):
    """Compute RSI for a price series."""
    delta = prices_series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def download_data():
    if os.path.exists(CACHE_FILE):
        mod_time = os.path.getmtime(CACHE_FILE)
        if (datetime.now().timestamp() - mod_time) / 3600 < 24:
            print("  Loading cached data...")
            with open(CACHE_FILE, 'rb') as f:
                return pickle.load(f)

    all_tickers = UNIVERSE + ['SPY', '^VIX']
    print(f"  Downloading {len(all_tickers)} tickers...")

    data = {}
    volume_data = {}
    for ticker in all_tickers:
        try:
            df = yf.download(ticker, start='1999-01-01', end='2026-02-21',
                           auto_adjust=True, progress=False)
            if len(df) > 0:
                close = df['Close']
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                data[ticker] = close.squeeze()

                if 'Volume' in df.columns:
                    vol = df['Volume']
                    if isinstance(vol, pd.DataFrame):
                        vol = vol.iloc[:, 0]
                    volume_data[ticker] = vol.squeeze()
        except:
            pass

    print(f"  Downloaded {len(data)} tickers successfully")

    prices = pd.DataFrame(data).ffill()
    volumes = pd.DataFrame(volume_data).ffill()

    result = {'prices': prices, 'volumes': volumes}
    with open(CACHE_FILE, 'wb') as f:
        pickle.dump(result, f)
    return result


def run_backtest(data):
    prices = data['prices']
    volumes = data['volumes']

    dates = prices.index
    n_days = len(dates)
    min_history = max(TREND_SMA, DROP_LOOKBACK + RSI_PERIOD) + 50

    cash = float(INITIAL_CAPITAL)
    # positions: list of {ticker, entry_price, entry_date_idx, shares}
    positions = []
    portfolio_values = []
    trade_log = []

    current_regime = 'RISK_ON'
    regime_counter = 0
    total_entries = 0
    total_exits_profit = 0
    total_exits_stop = 0
    total_exits_time = 0

    print(f"  Backtest: {dates[min_history].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
    print(f"  Initial capital: ${INITIAL_CAPITAL:,.0f}")

    # Pre-compute RSI for all stocks
    print("  Pre-computing RSI...")
    rsi_data = {}
    for ticker in UNIVERSE:
        if ticker in prices.columns:
            rsi_data[ticker] = compute_rsi(prices[ticker], RSI_PERIOD)

    print("  Running simulation...")

    for i in range(n_days):
        date = dates[i]

        # ── COMPUTE PORTFOLIO VALUE ──
        port_val = cash
        for pos in positions:
            t = pos['ticker']
            if t in prices.columns and not pd.isna(prices[t].iloc[i]):
                port_val += pos['shares'] * float(prices[t].iloc[i])
        portfolio_values.append({'date': date, 'value': float(port_val)})

        if i < min_history:
            continue

        # ── CASH YIELD (daily accrual) ──
        if cash > 0:
            daily_yield = cash * CASH_YIELD_RATE / 252
            cash += daily_yield

        # ── REGIME DETECTION ──
        if 'SPY' in prices.columns and not pd.isna(prices['SPY'].iloc[i]) and i >= REGIME_SMA:
            spy_price = float(prices['SPY'].iloc[i])
            spy_sma = float(prices['SPY'].iloc[i - REGIME_SMA + 1:i + 1].mean())

            if spy_price > spy_sma:
                if current_regime != 'RISK_ON':
                    regime_counter += 1
                    if regime_counter >= REGIME_CONFIRM:
                        current_regime = 'RISK_ON'
                        regime_counter = 0
                else:
                    regime_counter = 0
            else:
                if current_regime != 'RISK_OFF':
                    regime_counter += 1
                    if regime_counter >= REGIME_CONFIRM:
                        current_regime = 'RISK_OFF'
                        regime_counter = 0
                else:
                    regime_counter = 0

        # ── VIX CHECK ──
        vix_panic = False
        if '^VIX' in prices.columns and not pd.isna(prices['^VIX'].iloc[i]):
            vix = float(prices['^VIX'].iloc[i])
            if vix > VIX_PANIC:
                vix_panic = True

        # ── CHECK EXITS ON EXISTING POSITIONS ──
        for pos in list(positions):
            t = pos['ticker']
            if t not in prices.columns or pd.isna(prices[t].iloc[i]):
                continue

            current_price = float(prices[t].iloc[i])
            entry_price = pos['entry_price']
            pnl_pct = (current_price / entry_price) - 1.0
            hold_days = i - pos['entry_date_idx']

            exit_reason = None
            if pnl_pct >= PROFIT_TARGET:
                exit_reason = 'PROFIT'
                total_exits_profit += 1
            elif pnl_pct <= STOP_LOSS:
                exit_reason = 'STOP'
                total_exits_stop += 1
            elif hold_days >= MAX_HOLD_DAYS:
                exit_reason = 'TIME'
                total_exits_time += 1

            if exit_reason:
                proceeds = pos['shares'] * current_price
                comm = proceeds * COMMISSION_BPS / 10000
                cash += proceeds - comm
                trade_log.append({
                    'date': date, 'ticker': t, 'action': 'SELL',
                    'reason': exit_reason, 'entry': entry_price,
                    'exit': current_price, 'pnl_pct': pnl_pct,
                    'hold_days': hold_days, 'shares': pos['shares']
                })
                positions.remove(pos)

        # ── FIND NEW ENTRY SIGNALS ──
        max_pos = MAX_POSITIONS if current_regime == 'RISK_ON' else MAX_POS_RISK_OFF
        open_slots = max_pos - len(positions)

        if open_slots <= 0 or vix_panic:
            continue

        # Already held tickers
        held_tickers = set(p['ticker'] for p in positions)

        candidates = []
        for ticker in UNIVERSE:
            if ticker in held_tickers:
                continue
            if ticker not in prices.columns:
                continue
            if pd.isna(prices[ticker].iloc[i]):
                continue

            current_price = float(prices[ticker].iloc[i])

            # 1. Drop threshold: stock fell >= DROP_THRESHOLD in last DROP_LOOKBACK days
            if i < DROP_LOOKBACK:
                continue
            past_price = float(prices[ticker].iloc[i - DROP_LOOKBACK])
            if pd.isna(past_price) or past_price <= 0:
                continue
            drop = (current_price / past_price) - 1.0
            if drop > DROP_THRESHOLD:  # Not dropped enough
                continue

            # 2. RSI check
            if ticker not in rsi_data:
                continue
            rsi_val = rsi_data[ticker].iloc[i]
            if pd.isna(rsi_val) or rsi_val > RSI_THRESHOLD:
                continue

            # 3. Trend filter: above 200-day SMA (buying dips in uptrends only)
            if i < TREND_SMA:
                continue
            sma_val = float(prices[ticker].iloc[i - TREND_SMA + 1:i + 1].mean())
            if current_price < sma_val:
                continue  # Below trend — falling knife, skip

            # 4. Volume filter: must have decent liquidity
            if ticker in volumes.columns and i >= 20:
                avg_vol = volumes[ticker].iloc[i-20:i].mean()
                if pd.isna(avg_vol) or avg_vol < 500_000:
                    continue

            # Score by how oversold (more oversold = better)
            score = -drop  # Bigger drop = higher score
            candidates.append((ticker, score, drop, rsi_val))

        # Sort by most oversold first
        candidates.sort(key=lambda x: x[1], reverse=True)

        # Enter positions
        for ticker, score, drop, rsi_val in candidates[:open_slots]:
            buy_price = float(prices[ticker].iloc[i])
            if buy_price <= 0:
                continue

            # Position size: equal weight based on portfolio value
            target_val = port_val * POSITION_SIZE
            shares = int(target_val / buy_price)
            if shares <= 0:
                continue

            cost = shares * buy_price
            comm = cost * COMMISSION_BPS / 10000

            if cost + comm <= cash:
                cash -= cost + comm
                positions.append({
                    'ticker': ticker,
                    'entry_price': buy_price,
                    'entry_date_idx': i,
                    'shares': shares
                })
                total_entries += 1
                trade_log.append({
                    'date': date, 'ticker': ticker, 'action': 'BUY',
                    'entry': buy_price, 'drop': drop, 'rsi': rsi_val,
                    'shares': shares
                })

    # Close remaining positions at last price
    last_i = n_days - 1
    for pos in positions:
        t = pos['ticker']
        if t in prices.columns and not pd.isna(prices[t].iloc[last_i]):
            p = float(prices[t].iloc[last_i])
            cash += pos['shares'] * p

    stats = {
        'total_entries': total_entries,
        'exits_profit': total_exits_profit,
        'exits_stop': total_exits_stop,
        'exits_time': total_exits_time,
    }
    return pd.DataFrame(portfolio_values), pd.DataFrame(trade_log), stats


def analyze(portfolio_df, trade_df, stats):
    df = portfolio_df.set_index('date')
    df = df[df['value'] > 0]
    df['return'] = df['value'].pct_change()
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
    max_dd_date = dd.idxmin()

    downside = df['return'][df['return'] < 0].std() * np.sqrt(252)
    sortino = (cagr - 0.02) / downside if downside > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    monthly = df['value'].resample('ME').last()
    monthly_ret = monthly.pct_change().dropna()
    win_rate_monthly = (monthly_ret > 0).mean()

    yearly = df['value'].resample('YE').last()
    yearly_ret = yearly.pct_change().dropna()

    # Trade-level stats
    sells = trade_df[trade_df['action'] == 'SELL'] if len(trade_df) > 0 else pd.DataFrame()
    if len(sells) > 0 and 'pnl_pct' in sells.columns:
        trade_win_rate = (sells['pnl_pct'] > 0).mean()
        avg_win = sells[sells['pnl_pct'] > 0]['pnl_pct'].mean() if (sells['pnl_pct'] > 0).any() else 0
        avg_loss = sells[sells['pnl_pct'] <= 0]['pnl_pct'].mean() if (sells['pnl_pct'] <= 0).any() else 0
        avg_hold = sells['hold_days'].mean()
        total_trades = len(sells)
    else:
        trade_win_rate = avg_win = avg_loss = avg_hold = total_trades = 0

    print(f"\n{'='*60}")
    print(f"  RATTLESNAKE v1.0 -- MEAN-REVERSION RESULTS")
    print(f"{'='*60}")
    print(f"  Period:       {df.index[0].strftime('%Y-%m-%d')} -> {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Years:        {years:.1f}")
    print(f"")
    print(f"  -- PORTFOLIO --")
    print(f"  Initial:      ${INITIAL_CAPITAL:>12,.0f}")
    print(f"  Final:        ${final_val:>12,.0f}")
    print(f"  CAGR:         {cagr:>11.2%}")
    print(f"  Annual Vol:   {annual_vol:>11.2%}")
    print(f"  Max Drawdown: {max_dd:>11.2%} ({max_dd_date.strftime('%Y-%m-%d')})")
    print(f"")
    print(f"  -- RATIOS --")
    print(f"  Sharpe:       {sharpe:>11.2f}")
    print(f"  Sortino:      {sortino:>11.2f}")
    print(f"  Calmar:       {calmar:>11.2f}")
    print(f"")
    print(f"  -- TRADING --")
    print(f"  Total Entries:   {stats['total_entries']:>6}")
    print(f"  Profit Exits:    {stats['exits_profit']:>6} ({stats['exits_profit']/max(stats['total_entries'],1)*100:.0f}%)")
    print(f"  Stop Exits:      {stats['exits_stop']:>6} ({stats['exits_stop']/max(stats['total_entries'],1)*100:.0f}%)")
    print(f"  Time Exits:      {stats['exits_time']:>6} ({stats['exits_time']/max(stats['total_entries'],1)*100:.0f}%)")
    print(f"  Trade Win Rate:  {trade_win_rate:>10.1%}")
    print(f"  Avg Winner:      {avg_win:>10.2%}")
    print(f"  Avg Loser:       {avg_loss:>10.2%}")
    print(f"  Avg Hold Days:   {avg_hold:>10.1f}")
    print(f"  Monthly Win%:    {win_rate_monthly:>10.1%}")
    print(f"")

    # Payoff ratio
    if avg_loss != 0:
        payoff = abs(avg_win / avg_loss)
        expectancy = (trade_win_rate * avg_win) + ((1 - trade_win_rate) * avg_loss)
        print(f"  Payoff Ratio:    {payoff:>10.2f}")
        print(f"  Expectancy:      {expectancy:>10.3%}")
        print(f"")

    # Head-to-head vs COMPASS
    print(f"  {'METRIC':<18} {'RATTLESNAKE':>12} {'COMPASS':>10}")
    print(f"  {'-'*40}")
    print(f"  {'CAGR':<18} {cagr:>11.2%} {'16.95%':>10}")
    print(f"  {'Sharpe':<18} {sharpe:>12.2f} {'0.81':>10}")
    print(f"  {'Max DD':<18} {max_dd:>11.2%} {'-28.40%':>10}")
    print(f"  {'Volatility':<18} {annual_vol:>11.2%} {'~18%':>10}")
    print(f"  {'Strategy':<18} {'MeanRevert':>12} {'Momentum':>10}")
    print(f"")

    # Annual returns
    print(f"  -- ANNUAL RETURNS --")
    for idx, ret in yearly_ret.items():
        yr = idx.year
        if ret > 0:
            bar = '+' * min(int(ret * 100), 50)
            print(f"  {yr}  +{ret:>5.1%}  {bar}")
        else:
            bar = '-' * min(int(abs(ret) * 100), 50)
            print(f"  {yr}  {ret:>6.1%}  {bar}")

    # Most traded stocks
    if len(trade_df) > 0:
        buys = trade_df[trade_df['action'] == 'BUY']
        if len(buys) > 0:
            from collections import Counter
            counter = Counter(buys['ticker'].tolist())
            print(f"\n  -- MOST TRADED (top 10) --")
            for t, c in counter.most_common(10):
                print(f"  {t:<6} {c:>4} trades")

    print(f"\n{'='*60}")
    return {'cagr': cagr, 'sharpe': sharpe, 'max_dd': max_dd, 'final_value': final_val}


if __name__ == '__main__':
    print("RATTLESNAKE v1.0 - Mean-Reversion Contrarian")
    print("=" * 50)
    print("  Buy the dip. Sell the bounce.")
    print("  The philosophical opposite of COMPASS.")
    print()

    print("Step 1: Download data...")
    data = download_data()
    prices = data['prices']
    print(f"  {len(prices)} days, {len(prices.columns)} tickers")
    avail = [t for t in UNIVERSE if t in prices.columns]
    print(f"  Universe coverage: {len(avail)}/{len(UNIVERSE)} stocks")

    print("\nStep 2: Backtest...")
    port_df, trade_df, stats = run_backtest(data)

    print("\nStep 3: Results...")
    metrics = analyze(port_df, trade_df, stats)
