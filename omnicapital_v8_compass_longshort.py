"""
OmniCapital v8.1 COMPASS Long-Short
====================================
Extiende COMPASS v8 con pata short: vende en corto las 10 acciones con peor
ratio Debt/EBITDA del broad pool (excluyendo financials).

- Longs (80%): Cross-sectional momentum top-5 del top-40 (igual que v8)
- Shorts (20%): Top-10 por Debt/EBITDA (ex-financials) de todo el broad pool
- Financials excluidos de shorts (su modelo de deuda es estructural, no distress)
- Backtest limitado al periodo con datos fundamentales reales (~2021-2026)
- Rebalanceo shorts: trimestral (cada 63 trading days)
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETROS
# ============================================================================

# Universe
TOP_N = 40
MIN_AGE_DAYS = 63

# Signal (longs)
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20

# Regime
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3

# Long positions
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5

# Position-level risk (longs)
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03

# Portfolio-level risk
PORTFOLIO_STOP_LOSS = -0.15

# Recovery stages
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126

# Leverage & Vol targeting
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.5
LEVERAGE_MAX = 2.0
VOL_LOOKBACK = 20

# Short selling
SHORT_ALLOCATION = 0.20       # 20% del capital para shorts
LONG_ALLOCATION = 0.80        # 80% del capital para longs
NUM_SHORTS = 10               # Bottom 10 por revenue/debt
SHORT_BORROW_COST = 0.015     # 1.5% anual
SHORT_STOP_LOSS = 0.15        # Cerrar short si sube +15%
SHORT_REBALANCE_DAYS = 63     # Rebalancear cada trimestre

# Costs
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001

# Financials exclusion (for shorts — their high debt is structural, not distress)
FINANCIALS = {
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
    'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG',
}

# Data — periodo limitado a datos fundamentales disponibles
END_DATE = '2026-02-09'
# START_DATE se determina en runtime segun datos fundamentales disponibles

# Broad pool (~113 S&P 500 stocks)
BROAD_POOL = [
    # Technology
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'AMD',
    'INTC', 'CSCO', 'IBM', 'TXN', 'QCOM', 'ORCL', 'ACN', 'NOW', 'INTU',
    'AMAT', 'MU', 'LRCX', 'SNPS', 'CDNS', 'KLAC', 'MRVL',
    # Financials
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
    'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG',
    # Healthcare
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'AMGN', 'BMY', 'MDT', 'ISRG', 'SYK', 'GILD', 'REGN', 'VRTX', 'BIIB',
    # Consumer
    'AMZN', 'TSLA', 'WMT', 'HD', 'PG', 'COST', 'KO', 'PEP', 'NKE',
    'MCD', 'DIS', 'SBUX', 'TGT', 'LOW', 'CL', 'KMB', 'GIS', 'EL',
    'MO', 'PM',
    # Energy
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'PSX', 'VLO',
    # Industrials
    'GE', 'CAT', 'BA', 'HON', 'UNP', 'RTX', 'LMT', 'DE', 'UPS', 'FDX',
    'MMM', 'GD', 'NOC', 'EMR',
    # Utilities & Real Estate
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    # Telecom
    'VZ', 'T', 'TMUS', 'CMCSA',
]

print("=" * 80)
print("OMNICAPITAL v8.1 COMPASS LONG-SHORT")
print("Longs: Momentum top-5 | Shorts: Top-10 Debt/EBITDA (ex-financials)")
print("=" * 80)
print(f"\nBroad pool: {len(BROAD_POOL)} stocks | Top-{TOP_N} annual rotation")
print(f"Capital split: {LONG_ALLOCATION:.0%} longs / {SHORT_ALLOCATION:.0%} shorts")
print(f"Shorts: {NUM_SHORTS} highest Debt/EBITDA (excl {len(FINANCIALS)} financials) | Rebalance: {SHORT_REBALANCE_DAYS}d")
print()


# ============================================================================
# DATA FUNCTIONS
# ============================================================================

def download_broad_pool(start_date: str) -> Dict[str, pd.DataFrame]:
    """Download/load price data for broad pool"""
    cache_file = f'data_cache/broad_pool_{start_date}_{END_DATE}.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading broad pool data...")
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            print("[Cache] Failed, re-downloading...")

    print(f"[Download] Downloading {len(BROAD_POOL)} symbols ({start_date} to {END_DATE})...")
    data = {}
    failed = []

    for i, symbol in enumerate(BROAD_POOL):
        try:
            df = yf.download(symbol, start=start_date, end=END_DATE, progress=False)
            if not df.empty and len(df) > 50:
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


def download_spy(start_date: str) -> pd.DataFrame:
    """Download SPY data for regime filter"""
    # Need extra history for SMA200
    extended_start = str(int(start_date[:4]) - 1) + start_date[4:]
    cache_file = f'data_cache/SPY_{extended_start}_{END_DATE}.csv'

    if os.path.exists(cache_file):
        print("[Cache] Loading SPY data...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)

    print("[Download] Downloading SPY...")
    df = yf.download('SPY', start=extended_start, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def download_fundamentals() -> pd.DataFrame:
    """
    Download Total Debt and EBITDA from yfinance for all non-financial stocks.
    Returns DataFrame with columns: symbol, year, ebitda, total_debt, debt_ebitda
    High Debt/EBITDA = overleveraged = short candidate.
    Financials excluded (their debt model is structural).
    Cached in CSV.
    """
    cache_file = 'data_cache/fundamentals_debt_ebitda.csv'

    if os.path.exists(cache_file):
        print("[Cache] Loading fundamentals (Debt/EBITDA)...")
        return pd.read_csv(cache_file)

    # Exclude financials from fundamental download for shorts
    short_pool = [s for s in BROAD_POOL if s not in FINANCIALS]
    print(f"[Download] Downloading fundamentals for {len(short_pool)} stocks (excl {len(FINANCIALS)} financials)...")
    rows = []

    for i, symbol in enumerate(short_pool):
        try:
            ticker = yf.Ticker(symbol)

            inc = ticker.financials
            bs = ticker.balance_sheet

            if inc is None or bs is None or inc.empty or bs.empty:
                continue

            for col in inc.columns:
                year = col.year

                # Get EBITDA
                ebitda = None
                for label in ['EBITDA', 'Normalized EBITDA']:
                    if label in inc.index:
                        val = inc.loc[label, col]
                        if pd.notna(val) and val > 0:
                            ebitda = float(val)
                            break

                # Get Total Debt
                debt = None
                if col in bs.columns:
                    for label in ['Total Debt', 'Long Term Debt', 'Long Term Debt And Capital Lease Obligation']:
                        if label in bs.index:
                            val = bs.loc[label, col]
                            if pd.notna(val) and val > 0:
                                debt = float(val)
                                break

                if ebitda is not None and debt is not None and ebitda > 0:
                    rows.append({
                        'symbol': symbol,
                        'year': year,
                        'ebitda': ebitda,
                        'total_debt': debt,
                        'debt_ebitda': debt / ebitda  # High = bad
                    })

            if (i + 1) % 20 == 0:
                print(f"  [{i+1}/{len(short_pool)}] Processed {len(rows)} data points...")

        except Exception:
            continue

    df = pd.DataFrame(rows)
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file, index=False)
    print(f"[Fundamentals] {len(df)} data points for {df['symbol'].nunique()} stocks (ex-financials), years {df['year'].min()}-{df['year'].max()}")
    return df


def compute_annual_short_candidates(fund_df: pd.DataFrame) -> Dict[int, List[str]]:
    """
    For each year with fundamental data, select top-10 by Debt/EBITDA ratio.
    High Debt/EBITDA = overleveraged relative to earnings = short candidate.
    Financials already excluded from fund_df.
    """
    annual_shorts = {}

    for year in sorted(fund_df['year'].unique()):
        year_data = fund_df[fund_df['year'] == year].copy()
        year_data = year_data.sort_values('debt_ebitda', ascending=False)  # Highest first

        # Top N by Debt/EBITDA (most leveraged)
        candidates = year_data.head(NUM_SHORTS)['symbol'].tolist()
        if len(candidates) >= 3:
            annual_shorts[year] = candidates
            top_ratios = year_data.head(NUM_SHORTS)['debt_ebitda']
            print(f"  {year}: {len(candidates)} short candidates | "
                  f"Worst: {candidates[:3]} | Debt/EBITDA: {top_ratios.iloc[0]:.1f}x - {top_ratios.iloc[-1]:.1f}x")

    return annual_shorts


def compute_annual_top40(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    """For each year, compute top-40 by avg daily dollar volume"""
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
        top_n = [s for s, _ in ranked[:TOP_N]]
        annual_universe[year] = top_n

    return annual_universe


# ============================================================================
# SIGNAL & REGIME (same as v8)
# ============================================================================

def compute_regime(spy_data: pd.DataFrame) -> pd.Series:
    """SPY vs SMA200 regime. True=RISK_ON, False=RISK_OFF."""
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
    """Cross-sectional momentum: 90d return (skip last 5d) - 5d return"""
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
        needed = MOMENTUM_LOOKBACK + MOMENTUM_SKIP
        if sym_idx < needed:
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
    """Inverse-volatility weights"""
    vols = {}
    for symbol in selected:
        if symbol not in price_data or date not in price_data[symbol].index:
            continue
        df = price_data[symbol]
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
    """Leverage = target_vol / realized_vol, clipped"""
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
    """Return tradeable symbols from top-40 for that year"""
    eligible = set(annual_universe.get(date.year, []))
    tradeable = []
    for symbol in eligible:
        if symbol not in price_data or date not in price_data[symbol].index:
            continue
        symbol_first_date = price_data[symbol].index[0]
        days_since = (date - symbol_first_date).days
        if date <= first_date + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since >= MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


# ============================================================================
# BACKTEST
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data, annual_short_candidates):
    """Run COMPASS Long-Short backtest"""

    print("\n" + "=" * 80)
    print("RUNNING COMPASS LONG-SHORT BACKTEST")
    print("=" * 80)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    print("\nComputing market regime (SPY vs SMA200)...")
    regime = compute_regime(spy_data)

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

    # Portfolio state
    cash = float(INITIAL_CAPITAL)

    # Long positions
    positions = {}
    trades = []

    # Short positions
    short_positions = {}  # symbol -> {entry_price, shares, entry_date, entry_idx}
    short_trades = []
    last_short_rebalance_idx = -999

    # Portfolio tracking
    portfolio_values = []
    stop_events = []
    peak_value = float(INITIAL_CAPITAL)
    in_protection_mode = False
    protection_stage = 0
    stop_loss_day_index = None
    post_stop_base = None

    risk_on_days = 0
    risk_off_days = 0

    for i, date in enumerate(all_dates):
        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # === PORTFOLIO VALUE ===
        portfolio_value = cash

        # Long mark-to-market
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # Short unrealized P&L
        for symbol, spos in list(short_positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                current_price = price_data[symbol].loc[date, 'Close']
                # Profit when price drops: (entry - current) * shares
                portfolio_value += (spos['entry_price'] - current_price) * spos['shares']

        # === PEAK & DRAWDOWN ===
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # === RECOVERY ===
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

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # === PORTFOLIO STOP LOSS ===
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({'date': date, 'portfolio_value': portfolio_value, 'drawdown': drawdown})
            print(f"\n  [STOP LOSS] {date.strftime('%Y-%m-%d')}: DD {drawdown:.1%} | Value: ${portfolio_value:,.0f}")

            # Close ALL longs
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
                        'pnl': pnl, 'return': pnl / (pos['entry_price'] * pos['shares']),
                        'side': 'long'
                    })
                del positions[symbol]

            # Close ALL shorts
            for symbol in list(short_positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    current_price = price_data[symbol].loc[date, 'Close']
                    spos = short_positions[symbol]
                    cash -= current_price * spos['shares'] + spos['shares'] * COMMISSION_PER_SHARE
                    pnl = (spos['entry_price'] - current_price) * spos['shares'] - 2 * spos['shares'] * COMMISSION_PER_SHARE
                    short_trades.append({
                        'symbol': symbol, 'entry_date': spos['entry_date'],
                        'exit_date': date, 'exit_reason': 'portfolio_stop',
                        'pnl': pnl, 'return': pnl / (spos['entry_price'] * spos['shares']),
                        'side': 'short'
                    })
                del short_positions[symbol]

            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i
            post_stop_base = cash

        # === REGIME ===
        is_risk_on = True
        if date in regime.index:
            is_risk_on = bool(regime.loc[date])
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # === DETERMINE LIMITS ===
        if in_protection_mode:
            if protection_stage == 1:
                max_positions = 2
                current_leverage = 0.5
            else:
                max_positions = 3
                current_leverage = 1.0
        elif not is_risk_on:
            max_positions = NUM_POSITIONS_RISK_OFF
            current_leverage = 1.0
        else:
            max_positions = NUM_POSITIONS
            current_leverage = compute_dynamic_leverage(spy_data, date)

        # === DAILY COSTS: MARGIN ===
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # === DAILY COSTS: SHORT BORROW ===
        for symbol, spos in short_positions.items():
            if symbol in price_data and date in price_data[symbol].index:
                current_price = price_data[symbol].loc[date, 'Close']
                borrow_cost = (SHORT_BORROW_COST / 252) * current_price * spos['shares']
                cash -= borrow_cost

        # === SHORTS: CHECK STOP LOSS (+15%) ===
        for symbol in list(short_positions.keys()):
            if symbol not in price_data or date not in price_data[symbol].index:
                continue
            spos = short_positions[symbol]
            current_price = price_data[symbol].loc[date, 'Close']
            short_return = (spos['entry_price'] - current_price) / spos['entry_price']

            if short_return <= -SHORT_STOP_LOSS:  # Price rose > 15%
                cash -= current_price * spos['shares'] + spos['shares'] * COMMISSION_PER_SHARE
                pnl = (spos['entry_price'] - current_price) * spos['shares'] - 2 * spos['shares'] * COMMISSION_PER_SHARE
                short_trades.append({
                    'symbol': symbol, 'entry_date': spos['entry_date'],
                    'exit_date': date, 'exit_reason': 'short_stop',
                    'pnl': pnl, 'return': short_return,
                    'side': 'short'
                })
                del short_positions[symbol]

        # === SHORTS: QUARTERLY REBALANCE ===
        if (i - last_short_rebalance_idx) >= SHORT_REBALANCE_DAYS and not in_protection_mode:
            # Close existing shorts
            for symbol in list(short_positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    current_price = price_data[symbol].loc[date, 'Close']
                    spos = short_positions[symbol]
                    cash -= current_price * spos['shares'] + spos['shares'] * COMMISSION_PER_SHARE
                    pnl = (spos['entry_price'] - current_price) * spos['shares'] - 2 * spos['shares'] * COMMISSION_PER_SHARE
                    short_return = (spos['entry_price'] - current_price) / spos['entry_price']
                    short_trades.append({
                        'symbol': symbol, 'entry_date': spos['entry_date'],
                        'exit_date': date, 'exit_reason': 'rebalance',
                        'pnl': pnl, 'return': short_return,
                        'side': 'short'
                    })
                del short_positions[symbol]

            # Open new shorts from candidates
            year = date.year
            short_candidates = annual_short_candidates.get(year, [])

            # If no candidates for this exact year, try closest available year
            if not short_candidates:
                available_years = sorted(annual_short_candidates.keys())
                for y in reversed(available_years):
                    if y <= year:
                        short_candidates = annual_short_candidates[y]
                        break

            if short_candidates and portfolio_value > 10000:
                short_capital = portfolio_value * SHORT_ALLOCATION * 0.95
                per_short = short_capital / len(short_candidates)

                for symbol in short_candidates:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue
                    if symbol in positions:  # Don't short something we're long
                        continue

                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue

                    shares = per_short / entry_price
                    commission = shares * COMMISSION_PER_SHARE

                    # Short sale: receive cash
                    cash += entry_price * shares - commission

                    short_positions[symbol] = {
                        'entry_price': entry_price,
                        'shares': shares,
                        'entry_date': date,
                        'entry_idx': i,
                    }

            last_short_rebalance_idx = i

        # === LONGS: CLOSE POSITIONS ===
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
                if pos_returns:
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
                    'pnl': pnl, 'return': pnl / (pos['entry_price'] * shares),
                    'side': 'long'
                })
                del positions[symbol]

        # === LONGS: OPEN NEW POSITIONS ===
        needed = max_positions - len(positions)
        # Long capital = (1 - SHORT_ALLOCATION) of available cash
        long_cash_available = cash * LONG_ALLOCATION

        if needed > 0 and long_cash_available > 1000 and len(tradeable_symbols) >= 5:
            scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
            available_scores = {s: sc for s, sc in scores.items()
                               if s not in positions and s not in short_positions}

            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]
                weights = compute_volatility_weights(price_data, selected, date)
                effective_capital = long_cash_available * current_leverage * 0.95

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue
                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue

                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = effective_capital * weight
                    max_per_pos = long_cash_available * 0.40
                    position_value = min(position_value, max_per_pos)

                    shares = position_value / entry_price
                    cost = shares * entry_price
                    commission = shares * COMMISSION_PER_SHARE

                    if cost + commission <= long_cash_available * 0.90:
                        positions[symbol] = {
                            'entry_price': entry_price, 'shares': shares,
                            'entry_date': date, 'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + commission

        # === SNAPSHOT ===
        portfolio_values.append({
            'date': date, 'value': portfolio_value,
            'cash': cash, 'long_positions': len(positions),
            'short_positions': len(short_positions),
            'drawdown': drawdown, 'leverage': current_leverage,
            'in_protection': in_protection_mode, 'risk_on': is_risk_on,
        })

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [PROT S{protection_stage}]" if in_protection_mode else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str} | "
                  f"L:{len(positions)} S:{len(short_positions)}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'short_trades': pd.DataFrame(short_trades) if short_trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'annual_universe': annual_universe,
        'annual_short_candidates': annual_short_candidates,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results):
    """Calculate performance metrics for long-short strategy"""
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']
    short_trades_df = results['short_trades']
    stop_df = results['stop_events']

    initial = INITIAL_CAPITAL
    final_value = df['value'].iloc[-1]
    years = len(df) / 252

    cagr = (final_value / initial) ** (1 / years) - 1 if years > 0 else 0
    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)
    max_dd = df['drawdown'].min()
    sharpe = cagr / volatility if volatility > 0 else 0

    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    # Long metrics
    long_win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    long_avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    long_total_pnl = trades_df['pnl'].sum() if len(trades_df) > 0 else 0

    # Short metrics
    short_win_rate = (short_trades_df['pnl'] > 0).mean() if len(short_trades_df) > 0 else 0
    short_avg_trade = short_trades_df['pnl'].mean() if len(short_trades_df) > 0 else 0
    short_total_pnl = short_trades_df['pnl'].sum() if len(short_trades_df) > 0 else 0

    # Exit reasons (longs)
    long_exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}
    short_exit_reasons = short_trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in short_trades_df.columns and len(short_trades_df) > 0 else {}

    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100
    risk_off_pct = results['risk_off_days'] / max(1, results['risk_on_days'] + results['risk_off_days']) * 100

    return {
        'initial': initial, 'final_value': final_value,
        'total_return': (final_value - initial) / initial,
        'years': years, 'cagr': cagr, 'volatility': volatility,
        'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar,
        'max_drawdown': max_dd,
        # Longs
        'long_trades': len(trades_df), 'long_win_rate': long_win_rate,
        'long_avg_trade': long_avg_trade, 'long_total_pnl': long_total_pnl,
        'long_exit_reasons': long_exit_reasons,
        # Shorts
        'short_trades': len(short_trades_df), 'short_win_rate': short_win_rate,
        'short_avg_trade': short_avg_trade, 'short_total_pnl': short_total_pnl,
        'short_exit_reasons': short_exit_reasons,
        # Risk
        'stop_events': len(stop_df),
        'protection_days': protection_days, 'protection_pct': protection_pct,
        'risk_off_pct': risk_off_pct,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # 1. Download fundamentals first to determine backtest period
    fund_df = download_fundamentals()

    earliest_fund_year = int(fund_df['year'].min())
    start_date = f'{earliest_fund_year}-01-01'
    print(f"\nFundamental data available from {earliest_fund_year}")
    print(f"Backtest period: {start_date} to {END_DATE}")

    # 2. Download price data for the fundamental period
    price_data = download_broad_pool(start_date)
    print(f"Symbols available: {len(price_data)}")

    spy_data = download_spy(start_date)
    print(f"SPY data: {len(spy_data)} trading days")

    # 3. Compute universes
    print("\n--- Computing Annual Top-40 (longs) ---")
    annual_universe = compute_annual_top40(price_data)

    print("\n--- Computing Annual Short Candidates (bottom-10 Revenue/Debt) ---")
    annual_short_candidates = compute_annual_short_candidates(fund_df)

    # 4. Run backtest
    results = run_backtest(price_data, annual_universe, spy_data, annual_short_candidates)

    # 5. Metrics
    metrics = calculate_metrics(results)

    # 6. Print results
    print("\n" + "=" * 80)
    print("RESULTS - OMNICAPITAL v8.1 COMPASS LONG-SHORT")
    print("=" * 80)

    print(f"\n--- Overall Performance ({metrics['years']:.1f} years) ---")
    print(f"Initial capital:        ${metrics['initial']:>15,.0f}")
    print(f"Final value:            ${metrics['final_value']:>15,.2f}")
    print(f"Total return:           {metrics['total_return']:>15.2%}")
    print(f"CAGR:                   {metrics['cagr']:>15.2%}")
    print(f"Volatility (annual):    {metrics['volatility']:>15.2%}")

    print(f"\n--- Risk-Adjusted ---")
    print(f"Sharpe ratio:           {metrics['sharpe']:>15.2f}")
    print(f"Sortino ratio:          {metrics['sortino']:>15.2f}")
    print(f"Calmar ratio:           {metrics['calmar']:>15.2f}")
    print(f"Max drawdown:           {metrics['max_drawdown']:>15.2%}")

    print(f"\n--- Long Side ---")
    print(f"Trades:                 {metrics['long_trades']:>15,}")
    print(f"Win rate:               {metrics['long_win_rate']:>15.2%}")
    print(f"Avg P&L per trade:      ${metrics['long_avg_trade']:>15,.2f}")
    print(f"Total P&L:              ${metrics['long_total_pnl']:>15,.2f}")
    if metrics['long_exit_reasons']:
        for reason, count in sorted(metrics['long_exit_reasons'].items(), key=lambda x: -x[1]):
            print(f"  {reason:25s}: {count:>6,}")

    print(f"\n--- Short Side ---")
    print(f"Trades:                 {metrics['short_trades']:>15,}")
    print(f"Win rate:               {metrics['short_win_rate']:>15.2%}")
    print(f"Avg P&L per trade:      ${metrics['short_avg_trade']:>15,.2f}")
    print(f"Total P&L:              ${metrics['short_total_pnl']:>15,.2f}")
    if metrics['short_exit_reasons']:
        for reason, count in sorted(metrics['short_exit_reasons'].items(), key=lambda x: -x[1]):
            print(f"  {reason:25s}: {count:>6,}")

    print(f"\n--- Risk Management ---")
    print(f"Stop loss events:       {metrics['stop_events']:>15,}")
    print(f"Days in protection:     {metrics['protection_days']:>15,} ({metrics['protection_pct']:.1f}%)")
    print(f"Risk-off days:          {metrics['risk_off_pct']:>14.1f}%")

    # Short candidates detail
    print(f"\n--- Short Candidates by Year ---")
    for year in sorted(annual_short_candidates.keys()):
        candidates = annual_short_candidates[year]
        print(f"  {year}: {candidates}")

    # 7. Save
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/v8_longshort_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/v8_longshort_long_trades.csv', index=False)
    if len(results['short_trades']) > 0:
        results['short_trades'].to_csv('backtests/v8_longshort_short_trades.csv', index=False)

    output_file = 'results_v8_longshort.pkl'
    with open(output_file, 'wb') as f:
        pickle.dump({
            'params': {
                'long_allocation': LONG_ALLOCATION,
                'short_allocation': SHORT_ALLOCATION,
                'num_shorts': NUM_SHORTS,
                'short_borrow_cost': SHORT_BORROW_COST,
                'short_stop_loss': SHORT_STOP_LOSS,
                'short_rebalance_days': SHORT_REBALANCE_DAYS,
            },
            'metrics': metrics,
            'portfolio_values': results['portfolio_values'],
            'trades': results['trades'],
            'short_trades': results['short_trades'],
            'annual_short_candidates': results['annual_short_candidates'],
        }, f)

    print(f"\nResults saved: {output_file}")

    print("\n" + "=" * 80)
    print("COMPASS LONG-SHORT BACKTEST COMPLETE")
    print("=" * 80)
