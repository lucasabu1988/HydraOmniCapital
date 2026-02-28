#!/usr/bin/env python3
"""
================================================================================
OMNICAPITAL -- ECLIPSE v1.0
Statistical Arbitrage via Engle-Granger Cointegration Pairs Trading
================================================================================
Backtest aislado para evaluar la propuesta del equipo asesor externo.
Usa el MISMO universo (BROAD_POOL top-40), mismos datos, mismo capital que COMPASS
para comparacion directa y justa.

Metodologia:
- Formation period (252d): test cointegration en todos los pares C(40,2)=780
- Trading period (126d): operar pares calificados con z-score entry/exit
- Market-neutral: long una pata + short la otra (hedge ratio via OLS)
- Costos realistas: comision + slippage ambas patas + borrow fee + cash yield

Nota: statsmodels NO esta instalado. ADF test implementado manualmente
con numpy.linalg.lstsq + valores criticos de MacKinnon hardcodeados.
================================================================================
"""

import pandas as pd
import numpy as np
import yfinance as yf
from scipy.stats import linregress
from itertools import combinations
import pickle
import os
import time as time_module
from typing import Dict, List, Tuple, Optional
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

# Pair Formation
FORMATION_PERIOD = 252      # 1 year lookback for cointegration test
TRADING_PERIOD = 126        # Re-form pairs every 6 months
COINT_PVALUE = 0.05         # 95% confidence for Engle-Granger
ADF_LAGS = 4                # Augmented lags in ADF test
MIN_HALF_LIFE = 5           # Min mean-reversion speed (days)
MAX_HALF_LIFE = 126         # Max (must revert within trading period)

# Trading Signals (Z-Score of spread)
ZSCORE_ENTRY = 2.0          # Enter when |z| > 2.0 std devs
ZSCORE_EXIT = 0.0           # Exit when z crosses 0 (mean reversion)
ZSCORE_STOP = 4.0           # Stop: cointegration breakdown
ZSCORE_WINDOW = 30          # Rolling window for z-score

# Portfolio
INITIAL_CAPITAL = 100_000
MAX_PAIRS = 10              # Max simultaneous pair trades
CAPITAL_PER_PAIR_PCT = 0.10 # 10% of portfolio per pair
MAX_PAIR_PCT = 0.20         # Hard cap 20% per pair

# Costs (BOTH legs)
COMMISSION_PER_SHARE = 0.001  # Same as COMPASS
SLIPPAGE_BPS = 2              # 2bps per side (4 legs round-trip)
SHORT_BORROW_RATE = 0.01      # 1% annualized on short leg
CASH_YIELD_RATE = 0.03        # 3% annual on uninvested cash

# Data
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'
INITIAL_CAPITAL = 100_000

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
# DATA FUNCTIONS (copied from COMPASS for self-containment)
# =============================================================================

def download_broad_pool() -> Dict[str, pd.DataFrame]:
    """Download/load cached data for the broad pool"""
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
    if failed:
        print(f"  Failed: {failed}")

    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)

    return data


