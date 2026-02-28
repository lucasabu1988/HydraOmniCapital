"""
OmniCapital v8 COMPASS - Cross-sectional Momentum, Position-Adjusted Risk Scaling
==================================================================================
Nuevo algoritmo con signal real, regime filter, vol targeting, y position-level stops.

Mejoras vs v6:
- Signal: Cross-sectional momentum (90d) + short-term reversal (5d skip)
- Regime: SPY > SMA200 = RISK_ON, SPY < SMA200 = RISK_OFF
- Sizing: Inverse volatility weighting (mas capital a stocks estables)
- Leverage: Volatility targeting (auto-reduce en crisis)
- Exits: Hold time (5d) + position stop (-8%) + trailing stop (3% desde max)
- Recovery: Gradual en 3 etapas (vs binario en v6)
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

# Signal
MOMENTUM_LOOKBACK = 90      # Dias para momentum de medio plazo
MOMENTUM_SKIP = 5           # Dias recientes a excluir (reversal)
MIN_MOMENTUM_STOCKS = 20    # Minimo de stocks con score valido para operar


# Regime
REGIME_SMA_PERIOD = 200     # SMA de SPY para regimen
REGIME_CONFIRM_DAYS = 3     # Dias consecutivos para confirmar cambio de regimen

# Positions
NUM_POSITIONS = 5           # Posiciones en RISK_ON
NUM_POSITIONS_RISK_OFF = 2  # Posiciones en RISK_OFF
HOLD_DAYS = 5               # Dias de hold (trading days)

# Position-level risk
POSITION_STOP_LOSS = -0.08  # -8% por posicion
TRAILING_ACTIVATION = 0.05  # Activar trailing tras +5%
TRAILING_STOP_PCT = 0.03    # Trailing stop: -3% desde max

# Portfolio-level risk
PORTFOLIO_STOP_LOSS = -0.15 # -15% drawdown del portfolio

# Recovery stages (time-based with regime confirmation)
RECOVERY_STAGE_1_DAYS = 63  # 3 meses para stage 1 (leverage 0.3x -> 1.0x, reserva 70%)
RECOVERY_STAGE_2_DAYS = 126 # 6 meses para stage 2 (1.0x -> vol targeting)
# Recovery requires: time elapsed + market in RISK_ON regime

# Leverage & Vol targeting
TARGET_VOL = 0.15           # 15% anualizado
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 1.0          # Production: no leverage (broker margin destroys value)
VOL_LOOKBACK = 20           # Dias para calcular realized vol

# Costs
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06          # 6% anual sobre borrowed
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035         # Fallback fijo (usado si FRED no disponible)
CASH_YIELD_SOURCE = 'AAA'       # Moody's Aaa Corporate Bond Yield (FRED)

# Data
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

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
print("OMNICAPITAL v8 COMPASS")
print("Cross-sectional Momentum, Position-Adjusted Risk Scaling")
print("=" * 80)
print(f"\nBroad pool: {len(BROAD_POOL)} stocks | Top-{TOP_N} annual rotation")
print(f"Signal: Momentum {MOMENTUM_LOOKBACK}d (skip {MOMENTUM_SKIP}d) + Inverse Vol sizing")
print(f"Regime: SPY SMA{REGIME_SMA_PERIOD} | Vol target: {TARGET_VOL:.0%}")
print(f"Hold: {HOLD_DAYS}d | Pos stop: {POSITION_STOP_LOSS:.0%} | Port stop: {PORTFOLIO_STOP_LOSS:.0%}")
print(f"Cash yield: Moody's Aaa IG Corporate (FRED, variable)")
print()


# ============================================================================
# DATA FUNCTIONS
# ============================================================================

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
    """Download SPY data for regime filter"""
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


def download_cash_yield() -> pd.Series:
    """Download Moody's Aaa Corporate Bond Yield from FRED.
    Returns a daily Series of yield rates (annual %, forward-filled from monthly).
    Falls back to fixed CASH_YIELD_RATE if FRED unavailable."""
    cache_file = 'data_cache/moody_aaa_yield.csv'

    if os.path.exists(cache_file):
        print("[Cache] Loading Moody's Aaa yield data...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        daily = df['yield_pct'].resample('D').ffill()
        print(f"  {len(daily)} daily rates, avg {daily.mean():.2f}%")
        return daily

    print("[Download] Downloading Moody's Aaa yield from FRED...")
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=1999-01-01&coed=2026-12-31'
        df = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
        df.columns = ['yield_pct']
        os.makedirs('data_cache', exist_ok=True)
        df.to_csv(cache_file)
        daily = df['yield_pct'].resample('D').ffill()
        print(f"  {len(daily)} daily rates, avg {daily.mean():.2f}%")
        return daily
    except Exception as e:
        print(f"  FRED download failed: {e}. Using fixed {CASH_YIELD_RATE:.1%}")
        return None


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


# ============================================================================
# SIGNAL & REGIME FUNCTIONS
# ============================================================================

def compute_regime(spy_data: pd.DataFrame) -> pd.Series:
    """
    Compute market regime based on SPY vs SMA200.
    Returns Series: True = RISK_ON, False = RISK_OFF.
    Requires REGIME_CONFIRM_DAYS consecutive days to switch.
    """
    spy_close = spy_data['Close']
    sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean()

    # Raw signal: SPY above SMA200
    raw_signal = spy_close > sma200

    # Require N consecutive days to confirm regime change
    regime = pd.Series(index=spy_close.index, dtype=bool)
    regime.iloc[:REGIME_SMA_PERIOD] = True  # Default RISK_ON until enough data

    current_regime = True  # Start RISK_ON
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


def compute_momentum_scores(price_data: Dict[str, pd.DataFrame],
                           tradeable: List[str],
                           date: pd.Timestamp,
                           all_dates: List[pd.Timestamp],
                           date_idx: int) -> Dict[str, float]:
    """
    Compute cross-sectional momentum score for each stock.
    Score = momentum_90d (excluding last 5 days) - skip_5d_return
    High score = strong medium-term momentum + recent pullback = buy signal
    """
    scores = {}

    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue

        # Need at least momentum_lookback + skip days of history
        needed = MOMENTUM_LOOKBACK + MOMENTUM_SKIP
        # Get the index position in this stock's data
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue

        if sym_idx < needed:
            continue

        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - MOMENTUM_SKIP]  # 5 days ago
        close_lookback = df['Close'].iloc[sym_idx - MOMENTUM_LOOKBACK]  # 90 days ago

        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue

        # Medium-term momentum (90d return, excluding last 5d)
        momentum_90d = (close_skip / close_lookback) - 1.0

        # Short-term return (last 5 days) - we want stocks that dipped recently
        skip_5d = (close_today / close_skip) - 1.0

        # Score: high momentum + recent dip = buy
        score = momentum_90d - skip_5d
        scores[symbol] = score

    return scores


def compute_volatility_weights(price_data: Dict[str, pd.DataFrame],
                               selected: List[str],
                               date: pd.Timestamp) -> Dict[str, float]:
    """
    Compute inverse-volatility weights for selected stocks.
    Lower vol stocks get higher weight.
    """
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

        # 20-day realized volatility
        returns = df['Close'].iloc[sym_idx - VOL_LOOKBACK:sym_idx + 1].pct_change().dropna()
        if len(returns) < VOL_LOOKBACK - 2:
            continue

        vol = returns.std() * np.sqrt(252)
        if vol > 0.01:  # Minimum vol to avoid division issues
            vols[symbol] = vol

    if not vols:
        # Fallback: equal weight
        return {s: 1.0 / len(selected) for s in selected}

    # Inverse vol weights
    raw_weights = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw_weights.values())
    return {s: w / total for s, w in raw_weights.items()}


def compute_dynamic_leverage(spy_data: pd.DataFrame, date: pd.Timestamp) -> float:
    """
    Compute leverage via volatility targeting.
    leverage = target_vol / realized_vol, clipped to [min, max]
    """
    if date not in spy_data.index:
        return 1.0

    idx = spy_data.index.get_loc(date)
    if idx < VOL_LOOKBACK + 1:
        return 1.0

    # Use SPY realized vol as portfolio vol proxy
    returns = spy_data['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
    if len(returns) < VOL_LOOKBACK - 2:
        return 1.0

    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol < 0.01:
        return LEVERAGE_MAX

    leverage = TARGET_VOL / realized_vol
    return max(LEVERAGE_MIN, min(LEVERAGE_MAX, leverage))


# ============================================================================
# BACKTEST
# ============================================================================

def get_tradeable_symbols(price_data: Dict[str, pd.DataFrame],
                         date: pd.Timestamp,
                         first_date: pd.Timestamp,
                         annual_universe: Dict[int, List[str]]) -> List[str]:
    """Return tradeable symbols from top-40 for that year"""
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


def run_backtest(price_data: Dict[str, pd.DataFrame],
                 annual_universe: Dict[int, List[str]],
                 spy_data: pd.DataFrame,
                 cash_yield_daily: Optional[pd.Series] = None) -> Dict:
    """Run COMPASS backtest"""

    print("\n" + "=" * 80)
    print("RUNNING COMPASS BACKTEST")
    print("=" * 80)

    # Get all trading dates
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    # Compute regime
    print("\nComputing market regime (SPY vs SMA200)...")
    regime = compute_regime(spy_data)

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

    # Portfolio state
    cash = float(INITIAL_CAPITAL)
    positions = {}  # symbol -> {entry_price, shares, entry_date, entry_idx, high_price}
    portfolio_values = []
    trades = []
    stop_events = []

    peak_value = float(INITIAL_CAPITAL)
    in_protection_mode = False
    protection_stage = 0     # 0=none, 1=stage1 (0.3x), 2=stage2 (1.0x)
    stop_loss_day_index = None
    post_stop_base = None

    risk_on_days = 0
    risk_off_days = 0

    current_year = None

    for i, date in enumerate(all_dates):
        # Annual rotation check
        if date.year != current_year:
            current_year = date.year

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # --- Calculate portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # --- Update peak ---
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # --- Check recovery from protection mode ---
        # Recovery is time-based + regime confirmation (no absolute growth requirement)
        # This prevents getting trapped for years after a deep drawdown
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
                peak_value = portfolio_value  # Reset peak from here
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
            print(f"\n  [STOP LOSS] {date.strftime('%Y-%m-%d')}: DD {drawdown:.1%} | Value: ${portfolio_value:,.0f}")

            # Close ALL positions
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
                current_leverage = 0.3  # Solo 30%, reservar 70% para estabilización
            else:  # stage 2
                max_positions = 3
                current_leverage = 1.0
        elif not is_risk_on:
            max_positions = NUM_POSITIONS_RISK_OFF
            current_leverage = 1.0
        else:
            max_positions = NUM_POSITIONS
            current_leverage = compute_dynamic_leverage(spy_data, date)

        # --- Daily costs (margin on borrowed amount) ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # --- Cash yield (Moody's Aaa corporate bond yield on uninvested cash) ---
        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        # --- Close positions ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            # 1. Hold time expired (5 trading days)
            days_held = i - pos['entry_idx']
            if days_held >= HOLD_DAYS:
                exit_reason = 'hold_expired'

            # 2. Position stop loss (-8%)
            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'

            # 3. Trailing stop
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            # 4. Stock no longer in top-40
            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            # 5. Excess positions (regime changed to risk_off or protection)
            if exit_reason is None and len(positions) > max_positions:
                # Close the worst-performing position
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

        # --- Open new positions ---
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            # Compute momentum scores
            scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)

            # Filter out stocks already in portfolio
            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available_scores) >= needed:
                # Select top N by score
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]

                # Compute inverse-vol weights
                weights = compute_volatility_weights(price_data, selected, date)

                # Effective capital with leverage
                effective_capital = cash * current_leverage * 0.95  # 5% buffer

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue

                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue

                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = effective_capital * weight

                    # Cap at a reasonable fraction
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

        # --- Record daily snapshot ---
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
            'in_protection': in_protection_mode,
            'risk_on': is_risk_on,
            'universe_size': len(tradeable_symbols)
        })

        # Annual progress log
        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [PROTECTION S{protection_stage}]" if in_protection_mode else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str} | "
                  f"Pos: {len(positions)}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'annual_universe': annual_universe,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results: Dict) -> Dict:
    """Calculate performance metrics"""
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

    # Sortino (downside only)
    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0

    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    avg_winner = trades_df.loc[trades_df['pnl'] > 0, 'pnl'].mean() if (trades_df['pnl'] > 0).any() else 0
    avg_loser = trades_df.loc[trades_df['pnl'] < 0, 'pnl'].mean() if (trades_df['pnl'] < 0).any() else 0

    # Exit reason breakdown
    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}

    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100

    risk_off_pct = results['risk_off_days'] / (results['risk_on_days'] + results['risk_off_days']) * 100

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
        'trades': len(trades_df),
        'exit_reasons': exit_reasons,
        'stop_events': len(stop_df),
        'protection_days': protection_days,
        'protection_pct': protection_pct,
        'risk_off_pct': risk_off_pct,
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # 1. Download/load data
    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    cash_yield_daily = download_cash_yield()

    # 2. Compute annual top-40
    print("\n--- Computing Annual Top-40 ---")
    annual_universe = compute_annual_top40(price_data)

    # 3. Run backtest
    results = run_backtest(price_data, annual_universe, spy_data, cash_yield_daily)

    # 4. Calculate metrics
    metrics = calculate_metrics(results)

    # 5. Print results
    print("\n" + "=" * 80)
    print("RESULTS - OMNICAPITAL v8 COMPASS")
    print("=" * 80)

    print(f"\n--- Performance ---")
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

    print(f"\n--- Trading ---")
    print(f"Trades executed:        {metrics['trades']:>15,}")
    print(f"Win rate:               {metrics['win_rate']:>15.2%}")
    print(f"Avg P&L per trade:      ${metrics['avg_trade']:>15,.2f}")
    print(f"Avg winner:             ${metrics['avg_winner']:>15,.2f}")
    print(f"Avg loser:              ${metrics['avg_loser']:>15,.2f}")

    print(f"\n--- Exit Reasons ---")
    for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: -x[1]):
        print(f"  {reason:25s}: {count:>6,} ({count/metrics['trades']*100:.1f}%)")

    print(f"\n--- Risk Management ---")
    print(f"Stop loss events:       {metrics['stop_events']:>15,}")
    print(f"Days in protection:     {metrics['protection_days']:>15,} ({metrics['protection_pct']:.1f}%)")
    print(f"Risk-off days:          {metrics['risk_off_pct']:>14.1f}%")

    print(f"\n--- Annual Returns ---")
    if len(metrics['annual_returns']) > 0:
        print(f"Best year:              {metrics['best_year']:>15.2%}")
        print(f"Worst year:             {metrics['worst_year']:>15.2%}")
        print(f"Positive years:         {(metrics['annual_returns'] > 0).sum()}/{len(metrics['annual_returns'])}")

    # 6. Comparison with v6
    print("\n" + "=" * 80)
    print("COMPARISON vs v6 TOP-40 ROTATION")
    print("=" * 80)
    print(f"{'Metric':<25} {'v6':>12} {'v8 COMPASS':>12} {'Change':>12}")
    print("-" * 65)
    v6_cagr = 0.054
    v6_sharpe = 0.22
    v6_maxdd = -0.594
    v6_stops = 9
    print(f"{'CAGR':<25} {v6_cagr:>11.2%} {metrics['cagr']:>11.2%} {metrics['cagr']-v6_cagr:>+11.2%}")
    print(f"{'Sharpe':<25} {v6_sharpe:>12.2f} {metrics['sharpe']:>12.2f} {metrics['sharpe']-v6_sharpe:>+12.2f}")
    print(f"{'Max Drawdown':<25} {v6_maxdd:>11.1%} {metrics['max_drawdown']:>11.1%} {metrics['max_drawdown']-v6_maxdd:>+11.1%}")
    print(f"{'Stop Events':<25} {v6_stops:>12} {metrics['stop_events']:>12}")

    # 7. Save results
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/v8_compass_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/v8_compass_trades.csv', index=False)

    output_file = 'results_v8_compass.pkl'
    with open(output_file, 'wb') as f:
        pickle.dump({
            'params': {
                'momentum_lookback': MOMENTUM_LOOKBACK,
                'momentum_skip': MOMENTUM_SKIP,
                'hold_days': HOLD_DAYS,
                'num_positions': NUM_POSITIONS,
                'target_vol': TARGET_VOL,
                'regime_sma': REGIME_SMA_PERIOD,
                'position_stop': POSITION_STOP_LOSS,
                'portfolio_stop': PORTFOLIO_STOP_LOSS,
                'trailing_activation': TRAILING_ACTIVATION,
                'trailing_stop': TRAILING_STOP_PCT,
            },
            'metrics': metrics,
            'portfolio_values': results['portfolio_values'],
            'trades': results['trades'],
            'stop_events': results['stop_events'],
            'annual_universe': results['annual_universe']
        }, f)

    print(f"\nResults saved: {output_file}")
    print(f"Daily CSV: backtests/v8_compass_daily.csv")
    print(f"Trades CSV: backtests/v8_compass_trades.csv")

    print("\n" + "=" * 80)
    print("COMPASS BACKTEST COMPLETE")
    print("=" * 80)
