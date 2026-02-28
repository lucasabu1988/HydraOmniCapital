#!/usr/bin/env python3
"""
================================================================================
OMNICAPITAL -- QUANTUM v1.0
High-Frequency Mean Reversion (RSI-2 + Internal Bar Strength)
================================================================================
Backtest aislado para evaluar la propuesta del equipo asesor externo.
Usa el MISMO universo (BROAD_POOL top-40), mismos datos, mismo capital que COMPASS.

Propuesta del asesor:
- Comprar "panico intradiario injustificado" en acciones alcistas
- RSI(2) < 15 + IBS < 0.20 + Close < SMA(5) + SPY > SMA(200)
- Salida: Close > SMA(5) o IBS > 0.80 o -8% stop o 7 dias time stop
- Promesa: Win Rate 65-70%, Sharpe > 1.0, MaxDD -15% a -20%

NOTA: Es esencialmente RATTLESNAKE mejorado. RATTLESNAKE logro 10.51% CAGR
con RSI(5) < 25. QUANTUM usa RSI(2) < 15 + IBS como filtro adicional.
================================================================================
"""

import pandas as pd
import numpy as np
import yfinance as yf
import pickle
import os
import time as time_module
from typing import Dict, List, Optional
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# PARAMETERS
# =============================================================================

SEED = 666
np.random.seed(SEED)

# Universe -- SAME as COMPASS
TOP_N = 40
MIN_AGE_DAYS = 63

# Regime
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3

# Entry signal (advisory team proposal)
RSI_PERIOD = 2              # RSI(2) -- ultra-short-term
RSI_THRESHOLD = 15          # Entry when RSI(2) < 15
IBS_THRESHOLD_ENTRY = 0.20  # Close in bottom 20% of daily range
SMA_FAST = 5                # Close must be below SMA(5)

# Exit signals
IBS_THRESHOLD_EXIT = 0.80   # Exit if close in top 80% of range
HARD_STOP_LOSS = -0.08      # -8% catastrophe stop
TIME_STOP_DAYS = 7          # Max hold 7 trading days

# Portfolio
INITIAL_CAPITAL = 100_000
MAX_POSITIONS = 5           # Max simultaneous
POSITION_SIZE = 0.20        # 20% per position (equal weight)
NUM_POS_RISK_OFF = 2        # Fewer in risk-off

# Costs (same as COMPASS)
COMMISSION_PER_SHARE = 0.001
SLIPPAGE_BPS = 2            # 2bps per trade
CASH_YIELD_RATE = 0.035     # 3.5% annual on cash

# Data
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# Broad pool -- IDENTICAL to COMPASS
BROAD_POOL = [
    # Technology (25)
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'AMD',
    'INTC', 'CSCO', 'IBM', 'TXN', 'QCOM', 'ORCL', 'ACN', 'NOW', 'INTU',
    'AMAT', 'MU', 'LRCX', 'SNPS', 'CDNS', 'KLAC', 'MRVL',
    # Financials (18)
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
    'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG',
    # Healthcare (18)
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'AMGN', 'BMY', 'MDT', 'ISRG', 'SYK', 'GILD', 'REGN', 'VRTX', 'BIIB',
    # Consumer (20)
    'AMZN', 'TSLA', 'WMT', 'HD', 'PG', 'COST', 'KO', 'PEP', 'NKE',
    'MCD', 'DIS', 'SBUX', 'TGT', 'LOW', 'CL', 'KMB', 'GIS', 'EL',
    'MO', 'PM',
    # Energy (9)
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'PSX', 'VLO',
    # Industrials (14)
    'GE', 'CAT', 'BA', 'HON', 'UNP', 'RTX', 'LMT', 'DE', 'UPS', 'FDX',
    'MMM', 'GD', 'NOC', 'EMR',
    # Utilities & Real Estate (5)
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    # Telecom (4)
    'VZ', 'T', 'TMUS', 'CMCSA',
]


# =============================================================================
# DATA FUNCTIONS (reuse COMPASS cache)
# =============================================================================

