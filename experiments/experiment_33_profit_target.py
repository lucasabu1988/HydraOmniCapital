"""
EXPERIMENT #33: Profit Target Exit
===================================
Hypothesis: If a position is up >= 3%, extend hold until +10% profit or trailing stop.
Instead of exiting at 5 days, keep holding winners.

Rules:
- If pos_return < 3% at hold expiry (5d) -> exit normally (hold_expired)
- If pos_return >= 3% at hold expiry -> EXTEND hold, exit only when:
  a) pos_return >= 10% (profit target hit)
  b) trailing stop triggered (-3% from high, activated at +5%)
  c) position stop triggered (-8%)
  d) universe rotation
  e) max extended hold of 15 days (safety cap)

Baseline: COMPASS v8.2 = 17.66% CAGR, 0.85 Sharpe, -27.5% MaxDD

NOTE: This is an ISOLATED experiment. omnicapital_v8_compass.py is NOT modified.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import os
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETERS (same as COMPASS v8.2 baseline)
# ============================================================================
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
LEVERAGE_MAX = 1.0
VOL_LOOKBACK = 20
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# === EXPERIMENT #33 PARAMETERS ===
PROFIT_EXTEND_THRESHOLD = 0.03  # Extend hold if pos is up >= 3% at hold expiry
PROFIT_TARGET = 0.10            # Take profit at +10%
MAX_EXTENDED_HOLD = 15          # Max days to hold (safety cap)

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

print("=" * 70)
print("EXPERIMENT #33: Profit Target Exit")
print("=" * 70)
print(f"Hypothesis: If position >= +{PROFIT_EXTEND_THRESHOLD:.0%} at day {HOLD_DAYS},")
print(f"            extend hold until +{PROFIT_TARGET:.0%} or trailing stop")
print(f"            Max extended hold: {MAX_EXTENDED_HOLD} days")
print(f"Baseline:   COMPASS v8.2 = 17.66% CAGR | 0.85 Sharpe | -27.5% MaxDD")
print("=" * 70)

# ============================================================================
# DATA LOADING (identical to production)
# ============================================================================
CACHE_DIR = 'data_cache'
os.makedirs(CACHE_DIR, exist_ok=True)

print("\nLoading data...")
price_data = {}
spy_data = None

# Load SPY
cache_spy = os.path.join(CACHE_DIR, 'spy_full.parquet')
if os.path.exists(cache_spy):
    spy_data = pd.read_parquet(cache_spy)
    print(f"  SPY: {len(spy_data)} bars (cached)")
else:
    spy_data = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    if not spy_data.empty:
        spy_data.to_parquet(cache_spy)
        print(f"  SPY: {len(spy_data)} bars (downloaded)")

# Handle multi-level columns from yfinance
if isinstance(spy_data.columns, pd.MultiIndex):
    spy_data.columns = spy_data.columns.get_level_values(0)

# Load stocks
cache_file = os.path.join(CACHE_DIR, 'broad_pool_full.parquet')
if os.path.exists(cache_file):
    all_data = pd.read_parquet(cache_file)
    print(f"  Pool: {len(all_data.columns.get_level_values(1).unique()) if isinstance(all_data.columns, pd.MultiIndex) else '?'} stocks (cached)")

    if isinstance(all_data.columns, pd.MultiIndex):
        symbols_in_data = all_data.columns.get_level_values(1).unique().tolist()
        for symbol in symbols_in_data:
            try:
                df = all_data.xs(symbol, level=1, axis=1).copy()
                df = df.dropna(subset=['Close'])
                if len(df) > 0:
                    price_data[symbol] = df
            except Exception:
                continue
    else:
        for symbol in BROAD_POOL:
            if symbol in all_data.columns:
                df = pd.DataFrame({'Close': all_data[symbol]}).dropna()
                if len(df) > 0:
                    price_data[symbol] = df
else:
    print("  Downloading pool data...")
    all_data = yf.download(BROAD_POOL, start=START_DATE, end=END_DATE, progress=True)
    if not all_data.empty:
        all_data.to_parquet(cache_file)
        if isinstance(all_data.columns, pd.MultiIndex):
            symbols_in_data = all_data.columns.get_level_values(1).unique().tolist()
            for symbol in symbols_in_data:
                try:
                    df = all_data.xs(symbol, level=1, axis=1).copy()
                    df = df.dropna(subset=['Close'])
                    if len(df) > 0:
                        price_data[symbol] = df
                except Exception:
                    continue

print(f"  Loaded {len(price_data)} stocks with data")

# ============================================================================
# BACKTEST ENGINE (identical to production EXCEPT exit logic)
# ============================================================================
trading_days = spy_data.index
cash = INITIAL_CAPITAL
positions = {}
trades = []
daily_values = []
peak_value = INITIAL_CAPITAL

# Regime tracking
current_regime = True
regime_consecutive = 0
regime_last_raw = True

# Protection/Recovery
in_protection = False
protection_stage = 0
stop_loss_day_index = None

# Universe tracking
current_universe = []
universe_year = None

# Experiment tracking
extensions_attempted = 0
extensions_hit_target = 0
extensions_hit_trailing = 0
extensions_hit_maxhold = 0
extensions_hit_stop = 0

print("\nRunning backtest...")

for i, date in enumerate(trading_days):
    # === Annual universe refresh ===
    year = date.year
    if year != universe_year:
        universe_year = year
        lookback_start = date - timedelta(days=365)
        valid_symbols = []
        for symbol in BROAD_POOL:
            if symbol in price_data:
                df = price_data[symbol]
                mask = (df.index >= lookback_start) & (df.index <= date)
                subset = df.loc[mask]
                if len(subset) >= MIN_AGE_DAYS:
                    avg_dollar_vol = (subset['Close'] * subset.get('Volume', pd.Series(1e6, index=subset.index))).mean()
                    valid_symbols.append((symbol, avg_dollar_vol))
        valid_symbols.sort(key=lambda x: x[1], reverse=True)
        current_universe = [s for s, _ in valid_symbols[:TOP_N]]

    # === SPY Regime ===
    if i >= REGIME_SMA_PERIOD:
        spy_close = spy_data['Close'].iloc[:i+1]
        sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean().iloc[-1]
        raw_regime = spy_close.iloc[-1] > sma200

        if raw_regime == regime_last_raw:
            regime_consecutive += 1
        else:
            regime_consecutive = 1
            regime_last_raw = raw_regime

        if regime_consecutive >= REGIME_CONFIRM_DAYS:
            current_regime = raw_regime

    # === Protection / Recovery ===
    if in_protection:
        max_positions = 2 if protection_stage == 1 else 3
    elif not current_regime:
        max_positions = NUM_POSITIONS_RISK_OFF
    else:
        max_positions = NUM_POSITIONS

    # Recovery stages
    if in_protection and stop_loss_day_index is not None:
        days_since_stop = i - stop_loss_day_index
        if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and current_regime:
            protection_stage = 2
        if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and current_regime:
            in_protection = False
            protection_stage = 0
            stop_loss_day_index = None

    # === Portfolio stop loss check ===
    portfolio_value = cash
    for symbol, pos in positions.items():
        if symbol in price_data and date in price_data[symbol].index:
            portfolio_value += pos['shares'] * price_data[symbol].loc[date, 'Close']
        else:
            portfolio_value += pos['shares'] * pos['entry_price']

    if portfolio_value > peak_value:
        peak_value = portfolio_value

    portfolio_dd = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

    if portfolio_dd <= PORTFOLIO_STOP_LOSS and not in_protection:
        # Sell everything
        for symbol in list(positions.keys()):
            if symbol in price_data and date in price_data[symbol].index:
                exit_price = price_data[symbol].loc[date, 'Close']
                pos = positions[symbol]
                proceeds = pos['shares'] * exit_price
                commission = pos['shares'] * COMMISSION_PER_SHARE
                cash += proceeds - commission
                pnl = (exit_price - pos['entry_price']) * pos['shares'] - commission
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': 'portfolio_stop',
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * pos['shares'])
                })
        positions = {}
        in_protection = True
        protection_stage = 1
        stop_loss_day_index = i

    # === POSITION EXITS (MODIFIED FOR EXPERIMENT #33) ===
    tradeable_symbols = current_universe if current_universe else list(price_data.keys())

    for symbol in list(positions.keys()):
        pos = positions[symbol]
        if symbol not in price_data or date not in price_data[symbol].index:
            continue

        current_price = price_data[symbol].loc[date, 'Close']
        exit_reason = None

        days_held = i - pos['entry_idx']
        pos_return = (current_price - pos['entry_price']) / pos['entry_price']

        # Update high price for trailing stop
        if current_price > pos['high_price']:
            pos['high_price'] = current_price

        # === EXPERIMENT #33: Modified hold expiry logic ===
        if days_held >= HOLD_DAYS:
            if not pos.get('extended', False):
                # First time hitting hold expiry
                if pos_return >= PROFIT_EXTEND_THRESHOLD:
                    # Winner: extend the hold
                    pos['extended'] = True
                    pos['extended_at_day'] = days_held
                    extensions_attempted += 1
                    exit_reason = None  # Don't exit yet
                else:
                    # Normal exit: position not profitable enough to extend
                    exit_reason = 'hold_expired'
            else:
                # Already extended — check profit target and max hold
                if pos_return >= PROFIT_TARGET:
                    exit_reason = 'profit_target'
                    extensions_hit_target += 1
                elif days_held >= MAX_EXTENDED_HOLD:
                    exit_reason = 'max_extended_hold'
                    extensions_hit_maxhold += 1

        # 2. Position stop loss (-8%) — always active
        if pos_return <= POSITION_STOP_LOSS:
            if pos.get('extended'):
                extensions_hit_stop += 1
            exit_reason = 'position_stop'

        # 3. Trailing stop — always active
        if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
            trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
            if current_price <= trailing_level:
                if pos.get('extended'):
                    extensions_hit_trailing += 1
                exit_reason = 'trailing_stop'

        # 4. Universe rotation
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
            trades.append({
                'symbol': symbol,
                'entry_date': pos['entry_date'],
                'exit_date': date,
                'exit_reason': exit_reason,
                'pnl': pnl,
                'return': pnl / (pos['entry_price'] * shares),
                'days_held': days_held,
                'extended': pos.get('extended', False),
            })
            del positions[symbol]

    # === ENTRIES (identical to production) ===
    slots_available = max_positions - len(positions)
    if slots_available > 0 and not in_protection or (in_protection and len(positions) < max_positions):
        # Compute momentum scores
        scores = {}
        for symbol in tradeable_symbols:
            if symbol in positions:
                continue
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            mask = df.index <= date
            recent = df.loc[mask]

            if len(recent) < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
                continue

            price_end = recent['Close'].iloc[-(MOMENTUM_SKIP + 1)]
            price_start = recent['Close'].iloc[-(MOMENTUM_LOOKBACK + MOMENTUM_SKIP)]

            if price_start > 0:
                momentum = (price_end - price_start) / price_start
                scores[symbol] = momentum

        if len(scores) >= MIN_MOMENTUM_STOCKS:
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            candidates = [s for s, _ in ranked[:max_positions] if s not in positions]

            # Vol targeting
            if i >= VOL_LOOKBACK:
                spy_returns = spy_data['Close'].iloc[max(0, i-VOL_LOOKBACK):i+1].pct_change().dropna()
                realized_vol = spy_returns.std() * np.sqrt(252)
                if realized_vol > 0:
                    leverage = min(LEVERAGE_MAX, max(LEVERAGE_MIN, TARGET_VOL / realized_vol))
                else:
                    leverage = LEVERAGE_MAX
            else:
                leverage = 1.0

            if in_protection:
                if protection_stage == 1:
                    leverage = 0.3
                else:
                    leverage = 1.0

            # Capital allocation
            total_equity = cash
            for s, p in positions.items():
                if s in price_data and date in price_data[s].index:
                    total_equity += p['shares'] * price_data[s].loc[date, 'Close']

            investable = total_equity * leverage
            per_position = investable / max_positions if max_positions > 0 else 0

            for symbol in candidates[:slots_available]:
                if symbol in price_data and date in price_data[symbol].index:
                    price = price_data[symbol].loc[date, 'Close']
                    if price > 0 and per_position > 0:
                        shares = per_position / price
                        cost = shares * price
                        commission = shares * COMMISSION_PER_SHARE
                        if cash >= cost + commission:
                            cash -= cost + commission
                            positions[symbol] = {
                                'shares': shares,
                                'entry_price': price,
                                'entry_date': date,
                                'entry_idx': i,
                                'high_price': price,
                                'extended': False,
                            }

    # === Cash yield ===
    if cash > 0:
        cash += cash * (CASH_YIELD_RATE / 252)

    # === Daily tracking ===
    portfolio_value = cash
    for symbol, pos in positions.items():
        if symbol in price_data and date in price_data[symbol].index:
            portfolio_value += pos['shares'] * price_data[symbol].loc[date, 'Close']
        else:
            portfolio_value += pos['shares'] * pos['entry_price']

    daily_values.append({
        'date': date,
        'portfolio_value': portfolio_value,
        'cash': cash,
        'num_positions': len(positions),
    })

    if i % 1000 == 0 and i > 0:
        cagr_so_far = (portfolio_value / INITIAL_CAPITAL) ** (252 / i) - 1 if i > 0 else 0
        print(f"  Day {i:,}/{len(trading_days):,} | {date.strftime('%Y-%m-%d')} | ${portfolio_value:,.0f} | CAGR: {cagr_so_far:.2%}")

# ============================================================================
# RESULTS
# ============================================================================
print("\n" + "=" * 70)
print("RESULTS: Experiment #33 — Profit Target Exit")
print("=" * 70)

df = pd.DataFrame(daily_values)
final_value = df['portfolio_value'].iloc[-1]
years = len(df) / 252
cagr = (final_value / INITIAL_CAPITAL) ** (1 / years) - 1

# Sharpe
daily_returns = df['portfolio_value'].pct_change().dropna()
sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252) if daily_returns.std() > 0 else 0

# Max drawdown
rolling_max = df['portfolio_value'].cummax()
drawdown = (df['portfolio_value'] - rolling_max) / rolling_max
max_dd = drawdown.min()

# SPY benchmark
spy_start = spy_data['Close'].iloc[0]
spy_end = spy_data['Close'].iloc[-1]
spy_cagr = (spy_end / spy_start) ** (1 / years) - 1

trades_df = pd.DataFrame(trades)
total_trades = len(trades_df)

print(f"\n{'Metric':<30} {'Experiment #33':>18} {'Baseline v8.2':>18} {'Diff':>12}")
print("-" * 80)
print(f"{'CAGR':<30} {cagr:>17.2%} {'17.66%':>18} {(cagr - 0.1766):>+11.2%}")
print(f"{'Sharpe Ratio':<30} {sharpe:>18.3f} {'0.850':>18} {(sharpe - 0.850):>+12.3f}")
print(f"{'Max Drawdown':<30} {max_dd:>17.2%} {'-27.50%':>18} {(max_dd - (-0.275)):>+11.2%}")
print(f"{'Final Value':<30} {'${:,.0f}'.format(final_value):>18} {'$6,910,000':>18}")
print(f"{'SPY CAGR':<30} {spy_cagr:>17.2%}")
print(f"{'Total Trades':<30} {total_trades:>18,}")
print(f"{'Years':<30} {years:>18.1f}")

print(f"\n{'--- Extension Statistics ---':^80}")
print(f"{'Extensions attempted':<40} {extensions_attempted:>10,}")
print(f"{'  Hit +10% profit target':<40} {extensions_hit_target:>10,}")
print(f"{'  Hit trailing stop':<40} {extensions_hit_trailing:>10,}")
print(f"{'  Hit max hold ({MAX_EXTENDED_HOLD}d)':<40} {extensions_hit_maxhold:>10,}")
print(f"{'  Hit position stop':<40} {extensions_hit_stop:>10,}")

if extensions_attempted > 0:
    target_rate = extensions_hit_target / extensions_attempted * 100
    print(f"{'  Target hit rate':<40} {target_rate:>9.1f}%")

if len(trades_df) > 0:
    exit_reasons = trades_df['exit_reason'].value_counts()
    print(f"\n{'--- Exit Reasons ---':^80}")
    for reason, count in exit_reasons.items():
        avg_ret = trades_df[trades_df['exit_reason'] == reason]['return'].mean() * 100
        print(f"  {reason:<30} {count:>6} trades  avg return: {avg_ret:>+7.2f}%")

    # Extended vs non-extended trade comparison
    if 'extended' in trades_df.columns:
        ext = trades_df[trades_df['extended'] == True]
        noext = trades_df[trades_df['extended'] == False]
        if len(ext) > 0 and len(noext) > 0:
            print(f"\n{'--- Extended vs Normal Trades ---':^80}")
            print(f"  {'Normal trades:':<30} {len(noext):>6}  avg return: {noext['return'].mean()*100:>+7.2f}%  avg days: {noext['days_held'].mean():>.1f}")
            print(f"  {'Extended trades:':<30} {len(ext):>6}  avg return: {ext['return'].mean()*100:>+7.2f}%  avg days: {ext['days_held'].mean():>.1f}")

# Verdict
print("\n" + "=" * 70)
cagr_diff = cagr - 0.1766
if cagr_diff > 0:
    print(f"RESULT: +{cagr_diff:.2%} CAGR improvement -> POTENTIAL WINNER (needs more analysis)")
else:
    print(f"RESULT: {cagr_diff:.2%} CAGR degradation -> FAILED (baseline wins)")
print(f"Baseline: 17.66% CAGR | 0.85 Sharpe | -27.5% MaxDD | $6.91M")
print(f"Exp #33:  {cagr:.2%} CAGR | {sharpe:.3f} Sharpe | {max_dd:.2%} MaxDD | ${final_value:,.0f}")
print("=" * 70)