def download_spy() -> pd.DataFrame:
    """Download SPY data for benchmark comparison"""
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'

    if os.path.exists(cache_file):
        print("[Cache] Loading SPY data...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        return df

    print("[Download] Downloading SPY...")
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def compute_annual_top40(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    """For each year, compute top-40 by avg daily dollar volume (prior year data)"""
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

        if year > years[0] and year - 1 in annual_universe:
            prev = set(annual_universe[year - 1])
            curr = set(top_n)
            added = curr - prev
            removed = prev - curr
            if added or removed:
                print(f"  {year}: Top-{TOP_N} | +{len(added)} added, -{len(removed)} removed")
        else:
            print(f"  {year}: Initial top-{TOP_N} = {len(top_n)} stocks")

    return annual_universe


# =============================================================================
# STATISTICAL ENGINE (manual ADF + Engle-Granger)
# =============================================================================

def adf_test(y: np.ndarray, max_lags: int = ADF_LAGS) -> Tuple[float, float]:
    """
    Augmented Dickey-Fuller test (manual implementation).
    H0: y has unit root (non-stationary). Ha: y is stationary.
    Model: dy_t = alpha + rho*y_{t-1} + sum(gamma_i * dy_{t-i}) + e_t
    Returns (t_stat, approx_p_value).
    """
    n = len(y)
    dy = np.diff(y)

    T = len(dy) - max_lags
    if T < 20:
        return 0.0, 1.0

    dep = dy[max_lags:]

    # Regressors: y_{t-1}, lagged diffs, constant
    X_cols = [y[max_lags:n - 1]]  # y_{t-1}
    for lag in range(1, max_lags + 1):
        X_cols.append(dy[max_lags - lag:n - 1 - lag])
    X_cols.append(np.ones(T))  # intercept

    X = np.column_stack(X_cols)

    try:
        beta_hat, _, _, _ = np.linalg.lstsq(X, dep, rcond=None)
    except np.linalg.LinAlgError:
        return 0.0, 1.0

    resid = dep - X @ beta_hat
    sigma2 = np.sum(resid ** 2) / (T - X.shape[1])

    try:
        cov = sigma2 * np.linalg.inv(X.T @ X)
        se = np.sqrt(np.diag(cov))
        t_stat = beta_hat[0] / se[0]
    except (np.linalg.LinAlgError, FloatingPointError):
        return 0.0, 1.0

    return t_stat, _adf_pvalue(t_stat)


def _adf_pvalue(t_stat: float, cointegration: bool = False) -> float:
    """
    Approximate p-value from MacKinnon critical values.
    Standard ADF (constant, no trend): 1%=-3.43, 5%=-2.86, 10%=-2.57
    Engle-Granger residuals (2 vars):  1%=-3.90, 5%=-3.34, 10%=-3.04
    """
    if cointegration:
        cv1, cv5, cv10 = -3.90, -3.34, -3.04
    else:
        cv1, cv5, cv10 = -3.43, -2.86, -2.57

    if t_stat <= cv1:
        p = 0.005
    elif t_stat <= cv5:
        p = 0.01 + (0.05 - 0.01) * (t_stat - cv1) / (cv5 - cv1)
    elif t_stat <= cv10:
        p = 0.05 + (0.10 - 0.05) * (t_stat - cv5) / (cv10 - cv5)
    elif t_stat <= -1.94:
        p = 0.10 + (0.30 - 0.10) * (t_stat - cv10) / (-1.94 - cv10)
    else:
        p = 0.30 + 0.70 * min(1.0, (t_stat + 1.94) / 3.0)

    return max(0.0, min(1.0, p))


def engle_granger_coint(y: np.ndarray, x: np.ndarray) -> Tuple[float, float, float, float]:
    """
    Engle-Granger two-step cointegration test.
    Step 1: OLS y = alpha + beta*x + e
    Step 2: ADF on residuals (with cointegration critical values)
    Returns (alpha, beta, adf_tstat, adf_pvalue).
    """
    slope, intercept, _, _, _ = linregress(x, y)
    residuals = y - intercept - slope * x

    t_stat, _ = adf_test(residuals)
    p_value = _adf_pvalue(t_stat, cointegration=True)

    return intercept, slope, t_stat, p_value


def compute_half_life(residuals: np.ndarray) -> float:
    """
    Half-life of mean reversion via AR(1): e_t = phi*e_{t-1} + noise.
    half_life = -log(2) / log(phi)
    """
    y = residuals[1:]
    x = residuals[:-1].reshape(-1, 1)
    x_with_const = np.column_stack([x, np.ones(len(x))])

    try:
        beta, _, _, _ = np.linalg.lstsq(x_with_const, y, rcond=None)
    except np.linalg.LinAlgError:
        return np.inf

    phi = beta[0]
    if phi >= 1.0 or phi <= 0.0:
        return np.inf

    return -np.log(2) / np.log(phi)


# =============================================================================
# PAIR FORMATION
# =============================================================================

def form_pairs(price_data: Dict[str, pd.DataFrame],
               tradeable: List[str],
               all_dates: list,
               end_idx: int) -> List[Dict]:
    """
    Test cointegration for all pairs in tradeable universe.
    Uses prior FORMATION_PERIOD days. Returns qualifying pairs sorted by strength.
    """
    start_idx = max(0, end_idx - FORMATION_PERIOD)
    formation_dates = all_dates[start_idx:end_idx]

    if len(formation_dates) < 200:
        return []

    # Build close-price matrix for formation window
    close_matrix = {}
    for sym in tradeable:
        if sym not in price_data:
            continue
        df = price_data[sym]
        prices = []
        valid = True
        for d in formation_dates:
            if d in df.index:
                prices.append(float(df.loc[d, 'Close']))
            else:
                valid = False
                break
        if valid and len(prices) == len(formation_dates):
            close_matrix[sym] = np.array(prices)

    symbols = list(close_matrix.keys())
    if len(symbols) < 5:
        return []

    qualifying = []
    for sym_y, sym_x in combinations(symbols, 2):
        y = close_matrix[sym_y]
        x = close_matrix[sym_x]

        alpha, beta, adf_t, adf_p = engle_granger_coint(y, x)

        if adf_p >= COINT_PVALUE:
            continue
        if abs(beta) < 0.01 or abs(beta) > 10.0:
            continue

        residuals = y - alpha - beta * x
        hl = compute_half_life(residuals)

        if hl < MIN_HALF_LIFE or hl > MAX_HALF_LIFE:
            continue

        spread_mean = float(np.mean(residuals))
        spread_std = float(np.std(residuals))
        if spread_std < 1e-8:
            continue

        qualifying.append({
            'y_symbol': sym_y,
            'x_symbol': sym_x,
            'alpha': alpha,
            'beta': beta,
            'adf_tstat': adf_t,
            'adf_pvalue': adf_p,
            'half_life': hl,
            'spread_mean': spread_mean,
            'spread_std': spread_std,
            'spread_history': [],
        })

    # Sort by cointegration strength (most negative t-stat = strongest)
    qualifying.sort(key=lambda p: p['adf_tstat'])

    # Return top buffer (3x MAX_PAIRS)
    return qualifying[:MAX_PAIRS * 3]


# =============================================================================
# TRADING HELPERS
# =============================================================================

def get_price(price_data: Dict[str, pd.DataFrame], symbol: str,
              date: pd.Timestamp) -> Optional[float]:
    """Safe price lookup. Returns None if unavailable."""
    if symbol not in price_data:
        return None
    df = price_data[symbol]
    if date in df.index:
        return float(df.loc[date, 'Close'])
    return None


def open_pair(pair_info: dict, date: pd.Timestamp, date_idx: int,
              direction: int, cash: float, portfolio_value: float,
              price_data: dict) -> Optional[dict]:
    """
    Open a pair trade. direction: +1 = long Y / short X, -1 = short Y / long X.
    Returns position dict or None if insufficient cash/data.
    """
    y_price = get_price(price_data, pair_info['y_symbol'], date)
    x_price = get_price(price_data, pair_info['x_symbol'], date)
    if y_price is None or x_price is None or y_price <= 0 or x_price <= 0:
        return None

    cap = min(portfolio_value * CAPITAL_PER_PAIR_PCT, portfolio_value * MAX_PAIR_PCT)
    if cap > cash * 0.95:  # need cash buffer
        return None
    if cap < 1000:
        return None

    beta = abs(pair_info['beta'])
    y_value = cap / (1.0 + beta)
    x_value = cap * beta / (1.0 + beta)

    y_shares = y_value / y_price
    x_shares = x_value / x_price

    # Entry costs (both legs)
    comm = (y_shares + x_shares) * COMMISSION_PER_SHARE
    slip = (y_shares * y_price + x_shares * x_price) * SLIPPAGE_BPS / 10000.0
    total_cost = comm + slip

    return {
        'pair_id': f"{pair_info['y_symbol']}_{pair_info['x_symbol']}",
        'y_symbol': pair_info['y_symbol'],
        'x_symbol': pair_info['x_symbol'],
        'beta': pair_info['beta'],
        'alpha': pair_info['alpha'],
        'direction': direction,
        'y_shares': y_shares,
        'x_shares': x_shares,
        'y_entry_price': y_price,
        'x_entry_price': x_price,
        'entry_date': date,
        'entry_idx': date_idx,
        'capital_committed': cap,
        'entry_cost': total_cost,
        'spread_history': list(pair_info['spread_history']),
    }


def close_pair(pos: dict, date: pd.Timestamp, price_data: dict,
               exit_reason: str) -> dict:
    """Close a pair trade. Returns trade record dict."""
    y_price = get_price(price_data, pos['y_symbol'], date)
    x_price = get_price(price_data, pos['x_symbol'], date)

    # Fallback to entry price if data missing on close day
    if y_price is None:
        y_price = pos['y_entry_price']
    if x_price is None:
        x_price = pos['x_entry_price']

    # PnL calculation
    if pos['direction'] == -1:  # short Y, long X
        y_pnl = (pos['y_entry_price'] - y_price) * pos['y_shares']
        x_pnl = (x_price - pos['x_entry_price']) * pos['x_shares']
    else:  # long Y, short X
        y_pnl = (y_price - pos['y_entry_price']) * pos['y_shares']
        x_pnl = (pos['x_entry_price'] - x_price) * pos['x_shares']

    # Exit costs
    comm = (pos['y_shares'] + pos['x_shares']) * COMMISSION_PER_SHARE
    slip = (pos['y_shares'] * y_price + pos['x_shares'] * x_price) * SLIPPAGE_BPS / 10000.0
    exit_cost = comm + slip

    gross_pnl = y_pnl + x_pnl
    net_pnl = gross_pnl - pos['entry_cost'] - exit_cost
    ret = net_pnl / pos['capital_committed'] if pos['capital_committed'] > 0 else 0.0

    return {
        'pair_id': pos['pair_id'],
        'y_symbol': pos['y_symbol'],
        'x_symbol': pos['x_symbol'],
        'direction': pos['direction'],
        'beta': pos['beta'],
        'entry_date': pos['entry_date'],
        'exit_date': date,
        'exit_reason': exit_reason,
        'y_entry': pos['y_entry_price'],
        'x_entry': pos['x_entry_price'],
        'y_exit': y_price,
        'x_exit': x_price,
        'gross_pnl': gross_pnl,
        'costs': pos['entry_cost'] + exit_cost,
        'net_pnl': net_pnl,
        'return_pct': ret,
        'capital': pos['capital_committed'],
        'hold_days': (date - pos['entry_date']).days,
    }


# =============================================================================
# BACKTEST
# =============================================================================

def run_backtest(price_data: Dict[str, pd.DataFrame],
                 annual_universe: Dict[int, List[str]]) -> Dict:
    """Day-by-day pairs trading simulation."""

    # Build sorted list of all trading dates
    all_dates_set = set()
    for df in price_data.values():
        all_dates_set.update(df.index)
    all_dates = sorted(list(all_dates_set))
    print(f"\n[Backtest] {len(all_dates)} trading days: {all_dates[0].date()} -> {all_dates[-1].date()}")

    # First date each symbol appears (for MIN_AGE_DAYS filter)
    first_date = {}
    for sym, df in price_data.items():
        first_date[sym] = df.index[0]

    cash = float(INITIAL_CAPITAL)
    active_pairs = []
    qualifying_pairs = []
    portfolio_values = []
    trades = []
    last_formation_idx = None
    formation_count = 0
    total_qualifying_pairs = 0

    t_start = time_module.time()

    for i, date in enumerate(all_dates):
        year = date.year

        # --- Tradeable universe (same top-40 as COMPASS) ---
        if year in annual_universe:
            universe = annual_universe[year]
        else:
            universe = annual_universe.get(min(annual_universe.keys()), [])

        tradeable = []
        for sym in universe:
            if sym in price_data and sym in first_date:
                age = (date - first_date[sym]).days
                if age >= MIN_AGE_DAYS:
                    if date in price_data[sym].index:
                        tradeable.append(sym)

        # --- Portfolio value ---
        portfolio_value = cash
        for pos in active_pairs:
            y_price = get_price(price_data, pos['y_symbol'], date)
            x_price = get_price(price_data, pos['x_symbol'], date)
            if y_price is None:
                y_price = pos['y_entry_price']
            if x_price is None:
                x_price = pos['x_entry_price']

            if pos['direction'] == -1:  # short Y, long X
                y_pnl = (pos['y_entry_price'] - y_price) * pos['y_shares']
                x_pnl = (x_price - pos['x_entry_price']) * pos['x_shares']
            else:  # long Y, short X
                y_pnl = (y_price - pos['y_entry_price']) * pos['y_shares']
                x_pnl = (pos['x_entry_price'] - x_price) * pos['x_shares']

            portfolio_value += pos['capital_committed'] + y_pnl + x_pnl - pos['entry_cost']

        # --- Cash yield ---
        if cash > 0:
            cash += cash * (CASH_YIELD_RATE / 252.0)

        # --- Daily borrow cost on short legs ---
        for pos in active_pairs:
            if pos['direction'] == -1:
                short_sym, short_shares = pos['y_symbol'], pos['y_shares']
            else:
                short_sym, short_shares = pos['x_symbol'], pos['x_shares']
            short_price = get_price(price_data, short_sym, date)
            if short_price is not None:
                daily_borrow = SHORT_BORROW_RATE / 252.0 * short_shares * short_price
                cash -= daily_borrow

        # --- PAIR FORMATION (every TRADING_PERIOD days) ---
        need_formation = False
        if last_formation_idx is None and i >= FORMATION_PERIOD:
            need_formation = True
        elif last_formation_idx is not None and (i - last_formation_idx) >= TRADING_PERIOD:
            need_formation = True

        if need_formation:
            # Close all existing pairs (trading period over)
            for pos in list(active_pairs):
                trade = close_pair(pos, date, price_data, 'formation_reset')
                trades.append(trade)
                cash += pos['capital_committed'] + trade['net_pnl']
            active_pairs = []

            # Re-form
            qualifying_pairs = form_pairs(price_data, tradeable, all_dates, i)
            last_formation_idx = i
            formation_count += 1
            total_qualifying_pairs += len(qualifying_pairs)

            if formation_count <= 5 or formation_count % 10 == 0:
                print(f"  Formation #{formation_count} at {date.date()}: "
                      f"{len(qualifying_pairs)} qualifying pairs from {len(tradeable)} stocks")

        # --- EXIT active pairs ---
        for pos in list(active_pairs):
            y_price = get_price(price_data, pos['y_symbol'], date)
            x_price = get_price(price_data, pos['x_symbol'], date)
            if y_price is None or x_price is None:
                # Force close if data disappears
                trade = close_pair(pos, date, price_data, 'data_missing')
                trades.append(trade)
                cash += pos['capital_committed'] + trade['net_pnl']
                active_pairs.remove(pos)
                continue

            spread = y_price - pos['alpha'] - pos['beta'] * x_price
            pos['spread_history'].append(spread)

            if len(pos['spread_history']) < ZSCORE_WINDOW:
                continue

            recent = pos['spread_history'][-ZSCORE_WINDOW:]
            s_mean = np.mean(recent)
            s_std = np.std(recent)
            if s_std < 1e-8:
                continue
            zscore = (spread - s_mean) / s_std

            exit_reason = None
            if pos['direction'] == -1 and zscore <= ZSCORE_EXIT:
                exit_reason = 'mean_reversion'
            elif pos['direction'] == +1 and zscore >= -ZSCORE_EXIT:
                exit_reason = 'mean_reversion'
            elif abs(zscore) > ZSCORE_STOP:
                exit_reason = 'breakdown_stop'

            # Force close if stock left universe
            if (pos['y_symbol'] not in tradeable or
                    pos['x_symbol'] not in tradeable):
                exit_reason = 'universe_rotation'

            if exit_reason:
                trade = close_pair(pos, date, price_data, exit_reason)
                trades.append(trade)
                cash += pos['capital_committed'] + trade['net_pnl']
                active_pairs.remove(pos)

        # --- ENTER new pairs ---
        if len(active_pairs) < MAX_PAIRS and qualifying_pairs:
            for qp in qualifying_pairs:
                if len(active_pairs) >= MAX_PAIRS:
                    break

                pair_id = f"{qp['y_symbol']}_{qp['x_symbol']}"
                if any(p['pair_id'] == pair_id for p in active_pairs):
                    continue

                y_price = get_price(price_data, qp['y_symbol'], date)
                x_price = get_price(price_data, qp['x_symbol'], date)
                if y_price is None or x_price is None:
                    continue

                # Both symbols must still be tradeable
                if qp['y_symbol'] not in tradeable or qp['x_symbol'] not in tradeable:
                    continue

                spread = y_price - qp['alpha'] - qp['beta'] * x_price
                qp['spread_history'].append(spread)

                if len(qp['spread_history']) < ZSCORE_WINDOW:
                    continue

                recent = qp['spread_history'][-ZSCORE_WINDOW:]
                s_mean = np.mean(recent)
                s_std = np.std(recent)
                if s_std < 1e-8:
                    continue
                zscore = (spread - s_mean) / s_std

                direction = None
                if zscore > ZSCORE_ENTRY:
                    direction = -1  # short Y, long X (spread too wide)
                elif zscore < -ZSCORE_ENTRY:
                    direction = +1  # long Y, short X (spread too narrow)

                if direction is not None:
                    pos = open_pair(qp, date, i, direction, cash, portfolio_value,
                                   price_data)
                    if pos is not None:
                        active_pairs.append(pos)
                        cash -= pos['capital_committed']

        # --- Update spread history for non-active qualifying pairs ---
        active_ids = {p['pair_id'] for p in active_pairs}
        for qp in qualifying_pairs:
            qp_id = f"{qp['y_symbol']}_{qp['x_symbol']}"
            if qp_id not in active_ids:
                y_p = get_price(price_data, qp['y_symbol'], date)
                x_p = get_price(price_data, qp['x_symbol'], date)
                if y_p is not None and x_p is not None:
                    spread = y_p - qp['alpha'] - qp['beta'] * x_p
                    qp['spread_history'].append(spread)

        # --- Daily snapshot ---
        gross_exposure = sum(p['capital_committed'] for p in active_pairs) * 2.0
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'active_pairs': len(active_pairs),
            'qualifying_pairs': len(qualifying_pairs),
            'gross_exposure': gross_exposure,
        })

        # Annual progress
        if i > 0 and i % 252 == 0:
            elapsed = time_module.time() - t_start
            print(f"  Year {i // 252:>2}: ${portfolio_value:>12,.0f} | "
                  f"Pairs: {len(active_pairs):>2} | Cash: ${cash:>10,.0f} | "
                  f"Trades: {len(trades):>4} | {elapsed:.1f}s")

    # Close remaining pairs at end
    for pos in list(active_pairs):
        trade = close_pair(pos, all_dates[-1], price_data, 'backtest_end')
        trades.append(trade)
        cash += pos['capital_committed'] + trade['net_pnl']
    active_pairs = []

    elapsed = time_module.time() - t_start
    print(f"\n[Backtest] Completed in {elapsed:.1f}s | {len(trades)} total pair trades")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'formation_count': formation_count,
        'avg_qualifying': total_qualifying_pairs / max(1, formation_count),
    }