def download_broad_pool() -> Dict[str, pd.DataFrame]:
    """Download/load cached OHLCV data for the broad pool."""
    cache_file = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading broad pool data...")
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            print("[Cache] Failed to load, re-downloading...")

    print(f"[Download] Downloading {len(BROAD_POOL)} symbols...")
    data = {}
    failed = []

    for i, symbol in enumerate(BROAD_POOL):
        try:
            df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[symbol] = df
                if (i + 1) % 20 == 0:
                    print(f"  [{i+1}/{len(BROAD_POOL)}] Downloaded {len(data)} symbols...")
            else:
                failed.append(symbol)
        except Exception:
            failed.append(symbol)

    print(f"[Download] {len(data)} symbols valid, {len(failed)} failed")
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)
    return data


def download_spy() -> pd.DataFrame:
    """Download SPY data for regime filter."""
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


def compute_annual_top40(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    """For each year, compute top-40 by avg daily dollar volume (prior year)."""
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}
    for year in years:
        if year == years[0]:
            ranking_end = pd.Timestamp(f'{year}-02-01',
                tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01',
                tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        else:
            ranking_end = pd.Timestamp(f'{year}-01-01',
                tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01',
                tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)

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


# =============================================================================
# INDICATORS
# =============================================================================

def compute_rsi(close: pd.Series, period: int = 2) -> pd.Series:
    """Wilder's RSI."""
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ema_up = up.ewm(com=period - 1, adjust=False).mean()
    ema_down = down.ewm(com=period - 1, adjust=False).mean()
    rs = ema_up / ema_down
    rsi = 100 - (100 / (1 + rs))
    return rsi.fillna(50)


def compute_ibs(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Internal Bar Strength: (Close - Low) / (High - Low)."""
    hl_range = high - low
    hl_range = hl_range.replace(0, np.nan)
    ibs = (close - low) / hl_range
    return ibs.fillna(0.5)


def precompute_indicators(price_data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Pre-compute RSI(2), IBS, SMA(5) for all stocks."""
    indicators = {}
    for sym, df in price_data.items():
        ind = pd.DataFrame(index=df.index)
        ind['close'] = df['Close']
        ind['high'] = df['High']
        ind['low'] = df['Low']
        ind['rsi2'] = compute_rsi(df['Close'], RSI_PERIOD)
        ind['ibs'] = compute_ibs(df['High'], df['Low'], df['Close'])
        ind['sma5'] = df['Close'].rolling(SMA_FAST).mean()
        indicators[sym] = ind
    return indicators


# =============================================================================
# REGIME
# =============================================================================

def compute_regime(spy_data: pd.DataFrame) -> pd.Series:
    """SPY > SMA(200) with confirmation days. True = RISK_ON."""
    spy_close = spy_data['Close']
    sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean()
    raw_signal = spy_close > sma200

    regime = pd.Series(index=spy_close.index, dtype=bool)
    regime.iloc[:REGIME_SMA_PERIOD] = True

    current = True
    count = 0
    for j in range(REGIME_SMA_PERIOD, len(spy_close)):
        if pd.isna(raw_signal.iloc[j]):
            regime.iloc[j] = current
            continue
        signal = bool(raw_signal.iloc[j])
        if signal != current:
            count += 1
            if count >= REGIME_CONFIRM_DAYS:
                current = signal
                count = 0
        else:
            count = 0
        regime.iloc[j] = current

    return regime


# =============================================================================
# BACKTEST
# =============================================================================

def run_backtest(price_data: Dict[str, pd.DataFrame],
                 annual_universe: Dict[int, List[str]],
                 spy_data: pd.DataFrame,
                 indicators: Dict[str, pd.DataFrame]) -> Dict:
    """Day-by-day QUANTUM mean-reversion simulation."""

    # Sorted trading dates
    all_dates_set = set()
    for df in price_data.values():
        all_dates_set.update(df.index)
    all_dates = sorted(list(all_dates_set))

    # First date each symbol appears
    first_date = {}
    for sym, df in price_data.items():
        first_date[sym] = df.index[0]

    # Regime series
    regime = compute_regime(spy_data)

    # State
    cash = float(INITIAL_CAPITAL)
    positions = []  # list of dicts
    portfolio_values = []
    trades = []
    risk_on_days = 0
    risk_off_days = 0

    min_history = REGIME_SMA_PERIOD + 10
    t_start = time_module.time()

    print(f"\n[Backtest] {len(all_dates)} trading days: "
          f"{all_dates[0].date()} -> {all_dates[-1].date()}")

    for i, date in enumerate(all_dates):
        year = date.year

        # --- Tradeable universe ---
        universe = annual_universe.get(year, [])
        tradeable = []
        for sym in universe:
            if sym in price_data and sym in first_date:
                age = (date - first_date[sym]).days
                if age >= MIN_AGE_DAYS and date in price_data[sym].index:
                    tradeable.append(sym)

        # --- Portfolio value ---
        port_val = cash
        for pos in positions:
            sym = pos['symbol']
            if sym in price_data and date in price_data[sym].index:
                price = float(price_data[sym].loc[date, 'Close'])
            else:
                price = pos['entry_price']
            port_val += pos['shares'] * price

        portfolio_values.append({
            'date': date,
            'value': port_val,
            'cash': cash,
            'positions': len(positions),
        })

        if i < min_history:
            continue

        # --- Cash yield ---
        if cash > 0:
            cash += cash * (CASH_YIELD_RATE / 252.0)

        # --- Regime ---
        is_risk_on = True
        if date in regime.index:
            is_risk_on = bool(regime.loc[date])

        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # --- EXIT existing positions ---
        for pos in list(positions):
            sym = pos['symbol']
            if sym not in indicators or date not in indicators[sym].index:
                continue

            ind = indicators[sym].loc[date]
            current_price = float(ind['close'])
            entry_price = pos['entry_price']
            pnl_pct = (current_price / entry_price) - 1.0
            hold_days = i - pos['entry_idx']

            exit_reason = None

            # 1. Mean reverted: Close > SMA(5)
            if not pd.isna(ind['sma5']) and current_price > ind['sma5']:
                exit_reason = 'mean_reverted_sma'
            # 2. Strong close: IBS > 0.80
            elif not pd.isna(ind['ibs']) and ind['ibs'] > IBS_THRESHOLD_EXIT:
                exit_reason = 'mean_reverted_ibs'
            # 3. Time stop
            elif hold_days >= TIME_STOP_DAYS:
                exit_reason = 'time_stop'
            # 4. Hard stop loss
            elif pnl_pct <= HARD_STOP_LOSS:
                exit_reason = 'hard_stop'

            if exit_reason:
                # Sell
                proceeds = pos['shares'] * current_price
                comm = pos['shares'] * COMMISSION_PER_SHARE
                slip = proceeds * SLIPPAGE_BPS / 10000.0
                cash += proceeds - comm - slip

                trades.append({
                    'symbol': sym,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'entry_price': entry_price,
                    'exit_price': current_price,
                    'shares': pos['shares'],
                    'pnl_pct': pnl_pct,
                    'pnl_dollar': (current_price - entry_price) * pos['shares'] - comm - slip - pos['entry_cost'],
                    'hold_days': hold_days,
                    'exit_reason': exit_reason,
                })
                positions.remove(pos)

        # --- ENTRY (only if risk-on and slots available) ---
        max_pos = MAX_POSITIONS if is_risk_on else NUM_POS_RISK_OFF
        open_slots = max_pos - len(positions)

        if open_slots > 0 and is_risk_on:
            held_symbols = {p['symbol'] for p in positions}
            candidates = []

            for sym in tradeable:
                if sym in held_symbols:
                    continue
                if sym not in indicators:
                    continue
                ind_df = indicators[sym]
                if date not in ind_df.index:
                    continue

                ind = ind_df.loc[date]
                close = float(ind['close'])
                rsi2 = ind['rsi2']
                ibs = ind['ibs']
                sma5 = ind['sma5']

                if pd.isna(rsi2) or pd.isna(ibs) or pd.isna(sma5):
                    continue

                # QUANTUM entry criteria:
                # 1. Close < SMA(5) (short-term downtrend)
                # 2. RSI(2) < 15 (extreme oversold)
                # 3. IBS < 0.20 (closed near bottom of range)
                if close < sma5 and rsi2 < RSI_THRESHOLD and ibs < IBS_THRESHOLD_ENTRY:
                    candidates.append((sym, float(rsi2), close))

            # Rank by lowest RSI (most oversold first)
            candidates.sort(key=lambda x: x[1])

            for sym, rsi_val, buy_price in candidates[:open_slots]:
                if buy_price <= 0:
                    continue

                target_val = port_val * POSITION_SIZE
                shares = int(target_val / buy_price)
                if shares <= 0:
                    continue

                cost = shares * buy_price
                comm = shares * COMMISSION_PER_SHARE
                slip = cost * SLIPPAGE_BPS / 10000.0
                total_entry_cost = comm + slip

                if cost + total_entry_cost > cash:
                    continue

                cash -= cost + total_entry_cost
                positions.append({
                    'symbol': sym,
                    'entry_price': buy_price,
                    'entry_date': date,
                    'entry_idx': i,
                    'shares': shares,
                    'entry_cost': total_entry_cost,
                })

        # Annual progress
        if i > 0 and i % 252 == 0:
            elapsed = time_module.time() - t_start
            print(f"  Year {i // 252:>2}: ${port_val:>12,.0f} | "
                  f"Pos: {len(positions)} | Cash: ${cash:>10,.0f} | "
                  f"Trades: {len(trades):>4} | Regime: {'ON' if is_risk_on else 'OFF'} | "
                  f"{elapsed:.1f}s")

    # Close remaining at end
    for pos in list(positions):
        sym = pos['symbol']
        last_date = all_dates[-1]
        if sym in price_data and last_date in price_data[sym].index:
            price = float(price_data[sym].loc[last_date, 'Close'])
        else:
            price = pos['entry_price']
        pnl_pct = (price / pos['entry_price']) - 1.0
        proceeds = pos['shares'] * price
        comm = pos['shares'] * COMMISSION_PER_SHARE
        slip = proceeds * SLIPPAGE_BPS / 10000.0
        cash += proceeds - comm - slip
        trades.append({
            'symbol': sym,
            'entry_date': pos['entry_date'],
            'exit_date': last_date,
            'entry_price': pos['entry_price'],
            'exit_price': price,
            'shares': pos['shares'],
            'pnl_pct': pnl_pct,
            'pnl_dollar': (price - pos['entry_price']) * pos['shares'] - comm - slip - pos['entry_cost'],
            'hold_days': (last_date - pos['entry_date']).days,
            'exit_reason': 'backtest_end',
        })
    positions = []

    elapsed = time_module.time() - t_start
    print(f"\n[Backtest] Completed in {elapsed:.1f}s | {len(trades)} total trades")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
    }


# =============================================================================
# METRICS
# =============================================================================

def calculate_metrics(results: Dict) -> Dict:
    """Calculate performance metrics (same formula as COMPASS)."""
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']

    initial = INITIAL_CAPITAL
    final_value = df['value'].iloc[-1]
    years = len(df) / 252.0
    cagr = (final_value / initial) ** (1.0 / years) - 1.0

    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)

    cummax = df['value'].cummax()
    drawdown = (df['value'] / cummax) - 1.0
    max_dd = drawdown.min()
    max_dd_date = drawdown.idxmin()

    sharpe = cagr / volatility if volatility > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0

    if len(trades_df) > 0 and 'pnl_pct' in trades_df.columns:
        win_rate = (trades_df['pnl_pct'] > 0).mean()
        avg_trade = trades_df['pnl_dollar'].mean()
        avg_winner_pct = trades_df.loc[trades_df['pnl_pct'] > 0, 'pnl_pct'].mean() \
            if (trades_df['pnl_pct'] > 0).any() else 0
        avg_loser_pct = trades_df.loc[trades_df['pnl_pct'] < 0, 'pnl_pct'].mean() \
            if (trades_df['pnl_pct'] < 0).any() else 0
        avg_winner_dollar = trades_df.loc[trades_df['pnl_dollar'] > 0, 'pnl_dollar'].mean() \
            if (trades_df['pnl_dollar'] > 0).any() else 0
        avg_loser_dollar = trades_df.loc[trades_df['pnl_dollar'] < 0, 'pnl_dollar'].mean() \
            if (trades_df['pnl_dollar'] < 0).any() else 0
        exit_reasons = trades_df['exit_reason'].value_counts().to_dict()
        avg_hold = trades_df['hold_days'].mean()
        total_trades = len(trades_df)
    else:
        win_rate = avg_trade = avg_winner_pct = avg_loser_pct = 0
        avg_winner_dollar = avg_loser_dollar = avg_hold = 0
        exit_reasons = {}
        total_trades = 0

    avg_positions = df['positions'].mean()

    # Days in market vs cash
    days_with_positions = (df['positions'] > 0).sum()
    pct_time_invested = days_with_positions / len(df) * 100

    # Annual returns
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
        'max_dd_date': max_dd_date,
        'win_rate': win_rate,
        'avg_trade_dollar': avg_trade,
        'avg_winner_pct': avg_winner_pct,
        'avg_loser_pct': avg_loser_pct,
        'avg_winner_dollar': avg_winner_dollar,
        'avg_loser_dollar': avg_loser_dollar,
        'total_trades': total_trades,
        'exit_reasons': exit_reasons,
        'avg_hold_days': avg_hold,
        'avg_positions': avg_positions,
        'pct_time_invested': pct_time_invested,
        'risk_on_days': results['risk_on_days'],
        'risk_off_days': results['risk_off_days'],
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
    }


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("QUANTUM v1.0 -- High-Frequency Mean Reversion (RSI-2 + IBS)")
    print("Advisory Team Proposal Backtest")
    print("=" * 80)
    print(f"\nUniverse: BROAD_POOL ({len(BROAD_POOL)} stocks) -> Top-{TOP_N} annual rotation")
    print(f"Entry: RSI({RSI_PERIOD})<{RSI_THRESHOLD} + IBS<{IBS_THRESHOLD_ENTRY} + "
          f"Close<SMA({SMA_FAST}) + SPY>SMA({REGIME_SMA_PERIOD})")
    print(f"Exit: Close>SMA({SMA_FAST}) | IBS>{IBS_THRESHOLD_EXIT} | "
          f"Stop {HARD_STOP_LOSS:.0%} | Time {TIME_STOP_DAYS}d")
    print(f"Positions: {MAX_POSITIONS} max | Size: {POSITION_SIZE:.0%} each | "
          f"Costs: {SLIPPAGE_BPS}bps + ${COMMISSION_PER_SHARE}/sh")
    print()

    # 1. Data
    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")

    spy_data = download_spy()

    # 2. Annual top-40
    print("\n--- Computing Annual Top-40 ---")
    annual_universe = compute_annual_top40(price_data)
    print(f"  {len(annual_universe)} years computed")

    # 3. Pre-compute indicators
    print("\n--- Pre-computing indicators (RSI-2, IBS, SMA-5) ---")
    indicators = precompute_indicators(price_data)
    print(f"  {len(indicators)} stocks processed")

    # 4. Run backtest
    results = run_backtest(price_data, annual_universe, spy_data, indicators)

    # 5. Calculate metrics
    metrics = calculate_metrics(results)

    # 6. Print results
    print("\n" + "=" * 80)
    print("RESULTS -- QUANTUM v1.0 (High-Frequency Mean Reversion)")
    print("=" * 80)

    print(f"\n  PERFORMANCE")
    print(f"  {'-' * 55}")
    print(f"  {'Initial Capital':<30} ${metrics['initial']:>16,}")
    print(f"  {'Final Value':<30} ${metrics['final_value']:>16,.0f}")
    print(f"  {'Total Return':<30} {metrics['total_return']:>16.2%}")
    print(f"  {'CAGR':<30} {metrics['cagr']:>16.2%}")
    print(f"  {'Period':<30} {metrics['years']:>15.1f}y")

    print(f"\n  RISK-ADJUSTED")
    print(f"  {'-' * 55}")
    print(f"  {'Volatility (ann.)':<30} {metrics['volatility']:>16.2%}")
    print(f"  {'Sharpe Ratio':<30} {metrics['sharpe']:>16.3f}")
    print(f"  {'Sortino Ratio':<30} {metrics['sortino']:>16.3f}")
    print(f"  {'Calmar Ratio':<30} {metrics['calmar']:>16.3f}")
    print(f"  {'Max Drawdown':<30} {metrics['max_drawdown']:>16.2%}")

    print(f"\n  TRADING")
    print(f"  {'-' * 55}")
    print(f"  {'Total Trades':<30} {metrics['total_trades']:>16}")
    print(f"  {'Win Rate':<30} {metrics['win_rate']:>16.1%}")
    print(f"  {'Avg Trade $':<30} ${metrics['avg_trade_dollar']:>15,.2f}")
    print(f"  {'Avg Winner':<30} {metrics['avg_winner_pct']:>16.2%}")
    print(f"  {'Avg Loser':<30} {metrics['avg_loser_pct']:>16.2%}")
    print(f"  {'Avg Hold Days':<30} {metrics['avg_hold_days']:>16.1f}")
    print(f"  {'% Time Invested':<30} {metrics['pct_time_invested']:>15.1f}%")
    print(f"  {'Avg Active Positions':<30} {metrics['avg_positions']:>16.1f}")

    # Payoff ratio
    if metrics['avg_loser_pct'] != 0:
        payoff = abs(metrics['avg_winner_pct'] / metrics['avg_loser_pct'])
        expectancy = (metrics['win_rate'] * metrics['avg_winner_pct'] +
                      (1 - metrics['win_rate']) * metrics['avg_loser_pct'])
        print(f"  {'Payoff Ratio':<30} {payoff:>16.2f}")
        print(f"  {'Expectancy per Trade':<30} {expectancy:>16.3%}")

    print(f"\n  EXIT REASONS")
    print(f"  {'-' * 55}")
    for reason, count in sorted(metrics['exit_reasons'].items(),
                                key=lambda x: x[1], reverse=True):
        pct = count / max(1, metrics['total_trades']) * 100
        print(f"  {reason:<30} {count:>8}  ({pct:>5.1f}%)")

    print(f"\n  MARKET EXPOSURE")
    print(f"  {'-' * 55}")
    total_regime = metrics['risk_on_days'] + metrics['risk_off_days']
    print(f"  {'Risk-ON days':<30} {metrics['risk_on_days']:>10}  "
          f"({metrics['risk_on_days']/max(1,total_regime)*100:.1f}%)")
    print(f"  {'Risk-OFF days':<30} {metrics['risk_off_days']:>10}  "
          f"({metrics['risk_off_days']/max(1,total_regime)*100:.1f}%)")

    # Annual returns
    print(f"\n  ANNUAL RETURNS")
    print(f"  {'-' * 35}")
    for yr, ret in metrics['annual_returns'].items():
        marker = " <--" if ret == metrics['best_year'] or ret == metrics['worst_year'] else ""
        print(f"  {yr.year:<8} {ret:>10.2%}{marker}")

    # 7. Head-to-head vs COMPASS vs RATTLESNAKE
    print("\n" + "=" * 80)
    print("HEAD-TO-HEAD: QUANTUM vs COMPASS vs RATTLESNAKE")
    print("=" * 80)
    print(f"\n  {'METRIC':<24} {'QUANTUM':>12} {'COMPASS(r)':>12} {'RATTLE':>12}")
    print(f"  {'-' * 60}")
    print(f"  {'CAGR':<24} {metrics['cagr']:>11.2%} {'13.52%':>12} {'10.51%':>12}")
    print(f"  {'Sharpe':<24} {metrics['sharpe']:>12.3f} {'0.658':>12} {'0.74':>12}")
    print(f"  {'Max Drawdown':<24} {metrics['max_drawdown']:>11.2%} {'-30.3%':>12} {'-18.7%':>12}")
    print(f"  {'Volatility':<24} {metrics['volatility']:>11.2%} {'20.7%':>12} {'~8%':>12}")
    print(f"  {'Win Rate':<24} {metrics['win_rate']:>11.1%} {'55.2%':>12} {'63.0%':>12}")
    print(f"  {'Total Trades':<24} {metrics['total_trades']:>12} {'5,445':>12} {'~900':>12}")
    print(f"  {'$100K -> $':<24} {metrics['final_value']:>11,.0f} {'$4,425K':>12} {'$1,250K':>12}")
    print(f"  {'Strategy':<24} {'MR RSI+IBS':>12} {'Momentum':>12} {'MR RSI':>12}")
    print(f"  {'% Time Invested':<24} {metrics['pct_time_invested']:>10.0f}% {'~73%':>12} {'~15%':>12}")

    print(f"\n  VERDICT:")
    if metrics['cagr'] > 0.1566:
        print(f"  QUANTUM BEATS COMPASS realistic ({metrics['cagr']:.2%} vs 15.66%)")
        if metrics['sharpe'] > 0.758:
            print(f"  AND has better Sharpe ({metrics['sharpe']:.3f} vs 0.758)")
        if metrics['max_drawdown'] > -0.303:
            print(f"  AND has better MaxDD ({metrics['max_drawdown']:.2%} vs -30.3%)")
    elif metrics['cagr'] > 0.1051:
        print(f"  QUANTUM beats RATTLESNAKE ({metrics['cagr']:.2%} vs 10.51%) "
              f"but does NOT beat COMPASS")
    elif metrics['cagr'] > 0.05:
        print(f"  QUANTUM has modest returns ({metrics['cagr']:.2%}) -- "
              f"no better than RATTLESNAKE or COMPASS")
    else:
        print(f"  QUANTUM FAILS ({metrics['cagr']:.2%} CAGR)")
        print(f"  Advisory team promises of Win Rate 65-70% and Sharpe > 1.0 NOT delivered")

    # Advisory team claims check
    print(f"\n  ADVISORY TEAM CLAIMS CHECK:")
    print(f"  {'-' * 55}")
    wr_ok = metrics['win_rate'] >= 0.65
    sh_ok = metrics['sharpe'] >= 1.0
    dd_ok = metrics['max_drawdown'] >= -0.20
    print(f"  {'Win Rate 65-70%':<30} {'CONFIRMED' if wr_ok else 'FAILED':>12}  "
          f"(actual: {metrics['win_rate']:.1%})")
    print(f"  {'Sharpe > 1.0':<30} {'CONFIRMED' if sh_ok else 'FAILED':>12}  "
          f"(actual: {metrics['sharpe']:.3f})")
    print(f"  {'MaxDD -15% to -20%':<30} {'CONFIRMED' if dd_ok else 'FAILED':>12}  "
          f"(actual: {metrics['max_drawdown']:.2%})")

    # 8. Save CSVs
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/quantum_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/quantum_trades.csv', index=False)
    print(f"\n  Saved: backtests/quantum_daily.csv ({len(results['portfolio_values'])} rows)")
    print(f"  Saved: backtests/quantum_trades.csv ({metrics['total_trades']} trades)")

    # 9. Save pickle
    with open('results_quantum_v1.pkl', 'wb') as f:
        pickle.dump({
            'params': {
                'rsi_period': RSI_PERIOD,
                'rsi_threshold': RSI_THRESHOLD,
                'ibs_entry': IBS_THRESHOLD_ENTRY,
                'ibs_exit': IBS_THRESHOLD_EXIT,
                'sma_fast': SMA_FAST,
                'hard_stop': HARD_STOP_LOSS,
                'time_stop': TIME_STOP_DAYS,
                'max_positions': MAX_POSITIONS,
                'position_size': POSITION_SIZE,
                'slippage_bps': SLIPPAGE_BPS,
                'commission': COMMISSION_PER_SHARE,
                'cash_yield': CASH_YIELD_RATE,
            },
            'metrics': {k: v for k, v in metrics.items()
                        if k not in ('annual_returns', 'max_dd_date')},
            'portfolio_values': results['portfolio_values'],
            'trades': results['trades'],
        }, f)
    print(f"  Saved: results_quantum_v1.pkl")

    print("\n" + "=" * 80)
    print(f"QUANTUM v1.0 COMPLETE | {metrics['cagr']:.2%} CAGR | "
          f"{metrics['sharpe']:.3f} Sharpe | {metrics['max_drawdown']:.2%} MaxDD")
    print("=" * 80)
