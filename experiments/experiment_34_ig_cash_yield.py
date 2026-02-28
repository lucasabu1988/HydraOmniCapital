"""
EXPERIMENT #34: Investment Grade Corporate Bond Cash Yield
==========================================================
Chassis change: Replace fixed 3.5% T-bill cash yield with historical
Moody's Aaa corporate bond yield (variable by year).

Data source: FRED series AAA (Moody's Seasoned Aaa Corporate Bond Yield)
- 2000-2025 average: 4.81% (vs 3.5% T-bill proxy)
- Range: 2.48% (2020) to 7.62% (2000)

This is a PURE CHASSIS change — no trading logic modified.
Uses exact production backtest engine with only the cash yield changed.

Baseline: COMPASS v8.2 = 17.66% CAGR (3.5% fixed cash yield)
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import os
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETERS (identical to COMPASS v8.2)
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
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

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
print("EXPERIMENT #34: IG Corporate Bond Cash Yield (Variable)")
print("=" * 70)
print("Chassis change: 3.5% fixed T-bill -> Moody's Aaa yield (variable)")
print("Data source: FRED series AAA, monthly, 2000-2026")
print("Baseline: COMPASS v8.2 = 17.66% CAGR (3.5% fixed)")
print("=" * 70)

# ============================================================================
# LOAD MOODY'S Aaa YIELD DATA FROM FRED
# ============================================================================
print("\nLoading Moody's Aaa yield data from FRED...")
url_aaa = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=2000-01-01&coed=2026-02-23'
aaa_monthly = pd.read_csv(url_aaa, parse_dates=['observation_date'], index_col='observation_date')
aaa_monthly.columns = ['yield_pct']

# Forward-fill monthly data to daily
aaa_daily = aaa_monthly.resample('D').ffill()
# Convert annual yield % to daily rate
aaa_daily['daily_rate'] = aaa_daily['yield_pct'] / 100 / 252

print(f"  Loaded {len(aaa_monthly)} monthly observations")
print(f"  Expanded to {len(aaa_daily)} daily rates")
print(f"  Period avg: {aaa_monthly['yield_pct'].mean():.2f}%")
print(f"  Range: {aaa_monthly['yield_pct'].min():.2f}% - {aaa_monthly['yield_pct'].max():.2f}%")

# ============================================================================
# DATA LOADING (identical to production)
# ============================================================================
CACHE_DIR = 'data_cache'
os.makedirs(CACHE_DIR, exist_ok=True)

print("\nLoading market data...")
price_data = {}
spy_data = None

cache_spy = os.path.join(CACHE_DIR, 'spy_full.parquet')
if os.path.exists(cache_spy):
    spy_data = pd.read_parquet(cache_spy)
    print(f"  SPY: {len(spy_data)} bars (cached)")
else:
    spy_data = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    if not spy_data.empty:
        spy_data.to_parquet(cache_spy)
        print(f"  SPY: {len(spy_data)} bars (downloaded)")

if isinstance(spy_data.columns, pd.MultiIndex):
    spy_data.columns = spy_data.columns.get_level_values(0)

cache_file = os.path.join(CACHE_DIR, 'broad_pool_full.parquet')
if os.path.exists(cache_file):
    all_data = pd.read_parquet(cache_file)
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
    print(f"  Pool: {len(price_data)} stocks (cached)")
else:
    print("  Downloading pool data...")
    all_data = yf.download(BROAD_POOL, start=START_DATE, end=END_DATE, progress=True)
    if not all_data.empty:
        all_data.to_parquet(cache_file)
        if isinstance(all_data.columns, pd.MultiIndex):
            for symbol in all_data.columns.get_level_values(1).unique().tolist():
                try:
                    df = all_data.xs(symbol, level=1, axis=1).copy()
                    df = df.dropna(subset=['Close'])
                    if len(df) > 0:
                        price_data[symbol] = df
                except Exception:
                    continue

# ============================================================================
# BACKTEST (identical to production except cash yield is variable)
# ============================================================================
trading_days = spy_data.index
cash = INITIAL_CAPITAL
positions = {}
trades = []
daily_values = []
peak_value = INITIAL_CAPITAL

current_regime = True
regime_consecutive = 0
regime_last_raw = True
in_protection = False
protection_stage = 0
stop_loss_day_index = None
current_universe = []
universe_year = None

# Track cash yield earned
total_cash_yield_earned = 0

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

    if in_protection and stop_loss_day_index is not None:
        days_since_stop = i - stop_loss_day_index
        if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and current_regime:
            protection_stage = 2
        if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and current_regime:
            in_protection = False
            protection_stage = 0
            stop_loss_day_index = None

    # === Portfolio value ===
    portfolio_value = cash
    for symbol, pos in positions.items():
        if symbol in price_data and date in price_data[symbol].index:
            portfolio_value += pos['shares'] * price_data[symbol].loc[date, 'Close']
        else:
            portfolio_value += pos['shares'] * pos['entry_price']

    if portfolio_value > peak_value:
        peak_value = portfolio_value

    portfolio_dd = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

    # === Portfolio stop ===
    if portfolio_dd <= PORTFOLIO_STOP_LOSS and not in_protection:
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
        positions = {}
        in_protection = True
        protection_stage = 1
        stop_loss_day_index = i

    # === Position exits (IDENTICAL to production) ===
    tradeable_symbols = current_universe if current_universe else list(price_data.keys())

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

    # === Entries (IDENTICAL to production) ===
    slots_available = max_positions - len(positions)
    if slots_available > 0 and not in_protection or (in_protection and len(positions) < max_positions):
        scores = {}
        for symbol in tradeable_symbols:
            if symbol in positions or symbol not in price_data:
                continue
            df = price_data[symbol]
            mask = df.index <= date
            recent = df.loc[mask]
            if len(recent) < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
                continue
            price_end = recent['Close'].iloc[-(MOMENTUM_SKIP + 1)]
            price_start = recent['Close'].iloc[-(MOMENTUM_LOOKBACK + MOMENTUM_SKIP)]
            if price_start > 0:
                scores[symbol] = (price_end - price_start) / price_start

        if len(scores) >= MIN_MOMENTUM_STOCKS:
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            candidates = [s for s, _ in ranked[:max_positions] if s not in positions]

            if i >= VOL_LOOKBACK:
                spy_returns = spy_data['Close'].iloc[max(0, i-VOL_LOOKBACK):i+1].pct_change().dropna()
                realized_vol = spy_returns.std() * np.sqrt(252)
                leverage = min(LEVERAGE_MAX, max(LEVERAGE_MIN, TARGET_VOL / realized_vol)) if realized_vol > 0 else LEVERAGE_MAX
            else:
                leverage = 1.0

            if in_protection:
                leverage = 0.3 if protection_stage == 1 else 1.0

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
                                'shares': shares, 'entry_price': price,
                                'entry_date': date, 'entry_idx': i,
                                'high_price': price,
                            }

    # === CASH YIELD: Variable Moody's Aaa rate (THE ONLY CHANGE) ===
    if cash > 0:
        # Look up the Aaa yield for this date
        date_ts = pd.Timestamp(date)
        if date_ts in aaa_daily.index:
            daily_rate = aaa_daily.loc[date_ts, 'daily_rate']
        else:
            # Find nearest prior date
            mask = aaa_daily.index <= date_ts
            if mask.any():
                daily_rate = aaa_daily.loc[mask].iloc[-1]['daily_rate']
            else:
                daily_rate = 0.035 / 252  # Fallback to T-bill

        yield_earned = cash * daily_rate
        cash += yield_earned
        total_cash_yield_earned += yield_earned

    # === Daily tracking ===
    portfolio_value = cash
    for symbol, pos in positions.items():
        if symbol in price_data and date in price_data[symbol].index:
            portfolio_value += pos['shares'] * price_data[symbol].loc[date, 'Close']
        else:
            portfolio_value += pos['shares'] * pos['entry_price']

    daily_values.append({'date': date, 'portfolio_value': portfolio_value, 'cash': cash})

    if i % 1000 == 0 and i > 0:
        cagr_so_far = (portfolio_value / INITIAL_CAPITAL) ** (252 / i) - 1
        print(f"  Day {i:,}/{len(trading_days):,} | {date.strftime('%Y-%m-%d')} | ${portfolio_value:,.0f} | CAGR: {cagr_so_far:.2%}")

# ============================================================================
# RESULTS
# ============================================================================
print("\n" + "=" * 70)
print("RESULTS: Experiment #34 — IG Corporate Bond Cash Yield")
print("=" * 70)

df = pd.DataFrame(daily_values)
final_value = df['portfolio_value'].iloc[-1]
years = len(df) / 252
cagr = (final_value / INITIAL_CAPITAL) ** (1 / years) - 1

daily_returns = df['portfolio_value'].pct_change().dropna()
sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252) if daily_returns.std() > 0 else 0

rolling_max = df['portfolio_value'].cummax()
drawdown = (df['portfolio_value'] - rolling_max) / rolling_max
max_dd = drawdown.min()

# Also run baseline (3.5% fixed) for comparison
print("\nRunning baseline (3.5% fixed) for exact comparison...")
# Re-run with fixed rate
cash_b = INITIAL_CAPITAL
positions_b = {}
trades_b = []
daily_values_b = []
peak_value_b = INITIAL_CAPITAL
current_regime_b = True
regime_consecutive_b = 0
regime_last_raw_b = True
in_protection_b = False
protection_stage_b = 0
stop_loss_day_index_b = None
universe_year_b = None
current_universe_b = []
FIXED_RATE = 0.035

for i, date in enumerate(trading_days):
    year = date.year
    if year != universe_year_b:
        universe_year_b = year
        lookback_start = date - timedelta(days=365)
        valid_symbols = []
        for symbol in BROAD_POOL:
            if symbol in price_data:
                df2 = price_data[symbol]
                mask = (df2.index >= lookback_start) & (df2.index <= date)
                subset = df2.loc[mask]
                if len(subset) >= MIN_AGE_DAYS:
                    avg_dollar_vol = (subset['Close'] * subset.get('Volume', pd.Series(1e6, index=subset.index))).mean()
                    valid_symbols.append((symbol, avg_dollar_vol))
        valid_symbols.sort(key=lambda x: x[1], reverse=True)
        current_universe_b = [s for s, _ in valid_symbols[:TOP_N]]

    if i >= REGIME_SMA_PERIOD:
        spy_close = spy_data['Close'].iloc[:i+1]
        sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean().iloc[-1]
        raw_regime = spy_close.iloc[-1] > sma200
        if raw_regime == regime_last_raw_b:
            regime_consecutive_b += 1
        else:
            regime_consecutive_b = 1
            regime_last_raw_b = raw_regime
        if regime_consecutive_b >= REGIME_CONFIRM_DAYS:
            current_regime_b = raw_regime

    if in_protection_b:
        max_positions_b = 2 if protection_stage_b == 1 else 3
    elif not current_regime_b:
        max_positions_b = NUM_POSITIONS_RISK_OFF
    else:
        max_positions_b = NUM_POSITIONS

    if in_protection_b and stop_loss_day_index_b is not None:
        days_since_stop = i - stop_loss_day_index_b
        if protection_stage_b == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and current_regime_b:
            protection_stage_b = 2
        if protection_stage_b == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and current_regime_b:
            in_protection_b = False
            protection_stage_b = 0
            stop_loss_day_index_b = None

    portfolio_value_b = cash_b
    for symbol, pos in positions_b.items():
        if symbol in price_data and date in price_data[symbol].index:
            portfolio_value_b += pos['shares'] * price_data[symbol].loc[date, 'Close']
        else:
            portfolio_value_b += pos['shares'] * pos['entry_price']
    if portfolio_value_b > peak_value_b:
        peak_value_b = portfolio_value_b
    portfolio_dd_b = (portfolio_value_b - peak_value_b) / peak_value_b if peak_value_b > 0 else 0

    if portfolio_dd_b <= PORTFOLIO_STOP_LOSS and not in_protection_b:
        for symbol in list(positions_b.keys()):
            if symbol in price_data and date in price_data[symbol].index:
                exit_price = price_data[symbol].loc[date, 'Close']
                pos = positions_b[symbol]
                cash_b += pos['shares'] * exit_price - pos['shares'] * COMMISSION_PER_SHARE
        positions_b = {}
        in_protection_b = True
        protection_stage_b = 1
        stop_loss_day_index_b = i

    tradeable_b = current_universe_b if current_universe_b else list(price_data.keys())
    for symbol in list(positions_b.keys()):
        pos = positions_b[symbol]
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
        if symbol not in tradeable_b:
            exit_reason = 'universe_rotation'
        if exit_reason is None and len(positions_b) > max_positions_b:
            pr = {}
            for s, p in positions_b.items():
                if s in price_data and date in price_data[s].index:
                    pr[s] = (price_data[s].loc[date, 'Close'] - p['entry_price']) / p['entry_price']
            if symbol == min(pr, key=pr.get):
                exit_reason = 'regime_reduce'
        if exit_reason:
            cash_b += pos['shares'] * current_price - pos['shares'] * COMMISSION_PER_SHARE
            del positions_b[symbol]

    slots_b = max_positions_b - len(positions_b)
    if slots_b > 0 and not in_protection_b or (in_protection_b and len(positions_b) < max_positions_b):
        scores = {}
        for symbol in tradeable_b:
            if symbol in positions_b or symbol not in price_data:
                continue
            df2 = price_data[symbol]
            recent = df2.loc[df2.index <= date]
            if len(recent) < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
                continue
            pe = recent['Close'].iloc[-(MOMENTUM_SKIP + 1)]
            ps = recent['Close'].iloc[-(MOMENTUM_LOOKBACK + MOMENTUM_SKIP)]
            if ps > 0:
                scores[symbol] = (pe - ps) / ps
        if len(scores) >= MIN_MOMENTUM_STOCKS:
            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            candidates = [s for s, _ in ranked[:max_positions_b] if s not in positions_b]
            if i >= VOL_LOOKBACK:
                sr = spy_data['Close'].iloc[max(0, i-VOL_LOOKBACK):i+1].pct_change().dropna()
                rv = sr.std() * np.sqrt(252)
                lev = min(LEVERAGE_MAX, max(LEVERAGE_MIN, TARGET_VOL / rv)) if rv > 0 else LEVERAGE_MAX
            else:
                lev = 1.0
            if in_protection_b:
                lev = 0.3 if protection_stage_b == 1 else 1.0
            te = cash_b
            for s, p in positions_b.items():
                if s in price_data and date in price_data[s].index:
                    te += p['shares'] * price_data[s].loc[date, 'Close']
            pp = te * lev / max_positions_b if max_positions_b > 0 else 0
            for symbol in candidates[:slots_b]:
                if symbol in price_data and date in price_data[symbol].index:
                    price = price_data[symbol].loc[date, 'Close']
                    if price > 0 and pp > 0:
                        shares = pp / price
                        cost = shares * price + shares * COMMISSION_PER_SHARE
                        if cash_b >= cost:
                            cash_b -= cost
                            positions_b[symbol] = {
                                'shares': shares, 'entry_price': price,
                                'entry_date': date, 'entry_idx': i,
                                'high_price': price,
                            }

    if cash_b > 0:
        cash_b += cash_b * (FIXED_RATE / 252)

    portfolio_value_b = cash_b
    for symbol, pos in positions_b.items():
        if symbol in price_data and date in price_data[symbol].index:
            portfolio_value_b += pos['shares'] * price_data[symbol].loc[date, 'Close']
        else:
            portfolio_value_b += pos['shares'] * pos['entry_price']
    daily_values_b.append({'date': date, 'portfolio_value': portfolio_value_b})

df_b = pd.DataFrame(daily_values_b)
final_b = df_b['portfolio_value'].iloc[-1]
cagr_b = (final_b / INITIAL_CAPITAL) ** (1 / years) - 1
dr_b = df_b['portfolio_value'].pct_change().dropna()
sharpe_b = (dr_b.mean() / dr_b.std()) * np.sqrt(252)
rm_b = df_b['portfolio_value'].cummax()
dd_b = (df_b['portfolio_value'] - rm_b) / rm_b
max_dd_b = dd_b.min()

print(f"\n{'Metric':<30} {'IG Corp (Aaa)':<20} {'T-bill (3.5%)':<20} {'Diff':<15}")
print("-" * 85)
print(f"{'CAGR':<30} {cagr:<19.2%} {cagr_b:<19.2%} {(cagr - cagr_b):<+14.2%}")
print(f"{'Sharpe':<30} {sharpe:<20.3f} {sharpe_b:<20.3f} {(sharpe - sharpe_b):<+15.3f}")
print(f"{'Max Drawdown':<30} {max_dd:<19.2%} {max_dd_b:<19.2%} {(max_dd - max_dd_b):<+14.2%}")
print(f"{'Final Value':<30} {'${:,.0f}'.format(final_value):<20} {'${:,.0f}'.format(final_b):<20} {'${:,.0f}'.format(final_value - final_b):<15}")
print(f"{'Total Cash Yield Earned':<30} {'${:,.0f}'.format(total_cash_yield_earned):<20}")
avg_yield = aaa_monthly['yield_pct'].mean()
print(f"{'Effective Avg Yield':<30} {avg_yield:<19.2f}% {'3.50%':<20}")

print("\n" + "=" * 70)
diff_cagr = cagr - cagr_b
if diff_cagr > 0:
    print(f"RESULT: +{diff_cagr:.2%} CAGR improvement -> CHASSIS UPGRADE CANDIDATE")
    print(f"  Pure additive: no trading logic changed, no extra risk")
    print(f"  Realistic: Aaa corporate bonds are highest quality IG debt")
else:
    print(f"RESULT: {diff_cagr:.2%} -> NO IMPROVEMENT")
print("=" * 70)