# =============================================================================
# METRICS
# =============================================================================

def calculate_metrics(results: Dict) -> Dict:
    """Calculate performance metrics (same formula as COMPASS for fair comparison)."""
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']

    initial = INITIAL_CAPITAL
    final_value = df['value'].iloc[-1]

    years = len(df) / 252.0
    cagr = (final_value / initial) ** (1.0 / years) - 1.0

    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)

    # Max drawdown
    cummax = df['value'].cummax()
    drawdown = (df['value'] / cummax) - 1.0
    max_dd = drawdown.min()

    sharpe = cagr / volatility if volatility > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    # Sortino
    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0

    # Trade stats
    if len(trades_df) > 0 and 'net_pnl' in trades_df.columns:
        win_rate = (trades_df['net_pnl'] > 0).mean()
        avg_trade = trades_df['net_pnl'].mean()
        avg_winner = trades_df.loc[trades_df['net_pnl'] > 0, 'net_pnl'].mean() \
            if (trades_df['net_pnl'] > 0).any() else 0
        avg_loser = trades_df.loc[trades_df['net_pnl'] < 0, 'net_pnl'].mean() \
            if (trades_df['net_pnl'] < 0).any() else 0
        exit_reasons = trades_df['exit_reason'].value_counts().to_dict()
        total_trades = len(trades_df)
        avg_hold = trades_df['hold_days'].mean()
    else:
        win_rate = avg_trade = avg_winner = avg_loser = avg_hold = 0
        exit_reasons = {}
        total_trades = 0

    # Average active pairs
    avg_pairs = df['active_pairs'].mean()

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
        'win_rate': win_rate,
        'avg_trade': avg_trade,
        'avg_winner': avg_winner,
        'avg_loser': avg_loser,
        'total_trades': total_trades,
        'exit_reasons': exit_reasons,
        'avg_hold_days': avg_hold,
        'avg_pairs_active': avg_pairs,
        'formation_count': results['formation_count'],
        'avg_qualifying': results['avg_qualifying'],
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
    }


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("ECLIPSE v1.0 -- Statistical Arbitrage via Engle-Granger Cointegration")
    print("Pairs Trading Backtest (Advisory Team Proposal)")
    print("=" * 80)
    print(f"\nUniverse: BROAD_POOL ({len(BROAD_POOL)} stocks) -> Top-{TOP_N} annual rotation")
    print(f"Formation: {FORMATION_PERIOD}d | Trading: {TRADING_PERIOD}d | "
          f"Coint p<{COINT_PVALUE}")
    print(f"Entry: |z|>{ZSCORE_ENTRY} | Exit: z->0 | Stop: |z|>{ZSCORE_STOP}")
    print(f"Max pairs: {MAX_PAIRS} | Capital/pair: {CAPITAL_PER_PAIR_PCT:.0%} | "
          f"Costs: {SLIPPAGE_BPS}bps + ${COMMISSION_PER_SHARE}/sh + "
          f"{SHORT_BORROW_RATE:.0%} borrow")
    print()

    # 1. Data
    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")

    spy_data = download_spy()

    # 2. Annual top-40 (same as COMPASS)
    print("\n--- Computing Annual Top-40 ---")
    annual_universe = compute_annual_top40(price_data)

    # 3. Run backtest
    results = run_backtest(price_data, annual_universe)

    # 4. Calculate metrics
    metrics = calculate_metrics(results)

    # 5. Print results
    print("\n" + "=" * 80)
    print("RESULTS -- ECLIPSE v1.0 (Statistical Arbitrage)")
    print("=" * 80)

    print(f"\n  {'PERFORMANCE':}")
    print(f"  {'-' * 50}")
    print(f"  {'Initial Capital':<28} ${metrics['initial']:>14,}")
    print(f"  {'Final Value':<28} ${metrics['final_value']:>14,.0f}")
    print(f"  {'Total Return':<28} {metrics['total_return']:>14.2%}")
    print(f"  {'CAGR':<28} {metrics['cagr']:>14.2%}")
    print(f"  {'Backtest Period':<28} {metrics['years']:>13.1f}y")

    print(f"\n  {'RISK-ADJUSTED':}")
    print(f"  {'-' * 50}")
    print(f"  {'Volatility (ann.)':<28} {metrics['volatility']:>14.2%}")
    print(f"  {'Sharpe Ratio':<28} {metrics['sharpe']:>14.3f}")
    print(f"  {'Sortino Ratio':<28} {metrics['sortino']:>14.3f}")
    print(f"  {'Calmar Ratio':<28} {metrics['calmar']:>14.3f}")
    print(f"  {'Max Drawdown':<28} {metrics['max_drawdown']:>14.2%}")

    print(f"\n  {'TRADING':}")
    print(f"  {'-' * 50}")
    print(f"  {'Total Pair Trades':<28} {metrics['total_trades']:>14}")
    print(f"  {'Win Rate':<28} {metrics['win_rate']:>14.1%}")
    print(f"  {'Avg Trade P&L':<28} ${metrics['avg_trade']:>13,.2f}")
    print(f"  {'Avg Winner':<28} ${metrics['avg_winner']:>13,.2f}")
    print(f"  {'Avg Loser':<28} ${metrics['avg_loser']:>13,.2f}")
    print(f"  {'Avg Hold Days':<28} {metrics['avg_hold_days']:>14.1f}")

    print(f"\n  {'EXIT REASONS':}")
    print(f"  {'-' * 50}")
    for reason, count in sorted(metrics['exit_reasons'].items(),
                                key=lambda x: x[1], reverse=True):
        pct = count / max(1, metrics['total_trades']) * 100
        print(f"  {reason:<28} {count:>8}  ({pct:>5.1f}%)")

    print(f"\n  {'ECLIPSE-SPECIFIC':}")
    print(f"  {'-' * 50}")
    print(f"  {'Formations':<28} {metrics['formation_count']:>14}")
    print(f"  {'Avg Qualifying Pairs':<28} {metrics['avg_qualifying']:>14.1f}")
    print(f"  {'Avg Active Pairs':<28} {metrics['avg_pairs_active']:>14.1f}")
    print(f"  {'Best Year':<28} {metrics['best_year']:>14.2%}")
    print(f"  {'Worst Year':<28} {metrics['worst_year']:>14.2%}")

    # Annual returns table
    print(f"\n  {'ANNUAL RETURNS':}")
    print(f"  {'-' * 30}")
    for yr, ret in metrics['annual_returns'].items():
        marker = " <--" if ret == metrics['best_year'] or ret == metrics['worst_year'] else ""
        print(f"  {yr.year:<8} {ret:>10.2%}{marker}")

    # 6. Head-to-head vs COMPASS
    print("\n" + "=" * 80)
    print("HEAD-TO-HEAD: ECLIPSE vs COMPASS")
    print("=" * 80)
    print(f"\n  {'METRIC':<24} {'ECLIPSE':>14} {'COMPASS (pure)':>16} {'COMPASS (real)':>16}")
    print(f"  {'-' * 70}")
    print(f"  {'CAGR':<24} {metrics['cagr']:>13.2%} {'17.66%':>16} {'13.52%':>16}")
    print(f"  {'Sharpe':<24} {metrics['sharpe']:>14.3f} {'0.850':>16} {'0.658':>16}")
    print(f"  {'Max Drawdown':<24} {metrics['max_drawdown']:>13.2%} {'-27.5%':>16} {'-30.3%':>16}")
    print(f"  {'Volatility':<24} {metrics['volatility']:>13.2%} {'20.8%':>16} {'20.7%':>16}")
    print(f"  {'Win Rate':<24} {metrics['win_rate']:>13.1%} {'55.2%':>16} {'55.2%':>16}")
    print(f"  {'Total Trades':<24} {metrics['total_trades']:>14} {'5,445':>16} {'5,445':>16}")
    print(f"  {'$100K -> $':<24} {metrics['final_value']:>13,.0f} {'$6,910,000':>16} {'$4,425,000':>16}")
    print(f"  {'Strategy':<24} {'Pairs Arb':>14} {'Momentum':>16} {'Momentum':>16}")
    print(f"  {'Market Exposure':<24} {'Neutral':>14} {'Long Only':>16} {'Long Only':>16}")

    print(f"\n  VERDICT:")
    if metrics['cagr'] > 0.1566:
        print(f"  ECLIPSE beats COMPASS realistic ({metrics['cagr']:.2%} vs 15.66%)")
    elif metrics['cagr'] > 0.05:
        print(f"  ECLIPSE has value as diversifier ({metrics['cagr']:.2%}) but does NOT beat COMPASS")
    else:
        print(f"  ECLIPSE FAILS to justify implementation ({metrics['cagr']:.2%} CAGR)")
        print(f"  Advisory team proposal does NOT deliver on promises of Sharpe > 1.50")

    # 7. Save CSVs
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/eclipse_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/eclipse_trades.csv', index=False)
    print(f"\n  Saved: backtests/eclipse_daily.csv ({len(results['portfolio_values'])} rows)")
    print(f"  Saved: backtests/eclipse_trades.csv ({len(results['trades'])} trades)")

    # 8. Save pickle
    with open('results_eclipse_v1.pkl', 'wb') as f:
        pickle.dump({
            'params': {
                'formation_period': FORMATION_PERIOD,
                'trading_period': TRADING_PERIOD,
                'coint_pvalue': COINT_PVALUE,
                'zscore_entry': ZSCORE_ENTRY,
                'zscore_exit': ZSCORE_EXIT,
                'zscore_stop': ZSCORE_STOP,
                'max_pairs': MAX_PAIRS,
                'capital_per_pair': CAPITAL_PER_PAIR_PCT,
                'slippage_bps': SLIPPAGE_BPS,
                'commission': COMMISSION_PER_SHARE,
                'borrow_rate': SHORT_BORROW_RATE,
                'cash_yield': CASH_YIELD_RATE,
            },
            'metrics': {k: v for k, v in metrics.items() if k != 'annual_returns'},
            'portfolio_values': results['portfolio_values'],
            'trades': results['trades'],
        }, f)
    print(f"  Saved: results_eclipse_v1.pkl")

    print("\n" + "=" * 80)
    print(f"ECLIPSE v1.0 COMPLETE | {metrics['cagr']:.2%} CAGR | "
          f"{metrics['sharpe']:.3f} Sharpe | {metrics['max_drawdown']:.2%} MaxDD")
    print("=" * 80)
