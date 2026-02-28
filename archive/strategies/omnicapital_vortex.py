"""
OmniCapital VORTEX - Velocity-Optimized Rotational Trading with EXponential Momentum
======================================================================================
A challenger algorithm designed to beat COMPASS v8.2's 16.04% CAGR.

Core thesis: Combine TWO orthogonal momentum signals to improve stock selection:
  1. VELOCITY: Standard price momentum (similar to COMPASS)
  2. ACCELERATION: Momentum of momentum (2nd derivative) — captures stocks
     that are not just rising, but rising at an increasing rate

Additional edges:
  - Dual timeframe confirmation (short + medium momentum must agree)
  - Volatility-adjusted scoring (high momentum in low vol = better signal)
  - Tighter trailing stops (+3% activation, -2% trail) to protect faster
  - Same risk framework: SPY regime, vol targeting, portfolio stops

Target: Beat COMPASS 16.04% CAGR with comparable or better risk metrics.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List, Optional
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETERS
# ============================================================================

# Universe
TOP_N = 40
MIN_AGE_DAYS = 63

# Signal: Dual timeframe + acceleration
MOM_LONG = 120              # Long momentum lookback (4 months)
MOM_SHORT = 30              # Short momentum lookback (6 weeks)
MOM_SKIP = 5                # Skip last 5 days (reversal avoidance)
ACCEL_LOOKBACK = 60         # Acceleration: compare momentum now vs 60d ago
MIN_MOMENTUM_STOCKS = 15

# Scoring weights
W_VELOCITY = 0.40           # Weight for raw momentum score
W_ACCELERATION = 0.35       # Weight for momentum acceleration
W_VOL_ADJ = 0.25            # Weight for vol-adjusted momentum (momentum/vol)

# Regime
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3

# Positions
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5

# Risk management
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.03  # Tighter: activate at +3% (vs COMPASS +5%)
TRAILING_STOP_PCT = 0.02    # Tighter: trail at -2% (vs COMPASS -3%)
PORTFOLIO_STOP_LOSS = -0.15

# Recovery
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126

# Leverage & Vol targeting
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 2.0
VOL_LOOKBACK = 20

# Costs
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001

# Data
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# Same broad pool as COMPASS
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

print("=" * 80)
print("OMNICAPITAL VORTEX")
print("Velocity-Optimized Rotational Trading with EXponential Momentum")
print("=" * 80)
print(f"\nBroad pool: {len(BROAD_POOL)} stocks | Top-{TOP_N} annual rotation")
print(f"Signal: Velocity({MOM_LONG}d/{MOM_SHORT}d) + Acceleration({ACCEL_LOOKBACK}d) + VolAdj")
print(f"Weights: Velocity {W_VELOCITY:.0%} | Acceleration {W_ACCELERATION:.0%} | VolAdj {W_VOL_ADJ:.0%}")
print(f"Regime: SPY SMA{REGIME_SMA_PERIOD} | Vol target: {TARGET_VOL:.0%}")
print(f"Hold: {HOLD_DAYS}d | Trail: +{TRAILING_ACTIVATION:.0%}/{TRAILING_STOP_PCT:.0%}")
print()


# ============================================================================
# DATA
# ============================================================================

def download_broad_pool():
    cache_file = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'
    if os.path.exists(cache_file):
        print("[Cache] Loading broad pool data...")
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
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
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)
    return data


def download_spy():
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading SPY data...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def compute_annual_top40(price_data):
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))
    annual_universe = {}
    for year in years:
        if year == years[0]:
            re = pd.Timestamp(f'{year}-02-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            rs = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        else:
            re = pd.Timestamp(f'{year}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            rs = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        scores = {}
        for symbol, df in price_data.items():
            mask = (df.index >= rs) & (df.index < re)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            scores[symbol] = (window['Close'] * window['Volume']).mean()
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
# VORTEX SIGNAL
# ============================================================================

def compute_vortex_scores(price_data, tradeable, date):
    """
    Compute VORTEX composite score for each stock.

    Three components:
    1. VELOCITY: Long momentum (120d) minus short-term reversal (5d skip)
       → Captures strong medium-term trend with recent dip entry
    2. ACCELERATION: Current short momentum(30d) minus previous short momentum(30d, 60d ago)
       → Captures stocks where momentum is INCREASING (2nd derivative > 0)
    3. VOL_ADJUSTED: Momentum / realized volatility
       → Prefers stocks with high momentum AND low noise

    Final score = W_VELOCITY * z(velocity) + W_ACCELERATION * z(acceleration) + W_VOL_ADJ * z(vol_adj)
    Where z() = cross-sectional z-score normalization
    """
    raw = {}

    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        try:
            idx = df.index.get_loc(date)
        except KeyError:
            continue

        needed = max(MOM_LONG, ACCEL_LOOKBACK + MOM_SHORT) + MOM_SKIP + 10
        if idx < needed:
            continue

        close = df['Close']
        c_today = close.iloc[idx]
        c_skip = close.iloc[idx - MOM_SKIP]            # 5 days ago
        c_long = close.iloc[idx - MOM_LONG]             # 120 days ago
        c_short = close.iloc[idx - MOM_SHORT]           # 30 days ago
        c_accel_base = close.iloc[idx - ACCEL_LOOKBACK]  # 60 days ago
        c_accel_prev = close.iloc[idx - ACCEL_LOOKBACK - MOM_SHORT]  # 90 days ago

        if any(v <= 0 for v in [c_today, c_skip, c_long, c_short, c_accel_base, c_accel_prev]):
            continue

        # 1. VELOCITY: long momentum with skip (like COMPASS but 120d)
        mom_long = (c_skip / c_long) - 1.0
        skip_ret = (c_today / c_skip) - 1.0
        velocity = mom_long - skip_ret

        # 2. ACCELERATION: current 30d momentum vs 30d momentum 60 days ago
        mom_current = (c_skip / c_short) - 1.0          # recent 30d momentum (skip-adjusted)
        mom_previous = (c_accel_base / c_accel_prev) - 1.0  # 30d momentum from 60d ago
        acceleration = mom_current - mom_previous

        # 3. VOL-ADJUSTED: momentum per unit of risk
        returns_20d = close.iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
        if len(returns_20d) < VOL_LOOKBACK - 2:
            continue
        vol = returns_20d.std() * np.sqrt(252)
        if vol < 0.01:
            vol = 0.01
        vol_adj = mom_long / vol

        raw[symbol] = {
            'velocity': velocity,
            'acceleration': acceleration,
            'vol_adj': vol_adj,
        }

    if len(raw) < MIN_MOMENTUM_STOCKS:
        return {}

    # Cross-sectional z-score normalization
    symbols = list(raw.keys())
    for component in ['velocity', 'acceleration', 'vol_adj']:
        vals = np.array([raw[s][component] for s in symbols])
        mu = vals.mean()
        sigma = vals.std()
        if sigma < 1e-8:
            sigma = 1.0
        for s in symbols:
            raw[s][f'{component}_z'] = (raw[s][component] - mu) / sigma

    # Composite score
    scores = {}
    for s in symbols:
        scores[s] = (W_VELOCITY * raw[s]['velocity_z'] +
                     W_ACCELERATION * raw[s]['acceleration_z'] +
                     W_VOL_ADJ * raw[s]['vol_adj_z'])

    return scores


# ============================================================================
# SHARED FUNCTIONS (same as COMPASS)
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


def get_tradeable(price_data, date, first_date, annual_universe):
    eligible = set(annual_universe.get(date.year, []))
    tradeable = []
    for symbol in eligible:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        days_since = (date - df.index[0]).days
        if date <= first_date + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since >= MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


# ============================================================================
# BACKTEST
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data):
    print("\n" + "=" * 80)
    print("RUNNING VORTEX BACKTEST")
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

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []
    peak_value = float(INITIAL_CAPITAL)
    in_protection_mode = False
    protection_stage = 0
    stop_loss_day_index = None
    risk_on_days = 0
    risk_off_days = 0

    for i, date in enumerate(all_dates):
        tradeable_symbols = get_tradeable(price_data, date, first_date, annual_universe)

        # Portfolio value
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                portfolio_value += pos['shares'] * price_data[symbol].loc[date, 'Close']

        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # Recovery
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = bool(regime.loc[date]) if date in regime.index else True
            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2
                print(f"  [RECOVERY S1] {date.strftime('%Y-%m-%d')}: Stage 2 | ${portfolio_value:,.0f}")
            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                print(f"  [RECOVERY S2] {date.strftime('%Y-%m-%d')}: Full recovery | ${portfolio_value:,.0f}")

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # Portfolio stop
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({'date': date, 'value': portfolio_value, 'dd': drawdown})
            print(f"\n  [STOP LOSS] {date.strftime('%Y-%m-%d')}: DD {drawdown:.1%} | ${portfolio_value:,.0f}")
            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    ep = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    proceeds = pos['shares'] * ep
                    comm = pos['shares'] * COMMISSION_PER_SHARE
                    cash += proceeds - comm
                    pnl = (ep - pos['entry_price']) * pos['shares'] - comm
                    trades.append({
                        'symbol': symbol, 'entry_date': pos['entry_date'],
                        'exit_date': date, 'exit_reason': 'portfolio_stop',
                        'pnl': pnl, 'return': pnl / (pos['entry_price'] * pos['shares'])
                    })
                del positions[symbol]
            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i

        # Regime
        is_risk_on = bool(regime.loc[date]) if date in regime.index else True
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # Max positions & leverage
        if in_protection_mode:
            if protection_stage == 1:
                max_positions = 2; current_leverage = 0.3
            else:
                max_positions = 3; current_leverage = 1.0
        elif not is_risk_on:
            max_positions = NUM_POSITIONS_RISK_OFF; current_leverage = 1.0
        else:
            max_positions = NUM_POSITIONS
            current_leverage = compute_dynamic_leverage(spy_data, date)

        # Margin cost
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            cash -= MARGIN_RATE / 252 * borrowed

        # --- CLOSE POSITIONS ---
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
                pos_rets = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        pos_rets[s] = (price_data[s].loc[date, 'Close'] - p['entry_price']) / p['entry_price']
                worst = min(pos_rets, key=pos_rets.get)
                if symbol == worst:
                    exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                comm = shares * COMMISSION_PER_SHARE
                cash += proceeds - comm
                pnl = (current_price - pos['entry_price']) * shares - comm
                trades.append({
                    'symbol': symbol, 'entry_date': pos['entry_date'],
                    'exit_date': date, 'exit_reason': exit_reason,
                    'pnl': pnl, 'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # --- OPEN POSITIONS (VORTEX SIGNAL) ---
        needed = max_positions - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            scores = compute_vortex_scores(price_data, tradeable_symbols, date)
            available = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available) >= needed:
                ranked = sorted(available.items(), key=lambda x: x[1], reverse=True)
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
                    max_per_pos = cash * 0.40
                    position_value = min(position_value, max_per_pos)
                    shares = position_value / entry_price
                    cost = shares * entry_price
                    comm = shares * COMMISSION_PER_SHARE
                    if cost + comm <= cash * 0.90:
                        positions[symbol] = {
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + comm

        portfolio_values.append({
            'date': date, 'value': portfolio_value, 'cash': cash,
            'positions': len(positions), 'drawdown': drawdown,
            'leverage': current_leverage, 'in_protection': in_protection_mode,
            'risk_on': is_risk_on,
        })

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [PROT S{protection_stage}]" if in_protection_mode else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'],
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results):
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']
    initial = INITIAL_CAPITAL
    final = df['value'].iloc[-1]
    years = len(df) / 252
    cagr = (final / initial) ** (1 / years) - 1
    rets = df['value'].pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    max_dd = df['drawdown'].min()
    sharpe = cagr / vol if vol > 0 else 0
    downside = rets[rets < 0]
    ds_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else vol
    sortino = cagr / ds_vol if ds_vol > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    avg_winner = trades_df.loc[trades_df['pnl'] > 0, 'pnl'].mean() if (trades_df['pnl'] > 0).any() else 0
    avg_loser = trades_df.loc[trades_df['pnl'] < 0, 'pnl'].mean() if (trades_df['pnl'] < 0).any() else 0
    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}
    prot_days = df['in_protection'].sum()
    prot_pct = prot_days / len(df) * 100
    risk_off_pct = results['risk_off_days'] / (results['risk_on_days'] + results['risk_off_days']) * 100
    ann = df['value'].resample('YE').last().pct_change().dropna()
    return {
        'initial': initial, 'final': final,
        'total_return': (final - initial) / initial,
        'years': years, 'cagr': cagr, 'vol': vol,
        'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar,
        'max_dd': max_dd, 'win_rate': win_rate,
        'avg_trade': avg_trade, 'avg_winner': avg_winner, 'avg_loser': avg_loser,
        'trades': len(trades_df), 'exit_reasons': exit_reasons,
        'stops': len(results['stop_events']),
        'prot_days': prot_days, 'prot_pct': prot_pct,
        'risk_off_pct': risk_off_pct,
        'best_year': ann.max() if len(ann) > 0 else 0,
        'worst_year': ann.min() if len(ann) > 0 else 0,
        'positive_years': f"{(ann > 0).sum()}/{len(ann)}" if len(ann) > 0 else "0/0",
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")
    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    print("\n--- Computing Annual Top-40 ---")
    annual_universe = compute_annual_top40(price_data)

    results = run_backtest(price_data, annual_universe, spy_data)
    m = calculate_metrics(results)

    # COMPASS reference (v8.2 production numbers)
    compass = {
        'cagr': 0.1604, 'sharpe': 0.770, 'sortino': 0.987,
        'max_dd': -0.288, 'calmar': 0.557, 'final': 4_822_626,
        'win_rate': 0.553, 'stops': 11,
    }

    print("\n" + "=" * 80)
    print("RESULTS - OMNICAPITAL VORTEX")
    print("=" * 80)

    print(f"\n--- Performance ---")
    print(f"Initial capital:        ${m['initial']:>15,.0f}")
    print(f"Final value:            ${m['final']:>15,.2f}")
    print(f"Total return:           {m['total_return']:>15.2%}")
    print(f"CAGR:                   {m['cagr']:>15.2%}")
    print(f"Volatility (annual):    {m['vol']:>15.2%}")

    print(f"\n--- Risk-Adjusted ---")
    print(f"Sharpe ratio:           {m['sharpe']:>15.2f}")
    print(f"Sortino ratio:          {m['sortino']:>15.2f}")
    print(f"Calmar ratio:           {m['calmar']:>15.2f}")
    print(f"Max drawdown:           {m['max_dd']:>15.2%}")

    print(f"\n--- Trading ---")
    print(f"Trades executed:        {m['trades']:>15,}")
    print(f"Win rate:               {m['win_rate']:>15.2%}")
    print(f"Avg P&L per trade:      ${m['avg_trade']:>15,.2f}")
    print(f"Avg winner:             ${m['avg_winner']:>15,.2f}")
    print(f"Avg loser:              ${m['avg_loser']:>15,.2f}")

    print(f"\n--- Exit Reasons ---")
    for reason, count in sorted(m['exit_reasons'].items(), key=lambda x: -x[1]):
        print(f"  {reason:25s}: {count:>6,} ({count/m['trades']*100:.1f}%)")

    print(f"\n--- Risk Management ---")
    print(f"Stop loss events:       {m['stops']:>15,}")
    print(f"Days in protection:     {m['prot_days']:>15,} ({m['prot_pct']:.1f}%)")
    print(f"Risk-off days:          {m['risk_off_pct']:>14.1f}%")

    print(f"\n--- Annual Returns ---")
    print(f"Best year:              {m['best_year']:>15.2%}")
    print(f"Worst year:             {m['worst_year']:>15.2%}")
    print(f"Positive years:         {m['positive_years']}")

    # ---- HEAD TO HEAD ----
    print("\n" + "=" * 80)
    print("HEAD TO HEAD: VORTEX vs COMPASS v8.2")
    print("=" * 80)
    print(f"{'Metric':<25} {'COMPASS':>15} {'VORTEX':>15} {'Delta':>15}")
    print("-" * 70)
    c_cagr = compass['cagr']; v_cagr = m['cagr']
    c_sh = compass['sharpe']; v_sh = m['sharpe']
    c_dd = compass['max_dd']; v_dd = m['max_dd']
    c_cal = compass['calmar']; v_cal = m['calmar']
    c_wr = compass['win_rate']; v_wr = m['win_rate']
    print(f"{'CAGR':<25} {c_cagr:>14.2%} {v_cagr:>14.2%} {v_cagr-c_cagr:>+14.2%}")
    print(f"{'Sharpe':<25} {c_sh:>15.3f} {v_sh:>15.3f} {v_sh-c_sh:>+15.3f}")
    print(f"{'Sortino':<25} {compass['sortino']:>15.3f} {m['sortino']:>15.3f} {m['sortino']-compass['sortino']:>+15.3f}")
    print(f"{'Max Drawdown':<25} {c_dd:>14.1%} {v_dd:>14.1%} {v_dd-c_dd:>+14.1%}")
    print(f"{'Calmar':<25} {c_cal:>15.3f} {v_cal:>15.3f} {v_cal-c_cal:>+15.3f}")
    fin_c = f"${compass['final']:,.0f}"; fin_v = f"${m['final']:,.0f}"
    print(f"{'Final Value':<25} {fin_c:>15} {fin_v:>15}")
    print(f"{'Win Rate':<25} {c_wr:>14.1%} {v_wr:>14.1%} {v_wr-c_wr:>+14.1%}")
    print(f"{'Stop Events':<25} {compass['stops']:>15} {m['stops']:>15}")

    winner = "VORTEX" if v_cagr > c_cagr else "COMPASS"
    print(f"\n  >>> CAGR WINNER: {winner} <<<")
    if v_cagr > c_cagr:
        print(f"  VORTEX beats COMPASS by {v_cagr - c_cagr:.2%} CAGR")
    else:
        print(f"  COMPASS wins by {c_cagr - v_cagr:.2%} CAGR")

    # Save
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/vortex_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/vortex_trades.csv', index=False)

    print("\n" + "=" * 80)
    print("VORTEX BACKTEST COMPLETE")
    print("=" * 80)
