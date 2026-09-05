"""
NIGHTSHIFT - Overnight Close-to-Open Trading Strategy
======================================================
Captures the overnight return premium by buying ETFs at market close
and selling at next market open. Complements COMPASS v8.2 daytime strategy.

Instruments: SPY, QQQ (equities) | TLT, GLD (safe haven)
Signal: Regime + VIX + Prior-day momentum + Day-of-week
Capital: $50k separate pool, no leverage
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import os
import time
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# NIGHTSHIFT PARAMETERS
# ============================================================================

# Instruments
INSTRUMENTS = ['SPY', 'QQQ', 'TLT', 'GLD']

# Signal thresholds
VIX_HIGH_THRESHOLD = 25
VIX_EXTREME_THRESHOLD = 35
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3

# Prior-day intraday return thresholds
BIG_UP_THRESHOLD = 0.01       # SPY intraday > +1%
BIG_DOWN_THRESHOLD = -0.01    # SPY intraday < -1%

# Day-of-week (0=Mon)
WEAK_NIGHTS = [0]             # Monday night historically weaker

# Allocation profiles
RISK_ON_WEIGHTS = {'SPY': 0.60, 'QQQ': 0.40, 'TLT': 0.0, 'GLD': 0.0}
NEUTRAL_WEIGHTS = {'SPY': 0.0, 'QQQ': 0.0, 'TLT': 0.50, 'GLD': 0.50}

# Circuit breaker
CIRCUIT_BREAKER_THRESHOLD = -0.03   # -3% overnight loss
CIRCUIT_BREAKER_NIGHTS = 5          # Flat for 5 nights after trigger

# Capital
INITIAL_CAPITAL = 50_000
POSITION_SIZE_PCT = 1.0     # Use 100% of capital (no leverage)

# Costs
COMMISSION_PER_TRADE = 1.00  # $1 per trade
SLIPPAGE_BPS = 2             # 0.02% per side

# Data
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'


# ============================================================================
# DATA FUNCTIONS
# ============================================================================

def download_instrument(symbol, ticker_symbol=None):
    """Download/load cached OHLCV data for an instrument"""
    if ticker_symbol is None:
        ticker_symbol = symbol
    cache_file = f'data_cache/{symbol}_{START_DATE}_{END_DATE}.csv'

    if os.path.exists(cache_file):
        print(f"  [Cache] {symbol}")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)

    print(f"  [Download] {symbol} ({ticker_symbol})...")
    df = yf.download(ticker_symbol, start=START_DATE, end=END_DATE, progress=False)
    if not df.empty:
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        os.makedirs('data_cache', exist_ok=True)
        df.to_csv(cache_file)
    return df


def download_all_data():
    """Download all instruments + VIX"""
    print("Loading instrument data...")
    data = {}
    for sym in INSTRUMENTS:
        df = download_instrument(sym)
        if not df.empty:
            data[sym] = df
    data['VIX'] = download_instrument('VIX', '^VIX')
    print(f"Instruments loaded: {list(data.keys())}")
    for sym, df in data.items():
        print(f"  {sym}: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')} ({len(df)} days)")
    return data


# ============================================================================
# SIGNAL FUNCTIONS
# ============================================================================

def compute_regime(spy_data):
    """SPY > SMA200 with 3-day confirmation (identical to COMPASS v8)"""
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


def compute_nightshift_signal(regime_on, vix_level, spy_intraday_return,
                               day_of_week, circuit_breaker_active):
    """
    Determine nightly allocation signal.
    Returns: 'RISK_ON', 'NEUTRAL', or 'FLAT'
    """
    # Priority 1: Circuit breaker
    if circuit_breaker_active:
        return 'FLAT'

    # Priority 2: Bear market regime
    if not regime_on:
        return 'FLAT'

    # Priority 3: Monday night (historically weaker)
    if day_of_week in WEAK_NIGHTS:
        return 'NEUTRAL'

    # Priority 4: Extreme VIX
    if not pd.isna(vix_level) and vix_level > VIX_EXTREME_THRESHOLD:
        return 'NEUTRAL'

    # Priority 5: High VIX + down day = strong overnight bounce
    if not pd.isna(vix_level) and vix_level > VIX_HIGH_THRESHOLD:
        if spy_intraday_return < BIG_DOWN_THRESHOLD:
            return 'RISK_ON'
        return 'RISK_ON'

    # Priority 6: Big up intraday = mean reversion overnight
    if spy_intraday_return > BIG_UP_THRESHOLD:
        return 'NEUTRAL'

    # Default: capture overnight premium
    return 'RISK_ON'


def get_allocation_weights(signal, available_instruments, date):
    """Get instrument weights based on signal and available data"""
    if signal == 'FLAT':
        return {}

    if signal == 'RISK_ON':
        base = RISK_ON_WEIGHTS
    else:  # NEUTRAL
        base = NEUTRAL_WEIGHTS

    # Filter to available instruments
    weights = {s: w for s, w in base.items() if s in available_instruments and w > 0}

    if not weights:
        return {}

    # Renormalize if some instruments missing
    total = sum(weights.values())
    if total > 0 and abs(total - 1.0) > 0.01:
        weights = {s: w / total for s, w in weights.items()}

    return weights


# ============================================================================
# BACKTEST ENGINE
# ============================================================================

def run_nightshift_backtest(data, regime):
    """Run overnight close-to-open backtest"""

    print(f"\n{'='*60}")
    print(f"  RUNNING NIGHTSHIFT BACKTEST")
    print(f"{'='*60}")

    spy_data = data['SPY']
    vix_data = data.get('VIX', pd.DataFrame())

    # Use SPY dates as the master calendar
    all_dates = spy_data.index.tolist()

    # Start after regime warmup (200 days)
    start_idx = REGIME_SMA_PERIOD + 10

    cash = float(INITIAL_CAPITAL)
    portfolio_values = []
    trades = []
    circuit_breaker_events = []
    circuit_breaker_remaining = 0

    signal_counts = {'RISK_ON': 0, 'NEUTRAL': 0, 'FLAT': 0}

    for i in range(start_idx, len(all_dates) - 1):
        date = all_dates[i]
        next_date = all_dates[i + 1]

        # --- Determine which instruments have data for tonight ---
        available = set()
        for sym in INSTRUMENTS:
            if sym in data:
                df = data[sym]
                if date in df.index and next_date in df.index:
                    close_val = df.loc[date, 'Close']
                    open_val = df.loc[next_date, 'Open']
                    if not pd.isna(close_val) and not pd.isna(open_val) and close_val > 0 and open_val > 0:
                        available.add(sym)

        # --- Inputs for signal ---
        regime_on = bool(regime.loc[date]) if date in regime.index else True

        vix_level = np.nan
        if not vix_data.empty and date in vix_data.index:
            vix_level = vix_data.loc[date, 'Close']

        # SPY intraday return: Close / Open - 1
        spy_intraday = 0.0
        if date in spy_data.index:
            spy_open = spy_data.loc[date, 'Open']
            spy_close = spy_data.loc[date, 'Close']
            if spy_open > 0:
                spy_intraday = (spy_close / spy_open) - 1.0

        day_of_week = date.dayofweek
        cb_active = circuit_breaker_remaining > 0

        # --- Compute signal ---
        signal = compute_nightshift_signal(regime_on, vix_level, spy_intraday,
                                            day_of_week, cb_active)
        signal_counts[signal] += 1

        # --- Get allocation ---
        weights = get_allocation_weights(signal, available, date)

        # --- Compute overnight P&L ---
        overnight_pnl = 0.0
        overnight_details = {}
        total_commission = 0.0
        n_instruments_traded = 0

        if weights:
            for sym, weight in weights.items():
                if weight <= 0 or sym not in available:
                    continue

                close_price = data[sym].loc[date, 'Close']
                open_price = data[sym].loc[next_date, 'Open']
                overnight_ret = (open_price / close_price) - 1.0

                position_value = cash * POSITION_SIZE_PCT * weight
                gross_pnl = position_value * overnight_ret

                # Costs: commission + slippage (both sides)
                commission = COMMISSION_PER_TRADE
                slippage = position_value * (SLIPPAGE_BPS / 10000) * 2  # buy + sell
                net_pnl = gross_pnl - commission - slippage

                overnight_pnl += net_pnl
                total_commission += commission + slippage
                overnight_details[sym] = {
                    'weight': weight,
                    'overnight_return': overnight_ret,
                    'pnl': net_pnl,
                }
                n_instruments_traded += 1

        # --- Update capital ---
        cash += overnight_pnl
        if cash < 0:
            cash = 0  # Safeguard

        # --- Drawdown ---
        peak = max(pv['value'] for pv in portfolio_values) if portfolio_values else INITIAL_CAPITAL
        peak = max(peak, cash)
        drawdown = (cash - peak) / peak if peak > 0 else 0

        # --- Circuit breaker check ---
        if overnight_pnl != 0:
            overnight_return_pct = overnight_pnl / (cash - overnight_pnl) if (cash - overnight_pnl) > 0 else 0
            if overnight_return_pct < CIRCUIT_BREAKER_THRESHOLD:
                circuit_breaker_remaining = CIRCUIT_BREAKER_NIGHTS
                circuit_breaker_events.append({
                    'date': date,
                    'loss': overnight_return_pct,
                    'value': cash,
                })
                print(f"  [CIRCUIT BREAKER] {date.strftime('%Y-%m-%d')}: "
                      f"Loss {overnight_return_pct:.2%} | Flat for {CIRCUIT_BREAKER_NIGHTS} nights")

        if circuit_breaker_remaining > 0:
            circuit_breaker_remaining -= 1

        # --- Record ---
        spy_overnight = 0.0
        if 'SPY' in available:
            spy_overnight = (data['SPY'].loc[next_date, 'Open'] / data['SPY'].loc[date, 'Close']) - 1.0

        portfolio_values.append({
            'date': date,
            'value': cash,
            'pnl': overnight_pnl,
            'signal': signal,
            'circuit_breaker': cb_active,
            'spy_overnight': spy_overnight,
            'vix_level': vix_level if not pd.isna(vix_level) else 0,
            'regime': regime_on,
            'drawdown': drawdown,
            'n_instruments': n_instruments_traded,
            'costs': total_commission,
        })

        if weights:
            trades.append({
                'date': date,
                'next_open_date': next_date,
                'signal': signal,
                'instruments': ','.join(weights.keys()),
                'overnight_pnl': overnight_pnl,
                'overnight_return': overnight_pnl / (cash - overnight_pnl) if (cash - overnight_pnl) > 0 else 0,
                'capital_after': cash,
                **{f'{s}_weight': weights.get(s, 0) for s in INSTRUMENTS},
                **{f'{s}_ret': overnight_details.get(s, {}).get('overnight_return', 0) for s in INSTRUMENTS},
            })

        # Progress
        if (i - start_idx) % (252 * 5) == 0 and i > start_idx:
            print(f"  Day {i}: ${cash:,.0f} | DD: {drawdown:.1%} | Signal: {signal}")

    final_val = cash
    print(f"  DONE: ${final_val:,.0f} | Trades: {len(trades)} | "
          f"CB events: {len(circuit_breaker_events)}")
    print(f"  Signals: RISK_ON={signal_counts['RISK_ON']} | "
          f"NEUTRAL={signal_counts['NEUTRAL']} | FLAT={signal_counts['FLAT']}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'circuit_breaker_events': circuit_breaker_events,
        'final_value': final_val,
        'signal_counts': signal_counts,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results, label="NIGHTSHIFT"):
    """Calculate performance metrics"""
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']

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

    # Overnight-specific stats
    active_nights = df[df['pnl'] != 0]
    win_rate = (active_nights['pnl'] > 0).mean() if len(active_nights) > 0 else 0
    avg_overnight = active_nights['pnl'].mean() if len(active_nights) > 0 else 0
    avg_winner = active_nights.loc[active_nights['pnl'] > 0, 'pnl'].mean() if (active_nights['pnl'] > 0).any() else 0
    avg_loser = active_nights.loc[active_nights['pnl'] < 0, 'pnl'].mean() if (active_nights['pnl'] < 0).any() else 0

    # Annual returns
    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()

    return {
        'label': label,
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
        'avg_overnight': avg_overnight,
        'avg_winner': avg_winner,
        'avg_loser': avg_loser,
        'total_trades': len(trades_df),
        'signal_counts': results['signal_counts'],
        'circuit_breaker_events': len(results['circuit_breaker_events']),
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
    }


def calculate_combined_metrics(combined_df):
    """Calculate metrics for the combined COMPASS+NIGHTSHIFT portfolio"""
    years = len(combined_df) / 252
    initial = combined_df['combined_value'].iloc[0]
    final = combined_df['combined_value'].iloc[-1]
    cagr = (final / initial) ** (1 / years) - 1

    returns = combined_df['combined_value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)

    # Max drawdown
    running_max = combined_df['combined_value'].cummax()
    dd = (combined_df['combined_value'] - running_max) / running_max
    max_dd = dd.min()

    sharpe = cagr / volatility if volatility > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0

    return {
        'label': 'COMBINED',
        'initial': initial,
        'final_value': final,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
    }


# ============================================================================
# COMBINATION
# ============================================================================

def combine_with_compass(nightshift_df):
    """Combine NIGHTSHIFT with COMPASS equity curves"""
    # Load COMPASS daily
    compass_file = 'backtests/v8_opt_base_v8.2_daily.csv'
    if not os.path.exists(compass_file):
        compass_file = 'backtests/v8_compass_daily.csv'
    if not os.path.exists(compass_file):
        print("[WARN] COMPASS daily CSV not found, skipping combination")
        return None

    compass_df = pd.read_csv(compass_file, parse_dates=['date'])
    compass_df = compass_df.set_index('date')

    night_df = nightshift_df.set_index('date')

    # Align on common dates
    common = compass_df.index.intersection(night_df.index)
    if len(common) == 0:
        print("[WARN] No common dates between COMPASS and NIGHTSHIFT")
        return None

    combined = pd.DataFrame(index=common)
    combined['compass_value'] = compass_df.loc[common, 'value']
    combined['nightshift_value'] = night_df.loc[common, 'value']
    combined['combined_value'] = combined['compass_value'] + combined['nightshift_value']

    # Drawdowns
    for col in ['compass_value', 'nightshift_value', 'combined_value']:
        peak = combined[col].cummax()
        combined[col.replace('_value', '_dd')] = (combined[col] - peak) / peak

    combined = combined.reset_index()
    return combined


# ============================================================================
# OUTPUT
# ============================================================================

def print_results(metrics, signal_counts):
    """Print NIGHTSHIFT results"""
    m = metrics
    sc = signal_counts
    total_signals = sum(sc.values())

    print(f"\n{'='*80}")
    print(f"RESULTS - NIGHTSHIFT OVERNIGHT STRATEGY")
    print(f"{'='*80}")

    print(f"\n--- Performance ---")
    print(f"Initial capital:        ${m['initial']:>15,.0f}")
    print(f"Final value:            ${m['final_value']:>15,.0f}")
    print(f"Total return:           {m['total_return']:>15.2%}")
    print(f"CAGR:                   {m['cagr']:>15.2%}")
    print(f"Volatility (annual):    {m['volatility']:>15.2%}")

    print(f"\n--- Risk-Adjusted ---")
    print(f"Sharpe ratio:           {m['sharpe']:>15.3f}")
    print(f"Sortino ratio:          {m['sortino']:>15.3f}")
    print(f"Calmar ratio:           {m['calmar']:>15.3f}")
    print(f"Max drawdown:           {m['max_drawdown']:>15.2%}")

    print(f"\n--- Signal Distribution ---")
    print(f"RISK_ON nights:         {sc['RISK_ON']:>10,} ({sc['RISK_ON']/total_signals*100:.1f}%)")
    print(f"NEUTRAL nights:         {sc['NEUTRAL']:>10,} ({sc['NEUTRAL']/total_signals*100:.1f}%)")
    print(f"FLAT nights:            {sc['FLAT']:>10,} ({sc['FLAT']/total_signals*100:.1f}%)")
    print(f"Circuit breaker events: {m['circuit_breaker_events']:>10}")

    print(f"\n--- Overnight Trading ---")
    print(f"Total overnight trades: {m['total_trades']:>10,}")
    print(f"Win rate:               {m['win_rate']:>15.1%}")
    print(f"Avg overnight P&L:      ${m['avg_overnight']:>15,.2f}")
    print(f"Avg winner:             ${m['avg_winner']:>15,.2f}")
    print(f"Avg loser:              ${m['avg_loser']:>15,.2f}")

    print(f"\n--- Annual Returns ---")
    if len(m['annual_returns']) > 0:
        print(f"Best year:              {m['best_year']:>15.2%}")
        print(f"Worst year:             {m['worst_year']:>15.2%}")
        print(f"Positive years:         {(m['annual_returns'] > 0).sum()}/{len(m['annual_returns'])}")


def print_comparison(nightshift_m, combined_m):
    """Print side-by-side comparison"""
    # Load COMPASS metrics from the optimization results
    compass_cagr = 0.1604
    compass_sharpe = 0.770
    compass_sortino = 1.069
    compass_maxdd = -0.288
    compass_final = 4_822_626

    print(f"\n{'='*80}")
    print(f"COMPARISON: COMPASS vs NIGHTSHIFT vs COMBINED")
    print(f"{'='*80}")

    col = 15
    print(f"\n{'Metric':<22}{'COMPASS':>{col}}{'NIGHTSHIFT':>{col}}{'COMBINED':>{col}}")
    print("-" * (22 + col * 3))

    rows = [
        ('Initial Capital',  f"$100,000",           f"$50,000",                        f"$150,000"),
        ('Final Value',       f"${compass_final:,.0f}", f"${nightshift_m['final_value']:,.0f}", f"${combined_m['final_value']:,.0f}"),
        ('CAGR',              f"{compass_cagr:.2%}",   f"{nightshift_m['cagr']:.2%}",    f"{combined_m['cagr']:.2%}"),
        ('Sharpe',            f"{compass_sharpe:.3f}",  f"{nightshift_m['sharpe']:.3f}",  f"{combined_m['sharpe']:.3f}"),
        ('Sortino',           f"{compass_sortino:.3f}", f"{nightshift_m['sortino']:.3f}", f"{combined_m['sortino']:.3f}"),
        ('Max Drawdown',      f"{compass_maxdd:.1%}",   f"{nightshift_m['max_drawdown']:.1%}", f"{combined_m['max_drawdown']:.1%}"),
        ('Volatility',        f"20.85%",                f"{nightshift_m['volatility']:.2%}", f"{combined_m['volatility']:.2%}"),
    ]

    for name, c, n, cb in rows:
        print(f"{name:<22}{c:>{col}}{n:>{col}}{cb:>{col}}")


def plot_results(nightshift_results, combined_df):
    """Plot equity curves - Bloomberg dark theme"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("[WARN] matplotlib not installed, skipping chart")
        return

    night_df = nightshift_results['portfolio_values']

    fig, axes = plt.subplots(2, 1, figsize=(16, 10), gridspec_kw={'height_ratios': [3, 1]})
    fig.patch.set_facecolor('#0a0a0a')

    for ax in axes:
        ax.set_facecolor('#0a0a0a')
        for spine in ax.spines.values():
            spine.set_color('#333')
        ax.tick_params(colors='#666')
        ax.grid(True, alpha=0.15, color='#333')

    ax1, ax2 = axes

    # Equity curves
    dates_n = pd.to_datetime(night_df['date'])
    ax1.semilogy(dates_n, night_df['value'], color='#00ff41', linewidth=1.2,
                  label=f"NIGHTSHIFT ($50k)", alpha=0.9)

    if combined_df is not None:
        dates_c = pd.to_datetime(combined_df['date'])
        ax1.semilogy(dates_c, combined_df['compass_value'], color='#ff8c00', linewidth=1.2,
                      label=f"COMPASS ($100k)", alpha=0.9)
        ax1.semilogy(dates_c, combined_df['combined_value'], color='#4488ff', linewidth=1.5,
                      label=f"COMBINED ($150k)", alpha=0.9)

    ax1.set_title('NIGHTSHIFT Overnight Strategy - Equity Curves', color='#ff8c00',
                   fontsize=14, fontweight='bold', fontfamily='monospace')
    ax1.set_ylabel('Portfolio Value (log)', color='#888', fontfamily='monospace')
    ax1.legend(fontsize=10, loc='upper left', facecolor='#1a1a1a', edgecolor='#333',
               labelcolor='#ccc')

    # Drawdown
    ax2.fill_between(dates_n, night_df['drawdown'] * 100, 0, color='#00ff41', alpha=0.3)
    ax2.plot(dates_n, night_df['drawdown'] * 100, color='#00ff41', linewidth=0.5)

    if combined_df is not None:
        dates_c = pd.to_datetime(combined_df['date'])
        ax2.fill_between(dates_c, combined_df['combined_dd'] * 100, 0, color='#4488ff', alpha=0.2)
        ax2.plot(dates_c, combined_df['combined_dd'] * 100, color='#4488ff', linewidth=0.5)

    ax2.set_title('Drawdown', color='#ff8c00', fontsize=11, fontfamily='monospace')
    ax2.set_ylabel('DD %', color='#888', fontfamily='monospace')
    ax2.set_xlabel('Date', color='#888', fontfamily='monospace')

    plt.tight_layout()
    fname = 'backtests/nightshift_equity_curves.png'
    plt.savefig(fname, dpi=150, facecolor='#0a0a0a', bbox_inches='tight')
    plt.close()
    print(f"Saved: {fname}")


