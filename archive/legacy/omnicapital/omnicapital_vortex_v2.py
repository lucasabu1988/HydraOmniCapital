"""
OmniCapital VORTEX v2 - Second attempt to beat COMPASS 16.04% CAGR
====================================================================
Learnings from v1:
- Z-score composite dilutes signal (11.07% CAGR, worse than COMPASS)
- BUT: tighter trailing reduced Max DD to -24.7% (good)
- Trailing stops at +3%/-2% created 546 stops (too many, cuts winners)

v2 Strategy: "Breakout Momentum"
- Instead of mean-reversion entry (COMPASS), target CONTINUATION entries
- Buy stocks making NEW HIGHS with strong volume confirmation
- Use price acceleration (not z-scored, raw rank) as tiebreaker
- Keep COMPASS trailing stops (+5%/-3%) — proven to work
- Add volume surge filter: only buy when recent volume > 1.5x average
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETERS
# ============================================================================

TOP_N = 40
MIN_AGE_DAYS = 63

# Signal
BREAKOUT_LOOKBACK = 60       # Is price near 60-day high?
MOM_LOOKBACK = 90            # Momentum lookback
MOM_SKIP = 3                 # Shorter skip (3d vs COMPASS 5d) — less reversal bias
VOLUME_LOOKBACK = 20         # Volume average period
VOLUME_SURGE = 1.3           # Volume must be > 1.3x average to qualify
MIN_MOMENTUM_STOCKS = 15

# Regime
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3

# Positions
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5

# Risk
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03
PORTFOLIO_STOP_LOSS = -0.15

# Recovery
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126

# Leverage
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 2.0
VOL_LOOKBACK = 20

# Costs
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

print("=" * 80)
print("OMNICAPITAL VORTEX v2 - Breakout Momentum")
print("=" * 80)
print(f"Pool: {len(BROAD_POOL)} stocks | Top-{TOP_N}")
print(f"Signal: Breakout({BREAKOUT_LOOKBACK}d) + Mom({MOM_LOOKBACK}d, skip {MOM_SKIP}d) + Volume(>{VOLUME_SURGE}x)")
print(f"Hold: {HOLD_DAYS}d | Trail: +{TRAILING_ACTIVATION:.0%}/{TRAILING_STOP_PCT:.0%}")
print()


# ============================================================================
# DATA + SHARED FUNCTIONS (identical to COMPASS)
# ============================================================================

def load_data():
    cache_file = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'
    with open(cache_file, 'rb') as f:
        price_data = pickle.load(f)
    spy_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    spy_data = pd.read_csv(spy_file, index_col=0, parse_dates=True)
    return price_data, spy_data


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
            if len(window) < 20: continue
            scores[symbol] = (window['Close'] * window['Volume']).mean()
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        annual_universe[year] = [s for s, _ in ranked[:TOP_N]]
    return annual_universe


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


def compute_vol_weights(price_data, selected, date):
    vols = {}
    for symbol in selected:
        if symbol not in price_data: continue
        df = price_data[symbol]
        if date not in df.index: continue
        idx = df.index.get_loc(date)
        if idx < VOL_LOOKBACK + 1: continue
        rets = df['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
        if len(rets) < VOL_LOOKBACK - 2: continue
        vol = rets.std() * np.sqrt(252)
        if vol > 0.01: vols[symbol] = vol
    if not vols:
        return {s: 1.0 / len(selected) for s in selected}
    raw = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw.values())
    return {s: w / total for s, w in raw.items()}


def compute_leverage(spy_data, date):
    if date not in spy_data.index: return 1.0
    idx = spy_data.index.get_loc(date)
    if idx < VOL_LOOKBACK + 1: return 1.0
    rets = spy_data['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
    if len(rets) < VOL_LOOKBACK - 2: return 1.0
    vol = rets.std() * np.sqrt(252)
    if vol < 0.01: return LEVERAGE_MAX
    return max(LEVERAGE_MIN, min(LEVERAGE_MAX, TARGET_VOL / vol))


def get_tradeable(price_data, date, first_date, annual_universe):
    eligible = set(annual_universe.get(date.year, []))
    tradeable = []
    for symbol in eligible:
        if symbol not in price_data: continue
        df = price_data[symbol]
        if date not in df.index: continue
        days_since = (date - df.index[0]).days
        if date <= first_date + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since >= MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


# ============================================================================
# VORTEX v2 SIGNAL: Breakout + Momentum + Volume
# ============================================================================

def compute_vortex_v2_scores(price_data, tradeable, date):
    """
    Score = momentum_90d (skip 3d) * breakout_proximity * volume_surge_flag

    1. Momentum: Same idea as COMPASS but with 3d skip instead of 5d
    2. Breakout proximity: How close is price to 60-day high (0 to 1)
       → Stocks at or near highs get full score, stocks far from high penalized
    3. Volume filter: Only include stocks with recent volume > 1.3x 20d average
       → Volume confirms the move is real, not just drift

    This creates a TREND-FOLLOWING signal vs COMPASS's MEAN-REVERSION signal.
    """
    scores = {}

    for symbol in tradeable:
        if symbol not in price_data: continue
        df = price_data[symbol]
        if date not in df.index: continue
        try:
            idx = df.index.get_loc(date)
        except KeyError:
            continue

        needed = max(MOM_LOOKBACK, BREAKOUT_LOOKBACK, VOLUME_LOOKBACK) + MOM_SKIP + 5
        if idx < needed: continue

        close = df['Close']
        volume = df['Volume']

        c_today = close.iloc[idx]
        c_skip = close.iloc[idx - MOM_SKIP]
        c_lookback = close.iloc[idx - MOM_LOOKBACK]

        if c_lookback <= 0 or c_skip <= 0 or c_today <= 0:
            continue

        # 1. Momentum (90d, skip 3d)
        mom = (c_skip / c_lookback) - 1.0
        skip_ret = (c_today / c_skip) - 1.0
        momentum_score = mom - skip_ret

        # 2. Breakout proximity: price / 60d high
        high_60d = close.iloc[idx - BREAKOUT_LOOKBACK:idx + 1].max()
        if high_60d <= 0:
            continue
        breakout_pct = c_today / high_60d  # 1.0 = at the high, 0.9 = 10% below

        # Only consider stocks within 5% of their 60d high
        if breakout_pct < 0.95:
            continue

        # 3. Volume confirmation
        vol_recent = volume.iloc[idx - 4:idx + 1].mean()  # last 5 days avg
        vol_avg = volume.iloc[idx - VOLUME_LOOKBACK:idx + 1].mean()  # 20d avg
        if vol_avg <= 0:
            continue
        vol_ratio = vol_recent / vol_avg

        if vol_ratio < VOLUME_SURGE:
            continue  # No volume confirmation = skip

        # Composite: momentum * breakout proximity * volume boost
        # Breakout_pct is 0.95-1.0, so normalize to 0-1 range
        breakout_bonus = (breakout_pct - 0.95) / 0.05  # 0 at 95%, 1 at 100%
        vol_bonus = min(vol_ratio / VOLUME_SURGE, 2.0)  # cap at 2x boost

        score = momentum_score * (1.0 + 0.5 * breakout_bonus) * (0.8 + 0.2 * vol_bonus)
        scores[symbol] = score

    return scores


# ============================================================================
# BACKTEST
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data):
    print("\n" + "=" * 80)
    print("RUNNING VORTEX v2 BACKTEST")
    print("=" * 80)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    regime = compute_regime(spy_data)
    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Days: {len(all_dates)}")

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []
    peak_value = float(INITIAL_CAPITAL)
    in_prot = False
    prot_stage = 0
    stop_idx = None
    risk_on_d = 0
    risk_off_d = 0
    skip_days = 0  # Days to skip after volume filter fails

    for i, date in enumerate(all_dates):
        tradeable = get_tradeable(price_data, date, first_date, annual_universe)

        pv = cash
        for sym, pos in list(positions.items()):
            if sym in price_data and date in price_data[sym].index:
                pv += pos['shares'] * price_data[sym].loc[date, 'Close']

        if pv > peak_value and not in_prot:
            peak_value = pv

        # Recovery
        if in_prot and stop_idx is not None:
            ds = i - stop_idx
            ro = bool(regime.loc[date]) if date in regime.index else True
            if prot_stage == 1 and ds >= RECOVERY_STAGE_1_DAYS and ro:
                prot_stage = 2
            if prot_stage == 2 and ds >= RECOVERY_STAGE_2_DAYS and ro:
                in_prot = False; prot_stage = 0; peak_value = pv; stop_idx = None

        dd = (pv - peak_value) / peak_value if peak_value > 0 else 0

        # Portfolio stop
        if dd <= PORTFOLIO_STOP_LOSS and not in_prot:
            stop_events.append({'date': date, 'value': pv, 'dd': dd})
            for sym in list(positions.keys()):
                if sym in price_data and date in price_data[sym].index:
                    ep = price_data[sym].loc[date, 'Close']
                    pos = positions[sym]
                    pr = pos['shares'] * ep
                    cm = pos['shares'] * COMMISSION_PER_SHARE
                    cash += pr - cm
                    pnl = (ep - pos['entry_price']) * pos['shares'] - cm
                    trades.append({'symbol': sym, 'exit_reason': 'portfolio_stop', 'pnl': pnl,
                                   'ret': pnl / (pos['entry_price'] * pos['shares'])})
                del positions[sym]
            in_prot = True; prot_stage = 1; stop_idx = i

        # Regime
        ro = bool(regime.loc[date]) if date in regime.index else True
        if ro: risk_on_d += 1
        else: risk_off_d += 1

        if in_prot:
            if prot_stage == 1: maxp = 2; lev = 0.3
            else: maxp = 3; lev = 1.0
        elif not ro:
            maxp = NUM_POSITIONS_RISK_OFF; lev = 1.0
        else:
            maxp = NUM_POSITIONS; lev = compute_leverage(spy_data, date)

        if lev > 1.0:
            cash -= MARGIN_RATE / 252 * pv * (lev - 1) / lev

        # Close positions
        for sym in list(positions.keys()):
            pos = positions[sym]
            if sym not in price_data or date not in price_data[sym].index: continue
            cp = price_data[sym].loc[date, 'Close']
            ex = None
            if i - pos['entry_idx'] >= HOLD_DAYS: ex = 'hold_expired'
            pr = (cp - pos['entry_price']) / pos['entry_price']
            if pr <= POSITION_STOP_LOSS: ex = 'position_stop'
            if cp > pos['high_price']: pos['high_price'] = cp
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                if cp <= pos['high_price'] * (1 - TRAILING_STOP_PCT): ex = 'trailing_stop'
            if sym not in tradeable: ex = 'universe_rotation'
            if ex is None and len(positions) > maxp:
                rets = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        rets[s] = (price_data[s].loc[date, 'Close'] - p['entry_price']) / p['entry_price']
                if sym == min(rets, key=rets.get): ex = 'regime_reduce'
            if ex:
                sh = pos['shares']; proc = sh * cp; cm = sh * COMMISSION_PER_SHARE
                cash += proc - cm
                pnl = (cp - pos['entry_price']) * sh - cm
                trades.append({'symbol': sym, 'exit_reason': ex, 'pnl': pnl,
                               'ret': pnl / (pos['entry_price'] * sh)})
                del positions[sym]

        # Open positions
        needed = maxp - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable) >= 5:
            scores = compute_vortex_v2_scores(price_data, tradeable, date)
            avail = {s: sc for s, sc in scores.items() if s not in positions}

            if len(avail) >= needed:
                ranked = sorted(avail.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]
                weights = compute_vol_weights(price_data, selected, date)
                eff_cap = cash * lev * 0.95
                for sym in selected:
                    if sym not in price_data or date not in price_data[sym].index: continue
                    ep = price_data[sym].loc[date, 'Close']
                    if ep <= 0: continue
                    w = weights.get(sym, 1.0 / len(selected))
                    pval = min(eff_cap * w, cash * 0.40)
                    sh = pval / ep; cost = sh * ep; cm = sh * COMMISSION_PER_SHARE
                    if cost + cm <= cash * 0.90:
                        positions[sym] = {'entry_price': ep, 'shares': sh,
                                          'entry_date': date, 'entry_idx': i, 'high_price': ep}
                        cash -= cost + cm

        portfolio_values.append({'date': date, 'value': pv, 'drawdown': dd,
                                 'leverage': lev, 'in_protection': in_prot, 'risk_on': ro})

        if i % 252 == 0 and i > 0:
            yr = i // 252
            rs = "RISK_ON" if ro else "RISK_OFF"
            ps = f" [PROT S{prot_stage}]" if in_prot else ""
            print(f"  Year {yr}: ${pv:,.0f} | DD: {dd:.1%} | Lev: {lev:.2f}x | {rs}{ps}")

    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    pv_df = pd.DataFrame(portfolio_values)
    return pv_df, trades_df, stop_events, risk_on_d, risk_off_d


# ============================================================================
# METRICS + MAIN
# ============================================================================

def calc_metrics(pv_df, trades_df, stops, ron, roff):
    df = pv_df.set_index('date')
    final = df['value'].iloc[-1]
    yrs = len(df) / 252
    cagr = (final / INITIAL_CAPITAL) ** (1 / yrs) - 1
    rets = df['value'].pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    max_dd = df['drawdown'].min()
    sharpe = cagr / vol if vol > 0 else 0
    down = rets[rets < 0]
    ds_vol = down.std() * np.sqrt(252) if len(down) > 0 else vol
    sortino = cagr / ds_vol if ds_vol > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    wr = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_t = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    exits = trades_df['exit_reason'].value_counts().to_dict() if len(trades_df) > 0 else {}
    ann = df['value'].resample('YE').last().pct_change().dropna()
    return {
        'final': final, 'cagr': cagr, 'sharpe': sharpe, 'sortino': sortino,
        'max_dd': max_dd, 'calmar': calmar, 'vol': vol, 'wr': wr,
        'avg_trade': avg_t, 'trades': len(trades_df), 'stops': len(stops),
        'exits': exits, 'best_yr': ann.max() if len(ann) > 0 else 0,
        'worst_yr': ann.min() if len(ann) > 0 else 0,
    }


if __name__ == "__main__":
    price_data, spy_data = load_data()
    print(f"Data: {len(price_data)} symbols, SPY: {len(spy_data)} days")
    annual_universe = compute_annual_top40(price_data)
    pv, tr, st, ron, roff = run_backtest(price_data, annual_universe, spy_data)
    m = calc_metrics(pv, tr, st, ron, roff)

    compass = {'cagr': 0.1604, 'sharpe': 0.770, 'max_dd': -0.288,
               'calmar': 0.557, 'final': 4_822_626, 'sortino': 0.987}

    # Build display values
    v_final = f"${m['final']:,.0f}"
    v_cagr = f"{m['cagr']:.2%}"
    v_sharpe = f"{m['sharpe']:.3f}"
    v_sortino = f"{m['sortino']:.3f}"
    v_maxdd = f"{m['max_dd']:.1%}"
    v_calmar = f"{m['calmar']:.3f}"
    v_wr = f"{m['wr']:.1%}"
    v_trades = f"{m['trades']:,}"
    v_stops = f"{m['stops']}"
    v_best = f"{m['best_yr']:.1%}"
    v_worst = f"{m['worst_yr']:.1%}"
    d_cagr = f"{m['cagr']-0.1604:+.2%}"
    d_sharpe = f"{m['sharpe']-0.770:+.3f}"
    d_sortino = f"{m['sortino']-0.987:+.3f}"
    d_maxdd = f"{m['max_dd']+0.288:+.1%}"
    d_calmar = f"{m['calmar']-0.557:+.3f}"

    print("\n" + "=" * 80)
    print("VORTEX v2 vs COMPASS v8.2")
    print("=" * 80)
    print(f"{'Metric':<20} {'COMPASS':>15} {'VORTEX v2':>15} {'Delta':>15}")
    print("-" * 65)
    print(f"{'Final Value':<20} {'$4,822,626':>15} {v_final:>15}")
    print(f"{'CAGR':<20} {'16.04%':>15} {v_cagr:>15} {d_cagr:>15}")
    print(f"{'Sharpe':<20} {'0.770':>15} {v_sharpe:>15} {d_sharpe:>15}")
    print(f"{'Sortino':<20} {'0.987':>15} {v_sortino:>15} {d_sortino:>15}")
    print(f"{'Max DD':<20} {'-28.8%':>15} {v_maxdd:>15} {d_maxdd:>15}")
    print(f"{'Calmar':<20} {'0.557':>15} {v_calmar:>15} {d_calmar:>15}")
    print(f"{'Win Rate':<20} {'55.3%':>15} {v_wr:>15}")
    print(f"{'Trades':<20} {'5,386':>15} {v_trades:>15}")
    print(f"{'Stops':<20} {'11':>15} {v_stops:>15}")
    print(f"{'Best Year':<20} {'110.2%':>15} {v_best:>15}")
    print(f"{'Worst Year':<20} {'-27.5%':>15} {v_worst:>15}")

    for reason, cnt in sorted(m['exits'].items(), key=lambda x: -x[1]):
        print(f"  {reason:25s}: {cnt:>5} ({cnt/m['trades']*100:.1f}%)")

    winner = "VORTEX v2" if m['cagr'] > 0.1604 else "COMPASS"
    print(f"\n  >>> CAGR WINNER: {winner} <<<")
    print("=" * 80)
