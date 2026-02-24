"""
Experiment #36b: Gold Accumulation on Protection
=================================================
COMPASS v8.2 — each time portfolio stop triggers, buy gold futures
with 1% of portfolio value. Gold is NEVER sold (permanent accumulation).

Rules:
- On each portfolio stop loss: allocate 1% of portfolio value to gold futures (GC=F)
- Gold units are NEVER sold — permanent accumulation across cycles
- Rest of COMPASS v8.2 operates identically (protection mode, recovery, etc.)
- Gold held as notional units priced at GC=F continuous futures

Baseline: COMPASS v8.2 = 18.56% CAGR, 0.90 Sharpe, -26.9% MaxDD
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import os
from typing import Dict, List, Optional
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# COMPASS v8.2 PARAMETERS (LOCKED — identical to production)
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
CASH_YIELD_SOURCE = 'AAA'
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# Experiment #36b specific
GOLD_ALLOCATION_PCT = 0.01  # 1% of portfolio to gold on each stop loss

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
    'NFLX',
]

print("=" * 80)
print("EXPERIMENT #36b: GOLD ACCUMULATION ON PROTECTION")
print("1% of portfolio to gold futures (GC=F) on each stop — never sold")
print("=" * 80)


# ============================================================================
# DATA FUNCTIONS
# ============================================================================

def load_data_parquet() -> Dict[str, pd.DataFrame]:
    cache_dir = 'data_cache_parquet'
    manifest_file = os.path.join(cache_dir, f'manifest_{START_DATE}_{END_DATE}.txt')
    if not os.path.exists(manifest_file):
        print("[ERROR] No parquet cache found.")
        return {}
    print("[Cache] Loading from parquet cache...")
    data = {}
    for symbol in BROAD_POOL:
        pfile = os.path.join(cache_dir, f'{symbol}.parquet')
        if os.path.exists(pfile):
            df = pd.read_parquet(pfile)
            if not df.empty and len(df) > 100:
                data[symbol] = df
    print(f"  Loaded {len(data)} symbols from parquet")
    return data


def download_gold_futures() -> pd.DataFrame:
    cache_file = f'data_cache/GC_F_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading Gold Futures data...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    print("[Download] Downloading Gold Futures (GC=F)...")
    df = yf.download('GC=F', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    print(f"  Gold: {len(df)} days ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
    return df


def download_spy() -> pd.DataFrame:
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def download_cash_yield() -> Optional[pd.Series]:
    cache_file = 'data_cache/moody_aaa_yield.csv'
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        return df['yield_pct'].resample('D').ffill()
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=1999-01-01&coed=2026-12-31'
        df = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
        df.columns = ['yield_pct']
        os.makedirs('data_cache', exist_ok=True)
        df.to_csv(cache_file)
        return df['yield_pct'].resample('D').ffill()
    except Exception:
        return None


# ============================================================================
# SIGNAL & REGIME (identical to production)
# ============================================================================

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
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue
        if sym_idx < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
            continue
        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - MOMENTUM_SKIP]
        close_lookback = df['Close'].iloc[sym_idx - MOMENTUM_LOOKBACK]
        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue
        momentum_90d = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        scores[symbol] = momentum_90d - skip_5d
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


def compute_annual_top40(price_data):
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
        annual_universe[year] = [s for s, _ in ranked[:TOP_N]]
    return annual_universe


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
# BACKTEST — COMPASS v8.2 + 1% Gold Accumulation on Stop
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data, gold_data, cash_yield_daily=None):
    """COMPASS v8.2 backtest with 1% gold purchase on each protection trigger."""

    print("\n" + "=" * 80)
    print("RUNNING COMPASS + 1% GOLD ACCUMULATION BACKTEST")
    print("=" * 80)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    regime = compute_regime(spy_data)

    gold_first_date = gold_data.index[0] if len(gold_data) > 0 else pd.Timestamp('2099-01-01')
    print(f"Gold Futures available from: {gold_first_date.strftime('%Y-%m-%d')}")
    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

    # Portfolio state
    cash = float(INITIAL_CAPITAL)
    positions = {}
    gold_units = 0.0  # Permanent gold holdings (NEVER sold)
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

    protection_cycles = 0
    gold_purchases = []  # Track each gold purchase

    for i, date in enumerate(all_dates):
        if date.year != current_year:
            current_year = date.year

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # --- Gold price today ---
        gold_price = None
        if date in gold_data.index:
            gold_price = float(gold_data.loc[date, 'Close'])

        # --- Calculate portfolio value ---
        portfolio_value = cash

        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # Add gold value (permanent, never sold)
        if gold_price and gold_price > 0 and gold_units > 0:
            portfolio_value += gold_units * gold_price

        # --- Update peak ---
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # --- Check recovery from protection mode ---
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = True
            if date in regime.index:
                is_regime_on = bool(regime.loc[date])

            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2
                print(f"  [RECOVERY S1] {date.strftime('%Y-%m-%d')}: Stage 2 | Value: ${portfolio_value:,.0f}")

            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None
                print(f"  [RECOVERY S2] {date.strftime('%Y-%m-%d')}: Full recovery | Value: ${portfolio_value:,.0f}")

        # --- Drawdown ---
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # --- Portfolio stop loss ---
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({
                'date': date,
                'portfolio_value': portfolio_value,
                'drawdown': drawdown
            })
            protection_cycles += 1
            print(f"\n  [STOP LOSS #{protection_cycles}] {date.strftime('%Y-%m-%d')}: DD {drawdown:.1%} | Value: ${portfolio_value:,.0f}")

            # Close ALL equity positions (same as baseline)
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
                del positions[symbol]

            # === BUY 1% OF PORTFOLIO VALUE IN GOLD — NEVER SELL ===
            if gold_price and gold_price > 0 and date >= gold_first_date:
                gold_allocation = portfolio_value * GOLD_ALLOCATION_PCT
                gold_buy_units = gold_allocation / gold_price
                commission = gold_buy_units * COMMISSION_PER_SHARE
                if gold_allocation + commission <= cash:
                    gold_units += gold_buy_units
                    cash -= (gold_allocation + commission)
                    gold_purchases.append({
                        'date': date,
                        'units': gold_buy_units,
                        'price': gold_price,
                        'cost': gold_allocation,
                        'total_units': gold_units,
                    })
                    print(f"  [GOLD +1%] Bought {gold_buy_units:.2f} units @ ${gold_price:.2f} = ${gold_allocation:,.0f} | Total: {gold_units:.2f} units")
                else:
                    print(f"  [GOLD SKIP] Not enough cash for 1% gold allocation")
            else:
                print(f"  [NO GOLD] Gold not available on {date.strftime('%Y-%m-%d')}")

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

        # --- Daily costs ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # --- Cash yield on uninvested cash ---
        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        # --- Close equity positions (identical to baseline) ---
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
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # --- Open new equity positions (identical to baseline) ---
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
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + commission

        # --- Record daily ---
        gold_value = gold_units * gold_price if (gold_price and gold_units > 0) else 0
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
            'in_protection': in_protection_mode,
            'risk_on': is_risk_on,
            'gold_units': gold_units,
            'gold_value': gold_value,
        })

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [PROT S{protection_stage}]" if in_protection_mode else ""
            gold_str = f" | Gold: {gold_units:.2f} units (${gold_value:,.0f})" if gold_units > 0 else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str}{gold_str}")

    print(f"\n  Protection cycles: {protection_cycles}")
    print(f"  Gold purchases: {len(gold_purchases)}")
    print(f"  Final gold units: {gold_units:.2f}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
        'protection_cycles': protection_cycles,
        'gold_purchases': gold_purchases,
        'final_gold_units': gold_units,
    }


# ============================================================================
# METRICS
# ============================================================================

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

    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}

    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100

    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()

    return {
        'initial': initial,
        'final_value': final_value,
        'total_return': (final_value - initial) / initial,
        'years': years,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'avg_trade': avg_trade,
        'trades': len(trades_df),
        'exit_reasons': exit_reasons,
        'stop_events': len(stop_df),
        'protection_days': protection_days,
        'protection_pct': protection_pct,
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    price_data = load_data_parquet()
    if not price_data:
        print("ERROR: No data. Exiting.")
        exit(1)
    print(f"Symbols: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY: {len(spy_data)} days")

    gold_data = download_gold_futures()
    print(f"Gold Futures: {len(gold_data)} days")

    cash_yield_daily = download_cash_yield()

    print("\n--- Computing Annual Top-40 ---")
    annual_universe = compute_annual_top40(price_data)

    results = run_backtest(price_data, annual_universe, spy_data, gold_data, cash_yield_daily)
    metrics = calculate_metrics(results)

    # Results
    print("\n" + "=" * 80)
    print("RESULTS — EXPERIMENT #36b: 1% GOLD ACCUMULATION")
    print("=" * 80)

    print(f"\n--- Performance ---")
    print(f"Initial capital:        ${metrics['initial']:>15,.0f}")
    print(f"Final value:            ${metrics['final_value']:>15,.2f}")
    print(f"CAGR:                   {metrics['cagr']:>15.2%}")
    print(f"Volatility (annual):    {metrics['volatility']:>15.2%}")

    print(f"\n--- Risk-Adjusted ---")
    print(f"Sharpe ratio:           {metrics['sharpe']:>15.2f}")
    print(f"Sortino ratio:          {metrics['sortino']:>15.2f}")
    print(f"Calmar ratio:           {metrics['calmar']:>15.2f}")
    print(f"Max drawdown:           {metrics['max_drawdown']:>15.2%}")

    print(f"\n--- Trading ---")
    print(f"Trades executed:        {metrics['trades']:>15,}")
    print(f"Win rate:               {metrics['win_rate']:>15.2%}")
    print(f"Stop loss events:       {metrics['stop_events']:>15,}")
    print(f"Protection days:        {metrics['protection_days']:>15,} ({metrics['protection_pct']:.1f}%)")

    print(f"\n--- Gold Accumulation ---")
    print(f"Gold purchases:         {len(results['gold_purchases']):>15,}")
    print(f"Final gold units:       {results['final_gold_units']:>15.2f}")

    if len(gold_data) > 0 and results['final_gold_units'] > 0:
        last_gold_price = float(gold_data['Close'].iloc[-1])
        gold_final_value = results['final_gold_units'] * last_gold_price
        total_cost = sum(p['cost'] for p in results['gold_purchases'])
        gold_return = (gold_final_value - total_cost) / total_cost * 100 if total_cost > 0 else 0
        gold_pct_portfolio = gold_final_value / metrics['final_value'] * 100

        print(f"Gold total cost:        ${total_cost:>15,.2f}")
        print(f"Gold final value:       ${gold_final_value:>15,.2f} (@ ${last_gold_price:.2f})")
        print(f"Gold return:            {gold_return:>14.1f}%")
        print(f"Gold % of portfolio:    {gold_pct_portfolio:>14.1f}%")

        print(f"\n  Purchase history:")
        for p in results['gold_purchases']:
            current_val = p['units'] * last_gold_price
            ret = (current_val - p['cost']) / p['cost'] * 100
            print(f"    {p['date'].strftime('%Y-%m-%d')}: {p['units']:.2f} units @ ${p['price']:.2f} = ${p['cost']:,.0f} -> ${current_val:,.0f} ({ret:+.1f}%)")

    # Comparison
    print("\n" + "=" * 80)
    print("COMPARISON vs COMPASS v8.2 BASELINE")
    print("=" * 80)

    baseline_cagr = 0.1856
    baseline_sharpe = 0.90
    baseline_maxdd = -0.269
    baseline_final = 8_430_000

    print(f"{'Metric':<25} {'Baseline':>14} {'Gold 1%':>14} {'Delta':>14}")
    print("-" * 70)
    print(f"{'CAGR':<25} {baseline_cagr:>13.2%} {metrics['cagr']:>13.2%} {metrics['cagr']-baseline_cagr:>+13.2%}")
    print(f"{'Sharpe':<25} {baseline_sharpe:>14.2f} {metrics['sharpe']:>14.2f} {metrics['sharpe']-baseline_sharpe:>+14.2f}")
    print(f"{'Max Drawdown':<25} {baseline_maxdd:>13.1%} {metrics['max_drawdown']:>13.1%} {metrics['max_drawdown']-baseline_maxdd:>+13.1%}")
    print(f"{'Final Value':<25} ${baseline_final:>13,.0f} ${metrics['final_value']:>13,.0f} ${metrics['final_value']-baseline_final:>+13,.0f}")

    # Verdict
    print("\n" + "=" * 80)
    if metrics['cagr'] >= baseline_cagr:
        print("VERDICT: PASSED — Gold accumulation improves or matches baseline")
    else:
        delta_cagr = (metrics['cagr'] - baseline_cagr) * 100
        print(f"VERDICT: FAILED — Gold accumulation costs {abs(delta_cagr):.2f}% CAGR")
    print("=" * 80)