def save_results(results, combined_df):
    """Save all CSVs"""
    os.makedirs('backtests', exist_ok=True)

    results['portfolio_values'].to_csv('backtests/nightshift_daily.csv', index=False)
    print("Saved: backtests/nightshift_daily.csv")

    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/nightshift_trades.csv', index=False)
        print("Saved: backtests/nightshift_trades.csv")

    if combined_df is not None:
        combined_df.to_csv('backtests/nightshift_combined.csv', index=False)
        print("Saved: backtests/nightshift_combined.csv")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("  NIGHTSHIFT - Overnight Close-to-Open Strategy")
    print("  Instruments: SPY, QQQ, TLT, GLD")
    print("  Capital: $50,000 | No leverage")
    print("=" * 80)

    t_start = time.time()

    # 1. Load data
    data = download_all_data()

    # 2. Compute regime
    print("\nComputing market regime (SPY SMA200)...")
    regime = compute_regime(data['SPY'])
    risk_off_pct = (~regime.iloc[REGIME_SMA_PERIOD:]).mean() * 100
    print(f"  RISK_OFF: {risk_off_pct:.1f}% of days")

    # 3. Run backtest
    results = run_nightshift_backtest(data, regime)

    # 4. Calculate metrics
    metrics = calculate_metrics(results)

    # 5. Print results
    print_results(metrics, results['signal_counts'])

    # 6. Combine with COMPASS
    print(f"\n--- Combining with COMPASS ---")
    combined_df = combine_with_compass(results['portfolio_values'])

    if combined_df is not None:
        combined_metrics = calculate_combined_metrics(combined_df)
        print_comparison(metrics, combined_metrics)
    else:
        combined_metrics = None

    # 7. Save outputs
    print()
    save_results(results, combined_df)

    # 8. Plot
    plot_results(results, combined_df)

    elapsed = time.time() - t_start
    print(f"\nTotal time: {elapsed:.0f}s")
    print("\n" + "=" * 80)
    print("  NIGHTSHIFT BACKTEST COMPLETE")
    print("=" * 80)
