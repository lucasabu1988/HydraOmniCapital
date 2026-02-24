"""
Experiment #36 — Gold Allocation Optimization
===============================================
Sweep gold allocation % (0.5% to 10%) to find optimal.
Reuses the exp36 backtest engine with parameterized allocation.
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
# COMPASS v8.2 PARAMETERS (LOCKED)
# ============================================================================

TOP_N = 40
MIN_AGE_DAYS = 63
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
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

# ============================================================================
# DATA FUNCTIONS
# ============================================================================

def load_data_parquet():
    cache_dir = 'data_cache_parquet'
    manifest_file = os.path.join(cache_dir, f'manifest_{START_DATE}_{END_DATE}.txt')
    if not os.path.exists(manifest_file):
        return {}
    data = {}
    for symbol in BROAD_POOL:
        pfile = os.path.join(cache_dir, f'{symbol}.parquet')
        if os.path.exists(pfile):
            df = pd.read_parquet(pfile)
            if not df.empty and len(df) > 100:
                data[symbol] = df
    return data


def download_gold_futures():
    cache_file = f'data_cache/GC_F_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    df = yf.download('GC=F', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def download_spy():
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def download_cash_yield():
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
        if sym_idx < MOMENTUM_LOOKBACK + 5:
            continue
        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - 5]
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
# BACKTEST (parameterized gold allocation)
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data, gold_data, regime,
                 all_dates, first_date, gold_first_date, cash_yield_daily,
                 gold_pct):
    """Run COMPASS backtest with parameterized gold allocation."""

    cash = float(INITIAL_CAPITAL)
    positions = {}
    gold_units = 0.0
    portfolio_values = []
    trades = []
    stop_events = []

    peak_value = float(INITIAL_CAPITAL)
    in_protection_mode = False
    protection_stage = 0
    stop_loss_day_index = None
    post_stop_base = None
    current_year = None

    for i, date in enumerate(all_dates):
        if date.year != current_year:
            current_year = date.year

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        gold_price = None
        if date in gold_data.index:
            gold_price = float(gold_data.loc[date, 'Close'])

        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price
        if gold_price and gold_price > 0 and gold_units > 0:
            portfolio_value += gold_units * gold_price

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

            # Buy gold
            if gold_price and gold_price > 0 and date >= gold_first_date and gold_pct > 0:
                gold_allocation = portfolio_value * gold_pct
                gold_buy_units = gold_allocation / gold_price
                commission = gold_buy_units * COMMISSION_PER_SHARE
                if gold_allocation + commission <= cash:
                    gold_units += gold_buy_units
                    cash -= (gold_allocation + commission)

            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i
            post_stop_base = cash

        is_risk_on = True
        if date in regime.index:
            is_risk_on = bool(regime.loc[date])

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
                    position_value = min(effective_capital * weight, cash * 0.40)
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
            'date': date, 'value': portfolio_value,
            'drawdown': drawdown, 'in_protection': in_protection_mode,
        })

    pv_df = pd.DataFrame(portfolio_values)
    final_value = pv_df['value'].iloc[-1]
    years = len(pv_df) / 252
    cagr = (final_value / INITIAL_CAPITAL) ** (1 / years) - 1

    returns = pv_df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)
    max_dd = pv_df['drawdown'].min()
    sharpe = cagr / volatility if volatility > 0 else 0

    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0

    protection_days = pv_df['in_protection'].sum()

    # Gold value at end
    last_gold_price = float(gold_data['Close'].iloc[-1]) if len(gold_data) > 0 else 0
    gold_final_value = gold_units * last_gold_price

    return {
        'cagr': cagr,
        'sharpe': sharpe,
        'sortino': sortino,
        'max_dd': max_dd,
        'final_value': final_value,
        'volatility': volatility,
        'stops': len(stop_events),
        'trades': len(trades),
        'protection_days': protection_days,
        'gold_units': gold_units,
        'gold_final_value': gold_final_value,
        'gold_pct_portfolio': gold_final_value / final_value * 100 if final_value > 0 else 0,
    }


# ============================================================================
# MAIN — SWEEP
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("EXPERIMENT #36 — GOLD ALLOCATION OPTIMIZATION")
    print("Sweep: 0% (baseline), 0.5%, 1%, 2%, 3%, 5%, 7%, 10%")
    print("=" * 80)

    # Load data once
    print("\nLoading data...")
    price_data = load_data_parquet()
    spy_data = download_spy()
    gold_data = download_gold_futures()
    cash_yield_daily = download_cash_yield()
    annual_universe = compute_annual_top40(price_data)

    print(f"  {len(price_data)} symbols, SPY {len(spy_data)}d, Gold {len(gold_data)}d")

    # Precompute shared state
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]
    regime = compute_regime(spy_data)
    gold_first_date = gold_data.index[0] if len(gold_data) > 0 else pd.Timestamp('2099-01-01')

    # Sweep
    allocations = [0.0, 0.001, 0.002, 0.003, 0.00333, 0.004, 0.005]
    results = []

    for pct in allocations:
        label = f"{pct*100:.1f}%"
        print(f"\n  Running gold_pct={label}...", end=" ", flush=True)

        r = run_backtest(price_data, annual_universe, spy_data, gold_data,
                         regime, all_dates, first_date, gold_first_date,
                         cash_yield_daily, gold_pct=pct)

        results.append({
            'pct': pct,
            'label': label,
            **r
        })
        print(f"CAGR={r['cagr']:.2%} | Sharpe={r['sharpe']:.2f} | MaxDD={r['max_dd']:.1%} | Final=${r['final_value']:,.0f} | Gold={r['gold_pct_portfolio']:.1f}%")

    # Summary table
    print("\n" + "=" * 100)
    print("GOLD ALLOCATION SWEEP — RESULTS")
    print("=" * 100)
    print(f"{'Alloc':>7} {'CAGR':>8} {'Sharpe':>8} {'Sortino':>8} {'MaxDD':>8} {'Final Value':>14} {'Gold%':>7} {'Gold$':>12} {'vs Base':>10}")
    print("-" * 100)

    baseline_cagr = results[0]['cagr']
    baseline_final = results[0]['final_value']

    for r in results:
        delta_cagr = r['cagr'] - baseline_cagr
        delta_final = r['final_value'] - baseline_final
        marker = " <-- BEST" if r['cagr'] == max(x['cagr'] for x in results) else ""
        print(f"{r['label']:>7} {r['cagr']:>7.2%} {r['sharpe']:>8.2f} {r['sortino']:>8.2f} "
              f"{r['max_dd']:>7.1%} ${r['final_value']:>13,.0f} {r['gold_pct_portfolio']:>6.1f}% "
              f"${r['gold_final_value']:>11,.0f} {delta_cagr:>+9.2%}{marker}")

    # Find optimal
    best = max(results, key=lambda x: x['cagr'])
    best_sharpe = max(results, key=lambda x: x['sharpe'])

    print(f"\n  Best CAGR:   {best['label']} ({best['cagr']:.2%}, +{(best['cagr']-baseline_cagr)*100:.2f}% vs baseline)")
    print(f"  Best Sharpe: {best_sharpe['label']} ({best_sharpe['sharpe']:.2f})")

    if best['pct'] == 0:
        print("\n  CONCLUSION: No gold allocation beats baseline. Keep COMPASS v8.2 as-is.")
    else:
        print(f"\n  CONCLUSION: Optimal gold = {best['label']} per stop loss event")
        print(f"  This adds +{(best['cagr']-baseline_cagr)*100:.2f}% CAGR with {best['max_dd']:.1%} MaxDD")
