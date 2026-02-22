"""
Chassis Execution Analysis -- Isolate each friction factor
============================================================
Runs 4 variants of the SAME motor, changing only execution model:

  A) Close[T]   + 0 bps  = original (ideal, no friction)
  B) Close[T]   + 5 bps  = slippage only
  C) Open[T+1]  + 0 bps  = overnight gap only
  D) Open[T+1]  + 5 bps  = full realistic

All use historical T-Bill yields (to isolate execution impact only).
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import os
from typing import Dict, List
import warnings
import time as time_module
warnings.filterwarnings('ignore')

# ============================================================================
# MOTOR PARAMETERS (LOCKED)
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
LEVERAGE_MAX = 2.0
VOL_LOOKBACK = 20
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001

TBILL_YIELD_BY_ERA = {
    2000: 0.055, 2001: 0.035, 2002: 0.016, 2003: 0.010, 2004: 0.022,
    2005: 0.040, 2006: 0.048, 2007: 0.045, 2008: 0.015, 2009: 0.002,
    2010: 0.001, 2011: 0.001, 2012: 0.001, 2013: 0.001, 2014: 0.001,
    2015: 0.002, 2016: 0.005, 2017: 0.013, 2018: 0.024, 2019: 0.021,
    2020: 0.004, 2021: 0.001, 2022: 0.030, 2023: 0.052, 2024: 0.050,
    2025: 0.043, 2026: 0.040,
}

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


# ============================================================================
# DATA (Parquet cache)
# ============================================================================

def load_data():
    cache_dir = 'data_cache_parquet'
    data = {}
    for symbol in BROAD_POOL:
        pq = os.path.join(cache_dir, f'{symbol}.parquet')
        if os.path.exists(pq):
            df = pd.read_parquet(pq)
            if len(df) > 100:
                data[symbol] = df
    spy = pd.read_parquet(os.path.join(cache_dir, 'SPY.parquet'))
    return data, spy


def build_matrices(price_data, spy_data):
    all_dates = sorted(spy_data.index.tolist())
    symbols = sorted(price_data.keys())
    close_data = {}
    open_data = {}
    volume_data = {}
    for s in symbols:
        df = price_data[s]
        close_data[s] = df['Close'].reindex(all_dates)
        open_data[s] = df['Open'].reindex(all_dates)
        volume_data[s] = df['Volume'].reindex(all_dates)
    close_m = pd.DataFrame(close_data, index=all_dates)
    open_m = pd.DataFrame(open_data, index=all_dates)
    vol_m = pd.DataFrame(volume_data, index=all_dates)
    spy_close = spy_data['Close'].reindex(all_dates)
    return all_dates, close_m, open_m, vol_m, spy_close


def compute_regime(spy_close):
    sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean()
    raw = spy_close > sma200
    regime = pd.Series(index=spy_close.index, dtype=bool)
    regime.iloc[:REGIME_SMA_PERIOD] = True
    current = True
    consec = 0
    last = True
    for i in range(REGIME_SMA_PERIOD, len(raw)):
        r = raw.iloc[i]
        if pd.isna(r):
            regime.iloc[i] = current
            continue
        if r == last:
            consec += 1
        else:
            consec = 1
            last = r
        if r != current and consec >= REGIME_CONFIRM_DAYS:
            current = r
        regime.iloc[i] = current
    return regime


def compute_top40(close_m, vol_m, all_dates):
    years = sorted(set(d.year for d in all_dates))
    annual = {}
    for year in years:
        mask = np.array([d.year == year - 1 for d in all_dates])
        if mask.sum() < 20:
            continue
        dv = (close_m.iloc[mask] * vol_m.iloc[mask]).mean().dropna()
        top = dv.nlargest(min(TOP_N, len(dv))).index.tolist()
        annual[year] = top
    return annual


# ============================================================================
# BACKTEST (parameterized execution)
# ============================================================================

def run_variant(close_m, open_m, spy_close, all_dates, annual_universe,
                use_next_day_open: bool, slippage_bps: int, label: str,
                use_next_day_close: bool = False):
    """Run one variant of the backtest with specific execution model.

    Execution modes (mutually exclusive):
      use_next_day_close=True  -> MOC: signal Close[T], execute Close[T+1]
      use_next_day_open=True   -> MOO: signal Close[T], execute Open[T+1]
      both False               -> Ideal: signal Close[T], execute Close[T]
    """

    print(f"\n  [{label}] Running...")

    regime = compute_regime(spy_close)
    first_date = all_dates[0]
    symbols_list = close_m.columns.tolist()

    slip_rate = slippage_bps / 10000.0

    def exec_price(i, symbol, direction):
        if use_next_day_close and i + 1 < len(close_m):
            # MOC: execute at next day's Close
            raw = close_m.iloc[i + 1][symbol]
            if pd.isna(raw) or raw <= 0:
                raw = close_m.iloc[i][symbol]
        elif use_next_day_open and i + 1 < len(close_m):
            raw = open_m.iloc[i + 1][symbol]
            if pd.isna(raw) or raw <= 0:
                raw = close_m.iloc[i][symbol]
        else:
            raw = close_m.iloc[i][symbol]
        if pd.isna(raw) or raw <= 0:
            return None
        if direction == 'buy':
            return raw * (1.0 + slip_rate)
        else:
            return raw * (1.0 - slip_rate)

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []
    peak_value = float(INITIAL_CAPITAL)
    in_prot = False
    prot_stage = 0
    stop_day_idx = None
    risk_on_d = 0
    risk_off_d = 0

    for i, date in enumerate(all_dates):
        # Tradeable
        eligible = set(annual_universe.get(date.year, []))
        tradeable = []
        for s in eligible:
            if s not in symbols_list:
                continue
            cv = close_m.iloc[i][s]
            if pd.isna(cv):
                continue
            fv = close_m[s].first_valid_index()
            if fv is None:
                continue
            if date <= first_date + timedelta(days=30) or (date - fv).days >= MIN_AGE_DAYS:
                tradeable.append(s)

        # Portfolio value
        pv = cash
        for s, p in positions.items():
            cv = close_m.iloc[i][s]
            if not pd.isna(cv):
                pv += p['shares'] * cv

        if pv > peak_value and not in_prot:
            peak_value = pv

        # Recovery
        if in_prot and stop_day_idx is not None:
            ds = i - stop_day_idx
            ro = bool(regime.iloc[i]) if i < len(regime) else True
            if prot_stage == 1 and ds >= RECOVERY_STAGE_1_DAYS and ro:
                prot_stage = 2
            if prot_stage == 2 and ds >= RECOVERY_STAGE_2_DAYS and ro:
                in_prot = False
                prot_stage = 0
                peak_value = pv
                stop_day_idx = None

        dd = (pv - peak_value) / peak_value if peak_value > 0 else 0

        # Portfolio stop
        if dd <= PORTFOLIO_STOP_LOSS and not in_prot:
            stop_events.append(date)
            for s in list(positions.keys()):
                ep = exec_price(i, s, 'sell')
                p = positions[s]
                if ep is None:
                    cv = close_m.iloc[i][s]
                    ep = cv if not pd.isna(cv) else p['entry_price']
                cash += p['shares'] * ep - p['shares'] * COMMISSION_PER_SHARE
                pnl = (ep - p['ep']) * p['shares']
                trades.append({'pnl': pnl, 'ret': pnl / (p['ep'] * p['shares'])})
                del positions[s]
            in_prot = True
            prot_stage = 1
            stop_day_idx = i

        # Regime
        is_ro = bool(regime.iloc[i]) if i < len(regime) else True
        if is_ro:
            risk_on_d += 1
        else:
            risk_off_d += 1

        # Max pos & leverage
        if in_prot:
            max_pos = 2 if prot_stage == 1 else 3
            lev = 0.3 if prot_stage == 1 else 1.0
        elif not is_ro:
            max_pos = NUM_POSITIONS_RISK_OFF
            lev = 1.0
        else:
            max_pos = NUM_POSITIONS
            if i >= VOL_LOOKBACK + 1:
                rets = spy_close.iloc[i - VOL_LOOKBACK:i + 1].pct_change().dropna()
                if len(rets) >= VOL_LOOKBACK - 2:
                    rv = rets.std() * np.sqrt(252)
                    lev = max(LEVERAGE_MIN, min(LEVERAGE_MAX, TARGET_VOL / rv)) if rv > 0.01 else LEVERAGE_MAX
                else:
                    lev = 1.0
            else:
                lev = 1.0

        # Daily costs
        if lev > 1.0:
            cash -= MARGIN_RATE / 252 * pv * (lev - 1) / lev
        if cash > 0:
            cash += cash * (TBILL_YIELD_BY_ERA.get(date.year, 0.035) / 252)

        # Exits
        for s in list(positions.keys()):
            p = positions[s]
            cv = close_m.iloc[i][s]
            if pd.isna(cv):
                continue
            exit_r = None
            if i - p['eidx'] >= HOLD_DAYS:
                exit_r = 'hold'
            pr = (cv - p['ep']) / p['ep']
            if pr <= POSITION_STOP_LOSS:
                exit_r = 'pos_stop'
            if cv > p['high']:
                p['high'] = cv
            if p['high'] > p['ep'] * (1 + TRAILING_ACTIVATION):
                if cv <= p['high'] * (1 - TRAILING_STOP_PCT):
                    exit_r = 'trail'
            if s not in tradeable:
                exit_r = 'univ'
            if exit_r is None and len(positions) > max_pos:
                prs = {}
                for s2, p2 in positions.items():
                    cv2 = close_m.iloc[i][s2]
                    if not pd.isna(cv2):
                        prs[s2] = (cv2 - p2['ep']) / p2['ep']
                if prs and s == min(prs, key=prs.get):
                    exit_r = 'reduce'
            if exit_r:
                ep = exec_price(i, s, 'sell')
                if ep is None:
                    ep = cv
                cash += p['shares'] * ep - p['shares'] * COMMISSION_PER_SHARE
                pnl = (ep - p['ep']) * p['shares']
                trades.append({'pnl': pnl, 'ret': pnl / (p['ep'] * p['shares'])})
                del positions[s]

        # Entries
        needed = max_pos - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable) >= 5:
            scores = {}
            for s in tradeable:
                if s not in symbols_list or i < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
                    continue
                c0 = close_m.iloc[i][s]
                c5 = close_m.iloc[i - MOMENTUM_SKIP][s]
                c90 = close_m.iloc[i - MOMENTUM_LOOKBACK][s]
                if pd.isna(c0) or pd.isna(c5) or pd.isna(c90) or c90 <= 0 or c5 <= 0:
                    continue
                scores[s] = (c5 / c90 - 1) - (c0 / c5 - 1)
            avail = {s: sc for s, sc in scores.items() if s not in positions}
            if len(avail) >= needed:
                sel = [s for s, _ in sorted(avail.items(), key=lambda x: -x[1])[:needed]]
                # Inverse vol weights
                vols = {}
                for s in sel:
                    if i < VOL_LOOKBACK + 1:
                        continue
                    r = close_m[s].iloc[i - VOL_LOOKBACK:i + 1].pct_change().dropna()
                    if len(r) >= VOL_LOOKBACK - 2:
                        v = r.std() * np.sqrt(252)
                        if v > 0.01:
                            vols[s] = v
                if vols:
                    rw = {s: 1.0 / v for s, v in vols.items()}
                    tw = sum(rw.values())
                    wts = {s: w / tw for s, w in rw.items()}
                else:
                    wts = {s: 1.0 / len(sel) for s in sel}

                eff_cap = cash * lev * 0.95
                for s in sel:
                    ep = exec_price(i, s, 'buy')
                    if ep is None:
                        continue
                    w = wts.get(s, 1.0 / len(sel))
                    pv_s = min(eff_cap * w, cash * 0.40)
                    sh = pv_s / ep
                    cost = sh * ep + sh * COMMISSION_PER_SHARE
                    if cost <= cash * 0.90:
                        positions[s] = {'ep': ep, 'shares': sh, 'eidx': i, 'high': ep}
                        cash -= cost

        portfolio_values.append(pv)

    # Metrics
    pv_series = pd.Series(portfolio_values, index=all_dates)
    final = pv_series.iloc[-1]
    years = len(pv_series) / 252
    cagr = (final / INITIAL_CAPITAL) ** (1 / years) - 1
    rets = pv_series.pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    sharpe = cagr / vol if vol > 0 else 0
    peak_s = pv_series.expanding().max()
    max_dd = ((pv_series - peak_s) / peak_s).min()
    trades_df = pd.DataFrame(trades)
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0

    return {
        'label': label,
        'final': final,
        'cagr': cagr,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'vol': vol,
        'trades': len(trades_df),
        'win_rate': win_rate,
        'stops': len(stop_events),
        'pv_series': pv_series,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("CHASSIS EXECUTION ANALYSIS -- Isolating Friction Factors")
    print("=" * 80)

    t0 = time_module.time()

    # Load data
    print("\n[1/3] Loading data (Parquet cache)...")
    price_data, spy_data = load_data()
    print(f"  Loaded {len(price_data)} symbols + SPY")

    print("[2/3] Building aligned matrices...")
    all_dates, close_m, open_m, vol_m, spy_close = build_matrices(price_data, spy_data)
    print(f"  Matrix: {len(all_dates)} dates x {len(close_m.columns)} symbols")

    print("[3/3] Computing annual Top-40...")
    annual = compute_top40(close_m, vol_m, all_dates)

    # Run 4 variants
    print("\n" + "=" * 80)
    print("RUNNING 4 EXECUTION VARIANTS")
    print("=" * 80)

    # (use_next_day_open, slippage_bps, label, use_next_day_close)
    variants = [
        (False, 0,  "A: Close[T] + 0bps (ideal)",        False),
        (False, 5,  "B: Close[T] + 5bps (slip only)",    False),
        (True,  0,  "C: Open[T+1] + 0bps (gap only)",    False),
        (True,  5,  "D: Open[T+1] + 5bps (market order)",False),
        (False, 0,  "E: Close[T+1] + 0bps (MOC ideal)",  True),
        (False, 2,  "F: Close[T+1] + 2bps (MOC real)",   True),
        (False, 5,  "G: Close[T+1] + 5bps (MOC worst)",  True),
    ]

    results = []
    for use_open, slip, label, use_close_t1 in variants:
        r = run_variant(close_m, open_m, spy_close, all_dates, annual,
                       use_next_day_open=use_open, slippage_bps=slip, label=label,
                       use_next_day_close=use_close_t1)
        results.append(r)
        print(f"    -> CAGR: {r['cagr']:.2%} | Sharpe: {r['sharpe']:.3f} | "
              f"MaxDD: {r['max_dd']:.1%} | Final: ${r['final']:,.0f}")

    t_total = time_module.time() - t0

    # Summary
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY -- Execution Impact Decomposition")
    print("=" * 80)

    print(f"\n  {'Variant':<35} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} {'Final':>14} {'WinRate':>8}")
    print(f"  {'-'*85}")
    for r in results:
        print(f"  {r['label']:<35} {r['cagr']:>7.2%} {r['sharpe']:>8.3f} "
              f"{r['max_dd']:>7.1%} ${r['final']:>12,.0f} {r['win_rate']:>7.1%}")

    # Decomposition
    A = results[0]  # ideal Close[T] + 0bps
    B = results[1]  # Close[T] + 5bps
    C = results[2]  # Open[T+1] + 0bps
    D = results[3]  # Open[T+1] + 5bps (market order)
    E = results[4]  # Close[T+1] + 0bps (MOC ideal)
    F = results[5]  # Close[T+1] + 2bps (MOC realistic)
    G = results[6]  # Close[T+1] + 5bps (MOC worst)

    print(f"\n  {'='*60}")
    print(f"  IMPACT DECOMPOSITION (vs ideal baseline A)")
    print(f"  {'='*60}")
    print(f"  Slippage 5bps (Close):     {B['cagr'] - A['cagr']:>+7.2%} CAGR")
    print(f"  Overnight gap (Open[T+1]): {C['cagr'] - A['cagr']:>+7.2%} CAGR")
    print(f"  Market order (gap+5bps):   {D['cagr'] - A['cagr']:>+7.2%} CAGR")
    print(f"  MOC ideal (0bps):          {E['cagr'] - A['cagr']:>+7.2%} CAGR")
    print(f"  MOC realistic (2bps):      {F['cagr'] - A['cagr']:>+7.2%} CAGR")
    print(f"  MOC worst (5bps):          {G['cagr'] - A['cagr']:>+7.2%} CAGR")

    print(f"\n  {'='*60}")
    print(f"  EXECUTION STRATEGY COMPARISON")
    print(f"  {'='*60}")
    print(f"  {'Strategy':<30} {'CAGR':>8} {'Sharpe':>8} {'vs Ideal':>10}")
    print(f"  {'-'*58}")
    print(f"  {'Market order (Open+5bps)':<30} {D['cagr']:>7.2%} {D['sharpe']:>8.3f} {D['cagr']-A['cagr']:>+9.2%}")
    print(f"  {'MOC order (Close+2bps)':<30} {F['cagr']:>7.2%} {F['sharpe']:>8.3f} {F['cagr']-A['cagr']:>+9.2%}")
    print(f"  {'MOC saves vs market order':<30} {F['cagr']-D['cagr']:>+7.2%} {F['sharpe']-D['sharpe']:>+8.3f}")

    print(f"\n  Total time: {t_total:.0f}s ({t_total/len(variants):.0f}s per variant)")

    # Save comparison CSV
    comp = pd.DataFrame([{
        'variant': r['label'],
        'cagr': round(r['cagr'] * 100, 2),
        'sharpe': round(r['sharpe'], 3),
        'max_dd': round(r['max_dd'] * 100, 1),
        'final_value': round(r['final'], 0),
        'trades': r['trades'],
        'win_rate': round(r['win_rate'] * 100, 1),
        'stops': r['stops'],
    } for r in results])

    os.makedirs('backtests', exist_ok=True)
    comp.to_csv('backtests/chassis_execution_comparison.csv', index=False)
    print(f"\n  Saved: backtests/chassis_execution_comparison.csv")

    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
